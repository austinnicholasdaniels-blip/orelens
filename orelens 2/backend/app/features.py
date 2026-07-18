"""
Site features: search, on-demand ticker adds, notable-holder scanners,
and the AI ranking scanner (Claude API).
"""
from __future__ import annotations
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .services import marketdata
from .services import marketdata as yahoo

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

    data = await run_in_threadpool(marketdata.fetch_company_data, tick, c.exchange)
    if not data["prices"] and c.exchange in ("TSX", "TSXV"):
        alt = "TSX" if c.exchange == "TSXV" else "TSXV"
        alt_data = await run_in_threadpool(marketdata.fetch_company_data, tick, alt)
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
    for sh in data.get("shares_history", []):
        if not db.execute(select(models.SharesHistory).where(
                models.SharesHistory.company_id == c.id,
                models.SharesHistory.as_of == sh["as_of"])).scalar_one_or_none():
            db.add(models.SharesHistory(company_id=c.id,
                                        as_of=sh["as_of"], shares=sh["shares"]))
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
    """Fetch a filing PDF, extract cash / burn / warrant & option tables with
    the Anthropic API, store them with the filing URL as source, and re-grade."""
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


# ------------------------------------------------- most-dilutive scanner
from sqlalchemy import desc as _desc




def _stale_tickers(db) -> set[str]:
    """Tickers whose price feed has stopped updating - delisted, halted, or
    dead symbols. Anything more than 10 days behind the freshest price in the
    universe (or with no prices at all) is considered inactive."""
    from datetime import timedelta as _td
    max_day = db.execute(select(func.max(models.DailyPrice.day))).scalar()
    if not max_day:
        return set()
    cutoff = max_day - _td(days=10)
    rows = db.execute(
        select(models.Company.ticker, func.max(models.DailyPrice.day))
        .join(models.DailyPrice, models.DailyPrice.company_id == models.Company.id)
        .group_by(models.Company.ticker)).all()
    stale = {t for t, d in rows if d and d < cutoff}
    priced = {t for t, _ in rows}
    all_t = {t for (t,) in db.execute(select(models.Company.ticker)).all()}
    return stale | (all_t - priced)


def _drop_stale(db, rows):
    """Filter scanner rows down to actively-trading tickers only."""
    if not isinstance(rows, list):
        return rows
    s = _stale_tickers(db)
    return [r for r in rows if r.get("ticker") not in s]


@router.get("/api/scanners/most-dilutive")
def most_dilutive(commodity: str | None = None, tier: str | None = None,
                  db: Session = Depends(get_db)):
    """Companies ranked by the largest quarter-over-quarter increase in shares
    outstanding - i.e. who actually printed the most new stock last quarter."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        hist = db.execute(select(models.SharesHistory).where(
            models.SharesHistory.company_id == c.id)
            .order_by(models.SharesHistory.as_of)).scalars().all()
        if len(hist) < 2 or not hist[-2].shares:
            continue
        last, prev = hist[-1], hist[-2]
        qoq_pct = round(100 * (last.shares - prev.shares) / prev.shares, 1)
        if qoq_pct <= 0:
            continue  # only companies that actually diluted
        total_pct = (round(100 * (last.shares - hist[0].shares) / hist[0].shares, 1)
                     if hist[0].shares else None)
        g = db.execute(select(models.DilutionGrade).where(
            models.DilutionGrade.company_id == c.id)
            .order_by(_desc(models.DilutionGrade.day)).limit(1)).scalar_one_or_none()
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "qoq_pct": qoq_pct,
            "shares_added_m": round((last.shares - prev.shares) / 1e6, 1),
            "total_growth_pct": total_pct,
            "as_of": last.as_of.isoformat(),
            "grade": g.grade if g else None,
        })
    out.sort(key=lambda x: -x["qoq_pct"])
    return _drop_stale(db, out)


# ------------------------------------------------- all-stocks market board
@router.get("/api/scanners/all-stocks")
def all_stocks(commodity: str | None = None, tier: str | None = None,
               db: Session = Depends(get_db)):
    """Every tracked company with its latest price and day-over-day change."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        px = db.execute(select(models.DailyPrice).where(
            models.DailyPrice.company_id == c.id)
            .order_by(_desc(models.DailyPrice.day)).limit(2)).scalars().all()
        if not px:
            continue
        last = px[0]
        change = (round(100 * (last.close - px[1].close) / px[1].close, 1)
                  if len(px) > 1 and px[1].close else None)
        g = db.execute(select(models.DilutionGrade).where(
            models.DilutionGrade.company_id == c.id)
            .order_by(_desc(models.DilutionGrade.day)).limit(1)).scalar_one_or_none()
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "price": round(last.close, 2), "change_pct": change,
            "volume": int(last.volume or 0), "as_of": last.day.isoformat(),
            "grade": g.grade if g else None,
        })
    out.sort(key=lambda x: -(x["change_pct"] if x["change_pct"] is not None else -999))
    return _drop_stale(db, out)


# ------------------------------------------------- press-release feed
@router.get("/api/scanners/news")
def news_feed(commodity: str | None = None, tier: str | None = None,
              db: Session = Depends(get_db)):
    """Latest mining press releases from the nightly wire sync, newest first."""
    from datetime import datetime as _dtt, timedelta as _tdd
    cutoff = _dtt.utcnow() - _tdd(days=5)
    rows = db.execute(select(models.PressRelease)
                      .where(models.PressRelease.published >= cutoff)
                      .order_by(_desc(models.PressRelease.published))
                      .limit(150)).scalars().all()
    companies = {c.id: c for c in db.execute(select(models.Company)).scalars()}
    out = []
    for r in rows:
        c = companies.get(r.company_id)
        # bulletproof display rule: only rows from the Newsfile mining
        # industry feeds ever show. Kills all junk from the old PRNewswire /
        # Accesswire / GlobeNewswire general feeds (including rows those
        # feeds false-matched to tracked tickers) without a database purge.
        if not r.wire.startswith(("Newsfile", "EODHD")):
            continue
        if commodity and (not c or c.commodity != commodity):
            continue
        if tier and (not c or c.jurisdiction_tier != tier):
            continue
        out.append({
            "published": r.published.isoformat() if r.published else None,
            "ticker": c.ticker if c else None,
            "exchange": c.exchange if c else None,
            "headline": r.headline, "url": r.url, "wire": r.wire,
            "drill_start": bool(r.is_drill_start),
        })
    return _drop_stale(db, out)[:100]


# ------------------------------------------------- coiled-springs scanner
@router.get("/api/scanners/coiled-springs")
def coiled_springs(commodity: str | None = None, tier: str | None = None,
                   db: Session = Depends(get_db)):
    from .services import scanners as _sc
    return _drop_stale(db, _sc.scan_coiled_springs(db, commodity, tier))


# ------------------------------------------------- unlock calendar
@router.get("/api/scanners/unlock-calendar")
def unlock_calendar(commodity: str | None = None, tier: str | None = None,
                    db: Session = Depends(get_db)):
    """Closed financings whose 4-month hold is expiring: the day this paper
    free-trades is a supply event. Sorted soonest first."""
    from datetime import timedelta as _td
    today = date.today()
    out = []
    for fin in db.execute(select(models.Financing).where(
            models.Financing.closed.is_(True),
            models.Financing.hold_expiry.is_not(None),
            models.Financing.hold_expiry >= today - _td(days=7))
            .order_by(models.Financing.hold_expiry)).scalars():
        c = db.get(models.Company, fin.company_id)
        if not c:
            continue
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        est_shares = (fin.amount / fin.price_per_unit
                      if fin.amount and fin.price_per_unit else None)
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "kind": fin.kind, "close_date": fin.close_date and fin.close_date.isoformat(),
            "amount_m": fin.amount and round(fin.amount / 1e6, 2),
            "price": fin.price_per_unit,
            "est_shares_m": est_shares and round(est_shares / 1e6, 1),
            "warrant_strike": fin.warrant_strike,
            "hold_expiry": fin.hold_expiry.isoformat(),
            "days_until": (fin.hold_expiry - today).days,
        })
    return _drop_stale(db, out)


@router.post("/api/admin/detect-financings")
def detect_financings(db: Session = Depends(get_db)):
    """Backfill: run financing detection over every stored press release."""
    from .jobs.nightly import _upsert_financing
    from .services import financing as _fin
    found = 0
    for pr in db.execute(select(models.PressRelease).where(
            models.PressRelease.company_id.is_not(None))).scalars():
        f = _fin.parse_financing(f"{pr.headline} {pr.body or ''}")
        if f:
            _upsert_financing(db, pr.company_id, pr.published,
                              pr.headline[:400], pr.url[:400], f)
            found += 1
    db.commit()
    total = db.execute(select(models.Financing)).scalars().all()
    return {"releases_matched": found, "financings_tracked": len(total)}


# ------------------------------------------------- data quality / trust page
@router.get("/api/data-quality")
def data_quality(db: Session = Depends(get_db)):
    """Coverage and freshness stats - the numbers a diligence team asks for."""
    companies = db.execute(select(models.Company)).scalars().all()
    n = len(companies)
    def _count(model):
        return len({r for r in db.execute(
            select(model.company_id).distinct()).scalars()})
    latest_price_day = db.execute(select(models.DailyPrice.day)
        .order_by(_desc(models.DailyPrice.day)).limit(1)).scalar_one_or_none()
    return {
        "companies_tracked": n,
        "with_price_history": _count(models.DailyPrice),
        "with_financials": _count(models.FinancialSnapshot),
        "with_warrant_tables": _count(models.WarrantTranche),
        "with_share_history": _count(models.SharesHistory),
        "with_dilution_grade": _count(models.DilutionGrade),
        "financings_tracked": len(db.execute(select(models.Financing)).scalars().all()),
        "press_releases_stored": len(db.execute(select(models.PressRelease)).scalars().all()),
        "latest_price_day": latest_price_day and latest_price_day.isoformat(),
        "note": "Every financial figure stores its source filing URL for verification.",
    }




# ---------------------------------------------------------- attribution guard
_SUFFIX_WORDS = {"corp", "corp.", "inc", "inc.", "ltd", "ltd.", "limited",
                 "corporation", "company", "co", "co.", "plc", "incorporated"}


def _core_name(name: str) -> str:
    """Company name minus legal suffixes, lowercased: 'New Found Gold Corp.'
    -> 'new found gold'."""
    words = [w for w in name.lower().replace(",", " ").split()
             if w not in _SUFFIX_WORDS]
    return " ".join(words)


def _title_mentions(company, title: str) -> bool:
    """A headline may only be attributed to a company if it actually names
    the company (core name phrase) or cites its exchange ticker. Google's
    relevance matching is fuzzy - never trust it for attribution."""
    import re as _re
    t = title.lower()
    core = _core_name(company.name)
    if core and core in t:
        return True
    return bool(_re.search(
        rf"\((?:TSX|TSXV|TSX-V|CSE|ASX|NYSE|OTCQ[BX])\s*:\s*{_re.escape(company.ticker)}\b",
        title))


_title_belongs_to = _title_mentions   # single source of truth


# --------------------------------------------- financing history backfill
@router.post("/api/admin/backfill-financing-history")
async def backfill_financing_history(days: int = 135, db: Session = Depends(get_db)):
    """Scan the last ~4 months of news for every tracked company via Google
    News RSS and extract placements/bought deals into the Financing table.
    Captures financings on every wire, not just Newsfile."""
    import asyncio as _aio
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from .jobs.nightly import _upsert_financing
    from .services import financing as _finmod

    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    per_company, total = {}, 0

    companies = db.execute(select(models.Company)).scalars().all()
    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        for c in companies:
            from urllib.parse import quote_plus as _qp
            q = f'"{c.name}" ("private placement" OR "bought deal" OR "offering") when:{days}d'
            url = (f"https://news.google.com/rss/search?q={_qp(q)}"
                   "&hl=en-CA&gl=CA&ceid=CA:en")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            found = 0
            for e in feed.entries[:15]:
                title = e.get("title", "")
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                if not _title_mentions(c, title):
                    continue    # Google returned a related-but-different company
                parsed = _finmod.parse_financing(title)
                if not parsed:
                    continue
                _upsert_financing(db, c.id, pub, title[:400],
                                  e.get("link", "")[:400], parsed)
                found += 1
            if found:
                per_company[c.ticker] = found
                total += found
            await _aio.sleep(0.35)   # be polite to Google News
    db.commit()
    fins = db.execute(select(models.Financing)).scalars().all()
    closed = [x for x in fins if x.closed]
    return {"companies_scanned": len(companies), "headlines_matched": total,
            "financings_tracked": len(fins), "closed_with_hold_expiry": len(closed),
            "hits_by_ticker": per_company}


# ------------------------------------------------- stock promotions scanner
@router.get("/api/scanners/stock-promotions")
def stock_promotions(commodity: str | None = None, tier: str | None = None,
                     db: Session = Depends(get_db)):
    """Disclosed investor-awareness / IR engagements from the last ~5 months.
    Paid promotion + tight float is the classic junior setup - watch for it."""
    from datetime import timedelta as _td
    today = date.today()
    out = []
    for p in db.execute(select(models.Promotion).where(
            models.Promotion.announced >= today - _td(days=160))
            .order_by(_desc(models.Promotion.announced))).scalars():
        c = db.get(models.Company, p.company_id)
        if not c:
            continue
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        if p.ends:
            status = "ACTIVE" if p.ends >= today else "Expired"
        else:
            status = "ACTIVE (term undisclosed)" if (today - p.announced).days <= 90 else "Unknown"
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "firm": p.firm, "amount": p.amount and round(p.amount, 0),
            "monthly_fee": p.monthly_fee and round(p.monthly_fee, 0),
            "term_months": p.term_months,
            "announced": p.announced.isoformat(),
            "ends": p.ends and p.ends.isoformat(),
            "status": status, "headline": p.headline, "url": p.source_url,
        })
    out.sort(key=lambda x: (not x["status"].startswith("ACTIVE"), x["announced"]), )
    out.sort(key=lambda x: not x["status"].startswith("ACTIVE"))
    return _drop_stale(db, out)


@router.post("/api/admin/backfill-promotions")
async def backfill_promotions(days: int = 150, db: Session = Depends(get_db)):
    """Scan ~5 months of news per company via Google News RSS for disclosed
    investor-awareness / IR / marketing engagements."""
    import asyncio as _aio
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .jobs.nightly import _upsert_promotion
    from .services import promotion as _promo

    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    per_company, total = {}, 0
    companies = db.execute(select(models.Company)).scalars().all()
    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        for c in companies:
            q = (f'"{c.name}" ("investor awareness" OR "investor relations" '
                 f'OR "marketing services" OR "market awareness") when:{days}d')
            url = (f"https://news.google.com/rss/search?q={_qp(q)}"
                   "&hl=en-CA&gl=CA&ceid=CA:en")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            found = 0
            for e in feed.entries[:15]:
                title = e.get("title", "")
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                if not _title_mentions(c, title):
                    continue    # Google returned a related-but-different company
                parsed = _promo.parse_promotion(title)
                if not parsed:
                    continue
                _upsert_promotion(db, c.id, pub, title[:400],
                                  e.get("link", "")[:400], parsed)
                found += 1
            if found:
                per_company[c.ticker] = found
                total += found
            await _aio.sleep(0.35)
    db.commit()
    promos = db.execute(select(models.Promotion)).scalars().all()
    return {"companies_scanned": len(companies), "headlines_matched": total,
            "promotions_tracked": len(promos), "hits_by_ticker": per_company}


# --------------------------------------- DEEP promotion scan (full release text)
@router.post("/api/admin/backfill-promotions-deep")
async def backfill_promotions_deep(days: int = 160, db: Session = Depends(get_db)):
    """Accuracy pass: follow every candidate headline to the full release page
    and parse firm / term / fees from the complete disclosure text. Also
    re-fetches existing sparse rows to fill missing fields."""
    import asyncio as _aio
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .jobs.nightly import _upsert_promotion
    from .services import promotion as _promo

    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    hint = ("investor", "awareness", "marketing", "relations", "engag",
            "media", "advertis", "ir program", "digital")
    stats = {"pages_fetched": 0, "promotions_found": 0, "rows_enriched": 0,
             "hits_by_ticker": {}}

    async def _page_text(client, url: str) -> str:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return _promo.html_to_text(r.text)[:60_000]
        except Exception:  # noqa: BLE001
            return ""

    companies = db.execute(select(models.Company)).scalars().all()
    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        # pass 1: enrich existing sparse rows from their source pages
        for row in db.execute(select(models.Promotion)).scalars():
            if row.firm and (row.amount or row.monthly_fee) and row.term_months:
                continue
            text = await _page_text(client, row.source_url)
            stats["pages_fetched"] += 1
            parsed = _promo.parse_promotion(text) if text else None
            if parsed:
                row.firm = row.firm or parsed.get("firm")
                row.amount = row.amount or parsed.get("amount")
                row.monthly_fee = row.monthly_fee or parsed.get("monthly_fee")
                if not row.term_months and parsed.get("term_months"):
                    row.term_months = parsed["term_months"]
                    row.ends = row.announced + _td(days=int(parsed["term_months"] * 30.4))
                stats["rows_enriched"] += 1
            await _aio.sleep(0.25)

        # pass 2: per-company Google News, follow links, parse full text
        for c in companies:
            q = (f'"{c.name}" ("investor awareness" OR "investor relations" '
                 f'OR "marketing" OR "market awareness") when:{days}d')
            url = (f"https://news.google.com/rss/search?q={_qp(q)}"
                   "&hl=en-CA&gl=CA&ceid=CA:en")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            found = 0
            for e in feed.entries[:10]:
                title = e.get("title", "")
                if not _title_mentions(c, title):
                    continue    # never attribute another company's news
                if not any(h in title.lower() for h in hint):
                    continue
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                text = await _page_text(client, e.get("link", ""))
                stats["pages_fetched"] += 1
                parsed = _promo.parse_promotion(text or title)
                if not parsed:
                    continue
                _upsert_promotion(db, c.id, pub, title[:400],
                                  e.get("link", "")[:400], parsed)
                found += 1
                await _aio.sleep(0.25)
            if found:
                stats["hits_by_ticker"][c.ticker] = found
                stats["promotions_found"] += found
            await _aio.sleep(0.2)
    db.commit()
    promos = db.execute(select(models.Promotion)).scalars().all()
    complete = [p for p in promos if p.firm and (p.amount or p.monthly_fee)]
    stats["promotions_tracked"] = len(promos)
    stats["with_full_terms"] = len(complete)
    return stats


@router.post("/api/admin/purge-misattributed")
def purge_misattributed(db: Session = Depends(get_db)):
    """Delete any stored financing or promotion whose headline does not
    actually name its attributed company. Accuracy over volume, always."""
    removed = {"financings": 0, "promotions": 0}
    for model, key in ((models.Financing, "financings"),
                       (models.Promotion, "promotions")):
        for row in db.execute(select(model)).scalars().all():
            c = db.get(models.Company, row.company_id)
            if not c or not _title_mentions(c, row.headline):
                db.delete(row)
                removed[key] += 1
    db.commit()
    return {"removed": removed,
            "financings_remaining": len(db.execute(select(models.Financing)).scalars().all()),
            "promotions_remaining": len(db.execute(select(models.Promotion)).scalars().all())}


# ---------------------------------------------------- data integrity cleaner
@router.post("/api/admin/clean-misattributed")
def clean_misattributed(db: Session = Depends(get_db)):
    """Delete promotions/financings whose headline does not actually name the
    company it was attributed to, and dedupe financings (same company, same
    amount, same kind -> keep the earliest)."""
    removed_promos = removed_fins = deduped = 0
    companies = {c.id: c for c in db.execute(select(models.Company)).scalars()}

    for p in db.execute(select(models.Promotion)).scalars().all():
        c = companies.get(p.company_id)
        if not c or not _title_belongs_to(c, p.headline):
            db.delete(p)
            removed_promos += 1
    for fin in db.execute(select(models.Financing)).scalars().all():
        c = companies.get(fin.company_id)
        if not c or not _title_belongs_to(c, fin.headline):
            db.delete(fin)
            removed_fins += 1
    db.flush()

    seen: dict[tuple, int] = {}
    for fin in db.execute(select(models.Financing)
                          .order_by(models.Financing.announced)).scalars().all():
        key = (fin.company_id, fin.kind, fin.amount)
        if key in seen:
            db.delete(fin)
            deduped += 1
        else:
            seen[key] = fin.id
    db.commit()
    promos = len(db.execute(select(models.Promotion)).scalars().all())
    fins = len(db.execute(select(models.Financing)).scalars().all())
    return {"removed_misattributed_promotions": removed_promos,
            "removed_misattributed_financings": removed_fins,
            "deduped_financings": deduped,
            "promotions_remaining": promos, "financings_remaining": fins}


# --------------------------------- market-wide promotion sweep (all of TSXV)
ISSUER_PAT_SRC = (r"([A-Z][A-Za-z0-9&.\-' ]{2,60}?)\s*"
                  r"\(\s*(TSXV|TSX-V|TSX VENTURE|TSX|CSE|CNSX|NEO)\s*[:\s]\s*([A-Z]{1,6})(?:\.[A-Z])?\s*[\)|,]")

