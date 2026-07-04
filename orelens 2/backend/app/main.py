from contextlib import asynccontextmanager
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from . import models
from .jobs.nightly import run_nightly
from .services import scanners
from .services.drill_parser import percentile_rank
from . import universe as universe_module
from . import features as features_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    # First boot on a fresh database: load the demo universe so the UI isn't empty.
    import os
    if os.environ.get("SEED_ON_START") == "1":
        from sqlalchemy.orm import Session as _S
        with _S(engine) as s:
            empty = s.execute(select(models.Company).limit(1)).first() is None
        if empty:
            from .seed import seed
            seed()
    scheduler = AsyncIOScheduler()
    # every weeknight 23:00 EST (America/New_York handles DST)
    scheduler.add_job(run_nightly, CronTrigger(
        day_of_week="mon-fri", hour=23, minute=0, timezone="America/New_York"))
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="OreLens API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.include_router(universe_module.router)
app.include_router(features_module.router)


@app.get("/api/scanners/active-drills")
def active_drills(commodity: str | None = None, tier: str | None = None,
                  db: Session = Depends(get_db)):
    return scanners.scan_active_drills(db, commodity, tier)


@app.get("/api/scanners/high-grade-breakouts")
def high_grade(commodity: str | None = None, tier: str | None = None,
               db: Session = Depends(get_db)):
    return scanners.scan_high_grade_breakouts(db, commodity=commodity, tier=tier)


@app.get("/api/scanners/value-momentum")
def value_momentum(commodity: str | None = None, tier: str | None = None,
                   db: Session = Depends(get_db)):
    return scanners.scan_value_momentum(db, commodity, tier)


