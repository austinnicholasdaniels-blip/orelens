"""
Seed a small, realistic demo universe so the dashboard works before any API
keys are configured. All figures are illustrative sample data, not live facts.

Run:  python -m app.seed
"""
from __future__ import annotations
import math
import random
from datetime import date, datetime, timedelta

from .db import Base, SessionLocal, engine
from .models import (
    Company, DailyPrice, FinancialSnapshot, WarrantTranche, DrillProgram,
    DrillResult, PressRelease, InsiderBuy,
)
from .jobs.nightly import run_grades
from .services.drill_parser import parse_intercepts

random.seed(7)

UNIVERSE = [
    # ticker, exch, name, commodity, jurisdiction, tier, project, SO (M), price0, cash (M), burn (M/mo), resource_oz
    ("AUR", "TSXV", "Aurora Ridge Gold", "Gold", "Nevada, USA", "Tier 1", "Copper Basin", 92e6, 0.74, 14.0e6, 0.9e6, 1.1e6),
    ("SLW", "TSXV", "Sierra Loba Silver", "Silver", "Durango, Mexico", "Tier 1", "La Loba", 148e6, 0.41, 6.2e6, 0.7e6, 42e6),
    ("KOB", "CSE", "Kobalt Creek Resources", "Copper", "British Columbia, Canada", "Tier 1", "Creek Porphyry", 210e6, 0.18, 2.1e6, 0.55e6, None),
    ("MGD", "TSXV", "Marigold Exploration", "Gold", "Abitibi, Quebec", "Tier 1", "Marigold East", 64e6, 1.32, 22.0e6, 1.1e6, 0.6e6),
    ("TNG", "ASX", "Tanami Nickel Group", "Nickel", "Western Australia", "Tier 1", "Redback", 310e6, 0.11, 1.4e6, 0.6e6, None),
    ("VLC", "TSXV", "Volcanic Lithium Corp", "Lithium", "Salta, Argentina", "High Risk", "Salar Norte", 175e6, 0.29, 3.3e6, 0.8e6, None),
    ("BKG", "CSE", "Blackgate Gold", "Gold", "Guerrero, Mexico", "High Risk", "Cerro Negro", 240e6, 0.09, 0.7e6, 0.5e6, None),
]

SAMPLE_RELEASES = {
    "AUR": (
        "Aurora Ridge Gold intersects 12.4 g/t Au over 8.5 m in hole CB-24-018 "
        "at Copper Basin. To date, 6 of 10 holes intersected mineralized grades "
        "above cutoff in the Phase 1 program.", True),
    "MGD": (
        "Marigold Exploration drills 6.1 g/t Au over 14.0 m in hole MGE-24-007, "
        "including 21.5 g/t Au over 3.0 m. 8 of 9 holes intersected mineralization. "
        "Diamond drilling underway with two rigs mobilized for the 10,000 m "
        "phase 1 program.", True),
    "KOB": (
        "Kobalt Creek announces drilling commenced at Creek Porphyry; "
        "first assays pending. The 5,000 m program will test three targets.", True),
    "SLW": (
        "Sierra Loba reports 620 g/t Ag over 4.2 m in hole LL-24-031. "
        "3 of 5 holes intersected high-grade veining.", False),
    "TNG": (
        "Tanami Nickel intersects 2.4% Ni over 12.0 m at Redback; "
        "rigs mobilized for follow-up drilling.", True),
}


def seed() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    today = date.today()

    for (tick, exch, name, comm, juris, tier, proj, so, p0, cash, burn, res) in UNIVERSE:
        c = Company(ticker=tick, exchange=exch, name=name, commodity=comm,
                    jurisdiction=juris, jurisdiction_tier=tier, project_name=proj,
                    shares_outstanding=so, resource_oz=res)
        db.add(c)
        db.flush()

        # ~90 days of prices; MGD gets a VCP-style contraction, AUR a news-day breakout
        px = p0
        for i in range(90, 0, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            drift = random.gauss(0, 0.03)
            if tick == "MGD" and i < 15:
                drift *= 0.25  # volatility contraction
            px = max(0.02, px * (1 + drift))
            vol = random.uniform(0.4, 1.6) * so * 0.004
            if tick == "MGD" and i < 15:
                vol *= 0.45  # volume dry-up
            if tick == "AUR" and i == 1:
                px *= 1.32
                vol *= 5.5  # breakout on the drill hit
            db.add(DailyPrice(company_id=c.id, day=d, close=round(px, 3), volume=round(vol)))

        db.add(FinancialSnapshot(company_id=c.id, as_of=today - timedelta(days=35),
                                 cash=cash, monthly_burn=burn,
                                 source_filing="Interim FS (seed)"))

        # warrant ladder — BKG gets a big hold-unlock this week to trigger an F
        for k in range(3):
            db.add(WarrantTranche(
                company_id=c.id, strike=round(p0 * (0.7 + 0.4 * k), 2),
                expiry=today + timedelta(days=180 + 240 * k),
                quantity=so * (0.03 + 0.02 * k),
                hold_unlock=(today + timedelta(days=3)) if (tick == "BKG" and k == 0) else None,
                source_filing="MD&A (seed)"))
        if tick == "BKG":
            db.add(WarrantTranche(company_id=c.id, strike=0.05,
                                  expiry=today + timedelta(days=120),
                                  quantity=so * 0.30,
                                  hold_unlock=today + timedelta(days=2)))

        prog = DrillProgram(
            company_id=c.id, name="Phase 1", announced=today - timedelta(days=20),
            rigs_active=2 if tick == "MGD" else 1,
            planned_holes=10, planned_meters=5000 if tick != "MGD" else 10000,
            avg_depth_m=250, cost_per_meter=250, active=tick in SAMPLE_RELEASES)
        db.add(prog)
        db.flush()

        if tick in SAMPLE_RELEASES:
            text, is_start = SAMPLE_RELEASES[tick]
            pr = PressRelease(company_id=c.id, published=datetime.utcnow() - timedelta(days=1),
                              headline=text.split(".")[0][:400],
                              url=f"https://example.com/pr/{tick.lower()}-phase1",
                              wire="GlobeNewswire", body=text, is_drill_start=is_start)
            db.add(pr)
            for i in parse_intercepts(text):
                db.add(DrillResult(
                    company_id=c.id, program_id=prog.id,
                    published=datetime.utcnow() - timedelta(days=1),
                    hole_id=i.hole_id, commodity=i.commodity, grade=i.grade,
                    unit=i.unit, width_m=i.width_m, grade_meters=i.grade_meters,
                    above_benchmark=i.above_benchmark, raw_sentence=i.raw_sentence,
                    source_url=pr.url))

        if tick in ("MGD", "AUR"):
            db.add(InsiderBuy(company_id=c.id, trade_date=today - timedelta(days=12),
                              insider="CEO", shares=200_000, price=p0, open_market=True))

    db.commit()
    run_grades(db)
    db.close()
    print("Seeded", len(UNIVERSE), "companies with prices, warrants, drill results, and grades.")


if __name__ == "__main__":
    seed()