MARKET_PROMO_QUERIES = [
    '"investor awareness" "TSXV"',
    '"investor awareness" "TSX Venture"',
    '"investor awareness campaign" mining',
    '"investor relations agreement" "TSXV"',
    '"market awareness" "TSXV"',
    '"marketing services" "TSXV"',
    '"engages" "investor awareness"',
    '"digital marketing" "TSXV" mining',
]


@router.post("/api/admin/scan-promotions-market")
async def scan_promotions_market(days: int = 150, db: Session = Depends(get_db)):
    """Market-wide sweep: search the news for promotion language across ALL
    TSXV/TSX mining issuers (not just tracked ones), follow each hit to the
    release page, extract the issuer's own name + ticker from its exchange
    parenthetical, auto-add unknown companies, and file the promotion."""
    import asyncio as _aio
    import re as _re
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .jobs.nightly import _upsert_promotion
    from .services import promotion as _promo

    issuer_pat = _re.compile(ISSUER_PAT_SRC)
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    stats = {"headlines_seen": 0, "pages_fetched": 0, "promotions_filed": 0,
             "companies_added": [], "hits_by_ticker": {}}
    seen_links: set[str] = set()

    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        for query in MARKET_PROMO_QUERIES:
            url = (f"https://news.google.com/rss/search?q={_qp(query + f' when:{days}d')}"
                   "&hl=en-CA&gl=CA&ceid=CA:en")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            for e in feed.entries[:100]:
                link = e.get("link", "")
                title = e.get("title", "")
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                stats["headlines_seen"] += 1
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                # fetch the release page: issuer + full disclosure text live there
                try:
                    pr = await client.get(link)
                    pr.raise_for_status()
                    text = _promo.html_to_text(pr.text)[:80_000]
                except Exception:  # noqa: BLE001
                    continue
                stats["pages_fetched"] += 1
                parsed = _promo.parse_promotion(text)
                if not parsed:
                    continue
                m = issuer_pat.search(text[:6000])   # issuer is named up top
                if not m:
                    continue
                name = m.group(1).strip(" ,.")
                # strip dateline prefixes: "Vancouver, BC - Miivo AI Corp." -> "Miivo AI Corp."
                name = _re.split(r"\s[\-\u2013\u2014]{1,2}\s|--|\)\s", name)[-1].strip(" ,.-")
                ticker = m.group(3).upper()
                exchange = "TSXV" if "V" in m.group(2).upper().replace("TSX", "") \
                           or "VENTURE" in m.group(2).upper() else "TSX"
                if len(name) < 4:
                    continue
                c = db.execute(select(models.Company).where(
                    models.Company.ticker == ticker)).scalar_one_or_none()
                if not c:
                    c = models.Company(ticker=ticker, exchange=exchange,
                                       name=name, commodity="Unclassified",
                                       jurisdiction="", jurisdiction_tier="Tier 1",
                                       project_name="", shares_outstanding=0)
                    db.add(c)
                    db.flush()
                    stats["companies_added"].append(f"{ticker} ({name})")
                # final attribution check against the issuer's own name
                if not _title_mentions(c, title) and c.name.lower() not in text[:2000].lower():
                    continue
                _upsert_promotion(db, c.id, pub, title[:400], link[:400], parsed)
                stats["promotions_filed"] += 1
                stats["hits_by_ticker"][ticker] = stats["hits_by_ticker"].get(ticker, 0) + 1
                await _aio.sleep(0.25)
            await _aio.sleep(0.3)
    db.commit()
    promos = db.execute(select(models.Promotion)).scalars().all()
    stats["promotions_tracked_total"] = len(promos)
    return stats


# ----------------------- market sweep v2: Bing News (direct links) + mining filter
MINING_HINTS = ("mining", "mineral", "exploration", "gold", "silver", "copper",
                "lithium", "uranium", "drill", "metals", "nickel", "zinc",
                "critical mineral", "mineraliz", "assay", "ore ")

BING_PROMO_QUERIES = [
    '"engages" "investor awareness"',
    '"investor awareness services"',
    '"investor awareness campaign"',
    '"investor relations agreement"',
    '"market awareness campaign"',
    '"marketing services agreement" TSXV',
    '"engages" "investor relations"',
]


@router.post("/api/admin/scan-promotions-market-v2")
async def scan_promotions_market_v2(days: int = 150, db: Session = Depends(get_db)):
    """Market-wide sweep, corrected: Bing News RSS returns DIRECT publisher
    links (Google's are redirects our server can't follow). Strategy per the
    operator: search the engagement language broadly, then keep only releases
    whose text reads as mining. Auto-adds unknown issuers."""
    import asyncio as _aio
    import re as _re
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .jobs.nightly import _upsert_promotion
    from .services import promotion as _promo

    issuer_pat = _re.compile(ISSUER_PAT_SRC)
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    stats = {"headlines_seen": 0, "pages_fetched": 0, "non_mining_skipped": 0,
             "promotions_filed": 0, "companies_added": [], "hits_by_ticker": {}}
    seen: set[str] = set()

    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        for query in BING_PROMO_QUERIES:
            url = (f"https://www.bing.com/news/search?q={_qp(query)}"
                   "&format=rss&count=60")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            for e in feed.entries:
                link = e.get("link", "")
                title = e.get("title", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                stats["headlines_seen"] += 1
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                try:
                    pr = await client.get(link)
                    pr.raise_for_status()
                    text = _promo.html_to_text(pr.text)[:80_000]
                except Exception:  # noqa: BLE001
                    continue
                stats["pages_fetched"] += 1
                low = text.lower()
                if not any(h in low for h in MINING_HINTS):
                    stats["non_mining_skipped"] += 1
                    continue
                parsed = _promo.parse_promotion(text)
                if not parsed:
                    continue
                m = issuer_pat.search(text[:8000])
                if not m:
                    continue
                name = m.group(1).strip(" ,.")
                name = _re.split(r"\s[\-\u2013\u2014]{1,2}\s|--|\)\s", name)[-1].strip(" ,.-")
                ticker = m.group(3).upper()
                exchange = "TSXV" if "V" in m.group(2).upper().replace("TSX", "") \
                           or "VENTURE" in m.group(2).upper() else "TSX"
                if len(name) < 4:
                    continue
                c = db.execute(select(models.Company).where(
                    models.Company.ticker == ticker)).scalar_one_or_none()
                if not c:
                    c = models.Company(ticker=ticker, exchange=exchange,
                                       name=name, commodity="Unclassified",
                                       jurisdiction="", jurisdiction_tier="Tier 1",
                                       project_name="", shares_outstanding=0)
                    db.add(c)
                    db.flush()
                    stats["companies_added"].append(f"{ticker} ({name})")
                if not _title_mentions(c, title) and c.name.lower() not in low[:3000]:
                    continue
                _upsert_promotion(db, c.id, pub, title[:400], link[:400], parsed)
                stats["promotions_filed"] += 1
                stats["hits_by_ticker"][ticker] = stats["hits_by_ticker"].get(ticker, 0) + 1
                await _aio.sleep(0.2)
            await _aio.sleep(0.3)
    db.commit()
    promos = db.execute(select(models.Promotion)).scalars().all()
    stats["promotions_tracked_total"] = len(promos)
    return stats


# ------------------- market sweep v3: Google archive (decoded) + firm roster
PROMO_FIRMS = [
    "Outside The Box Capital", "Winning Media", "Native Ads", "Apaton Finance",
    "Market One Media", "ICP Securities", "Torrey Hills Capital",
    "Machai Capital", "Hybrid Financial", "Renmark Financial",
    "i2i Marketing", "Global One Media", "Stockhouse Publishing",
    "AGORACOM", "InvestorBrandNetwork", "Red Cloud Financial",
]

V3_QUERIES = [
    "engages investor relations mining",
    "engages investor awareness",
    "investor relations agreement TSXV",
    "market awareness campaign mining",
    "marketing services agreement mining",
] + [f'"{firm}"' for firm in PROMO_FIRMS]


def _gnews_real_url(link: str, html: str | None = None) -> str | None:
    """Resolve a news.google.com redirect to the real article URL.
    Step 1: decode the base64 token (works for CBMi-era links).
    Step 2: regex the target out of the interstitial HTML if provided."""
    import base64
    import re as _re
    m = _re.search(r"articles/([^?/]+)", link)
    if m:
        token = m.group(1)
        pad = "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(token + pad)
            m2 = _re.search(rb'https?://[^\x00-\x08\x0b\x0c\x0e-\x1f"\\ ]+', raw)
            if m2:
                url = m2.group(0).decode("utf-8", "ignore").rstrip("\x01\x02R")
                if "google" not in url:
                    return url
        except Exception:  # noqa: BLE001
            pass
    if html:
        import re as _re2
        m3 = _re2.search(r'href="(https?://(?!(?:[^"]*google|accounts\.))[^"]{15,300})"', html)
        if m3:
            return m3.group(1)
    return None


@router.post("/api/admin/scan-promotions-market-v3")
async def scan_promotions_market_v3(days: int = 365, db: Session = Depends(get_db)):
    """Deep market sweep: Google News archive (up to a year) with redirect
    decoding, broad 'engages investor relations' phrasing, AND direct searches
    for every known promotion firm - each firm query surfaces its whole mining
    client roster. Only ticker, amount, and active-status are surfaced to the
    UI; everything stored keeps its source link for verification."""
    import asyncio as _aio
    import re as _re
    import feedparser as _fp
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .jobs.nightly import _upsert_promotion
    from .services import promotion as _promo

    issuer_pat = _re.compile(ISSUER_PAT_SRC)
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    cutoff = _dt.utcnow() - _td(days=days)
    stats = {"headlines_seen": 0, "links_decoded": 0, "links_via_html": 0,
             "pages_fetched": 0, "non_mining_skipped": 0, "promotions_filed": 0,
             "companies_added": [], "hits_by_ticker": {}}
    seen: set[str] = set()

    async def _resolve_and_fetch(client, glink: str) -> str:
        """Return release text or '' - tries decoded URL, then interstitial."""
        real = _gnews_real_url(glink)
        if real:
            stats["links_decoded"] += 1
        else:
            try:
                g = await client.get(glink)
                real = _gnews_real_url(glink, g.text)
                if real:
                    stats["links_via_html"] += 1
            except Exception:  # noqa: BLE001
                return ""
        if not real:
            return ""
        try:
            pr = await client.get(real)
            pr.raise_for_status()
            stats["pages_fetched"] += 1
            return _promo.html_to_text(pr.text)[:80_000]
        except Exception:  # noqa: BLE001
            return ""

    async with _httpx.AsyncClient(timeout=25, headers=ua,
                                  follow_redirects=True) as client:
        for query in V3_QUERIES:
            q = f"{query} when:{days}d"
            url = (f"https://news.google.com/rss/search?q={_qp(q)}"
                   "&hl=en-CA&gl=CA&ceid=CA:en")
            try:
                r = await client.get(url)
                r.raise_for_status()
                feed = _fp.parse(r.content)
            except Exception:  # noqa: BLE001
                continue
            for e in feed.entries:
                link = e.get("link", "")
                title = e.get("title", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                stats["headlines_seen"] += 1
                pub = (_dt(*e.published_parsed[:6])
                       if e.get("published_parsed") else None)
                if not pub or pub < cutoff:
                    continue
                # cheap pre-filter on the headline before doing network work
                tl = title.lower()
                if not any(k in tl for k in ("engag", "investor", "awareness",
                                             "marketing", "market making",
                                             "relations")):
                    continue
                text = await _resolve_and_fetch(client, link)
                if not text:
                    continue
                low = text.lower()
                if not any(h in low for h in MINING_HINTS):
                    stats["non_mining_skipped"] += 1
                    continue
                parsed = _promo.parse_promotion(text)
                if not parsed:
                    continue
                m = issuer_pat.search(text[:8000])
                if not m:
                    continue
                name = m.group(1).strip(" ,.")
                name = _re.split(r"\s[\-\u2013\u2014]{1,2}\s|--|\)\s", name)[-1].strip(" ,.-")
                ticker = m.group(3).upper()
                exchange = "TSXV" if "V" in m.group(2).upper().replace("TSX", "") \
                           or "VENTURE" in m.group(2).upper() else "TSX"
                if len(name) < 4:
                    continue
                c = db.execute(select(models.Company).where(
                    models.Company.ticker == ticker)).scalar_one_or_none()
                if not c:
                    c = models.Company(ticker=ticker, exchange=exchange,
                                       name=name, commodity="Unclassified",
                                       jurisdiction="", jurisdiction_tier="Tier 1",
                                       project_name="", shares_outstanding=0)
                    db.add(c)
                    db.flush()
                    stats["companies_added"].append(f"{ticker} ({name})")
                if not _title_mentions(c, title) and c.name.lower() not in low[:3000]:
                    continue
                _upsert_promotion(db, c.id, pub, title[:400], link[:400], parsed)
                stats["promotions_filed"] += 1
                stats["hits_by_ticker"][ticker] = stats["hits_by_ticker"].get(ticker, 0) + 1
                await _aio.sleep(0.2)
            await _aio.sleep(0.3)
    db.commit()
    promos = db.execute(select(models.Promotion)).scalars().all()
    stats["promotions_tracked_total"] = len(promos)
    return stats


# ---------------------------------------------------- promotion dedupe pass
@router.post("/api/admin/dedupe-promotions")
def dedupe_promotions(db: Session = Depends(get_db)):
    """Collapse syndicated copies: per company, promotions with the same firm,
    the same amount, or announced within 21 days of each other are one deal.
    Keeps the most complete row and merges fields from the copies."""
    from collections import defaultdict
    removed = 0
    by_company = defaultdict(list)
    for p in db.execute(select(models.Promotion)).scalars():
        by_company[p.company_id].append(p)
    for rows in by_company.values():
        rows.sort(key=lambda r: (r.amount is None, r.firm is None,
                                 -(r.announced.toordinal())))
        kept: list = []
        for r in rows:
            merged = False
            for k in kept:
                same_firm = bool(r.firm and k.firm and
                                 r.firm.lower() == k.firm.lower())
                same_amount = bool(r.amount and k.amount and
                                   abs(r.amount - k.amount) < 0.01 * k.amount + 1)
                close_dates = abs((k.announced - r.announced).days) <= 21
                if same_firm or same_amount or close_dates:
                    k.firm = k.firm or r.firm
                    k.amount = k.amount or r.amount
                    k.monthly_fee = k.monthly_fee or r.monthly_fee
                    k.term_months = k.term_months or r.term_months
                    k.ends = k.ends or r.ends
                    db.delete(r)
                    removed += 1
                    merged = True
                    break
            if not merged:
                kept.append(r)
    db.commit()
    remaining = len(db.execute(select(models.Promotion)).scalars().all())
    return {"duplicates_removed": removed, "promotions_remaining": remaining}


# ------------------------------------------------ company table dedupe + lock
@router.post("/api/admin/dedupe-companies")
def dedupe_companies(db: Session = Depends(get_db)):
    """Merge duplicate Company rows (same ticker): keep the oldest/most complete
    row, repoint every child record onto it, delete the rest, then create a
    UNIQUE index on ticker so duplicates are impossible from now on."""
    from collections import defaultdict
    from sqlalchemy import text as _text

    child_models = [models.DailyPrice, models.FinancialSnapshot,
                    models.WarrantTranche, models.PressRelease,
                    models.DrillResult, models.DrillProgram,
                    models.DilutionGrade, models.SharesHistory,
                    models.Financing, models.Promotion]

    by_ticker = defaultdict(list)
    for c in db.execute(select(models.Company)).scalars():
        by_ticker[c.ticker].append(c)

    merged = 0
    for ticker, rows in by_ticker.items():
        if len(rows) < 2:
            continue
        # keeper: most price history, then lowest id (oldest)
        def _weight(c):
            n = len(db.execute(select(models.DailyPrice.id).where(
                models.DailyPrice.company_id == c.id)).scalars().all())
            return (-n, c.id)
        rows.sort(key=_weight)
        keeper, dupes = rows[0], rows[1:]
        for d in dupes:
            if not keeper.name or keeper.name == keeper.ticker:
                keeper.name = d.name or keeper.name
            if keeper.commodity in (None, "", "Unclassified"):
                keeper.commodity = d.commodity or keeper.commodity
            for M in child_models:
                for child in db.execute(select(M).where(
                        M.company_id == d.id)).scalars():
                    child.company_id = keeper.id
            db.delete(d)
            merged += 1
        db.flush()
    db.commit()

    index_created = False
    try:
        db.execute(_text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_ticker "
            "ON companies (ticker)"))
        db.commit()
        index_created = True
    except Exception:  # noqa: BLE001
        db.rollback()

    remaining = len(db.execute(select(models.Company)).scalars().all())
    return {"duplicate_companies_merged": merged,
            "companies_remaining": remaining,
            "unique_index_created": index_created,
            "next": "run /api/admin/dedupe-promotions and "
                    "/api/admin/clean-misattributed to finish"}


# ------------------------------------------------- one-click full cleanup
@router.post("/api/admin/clean-all")
def clean_all(db: Session = Depends(get_db)):
    """Run every data-hygiene pass in order: company merge, misattribution
    purge + financing dedupe, promotion syndication dedupe."""
    report = {}
    report["companies"] = dedupe_companies(db)
    report["misattribution_and_financings"] = clean_misattributed(db)
    report["promotions"] = dedupe_promotions(db)
    return report


# --------------------------------------------- promotion scoreboard research
@router.get("/api/research/promotion-scoreboard")
def promotion_scoreboard(db: Session = Depends(get_db)):
    """What actually happens to promoted stocks: for every disclosed
    engagement, the stock's return from the announcement through the campaign
    and in the 30 days after it ends. Computed from OreLens's own registry
    and price history - the dataset nobody else has."""
    from statistics import median
    today = date.today()

    def _px_near(cid: int, day, direction: int = 1):
        """Closest close on/after (1) or on/before (-1) a date."""
        qy = select(models.DailyPrice).where(models.DailyPrice.company_id == cid)
        if direction == 1:
            qy = qy.where(models.DailyPrice.day >= day).order_by(models.DailyPrice.day)
        else:
            qy = qy.where(models.DailyPrice.day <= day).order_by(_desc(models.DailyPrice.day))
        row = db.execute(qy.limit(1)).scalar_one_or_none()
        return row.close if row else None

    rows, during_rets, after_rets = [], [], []
    for p in db.execute(select(models.Promotion)
                        .order_by(_desc(models.Promotion.announced))).scalars():
        c = db.get(models.Company, p.company_id)
        if not c:
            continue
        start_px = _px_near(c.id, p.announced, 1)
        if not start_px:
            continue
        end_day = min(p.ends, today) if p.ends else today
        end_px = _px_near(c.id, end_day, -1)
        during = (round(100 * (end_px - start_px) / start_px, 1)
                  if end_px and start_px else None)
        after = None
        if p.ends and p.ends < today:
            from datetime import timedelta as _td
            a_px = _px_near(c.id, p.ends + _td(days=30), -1)
            if a_px and end_px:
                after = round(100 * (a_px - end_px) / end_px, 1)
        if during is not None:
            during_rets.append(during)
        if after is not None:
            after_rets.append(after)
        rows.append({
            "ticker": c.ticker, "name": c.name,
            "announced": p.announced.isoformat(),
            "ends": p.ends and p.ends.isoformat(),
            "amount": p.amount,
            "return_during_pct": during,
            "return_30d_after_pct": after,
            "status": "ACTIVE" if (p.ends and p.ends >= today) or
                      (not p.ends and (today - p.announced).days <= 90) else "Ended",
        })

    summary = {
        "campaigns_analyzed": len(rows),
        "with_price_data": len(during_rets),
        "median_return_during_pct": round(median(during_rets), 1) if during_rets else None,
        "avg_return_during_pct": (round(sum(during_rets) / len(during_rets), 1)
                                  if during_rets else None),
        "median_return_30d_after_pct": (round(median(after_rets), 1)
                                        if after_rets else None),
        "campaigns_ended_with_after_data": len(after_rets),
        "note": ("After-campaign returns populate as campaigns end and prices "
                 "accrue for newly discovered issuers."),
    }
    return {"summary": summary, "campaigns": rows}


# ------------------------------------------------------- beta access gate
class BetaSignupBody(BaseModel):
    name: str
    email: str
    country_code: str
    phone: str
    account_size: str


@router.post("/api/beta/signup")
def beta_signup(body: BetaSignupBody, db: Session = Depends(get_db)):
    """Register a beta first-access lead and return the access token the
    client stores as a 45-day cookie. Re-submitting the same email returns
    the same token (people clear cookies)."""
    import re as _re
    import secrets as _secrets
    email = body.email.strip().lower()
    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"error": "Please enter a valid email address."}
    if not body.name.strip() or not body.phone.strip():
        return {"error": "Name and phone number are required."}
    existing = db.execute(select(models.BetaSignup).where(
        models.BetaSignup.email == email)).scalar_one_or_none()
    if existing:
        existing.name = body.name.strip()[:120]
        existing.country_code = body.country_code.strip()[:8]
        existing.phone = body.phone.strip()[:30]
        existing.account_size = body.account_size.strip()[:30]
        db.commit()
        return {"token": existing.token}
    token = _secrets.token_hex(24)
    db.add(models.BetaSignup(
        name=body.name.strip()[:120], email=email,
        country_code=body.country_code.strip()[:8],
        phone=body.phone.strip()[:30],
        account_size=body.account_size.strip()[:30], token=token))
    db.commit()
    return {"token": token}


