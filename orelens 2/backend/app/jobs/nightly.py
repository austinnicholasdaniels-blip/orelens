"""
Nightly pipeline — runs every weeknight at 23:00 EST.

Trigger it either via the in-process APScheduler (started in main.py) or an
external cron / GitHub Action hitting POST /jobs/nightly (both are wired).

Order matters: prices -> filings -> newswires -> grades.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import (
    Company, DailyPrice, FinancialSnapshot, WarrantTranche,
    PressRelease, DrillResult, DrillProgram, DilutionGrade, SharesHistory,
)
from ..services import ingest, drill_parser
from ..services import financing as _fin
from ..services import promotion as _promo
from ..models import Promotion
from ..models import Financing
from ..services.grading import GradeInput, TrancheIn, compute_grade

log = logging.getLogger("orelens.nightly")


async def sync_prices(db: Session) -> None:
    from starlette.concurrency import run_in_threadpool
    from ..services import yahoo
    for c in db.execute(select(Company)).scalars():
        data = await run_in_threadpool(yahoo.fetch_company_data, c.ticker, c.exchange, "5d")
        last = data["prices"][-1] if data["prices"] else None
        quote = {"close": last["close"], "volume": last["volume"],
                 "shares_outstanding": data["shares_outstanding"]} if last else None
        if not quote:
            continue
        exists = db.execute(
            select(DailyPrice).where(DailyPrice.company_id == c.id,
                                     DailyPrice.day == date.today())
        ).scalar_one_or_none()
        if exists:
            exists.close, exists.volume = quote["close"], quote["volume"] or 0
        else:
            db.add(DailyPrice(company_id=c.id, day=date.today(),
                              close=quote["close"], volume=quote["volume"] or 0))
        if quote.get("shares_outstanding"):
            c.shares_outstanding = quote["shares_outstanding"]
        for ch in data.get("cash_history", []):
            exists_fs = db.execute(select(FinancialSnapshot).where(
                FinancialSnapshot.company_id == c.id,
                FinancialSnapshot.as_of == ch["as_of"])).scalars().first()
            if not exists_fs:
                db.add(FinancialSnapshot(
                    company_id=c.id, as_of=ch["as_of"], cash=ch["cash"],
                    monthly_burn=data.get("monthly_burn") or 0.0,
                    source_filing="Yahoo quarterly balance sheet"))
        for sh in data.get("shares_history", []):
            if not db.execute(select(SharesHistory).where(
                    SharesHistory.company_id == c.id,
                    SharesHistory.as_of == sh["as_of"])).scalar_one_or_none():
                db.add(SharesHistory(company_id=c.id,
                                     as_of=sh["as_of"], shares=sh["shares"]))
    db.commit()


def _upsert_financing(db: Session, company_id: int, published, headline: str,
                      url: str, f: dict) -> None:
    from datetime import timedelta as _td
    pub_date = published.date() if hasattr(published, "date") else published
    if f["is_close"]:
        # try to close out a matching open announcement
        open_fin = db.execute(
            select(Financing).where(Financing.company_id == company_id,
                                    Financing.closed.is_(False))
            .order_by(Financing.announced.desc()).limit(1)).scalar_one_or_none()
        if open_fin:
            open_fin.closed = True
            open_fin.close_date = pub_date
            open_fin.hold_expiry = pub_date + _td(days=122)  # ~4 months + 1 day
            open_fin.amount = f["amount"] or open_fin.amount
            open_fin.price_per_unit = f["price_per_unit"] or open_fin.price_per_unit
            open_fin.warrant_strike = f["warrant_strike"] or open_fin.warrant_strike
            return
        # syndication/dup guard for closes: same company + same amount = same deal
        for ex in db.execute(select(Financing).where(
                Financing.company_id == company_id,
                Financing.closed.is_(True))).scalars():
            if f["amount"] and ex.amount and abs(f["amount"] - ex.amount) < 0.01 * ex.amount + 1:
                return
            if ex.close_date and abs((ex.close_date - pub_date).days) <= 5:
                return
        db.add(Financing(company_id=company_id, announced=pub_date, closed=True,
                         close_date=pub_date, hold_expiry=pub_date + _td(days=122),
                         amount=f["amount"], price_per_unit=f["price_per_unit"],
                         warrant_strike=f["warrant_strike"], kind=f["kind"],
                         headline=headline, source_url=url))
    else:
        dup = db.execute(
            select(Financing).where(Financing.company_id == company_id,
                                    Financing.announced == pub_date)).scalars().first()
        if not dup:
            db.add(Financing(company_id=company_id, announced=pub_date,
                             amount=f["amount"], price_per_unit=f["price_per_unit"],
                             warrant_strike=f["warrant_strike"], kind=f["kind"],
                             headline=headline, source_url=url))


def _upsert_promotion(db: Session, company_id: int, published, headline: str,
                      url: str, p: dict) -> None:
    from datetime import timedelta as _td
    pub_date = published.date() if hasattr(published, "date") else published
    ends = (pub_date + _td(days=int(p["term_months"] * 30.4))
            if p.get("term_months") else None)
    # syndication guard: the same engagement gets republished by multiple
    # outlets on different days. Same company + (same firm OR same amount OR
    # announced within 21 days) = the same deal, not a new one.
    for ex in db.execute(select(Promotion).where(
            Promotion.company_id == company_id)).scalars():
        same_firm = bool(p.get("firm") and ex.firm and
                         p["firm"].lower() == ex.firm.lower())
        same_amount = bool(p.get("amount") and ex.amount and
                           abs(p["amount"] - ex.amount) < 0.01 * ex.amount + 1)
        close_dates = abs((ex.announced - pub_date).days) <= 21
        if same_firm or same_amount or close_dates:
            ex.firm = ex.firm or p.get("firm")
            ex.amount = ex.amount or p.get("amount")
            ex.monthly_fee = ex.monthly_fee or p.get("monthly_fee")
            if not ex.term_months and p.get("term_months"):
                ex.term_months = p["term_months"]
                ex.ends = ex.announced + _td(days=int(p["term_months"] * 30.4))
            return
    db.add(Promotion(company_id=company_id, announced=pub_date,
                     firm=p.get("firm"), amount=p.get("amount"),
                     monthly_fee=p.get("monthly_fee"),
                     term_months=p.get("term_months"), ends=ends,
                     headline=headline, source_url=url))


async def sync_newswires(db: Session) -> dict:
    import re as _re
    tickers = {c.ticker: c.id for c in db.execute(select(Company)).scalars()}
    names = {c.name.lower(): c.id for c in db.execute(select(Company)).scalars()}
    wire_items = ingest.fetch_wire_items()
    stored = 0
    for item in wire_items:
        if db.execute(select(PressRelease).where(PressRelease.url == item["url"])).scalar_one_or_none():
            continue
        text = f"{item['headline']} {item['summary']}"
        # only match a ticker inside a real exchange parenthetical, e.g.
        # "(TSXV: DV)" / "(TSX: SKE)" / "(CSE: API)" - avoids 2-letter false hits
        company_id = None
        for t, cid in tickers.items():
            if _re.search(
                    rf"\((?:TSX|TSXV|TSX-V|CSE|ASX|NYSE|OTCQ[BX])\s*:\s*{_re.escape(t)}\b",
                    text):
                company_id = cid
                break
        if not company_id:
            company_id = next(
                (cid for nm, cid in names.items() if nm in text.lower()), None)

        pr = PressRelease(
            company_id=company_id, published=item["published"],
            headline=item["headline"][:400], url=item["url"][:400],
            wire=item["wire"], body=item["summary"],
            is_drill_start=drill_parser.is_drill_start(text),
        )
        db.add(pr)
        stored += 1

        if company_id:
            f = _fin.parse_financing(text)
            if f:
                _upsert_financing(db, company_id, item["published"],
                                  item["headline"][:400], item["url"][:400], f)
            pmo = _promo.parse_promotion(text)
            if pmo:
                _upsert_promotion(db, company_id, item["published"],
                                  item["headline"][:400], item["url"][:400], pmo)
        if company_id:
            program = db.execute(
                select(DrillProgram).where(DrillProgram.company_id == company_id,
                                           DrillProgram.active.is_(True))
            ).scalars().first()
            for i in drill_parser.parse_intercepts(text):
                db.add(DrillResult(
                    company_id=company_id,
                    program_id=program.id if program else None,
                    published=item["published"], hole_id=i.hole_id,
                    commodity=i.commodity, grade=i.grade, unit=i.unit,
                    width_m=i.width_m, grade_meters=i.grade_meters,
                    above_benchmark=i.above_benchmark,
                    source_url=item["url"][:400], raw_sentence=i.raw_sentence[:2000],
                ))
    db.commit()
    return {"feed_items": len(wire_items), "new_stored": stored}


async def sync_filings(db: Session) -> None:
    """For each issuer: pull new MD&A / interim financials, extract cash, burn,
    and the warrant table via the LLM pass, and persist a snapshot."""
    log.info("filings sync: wire your SEDAR+ feed source here")


def run_grades(db: Session) -> None:
    today = date.today()
    for c in db.execute(select(Company)).scalars():
        fin = db.execute(
            select(FinancialSnapshot).where(FinancialSnapshot.company_id == c.id)
            .order_by(FinancialSnapshot.as_of.desc()).limit(1)
        ).scalar_one_or_none()
        price = db.execute(
            select(DailyPrice).where(DailyPrice.company_id == c.id)
            .order_by(DailyPrice.day.desc()).limit(1)
        ).scalar_one_or_none()
        if not fin or not price:
            continue
        prog = db.execute(
            select(DrillProgram).where(DrillProgram.company_id == c.id,
                                       DrillProgram.active.is_(True))
        ).scalars().first()
        tranches = [
            TrancheIn(strike=t.strike, quantity=t.quantity, expiry=t.expiry,
                      hold_unlock=t.hold_unlock)
            for t in db.execute(select(WarrantTranche).where(
                WarrantTranche.company_id == c.id)).scalars()
        ]
        res = compute_grade(GradeInput(
            cash=fin.cash, monthly_burn=fin.monthly_burn, price=price.close,
            shares_outstanding=c.shares_outstanding, tranches=tranches,
            planned_holes=prog.planned_holes if prog else 0,
            avg_depth_m=prog.avg_depth_m if prog else 0,
            cost_per_meter=prog.cost_per_meter if prog else 250.0,
        ))
        existing = db.execute(
            select(DilutionGrade).where(DilutionGrade.company_id == c.id,
                                        DilutionGrade.day == today)
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            db.flush()
        db.add(DilutionGrade(
            company_id=c.id, day=today, grade=res.grade,
            cash_runway_m=res.cash_runway_m, adjusted_runway_m=res.adjusted_runway_m,
            upcoming_drill_cost=res.upcoming_drill_cost,
            itm_warrant_cash=res.itm_warrant_cash, overhang_ratio=res.overhang_ratio,
            unlock_risk_pct_float=res.unlock_risk_pct_float, rationale=res.rationale,
        ))
    db.commit()


async def run_nightly() -> dict:
    started = datetime.utcnow()
    db = SessionLocal()
    try:
        await sync_prices(db)
        await sync_filings(db)
        wire_stats = await sync_newswires(db)
        run_grades(db)
    finally:
        db.close()
    return {"started": started.isoformat(), "finished": datetime.utcnow().isoformat(),
            "newswire": wire_stats}


if __name__ == "__main__":
    asyncio.run(run_nightly())
