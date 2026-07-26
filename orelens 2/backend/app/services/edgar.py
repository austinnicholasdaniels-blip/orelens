"""
SEC EDGAR filings for US-listed issuers.

Free, official, no API key. We store metadata only - form type, filing date,
and a link to the document on sec.gov - never the filing contents.

SEC asks for a descriptive User-Agent with contact details; sending one is a
condition of polite access to their service.
"""
from __future__ import annotations

import time
from datetime import date, datetime

import httpx

UA = {"User-Agent": "OreLens research platform (contact@getorelens.com)"}
TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

# forms worth surfacing to an investor; skip ownership noise (3/4/5) by default
INTERESTING = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "S-1", "S-1/A",
    "S-3", "S-3/A", "424B3", "424B5", "40-F", "20-F", "6-K", "DEF 14A",
}

_cik_cache: dict[str, str] | None = None


def cik_map() -> dict[str, str]:
    """ticker -> zero-padded CIK, from the SEC's own published mapping."""
    global _cik_cache
    if _cik_cache is not None:
        return _cik_cache
    out: dict[str, str] = {}
    try:
        r = httpx.get(TICKER_MAP, headers=UA, timeout=30)
        if r.status_code == 200:
            for row in r.json().values():
                t = str(row.get("ticker", "")).upper().strip()
                if t:
                    out[t] = str(row.get("cik_str", "")).zfill(10)
    except Exception:  # noqa: BLE001
        pass
    _cik_cache = out
    return out


def recent_filings(cik: str, limit: int = 25) -> list[dict]:
    """Most recent filings for one CIK - metadata and official links only."""
    try:
        r = httpx.get(SUBMISSIONS.format(cik=cik), headers=UA, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:  # noqa: BLE001
        return []

    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    descs = recent.get("primaryDocDescription") or []
    cik_int = str(int(cik))

    out: list[dict] = []
    for i, form in enumerate(forms):
        if form not in INTERESTING:
            continue
        try:
            filed = datetime.strptime(dates[i], "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            continue
        acc = accs[i] if i < len(accs) else ""
        doc = docs[i] if i < len(docs) else ""
        if not acc or not doc:
            continue
        url = ARCHIVE.format(cik_int=cik_int, acc_nodash=acc.replace("-", ""),
                             doc=doc)
        out.append({
            "form": form, "filed": filed, "accession": acc, "url": url,
            "title": (descs[i] if i < len(descs) and descs[i] else form),
        })
        if len(out) >= limit:
            break
    return out


def polite_pause() -> None:
    """SEC allows ~10 requests/second; stay well under it."""
    time.sleep(0.15)


def is_us_listed(exchange: str) -> bool:
    return (exchange or "").upper() in {"NYSE", "NASDAQ", "OTC", "NYSE AMERICAN"}


def as_date(v) -> date:
    return v if isinstance(v, date) else date.today()
