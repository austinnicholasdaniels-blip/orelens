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
        if not r.wire.startswith("Newsfile"):
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
