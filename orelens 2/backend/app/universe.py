"""
Real junior-mining universe + loader.

POST /api/admin/load-universe
  1. Removes the fictional demo companies (and all their child rows)
  2. Upserts the real universe below
  3. For each ticker, pulls shares outstanding, ~6 months of daily price
     history, and quarterly cash/burn from Yahoo Finance (free, unofficial)

Notes:
- Financial snapshots (cash / burn) and warrant tables are NOT invented here.
  Grades stay empty until real filing data is loaded — placeholder numbers
  would produce misleading grades.
- Tickers verified against knowledge as of early 2026; delistings/takeovers
  can happen any time. A failed lookup is logged and skipped, not fatal.
"""
from __future__ import annotations
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .services import yahoo

log = logging.getLogger("orelens.universe")
router = APIRouter()

DEMO_TICKERS = ["AUR", "SLW", "KOB", "MGD", "TNG", "VLC", "BKG"]

# ticker, exchange, name, commodity, jurisdiction, tier, project
UNIVERSE = [
    # ---- Gold: Canada / USA / Tier 1 ----
    ("NFG",  "TSXV", "New Found Gold",        "Gold",   "Newfoundland, Canada",  "Tier 1", "Queensway"),
    ("SGD",  "TSXV", "Snowline Gold",         "Gold",   "Yukon, Canada",         "Tier 1", "Rogue / Valley"),
    ("AMX",  "TSXV", "Amex Exploration",      "Gold",   "Abitibi, Quebec",       "Tier 1", "Perron"),
    ("TUD",  "TSXV", "Tudor Gold",            "Gold",   "Golden Triangle, BC",   "Tier 1", "Treaty Creek"),
    ("SKE",  "TSX",  "Skeena Resources",      "Gold",   "Golden Triangle, BC",   "Tier 1", "Eskay Creek"),
    ("ARTG", "TSX",  "Artemis Gold",          "Gold",   "British Columbia",      "Tier 1", "Blackwater"),
    ("AOT",  "TSX",  "Ascot Resources",       "Gold",   "British Columbia",      "Tier 1", "Premier"),
    ("PRB",  "TSX",  "Probe Gold",            "Gold",   "Val-d'Or, Quebec",      "Tier 1", "Novador"),
    ("WM",   "TSX",  "Wallbridge Mining",     "Gold",   "Abitibi, Quebec",       "Tier 1", "Fenelon"),
    ("FURY", "TSX",  "Fury Gold Mines",       "Gold",   "Eeyou Istchee, Quebec", "Tier 1", "Eau Claire"),
    ("LGD",  "TSX",  "Liberty Gold",          "Gold",   "Idaho, USA",            "Tier 1", "Black Pine"),
    ("ITR",  "TSXV", "Integra Resources",     "Gold",   "Idaho, USA",            "Tier 1", "DeLamar"),
    ("PPTA", "TSX",  "Perpetua Resources",    "Gold",   "Idaho, USA",            "Tier 1", "Stibnite"),
    ("RUP",  "TSX",  "Rupert Resources",      "Gold",   "Lapland, Finland",      "Tier 1", "Ikkari"),
    ("GMIN", "TSX",  "G Mining Ventures",     "Gold",   "Para, Brazil",          "Tier 1", "Tocantinzinho"),
    # ---- Gold: higher-risk jurisdictions ----
    ("MAU",  "TSX",  "Montage Gold",          "Gold",   "Cote d'Ivoire",         "High Risk", "Kone"),
    ("ORE",  "TSX",  "Orezone Gold",          "Gold",   "Burkina Faso",          "High Risk", "Bombore"),
    ("ERD",  "TSX",  "Erdene Resource",       "Gold",   "Mongolia",              "High Risk", "Bayan Khundii"),
    ("MKO",  "TSXV", "Mako Mining",           "Gold",   "Nicaragua",             "High Risk", "San Albino"),
    ("WAF",  "ASX",  "West African Resources","Gold",   "Burkina Faso",          "High Risk", "Sanbrado"),
    ("MEK",  "ASX",  "Meeka Metals",          "Gold",   "Murchison, W. Australia","Tier 1",  "Murchison"),
    ("TTM",  "ASX",  "Titan Minerals",        "Gold",   "Ecuador",               "High Risk", "Dynasty"),
    # ---- Silver ----
    ("VZLA", "TSX",  "Vizsla Silver",         "Silver", "Sinaloa, Mexico",       "Tier 1", "Panuco"),
    ("ABRA", "TSX",  "AbraSilver Resource",   "Silver", "Salta, Argentina",      "Tier 1", "Diablillos"),
    ("BRC",  "TSXV", "Blackrock Silver",      "Silver", "Nevada, USA",           "Tier 1", "Tonopah West"),
    ("SLVR", "TSXV", "Silver Tiger Metals",   "Silver", "Sonora, Mexico",        "Tier 1", "El Tigre"),
    ("DV",   "TSXV", "Dolly Varden Silver",   "Silver", "Golden Triangle, BC",   "Tier 1", "Kitsault Valley"),
    ("AAG",  "TSXV", "Aftermath Silver",      "Silver", "Puno, Peru",            "High Risk", "Berenguela"),
    ("KTN",  "TSXV", "Kootenay Silver",       "Silver", "Sonora, Mexico",        "Tier 1", "Columba"),
    ("SSV",  "TSXV", "Southern Silver",       "Silver", "Durango, Mexico",       "Tier 1", "Cerro Las Minitas"),
    ("OCG",  "TSXV", "Outcrop Silver",        "Silver", "Tolima, Colombia",      "High Risk", "Santa Ana"),
    # ---- Copper ----
    ("NGEX", "TSX",  "NGEx Minerals",         "Copper", "Vicuna, Argentina/Chile","Tier 1", "Lunahuasi"),
    ("MARI", "TSX",  "Marimaca Copper",       "Copper", "Antofagasta, Chile",    "Tier 1", "Marimaca"),
    ("FDY",  "TSX",  "Faraday Copper",        "Copper", "Arizona, USA",          "Tier 1", "Copper Creek"),
    ("ALDE", "TSXV", "Aldebaran Resources",   "Copper", "San Juan, Argentina",   "Tier 1", "Altar"),
    ("KDK",  "TSXV", "Kodiak Copper",         "Copper", "British Columbia",      "Tier 1", "MPD"),
    ("HCH",  "ASX",  "Hot Chili",             "Copper", "Atacama, Chile",        "Tier 1", "Costa Fuego"),
    # ---- Nickel ----
    ("FPX",  "TSXV", "FPX Nickel",            "Nickel", "British Columbia",      "Tier 1", "Baptiste"),
    ("CNC",  "TSXV", "Canada Nickel",         "Nickel", "Timmins, Ontario",      "Tier 1", "Crawford"),
    ("TLO",  "TSX",  "Talon Metals",          "Nickel", "Minnesota, USA",        "Tier 1", "Tamarack"),
    # ---- Lithium ----
    ("PMET", "TSX",  "Patriot Battery Metals","Lithium","James Bay, Quebec",     "Tier 1", "Shaakichiuwaanaan"),
    ("FL",   "TSXV", "Frontier Lithium",      "Lithium","Ontario, Canada",       "Tier 1", "PAK"),
    ("LIFT", "TSXV", "Li-FT Power",           "Lithium","NWT, Canada",           "Tier 1", "Yellowknife"),
    ("GT1",  "ASX",  "Green Technology Metals","Lithium","Ontario, Canada",      "Tier 1", "Seymour"),
]

