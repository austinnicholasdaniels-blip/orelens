"""
Engine dispatcher: EODHD when the key is configured, Yahoo otherwise.
Everything upstream imports this module and never cares which engine ran.
"""
from __future__ import annotations

from ..config import settings
from . import eodhd, yahoo


def fetch_company_data(ticker: str, exchange: str, period: str = "6mo") -> dict:
    if settings.eodhd_api_key:
        data = eodhd.fetch_company_data(ticker, exchange, period)
        if data["prices"]:          # graceful fallback if EODHD lacks the name
            return data
    return yahoo.fetch_company_data(ticker, exchange, period)
