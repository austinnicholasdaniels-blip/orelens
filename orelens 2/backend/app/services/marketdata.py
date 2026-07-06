"""
Engine dispatcher: EODHD when the key is configured, Yahoo otherwise.
Everything upstream imports this module instead of a specific engine.
"""
from __future__ import annotations
from ..config import settings


def _engine():
    if settings.eodhd_api_key:
        from . import eodhd
        return eodhd
    from . import yahoo
    return yahoo


def fetch_company_data(ticker: str, exchange: str, period: str = "6mo") -> dict:
    return _engine().fetch_company_data(ticker, exchange, period)


def engine_name() -> str:
    return "eodhd" if settings.eodhd_api_key else "yahoo"