@router.get("/api/admin/beta-signups")
def beta_signups(db: Session = Depends(get_db)):
    """The beta lead list: name, email, phone with country code, account
    size, signup date. This is the asset the gate exists to build."""
    rows = db.execute(select(models.BetaSignup)
                      .order_by(_desc(models.BetaSignup.created))).scalars().all()
    return {"count": len(rows), "signups": [
        {"name": r.name, "email": r.email,
         "phone": f"{r.country_code} {r.phone}",
         "account_size": r.account_size,
         "signed_up": r.created.isoformat()} for r in rows]}


# ------------------------------------------- EODHD raw-response debug probe
@router.post("/api/admin/eodhd-debug")
def eodhd_debug(ticker: str = "VZLA"):
    """Capture EODHD's raw replies for the failing endpoints, several variants
    at once, so we can see exactly what the API says from this server."""
    import httpx as _hx
    from datetime import date as _d, timedelta as _t
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"key_present": False}
    frm = (_d.today() - _t(days=185)).isoformat()
    probes = {
        "eod_V_with_period": (f"https://eodhd.com/api/eod/{ticker}.V",
                              {"period": "d", "from": frm}),
        "eod_V_no_period": (f"https://eodhd.com/api/eod/{ticker}.V",
                            {"from": frm}),
        "eod_TO_variant": (f"https://eodhd.com/api/eod/{ticker}.TO",
                           {"from": frm}),
        "news_V": ("https://eodhd.com/api/news",
                   {"s": f"{ticker}.V", "limit": 3}),
        "news_US": ("https://eodhd.com/api/news",
                    {"s": f"{ticker}.US", "limit": 3}),
    }
    out = {}
    for name, (url, params) in probes.items():
        try:
            r = _hx.get(url, params={**params, "api_token": _s.eodhd_api_key,
                                     "fmt": "json"}, timeout=25)
            body = r.text[:400]
            out[name] = {"status": r.status_code, "body_start": body}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)[:200]}
    return out


# ------------------------------------------------- EODHD engine self-test
@router.post("/api/admin/eodhd-selftest")
def eodhd_selftest(ticker: str = "VZLA", exchange: str = "TSXV"):
    """Validate the EODHD engine against a real symbol from this server."""
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"key_present": False,
                "fix": "Add EODHD_API_KEY in Render -> orelens-api -> Environment"}
    from .services import eodhd as _e
    d = _e.fetch_company_data(ticker, exchange, "6mo")
    news = _e.fetch_news(ticker, exchange, days=14)
    return {
        "key_present": True, "symbol": _e._symbol(ticker, exchange),
        "price_days": len(d["prices"]),
        "latest_price_day": d["prices"][-1]["date"].isoformat() if d["prices"] else None,
        "shares_outstanding": d["shares_outstanding"],
        "cash_latest": d["cash"], "monthly_burn": d["monthly_burn"],
        "cash_quarters": len(d["cash_history"]),
        "shares_quarters": len(d["shares_history"]),
        "financing_cf_quarters": len(d["financing_cf_history"]),
        "sector": d["sector"], "industry": d["industry"],
        "news_items_14d": len(news),
        "news_sample": [n["headline"][:80] for n in news[:3]],
    }


# ---------------------------------------------- EODHD deep-history backfill
_DEEP_STATUS: dict = {"state": "idle"}


def _run_deep_backfill(years: int) -> None:
    """Background worker: multi-year prices + full quarterly record for every
    company, exchange self-heal persisted, then a re-grade."""
    from .db import SessionLocal
    from .jobs.nightly import run_grades
    db = SessionLocal()
    stats = {"state": "running", "companies_done": 0, "companies_total": 0,
             "price_rows_added": 0, "cash_quarters_added": 0,
             "shares_quarters_added": 0, "exchanges_fixed": [],
             "commodities_filled": 0, "no_data": []}
    _DEEP_STATUS.clear(); _DEEP_STATUS.update(stats)
    try:
        period = f"{min(years, 10)}y"
        companies = db.execute(select(models.Company)).scalars().all()
        stats["companies_total"] = len(companies)
        for c in companies:
            try:
                data = marketdata.fetch_company_data(c.ticker, c.exchange, period)
            except Exception:  # noqa: BLE001
                stats["no_data"].append(c.ticker)
                continue
            if not data["prices"]:
                stats["no_data"].append(c.ticker)
                stats["companies_done"] += 1
                _DEEP_STATUS.update(stats)
                continue
            if data.get("resolved_exchange") and data["resolved_exchange"] != c.exchange:
                stats["exchanges_fixed"].append(
                    f"{c.ticker}: {c.exchange} -> {data['resolved_exchange']}")
                c.exchange = data["resolved_exchange"]
            if data.get("shares_outstanding"):
                c.shares_outstanding = data["shares_outstanding"]
            if c.commodity in (None, "", "Unclassified") and data.get("industry"):
                c.commodity = (data["industry"] or "")[:40] or c.commodity
                stats["commodities_filled"] += 1
            have_days = {p.day for p in db.execute(select(models.DailyPrice).where(
                models.DailyPrice.company_id == c.id)).scalars()}
            for row in data["prices"]:
                if row["date"] not in have_days:
                    db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                             close=row["close"], volume=row["volume"]))
                    stats["price_rows_added"] += 1
            have_fs = {s.as_of for s in db.execute(select(models.FinancialSnapshot).where(
                models.FinancialSnapshot.company_id == c.id)).scalars()}
            for ch in data["cash_history"]:
                if ch["as_of"] not in have_fs:
                    db.add(models.FinancialSnapshot(
                        company_id=c.id, as_of=ch["as_of"], cash=ch["cash"],
                        monthly_burn=data.get("monthly_burn") or 0.0,
                        source_filing="EODHD quarterly balance sheet (SEDAR-sourced)"))
                    stats["cash_quarters_added"] += 1
            have_sh = {s.as_of for s in db.execute(select(models.SharesHistory).where(
                models.SharesHistory.company_id == c.id)).scalars()}
            for sh in data["shares_history"]:
                if sh["as_of"] not in have_sh:
                    db.add(models.SharesHistory(company_id=c.id, as_of=sh["as_of"],
                                                shares=sh["shares"]))
                    stats["shares_quarters_added"] += 1
            db.commit()
            stats["companies_done"] += 1
            _DEEP_STATUS.update(stats)
        run_grades(db)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        stats["state"] = "error"
        stats["error"] = str(exc)[:300]
        db.rollback()
    finally:
        db.close()
        _DEEP_STATUS.update(stats)


@router.post("/api/admin/backfill-deep-history")
def backfill_deep_history(years: int = 5):
    """Kick off the deep-history upgrade in the background (it runs for
    several minutes) and return immediately. Poll backfill-deep-status."""
    import threading
    if _DEEP_STATUS.get("state") == "running":
        return {"started": False, "reason": "already running",
                "progress": _DEEP_STATUS}
    threading.Thread(target=_run_deep_backfill, args=(years,),
                     daemon=True).start()
    return {"started": True, "years": years,
            "check_progress": "GET /api/admin/backfill-deep-status"}


@router.get("/api/admin/backfill-deep-status")
def backfill_deep_status():
    return _DEEP_STATUS



# ------------------------------------------------- EODHD engine self-test
@router.post("/api/admin/eodhd-selftest")
def eodhd_selftest(ticker: str = "VZLA", exchange: str = "TSXV"):
    """Validate the EODHD engine against a real symbol from this server."""
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"key_present": False,
                "fix": "Add EODHD_API_KEY in Render -> orelens-api -> Environment"}
    from .services import eodhd as _e
    d = _e.fetch_company_data(ticker, exchange, "6mo")
    news = _e.fetch_news(ticker, exchange, days=14)
    return {
        "key_present": True, "symbol": _e._symbol(ticker, exchange),
        "price_days": len(d["prices"]),
        "latest_price_day": d["prices"][-1]["date"].isoformat() if d["prices"] else None,
        "shares_outstanding": d["shares_outstanding"],
        "cash_latest": d["cash"], "monthly_burn": d["monthly_burn"],
        "cash_quarters": len(d["cash_history"]),
        "shares_quarters": len(d["shares_history"]),
        "financing_cf_quarters": len(d["financing_cf_history"]),
        "sector": d["sector"], "industry": d["industry"],
        "news_items_14d": len(news),
        "news_sample": [n["headline"][:80] for n in news[:3]],
    }


# ---------------------------------------------- EODHD deep-history backfill
@router.post("/api/admin/backfill-deep-history")
async def backfill_deep_history(years: int = 5, db: Session = Depends(get_db)):
    """The upgrade run: re-pull every tracked company through the licensed
    engine with multi-year price history and the FULL quarterly cash/share
    record, persist everything, fix stale exchanges, then re-grade."""
    from starlette.concurrency import run_in_threadpool
    period = f"{min(years, 10)}y"
    stats = {"companies": 0, "price_rows_added": 0, "cash_quarters_added": 0,
             "shares_quarters_added": 0, "exchanges_fixed": [],
             "sectors_filled": 0, "no_data": []}
    companies = db.execute(select(models.Company)).scalars().all()
    for c in companies:
        data = await run_in_threadpool(marketdata.fetch_company_data,
                                       c.ticker, c.exchange, period)
        if not data["prices"]:
            stats["no_data"].append(c.ticker)
            continue
        stats["companies"] += 1
        if data.get("resolved_exchange") and data["resolved_exchange"] != c.exchange:
            stats["exchanges_fixed"].append(f"{c.ticker}: {c.exchange} -> {data['resolved_exchange']}")
            c.exchange = data["resolved_exchange"]
        if data.get("shares_outstanding"):
            c.shares_outstanding = data["shares_outstanding"]
        if c.commodity in (None, "", "Unclassified") and data.get("industry"):
            c.commodity = (data["industry"] or "")[:40] or c.commodity
            stats["sectors_filled"] += 1
        have_days = {p.day for p in db.execute(select(models.DailyPrice).where(
            models.DailyPrice.company_id == c.id)).scalars()}
        for row in data["prices"]:
            if row["date"] not in have_days:
                db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                         close=row["close"], volume=row["volume"],
                                         open=row.get("open"), high=row.get("high"),
                                         low=row.get("low")))
                stats["price_rows_added"] += 1
        have_fs = {s.as_of for s in db.execute(select(models.FinancialSnapshot).where(
            models.FinancialSnapshot.company_id == c.id)).scalars()}
        for ch in data["cash_history"]:
            if ch["as_of"] not in have_fs:
                db.add(models.FinancialSnapshot(
                    company_id=c.id, as_of=ch["as_of"], cash=ch["cash"],
                    monthly_burn=data.get("monthly_burn") or 0.0,
                    source_filing="EODHD quarterly balance sheet (SEDAR-sourced)"))
                stats["cash_quarters_added"] += 1
        have_sh = {s.as_of for s in db.execute(select(models.SharesHistory).where(
            models.SharesHistory.company_id == c.id)).scalars()}
        for sh in data["shares_history"]:
            if sh["as_of"] not in have_sh:
                db.add(models.SharesHistory(company_id=c.id, as_of=sh["as_of"],
                                            shares=sh["shares"]))
                stats["shares_quarters_added"] += 1
        db.commit()
    from .jobs.nightly import run_grades
    run_grades(db)
    return stats


# ============================ DILUTION INTELLIGENCE SCANNERS (EODHD-era) ====
def _latest_fin(db, cid):
    return db.execute(select(models.FinancialSnapshot).where(
        models.FinancialSnapshot.company_id == cid)
        .order_by(_desc(models.FinancialSnapshot.as_of)).limit(1)).scalar_one_or_none()


def _px_series(db, cid, days=400):
    from datetime import timedelta as _td
    cutoff = date.today() - _td(days=days)
    return db.execute(select(models.DailyPrice).where(
        models.DailyPrice.company_id == cid,
        models.DailyPrice.day >= cutoff)
        .order_by(models.DailyPrice.day)).scalars().all()


def _grade_of(db, cid):
    g = db.execute(select(models.DilutionGrade).where(
        models.DilutionGrade.company_id == cid)
        .order_by(_desc(models.DilutionGrade.day)).limit(1)).scalar_one_or_none()
    return g.grade if g else None


def _shares_hist(db, cid):
    return db.execute(select(models.SharesHistory).where(
        models.SharesHistory.company_id == cid)
        .order_by(models.SharesHistory.as_of)).scalars().all()


def _raise_events(hist, years=3):
    """Quarters where shares outstanding jumped >=2% = an issuance event."""
    from datetime import timedelta as _td
    cutoff = date.today() - _td(days=int(years * 365.25))
    events = []
    for prev, cur in zip(hist, hist[1:]):
        if cur.as_of < cutoff or not prev.shares:
            continue
        pct = 100 * (cur.shares - prev.shares) / prev.shares
        if pct >= 2.0:
            events.append({"date": cur.as_of, "pct": round(pct, 1),
                           "shares_added": cur.shares - prev.shares})
    return events




