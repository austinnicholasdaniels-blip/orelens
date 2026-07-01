"""
Drill Result Engine
-------------------
Parses junior-mining press-release text into structured intercepts.

Handles the common newswire syntaxes:
  "12.4 g/t Au over 8.5 m"        "8.5 m @ 12.4 g/t Au"
  "12.4 gpt gold over 8.5 metres" "intersects 2.1% Cu over 40 m"
  "40 m grading 2.1% copper"      "1.4% Li2O over 22.0 m"

Design: deterministic regex first (cheap, auditable), optional LLM pass for
sentences the regex misses (see filings_parser.extract_with_llm for pattern).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- benchmarks
# grade x width thresholds ("gram-meters" / "%-meters") for a headline hit
BENCHMARKS = {
    "Gold":    {"unit": "g/t", "grade_meters": 50.0},   # e.g. 5 g/t over 10 m
    "Silver":  {"unit": "g/t", "grade_meters": 1500.0}, # ~ 150 g/t over 10 m
    "Copper":  {"unit": "%",   "grade_meters": 20.0},   # e.g. 2% over 10 m
    "Nickel":  {"unit": "%",   "grade_meters": 15.0},
    "Lithium": {"unit": "%",   "grade_meters": 15.0},   # % Li2O basis
    "Zinc":    {"unit": "%",   "grade_meters": 40.0},
}

COMMODITY_ALIASES = {
    "au": "Gold", "gold": "Gold",
    "ag": "Silver", "silver": "Silver",
    "cu": "Copper", "copper": "Copper",
    "ni": "Nickel", "nickel": "Nickel",
    "li2o": "Lithium", "li": "Lithium", "lithium": "Lithium",
    "zn": "Zinc", "zinc": "Zinc",
}

_NUM = r"(\d+(?:[.,]\d+)?)"
_LEN = r"(?:m|meters?|metres?)"
_COMM = r"(Au|Ag|Cu|Ni|Zn|Li2O|Li|gold|silver|copper|nickel|zinc|lithium)"

# "12.4 g/t Au over 8.5 m"   /  "2.1% Cu over 40 m" / "... across 40 m"
_P_GRADE_FIRST = re.compile(
    rf"{_NUM}\s*(g/t|gpt|%)\s*{_COMM}\s*(?:over|across|averaging over)\s*{_NUM}\s*{_LEN}",
    re.IGNORECASE,
)
# "8.5 m @ 12.4 g/t Au"  /  "40 m grading 2.1% Cu" / "40 m of 2.1% copper"
_P_WIDTH_FIRST = re.compile(
    rf"{_NUM}\s*{_LEN}\s*(?:@|at|grading|of|averaging)\s*{_NUM}\s*(g/t|gpt|%)\s*{_COMM}",
    re.IGNORECASE,
)
_P_HOLE = re.compile(r"\b((?:DDH|RC|HOLE|[A-Z]{1,4})[-_ ]?\d{2,4}[-_]?\d{0,4})\b")

# hit-ratio phrasing: "6 of 10 holes intersected..." / "all 12 holes"
_P_HIT_RATIO = re.compile(
    r"(\d{1,3})\s+(?:of|out of)\s+(\d{1,3})\s+holes?", re.IGNORECASE)
_P_ALL_HOLES = re.compile(r"all\s+(\d{1,3})\s+holes?", re.IGNORECASE)

DRILL_START_KEYWORDS = (
    "drilling commenced", "drilling has commenced", "commences drilling",
    "rigs mobilized", "rig mobilized", "mobilized to site",
    "phase 1 program", "phase one program", "phase 2 program",
    "diamond drilling underway", "drill program underway",
    "commencement of drilling", "begins drilling", "drilling begins",
)


@dataclass
class Intercept:
    commodity: str
    grade: float
    unit: str            # "g/t" or "%"
    width_m: float
    grade_meters: float
    above_benchmark: bool
    hole_id: str
    raw_sentence: str


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _norm_commodity(token: str) -> str:
    return COMMODITY_ALIASES.get(token.lower(), token.title())


def _mk(grade: float, unit: str, commodity: str, width: float, sentence: str) -> Intercept:
    unit = "g/t" if unit.lower() in ("g/t", "gpt") else "%"
    gm = round(grade * width, 2)
    bench = BENCHMARKS.get(commodity)
    above = bool(bench and bench["unit"] == unit and gm >= bench["grade_meters"])
    hole = _P_HOLE.search(sentence)
    return Intercept(
        commodity=commodity, grade=grade, unit=unit, width_m=width,
        grade_meters=gm, above_benchmark=above,
        hole_id=hole.group(1) if hole else "", raw_sentence=sentence.strip(),
    )


def parse_intercepts(text: str) -> list[Intercept]:
    """Extract every drill intercept from press-release text."""
    out: list[Intercept] = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        for m in _P_GRADE_FIRST.finditer(sentence):
            grade, unit, comm, width = _f(m.group(1)), m.group(2), _norm_commodity(m.group(3)), _f(m.group(4))
            out.append(_mk(grade, unit, comm, width, sentence))
        for m in _P_WIDTH_FIRST.finditer(sentence):
            width, grade, unit, comm = _f(m.group(1)), _f(m.group(2)), m.group(3), _norm_commodity(m.group(4))
            out.append(_mk(grade, unit, comm, width, sentence))
    # de-dup identical intercepts caught by both patterns
    seen, deduped = set(), []
    for i in out:
        key = (i.commodity, i.grade, i.unit, i.width_m)
        if key not in seen:
            seen.add(key)
            deduped.append(i)
    return deduped


def parse_hit_ratio(text: str) -> tuple[int, int] | None:
    """Returns (holes_hit, holes_drilled) if the release states it."""
    m = _P_HIT_RATIO.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _P_ALL_HOLES.search(text)
    if m:
        n = int(m.group(1))
        return n, n
    return None


def is_drill_start(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in DRILL_START_KEYWORDS)


def percentile_rank(value: float, population: list[float]) -> float:
    """Where an intercept's gram-meters sits vs. tracked peers (0-100)."""
    if not population:
        return 100.0
    below = sum(1 for v in population if v < value)
    return round(100.0 * below / len(population), 1)
