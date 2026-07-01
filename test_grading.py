from datetime import date, timedelta
from app.services.grading import GradeInput, TrancheIn, compute_grade

TODAY = date(2026, 7, 1)


def base(**kw):
    d = dict(cash=12_000_000, monthly_burn=800_000, price=1.00,
             shares_outstanding=100_000_000, tranches=[], today=TODAY)
    d.update(kw)
    return GradeInput(**d)


def test_grade_a_long_runway_low_overhang():
    r = compute_grade(base())
    assert r.grade == "A" and r.cash_runway_m == 15.0


def test_a_blocked_by_overhang():
    tr = [TrancheIn(strike=2.0, quantity=20_000_000, expiry=TODAY + timedelta(days=365))]
    r = compute_grade(base(tranches=tr))
    assert r.grade == "B" and r.overhang_ratio == 0.2


def test_a_via_itm_warrant_coverage():
    # runway ~8.75 months but ITM warrants fund >12 months, overhang stays <15%
    tr = [TrancheIn(strike=0.90, quantity=14_000_000, expiry=TODAY + timedelta(days=365))]
    r = compute_grade(base(cash=7_000_000, tranches=tr))
    assert r.itm_warrant_cash == 12_600_000
    assert r.overhang_ratio == 0.14
    assert r.grade == "A"


def test_drill_cost_reduces_runway_to_c():
    r = compute_grade(base(cash=8_000_000, planned_holes=20, avg_depth_m=800, cost_per_meter=250))
    # drill cost 4.0M -> adjusted runway 5 months
    assert r.upcoming_drill_cost == 4_000_000 and r.grade == "C"


def test_grade_d():
    r = compute_grade(base(cash=2_000_000))
    assert r.grade == "D"


def test_grade_f_runway():
    r = compute_grade(base(cash=500_000))
    assert r.grade == "F"


def test_grade_f_unlock():
    tr = [TrancheIn(strike=0.05, quantity=30_000_000,
                    expiry=TODAY + timedelta(days=120),
                    hold_unlock=TODAY + timedelta(days=2))]
    r = compute_grade(base(tranches=tr))
    assert r.grade == "F" and r.unlock_risk_pct_float == 0.30


def test_expired_tranches_ignored():
    tr = [TrancheIn(strike=0.10, quantity=50_000_000, expiry=TODAY - timedelta(days=1))]
    r = compute_grade(base(tranches=tr))
    assert r.itm_warrant_cash == 0 and r.grade == "A"