def _burn_runway(db, cid):
    """Single source of truth for burn and runway. Burn priority:
    (1) OCF-derived from the latest snapshot; (2) estimated from the cash
    decline itself when OCF burn is missing/zero but the treasury is visibly
    shrinking (zero-burn-with-falling-cash is a contradiction, not a fact).
    Raise signals cover BOTH closed and merely announced financings."""
    from datetime import timedelta as _td
    snaps = db.execute(select(models.FinancialSnapshot).where(
        models.FinancialSnapshot.company_id == cid)
        .order_by(models.FinancialSnapshot.as_of)).scalars().all()
    if not snaps:
        return None
    fin = snaps[-1]
    burn, source = (fin.monthly_burn, "ocf") if fin.monthly_burn else (None, None)
    if not burn:
        declines = []
        for a, b in zip(snaps[-8:], snaps[-8:][1:]):
            if a.cash and b.cash and b.cash < a.cash:
                q_days = max((b.as_of - a.as_of).days, 30)
                declines.append((a.cash - b.cash) / (q_days / 30.4))
        if len(declines) >= 2:
            declines.sort()
            burn = round(declines[len(declines) // 2], 0)
            source = "cash-trend"
    runway = (fin.cash / burn) if (fin.cash and burn) else None
    closed_amt, closed_date, announced_amt, announced_date = 0.0, None, 0.0, None
    cutoff = date.today() - _td(days=120)
    from .services.attribution import source_names_company as _names_co
    _co = db.get(models.Company, cid)
    for r in db.execute(select(models.Financing).where(
            models.Financing.company_id == cid)).scalars():
        # A dated raise is an assertion about this issuer. If the source
        # headline doesn't name them, we don't claim it happened.
        if _co and r.headline and not _names_co(r.headline, _co.ticker,
                                                _co.name, _co.exchange):
            continue
        if r.closed and r.close_date and r.close_date > fin.as_of:
            closed_amt += (r.amount or 0)
            closed_date = max(closed_date or r.close_date, r.close_date)
        elif not r.closed and r.announced and r.announced >= cutoff:
            announced_amt += (r.amount or 0)
            announced_date = max(announced_date or r.announced, r.announced)
    adj_cash = (fin.cash or 0) + closed_amt
    adj_runway = (adj_cash / burn) if burn and adj_cash else runway
    return {"fin": fin, "burn": burn, "burn_source": source,
            "runway": runway, "closed_amt": closed_amt,
            "closed_date": closed_date, "announced_amt": announced_amt,
            "announced_date": announced_date,
            "adj_cash": adj_cash, "adj_runway": adj_runway}


def _raises_since(db, cid, since):
    """Closed financings with close_date after `since` - the money the
    quarterly snapshot doesn't know about yet (the PNPN problem)."""
    rows = db.execute(select(models.Financing).where(
        models.Financing.company_id == cid,
        models.Financing.closed.is_(True),
        models.Financing.close_date.is_not(None),
        models.Financing.close_date > since)).scalars().all()
    total = sum(r.amount for r in rows if r.amount)
    latest = max((r.close_date for r in rows), default=None)
    return total, latest, len(rows)


@router.get("/api/scanners/dilution-risk")
def dilution_risk(commodity: str | None = None, tier: str | None = None,
                  db: Session = Depends(get_db)):
    """Highest probability of a dilutive raise: short runway, shrinking cash,
    habitual issuance, and a beaten-down price all push the score up."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        br = _burn_runway(db, c.id)
        if not br or not br["fin"].cash:
            continue
        fin = br["fin"]
        score, why = 0, []
        runway = br["runway"]
        if runway is not None:
            if runway <= 3:
                score += 40; why.append(f"{runway:.0f}mo runway")
            elif runway <= 6:
                score += 30; why.append(f"{runway:.0f}mo runway")
            elif runway <= 12:
                score += 15; why.append(f"{runway:.0f}mo runway")
        hist = _shares_hist(db, c.id)
        events = _raise_events(hist, years=3)
        if len(events) >= 5:
            score += 25; why.append(f"{len(events)} raises in 3y")
        elif len(events) >= 3:
            score += 15; why.append(f"{len(events)} raises in 3y")
        snaps = db.execute(select(models.FinancialSnapshot).where(
            models.FinancialSnapshot.company_id == c.id)
            .order_by(_desc(models.FinancialSnapshot.as_of)).limit(4)).scalars().all()
        cash_seq = [s.cash for s in reversed(snaps) if s.cash is not None]
        if len(cash_seq) >= 3 and all(b < a for a, b in zip(cash_seq, cash_seq[1:])):
            score += 15; why.append("cash shrinking 3+ quarters")
        px = _px_series(db, c.id, 370)
        if px:
            closes = [p.close for p in px]
            lo, last = min(closes), closes[-1]
            if lo and last <= lo * 1.20:
                score += 10; why.append("near 52w low")
        # news-aware, both flavors: a CLOSED raise refills the treasury;
        # an ANNOUNCED raise means the dilution question is already answered.
        adj_runway = br["adj_runway"]
        label_override = None
        if br["closed_amt"]:
            score = max(0, score - 35)
            why.append(f"but raised ${br['closed_amt']/1e6:.1f}M on "
                       f"{br['closed_date']} (post-dates cash figure)")
        if br["announced_amt"] or (br["announced_date"] and not br["announced_amt"]):
            score = max(0, score - 35)
            label_override = "RAISE ANNOUNCED"
            amt_txt = (f"~${br['announced_amt']/1e6:.1f}M "
                       if br["announced_amt"] else "")
            why.append(f"raise {amt_txt}announced {br['announced_date']} - "
                       "dilution already in motion")
        if score < 15:
            continue
        prob = label_override or ("VERY HIGH" if score >= 60 else
                "HIGH" if score >= 40 else "ELEVATED" if score >= 25
                else "MODERATE")
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "score": score, "probability": prob,
            "runway_m": adj_runway and round(adj_runway, 1),
            "cash_m": round(br["adj_cash"] / 1e6, 1),
            "raises_3y": len(events),
            "why": " - ".join(why), "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: -x["score"])
    return _drop_stale(db, out)


@router.get("/api/scanners/burn-league")
def burn_league(commodity: str | None = None, tier: str | None = None,
                db: Session = Depends(get_db)):
    """True burn, ranked: operating-cash-flow burn per month and the real
    runway it implies. The shortest fuses at the top."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        br = _burn_runway(db, c.id)
        if not br or not br["burn"] or not br["fin"].cash:
            continue
        fin = br["fin"]
        as_of = fin.as_of.isoformat()
        if br["burn_source"] == "cash-trend":
            as_of += " (burn est. from cash decline)"
        if br["closed_amt"]:
            as_of += f" + raise {br['closed_date']}"
        if br["announced_amt"]:
            as_of += f" | raise ANNOUNCED {br['announced_date']}"
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "monthly_burn": round(br["burn"], 0),
            "cash_m": round(br["adj_cash"] / 1e6, 1),
            "raised_since_m": br["closed_amt"] and round(br["closed_amt"] / 1e6, 1),
            "runway_m": round(br["adj_runway"], 1),
            "as_of": as_of,
            "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: x["runway_m"])
    return _drop_stale(db, out)


@router.get("/api/scanners/serial-raisers")
def serial_raisers(commodity: str | None = None, tier: str | None = None,
                   db: Session = Depends(get_db)):
    """Who taps the market like clockwork: share-issuance events (quarters
    with a >=2% jump in shares out) over the last 3 years, from filings."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        hist = _shares_hist(db, c.id)
        if len(hist) < 4:
            continue
        events = _raise_events(hist, years=3)
        if not events:
            continue
        first, last = hist[0], hist[-1]
        total_growth = (100 * (last.shares - first.shares) / first.shares
                        if first.shares else None)
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "raises_3y": len(events),
            "raises_per_year": round(len(events) / 3.0, 1),
            "last_raise": events[-1]["date"].isoformat(),
            "last_raise_pct": events[-1]["pct"],
            "shares_growth_pct": total_growth and round(total_growth, 0),
            "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: (-x["raises_3y"], x["ticker"]))
    return _drop_stale(db, out)


@router.get("/api/scanners/bullish-setups")
def bullish_setups(commodity: str | None = None, tier: str | None = None,
                   db: Session = Depends(get_db)):
    """Strength with a clean structure: uptrend (price > 50d > 200d), volume
    building, near the 52-week high, a year-plus of runway so no raise looms,
    and minimal trailing dilution."""
    out = []
    for c in db.execute(select(models.Company)).scalars():
        if (commodity and c.commodity != commodity) or \
           (tier and c.jurisdiction_tier != tier):
            continue
        px = _px_series(db, c.id, 400)
        if len(px) < 60:
            continue
        closes = [p.close for p in px]
        vols = [p.volume or 0 for p in px]
        last = closes[-1]
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        hi52 = max(closes)
        v20 = sum(vols[-20:]) / 20
        v60 = sum(vols[-60:]) / 60 if len(vols) >= 60 else v20
        ret60 = (100 * (last - closes[-60]) / closes[-60]
                 if len(closes) >= 60 and closes[-60] else 0)
        score, why = 0, []
        if last > ma50:
            score += 20; why.append("above 50d")
        if ma200 and ma50 > ma200:
            score += 15; why.append("50d > 200d")
        if hi52 and last >= hi52 * 0.80:
            score += 20; why.append("within 20% of 52w high")
        if v60 and v20 > v60 * 1.15:
            score += 15; why.append("volume building")
        if ret60 > 15:
            score += 10; why.append(f"+{ret60:.0f}% in 60d")
        fin = _latest_fin(db, c.id)
        runway = (fin.cash / fin.monthly_burn
                  if fin and fin.cash and fin.monthly_burn else None)
        if runway and runway >= 12:
            score += 15; why.append(f"{runway:.0f}mo runway")
        hist = _shares_hist(db, c.id)
        events_1y = [e for e in _raise_events(hist, years=1)]
        if not events_1y:
            score += 5; why.append("no dilution 12mo")
        if score < 55:
            continue
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "price": round(last, 2), "score": score,
            "ret_60d_pct": round(ret60, 1),
            "off_high_pct": hi52 and round(100 * (hi52 - last) / hi52, 1),
            "runway_m": runway and round(runway, 1),
            "why": " - ".join(why), "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: -x["score"])
    return _drop_stale(db, out)


# ------------------------------------------------ EODHD news refresh (mining)
_NEWS_STATUS: dict = {"state": "idle"}


def _run_news_refresh(days: int, purge_bunched: bool,
                      trigger: str = "manual") -> None:
    from collections import Counter
    from .db import SessionLocal
    from .config import settings as _s
    from .services import eodhd as _e
    from .services import financing as _finmod
    from .services import promotion as _promo
    from .jobs.nightly import _upsert_financing, _upsert_promotion
    db = SessionLocal()
    from datetime import datetime as _dtt
    stats = {"state": "running", "trigger": trigger,
             "started_at": _dtt.utcnow().isoformat(timespec="seconds"),
             "companies_done": 0, "companies_total": 0,
             "news_stored": 0, "bunched_rows_purged": 0,
             "financings_detected": 0, "promotions_detected": 0}
    _NEWS_STATUS.clear(); _NEWS_STATUS.update(stats)
    try:
        if purge_bunched:
            stamps = Counter()
            rows = db.execute(select(models.PressRelease).where(
                models.PressRelease.wire.like("Newsfile%"))).scalars().all()
            for r in rows:
                if r.published:
                    stamps[r.published.replace(microsecond=0)] += 1
            bad = {s for s, n in stamps.items() if n >= 8}
            for r in rows:
                if r.published and r.published.replace(microsecond=0) in bad:
                    db.delete(r)
                    stats["bunched_rows_purged"] += 1
            db.commit()

        # one article often tags several tickers - dedupe across the whole run
        # (keys truncated to 400 chars to exactly match what the DB stores)
        seen_urls = {u[:400] for (u,) in
                     db.execute(select(models.PressRelease.url))}
        companies = db.execute(select(models.Company)).scalars().all()
        stats["companies_total"] = len(companies)
        for c in companies:
            try:
                items = _e.fetch_news(c.ticker, c.exchange, days, 20)
            except Exception:  # noqa: BLE001
                items = []
            core = _core_name(c.name)
            for item in items:
                if item["url"][:400] in seen_urls:
                    continue
                text = f"{item['headline']} {item['summary']}"
                low = text.lower()
                # attribution guard: ticker collisions across exchanges (e.g.
                # CNC.V Canada Nickel vs CNC NYSE Centene) mean a per-ticker
                # feed can carry a stranger's news. Store only if the article
                # names the company or plainly reads as mining.
                if core not in low and not any(h in low for h in MINING_HINTS):
                    continue
                seen_urls.add(item["url"][:400])
                db.add(models.PressRelease(
                    company_id=c.id, published=item["published"],
                    headline=item["headline"][:400], url=item["url"][:400],
                    wire="EODHD", body=item["summary"], is_drill_start=False))
                stats["news_stored"] += 1
                fpar = _finmod.parse_financing(text)
                if fpar:
                    _upsert_financing(db, c.id, item["published"],
                                      item["headline"][:400], item["url"][:400], fpar)
                    stats["financings_detected"] += 1
                ppar = _promo.parse_promotion(text)
                if ppar:
                    _upsert_promotion(db, c.id, item["published"],
                                      item["headline"][:400], item["url"][:400], ppar)
                    stats["promotions_detected"] += 1
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                # a racing run inserted the same article first - drop just
                # this company's batch and keep the pipeline moving
                db.rollback()
            stats["companies_done"] += 1
            _NEWS_STATUS.update(stats)
        stats["state"] = "done"
        stats["press_releases_total"] = len(
            db.execute(select(models.PressRelease)).scalars().all())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"
        stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _NEWS_STATUS.update(stats)


@router.post("/api/admin/refresh-news")
def refresh_news(days: int = 30, purge_bunched: bool = True):
    """Kick off the licensed-news refresh in the background and return
    immediately. Poll refresh-news-status for progress."""
    import threading
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"error": "EODHD_API_KEY not configured"}
    if _NEWS_STATUS.get("state") == "running":
        return {"started": False, "reason": "already running",
                "progress": _NEWS_STATUS}
    threading.Thread(target=_run_news_refresh, args=(days, purge_bunched),
                     daemon=True).start()
    return {"started": True, "days": days,
            "check_progress": "GET /api/admin/refresh-news-status"}


@router.get("/api/admin/refresh-news-status")
def refresh_news_status():
    return _NEWS_STATUS


@router.post("/api/admin/clean-news")
def clean_news(db: Session = Depends(get_db)):
    """Purge stored news that fails attribution: doesn't name its company and
    doesn't read as mining (ticker-collision fallout like CNC/Centene)."""
    removed = 0
    companies = {c.id: c for c in db.execute(select(models.Company)).scalars()}
    for r in db.execute(select(models.PressRelease).where(
            models.PressRelease.wire == "EODHD")).scalars().all():
        c = companies.get(r.company_id)
        if not c:
            continue
        low = f"{r.headline} {r.body or ''}".lower()
        if _core_name(c.name) not in low and not any(h in low for h in MINING_HINTS):
            db.delete(r)
            removed += 1
    db.commit()
    return {"unrelated_news_removed": removed}


# --------------------------------------------- universe expansion (US + CA)
US_MINERS = [
    ("NEM","NYSE","Newmont Corporation","Gold"),("GOLD","NYSE","Barrick Gold","Gold"),
    ("AEM","NYSE","Agnico Eagle Mines","Gold"),("KGC","NYSE","Kinross Gold","Gold"),
    ("AU","NYSE","AngloGold Ashanti","Gold"),("GFI","NYSE","Gold Fields","Gold"),
    ("HMY","NYSE","Harmony Gold","Gold"),("EGO","NYSE","Eldorado Gold","Gold"),
    ("IAG","NYSE","IAMGOLD","Gold"),("BTG","NYSE","B2Gold","Gold"),
    ("AGI","NYSE","Alamos Gold","Gold"),("OR","NYSE","Osisko Gold Royalties","Gold"),
    ("WPM","NYSE","Wheaton Precious Metals","Silver"),("FNV","NYSE","Franco-Nevada","Gold"),
    ("RGLD","NASDAQ","Royal Gold","Gold"),("SAND","NYSE","Sandstorm Gold","Gold"),
    ("PAAS","NYSE","Pan American Silver","Silver"),("AG","NYSE","First Majestic Silver","Silver"),
    ("HL","NYSE","Hecla Mining","Silver"),("CDE","NYSE","Coeur Mining","Silver"),
    ("EXK","NYSE","Endeavour Silver","Silver"),("FSM","NYSE","Fortuna Mining","Silver"),
    ("MAG","NYSE","MAG Silver","Silver"),("SILV","NYSE","SilverCrest Metals","Silver"),
    ("GATO","NYSE","Gatos Silver","Silver"),("USAS","NYSE","Americas Gold and Silver","Silver"),
    ("FCX","NYSE","Freeport-McMoRan","Copper"),("SCCO","NYSE","Southern Copper","Copper"),
    ("ERO","NYSE","Ero Copper","Copper"),("HBM","NYSE","Hudbay Minerals","Copper"),
    ("TGB","NYSE","Taseko Mines","Copper"),("CCJ","NYSE","Cameco","Uranium"),
    ("UEC","NYSE","Uranium Energy Corp","Uranium"),("DNN","NYSE","Denison Mines","Uranium"),
    ("NXE","NYSE","NexGen Energy","Uranium"),("UUUU","NYSE","Energy Fuels","Uranium"),
    ("URG","NYSE","Ur-Energy","Uranium"),("LAC","NYSE","Lithium Americas","Lithium"),
    ("PLL","NASDAQ","Piedmont Lithium","Lithium"),("SGML","NASDAQ","Sigma Lithium","Lithium"),
    ("MP","NYSE","MP Materials","Rare Earths"),("TMC","NASDAQ","TMC the metals company","Nickel"),
    ("VALE","NYSE","Vale","Iron Ore"),("RIO","NYSE","Rio Tinto","Diversified"),
    ("BHP","NYSE","BHP Group","Diversified"),("TECK","NYSE","Teck Resources","Diversified"),
    ("EQX","NYSE","Equinox Gold","Gold"),
    ("SSRM","NASDAQ","SSR Mining","Gold"),("ORLA","NYSE","Orla Mining","Gold"),
    ("SKE","NYSE","Skeena Resources","Gold"),("ITRG","NYSE","Integra Resources","Gold"),
    ("IDR","NYSE","Idaho Strategic Resources","Gold"),("PPTA","NASDAQ","Perpetua Resources","Gold"),
    ("VZLA","NYSE","Vizsla Silver","Silver"),
    ("SEA","TSX","Seabridge Gold","Gold"),("MND","TSX","Mandalay Resources","Gold"),
    ("KNT","TSXV","K92 Mining","Gold"),("ARIS","TSX","Aris Mining","Gold"),
    ("LUG","TSX","Lundin Gold","Gold"),("MOZ","TSX","Marathon Gold","Gold"),
    # ---- wave 2: NYSE/NASDAQ juniors + mid-tiers, TSX heavyweights ----
    ("MUX","NYSE","McEwen Mining","Gold"),("NG","NYSE","NovaGold Resources","Gold"),
    ("NAK","NYSE","Northern Dynasty Minerals","Copper"),("CGAU","NYSE","Centerra Gold","Gold"),
    ("BVN","NYSE","Compania de Minas Buenaventura","Gold"),("DRD","NYSE","DRDGold","Gold"),
    ("SBSW","NYSE","Sibanye Stillwater","PGE"),("CMCL","NYSE","Caledonia Mining","Gold"),
    ("ASM","NYSE","Avino Silver & Gold Mines","Silver"),("SVM","NYSE","Silvercorp Metals","Silver"),
    ("GLDG","NYSE","GoldMining Inc","Gold"),("PZG","NYSE","Paramount Gold Nevada","Gold"),
    ("VGZ","NYSE","Vista Gold","Gold"),("THM","NYSE","International Tower Hill Mines","Gold"),
    ("TRX","NYSE","TRX Gold","Gold"),("GAU","NYSE","Galiano Gold","Gold"),
    ("USAU","NASDAQ","US Gold Corp","Gold"),("USGO","NASDAQ","US GoldMining","Gold"),
    ("GORO","NYSE","Gold Resource Corporation","Gold"),("XPL","NYSE","Solitario Resources","Zinc"),
    ("MTA","NYSE","Metalla Royalty & Streaming","Royalty"),("TFPM","NYSE","Triple Flag Precious Metals","Royalty"),
    ("UROY","NASDAQ","Uranium Royalty Corp","Uranium"),("EU","NYSE","enCore Energy","Uranium"),
    ("LEU","NYSE","Centrus Energy","Uranium"),("IE","NYSE","Ivanhoe Electric","Copper"),
    ("TMQ","NYSE","Trilogy Metals","Copper"),("WRN","NYSE","Western Copper and Gold","Copper"),
    ("SLI","NYSE","Standard Lithium","Lithium"),("ABAT","NASDAQ","American Battery Technology","Lithium"),
    ("LITM","NASDAQ","Snow Lake Resources","Lithium"),("NB","NASDAQ","NioCorp Developments","Rare Earths"),
    ("UAMY","NYSE","United States Antimony","Antimony"),("TMRC","NASDAQ","Texas Mineral Resources","Rare Earths"),
    ("NEXA","NYSE","Nexa Resources","Zinc"),("AA","NYSE","Alcoa Corporation","Diversified"),
    ("CLF","NYSE","Cleveland-Cliffs","Iron Ore"),("BTU","NYSE","Peabody Energy","Coal"),
    ("AMR","NYSE","Alpha Metallurgical Resources","Coal"),("HCC","NYSE","Warrior Met Coal","Coal"),
    ("EDV","TSX","Endeavour Mining","Gold"),("TXG","TSX","Torex Gold Resources","Gold"),
    ("OGC","TSX","OceanaGold","Gold"),("WDO","TSX","Wesdome Gold Mines","Gold"),
    ("ABRA","TSX","AbraSilver Resource","Silver"),("DSV","TSX","Discovery Silver","Silver"),
    ("FCU","TSX","Fission Uranium","Uranium"),("GLO","TSX","Global Atomic","Uranium"),
    ("MGA","TSX","Mega Uranium","Uranium"),("NGEX","TSX","NGEx Minerals","Copper"),
    ("LUN","TSX","Lundin Mining","Copper"),("FM","TSX","First Quantum Minerals","Copper"),
    ("CS","TSX","Capstone Copper","Copper"),("III","TSX","Imperial Metals","Copper"),
    ("AAUC","TSX","Allied Gold","Gold"),
    ("HYMC","NASDAQ","Hycroft Mining","Gold"),("AUST","NYSE","Austin Gold","Gold"),
    ("LODE","NYSE","Comstock Inc","Gold"),("GROY","NYSE","Gold Royalty Corp","Royalty"),
    ("LTBR","NASDAQ","Lightbridge Corporation","Uranium"),("IONR","NASDAQ","ioneer Ltd","Lithium"),
    ("PLG","NYSE","Platinum Group Metals","PGE"),("IPX","NASDAQ","IperionX","Rare Earths"),
    ("METC","NASDAQ","Ramaco Resources","Coal"),("NRP","NYSE","Natural Resource Partners","Coal"),
    ("ODV","TSXV","Osisko Development","Gold"),("GMIN","TSX","G Mining Ventures","Gold"),
    ("PRYM","TSXV","Prime Mining","Gold"),("AMX","TSXV","Amex Exploration","Gold"),
    ("SLS","TSX","Solaris Resources","Copper"),("MAI","TSXV","Minera Alamos","Gold"),
    ("ORE","TSX","Orezone Gold","Gold"),("RUP","TSX","Rupert Resources","Gold"),
    ("TUD","TSXV","Tudor Gold","Gold"),("GGD","TSX","GoGold Resources","Silver"),
    ("SGD","TSXV","Snowline Gold","Gold"),("DPM","TSX","Dundee Precious Metals","Gold"),
    ("WM","TSXV","Wallbridge Mining","Gold"),("HSTR","TSXV","Heliostar Metals","Gold"),
    ("FUU","TSXV","F3 Uranium","Uranium"),("ISO","TSX","IsoEnergy","Uranium"),
    ("TLG","TSX","Talon Metals","Nickel"),("FVL","TSX","Freegold Ventures","Gold"),
    ("ARTG","TSXV","Artemis Gold","Gold"),
    ("PDN","ASX","Paladin Energy","Uranium"),("DYL","ASX","Deep Yellow","Uranium"),
    ("BOE","ASX","Boss Energy","Uranium"),("NST","ASX","Northern Star Resources","Gold"),
    ("EVN","ASX","Evolution Mining","Gold"),("RMS","ASX","Ramelius Resources","Gold"),
    ("WGX","ASX","Westgold Resources","Gold"),("BGL","ASX","Bellevue Gold","Gold"),
    ("CMM","ASX","Capricorn Metals","Gold"),("PLS","ASX","Pilbara Minerals","Lithium"),
    ("MIN","ASX","Mineral Resources","Diversified"),("IGO","ASX","IGO Limited","Nickel"),
    ("LTR","ASX","Liontown Resources","Lithium"),("S32","ASX","South32","Diversified"),
    ("SFR","ASX","Sandfire Resources","Copper"),
    ("CRML","NASDAQ","Critical Metals Corp","Rare Earths"),
    ("USAR","NASDAQ","USA Rare Earth","Rare Earths"),
    ("AREC","NASDAQ","American Resources Corporation","Rare Earths"),
    ("WWR","NYSE","Westwater Resources","Graphite"),
    ("MTAL","NYSE","Metals Acquisition","Copper"),
    ("NVA","NASDAQ","Nova Minerals","Gold"),
    ("ATLX","NASDAQ","Atlas Lithium","Lithium"),
    ("LAR","NYSE","Lithium Argentina","Lithium"),
    ("NMG","NYSE","Nouveau Monde Graphite","Graphite"),
    ("SQM","NYSE","Sociedad Quimica y Minera de Chile","Lithium"),
    ("ALB","NYSE","Albemarle Corporation","Lithium"),
    ("MOS","NYSE","The Mosaic Company","Potash"),
    ("NTR","NYSE","Nutrien Ltd","Potash"),
    ("ICL","NYSE","ICL Group","Potash"),
    ("TROX","NYSE","Tronox Holdings","Diversified"),
    ("GSM","NASDAQ","Ferroglobe PLC","Diversified"),
    ("AAU","NYSE","Almaden Minerals","Gold"),
    ("WRLG","TSXV","West Red Lake Gold Mines","Gold"),
    ("PMET","TSX","Patriot Battery Metals","Lithium"),
    ("FL","TSXV","Frontier Lithium","Lithium"),
]

_EXPAND_STATUS: dict = {"state": "idle"}


def _run_expand_universe() -> None:
    from .db import SessionLocal
    from .jobs.nightly import run_grades
    db = SessionLocal()
    stats = {"state": "running", "added": [], "skipped_existing": 0,
             "no_data": [], "done": 0, "total": len(US_MINERS)}
    _EXPAND_STATUS.clear(); _EXPAND_STATUS.update(stats)
    try:
        for tick, exch, name, commodity in US_MINERS:
            existing = db.execute(select(models.Company).where(
                models.Company.ticker == tick)).scalar_one_or_none()
            if existing:
                stats["skipped_existing"] += 1
                stats["done"] += 1
                _EXPAND_STATUS.update(stats)
                continue
            try:
                data = marketdata.fetch_company_data(tick, exch, "5y")
            except Exception:  # noqa: BLE001
                data = {"prices": []}
            if not data["prices"]:
                stats["no_data"].append(tick)
                stats["done"] += 1
                _EXPAND_STATUS.update(stats)
                continue
            c = models.Company(
                ticker=tick, exchange=data.get("resolved_exchange") or exch,
                name=name, commodity=commodity, jurisdiction="",
                jurisdiction_tier="Tier 1", project_name="",
                shares_outstanding=data.get("shares_outstanding") or 0)
            db.add(c); db.flush()
            for row in data["prices"]:
                db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                         close=row["close"], volume=row["volume"],
                                         open=row.get("open"), high=row.get("high"),
                                         low=row.get("low")))
            for ch in data.get("cash_history", []):
                db.add(models.FinancialSnapshot(
                    company_id=c.id, as_of=ch["as_of"], cash=ch["cash"],
                    monthly_burn=data.get("monthly_burn") or 0.0,
                    source_filing="EODHD quarterly balance sheet (SEDAR/SEC)"))
            for sh in data.get("shares_history", []):
                db.add(models.SharesHistory(company_id=c.id, as_of=sh["as_of"],
                                            shares=sh["shares"]))
            db.commit()
            stats["added"].append(tick)
            stats["done"] += 1
            _EXPAND_STATUS.update(stats)
        run_grades(db)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _EXPAND_STATUS.update(stats)


