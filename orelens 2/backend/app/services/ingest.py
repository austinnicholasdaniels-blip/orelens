"""
Ingestion layer: three engines behind one module.

A) market_data      — daily OHLCV + shares outstanding via Financial Modeling Prep
B) filings          — SEDAR+ / EDGAR monitoring + PDF text + LLM structured extraction
C) newswire         — GlobeNewswire / PRNewswire / Accesswire RSS ingestion

Everything degrades gracefully without API keys so the app runs on seed data.
"""
from __future__ import annotations
import io
import json
import logging
from datetime import datetime

import feedparser
import httpx

from ..config import settings

log = logging.getLogger("orelens.ingest")

# --------------------------------------------------------------------------
# A) Core financial & market data engine (Financial Modeling Prep)
# --------------------------------------------------------------------------
FMP = "https://financialmodelingprep.com/api/v3"

# FMP ticker suffixes: TSX ".TO", TSXV ".V", CSE ".CN", ASX ".AX"
EXCHANGE_SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "ASX": ".AX"}


def fmp_symbol(ticker: str, exchange: str) -> str:
    return f"{ticker}{EXCHANGE_SUFFIX.get(exchange, '')}"


async def fetch_daily_quote(ticker: str, exchange: str) -> dict | None:
    """Returns {close, volume, shares_outstanding} or None."""
    if not settings.fmp_api_key:
        log.warning("FMP_API_KEY not set — skipping live quote for %s", ticker)
        return None
    sym = fmp_symbol(ticker, exchange)
    async with httpx.AsyncClient(timeout=20) as client:
        q = await client.get(f"{FMP}/quote/{sym}", params={"apikey": settings.fmp_api_key})
        q.raise_for_status()
        rows = q.json()
        if not rows:
            return None
        r = rows[0]
        return {
            "close": r.get("price"),
            "volume": r.get("volume"),
            "shares_outstanding": r.get("sharesOutstanding"),
        }


# --------------------------------------------------------------------------
# B) Regulatory filing scraper — SEDAR+ / EDGAR
# --------------------------------------------------------------------------
# SEDAR+ has no official public API; monitor per-issuer RSS/Atom feeds or a
# commercial mirror. EDGAR full-text + submissions API is free.
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
FILING_TYPES = ("MD&A", "Interim Financial Statements", "6-K", "10-Q", "40-F")


async def fetch_edgar_recent(cik: int) -> list[dict]:
    async with httpx.AsyncClient(
        timeout=20, headers={"User-Agent": "OreLens research contact@example.com"}
    ) as client:
        r = await client.get(EDGAR_SUBMISSIONS.format(cik=cik))
        r.raise_for_status()
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        return [
            {"form": f, "accession": a, "filed": d}
            for f, a, d in zip(
                recent.get("form", []),
                recent.get("accessionNumber", []),
                recent.get("filingDate", []),
            )
            if f in ("6-K", "10-Q", "40-F", "20-F")
        ]


def pdf_to_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text.append(page.extract_text() or "")
    return "\n".join(text)


EXTRACTION_PROMPT = """You are a mining-finance analyst. From the filing text below, extract:
1. cash_and_equivalents (number, in the filing's reporting currency)
2. monthly_burn_rate (number; if only quarterly operating cash outflow is stated, divide by 3)
3. warrants: array of {{strike_price, expiry_date (YYYY-MM-DD), quantity_outstanding}}
4. options: array of {{strike_price, expiry_date (YYYY-MM-DD), quantity_outstanding}}

Respond with ONLY a JSON object with keys: cash_and_equivalents, monthly_burn_rate, warrants, options.
No preamble, no markdown fences. Use null for anything not found.

FILING TEXT:
{filing_text}
"""


async def extract_capital_structure(filing_text: str) -> dict | None:
    """LLM parsing pass: filing text -> structured cash/burn/warrant JSON."""
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping filing extraction")
        return None
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    # keep within a sane budget: warrant tables live in the notes, usually late in the doc
    snippet = filing_text[:180_000]
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(filing_text=snippet)}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("LLM extraction returned non-JSON; skipping")
        return None


# --------------------------------------------------------------------------
# C) Real-time news wire ingestion
# --------------------------------------------------------------------------
# Newsfile is the dominant junior-mining wire in Canada; these are its
# official industry feeds (verified at newsfilecorp.com/newscategories.php).
# GlobeNewswire's mining subjectcode feed was dropped: it serves general
# releases (verified 2026-07) and polluted the news tab.
WIRE_FEEDS = {
    "Newsfile Mining": "https://feeds.newsfilecorp.com/industry/mining-metals",
    "Newsfile Precious": "https://feeds.newsfilecorp.com/industry/precious-metals",
    "Newsfile Energy Metals": "https://feeds.newsfilecorp.com/industry/energy-metals",
}


def fetch_wire_items() -> list[dict]:
    """Fetch each feed over httpx with a browser-style User-Agent (the feeds
    host rejects default library agents), then parse the bytes."""
    items = []
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36")}
    for wire, url in WIRE_FEEDS.items():
        try:
            resp = httpx.get(url, headers=ua, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for e in feed.entries:
                items.append({
                    "wire": wire,
                    "headline": e.get("title", ""),
                    "url": e.get("link", ""),
                    "published": datetime(*e.published_parsed[:6]) if e.get("published_parsed") else datetime.utcnow(),
                    "summary": e.get("summary", ""),
                })
        except Exception as exc:  # noqa: BLE001 — a dead feed must not kill the run
            log.error("feed %s failed: %s", wire, exc)
    return items
