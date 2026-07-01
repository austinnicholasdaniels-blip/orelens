"""
Near-Term Dilution Risk Model — the ABCDF grading algorithm.

Runs nightly after data sync. Pure functions so it's trivially unit-testable.

  Cash Runway (months)        = cash / monthly_burn
  Upcoming Drill Cost         = planned_holes * avg_depth * cost_per_meter
  Adjusted Cash Runway        = (cash - upcoming_drill_cost) / monthly_burn
  ITM Warrant Cash Potential  = sum(qty * strike  for tranches with strike < price)
  Overhang Ratio              = total warrants+options / shares outstanding
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class TrancheIn:
    strike: float
    quantity: float
    expiry: date
    hold_unlock: date | None = None


@dataclass
class GradeInput:
    cash: float
    monthly_burn: float
    price: float
    shares_outstanding: float
    tranches: list[TrancheIn] = field(default_factory=list)
    planned_holes: int = 0
    avg_depth_m: float = 0.0
    cost_per_meter: float = 250.0
    today: date = field(default_factory=date.today)


@dataclass
class GradeResult:
    grade: str
    cash_runway_m: float
    adjusted_runway_m: float
    upcoming_drill_cost: float
    itm_warrant_cash: float
    overhang_ratio: float
    unlock_risk_pct_float: float
    rationale: str


def compute_grade(x: GradeInput) -> GradeResult:
    burn = max(x.monthly_burn, 1.0)  # avoid div/0; a $0-burn shell is effectively infinite runway
    runway = x.cash / burn
    drill_cost = x.planned_holes * x.avg_depth_m * x.cost_per_meter
    adj_runway = (x.cash - drill_cost) / burn

    live = [t for t in x.tranches if t.expiry >= x.today]
    itm_cash = sum(t.quantity * t.strike for t in live if t.strike < x.price)
    total_overhang = sum(t.quantity for t in live)
    overhang_ratio = total_overhang / x.shares_outstanding if x.shares_outstanding else 0.0

    # PP 4-month hold unlocks landing within the next 7 days, as % of float
    week_out = x.today + timedelta(days=7)
    unlocking = sum(
        t.quantity for t in live
        if t.hold_unlock and x.today <= t.hold_unlock <= week_out
    )
    unlock_pct = unlocking / x.shares_outstanding if x.shares_outstanding else 0.0

    twelve_month_need = 12 * burn + drill_cost
    itm_covers_year = itm_cash >= twelve_month_need

    # ---- grading matrix (checked worst-first so severe conditions dominate) ----
    if adj_runway < 1 or unlock_pct > 0.25:
        grade = "F"
        why = ("Adjusted runway under 1 month" if adj_runway < 1
               else f"{unlock_pct:.0%} of float unlocks from 4-month hold this week")
    elif adj_runway < 3:
        grade, why = "D", "Adjusted runway under 3 months — imminent, highly dilutive financing required"
    elif adj_runway < 6:
        grade, why = "C", "Adjusted runway 3–6 months — financing window open; dilution likely next quarter unless warrants exercise"
    elif adj_runway < 12 and not itm_covers_year:
        grade, why = "B", "Adjusted runway 6–12 months — low immediate dilution risk"
    else:
        # A requires the funding condition AND a modest overhang
        if (adj_runway > 12 or itm_covers_year) and overhang_ratio < 0.15:
            grade = "A"
            why = ("Runway exceeds 12 months" if adj_runway > 12
                   else "ITM warrant exercises can fully fund the next 12 months of burn + drilling")
            why += f"; overhang {overhang_ratio:.1%} of float"
        else:
            grade, why = "B", f"Funding secure but warrant overhang is {overhang_ratio:.1%} of float (≥15%)"

    return GradeResult(
        grade=grade,
        cash_runway_m=round(runway, 1),
        adjusted_runway_m=round(adj_runway, 1),
        upcoming_drill_cost=round(drill_cost, 0),
        itm_warrant_cash=round(itm_cash, 0),
        overhang_ratio=round(overhang_ratio, 4),
        unlock_risk_pct_float=round(unlock_pct, 4),
        rationale=why,
    )