@router.post("/api/admin/expand-universe")
def expand_universe():
    """Add ~60 US-listed and Canadian miners (5y history each) in the
    background. Poll expand-universe-status."""
    import threading
    if _EXPAND_STATUS.get("state") == "running":
        return {"started": False, "progress": _EXPAND_STATUS}
    threading.Thread(target=_run_expand_universe, daemon=True).start()
    return {"started": True, "check_progress": "GET /api/admin/expand-universe-status"}


@router.get("/api/admin/expand-universe-status")
def expand_universe_status():
    return _EXPAND_STATUS


# ------------------------------------- market-wide financing sweep (unlocks)
FIN_QUERIES = [
    '"closes" "private placement" TSXV',
    '"closes private placement" mining',
    '"closing of" "private placement" "TSX Venture"',
    '"bought deal" "closing" mining',
    '"announces" "private placement" TSXV mining',
    '"upsized" "private placement" mining',
]

_FINSWEEP_STATUS: dict = {"state": "idle"}


def _run_financing_sweep(days: int) -> None:
    import re as _re
    import feedparser as _fp
    import httpx as _hx
    from datetime import datetime as _dt, timedelta as _td
    from urllib.parse import quote_plus as _qp
    from .db import SessionLocal
    from .jobs.nightly import _upsert_financing
    from .services import financing as _finmod
    from .services import promotion as _promo
    db = SessionLocal()
    issuer_pat = _re.compile(ISSUER_PAT_SRC)
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
    stats = {"state": "running", "headlines_seen": 0, "pages_fetched": 0,
             "financings_filed": 0, "companies_added": [], "queries_done": 0,
             "queries_total": len(FIN_QUERIES)}
    _FINSWEEP_STATUS.clear(); _FINSWEEP_STATUS.update(stats)
    try:
        cutoff = _dt.utcnow() - _td(days=days)
        seen: set[str] = set()
        with _hx.Client(timeout=25, headers=ua, follow_redirects=True) as client:
            for query in FIN_QUERIES:
                url = (f"https://news.google.com/rss/search?q={_qp(query + f' when:{days}d')}"
                       "&hl=en-CA&gl=CA&ceid=CA:en")
                try:
                    feed = _fp.parse(client.get(url).content)
                except Exception:  # noqa: BLE001
                    stats["queries_done"] += 1
                    continue
                for e in feed.entries:
                    link, title = e.get("link", ""), e.get("title", "")
                    if not link or link in seen:
                        continue
                    seen.add(link)
                    stats["headlines_seen"] += 1
                    pub = (_dt(*e.published_parsed[:6])
                           if e.get("published_parsed") else None)
                    if not pub or pub < cutoff:
                        continue
                    real = _gnews_real_url(link)
                    if not real:
                        try:
                            real = _gnews_real_url(link, client.get(link).text)
                        except Exception:  # noqa: BLE001
                            continue
                    if not real:
                        continue
                    try:
                        text = _promo.html_to_text(client.get(real).text)[:80_000]
                    except Exception:  # noqa: BLE001
                        continue
                    stats["pages_fetched"] += 1
                    low = text.lower()
                    if not any(h in low for h in MINING_HINTS):
                        continue
                    parsed = _finmod.parse_financing(text[:6000])
                    if not parsed:
                        continue
                    m = issuer_pat.search(text[:8000])
                    if not m:
                        continue
                    name = m.group(1).strip(" ,.")
                    name = _re.split(r"\s[\-\u2013\u2014]{1,2}\s|--|\)\s", name)[-1].strip(" ,.-")
                    ticker = m.group(3).upper()
                    exchange = "TSXV" if "V" in m.group(2).upper().replace("TSX", "") \
                               or "VENTURE" in m.group(2).upper() else "TSX"
                    if len(name) < 4:
                        continue
                    c = db.execute(select(models.Company).where(
                        models.Company.ticker == ticker)).scalar_one_or_none()
                    if not c:
                        c = models.Company(ticker=ticker, exchange=exchange,
                                           name=name, commodity="Unclassified",
                                           jurisdiction="", jurisdiction_tier="Tier 1",
                                           project_name="", shares_outstanding=0)
                        db.add(c); db.flush()
                        stats["companies_added"].append(f"{ticker} ({name})")
                    if not _title_mentions(c, title) and c.name.lower() not in low[:3000]:
                        continue
                    _upsert_financing(db, c.id, pub, title[:400], real[:400], parsed)
                    stats["financings_filed"] += 1
                    db.commit()
                stats["queries_done"] += 1
                _FINSWEEP_STATUS.update(stats)
        fins = db.execute(select(models.Financing).where(
            models.Financing.closed.is_(True))).scalars().all()
        stats["closed_financings_total"] = len(fins)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _FINSWEEP_STATUS.update(stats)


@router.post("/api/admin/scan-financings-market")
def scan_financings_market(days: int = 150):
    """Market-wide financing sweep: find placement closings across ALL TSXV/
    TSX miners (auto-adding unknown issuers) so the Unlock Calendar covers
    the whole market, not just tracked names. Background job."""
    import threading
    if _FINSWEEP_STATUS.get("state") == "running":
        return {"started": False, "progress": _FINSWEEP_STATUS}
    threading.Thread(target=_run_financing_sweep, args=(days,),
                     daemon=True).start()
    return {"started": True, "days": days,
            "check_progress": "GET /api/admin/scan-financings-market-status"}


@router.get("/api/admin/scan-financings-market-status")
def scan_financings_market_status():
    return _FINSWEEP_STATUS


# ---------------------------------- promotion hunt (EODHD licensed archive)
_PROMOHUNT_STATUS: dict = {"state": "idle"}


def _run_promo_hunt(days: int) -> None:
    """Fetch up to `days` of licensed news per tracked company and parse the
    FULL article text for promotion disclosures - headlines rarely carry the
    fees, article bodies do."""
    from .db import SessionLocal
    from .services import eodhd as _e
    from .services import promotion as _promo
    from .jobs.nightly import _upsert_promotion
    db = SessionLocal()
    stats = {"state": "running", "companies_done": 0, "companies_total": 0,
             "articles_scanned": 0, "promotions_found": 0, "hits": {}}
    _PROMOHUNT_STATUS.clear(); _PROMOHUNT_STATUS.update(stats)
    try:
        companies = db.execute(select(models.Company)).scalars().all()
        stats["companies_total"] = len(companies)
        for c in companies:
            try:
                items = _e.fetch_news(c.ticker, c.exchange, days, 50)
            except Exception:  # noqa: BLE001
                items = []
            core = _core_name(c.name)
            for item in items:
                text = f"{item['headline']} {item['summary']}"
                low = text.lower()
                stats["articles_scanned"] += 1
                if core not in low:
                    continue   # a promotion record must name its issuer
                parsed = _promo.parse_promotion(text)
                if not parsed:
                    continue
                _upsert_promotion(db, c.id, item["published"],
                                  item["headline"][:400], item["url"][:400], parsed)
                stats["promotions_found"] += 1
                stats["hits"][c.ticker] = stats["hits"].get(c.ticker, 0) + 1
            db.commit()
            stats["companies_done"] += 1
            _PROMOHUNT_STATUS.update(stats)
        stats["promotions_total"] = len(
            db.execute(select(models.Promotion)).scalars().all())
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _PROMOHUNT_STATUS.update(stats)


@router.post("/api/admin/hunt-promotions-eodhd")
def hunt_promotions_eodhd(days: int = 180):
    """Deep licensed-archive promotion hunt. Background; poll
    hunt-promotions-eodhd-status."""
    import threading
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"error": "EODHD_API_KEY not configured"}
    if _PROMOHUNT_STATUS.get("state") == "running":
        return {"started": False, "progress": _PROMOHUNT_STATUS}
    threading.Thread(target=_run_promo_hunt, args=(days,), daemon=True).start()
    return {"started": True, "days": days,
            "check_progress": "GET /api/admin/hunt-promotions-eodhd-status"}


@router.get("/api/admin/hunt-promotions-eodhd-status")
def hunt_promotions_eodhd_status():
    return _PROMOHUNT_STATUS


# --------------------------------- drill activity from stored licensed news
@router.post("/api/admin/detect-drilling-from-news")
def detect_drilling_from_news(days: int = 120, db: Session = Depends(get_db)):
    """Mine the stored news bodies (EODHD + wires) for drill starts and
    assay intercepts: marks programs active with real last-activity dates and
    files parsed intercepts. Fattens the Active Drill Programs board."""
    from datetime import datetime as _dt, timedelta as _td
    from .services import drill_parser as _dp
    cutoff = _dt.utcnow() - _td(days=days)
    stats = {"releases_scanned": 0, "drill_starts": 0, "intercepts_added": 0,
             "programs_activated": []}
    rows = db.execute(select(models.PressRelease).where(
        models.PressRelease.company_id.is_not(None),
        models.PressRelease.published >= cutoff)).scalars().all()
    have_holes = {(r.company_id, r.hole_id) for r in
                  db.execute(select(models.DrillResult)).scalars()}
    for pr in rows:
        stats["releases_scanned"] += 1
        text = f"{pr.headline} {pr.body or ''}"
        program = db.execute(select(models.DrillProgram).where(
            models.DrillProgram.company_id == pr.company_id,
            models.DrillProgram.active.is_(True))).scalars().first()
        started = _dp.is_drill_start(text)
        intercepts = _dp.parse_intercepts(text)
        if (started or intercepts) and not program:
            c = db.get(models.Company, pr.company_id)
            program = models.DrillProgram(
                company_id=pr.company_id,
                name=(pr.headline[:110] or "Current program"),
                announced=pr.published.date(), rigs_active=1, active=True)
            db.add(program); db.flush()
            stats["programs_activated"].append(c.ticker if c else pr.company_id)
        if started:
            stats["drill_starts"] += 1
            pr.is_drill_start = True
        for i in intercepts:
            key = (pr.company_id, i.hole_id)
            if key in have_holes:
                continue
            have_holes.add(key)
            db.add(models.DrillResult(
                company_id=pr.company_id,
                program_id=program.id if program else None,
                published=pr.published, hole_id=i.hole_id,
                commodity=i.commodity, grade=i.grade, unit=i.unit,
                width_m=i.width_m, grade_meters=i.grade_meters,
                above_benchmark=i.above_benchmark,
                source_url=pr.url, raw_sentence=i.raw_sentence[:2000]))
            stats["intercepts_added"] += 1
    db.commit()
    return stats


# ------------------------------------------- manual promotion URL ingestion
class PromoUrlsBody(BaseModel):
    urls: list[str]


_URLINGEST_STATUS: dict = {"state": "idle"}


def _run_url_ingest(urls: list[str]) -> None:
    import re as _re
    import httpx as _hx
    from datetime import datetime as _dt
    from .db import SessionLocal
    from .services import promotion as _promo
    from .services import financing as _finmod
    from .jobs.nightly import _upsert_promotion, _upsert_financing
    db = SessionLocal()
    issuer_pat = _re.compile(ISSUER_PAT_SRC)
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
    stats = {"state": "running", "done": 0, "total": len(urls),
             "filed": [], "skipped": [], "companies_added": []}
    _URLINGEST_STATUS.clear(); _URLINGEST_STATUS.update(stats)
    try:
        companies = db.execute(select(models.Company)).scalars().all()
        by_ticker = {c.ticker: c for c in companies}
        cores = [(c, _core_name(c.name)) for c in companies]
        with _hx.Client(timeout=30, headers=ua, follow_redirects=True) as client:
            for url in urls:
                tail = url.rstrip("/").split("/")[-1][:60]
                try:
                    text = _promo.html_to_text(client.get(url).text)[:80_000]
                except Exception as exc:  # noqa: BLE001
                    stats["skipped"].append(f"{tail}: fetch failed ({str(exc)[:60]})")
                    stats["done"] += 1; _URLINGEST_STATUS.update(stats)
                    continue
                low = text.lower()
                head = text[:8000]
                # issuer: exchange parenthetical first, then known-name match
                c = None
                m = issuer_pat.search(head)
                if m and m.group(3).upper() in by_ticker:
                    c = by_ticker[m.group(3).upper()]
                if c is None:
                    zone = low[:1500]   # headline + dateline only, not sidebars
                    for cand, core in cores:
                        if core and len(core) >= 5 and \
                                _re.search(rf"\b{_re.escape(core)}\b", zone):
                            c = cand
                            break
                if c is None and m:
                    name = m.group(1).strip(" ,.")
                    name = _re.split(r"\s[\-\u2013\u2014]{1,2}\s|--|\)\s", name)[-1].strip(" ,.-")
                    ticker = m.group(3).upper()
                    exch_raw = m.group(2).upper()
                    exchange = ("CSE" if "CSE" in exch_raw or "CNSX" in exch_raw
                                else "TSXV" if "V" in exch_raw.replace("TSX", "")
                                or "VENTURE" in exch_raw else "TSX")
                    if len(name) >= 4 and any(h in low for h in MINING_HINTS):
                        c = models.Company(ticker=ticker, exchange=exchange,
                                           name=name, commodity="Unclassified",
                                           jurisdiction="", jurisdiction_tier="Tier 1",
                                           project_name="", shares_outstanding=0)
                        db.add(c); db.flush()
                        by_ticker[ticker] = c
                        cores.append((c, _core_name(name)))
                        stats["companies_added"].append(f"{ticker} ({name})")
                if c is None:
                    stats["skipped"].append(f"{tail}: issuer not identified")
                    stats["done"] += 1; _URLINGEST_STATUS.update(stats)
                    continue
                parsed = _promo.parse_promotion(text[:20_000])
                if not parsed:
                    stats["skipped"].append(f"{tail}: no promotion language parsed")
                    stats["done"] += 1; _URLINGEST_STATUS.update(stats)
                    continue
                headline = text.strip().split("\n")[0][:400] or tail
                _upsert_promotion(db, c.id, _dt.utcnow(), headline, url[:400], parsed)
                db.commit()
                amt = parsed.get("amount")
                stats["filed"].append(
                    f"{c.ticker}: {parsed.get('firm') or 'firm?'} "
                    f"{'$' + format(amt, ',.0f') if amt else '(no $ parsed)'}")
                # financings ride along when the release mentions one
                fpar = _finmod.parse_financing(text[:20_000])
                if fpar:
                    _upsert_financing(db, c.id, _dt.utcnow(), headline, url[:400], fpar)
                    db.commit()
                stats["done"] += 1
                _URLINGEST_STATUS.update(stats)
        stats["state"] = "done"
        stats["promotions_total"] = len(
            db.execute(select(models.Promotion)).scalars().all())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _URLINGEST_STATUS.update(stats)


@router.post("/api/admin/ingest-promotion-urls")
def ingest_promotion_urls(body: PromoUrlsBody):
    """Feed a list of release URLs; each is fetched, parsed for promotion
    terms, attributed to its issuer (auto-adding unknown miners), and filed.
    Background; poll ingest-promotion-urls-status for the per-URL report."""
    import threading
    if _URLINGEST_STATUS.get("state") == "running":
        return {"started": False, "progress": _URLINGEST_STATUS}
    urls = [u.strip() for u in body.urls if u.strip()]
    seen, deduped = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); deduped.append(u)
    threading.Thread(target=_run_url_ingest, args=(deduped,),
                     daemon=True).start()
    return {"started": True, "urls": len(deduped),
            "check_progress": "GET /api/admin/ingest-promotion-urls-status"}


@router.get("/api/admin/ingest-promotion-urls-status")
def ingest_promotion_urls_status():
    return _URLINGEST_STATUS


# --------------------------------------- promotion attribution verification
_VERIFYPROMO_STATUS: dict = {"state": "idle"}


def _run_verify_promotions() -> None:
    import re as _re
    import httpx as _hx
    from .db import SessionLocal
    from .services import promotion as _promo
    db = SessionLocal()
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
    stats = {"state": "running", "checked": 0, "total": 0,
             "verified": 0, "deleted": [], "unreachable_kept": []}
    _VERIFYPROMO_STATUS.clear(); _VERIFYPROMO_STATUS.update(stats)
    try:
        promos = db.execute(select(models.Promotion)).scalars().all()
        stats["total"] = len(promos)
        with _hx.Client(timeout=25, headers=ua, follow_redirects=True) as client:
            for p in promos:
                c = db.get(models.Company, p.company_id)
                stats["checked"] += 1
                if not c or not p.source_url:
                    _VERIFYPROMO_STATUS.update(stats); continue
                core = _core_name(c.name)
                # headline check is free - if it names the company, verified
                if _title_mentions(c, p.headline or ""):
                    stats["verified"] += 1
                    _VERIFYPROMO_STATUS.update(stats); continue
                try:
                    text = _promo.html_to_text(
                        client.get(p.source_url).text)[:6000].lower()
                except Exception:  # noqa: BLE001
                    stats["unreachable_kept"].append(f"{c.ticker}: {p.source_url[:60]}")
                    _VERIFYPROMO_STATUS.update(stats); continue
                zone = text[:2500]
                named = (len(core) >= 5 and
                         _re.search(rf"\b{_re.escape(core)}\b", zone)) or \
                        _re.search(rf"\b{_re.escape(c.ticker.lower())}\b", zone)
                if named:
                    stats["verified"] += 1
                else:
                    stats["deleted"].append(
                        f"{c.ticker}: '{(p.headline or '')[:60]}' -> {p.source_url[:60]}")
                    db.delete(p)
                    db.commit()
                _VERIFYPROMO_STATUS.update(stats)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _VERIFYPROMO_STATUS.update(stats)


@router.post("/api/admin/verify-promotions")
def verify_promotions():
    """Re-fetch every promotion's source page and delete records whose page
    does not actually name the company they're filed under (the AYA class of
    misattribution). Background; poll verify-promotions-status."""
    import threading
    if _VERIFYPROMO_STATUS.get("state") == "running":
        return {"started": False, "progress": _VERIFYPROMO_STATUS}
    threading.Thread(target=_run_verify_promotions, daemon=True).start()
    return {"started": True,
            "check_progress": "GET /api/admin/verify-promotions-status"}


@router.get("/api/admin/verify-promotions-status")
def verify_promotions_status():
    return _VERIFYPROMO_STATUS


# ----------------------------------------------- purge non-mining companies
MINING_COMMODITIES = {
    "gold", "silver", "copper", "nickel", "uranium", "lithium", "zinc",
    "lead", "cobalt", "tin", "tungsten", "platinum", "palladium", "pge",
    "rare earths", "iron ore", "coal", "potash", "phosphate", "diamonds",
    "graphite", "manganese", "antimony", "molybdenum", "vanadium",
    "diversified", "unclassified", "royalty", "silver-gold", "gold-copper",
}
NON_MINING_NAME_FLAGS = [
    "digital", " ai ", " ai.", "software", "technologies inc", "insights",
    "media", "pharma", "bio", "defense", "defence", "fintech", "payments",
    "crypto", "blockchain", "cannabis", "beverage", "gaming", "esports",
]


@router.post("/api/admin/purge-non-mining")
def purge_non_mining(dry_run: bool = True, db: Session = Depends(get_db)):
    """Remove companies that aren't miners. dry_run=true (default) only
    LISTS what would be deleted - review, then re-run with dry_run=false.
    Deletion cascades to prices, financials, promotions, and news."""
    targets = []
    for c in db.execute(select(models.Company)).scalars():
        low_name = f" {c.name.lower()} "
        commodity_ok = (c.commodity or "").strip().lower() in MINING_COMMODITIES
        name_flagged = any(fl in low_name for fl in NON_MINING_NAME_FLAGS)
        mining_in_name = any(w in low_name for w in
                             (" mining", " mines", " gold", " silver", " metals",
                              " minerals", " resources", " uranium", " lithium",
                              " copper", " exploration"))
        if (not commodity_ok and not mining_in_name) or \
           (name_flagged and not mining_in_name):
            targets.append(c)
    listing = [f"{c.ticker}: {c.name} [{c.commodity}]" for c in targets]
    if dry_run:
        return {"dry_run": True, "would_delete": listing,
                "count": len(listing),
                "next": "Re-run with dry_run=false to delete these."}
    child_models = [models.DailyPrice, models.FinancialSnapshot,
                    models.SharesHistory, models.Promotion, models.Financing,
                    models.PressRelease, models.DilutionGrade,
                    models.WarrantTranche, models.DrillResult,
                    models.DrillProgram]
    for c in targets:
        for M in child_models:
            for row in db.execute(select(M).where(
                    M.company_id == c.id)).scalars():
                db.delete(row)
        db.delete(c)
    db.commit()
    return {"dry_run": False, "deleted": listing, "count": len(listing)}


# ------------------------------------------------ promotion link repair
PRIMARY_WIRES = ("newsfilecorp.com", "globenewswire.com", "newswire.ca",
                 "accesswire.com", "prnewswire.com", "businesswire.com",
                 "thenewswire.com")

_LINKREPAIR_STATUS: dict = {"state": "idle"}


def _is_primary(url: str) -> bool:
    return any(w in (url or "") for w in PRIMARY_WIRES)


