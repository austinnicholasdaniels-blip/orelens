"""
Financing lifecycle detection: parse placement/bought-deal announcements and
closings out of press-release text. Regex-first (auditable), conservative:
anything ambiguous returns None rather than a guess.
"""
from __future__ import annotations
import re

KIND_PAT = re.compile(
    r"\b(private placement|bought deal|public offering|brokered offering|"
    r"non-brokered (?:private )?placement|equity offering|unit offering)\b", re.I)
CLOSE_PAT = re.compile(r"\b(closes|closed|closing of|completes|completed|final closing)\b", re.I)
ANNOUNCE_PAT = re.compile(r"\b(announces|upsizes|increases|arranges|launches)\b", re.I)
# $12.5 million / $12,500,000 / C$8 million
AMOUNT_PAT = re.compile(
    r"(?:C?\$|CAD\s*\$?)\s*([\d,]+(?:\.\d+)?)\s*(million|M\b)?", re.I)
PRICE_PAT = re.compile(
    r"(?:price of|at a price of|per (?:unit|share|common share)[^$]{0,20})\s*C?\$\s*(\d+\.\d+)"
    r"|C?\$\s*(\d+\.\d+)\s*per\s*(?:unit|share|common share)", re.I)
STRIKE_PAT = re.compile(
    r"exercise price of\s*C?\$\s*(\d+\.\d+)|exercisable at\s*C?\$\s*(\d+\.\d+)", re.I)


def parse_financing(text: str) -> dict | None:
    """Return {kind, is_close, amount, price_per_unit, warrant_strike} or None."""
    km = KIND_PAT.search(text)
    if not km:
        return None
    is_close = bool(CLOSE_PAT.search(text[:180]))  # closings say so in the headline
    if not is_close and not ANNOUNCE_PAT.search(text[:180]):
        # mentions a placement but is neither announcing nor closing (e.g. recap news)
        return None

    amount = None
    am = AMOUNT_PAT.search(text)
    if am:
        raw = float(am.group(1).replace(",", ""))
        amount = raw * 1_000_000 if am.group(2) else raw
        if amount < 50_000:          # implausibly small -> misparse, drop
            amount = None

    price = None
    pm = PRICE_PAT.search(text)
    if pm:
        price = float(pm.group(1) or pm.group(2))

    strike = None
    sm = STRIKE_PAT.search(text)
    if sm:
        strike = float(sm.group(1) or sm.group(2))

    return {"kind": km.group(1).lower(), "is_close": is_close,
            "amount": amount, "price_per_unit": price, "warrant_strike": strike}

