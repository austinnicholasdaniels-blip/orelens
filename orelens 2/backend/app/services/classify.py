"""
Commodity classification from company metadata.

Exists because the add-ticker path used to stamp every new company "Gold",
which put Copper Giant in the gold cohort. Guessing a default is the same
error class as reporting a $0 burn: asserting something we don't know.
When the evidence is thin we return None and the company is marked Unknown.
"""
from __future__ import annotations

import re

# ordered: more specific phrases first so "rare earth" beats "earth"
COMMODITY_TERMS: list[tuple[str, tuple[str, ...]]] = [
    ("Rare Earths", ("rare earth", "neodymium", "praseodymium", "dysprosium",
                     "monazite")),
    ("Uranium", ("uranium", "u3o8", "yellowcake")),
    ("Lithium", ("lithium", "spodumene", "brine", "petalite")),
    ("Copper", ("copper", "cuprous", "porphyry copper", "chalcopyrite")),
    ("Silver", ("silver", "argentiferous")),
    ("Gold", ("gold", "auriferous", "dore", "doré")),
    ("Nickel", ("nickel", "laterite")),
    ("Zinc", ("zinc", "sphalerite")),
    ("Cobalt", ("cobalt",)),
    ("Potash", ("potash", "sylvinite")),
    ("Phosphate", ("phosphate",)),
    ("Coal", ("coal", "metallurgical coal", "thermal coal", "coking")),
    ("Iron Ore", ("iron ore", "magnetite", "hematite", "taconite")),
    ("Tin", ("tin ", "cassiterite")),
    ("Tungsten", ("tungsten", "scheelite")),
    ("Graphite", ("graphite",)),
    ("Vanadium", ("vanadium",)),
    ("Platinum", ("platinum", "palladium", "pgm", "pge")),
    ("Diamonds", ("diamond", "kimberlite")),
    ("Antimony", ("antimony", "stibnite")),
    ("Molybdenum", ("molybdenum",)),
    ("Titanium", ("titanium", "ilmenite", "rutile", "mineral sands")),
    ("Manganese", ("manganese",)),
    ("Silica", ("silica", "quartzite")),
]

# Non-mining signals: if these dominate, the company doesn't belong here at all
NON_MINING = ("asset management", "software", "biotech", "pharmaceutic",
              "cannabis", "real estate", "insurance", "restaurant", "apparel")


def _score(text: str) -> dict[str, int]:
    t = (text or "").lower()
    scores: dict[str, int] = {}
    for commodity, terms in COMMODITY_TERMS:
        n = sum(len(re.findall(rf"\b{re.escape(term.strip())}", t)) for term in terms)
        if n:
            scores[commodity] = n
    return scores


def infer_commodity(name: str = "", description: str = "",
                    industry: str = "") -> str | None:
    """Best-evidence commodity, or None when the evidence is too thin.

    The company NAME is weighted heavily (a company called "Copper Giant"
    is a copper company), then the business description.
    """
    # 1) the name is the strongest evidence there is
    name_scores = _score(name)
    if name_scores:
        return max(name_scores.items(), key=lambda kv: kv[1])[0]

    # 2) otherwise the business description, but only on a clear signal:
    #    repeated mentions, or the single commodity the company talks about
    body = _score(f"{description} {industry}")
    if not body:
        return None
    top, n = max(body.items(), key=lambda kv: kv[1])
    if n >= 2 or len(body) == 1:
        return top
    return None


def name_states_commodity(name: str) -> str | None:
    """Only when the NAME names exactly one commodity - used for safe
    auto-correction. 'Copper Giant' -> Copper. 'Aya Gold & Silver' -> None
    (ambiguous, needs a human)."""
    hits = _score(name)
    return next(iter(hits)) if len(hits) == 1 else None


def looks_non_mining(name: str = "", description: str = "",
                     industry: str = "") -> bool:
    t = f"{name} {description} {industry}".lower()
    return any(term in t for term in NON_MINING) and not _score(t)