def _run_repair_promo_links() -> None:
    import re as _re
    import feedparser as _fp
    import httpx as _hx
    from urllib.parse import quote_plus as _qp
    from .db import SessionLocal
    from .services import promotion as _promo
    db = SessionLocal()
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
    stats = {"state": "running", "checked": 0, "total": 0, "already_good": 0,
             "repaired": [], "enriched": [], "unresolved": []}
    _LINKREPAIR_STATUS.clear(); _LINKREPAIR_STATUS.update(stats)

    def _page_ok(client, url, company):
        try:
            text = _promo.html_to_text(client.get(url).text)[:20_000]
        except Exception:  # noqa: BLE001
            return None
        zone = text[:3000].lower()
        core = _core_name(company.name)
        named = (len(core) >= 5 and
                 _re.search(rf"\b{_re.escape(core)}\b", zone)) or \
                _re.search(rf"\b{_re.escape(company.ticker.lower())}\b", zone)
        return text if named else None

    try:
        promos = db.execute(select(models.Promotion)).scalars().all()
        stats["total"] = len(promos)
        with _hx.Client(timeout=25, headers=ua, follow_redirects=True) as client:
            for p in promos:
                stats["checked"] += 1
                c = db.get(models.Company, p.company_id)
                if not c:
                    _LINKREPAIR_STATUS.update(stats); continue
                text = None
                if _is_primary(p.source_url):
                    text = _page_ok(client, p.source_url, c)
                    if text:
                        stats["already_good"] += 1
                if text is None:
                    # hunt the canonical wire release
                    q = f'"{c.name}" engages'
                    if p.firm:
                        q = f'"{c.name}" "{p.firm.split()[0]}" engages'
                    rss = (f"https://news.google.com/rss/search?q={_qp(q + ' when:400d')}"
                           "&hl=en-CA&gl=CA&ceid=CA:en")
                    try:
                        feed = _fp.parse(client.get(rss).content)
                    except Exception:  # noqa: BLE001
                        feed = None
                    found = None
                    for e in (feed.entries[:8] if feed else []):
                        real = _gnews_real_url(e.get("link", ""))
                        if not real:
                            try:
                                real = _gnews_real_url(e.get("link", ""),
                                                       client.get(e.get("link", "")).text)
                            except Exception:  # noqa: BLE001
                                continue
                        if not real or not _is_primary(real):
                            continue
                        t = _page_ok(client, real, c)
                        if t and _promo.parse_promotion(t[:20_000]):
                            found = (real, t)
                            break
                    if found:
                        old = (p.source_url or "")[:50]
                        p.source_url = found[0][:400]
                        text = found[1]
                        stats["repaired"].append(
                            f"{c.ticker}: {old}... -> {found[0][:70]}")
                    else:
                        stats["unresolved"].append(
                            f"{c.ticker}: {(p.source_url or 'no url')[:70]}")
                        db.commit()
                        _LINKREPAIR_STATUS.update(stats)
                        continue
                # enrich missing fields from the full release text
                if text and (p.amount is None or p.term_months is None):
                    parsed = _promo.parse_promotion(text[:20_000])
                    if parsed:
                        changed = []
                        if p.amount is None and parsed.get("amount"):
                            p.amount = parsed["amount"]; changed.append("amount")
                        if p.term_months is None and parsed.get("term_months"):
                            p.term_months = parsed["term_months"]; changed.append("term")
                        if p.ends is None and parsed.get("ends"):
                            p.ends = parsed["ends"]; changed.append("ends")
                        if not p.firm and parsed.get("firm"):
                            p.firm = parsed["firm"]; changed.append("firm")
                        if changed:
                            stats["enriched"].append(f"{c.ticker}: +{'+'.join(changed)}")
                db.commit()
                _LINKREPAIR_STATUS.update(stats)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _LINKREPAIR_STATUS.update(stats)


@router.post("/api/admin/repair-promotion-links")
def repair_promotion_links():
    """Every promotion's disclosure link gets pointed at the canonical wire
    release (Newsfile/GlobeNewswire/Newswire.ca...), replacing redirect tokens
    and aggregators, and missing budgets/terms are re-parsed from the full
    release. Background; poll repair-promotion-links-status."""
    import threading
    if _LINKREPAIR_STATUS.get("state") == "running":
        return {"started": False, "progress": _LINKREPAIR_STATUS}
    threading.Thread(target=_run_repair_promo_links, daemon=True).start()
    return {"started": True,
            "check_progress": "GET /api/admin/repair-promotion-links-status"}


@router.get("/api/admin/repair-promotion-links-status")
def repair_promotion_links_status():
    return _LINKREPAIR_STATUS


# ============================ CORRECTIVE TOOLING ============================
class RecordFinancingBody(BaseModel):
    ticker: str
    amount: float
    announced: str                    # YYYY-MM-DD
    closed: bool = False
    close_date: str | None = None
    kind: str = "private placement"
    headline: str = ""
    source_url: str = ""


@router.post("/api/admin/record-financing")
def record_financing(body: RecordFinancingBody, db: Session = Depends(get_db)):
    """Manual corrective entry: when detection misses a raise (announced or
    closed), file it here and every scanner adjusts immediately."""
    from datetime import datetime as _dt, timedelta as _td
    c = db.execute(select(models.Company).where(
        models.Company.ticker == body.ticker.upper().strip())).scalar_one_or_none()
    if not c:
        return {"error": f"{body.ticker} not tracked - add it first."}
    ann = _dt.strptime(body.announced, "%Y-%m-%d").date()
    cd = (_dt.strptime(body.close_date, "%Y-%m-%d").date()
          if body.close_date else (ann if body.closed else None))
    fin = models.Financing(
        company_id=c.id, announced=ann, closed=body.closed, close_date=cd,
        amount=body.amount, kind=body.kind[:60],
        headline=(body.headline or f"{c.name} {body.kind} ${body.amount:,.0f} (manual entry)")[:400],
        source_url=(body.source_url or "manual-entry")[:400],
        hold_expiry=(cd + _td(days=122)) if cd else None)
    db.add(fin); db.commit()
    return {"filed": f"{c.ticker}: ${body.amount:,.0f} {body.kind}, "
                     f"{'closed ' + str(cd) if body.closed else 'announced ' + str(ann)}",
            "effect": "dilution-risk and burn-league adjust on next load"}


@router.post("/api/admin/recheck-company")
def recheck_company(ticker: str, db: Session = Depends(get_db)):
    """Single-company corrective sweep: re-pull 30 days of licensed news for
    one ticker, run financing + promotion detection, report what was found."""
    from .config import settings as _s
    from .services import eodhd as _e
    from .services import financing as _finmod
    from .services import promotion as _promo
    from .jobs.nightly import _upsert_financing, _upsert_promotion
    if not _s.eodhd_api_key:
        return {"error": "EODHD_API_KEY not configured"}
    c = db.execute(select(models.Company).where(
        models.Company.ticker == ticker.upper().strip())).scalar_one_or_none()
    if not c:
        return {"error": f"{ticker} not tracked."}
    items = _e.fetch_news(c.ticker, c.exchange, 30, 30)
    core = _core_name(c.name)
    found = {"news_scanned": len(items), "financings": [], "promotions": []}
    for item in items:
        text = f"{item['headline']} {item['summary']}"
        if core not in text.lower():
            continue
        fpar = _finmod.parse_financing(text)
        if fpar:
            _upsert_financing(db, c.id, item["published"],
                              item["headline"][:400], item["url"][:400], fpar)
            found["financings"].append(item["headline"][:90])
        ppar = _promo.parse_promotion(text)
        if ppar:
            _upsert_promotion(db, c.id, item["published"],
                              item["headline"][:400], item["url"][:400], ppar)
            found["promotions"].append(item["headline"][:90])
    db.commit()
    br = _burn_runway(db, c.id)
    if br:
        found["current_view"] = {
            "burn": br["burn"], "burn_source": br["burn_source"],
            "runway_m": br["runway"] and round(br["runway"], 1),
            "adjusted_runway_m": br["adj_runway"] and round(br["adj_runway"], 1),
            "closed_raise_since_snapshot": br["closed_amt"],
            "announced_raise": br["announced_amt"] or br["announced_date"]}
    return found


@router.get("/api/admin/data-sentinel")
def data_sentinel(db: Session = Depends(get_db)):
    """The contradiction hunter: surfaces data that cannot all be true, so
    mistakes get caught by the software before a user sees them."""
    from datetime import datetime as _dt, timedelta as _td
    report = {"zero_burn_falling_cash": [], "implausible_runway": [],
              "stale_financials": [], "no_price_data": [],
              "financings_missing_amount": [], "unattributed_promotions": []}
    today = date.today()
    for c in db.execute(select(models.Company)).scalars():
        snaps = db.execute(select(models.FinancialSnapshot).where(
            models.FinancialSnapshot.company_id == c.id)
            .order_by(models.FinancialSnapshot.as_of)).scalars().all()
        if snaps:
            fin = snaps[-1]
            falling = (len(snaps) >= 3 and all(
                b.cash < a.cash for a, b in zip(snaps[-3:], snaps[-3:][1:])
                if a.cash and b.cash))
            if not fin.monthly_burn and falling:
                report["zero_burn_falling_cash"].append(
                    f"{c.ticker}: cash falling but burn recorded as 0")
            br = _burn_runway(db, c.id)
            if br and br["runway"] and br["runway"] > 120:
                report["implausible_runway"].append(
                    f"{c.ticker}: {br['runway']:.0f}mo runway "
                    f"(burn source: {br['burn_source']})")
            if (today - fin.as_of).days > 400:
                report["stale_financials"].append(
                    f"{c.ticker}: latest snapshot {fin.as_of}")
        if not db.execute(select(models.DailyPrice).where(
                models.DailyPrice.company_id == c.id).limit(1)).scalar_one_or_none():
            report["no_price_data"].append(c.ticker)
    for r in db.execute(select(models.Financing)).scalars():
        if r.amount in (None, 0):
            c = db.get(models.Company, r.company_id)
            report["financings_missing_amount"].append(
                f"{c.ticker if c else '?'}: {(r.headline or '')[:60]}")
    for p in db.execute(select(models.Promotion)).scalars():
        c = db.get(models.Company, p.company_id)
        if c and not _title_mentions(c, p.headline or ""):
            report["unattributed_promotions"].append(
                f"{c.ticker}: '{(p.headline or '')[:60]}'")
    report["summary"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    return report


# ============================ THIS WEEK IN DILUTION =========================
def _build_digest(db) -> dict:
    """Assemble the weekly digest from the live database. Pure read."""
    from datetime import datetime as _dt, timedelta as _td
    today = date.today()
    week_ago = today - _td(days=7)

    # unlocks inside 14 days
    unlocks = []
    for r in db.execute(select(models.Financing).where(
            models.Financing.hold_expiry.is_not(None),
            models.Financing.hold_expiry >= today,
            models.Financing.hold_expiry <= today + _td(days=14))
            .order_by(models.Financing.hold_expiry)).scalars():
        c = db.get(models.Company, r.company_id)
        if not c:
            continue
        unlocks.append({"ticker": c.ticker, "name": c.name,
                        "amount_m": r.amount and round(r.amount / 1e6, 1),
                        "unlocks": r.hold_expiry.isoformat(),
                        "days": (r.hold_expiry - today).days})

    # promotions disclosed this week
    promos = []
    for p in db.execute(select(models.Promotion).where(
            models.Promotion.announced >= week_ago)
            .order_by(_desc(models.Promotion.announced))).scalars():
        c = db.get(models.Company, p.company_id)
        if not c:
            continue
        promos.append({"ticker": c.ticker, "name": c.name,
                       "firm": p.firm, "paid": p.amount,
                       "announced": p.announced.isoformat()})

    # raises announced or closed this week
    raises_ = []
    for r in db.execute(select(models.Financing).where(
            models.Financing.announced >= week_ago)
            .order_by(_desc(models.Financing.announced))).scalars():
        c = db.get(models.Company, r.company_id)
        if not c:
            continue
        raises_.append({"ticker": c.ticker, "name": c.name,
                        "amount_m": r.amount and round(r.amount / 1e6, 1),
                        "kind": r.kind,
                        "status": "closed" if r.closed else "announced"})

    # grade moves: latest vs ~a week ago
    moves = []
    for c in db.execute(select(models.Company)).scalars():
        rows = db.execute(select(models.DilutionGrade).where(
            models.DilutionGrade.company_id == c.id)
            .order_by(_desc(models.DilutionGrade.day)).limit(15)).scalars().all()
        if len(rows) < 2:
            continue
        latest = rows[0]
        prior = next((r for r in rows if (latest.day - r.day).days >= 5), rows[-1])
        if prior.grade != latest.grade:
            moves.append({"ticker": c.ticker, "name": c.name,
                          "from": prior.grade, "to": latest.grade,
                          "direction": "up" if latest.grade < prior.grade else "down"})

    # shortest fuses (top 5 of burn league logic)
    fuses = []
    for c in db.execute(select(models.Company)).scalars():
        br = _burn_runway(db, c.id)
        if br and br["burn"] and br["fin"].cash and br["adj_runway"]:
            if br["burn"] > 20_000_000:
                continue   # majors with credit lines aren't fuse stories
            fuses.append({"ticker": c.ticker, "name": c.name,
                          "runway_m": round(br["adj_runway"], 1),
                          "burn": round(br["burn"], 0)})
    fuses.sort(key=lambda x: x["runway_m"])
    fuses = fuses[:5]

    # scoreboard headline stat
    sb = promotion_scoreboard(db=db)["summary"]

    dq_counts = {
        "companies": len(db.execute(select(models.Company)).scalars().all()),
        "unlocks_14d": len(unlocks),
        "promos_week": len(promos),
        "raises_week": len(raises_),
    }
    return {"week_of": today.isoformat(), "counts": dq_counts,
            "unlocks": unlocks[:10], "promotions": promos[:10],
            "raises": raises_[:10], "grade_moves": moves[:10],
            "shortest_fuses": fuses, "scoreboard": {
                "median_during": sb.get("median_return_during_pct"),
                "median_after": sb.get("median_return_30d_after_pct"),
                "campaigns": sb.get("campaigns_analyzed")}}


@router.get("/api/digest/weekly")
def digest_weekly(db: Session = Depends(get_db)):
    return _build_digest(db)


def _digest_html(d: dict) -> str:
    """Email-safe HTML: inline styles, table layout, dark assay-lab theme."""
    G, BG, TX, MUT, RED = "#E8B44A", "#101312", "#E9E4D8", "#8D958F", "#D4574E"
    site = "https://getorelens.com"

    def row(cells, mono_idx=()):
        tds = "".join(
            f'<td style="padding:6px 10px;border-bottom:1px solid #2A302D;'
            f'font-family:{chr(39)}Courier New{chr(39)},monospace;" if i in mono_idx else '
            for i, _ in enumerate(cells))
        return ""

    def table(headers, rows_html):
        head = "".join(f'<th style="text-align:left;padding:6px 10px;color:{MUT};'
                       f'font-size:11px;text-transform:uppercase;letter-spacing:2px;'
                       f'border-bottom:1px solid #2A302D;">{h}</th>' for h in headers)
        return (f'<table width="100%" cellpadding="0" cellspacing="0" '
                f'style="border-collapse:collapse;margin:8px 0 22px;">'
                f'<tr>{head}</tr>{rows_html}</table>')

    def td(v, color=TX, mono=False):
        fam = "'Courier New',monospace" if mono else "Arial,sans-serif"
        return (f'<td style="padding:7px 10px;border-bottom:1px solid #232826;'
                f'color:{color};font-family:{fam};font-size:13px;">{v}</td>')

    def section(title):
        return (f'<p style="color:{MUT};font-size:11px;letter-spacing:3px;'
                f'text-transform:uppercase;margin:26px 0 4px;">{title}</p>')

    body = []
    body.append(
        f'<div style="text-align:center;padding:26px 0 6px;">'
        f'<div style="color:{G};font-size:26px;letter-spacing:4px;'
        f'font-family:Arial,sans-serif;font-weight:bold;">ORELENS</div>'
        f'<div style="color:{TX};font-size:20px;margin-top:6px;'
        f'font-family:Georgia,serif;">This Week in Dilution</div>'
        f'<div style="color:{MUT};font-size:12px;margin-top:4px;">'
        f'Week of {d["week_of"]} &middot; {d["counts"]["companies"]} companies tracked</div></div>')

    if d["unlocks"]:
        body.append(section("Unlocks hitting in the next 14 days"))
        rows = "".join("<tr>" + td(u["ticker"], G, True) + td(u["name"])
                       + td(f'${u["amount_m"]}M' if u["amount_m"] else "&mdash;", TX, True)
                       + td(f'{u["days"]}d &middot; {u["unlocks"]}',
                            RED if u["days"] <= 7 else MUT, True) + "</tr>"
                       for u in d["unlocks"])
        body.append(table(["Ticker", "Company", "Size", "Free-trades"], rows))

    if d["promotions"]:
        body.append(section("New paid promotions disclosed"))
        rows = "".join("<tr>" + td(p["ticker"], G, True) + td(p["name"])
                       + td(p["firm"] or "&mdash;")
                       + td(f'${p["paid"]:,.0f}' if p["paid"] else "&mdash;", TX, True)
                       + "</tr>" for p in d["promotions"])
        body.append(table(["Ticker", "Company", "Firm", "Paid"], rows))

    if d["raises"]:
        body.append(section("Fresh raises this week"))
        rows = "".join("<tr>" + td(r["ticker"], G, True) + td(r["name"])
                       + td(f'${r["amount_m"]}M' if r["amount_m"] else "&mdash;", TX, True)
                       + td(r["status"].upper(),
                            RED if r["status"] == "announced" else MUT) + "</tr>"
                       for r in d["raises"])
        body.append(table(["Ticker", "Company", "Size", "Status"], rows))

    if d["grade_moves"]:
        body.append(section("Grade moves"))
        rows = "".join("<tr>" + td(m["ticker"], G, True) + td(m["name"])
                       + td(f'{m["from"]} &rarr; {m["to"]}',
                            "#58B09C" if m["direction"] == "up" else RED, True)
                       + "</tr>" for m in d["grade_moves"])
        body.append(table(["Ticker", "Company", "Move"], rows))

    if d["shortest_fuses"]:
        body.append(section("Shortest fuses (adjusted runway)"))
        rows = "".join("<tr>" + td(x["ticker"], G, True) + td(x["name"])
                       + td(f'{x["runway_m"]} mo', RED if x["runway_m"] <= 6 else TX, True)
                       + td(f'${x["burn"]:,.0f}/mo', MUT, True) + "</tr>"
                       for x in d["shortest_fuses"])
        body.append(table(["Ticker", "Company", "Runway", "Burn"], rows))

    sb = d["scoreboard"]
    if sb.get("median_during") is not None:
        body.append(
            f'<div style="border:1px solid {G};padding:14px;margin:24px 0;">'
            f'<span style="color:{G};font-weight:bold;">The pattern:</span> '
            f'<span style="color:{TX};">across {sb["campaigns"]} tracked campaigns, the '
            f'median promoted stock moved {sb["median_during"]:+}% during its campaign'
            + (f' and {sb["median_after"]:+}% in the 30 days after it ended'
               if sb.get("median_after") is not None else "")
            + f'. <a href="{site}/research/promotions" style="color:{G};">Full scoreboard &rarr;</a></span></div>')

    body.append(
        f'<div style="text-align:center;color:{MUT};font-size:11px;padding:18px 0;">'
        f'<a href="{site}" style="color:{G};">getorelens.com</a> &middot; '
        f'Research tool, not investment advice. Every figure keeps its source.</div>')

    return (f'<html><body style="margin:0;background:{BG};">'
            f'<div style="max-width:640px;margin:0 auto;background:{BG};'
            f'font-family:Arial,sans-serif;padding:0 18px 20px;">'
            + "".join(body) + "</div></body></html>")


@router.get("/api/digest/weekly.html")
def digest_weekly_html(db: Session = Depends(get_db)):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_digest_html(_build_digest(db)))


@router.post("/api/admin/send-digest")
def send_digest(test_only_to: str | None = None, db: Session = Depends(get_db)):
    """Email the digest to every beta signup via Resend. Set RESEND_API_KEY
    in Render to enable. Use test_only_to=you@x.com for a solo test send."""
    import httpx as _hx
    from .config import settings as _s
    if not _s.resend_api_key:
        return {"error": "RESEND_API_KEY not configured",
                "how": "Create a free account at resend.com, add your domain "
                       "or use their test sender, then set RESEND_API_KEY in "
                       "Render -> orelens-api -> Environment."}
    d = _build_digest(db)
    html = _digest_html(d)
    subject = f"This Week in Dilution - {d['week_of']}"
    if test_only_to:
        recipients = [test_only_to]
    else:
        recipients = [r.email for r in db.execute(
            select(models.BetaSignup)).scalars()]
    sent, failed = 0, []
    with _hx.Client(timeout=20) as client:
        for email in recipients:
            try:
                r = client.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {_s.resend_api_key}"},
                    json={"from": _s.digest_from, "to": [email],
                          "subject": subject, "html": html})
                if r.status_code < 300:
                    sent += 1
                else:
                    failed.append(f"{email}: {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{email}: {str(exc)[:60]}")
    return {"sent": sent, "failed": failed, "subject": subject}


