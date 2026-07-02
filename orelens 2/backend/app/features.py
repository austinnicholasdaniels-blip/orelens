"""
Site features: search and on-demand ticker adds.
"""
from __future__ import annotations
import logging
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, or_
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .services import yahoo

log = logging.getLogger("orelens.features")
router = APIRouter()


# ----------------------------------------------------------------- search
@router.get("/api/search")
def search(q: str, db: Session = Depends(get_db)):
    q = q.strip()
    if not q:
        return []
    rows = db.execute(select(models.Company).where(or_(
        models.Company.ticker.ilike(f"{q}%"),
        models.Company.name.ilike(f"%{q}%"),
    )).limit(8)).scalars().all()
    return [{"ticker": c.ticker, "name": c.name, "exchange": c.exchange,
             "commodity": c.commodity} for c in rows]


class AddTickerBody(BaseModel):
    ticker: str
    exchange: str = "TSXV"           # TSX | TSXV | CSE | ASX
    name: str | None = None
    commodity: str = "Gold"


@router.post("/api/admin/add-ticker")
async def add_ticker(body: AddTickerBody, db: Session = Depends(get_db)):
    """Add any listed junior on demand: creates the company and pulls prices,
    shares outstanding, and quarterly cash/burn from Yahoo (with the same
    TSX/TSXV self-heal as the universe loader)."""
    tick = body.ticker.upper().strip()
    c = db.execute(select(models.Company).where(
        models.Company.ticker == tick)).scalar_one_or_none()
    if not c:
        c = models.Company(ticker=tick, exchange=body.exchange.upper(),
                           name=body.name or tick, commodity=body.commodity,
                           jurisdiction="", jurisdiction_tier="Tier 1",
                           project_name="", shares_outstanding=0)
        db.add(c)
        db.flush()

    data = await run_in_threadpool(yahoo.fetch_company_data, tick, c.exchange)
    if not data["prices"] and c.exchange in ("TSX", "TSXV"):
        alt = "TSX" if c.exchange == "TSXV" else "TSXV"
        alt_data = await run_in_threadpool(yahoo.fetch_company_data, tick, alt)
        if alt_data["prices"]:
            data, c.exchange = alt_data, alt
    if not data["prices"]:
        db.rollback()
        return {"error": f"No market data found for {tick} on TSX/TSXV/CSE/ASX — check the symbol."}

    if data["shares_outstanding"]:
        c.shares_outstanding = data["shares_outstanding"]
    have = {p.day for p in db.execute(select(models.DailyPrice).where(
        models.DailyPrice.company_id == c.id)).scalars()}
    for row in data["prices"]:
        if row["date"] not in have:
            db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                     close=row["close"], volume=row["volume"]))
    if data["cash"] and data["monthly_burn"]:
        if not db.execute(select(models.FinancialSnapshot).where(
                models.FinancialSnapshot.company_id == c.id)).scalars().first():
            db.add(models.FinancialSnapshot(
                company_id=c.id, as_of=date.today(), cash=data["cash"],
                monthly_burn=data["monthly_burn"],
                source_filing="Yahoo Finance quarterly statements"))
    db.commit()
    from .jobs.nightly import run_grades
    run_grades(db)
    return {"added": tick, "exchange": c.exchange,
            "price_days": len(data["prices"])}


# ------------------------------------------------- filing extraction (LLM)
import httpx as _httpx


class ExtractBody(BaseModel):
    ticker: str
    url: str          # direct link to the MD&A / financial statements PDF
    replace_warrants: bool = True


@router.post("/api/admin/extract-filing")
async def extract_filing(body: ExtractBody, db: Session = Depends(get_db)):
    """Fetch a filing (PDF or EDGAR HTML exhibit), extract cash / burn /
    warrant & option tables with the Anthropic API, store them with the
    filing URL as source, and re-grade."""
    from .services import ingest
    from sqlalchemy import delete as _delete
    from datetime import datetime as _dt

    c = db.execute(select(models.Company).where(
        models.Company.ticker == body.ticker.upper())).scalar_one_or_none()
    if not c:
        return {"error": "unknown ticker — add it first"}

    headers = {"User-Agent": "OreLens research tool (orelens-api.onrender.com)"}
    try:
        async with _httpx.AsyncClient(timeout=60, follow_redirects=True,
                                      headers=headers) as client:
            r = await client.get(body.url)
            r.raise_for_status()
            raw = r.content
            ctype = r.headers.get("content-type", "")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not fetch filing: {exc}"}

    # Accept both PDF filings (company sites, SEDAR+) and HTML exhibits (EDGAR 6-K)
    if raw[:5] == b"%PDF-" or "pdf" in ctype:
        try:
            text = await run_in_threadpool(ingest.pdf_to_text, raw)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"could not read PDF: {exc}"}
    else:
        import re as _re
        html = raw.decode("utf-8", errors="ignore")
        html = _re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=_re.I)
        html = _re.sub(r"<br\s*/?>|</(p|tr|div|h[1-6]|li)>", "\n", html, flags=_re.I)
        html = _re.sub(r"</t[dh]>", " | ", html, flags=_re.I)
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"&nbsp;?", " ", text)
        text = _re.sub(r"[ \t]{2,}", " ", text)
    if len(text) < 500:
        return {"error": "filing produced almost no text — may be a scanned image"}

    result = await ingest.extract_capital_structure(text)
    if not result:
        return {"error": "extraction failed — check ANTHROPIC_API_KEY / try again"}

    stored = {"cash": None, "monthly_burn": None, "warrants": 0, "options": 0}
    src = f"LLM extraction: {body.url}"[:240]

    if result.get("cash_and_equivalents") and result.get("monthly_burn_rate"):
        db.add(models.FinancialSnapshot(
            company_id=c.id, as_of=date.today(),
            cash=float(result["cash_and_equivalents"]),
            monthly_burn=float(result["monthly_burn_rate"]),
            source_filing=src))
        stored["cash"] = float(result["cash_and_equivalents"])
        stored["monthly_burn"] = float(result["monthly_burn_rate"])

    def _tranches(items, kind):
        n = 0
        for t in items or []:
            try:
                db.add(models.WarrantTranche(
                    company_id=c.id, kind=kind,
                    strike=float(t["strike_price"]),
                    expiry=_dt.strptime(str(t["expiry_date"]), "%Y-%m-%d").date(),
                    quantity=float(t["quantity_outstanding"]),
                    source_filing=src))
                n += 1
            except (KeyError, TypeError, ValueError):
                continue
        return n

    if body.replace_warrants and (result.get("warrants") or result.get("options")):
        db.execute(_delete(models.WarrantTranche).where(
            models.WarrantTranche.company_id == c.id))
    stored["warrants"] = _tranches(result.get("warrants"), "warrant")
    stored["options"] = _tranches(result.get("options"), "option")
    db.commit()

    from .jobs.nightly import run_grades
    run_grades(db)
    g = db.execute(select(models.DilutionGrade).where(
        models.DilutionGrade.company_id == c.id).order_by(
        models.DilutionGrade.day.desc())).scalars().first()
    return {"ticker": c.ticker, "extracted": stored,
            "new_grade": g and {"grade": g.grade,
                                "overhang_pct_float": round(g.overhang_ratio * 100, 1),
                                "rationale": g.rationale}}