def _purge_companies(db: Session, tickers: list[str]) -> int:
    ids = db.execute(
        select(models.Company.id).where(models.Company.ticker.in_(tickers))
    ).scalars().all()
    if not ids:
        return 0
    for model in (models.DailyPrice, models.FinancialSnapshot, models.WarrantTranche,
                  models.DrillResult, models.DrillProgram, models.PressRelease,
                  models.InsiderBuy, models.DilutionGrade):
        db.execute(delete(model).where(model.company_id.in_(ids)))
    db.execute(delete(models.Company).where(models.Company.id.in_(ids)))
    return len(ids)


@router.post("/api/admin/load-universe")
async def load_universe(db: Session = Depends(get_db)):
    removed = _purge_companies(db, DEMO_TICKERS)
    db.commit()

    added, priced, financials, failed = [], [], [], []
    for (tick, exch, name, comm, juris, tier, proj) in UNIVERSE:
        c = db.execute(select(models.Company).where(
            models.Company.ticker == tick)).scalar_one_or_none()
        if not c:
            c = models.Company(ticker=tick, exchange=exch, name=name,
                               commodity=comm, jurisdiction=juris,
                               jurisdiction_tier=tier, project_name=proj,
                               shares_outstanding=0)
            db.add(c)
            db.flush()
            added.append(tick)

        data = await run_in_threadpool(yahoo.fetch_company_data, tick, exch)
        # self-heal exchange migrations (TSXV graduations to TSX and vice versa)
        if not data["prices"] and exch in ("TSX", "TSXV"):
            alt = "TSX" if exch == "TSXV" else "TSXV"
            alt_data = await run_in_threadpool(yahoo.fetch_company_data, tick, alt)
            if alt_data["prices"]:
                data = alt_data
                c.exchange = alt
                log.info("%s migrated exchange -> %s", tick, alt)
        if data["shares_outstanding"]:
            c.shares_outstanding = data["shares_outstanding"]
        if data["prices"]:
            have = {p.day for p in db.execute(select(models.DailyPrice).where(
                models.DailyPrice.company_id == c.id)).scalars()}
            for row in data["prices"]:
                if row["date"] in have:
                    continue
                db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                         close=row["close"],
                                         volume=row["volume"]))
            priced.append(tick)
        else:
            failed.append(tick)
        if data["cash"] and data["monthly_burn"]:
            existing_fin = db.execute(select(models.FinancialSnapshot).where(
                models.FinancialSnapshot.company_id == c.id)).scalars().first()
            if not existing_fin:
                db.add(models.FinancialSnapshot(
                    company_id=c.id, as_of=date.today(),
                    cash=data["cash"], monthly_burn=data["monthly_burn"],
                    source_filing="Yahoo Finance quarterly statements"))
                financials.append(tick)
        db.commit()

    # compute dilution grades for anything that now has price + financials
    from .jobs.nightly import run_grades
    run_grades(db)

    return {"demo_companies_removed": removed, "companies_added": added,
            "price_history_loaded": priced, "financials_loaded": financials,
            "lookup_failed": failed,
            "universe_size": len(UNIVERSE)}


