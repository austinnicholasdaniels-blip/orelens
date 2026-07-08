"""
Stock-promotion detection: parse investor-awareness / IR / marketing
engagement disclosures out of press-release text. Conservative regexes.
"""
from __future__ import annotations
import re

TRIGGER_PAT = re.compile(
    r"investor awareness|investor relations (?:agreement|services|program|campaign)|"
    r"market(?:ing)? awareness|marketing (?:services|campaign|agreement)|"
    r"digital marketing|media campaign|advertising (?:campaign|services)|"
    r"market making (?:services|agreement)|capital markets advisory|"
    r"investor relations and capital markets|"
    r"engag\w+ .{0,60}(?:for )?investor", re.I)
FIRM_PAT = re.compile(
    r"[Ee]ngag\w+\s+(?:of\s+)?([A-Z][A-Za-z0-9&.,'\- ]{2,60}?)\s+(?:to |for |as |in )")
FIRM_PAT2 = re.compile(
    r"(?i:agreement|contract|partnership)[^.]{0,45}? with\s+([A-Z][A-Za-z0-9&.,'\- ]{2,60}?)(?:[,.(]|\s+(?:for|to|an|a)\b)")
FIRM_PAT3 = re.compile(
    r"(?:retained|services of|engagement of)\s+([A-Z][A-Za-z0-9&.,'\- ]{2,60}?)(?:[,.(]|\s+(?:to|for|as)\b)")
TERM_PAT = re.compile(
    r"(?:term of|period of|for|\ba)\s+(?:approximately\s+)?"
    r"(one|two|three|four|five|six|nine|twelve|\d{1,2})\s*(?:\(\d+\))?[\s-]*(month|year)", re.I)
MONTHLY_PAT = re.compile(
    r"(?:monthly (?:fee|payment|cash fee) of|per month[^$]{0,15})\s*(?:C|US)?\$\s*([\d,]+(?:\.\d+)?)"
    r"|(?:C|US)?\$\s*([\d,]+(?:\.\d+)?)\s*per month", re.I)
TOTAL_PAT = re.compile(
    r"(?:aggregate|total(?: consideration| fee| cost)? of|budget of|consideration of|cash fee of|compensation of|fees? of)\s*(?:up to\s*)?"
    r"(?:(?:C|US)?\$|EUR\s*|\u20ac\s*)\s*([\d,]+(?:\.\d+)?)\s*(million|M\b)?", re.I)
WEEKS_PAT = re.compile(
    r"(?:term of|period of|for|\ba)\s+(?:approximately\s+)?"
    r"(one|two|three|four|five|six|eight|ten|twelve|\d{1,2})\s*(?:\(\d+\))?[\s-]*weeks?", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "eight": 8, "nine": 9, "ten": 10, "twelve": 12}


def parse_promotion(text: str) -> dict | None:
    """Return {firm, term_months, monthly_fee, amount} or None."""
    if not TRIGGER_PAT.search(text):
        return None

    firm = None
    fm = FIRM_PAT.search(text) or FIRM_PAT2.search(text) or FIRM_PAT3.search(text)
    if fm:
        firm = fm.group(1).strip(" ,.")
        parts = firm.split()
        while parts and parts[-1][0].islower() and parts[-1] not in ("of", "and"):
            parts.pop()
        firm = " ".join(parts) or None

    term_months = None
    tm = TERM_PAT.search(text)
    if tm:
        n = WORDS.get(tm.group(1).lower()) or int(tm.group(1))
        term_months = n * 12 if tm.group(2).lower().startswith("year") else n
    else:
        wm = WEEKS_PAT.search(text)
        dm = re.search(r"(?:term of|period of|for)\s+(\d{2,3})[\s-]*days?", text, re.I)
        if wm:
            n = WORDS.get(wm.group(1).lower()) or int(wm.group(1))
            term_months = round(n / 4.33, 1)
        elif dm:
            term_months = round(int(dm.group(1)) / 30.4, 1)

    monthly = None
    mm = MONTHLY_PAT.search(text)
    if mm:
        monthly = float((mm.group(1) or mm.group(2)).replace(",", ""))

    amount = None
    for am in TOTAL_PAT.finditer(text):
        prefix = text[max(0, am.start() - 14):am.start()].lower()
        if "monthly" in prefix or "per month" in prefix:
            continue
        raw = float(am.group(1).replace(",", ""))
        cand = raw * 1_000_000 if am.group(2) else raw
        if cand >= 5_000 and (amount is None or cand > amount):
            amount = cand
    if amount is None and monthly and term_months:
        amount = monthly * term_months

    return {"firm": firm, "term_months": term_months,
            "monthly_fee": monthly, "amount": amount}


TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)


def html_to_text(html: str) -> str:
    """Cheap release-page text extraction for parsing."""
    html = SCRIPT_RE.sub(" ", html)
    html = re.sub(r"<br\s*/?>|</(p|tr|div|h[1-6]|li)>", "\n", html, flags=re.I)
    text = TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#36;", "$")
    return re.sub(r"[ \t]{2,}", " ", text)
