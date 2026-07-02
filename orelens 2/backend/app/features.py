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

