"""
Yahoo Finance data engine (via yfinance).

Covers TSX (.TO), TSX-V (.V), CSE (.CN), and ASX (.AX) at no cost.
Caveat: unofficial feed — fine for development/personal use; consider a
licensed provider (EODHD / FMP Premium) before building a paid product on it.

All functions here are blocking; call them from async code via
starlette.concurrency.run_in_threadpool.
"""
from __future__ import annotations
import logging
from datetime import date

log = logging.getLogger("orelens.yahoo")

SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "ASX": ".AX"}


def ysym(ticker: str, exchange: str) -> str:
    return f"{ticker}{SUFFIX.get(exchange, '')}"


def fetch_company_data(ticker: str, exchange: str, period: str = "6mo") -> dict:
    """Returns {prices, shares_outstanding, cash, monthly_burn, shares_history}.
    Any piece that fails comes back as None/empty — never raises."""
    import yfinance as yf
    import pandas as pd

    sym = ysym(ticker, exchange)
    out = {"prices": [], "shares_outstanding": None, "cash": None,
           "monthly_burn": None, "shares_history": []}
    t = yf.Ticker(sym)

    # --- daily price history ---
    try:
        df = t.history(period=period, interval="1d", auto_adjust=False)
        for idx, row in df.iterrows():
            if pd.isna(row.get("Close")):
                continue
            out["prices"].append({
                "date": idx.date() if hasattr(idx, "date") else idx,
                "close": float(row["Close"]),
                "volume": float(row.get("Volume") or 0),
            })
    except Exception as exc:  # noqa: BLE001
        log.error("history %s failed: %s", sym, exc)

    # --- shares outstanding ---
    try:
        so = t.fast_info.get("shares")
        if so:
            out["shares_outstanding"] = float(so)
    except Exception as exc:  # noqa: BLE001
        log.warning("shares %s failed: %s", sym, exc)

    # --- quarterly shares outstanding history ---
    try:
        qbs0 = t.quarterly_balance_sheet
        for label in ("Ordinary Shares Number", "Share Issued"):
            if qbs0 is not None and label in qbs0.index:
                ser = qbs0.loc[label].dropna()
                out["shares_history"] = [
                    {"as_of": idx.date() if hasattr(idx, "date") else idx,
                     "shares": float(v)} for idx, v in ser.items()]
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("shares history %s failed: %s", sym, exc)

    # --- cash & burn from quarterly statements ---
    try:
        qbs = t.quarterly_balance_sheet
        for label in ("Cash And Cash Equivalents",
                      "Cash Cash Equivalents And Short Term Investments"):
            if qbs is not None and label in qbs.index:
                v = qbs.loc[label].dropna()
                if len(v):
                    out["cash"] = float(v.iloc[0])
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("balance sheet %s failed: %s", sym, exc)
    try:
        qcf = t.quarterly_cashflow
        if qcf is not None and "Operating Cash Flow" in qcf.index:
            v = qcf.loc["Operating Cash Flow"].dropna()
            if len(v) and float(v.iloc[0]) < 0:
                out["monthly_burn"] = abs(float(v.iloc[0])) / 3.0
    except Exception as exc:  # noqa: BLE001
        log.warning("cashflow %s failed: %s", sym, exc)

    return out