@app.get("/api/tickers/{ticker}")
def ticker_profile(ticker: str, db: Session = Depends(get_db)):
    c = db.execute(select(models.Company).where(
        models.Company.ticker == ticker.upper())).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "unknown ticker")

    prices = db.execute(
        select(models.DailyPrice).where(models.DailyPrice.company_id == c.id)
        .order_by(models.DailyPrice.day)
    ).scalars().all()
    grade = db.execute(
        select(models.DilutionGrade).where(models.DilutionGrade.company_id == c.id)
        .order_by(desc(models.DilutionGrade.day)).limit(1)
    ).scalar_one_or_none()
    fin = db.execute(
        select(models.FinancialSnapshot).where(models.FinancialSnapshot.company_id == c.id)
        .order_by(desc(models.FinancialSnapshot.as_of)).limit(1)
    ).scalar_one_or_none()
    warrants = db.execute(
        select(models.WarrantTranche).where(models.WarrantTranche.company_id == c.id)
        .order_by(models.WarrantTranche.strike)
    ).scalars().all()
    results = db.execute(
        select(models.DrillResult).where(models.DrillResult.company_id == c.id)
        .order_by(models.DrillResult.published)
    ).scalars().all()
    program = db.execute(
        select(models.DrillProgram).where(models.DrillProgram.company_id == c.id,
                                          models.DrillProgram.active.is_(True))
    ).scalars().first()
    promos = db.execute(
        select(models.Promotion).where(models.Promotion.company_id == c.id)
        .order_by(desc(models.Promotion.announced)).limit(10)
    ).scalars().all()
    cash_snaps = db.execute(
        select(models.FinancialSnapshot).where(models.FinancialSnapshot.company_id == c.id)
        .order_by(models.FinancialSnapshot.as_of)
    ).scalars().all()
    fins = db.execute(
        select(models.Financing).where(models.Financing.company_id == c.id)
        .order_by(desc(models.Financing.announced)).limit(10)
    ).scalars().all()
    shares_hist = db.execute(
        select(models.SharesHistory).where(models.SharesHistory.company_id == c.id)
        .order_by(models.SharesHistory.as_of)
    ).scalars().all()

    # jurisdiction percentile for the best recent intercept (12-month window)
    comparison = None
    if results:
        best = max(results, key=lambda r: r.grade_meters)
        peer_pop = db.execute(
            select(models.DrillResult.grade_meters)
            .join(models.Company, models.Company.id == models.DrillResult.company_id)
            .where(models.Company.jurisdiction == c.jurisdiction,
                   models.DrillResult.commodity == best.commodity,
                   models.DrillResult.published >= (date.today() - timedelta(days=365)))
        ).scalars().all()
        pct = percentile_rank(best.grade_meters, peer_pop)
        comparison = (
            f"This intercept of {best.grade:g} {best.unit} {best.commodity} over "
            f"{best.width_m:g} m ({best.grade_meters:g} gram-meters) is in the top "
            f"{max(1, round(100 - pct)):g}% of all {best.commodity.lower()} intercepts "
            f"tracked in {c.jurisdiction} over the last 12 months."
        )

    holes = {r.hole_id for r in results if r.hole_id}
    hits = {r.hole_id for r in results if r.hole_id and r.hit}
    fully_diluted = c.shares_outstanding + sum(w.quantity for w in warrants)

    price = prices[-1].close if prices else None
    itm_cash = sum(w.quantity * w.strike for w in warrants
                   if price and w.strike < price and w.expiry >= date.today())

    return {
        "company": {
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction": c.jurisdiction,
            "jurisdiction_tier": c.jurisdiction_tier, "project": c.project_name,
        },
        "prices": [{"time": p.day.isoformat(), "value": p.close, "volume": p.volume}
                   for p in prices],
        "grade": grade and {
            "grade": grade.grade, "cash_runway_m": grade.cash_runway_m,
            "adjusted_runway_m": grade.adjusted_runway_m,
            "itm_warrant_cash": grade.itm_warrant_cash,
            "overhang_ratio": grade.overhang_ratio, "rationale": grade.rationale,
        },
        "capital": {
            "shares_outstanding": c.shares_outstanding,
            "fully_diluted": fully_diluted,
            "cash": fin.cash if fin else None,
            "monthly_burn": fin.monthly_burn if fin else None,
            "theoretical_warrant_cash": itm_cash,
        },
        "warrants": [{"strike": w.strike, "expiry": w.expiry.isoformat(),
                      "quantity": w.quantity, "kind": w.kind,
                      "itm": bool(price and w.strike < price)} for w in warrants],
        "program": program and {
            "name": program.name, "rigs": program.rigs_active,
            "planned_holes": program.planned_holes,
            "planned_meters": program.planned_meters,
            "holes_drilled": len(holes), "holes_hit": len(hits),
        },
        "drill_results": [{
            "published": r.published.isoformat(), "hole": r.hole_id,
            "intercept": f"{r.grade:g} {r.unit} {r.commodity} over {r.width_m:g} m",
            "grade_meters": r.grade_meters, "above_benchmark": r.above_benchmark,
        } for r in results],
        "cash_history": [
            {"as_of": s.as_of.isoformat(), "cash": s.cash,
             "change_pct": (round(100 * (s.cash - cash_snaps[i - 1].cash)
                                  / cash_snaps[i - 1].cash, 1)
                            if i and cash_snaps[i - 1].cash else None)}
            for i, s in enumerate(cash_snaps)],
        "promotions": [
            {"announced": p.announced.isoformat(), "firm": p.firm,
             "amount": p.amount, "monthly_fee": p.monthly_fee,
             "term_months": p.term_months,
             "ends": p.ends and p.ends.isoformat(),
             "active": bool(p.ends and p.ends >= date.today()) or
                       (not p.ends and (date.today() - p.announced).days <= 90),
             "headline": p.headline, "url": p.source_url} for p in promos],
        "financings": [
            {"kind": f.kind, "announced": f.announced.isoformat(),
             "closed": f.closed,
             "close_date": f.close_date and f.close_date.isoformat(),
             "amount": f.amount, "price": f.price_per_unit,
             "warrant_strike": f.warrant_strike,
             "hold_expiry": f.hold_expiry and f.hold_expiry.isoformat(),
             "headline": f.headline, "url": f.source_url} for f in fins],
        "shares_history": [
            {"as_of": h.as_of.isoformat(), "shares": h.shares,
             "added": (h.shares - shares_hist[i - 1].shares) if i else None,
             "added_pct": (round(100 * (h.shares - shares_hist[i - 1].shares)
                                 / shares_hist[i - 1].shares, 1)
                           if i and shares_hist[i - 1].shares else None)}
            for i, h in enumerate(shares_hist)],
        "comparison": comparison,
    }


@app.post("/api/jobs/nightly")
async def trigger_nightly():
    """External cron / GitHub Action entry point."""
    return await run_nightly()