# --------------------------------------------------------------------------
# Warrant / option tranche entry
# --------------------------------------------------------------------------
from pydantic import BaseModel, Field


class TrancheBody(BaseModel):
    strike: float = Field(gt=0)
    expiry: str                      # YYYY-MM-DD
    quantity: float = Field(gt=0)
    kind: str = "warrant"            # warrant | option
    hold_unlock: str | None = None   # YYYY-MM-DD, for recent PP 4-month holds


class WarrantsBody(BaseModel):
    tranches: list[TrancheBody]
    replace: bool = True             # replace existing tranches for this ticker
    source: str = "manual entry"     # cite the filing, e.g. "MD&A Mar 31 2026"


def _d(s: str | None):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


@router.get("/api/admin/warrants/{ticker}")
def get_warrants(ticker: str, db: Session = Depends(get_db)):
    c = db.execute(select(models.Company).where(
        models.Company.ticker == ticker.upper())).scalar_one_or_none()
    if not c:
        return {"error": "unknown ticker"}
    rows = db.execute(select(models.WarrantTranche).where(
        models.WarrantTranche.company_id == c.id).order_by(
        models.WarrantTranche.strike)).scalars().all()
    return [{"strike": w.strike, "expiry": w.expiry.isoformat(),
             "quantity": w.quantity, "kind": w.kind,
             "hold_unlock": w.hold_unlock and w.hold_unlock.isoformat(),
             "source": w.source_filing} for w in rows]


@router.post("/api/admin/warrants/{ticker}")
def set_warrants(ticker: str, body: WarrantsBody, db: Session = Depends(get_db)):
    """Store warrant/option tranches for a ticker and re-grade it immediately.
    Enter data straight from the company's latest MD&A / FS — cite it in
    the source field so every number is traceable."""
    c = db.execute(select(models.Company).where(
        models.Company.ticker == ticker.upper())).scalar_one_or_none()
    if not c:
        return {"error": "unknown ticker"}

    if body.replace:
        db.execute(delete(models.WarrantTranche).where(
            models.WarrantTranche.company_id == c.id))
    for t in body.tranches:
        db.add(models.WarrantTranche(
            company_id=c.id, kind=t.kind, strike=t.strike,
            expiry=_d(t.expiry), quantity=t.quantity,
            hold_unlock=_d(t.hold_unlock), source_filing=body.source[:240]))
    db.commit()

    from .jobs.nightly import run_grades
    run_grades(db)

    g = db.execute(select(models.DilutionGrade).where(
        models.DilutionGrade.company_id == c.id).order_by(
        models.DilutionGrade.day.desc())).scalars().first()
    return {"ticker": c.ticker, "tranches_stored": len(body.tranches),
            "new_grade": g and {"grade": g.grade,
                                "overhang_pct_float": round(g.overhang_ratio * 100, 1),
                                "itm_warrant_cash": g.itm_warrant_cash,
                                "rationale": g.rationale}}
