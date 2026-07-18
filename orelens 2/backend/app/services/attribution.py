"""
Attribution guard: does this source document actually name this company?

Every event we attach to an issuer (financing, promotion) must be traceable to
a source that names the company. Substring matching on a full page is how a
GlobeNewswire release about IperionX ended up filed as an Aya financing.
"""
from __future__ import annotations

import re

# Words that appear in half the names in the sector - never distinctive.
GENERIC = {
    "gold", "silver", "mining", "mines", "miner", "resources", "resource",
    "corp", "corporation", "inc", "incorporated", "ltd", "limited", "plc",
    "metals", "metal", "exploration", "explorations", "minerals", "mineral",
    "holdings", "holding", "energy", "uranium", "lithium", "copper", "zinc",
    "nickel", "cobalt", "coal", "iron", "ore", "rare", "earths", "royalty",
    "royalties", "ventures", "venture", "capital", "group", "company",
    "international", "global", "american", "canadian", "north", "south",
    "new", "the", "and", "of", "development", "developments", "industries",
    "technologies", "technology", "materials", "partners", "trust", "fund",
}

EXCHANGES = r"TSX|TSXV|TSX-V|TSX\.V|CSE|CNSX|ASX|NYSE|NYSE American|NASDAQ|OTCQB|OTCQX|OTC"


def distinctive_tokens(name: str) -> list[str]:
    """Name words that actually identify this company (drops sector nouns)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    return [w for w in words if len(w) >= 3 and w.lower() not in GENERIC]


def source_names_company(text: str, ticker: str, name: str,
                         exchange: str = "") -> bool:
    """True only if the text plainly refers to this issuer.

    Accepts (a) an exchange parenthetical carrying the ticker, (b) the ticker
    as a standalone all-caps token, or (c) a distinctive name word on a word
    boundary. Never a bare substring.
    """
    if not text:
        return False
    t = ticker.upper().strip()

    # (a) "(TSX: AYA)" / "(NYSE American: IPX)"
    if t and re.search(rf"\((?:{EXCHANGES})\s*[:\-]?\s*{re.escape(t)}\b",
                       text, re.I):
        return True

    # (b) standalone ticker token, case-sensitive so "aya" in a word can't hit
    if len(t) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])",
                                 text):
        return True

    # (c) a distinctive name word, word-bounded and case-insensitive
    for tok in distinctive_tokens(name):
        if re.search(rf"\b{re.escape(tok)}\b", text, re.I):
            return True
    return False


def why_rejected(text: str, ticker: str, name: str) -> str:
    """Human-readable reason, for the audit report."""
    toks = distinctive_tokens(name)
    return (f"source never names {ticker}"
            + (f" or any of {toks}" if toks else " (name has no distinctive words)"))
