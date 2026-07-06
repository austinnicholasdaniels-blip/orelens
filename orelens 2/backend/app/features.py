"""
Site features: search, on-demand ticker adds, notable-holder scanners,
and the AI ranking scanner (Claude API).
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
    return out


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
    return out


# ------------------------------------------------- press-release feed
@router.get("/api/scanners/news")
def news_feed(commodity: str | None = None, tier: str | None = None,
              db: Session = Depends(get_db)):
    """Latest mining press releases from the nightly wire sync, newest first."""
    rows = db.execute(select(models.PressRelease)
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
    return out[:100]


# ------------------------------------------------- coiled-springs scanner
@router.get("/api/scanners/coiled-springs")
def coiled_springs(commodity: str | None = None, tier: str | None = None,
                   db: Session = Depends(get_db)):
    from .services import scanners as _sc
    return _sc.scan_coiled_springs(db, commodity, tier)


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
    return out


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
    return out


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
                  r"\(\s*(TSXV|TSX-V|TSX VENTURE|TSX)\s*[:\s]\s*([A-Z]{1,6})(?:\.[A-Z])?\s*[\)|,]")

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
        fin = _latest_fin(db, c.id)
        if not fin or not fin.cash:
            continue
        score, why = 0, []
        runway = (fin.cash / fin.monthly_burn) if fin.monthly_burn else None
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
        # news-aware: a raise closed AFTER the cash snapshot means the
        # treasury is fuller than the quarterly figure - probability drops
        raised, raise_date, n_raises = _raises_since(db, c.id, fin.as_of)
        adj_runway = runway
        if raised and fin.monthly_burn:
            adj_runway = (fin.cash + raised) / fin.monthly_burn
            score = max(0, score - 35)
            why.append(f"but raised ${raised/1e6:.1f}M on {raise_date} "
                       f"(post-dates cash figure)")
        if score < 15:
            continue
        prob = ("VERY HIGH" if score >= 60 else "HIGH" if score >= 40
                else "ELEVATED" if score >= 25 else "MODERATE")
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "score": score, "probability": prob,
            "runway_m": adj_runway and round(adj_runway, 1),
            "cash_m": round((fin.cash + (raised or 0)) / 1e6, 1),
            "raises_3y": len(events),
            "why": " - ".join(why), "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: -x["score"])
    return out


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
        fin = _latest_fin(db, c.id)
        if not fin or not fin.monthly_burn or not fin.cash:
            continue
        raised, raise_date, _n = _raises_since(db, c.id, fin.as_of)
        adj_cash = fin.cash + (raised or 0)
        runway = adj_cash / fin.monthly_burn
        out.append({
            "ticker": c.ticker, "exchange": c.exchange, "name": c.name,
            "commodity": c.commodity, "jurisdiction_tier": c.jurisdiction_tier,
            "monthly_burn": round(fin.monthly_burn, 0),
            "cash_m": round(adj_cash / 1e6, 1),
            "raised_since_m": raised and round(raised / 1e6, 1),
            "runway_m": round(runway, 1),
            "as_of": (f"{fin.as_of.isoformat()} + raise {raise_date}"
                      if raised else fin.as_of.isoformat()),
            "grade": _grade_of(db, c.id),
        })
    out.sort(key=lambda x: x["runway_m"])
    return out


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
    return out


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
    return out


# ------------------------------------------------ EODHD news refresh (mining)
@router.post("/api/admin/refresh-news")
async def refresh_news(days: int = 30, purge_bunched: bool = True,
                       db: Session = Depends(get_db)):
    """Pull licensed per-ticker news for every tracked mining company right
    now, with real timestamps. Optionally purge the old scraped rows whose
    timestamps were all stamped at fetch time (the bunching defect)."""
    from starlette.concurrency import run_in_threadpool
    from collections import Counter
    from .config import settings as _s
    from .services import eodhd as _e
    from .services import financing as _finmod
    from .services import promotion as _promo
    from .jobs.nightly import _upsert_financing, _upsert_promotion
    if not _s.eodhd_api_key:
        return {"error": "EODHD_API_KEY not configured"}

    purged = 0
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
                purged += 1
        db.flush()

    stored = 0
    companies = db.execute(select(models.Company)).scalars().all()
    for c in companies:
        try:
            items = await run_in_threadpool(_e.fetch_news, c.ticker,
                                            c.exchange, days, 20)
        except Exception:  # noqa: BLE001
            continue
        for item in items:
            if db.execute(select(models.PressRelease).where(
                    models.PressRelease.url == item["url"])).scalar_one_or_none():
                continue
            text = f"{item['headline']} {item['summary']}"
            db.add(models.PressRelease(
                company_id=c.id, published=item["published"],
                headline=item["headline"][:400], url=item["url"][:400],
                wire="EODHD", body=item["summary"],
                is_drill_start=False))
            stored += 1
            fpar = _finmod.parse_financing(text)
            if fpar:
                _upsert_financing(db, c.id, item["published"],
                                  item["headline"][:400], item["url"][:400], fpar)
            ppar = _promo.parse_promotion(text)
            if ppar:
                _upsert_promotion(db, c.id, item["published"],
                                  item["headline"][:400], item["url"][:400], ppar)
    db.commit()
    total = len(db.execute(select(models.PressRelease)).scalars().all())
    return {"companies": len(companies), "news_stored": stored,
            "bunched_rows_purged": purged, "press_releases_total": total}
