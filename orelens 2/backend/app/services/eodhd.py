"""
EODHD engine: licensed prices, SEDAR-sourced fundamentals, and per-ticker
news for TSX / TSXV / CSE / ASX juniors. Same contract as services.yahoo so
everything upstream (grades, charts, scanners) is engine-agnostic.
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta

import httpx

from ..config import settings

log = logging.getLogger("orelens.eodhd")
BASE = "https://eodhd.com/api"

# EODHD exchange suffixes (note ASX is .AU here, unlike Yahoo's .AX)
SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "ASX": ".AU",
          "NYSE": ".US", "NASDAQ": ".US", "OTC": ".US"}


def _sym(ticker: str, exchange: str) -> str:
    return f"{ticker}{SUFFIX.get(exchange.upper(), '.V')}"


def _get(path: str, **params) -> object | None:
    params.setdefault("api_token", settings.eodhd_api_key)
    params.setdefault("fmt", "json")
    try:
        r = httpx.get(f"{BASE}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("eodhd %s failed: %s", path, exc)
        return None


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def fetch_company_data(ticker: str, exchange: str, period: str = "6mo") -> dict:
    """Prices + shares + quarterly cash / burn / share history.
    Contract-identical to yahoo.fetch_company_data."""
    out = {"prices": [], "shares_outstanding": None, "cash": None,
           "monthly_burn": None, "cash_history": [], "shares_history": [],
           "sector": None, "industry": None, "description": None,
           "financing_cf_history": []}
    sym = _sym(ticker, exchange)

    days = {"5d": 7, "1mo": 35, "3mo": 95, "6mo": 190, "1y": 370,
            "2y": 740, "5y": 1830}.get(period, 190)
    frm = (date.today() - timedelta(days=days)).isoformat()
    eod = _get(f"eod/{sym}", **{"from": frm, "period": "d"})
    if isinstance(eod, list):
        for row in eod:
            try:
                out["prices"].append({
                    "date": datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    "close": float(row["close"]),
                    "volume": int(row.get("volume") or 0)})
            except (KeyError, TypeError, ValueError):
                continue

    fund = _get(f"fundamentals/{sym}")
    if isinstance(fund, dict):
        gen = fund.get("General") or {}
        out["sector"] = gen.get("Sector")
        out["industry"] = gen.get("Industry")
        out["description"] = (gen.get("Description") or "")[:1000] or None

        ss = (fund.get("SharesStats") or {}).get("SharesOutstanding")
        out["shares_outstanding"] = _num(ss)

        fin = fund.get("Financials") or {}
        bs_q = (fin.get("Balance_Sheet") or {}).get("quarterly") or {}
        for day_key in sorted(bs_q.keys()):
            row = bs_q[day_key] or {}
            try:
                as_of = datetime.strptime(day_key, "%Y-%m-%d").date()
            except ValueError:
                continue
            cash = _num(row.get("cashAndEquivalents")) or _num(row.get("cash"))
            if cash is not None:
                out["cash_history"].append({"as_of": as_of, "cash": cash})
            sh = _num(row.get("commonStockSharesOutstanding"))
            if sh:
                out["shares_history"].append({"as_of": as_of, "shares": sh})
        if out["cash_history"]:
            out["cash"] = out["cash_history"][-1]["cash"]
        if not out["shares_outstanding"] and out["shares_history"]:
            out["shares_outstanding"] = out["shares_history"][-1]["shares"]

        cf_q = (fin.get("Cash_Flow") or {}).get("quarterly") or {}
        ocf_burns = []
        for day_key in sorted(cf_q.keys()):
            row = cf_q[day_key] or {}
            try:
                as_of = datetime.strptime(day_key, "%Y-%m-%d").date()
            except ValueError:
                continue
            ocf = _num(row.get("totalCashFromOperatingActivities"))
            if ocf is not None and ocf < 0:
                ocf_burns.append(-ocf / 3.0)   # quarterly outflow -> monthly
            fcf = _num(row.get("totalCashFromFinancingActivities"))
            if fcf is not None:
                out["financing_cf_history"].append(
                    {"as_of": as_of, "raised": fcf})
        if ocf_burns:
            recent = ocf_burns[-4:]
            out["monthly_burn"] = round(sum(recent) / len(recent), 0)

    return out


def fetch_news(ticker: str, exchange: str, days: int = 4, limit: int = 20) -> list[dict]:
    """Per-ticker news with real timestamps. Items match the wire-item shape
    the nightly consumes: headline / url / published / summary / wire."""
    sym = _sym(ticker, exchange)
    frm = (date.today() - timedelta(days=days)).isoformat()
    data = _get("news", s=sym, limit=limit, **{"from": frm})
    items = []
    if isinstance(data, list):
        for a in data:
            try:
                pub = datetime.fromisoformat(
                    str(a.get("date", "")).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue
            title = (a.get("title") or "").strip()
            link = (a.get("link") or "").strip()
            if not title or not link:
                continue
            items.append({"headline": title, "url": link, "published": pub,
                          "summary": (a.get("content") or "")[:4000],
                          "wire": "EODHD"})
    return items
