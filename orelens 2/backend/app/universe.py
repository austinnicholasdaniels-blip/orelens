"""
Real junior-mining universe + loader.

POST /api/admin/load-universe
  1. Removes the fictional demo companies (and all their child rows)
  2. Upserts the real universe below
  3. For each ticker, pulls current quote (shares outstanding) and ~120 days
     of daily price history from FMP so charts are populated immediately

Notes:
- Financial snapshots (cash / burn) and warrant tables are NOT invented here.
  Grades stay empty until real filing data is loaded — placeholder numbers
  would produce misleading grades.
- Tickers verified against knowledge as of early 2026; delistings/takeovers
  can happen any time. A failed FMP lookup is logged and skipped, not fatal.
"""
from __future__ import annotations
import logging
from datetime import date, datetime

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .config import settings
from .services.ingest import fmp_symbol

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

FMP = "https://financialmodelingprep.com/api/v3"


async def _fetch_quote_and_history(client: httpx.AsyncClient, ticker: str, exchange: str):
    sym = fmp_symbol(ticker, exchange)
    quote, history = None, []
    try:
        r = await client.get(f"{FMP}/quote/{sym}", params={"apikey": settings.fmp_api_key})
        rows = r.json() if r.status_code == 200 else []
        quote = rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        log.error("quote %s failed: %s", sym, exc)
    try:
        r = await client.get(f"{FMP}/historical-price-full/{sym}",
                             params={"apikey": settings.fmp_api_key, "timeseries": 120})
        data = r.json() if r.status_code == 200 else {}
        history = data.get("historical", []) or []
    except Exception as exc:  # noqa: BLE001
        log.error("history %s failed: %s", sym, exc)
    return quote, history


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

    added, priced, failed = [], [], []
    async with httpx.AsyncClient(timeout=25) as client:
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

            if not settings.fmp_api_key:
                db.commit()
                continue
            quote, history = await _fetch_quote_and_history(client, tick, exch)
            if quote and quote.get("sharesOutstanding"):
                c.shares_outstanding = quote["sharesOutstanding"]
            if history:
                have = {p.day for p in db.execute(select(models.DailyPrice).where(
                    models.DailyPrice.company_id == c.id)).scalars()}
                for row in history:
                    d = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    if d in have or row.get("close") is None:
                        continue
                    db.add(models.DailyPrice(company_id=c.id, day=d,
                                             close=row["close"],
                                             volume=row.get("volume") or 0))
                priced.append(tick)
            elif quote is None:
                failed.append(tick)
            db.commit()

    return {"demo_companies_removed": removed, "companies_added": added,
            "price_history_loaded": priced, "fmp_lookup_failed": failed,
            "universe_size": len(UNIVERSE)}

