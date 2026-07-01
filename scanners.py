"""
The three programmatic scanners. Each returns plain dicts ready for the API.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from ..models import (
    Company, DailyPrice, DrillProgram, DrillResult, DilutionGrade,
    PressRelease, InsiderBuy, FinancialSnapshot, WarrantTranche,
)


def _latest_grade(db: Session, company_id: int) -> DilutionGrade | None:
    return db.execute(
        select(DilutionGrade).where(DilutionGrade.company_id == company_id)
        .order_by(desc(DilutionGrade.day)).limit(1)
    ).scalar_one_or_none()


def _latest_price(db: Session, company_id: int) -> DailyPrice | None:
    return db.execute(
        select(DailyPrice).where(DailyPrice.company_id == company_id)
        .order_by(desc(DailyPrice.day)).limit(1)
    ).scalar_one_or_none()


def _avg_volume_20d(db: Session, company_id: int) -> float:
    rows = db.execute(
        select(DailyPrice.volume).where(DailyPrice.company_id == company_id)
        .order_by(desc(DailyPrice.day)).offset(1).limit(20)
    ).scalars().all()
    return (sum(rows) / len(rows)) if rows else 0.0


def _base(c: Company, g: DilutionGrade | None, p: DailyPrice | None) -> dict:
    return {
        "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
        "commodity": c.commodity, "jurisdiction": c.jurisdiction,
        "jurisdiction_tier": c.jurisdiction_tier, "project": c.project_name,
        "price": p.close if p else None,
        "grade": g.grade if g else None,
        "runway_m": g.adjusted_runway_m if g else None,
    }


# ------------------------------------------------- Scanner 1: Active Drill Programs
def scan_active_drills(db: Session, commodity: str | None = None, tier: str | None = None) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=45)
    starts = db.execute(
        select(PressRelease.company_id).where(
            PressRelease.is_drill_start.is_(True), PressRelease.published >= cutoff
        ).distinct()
    ).scalars().all()

    out = []
    for cid in starts:
        c = db.get(Company, cid)
        if not c:
            continue
        if commodity and c.commodity != commodity:
            continue
        if tier and c.jurisdiction_tier != tier:
            continue
        prog = db.execute(
            select(DrillProgram).where(
                DrillProgram.company_id == cid, DrillProgram.active.is_(True)
            ).order_by(desc(DrillProgram.announced)).limit(1)
        ).scalar_one_or_none()
        g = _latest_grade(db, cid)
        row = _base(c, g, _latest_price(db, cid))
        row.update({
            "rigs_active": prog.rigs_active if prog else None,
            "planned_meters": prog.planned_meters if prog else None,
            "program": prog.name if prog else None,
        })
        out.append(row)
    return sorted(out, key=lambda r: (r["runway_m"] is None, -(r["runway_m"] or 0)))


# ------------------------------------------- Scanner 2: High-Grade News Breakouts
def scan_high_grade_breakouts(db: Session, lookback_days: int = 10,
                              commodity: str | None = None, tier: str | None = None) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    results = db.execute(
        select(DrillResult).where(
            DrillResult.above_benchmark.is_(True), DrillResult.published >= cutoff
        )
    ).scalars().all()

    out, seen = [], set()
    for r in results:
        if r.company_id in seen:
            continue
        c = db.get(Company, r.company_id)
        if not c or (commodity and c.commodity != commodity) or (tier and c.jurisdiction_tier != tier):
            continue
        p = _latest_price(db, c.id)
        avg20 = _avg_volume_20d(db, c.id)
        vol_ratio = (p.volume / avg20) if (p and avg20) else 0.0
        if vol_ratio < 3.0:  # volume > 300% of 20-day average
            continue
        seen.add(r.company_id)

        # hit percentage for the active program
        prog_results = db.execute(
            select(DrillResult).where(DrillResult.company_id == c.id,
                                      DrillResult.program_id == r.program_id)
        ).scalars().all()
        holes = {x.hole_id for x in prog_results if x.hole_id}
        hits = {x.hole_id for x in prog_results if x.hole_id and x.hit}
        prog = db.get(DrillProgram, r.program_id) if r.program_id else None
        drilled = max(len(holes), (prog.planned_holes if prog else 0) or len(holes))

        row = _base(c, _latest_grade(db, c.id), p)
        row.update({
            "intercept": f"{r.grade:g} {r.unit} {r.commodity} over {r.width_m:g} m",
            "grade_meters": r.grade_meters,
            "volume_ratio": round(vol_ratio, 1),
            "hit_pct": f"{len(hits)}/{drilled}" if drilled else "—",
            "published": r.published.isoformat(),
        })
        out.append(row)
    return sorted(out, key=lambda x: -x["grade_meters"])


# --------------------------------- Scanner 3: Best Bang-for-Buck (Value-Momentum)
def scan_value_momentum(db: Session, commodity: str | None = None, tier: str | None = None) -> list[dict]:
    out = []
    for c in db.execute(select(Company)).scalars():
        if (commodity and c.commodity != commodity) or (tier and c.jurisdiction_tier != tier):
            continue
        g = _latest_grade(db, c.id)
        p = _latest_price(db, c.id)
        if not g or not p:
            continue

        score, factors = 0.0, []

        # 1) low dilution risk
        if g.grade in ("A", "B"):
            score += 30 if g.grade == "A" else 20
            factors.append(f"Grade {g.grade}")
        else:
            continue  # hard filter per spec

        # 2) EV / resource ounce (cheaper = better)
        ev_per_oz = None
        if c.resource_oz:
            fin = db.execute(
                select(FinancialSnapshot).where(FinancialSnapshot.company_id == c.id)
                .order_by(desc(FinancialSnapshot.as_of)).limit(1)
            ).scalar_one_or_none()
            mcap = p.close * c.shares_outstanding
            ev = mcap - (fin.cash if fin else 0)
            ev_per_oz = ev / c.resource_oz
            if ev_per_oz < 30:
                score += 25
            elif ev_per_oz < 75:
                score += 15
            elif ev_per_oz < 150:
                score += 5
            factors.append(f"EV/oz ${ev_per_oz:,.0f}")

        # 3) volatility contraction + volume dry-up during active program
        prices = db.execute(
            select(DailyPrice).where(DailyPrice.company_id == c.id)
            .order_by(desc(DailyPrice.day)).limit(30)
        ).scalars().all()
        if len(prices) >= 20:
            closes = [x.close for x in prices]
            vols = [x.volume for x in prices]
            recent_range = (max(closes[:10]) - min(closes[:10])) / (sum(closes[:10]) / 10)
            prior_range = (max(closes[10:]) - min(closes[10:])) / (sum(closes[10:]) / 20)
            vol_drying = (sum(vols[:10]) / 10) < 0.7 * (sum(vols[10:]) / 20)
            active = db.execute(
                select(func.count(DrillProgram.id)).where(
                    DrillProgram.company_id == c.id, DrillProgram.active.is_(True))
            ).scalar_one()
            if prior_range > 0 and recent_range < 0.6 * prior_range and vol_drying and active:
                score += 25
                factors.append("VCP + volume dry-up during drilling")

        # 4) open-market insider buying in the last 60 days
        cutoff = date.today() - timedelta(days=60)
        insider = db.execute(
            select(func.coalesce(func.sum(InsiderBuy.shares * InsiderBuy.price), 0.0)).where(
                InsiderBuy.company_id == c.id, InsiderBuy.open_market.is_(True),
                InsiderBuy.trade_date >= cutoff)
        ).scalar_one()
        if insider > 0:
            score += min(20, 5 + insider / 25_000)
            factors.append(f"Insider buys ${insider:,.0f}")

        row = _base(c, g, p)
        row.update({"score": round(score, 1), "ev_per_oz": ev_per_oz and round(ev_per_oz, 0),
                    "factors": factors})
        out.append(row)
    return sorted(out, key=lambda x: -x["score"])
