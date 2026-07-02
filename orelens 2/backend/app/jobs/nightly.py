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
        for sh in data.get("shares_history", []):
            if not db.execute(select(SharesHistory).where(
                    SharesHistory.company_id == c.id,
                    SharesHistory.as_of == sh["as_of"])).scalar_one_or_none():
                db.add(SharesHistory(company_id=c.id,
                                     as_of=sh["as_of"], shares=sh["shares"]))
    db.commit()


async def sync_newswires(db: Session) -> None:
    tickers = {c.ticker: c.id for c in db.execute(select(Company)).scalars()}
    names = {c.name.lower(): c.id for c in db.execute(select(Company)).scalars()}
    for item in ingest.fetch_wire_items():
        if db.execute(select(PressRelease).where(PressRelease.url == item["url"])).scalar_one_or_none():
            continue
        text = f"{item['headline']} {item['summary']}"
        company_id = next(
            (cid for t, cid in tickers.items() if f"({t}" in text or f"{t}:" in text),
            None,
        ) or next((cid for n, cid in names.items() if n in text.lower()), None)

        pr = PressRelease(
            company_id=company_id, published=item["published"],
            headline=item["headline"][:400], url=item["url"][:400],
            wire=item["wire"], body=item["summary"],
            is_drill_start=drill_parser.is_drill_start(text),
        )
        db.add(pr)

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


async def sync_filings(db: Session) -> None:
    """For each issuer: pull new MD&A / interim financials, extract cash, burn,
    and the warrant table via the LLM pass, and persist a snapshot."""
    # SEDAR+ access is issuer-by-issuer (RSS or commercial mirror) — plug the
    # per-issuer feed URL into Company metadata when you build the universe.
    # EDGAR path shown in ingest.fetch_edgar_recent for dual-listed names.
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
        await sync_newswires(db)
        run_grades(db)
    finally:
        db.close()
    return {"started": started.isoformat(), "finished": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    asyncio.run(run_nightly())
