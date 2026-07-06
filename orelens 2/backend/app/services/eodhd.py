"""
EODHD market-data engine (All-In-One plan).

Drop-in replacement for the Yahoo engine: fetch_company_data() returns the
exact same dict shape, so every scanner, chart, and grade upstream is
untouched. Fundamentals are SEDAR-sourced for Canadian issuers - quarterly
balance sheets and cash-flow statements go back years, not quarters.

Exchange suffixes (EODHD codes - note ASX is .AU, not Yahoo's .AX):
    TSX -> .TO   TSXV -> .V   CSE -> .CN   NEO -> .NE   ASX -> .AU
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta

import httpx

from ..config import settings

log = logging.getLogger("orelens.eodhd")
BASE = "https://eodhd.com/api"
SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "NEO": ".NE",
          "ASX": ".AU", "NYSE": ".US", "NASDAQ": ".US", "OTC": ".US"}
PERIOD_DAYS = {"5d": 7, "1mo": 35, "3mo": 95, "6mo": 185, "1y": 370,
               "2y": 740, "5y": 1850, "10y": 3700, "max": 10950}


def _symbol(ticker: str, exchange: str) -> str:
    return f"{ticker.upper()}{SUFFIX.get(exchange.upper(), '.V')}"


def _get(path: str, params: dict) -> object | None:
    params = {**params, "api_token": settings.eodhd_api_key, "fmt": "json"}
    try:
        r = httpx.get(f"{BASE}/{path}", params=params, timeout=30,
                      follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("EODHD %s failed: %s", path, exc)
        return None


def _num(v) -> float | None:
    try:
        if v in (None, "", "None", "NA"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _qdate(s: str):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_company_data(ticker: str, exchange: str, period: str = "6mo") -> dict:
    """Same contract as yahoo.fetch_company_data. Returns:
    prices, shares_outstanding, cash, cash_history, monthly_burn,
    shares_history (+ extras: sector, industry, description,
    financing_cf_history for future screeners)."""
    out = {"prices": [], "shares_outstanding": None, "cash": None,
           "cash_history": [], "monthly_burn": None, "shares_history": [],
           "sector": None, "industry": None, "description": None,
           "financing_cf_history": []}
    if not settings.eodhd_api_key:
        return out
    sym = _symbol(ticker, exchange)

    # ---- prices --------------------------------------------------------
    frm = (date.today() - timedelta(days=PERIOD_DAYS.get(period, 185))).isoformat()
    rows = _get(f"eod/{sym}", {"period": "d", "from": frm})
    if isinstance(rows, list):
        for r in rows:
            d = _qdate(r.get("date"))
            close = _num(r.get("adjusted_close")) or _num(r.get("close"))
            if d and close:
                out["prices"].append({"date": d, "close": close,
                                      "volume": _num(r.get("volume")) or 0})

    # ---- fundamentals (SEDAR-sourced for .TO/.V/.CN) ---------------------
    fund = _get(f"fundamentals/{sym}", {})
    if not isinstance(fund, dict):
        return out

    gen = fund.get("General") or {}
    out["sector"] = gen.get("Sector")
    out["industry"] = gen.get("Industry")
    desc = gen.get("Description")
    out["description"] = desc[:2000] if isinstance(desc, str) else None

    stats = fund.get("SharesStats") or {}
    out["shares_outstanding"] = _num(stats.get("SharesOutstanding"))

    fin = fund.get("Financials") or {}
    bs_q = ((fin.get("Balance_Sheet") or {}).get("quarterly")) or {}
    cf_q = ((fin.get("Cash_Flow") or {}).get("quarterly")) or {}

    # quarterly cash + per-quarter share counts (multi-year on EODHD)
    for key in sorted(bs_q.keys()):
        q = bs_q[key] or {}
        d = _qdate(q.get("date") or key)
        if not d:
            continue
        cash = (_num(q.get("cashAndEquivalents")) or _num(q.get("cash"))
                or _num(q.get("cashAndShortTermInvestments")))
        if cash is not None:
            out["cash_history"].append({"as_of": d, "cash": cash})
        sh = _num(q.get("commonStockSharesOutstanding"))
        if sh:
            out["shares_history"].append({"as_of": d, "shares": sh})
    if out["cash_history"]:
        out["cash"] = out["cash_history"][-1]["cash"]
    if not out["shares_outstanding"] and out["shares_history"]:
        out["shares_outstanding"] = out["shares_history"][-1]["shares"]

    # true burn from operating cash flow; financing CF for Serial Raisers
    ocf_recent = []
    for key in sorted(cf_q.keys()):
        q = cf_q[key] or {}
        d = _qdate(q.get("date") or key)
        if not d:
            continue
        ocf = _num(q.get("totalCashFromOperatingActivities"))
        fcf = _num(q.get("totalCashFromFinancingActivities"))
        if ocf is not None:
            ocf_recent.append(ocf)
        if fcf is not None:
            out["financing_cf_history"].append({"as_of": d, "raised": fcf})
    burns = [-o for o in ocf_recent[-4:] if o and o < 0]
    if burns:
        out["monthly_burn"] = round(sum(burns) / len(burns) / 3.0, 0)

    return out


def fetch_news(ticker: str, exchange: str, days: int = 5, limit: int = 25) -> list[dict]:
    """Per-ticker financial news with real timestamps. Items match the
    wire-item shape the nightly consumes: headline/url/published/summary/wire."""
    if not settings.eodhd_api_key:
        return []
    sym = _symbol(ticker, exchange)
    frm = (date.today() - timedelta(days=days)).isoformat()
    rows = _get("news", {"s": sym, "from": frm, "limit": limit})
    items = []
    if isinstance(rows, list):
        for r in rows:
            title = (r.get("title") or "").strip()
            link = (r.get("link") or "").strip()
            if not title or not link:
                continue
            pub = None
            raw = str(r.get("date") or "")
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    pub = datetime.strptime(raw[:19 if "T" in raw else 19], fmt.replace("%z", ""))
                    break
                except ValueError:
                    continue
            items.append({"headline": title, "url": link,
                          "published": pub or datetime.utcnow(),
                          "summary": (r.get("content") or "")[:2000],
                          "wire": "EODHD"})
    return items