# ------------------------------------------------- OHLC history backfill
_OHLC_STATUS: dict = {"state": "idle"}


def _run_ohlc_backfill() -> None:
    """Repaint history with real open/high/low from EODHD so candlestick
    charts render true candles instead of flat legacy rows."""
    from .db import SessionLocal
    from .services import eodhd as _e
    db = SessionLocal()
    stats = {"state": "running", "companies_done": 0, "companies_total": 0,
             "rows_updated": 0, "rows_inserted": 0}
    _OHLC_STATUS.clear(); _OHLC_STATUS.update(stats)
    try:
        companies = db.execute(select(models.Company)).scalars().all()
        stats["companies_total"] = len(companies)
        for c in companies:
            try:
                data = _e.fetch_company_data(c.ticker, c.exchange, "5y")
            except Exception:  # noqa: BLE001
                data = {"prices": []}
            if data["prices"]:
                rows = {p.day: p for p in db.execute(
                    select(models.DailyPrice).where(
                        models.DailyPrice.company_id == c.id)).scalars()}
                for r in data["prices"]:
                    ex = rows.get(r["date"])
                    if ex is None:
                        db.add(models.DailyPrice(
                            company_id=c.id, day=r["date"], close=r["close"],
                            volume=r["volume"], open=r.get("open"),
                            high=r.get("high"), low=r.get("low")))
                        stats["rows_inserted"] += 1
                    elif ex.open is None and r.get("open") is not None:
                        ex.open, ex.high, ex.low = r["open"], r["high"], r["low"]
                        stats["rows_updated"] += 1
                db.commit()
            stats["companies_done"] += 1
            _OHLC_STATUS.update(stats)
        stats["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        stats["state"] = "error"; stats["error"] = str(exc)[:300]
    finally:
        db.close()
        _OHLC_STATUS.update(stats)


@router.post("/api/admin/backfill-ohlc")
def backfill_ohlc():
    """Fill open/high/low across all price history (background).
    Poll backfill-ohlc-status."""
    import threading
    from .config import settings as _s
    if not _s.eodhd_api_key:
        return {"error": "EODHD_API_KEY not configured"}
    if _OHLC_STATUS.get("state") == "running":
        return {"started": False, "progress": _OHLC_STATUS}
    threading.Thread(target=_run_ohlc_backfill, daemon=True).start()
    return {"started": True, "check_progress": "GET /api/admin/backfill-ohlc-status"}


@router.get("/api/admin/backfill-ohlc-status")
def backfill_ohlc_status():
    return _OHLC_STATUS


# ------------------------------------------------- sponsored spotlight slot
_DEFAULT_SPOT = {"ticker": "CCJ",
                 "headline": "Uranium's Blue Chip Is Back in the Spotlight",
                 "blurb": ("Cameco (NYSE: CCJ) - powering the nuclear "
                           "renaissance from the Athabasca Basin to Westinghouse. "
                           "See the full capital story.")}


@router.get("/api/spotlight")
def get_spotlight(db: Session = Depends(get_db)):
    row = db.execute(select(models.Spotlight)
        .order_by(_desc(models.Spotlight.created)).limit(1)).scalar_one_or_none()
    if row is None:
        return {"active": True, **_DEFAULT_SPOT}
    if not row.active:
        return {"active": False}
    return {"active": True, "ticker": row.ticker,
            "headline": row.headline, "blurb": row.blurb}


class SpotlightBody(BaseModel):
    ticker: str
    headline: str
    blurb: str
    active: bool = True
    # custom story landing page (all optional)
    story_about: str | None = None
    story_website: str | None = None
    story_milestones: list[dict] | None = None   # [{"date","title","desc"?}]
    story_news: list[dict] | None = None         # [{"date","headline","url"?}]


@router.post("/api/admin/set-spotlight")
def set_spotlight(body: SpotlightBody, db: Session = Depends(get_db)):
    """Swap the sponsored footer slot without a deploy. Set active=false to
    hide the unit entirely."""
    for old in db.execute(select(models.Spotlight)).scalars():
        old.active = False
    import json as _json
    db.add(models.Spotlight(ticker=body.ticker.upper().strip()[:10],
                            headline=body.headline.strip()[:120],
                            blurb=body.blurb.strip()[:300],
                            active=body.active,
                            story_about=body.story_about,
                            story_website=body.story_website,
                            story_milestones=_json.dumps(body.story_milestones)
                            if body.story_milestones else None,
                            story_news=_json.dumps(body.story_news)
                            if body.story_news else None))
    db.commit()
    return {"spotlight_now": body.ticker.upper(), "active": body.active}


@router.get("/api/story/{ticker}")
def sponsor_story(ticker: str, db: Session = Depends(get_db)):
    """The sponsored landing page payload: the company's story A to Z.
    Curated fields come from set-spotlight; anything missing falls back to
    real data already on file (description, recent releases)."""
    import json as _json
    t = ticker.upper().strip()
    c = db.execute(select(models.Company).where(
        models.Company.ticker == t)).scalar_one_or_none()
    if not c:
        return {"error": "not tracked"}
    spot = db.execute(select(models.Spotlight)
        .order_by(_desc(models.Spotlight.created)).limit(1)).scalar_one_or_none()
    curated = spot if (spot and spot.ticker == t) else None
    milestones = (_json.loads(curated.story_milestones)
                  if curated and curated.story_milestones else [])
    news = (_json.loads(curated.story_news)
            if curated and curated.story_news else [])
    if not news:
        for r in db.execute(select(models.PressRelease).where(
                models.PressRelease.company_id == c.id)
                .order_by(_desc(models.PressRelease.published))
                .limit(6)).scalars():
            news.append({"date": r.published.date().isoformat()
                         if hasattr(r.published, "date") else str(r.published),
                         "headline": r.headline, "url": r.url})
    about = (curated.story_about if curated and curated.story_about
             else (getattr(c, "description", None) or ""))
    fin = _latest_fin(db, c.id)
    return {"ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction": c.jurisdiction,
            "headline": curated.headline if curated else None,
            "blurb": curated.blurb if curated else None,
            "about": about,
            "website": curated.story_website if curated else None,
            "milestones": milestones, "news": news[:8],
            "snapshot": {
                "shares_outstanding": c.shares_outstanding,
                "cash": fin.cash if fin else None,
                "as_of": fin.as_of.isoformat() if fin else None},
            "sponsored": bool(curated)}


@router.get("/api/billing-config")
def billing_config():
    """Pricing page reads this: checkout goes live the moment the
    STRIPE_PAYMENT_LINK env var is set in Render - no deploy needed."""
    from .config import settings as _s
    return {"checkout_url": _s.stripe_payment_link or None,
            "price_year": 97.99, "post_launch_price_year": 725,
            "plan": "Founding Member - Annual"}


# ============================ MEMBER AUTH (passwordless) ====================
import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import secrets as _secrets


def _auth_secret() -> str:
    from .config import settings as _s
    return _s.session_secret or _s.admin_key or "orelens-dev-secret"


def _sign_token(email: str, days: int = 365) -> str:
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    payload = _json.dumps({"email": email.lower(),
                           "exp": (_dt.utcnow() + _td(days=days)).timestamp()})
    body = _b64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = _hmac.new(_auth_secret().encode(), body.encode(),
                    _hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_token(token: str) -> str | None:
    import json as _json
    from datetime import datetime as _dt
    try:
        body, sig = token.rsplit(".", 1)
        expect = _hmac.new(_auth_secret().encode(), body.encode(),
                           _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expect):
            return None
        pad = body + "=" * (-len(body) % 4)
        data = _json.loads(_b64.urlsafe_b64decode(pad))
        if data["exp"] < _dt.utcnow().timestamp():
            return None
        return data["email"]
    except Exception:  # noqa: BLE001
        return None


def _hash_code(email: str, code: str) -> str:
    return _hashlib.sha256(f"{email.lower()}:{code}".encode()).hexdigest()


class AuthEmailBody(BaseModel):
    email: str


class AuthVerifyBody(BaseModel):
    email: str
    code: str


@router.post("/api/auth/request-code")
def auth_request_code(body: AuthEmailBody, db: Session = Depends(get_db)):
    """Step 1: member enters their email; a 6-digit code is emailed to them.
    Response never reveals whether the email is a member (no enumeration)."""
    import httpx as _hx
    from datetime import datetime as _dt, timedelta as _td
    from .config import settings as _s
    email = body.email.strip().lower()
    generic = {"ok": True,
               "message": "If that email has an active membership, a login "
                          "code is on its way. It expires in 10 minutes."}
    member = db.execute(select(models.Member).where(
        models.Member.email == email,
        models.Member.active.is_(True))).scalar_one_or_none()
    if not member:
        return generic
    code = f"{_secrets.randbelow(1_000_000):06d}"
    db.add(models.LoginCode(email=email, code_hash=_hash_code(email, code),
                            expires=_dt.utcnow() + _td(minutes=10)))
    db.commit()
    if _s.resend_api_key:
        try:
            with _hx.Client(timeout=15) as client:
                client.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {_s.resend_api_key}"},
                    json={"from": _s.digest_from, "to": [email],
                          "subject": f"{code} is your OreLens login code",
                          "html": (f"<p>Your OreLens login code:</p>"
                                   f"<h1 style='letter-spacing:6px'>{code}</h1>"
                                   f"<p>It expires in 10 minutes. If you didn't "
                                   f"request this, ignore this email.</p>")})
        except Exception:  # noqa: BLE001
            pass
    return generic


@router.post("/api/auth/verify-code")
def auth_verify_code(body: AuthVerifyBody, db: Session = Depends(get_db)):
    """Step 2: code checks out -> a year-long signed session token."""
    from datetime import datetime as _dt
    email = body.email.strip().lower()
    code = body.code.strip()
    row = db.execute(select(models.LoginCode).where(
        models.LoginCode.email == email,
        models.LoginCode.used.is_(False),
        models.LoginCode.expires > _dt.utcnow())
        .order_by(_desc(models.LoginCode.id)).limit(1)).scalar_one_or_none()
    if not row or not _hmac.compare_digest(row.code_hash,
                                           _hash_code(email, code)):
        return {"ok": False, "error": "Invalid or expired code."}
    row.used = True
    db.commit()
    return {"ok": True, "token": _sign_token(email), "email": email}


@router.get("/api/auth/me")
def auth_me(token: str, db: Session = Depends(get_db)):
    email = _verify_token(token)
    if not email:
        return {"ok": False}
    member = db.execute(select(models.Member).where(
        models.Member.email == email)).scalar_one_or_none()
    if not member or not member.active:
        return {"ok": False}
    return {"ok": True, "email": email, "member_since":
            member.created.date().isoformat()}


# ------------------------------------------------ Stripe webhook -----------
@router.post("/api/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe calls this on checkout + cancellation. Verified with the
    signing secret; creates/deactivates Members automatically."""
    import json as _json
    import time as _time
    from .config import settings as _s
    raw = await request.body()
    if not _s.stripe_webhook_secret:
        return {"error": "STRIPE_WEBHOOK_SECRET not configured"}
    sig_header = request.headers.get("stripe-signature", "")
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    expect = _hmac.new(_s.stripe_webhook_secret.encode(),
                       f"{t}.{raw.decode()}".encode(),
                       _hashlib.sha256).hexdigest()
    if not v1 or not _hmac.compare_digest(v1, expect) or             abs(_time.time() - float(t or 0)) > 600:
        return {"error": "signature verification failed"}
    event = _json.loads(raw)
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    if etype == "checkout.session.completed":
        email = ((obj.get("customer_details") or {}).get("email")
                 or obj.get("customer_email") or "").lower()
        if email:
            member = db.execute(select(models.Member).where(
                models.Member.email == email)).scalar_one_or_none()
            if member:
                member.active = True
                member.stripe_customer_id = obj.get("customer") or member.stripe_customer_id
            else:
                db.add(models.Member(email=email, active=True,
                                     stripe_customer_id=obj.get("customer"),
                                     source="stripe"))
            db.commit()
            return {"ok": True, "member": email}
    if etype in ("customer.subscription.deleted",):
        cust = obj.get("customer")
        if cust:
            member = db.execute(select(models.Member).where(
                models.Member.stripe_customer_id == cust)).scalar_one_or_none()
            if member:
                member.active = False
                db.commit()
                return {"ok": True, "deactivated": member.email}
    return {"ok": True, "ignored": etype}


# ------------------------------------------------ admin member tools -------
class AddMemberBody(BaseModel):
    email: str
    active: bool = True


@router.post("/api/admin/add-member")
def add_member(body: AddMemberBody, db: Session = Depends(get_db)):
    """Manual grant/revoke: comps, refunds, support fixes."""
    email = body.email.strip().lower()
    member = db.execute(select(models.Member).where(
        models.Member.email == email)).scalar_one_or_none()
    if member:
        member.active = body.active
    else:
        db.add(models.Member(email=email, active=body.active, source="manual"))
    db.commit()
    return {"email": email, "active": body.active}


@router.get("/api/admin/members")
def list_members(db: Session = Depends(get_db)):
    rows = db.execute(select(models.Member)
        .order_by(_desc(models.Member.created))).scalars().all()
    return {"count": len(rows), "members": [
        {"email": r.email, "active": r.active, "source": r.source,
         "since": r.created.date().isoformat()} for r in rows]}


@router.get("/api/admin/login-code")
def admin_peek_code(email: str, db: Session = Depends(get_db)):
    """Support fallback when email delivery fails: shows whether a live code
    exists for this member so you can walk them through login. (Codes are
    hashed; issue a fresh one with request-code, then read Resend logs, or
    use add-member + /welcome as the manual path.)"""
    from datetime import datetime as _dt
    row = db.execute(select(models.LoginCode).where(
        models.LoginCode.email == email.strip().lower(),
        models.LoginCode.used.is_(False),
        models.LoginCode.expires > _dt.utcnow())
        .order_by(_desc(models.LoginCode.id)).limit(1)).scalar_one_or_none()
    return {"email": email, "live_code_exists": bool(row),
            "expires": row.expires.isoformat() if row else None}


# ============================ MEMBER WATCHLIST ==============================
def _member_from_token(db, token: str):
    email = _verify_token(token or "")
    if not email:
        return None
    member = db.execute(select(models.Member).where(
        models.Member.email == email)).scalar_one_or_none()
    return member if (member and member.active) else None


def _watchlist_payload(db, member) -> dict:
    rows = db.execute(select(models.WatchlistItem).where(
        models.WatchlistItem.member_id == member.id)
        .order_by(models.WatchlistItem.created)).scalars().all()
    items = []
    for r in rows:
        c = db.execute(select(models.Company).where(
            models.Company.ticker == r.ticker)).scalar_one_or_none()
        px = None
        if c:
            last = db.execute(select(models.DailyPrice).where(
                models.DailyPrice.company_id == c.id)
                .order_by(_desc(models.DailyPrice.day)).limit(1)
            ).scalar_one_or_none()
            px = last.close if last else None
        items.append({"ticker": r.ticker,
                      "name": c.name if c else None,
                      "exchange": c.exchange if c else None,
                      "close": px,
                      "grade": _grade_of(db, c.id) if c else None})
    return {"ok": True, "tickers": [r.ticker for r in rows], "items": items}


class WatchBody(BaseModel):
    token: str
    ticker: str


class WatchSyncBody(BaseModel):
    token: str
    tickers: list[str]


@router.get("/api/watchlist")
def watchlist_get(token: str, db: Session = Depends(get_db)):
    member = _member_from_token(db, token)
    if not member:
        return {"ok": False, "error": "not a member session"}
    return _watchlist_payload(db, member)


@router.post("/api/watchlist/add")
def watchlist_add(body: WatchBody, db: Session = Depends(get_db)):
    member = _member_from_token(db, body.token)
    if not member:
        return {"ok": False, "error": "not a member session"}
    t = body.ticker.upper().strip()[:10]
    exists = db.execute(select(models.WatchlistItem).where(
        models.WatchlistItem.member_id == member.id,
        models.WatchlistItem.ticker == t)).scalar_one_or_none()
    if not exists and t:
        db.add(models.WatchlistItem(member_id=member.id, ticker=t))
        db.commit()
    return _watchlist_payload(db, member)


@router.post("/api/watchlist/remove")
def watchlist_remove(body: WatchBody, db: Session = Depends(get_db)):
    member = _member_from_token(db, body.token)
    if not member:
        return {"ok": False, "error": "not a member session"}
    t = body.ticker.upper().strip()
    row = db.execute(select(models.WatchlistItem).where(
        models.WatchlistItem.member_id == member.id,
        models.WatchlistItem.ticker == t)).scalar_one_or_none()
    if row:
        db.delete(row)
        db.commit()
    return _watchlist_payload(db, member)


@router.post("/api/watchlist/sync")
def watchlist_sync(body: WatchSyncBody, db: Session = Depends(get_db)):
    """Merge a device's cookie watchlist into the member's server list -
    called once right after login so nothing saved pre-login is lost."""
    member = _member_from_token(db, body.token)
    if not member:
        return {"ok": False, "error": "not a member session"}
    have = {r.ticker for r in db.execute(select(models.WatchlistItem).where(
        models.WatchlistItem.member_id == member.id)).scalars()}
    for t in body.tickers[:100]:
        t = t.upper().strip()[:10]
        if t and t not in have:
            db.add(models.WatchlistItem(member_id=member.id, ticker=t))
            have.add(t)
    db.commit()
    return _watchlist_payload(db, member)


# ============================ THE ASSAYER ===================================
# Bring your thesis. Leave with the truth.

ASSAYER_DAILY_CAP = 10


def _verified_events(db, c) -> dict:
    """Financings and promotions whose SOURCE HEADLINE actually names this
    company. Anything unverifiable is withheld rather than asserted."""
    from .services.attribution import source_names_company as _names_co
    fins = db.execute(select(models.Financing).where(
        models.Financing.company_id == c.id)
        .order_by(_desc(models.Financing.announced)).limit(8)).scalars().all()
    promos = db.execute(select(models.Promotion).where(
        models.Promotion.company_id == c.id)
        .order_by(_desc(models.Promotion.announced)).limit(6)).scalars().all()
    ok_f = [x for x in fins if _names_co(x.headline or "", c.ticker, c.name,
                                         c.exchange)]
    ok_p = [x for x in promos if _names_co(x.headline or "", c.ticker, c.name,
                                           c.exchange)]
    return {"financings": ok_f, "promotions": ok_p,
            "withheld": (len(fins) - len(ok_f)) + (len(promos) - len(ok_p))}


def _assayer_context(db, ticker: str) -> dict:
    """Everything OreLens knows about this company, packed for the model."""
    c = db.execute(select(models.Company).where(
        models.Company.ticker == ticker)).scalar_one_or_none()
    if not c:
        return {"tracked": False}
    ctx: dict = {"tracked": True, "name": c.name, "exchange": c.exchange,
                 "commodity": c.commodity, "jurisdiction": c.jurisdiction,
                 "shares_outstanding": c.shares_outstanding,
                 "dilution_grade": _grade_of(db, c.id)}
    last = db.execute(select(models.DailyPrice).where(
        models.DailyPrice.company_id == c.id)
        .order_by(_desc(models.DailyPrice.day)).limit(1)).scalar_one_or_none()
    if last:
        ctx["latest_close"] = last.close
        ctx["priced_as_of"] = last.day.isoformat()
    br = _burn_runway(db, c.id)
    if br:
        ctx["cash"] = br["fin"].cash
        ctx["cash_as_of"] = br["fin"].as_of.isoformat()
        ctx["monthly_burn"] = br["burn"]
        ctx["burn_source"] = br["burn_source"]
        ctx["runway_months"] = br["runway"] and round(br["runway"], 1)
        ctx["adjusted_runway_months"] = br["adj_runway"] and round(br["adj_runway"], 1)
        if br["closed_amt"]:
            ctx["raise_closed_recently"] = {"amount": br["closed_amt"],
                                            "date": str(br["closed_date"])}
        if br["announced_amt"] or br["announced_date"]:
            ctx["raise_announced_not_closed"] = {
                "amount": br["announced_amt"] or None,
                "date": str(br["announced_date"])}
    # share growth 1y
    hist = db.execute(select(models.SharesHistory).where(
        models.SharesHistory.company_id == c.id)
        .order_by(models.SharesHistory.as_of)).scalars().all()
    if len(hist) >= 2:
        yr_ago = [h for h in hist if (hist[-1].as_of - h.as_of).days >= 330]
        if yr_ago and yr_ago[-1].shares:
            ctx["share_growth_1y_pct"] = round(
                (hist[-1].shares / yr_ago[-1].shares - 1) * 100, 1)
    # active/recent promotions
    _ev = _verified_events(db, c)
    if _ev["promotions"]:
        ctx["paid_promotions"] = [
            {"announced": str(p.announced), "firm": p.firm, "paid": p.amount,
             "ends": str(p.ends) if p.ends else None,
             "source_headline": (p.headline or "")[:160]}
            for p in _ev["promotions"][:3]]
    if _ev["financings"]:
        ctx["financings_verified"] = [
            {"announced": str(x.announced), "closed": bool(x.closed),
             "amount": x.amount, "kind": x.kind,
             "source_headline": (x.headline or "")[:160]}
            for x in _ev["financings"][:4]]
    ctx["events_withheld_unverified"] = _ev["withheld"]
    # upcoming unlocks
    from datetime import timedelta as _td
    unlocks = db.execute(select(models.Financing).where(
        models.Financing.company_id == c.id,
        models.Financing.hold_expiry.is_not(None),
        models.Financing.hold_expiry >= date.today(),
        models.Financing.hold_expiry <= date.today() + _td(days=120))
        ).scalars().all()
    if unlocks:
        ctx["upcoming_unlocks"] = [
            {"free_trades": str(u.hold_expiry), "amount": u.amount}
            for u in unlocks]
    return ctx


ASSAYER_SYSTEM = """You are The Assayer - the trade-idea grader inside OreLens, \
the dilution-intelligence terminal for mining stocks. A member brings you their \
trade idea; you tell them what the sample is really worth. Voice: a sharp, \
fair trading-desk mentor. Direct, specific, zero hype, zero filler. You are a \
research tool, never an advisor - grade the QUALITY OF THE IDEA AND ITS \
REASONING, don't tell them to buy or sell.

AUTHORITY SPLIT - follow this strictly:
- PLATFORM DATA is authoritative for FIGURES: cash, burn, runway, raises \
(closed and announced), paid promotions, unlock dates and sizes, share \
counts, and recent prices. Weigh these heavily; if figures contradict the \
thesis, say so plainly.
- YOUR OWN KNOWLEDGE is authoritative for COMPANY IDENTITY: what the company \
actually is, its primary commodity and flagship asset, producer vs developer \
vs explorer status, jurisdiction, and where it trades. Platform \
classification fields (name/commodity/exchange) can be coarse or stale - if \
they conflict with what you know about a well-known company, TRUST YOUR \
KNOWLEDGE and quietly use the correct identity (you may note the platform \
tag looked off in one short clause, no more).
- MISSING DATA IS MISSING, NOT ZERO: if burn, cash, or runway are absent or \
zero-with-no-context, say the filings picture is thin - NEVER claim a \
company "has no burn" or "infinite runway" from absent data.
- EVENTS NEED SOURCES: only state that a company announced, closed, or is \
running a financing or promotion if that event appears in PLATFORM DATA with \
a source_headline that names this company. Never infer, guess, or recall \
such events from your own memory, and never state a date for one that isn't \
in the platform data. If no such events are present, say the platform shows \
no recent financing or promotion activity on record - that is a complete and \
acceptable answer. Getting this wrong publishes a false statement about a \
real issuer, which is the single worst error you can make.
- The member picked an exchange in the form; the platform may record a \
different primary listing. Don't scold either way - many names trade on \
multiple venues. Use the correct primary listing if you know it.

If the company isn't tracked, grade the thesis on its own logic, use your \
knowledge of the company, and say the dilution picture is unverified.

Respond with ONLY a JSON object, no markdown fences, in exactly this shape:
{"grade": "A"|"B"|"C"|"D"|"F",
 "score": 0-100,
 "verdict": "one punchy sentence",
 "dilution_risk": "2-4 sentences on THIS company's dilution/runway/unlock picture using the platform data",
 "strengths": ["...", "..."],
 "risks": ["...", "..."],
 "checklist": [{"item": "Runway vs. thesis timeframe", "status": "pass"|"warn"|"fail"},
               {"item": "Dilution overhang", "status": ...},
               {"item": "Promotion activity", "status": ...},
               {"item": "Entry vs. recent price", "status": ...},
               {"item": "Thesis specificity", "status": ...}],
 "feedback": "3-5 sentences of mentor feedback on the thesis itself - what's sharp, what's missing, what would make it institutional-grade"}"""


class AssayBody(BaseModel):
    token: str
    ticker: str
    exchange: str
    entry_price: float
    thesis: str


@router.post("/api/assayer")
def assay_trade(body: AssayBody, db: Session = Depends(get_db)):
    """The Assayer: grades a member's trade idea against the platform's
    dilution intelligence. Members only; capped per day."""
    import json as _json
    import httpx as _hx
    from datetime import datetime as _dt, timedelta as _td
    from .config import settings as _s
    member = _member_from_token(db, body.token)
    if not member:
        return {"ok": False, "error": "Log in to use The Assayer."}
    if not _s.anthropic_api_key:
        return {"ok": False, "error": "The Assayer is being connected - "
                "ANTHROPIC_API_KEY not configured yet."}
    today_count = len(db.execute(select(models.TradeIdea).where(
        models.TradeIdea.member_id == member.id,
        models.TradeIdea.created >= _dt.utcnow() - _td(days=1))
        ).scalars().all())
    if today_count >= ASSAYER_DAILY_CAP:
        return {"ok": False, "error": f"Daily limit reached "
                f"({ASSAYER_DAILY_CAP} assays per day). Back tomorrow."}
    ticker = body.ticker.upper().strip()[:10]
    thesis = body.thesis.strip()[:4000]
    if not ticker or len(thesis) < 20:
        return {"ok": False, "error": "Give The Assayer a ticker and a real "
                "thesis (a few sentences minimum)."}
    ctx = _assayer_context(db, ticker)
    if not ctx.get("tracked"):
        # kick a background ingest so the NEXT assay has full dilution context
        import threading as _th
        if _ADD_STATUS.get(ticker, {}).get("state") != "running":
            _ADD_STATUS[ticker] = {"state": "running"}
            _th.Thread(target=_ingest_new_ticker, args=(ticker,),
                       daemon=True).start()
        ctx["note"] = ("Not yet in the OreLens universe - a filings pull "
                       "just started in the background.")
    user_msg = _json.dumps({
        "trade_idea": {"ticker": ticker, "exchange": body.exchange,
                       "entry_price": body.entry_price, "thesis": thesis},
        "platform_data": ctx,
        "today": date.today().isoformat()})
    try:
        with _hx.Client(timeout=60) as client:
            r = client.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": _s.anthropic_api_key,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": _s.assayer_model, "max_tokens": 1400,
                      "system": ASSAYER_SYSTEM,
                      "messages": [{"role": "user", "content": user_msg}]})
            data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        result = _json.loads(text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"The assay furnace misfired - try "
                f"again in a moment. ({str(exc)[:80]})"}
    db.add(models.TradeIdea(member_id=member.id, ticker=ticker,
                            exchange=body.exchange[:10],
                            entry_price=body.entry_price, thesis=thesis,
                            grade=str(result.get("grade", ""))[:2],
                            response_json=_json.dumps(result)[:20000]))
    db.commit()
    return {"ok": True, "ticker": ticker, "tracked": ctx.get("tracked", False),
            "platform_context": ctx, "assay": result,
            "assays_left_today": ASSAYER_DAILY_CAP - today_count - 1}


@router.get("/api/assayer/history")
def assay_history(token: str, db: Session = Depends(get_db)):
    import json as _json
    member = _member_from_token(db, token)
    if not member:
        return {"ok": False, "error": "not a member session"}
    rows = db.execute(select(models.TradeIdea).where(
        models.TradeIdea.member_id == member.id)
        .order_by(_desc(models.TradeIdea.created)).limit(25)).scalars().all()
    return {"ok": True, "ideas": [
        {"ticker": r.ticker, "exchange": r.exchange, "entry": r.entry_price,
         "grade": r.grade, "when": r.created.isoformat(),
         "assay": _json.loads(r.response_json) if r.response_json else None}
        for r in rows]}


class DeleteCompanyBody(BaseModel):
    ticker: str


@router.post("/api/admin/delete-company")
def delete_company(body: DeleteCompanyBody, db: Session = Depends(get_db)):
    """Remove a company and every record tied to it (prices, financials,
    warrants, drills, releases, grades, financings, promotions, watchlist
    entries). For mis-resolved tickers and delisted names."""
    from sqlalchemy import delete as _delete
    t = body.ticker.upper().strip()
    c = db.execute(select(models.Company).where(
        models.Company.ticker == t)).scalar_one_or_none()
    if not c:
        return {"ok": False, "error": f"{t} not tracked"}
    removed: dict = {}
    for cls in (models.DailyPrice, models.FinancialSnapshot,
                models.WarrantTranche, models.DrillProgram,
                models.DrillResult, models.PressRelease, models.InsiderBuy,
                models.DilutionGrade, models.SharesHistory,
                models.Financing, models.Promotion):
        if hasattr(cls, "company_id"):
            res = db.execute(_delete(cls).where(cls.company_id == c.id))
            removed[cls.__tablename__] = res.rowcount
    res = db.execute(_delete(models.WatchlistItem).where(
        models.WatchlistItem.ticker == t))
    removed["watchlist_items"] = res.rowcount
    name = c.name
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted": t, "name": name, "removed_rows": removed}


class RemoveCompanyBody(BaseModel):
    ticker: str


@router.post("/api/admin/remove-company")
def remove_company(body: RemoveCompanyBody, db: Session = Depends(get_db)):
    """Delete a company and every trace of it (prices, shares history,
    financings, releases, promotions, grades, watchlist rows). For
    delistings, symbol collisions, and misclassified entries."""
    t = body.ticker.upper().strip()
    c = db.execute(select(models.Company).where(
        models.Company.ticker == t)).scalar_one_or_none()
    if not c:
        return {"removed": False, "error": f"{t} not tracked"}
    counts: dict = {}
    import sqlalchemy as _sa
    for model in (models.DailyPrice, models.SharesHistory, models.Financing,
                  models.PressRelease, models.Promotion):
        if hasattr(model, "company_id"):
            res = db.execute(_sa.delete(model).where(
                model.company_id == c.id))
            counts[model.__tablename__] = res.rowcount
    # any other model with a company_id column (grades, filings, etc.)
    for mapper in models.Base.registry.mappers:
        model = mapper.class_
        if model in (models.DailyPrice, models.SharesHistory, models.Financing,
                     models.PressRelease, models.Promotion, models.Company):
            continue
        if hasattr(model, "company_id"):
            res = db.execute(_sa.delete(model).where(
                model.company_id == c.id))
            counts[model.__tablename__] = res.rowcount
    # watchlist rows are keyed by ticker, not company_id
    res = db.execute(_sa.delete(models.WatchlistItem).where(
        models.WatchlistItem.ticker == t))
    counts["watchlist_items"] = res.rowcount
    db.delete(c)
    db.commit()
    return {"removed": True, "ticker": t, "name": c.name,
            "rows_deleted": counts}


@router.get("/api/site-config")
def site_config():
    """Marketing-surface switches, all env-driven - no deploy to change."""
    from .config import settings as _s
    return {"training_video_url": _s.training_video_url or None}


# ==================== PUBLIC ADD-TICKER (background) ========================
# The search bar's "not tracked yet" path. Runs the slow ingest in a thread
# so the browser never waits on a 60-90s request (which the gateway would
# kill anyway), and reports progress via a status endpoint.

_ADD_STATUS: dict = {}
_ADD_EXCH_TRY = ("TSXV", "TSX", "CSE", "NYSE", "NASDAQ", "ASX")


def _ingest_new_ticker(tick: str) -> None:
    from .db import SessionLocal
    from .jobs.nightly import run_grades
    db = SessionLocal()
    try:
        c = db.execute(select(models.Company).where(
            models.Company.ticker == tick)).scalar_one_or_none()
        if not c:
            c = models.Company(ticker=tick, exchange="TSXV", name=tick,
                               commodity="Gold", jurisdiction="",
                               jurisdiction_tier="Tier 1", project_name="",
                               shares_outstanding=0)
            db.add(c)
            db.flush()
        data = marketdata.fetch_company_data(tick, c.exchange)
        if not data["prices"]:
            for alt in _ADD_EXCH_TRY:
                if alt == c.exchange:
                    continue
                alt_data = marketdata.fetch_company_data(tick, alt)
                if alt_data["prices"]:
                    data, c.exchange = alt_data, alt
                    break
        if not data["prices"]:
            db.rollback()
            _ADD_STATUS[tick] = {"state": "error", "error":
                f"Couldn't find {tick} on any exchange we cover "
                f"(TSX / TSX-V / CSE / NYSE / NASDAQ / ASX) - "
                f"double-check the symbol."}
            return
        if data["shares_outstanding"]:
            c.shares_outstanding = data["shares_outstanding"]
        have = {p.day for p in db.execute(select(models.DailyPrice).where(
            models.DailyPrice.company_id == c.id)).scalars()}
        for row in data["prices"]:
            if row["date"] not in have:
                db.add(models.DailyPrice(company_id=c.id, day=row["date"],
                                         close=row["close"],
                                         volume=row["volume"]))
        for sh in data.get("shares_history", []):
            if not db.execute(select(models.SharesHistory).where(
                    models.SharesHistory.company_id == c.id,
                    models.SharesHistory.as_of == sh["as_of"])).scalar_one_or_none():
                db.add(models.SharesHistory(company_id=c.id,
                                            as_of=sh["as_of"],
                                            shares=sh["shares"]))
        if data["cash"] and data["monthly_burn"]:
            if not db.execute(select(models.FinancialSnapshot).where(
                    models.FinancialSnapshot.company_id == c.id)).scalars().first():
                db.add(models.FinancialSnapshot(
                    company_id=c.id, as_of=date.today(), cash=data["cash"],
                    monthly_burn=data["monthly_burn"],
                    source_filing="Quarterly statements"))
        db.commit()
        run_grades(db)
        _ADD_STATUS[tick] = {"state": "done", "ticker": tick}
    except Exception:  # noqa: BLE001
        db.rollback()
        _ADD_STATUS[tick] = {"state": "error", "error":
            "The data pull hit a snag - give it another try in a minute."}
    finally:
        db.close()


class RequestTickerBody(BaseModel):
    ticker: str


@router.post("/api/request-ticker")
def request_ticker(body: RequestTickerBody, db: Session = Depends(get_db)):
    import re as _re
    import threading as _th
    tick = body.ticker.upper().strip()
    if not _re.fullmatch(r"[A-Z0-9.\-]{1,8}", tick):
        return {"error": "That doesn't look like a ticker symbol."}
    c = db.execute(select(models.Company).where(
        models.Company.ticker == tick)).scalar_one_or_none()
    if c:
        has_prices = db.execute(select(models.DailyPrice).where(
            models.DailyPrice.company_id == c.id).limit(1)).scalar_one_or_none()
        if has_prices:
            return {"tracked": True, "ticker": tick}
    if _ADD_STATUS.get(tick, {}).get("state") == "running":
        return {"started": True, "ticker": tick}
    running = sum(1 for v in _ADD_STATUS.values() if v.get("state") == "running")
    if running >= 3:
        return {"error": "A few new tickers are already being pulled - "
                "try again in a minute."}
    _ADD_STATUS[tick] = {"state": "running"}
    _th.Thread(target=_ingest_new_ticker, args=(tick,), daemon=True).start()
    return {"started": True, "ticker": tick}


@router.get("/api/request-ticker-status")
def request_ticker_status(ticker: str):
    return _ADD_STATUS.get(ticker.upper().strip(), {"state": "unknown"})


@router.post("/api/admin/regrade")
def regrade_all(db: Session = Depends(get_db)):
    """Recompute every company's grade immediately (same code the nightly runs)."""
    from .jobs.nightly import run_grades
    run_grades(db)
    n = len(db.execute(select(models.DilutionGrade)).scalars().all())
    return {"regraded": True, "grades": n}


class UpdateCompanyBody(BaseModel):
    ticker: str
    name: str | None = None
    commodity: str | None = None
    exchange: str | None = None
    jurisdiction: str | None = None


@router.post("/api/admin/update-company")
def update_company(body: UpdateCompanyBody, db: Session = Depends(get_db)):
    """Correct a company's identity fields (name / commodity / exchange)."""
    c = db.execute(select(models.Company).where(
        models.Company.ticker == body.ticker.upper().strip())).scalar_one_or_none()
    if not c:
        return {"updated": False, "error": "not tracked"}
    for field in ("name", "commodity", "exchange", "jurisdiction"):
        v = getattr(body, field)
        if v:
            setattr(c, field, v.strip())
    db.commit()
    return {"updated": True, "ticker": c.ticker, "name": c.name,
            "commodity": c.commodity, "exchange": c.exchange}


@router.get("/api/admin/staleness-audit")
def staleness_audit(db: Session = Depends(get_db)):
    """Which tickers look dead? Latest price day + gap vs the universe max."""
    from datetime import timedelta as _td
    max_day = db.execute(select(func.max(models.DailyPrice.day))).scalar()
    rows = db.execute(
        select(models.Company.ticker, models.Company.name,
               models.Company.exchange, func.max(models.DailyPrice.day))
        .join(models.DailyPrice, models.DailyPrice.company_id == models.Company.id,
              isouter=True)
        .group_by(models.Company.ticker, models.Company.name,
                  models.Company.exchange)).all()
    out = []
    for t, name, ex, d in rows:
        behind = (max_day - d).days if (d and max_day) else None
        out.append({"ticker": t, "name": name, "exchange": ex,
                    "last_price": str(d) if d else None,
                    "days_behind": behind if behind is not None else 9999})
    out.sort(key=lambda r: -r["days_behind"])
    return {"universe_max_day": str(max_day), "suspects":
            [r for r in out if r["days_behind"] > 10], "all_count": len(out)}


@router.get("/api/admin/audit-attribution")
def audit_attribution(fix: bool = False, db: Session = Depends(get_db)):
    """Find events whose source headline never names the company they're filed
    under - the misattribution class. fix=true deletes the bad rows."""
    from .services.attribution import source_names_company as _names_co, why_rejected
    import sqlalchemy as _sa
    bad_f, bad_p = [], []
    companies = {c.id: c for c in db.execute(select(models.Company)).scalars()}
    for x in db.execute(select(models.Financing)).scalars():
        c = companies.get(x.company_id)
        if not c:
            continue
        if not _names_co(x.headline or "", c.ticker, c.name, c.exchange):
            bad_f.append({"id": x.id, "ticker": c.ticker, "company": c.name,
                          "announced": str(x.announced),
                          "headline": (x.headline or "")[:110],
                          "why": why_rejected(x.headline or "", c.ticker, c.name)})
    for x in db.execute(select(models.Promotion)).scalars():
        c = companies.get(x.company_id)
        if not c:
            continue
        if not _names_co(x.headline or "", c.ticker, c.name, c.exchange):
            bad_p.append({"id": x.id, "ticker": c.ticker, "company": c.name,
                          "announced": str(x.announced),
                          "headline": (x.headline or "")[:110]})
    deleted = 0
    if fix:
        for row in bad_f:
            db.execute(_sa.delete(models.Financing).where(
                models.Financing.id == row["id"]))
            deleted += 1
        for row in bad_p:
            db.execute(_sa.delete(models.Promotion).where(
                models.Promotion.id == row["id"]))
            deleted += 1
        db.commit()
    return {"dry_run": not fix, "bad_financings": bad_f,
            "bad_promotions": bad_p, "deleted": deleted,
            "note": "Add ?fix=true to delete these rows."}


@router.get("/api/admin/integrity-report")
def integrity_report(db: Session = Depends(get_db)):
    """One call: is the data safe to show members? Combines attribution,
    freshness, burn evidence, and name hygiene into a single verdict."""
    from .services.attribution import (source_names_company as _names_co,
                                       distinctive_tokens as _tok)
    companies = {c.id: c for c in db.execute(select(models.Company)).scalars()}

    misattributed = 0
    for model in (models.Financing, models.Promotion):
        for row in db.execute(select(model)).scalars():
            c = companies.get(row.company_id)
            if c and row.headline and not _names_co(row.headline, c.ticker,
                                                    c.name, c.exchange):
                misattributed += 1

    stale = sorted(_stale_tickers(db))
    weak_names = [c.ticker for c in companies.values()
                  if not _tok(c.name or "")]
    unknown_burn = [g.company_id for g in db.execute(
        select(models.DilutionGrade)).scalars()
        if (g.adjusted_runway_m or 0) >= 990 and (g.adjusted_runway_m or 0) < 999]

    checks = [
        {"check": "Event attribution",
         "detail": "every financing/promotion traces to a headline naming the issuer",
         "status": "PASS" if misattributed == 0 else "FAIL",
         "count": misattributed},
        {"check": "Ticker freshness",
         "detail": "tickers with a live price feed (stale ones auto-hidden)",
         "status": "PASS" if not stale else "INFO",
         "count": len(stale), "tickers": stale[:12]},
        {"check": "Company naming",
         "detail": "names distinctive enough to attribute news safely",
         "status": "PASS" if not weak_names else "WARN",
         "count": len(weak_names), "tickers": weak_names[:12]},
        {"check": "Burn measurability",
         "detail": "companies whose filings are too thin to measure burn (shown as n/a)",
         "status": "INFO", "count": len(unknown_burn)},
    ]
    failing = [c for c in checks if c["status"] == "FAIL"]
    return {"verdict": "SAFE TO SHOW" if not failing else "ISSUES FOUND",
            "universe": len(companies), "checks": checks,
            "next_step": ("Nothing to do." if not failing else
                          "Run /api/admin/audit-attribution?fix=true")}
