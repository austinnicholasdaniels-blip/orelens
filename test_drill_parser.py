from app.services.drill_parser import parse_intercepts, parse_hit_ratio, is_drill_start, percentile_rank


def test_grade_first_gold():
    text = "Drilling intersects 12.4 g/t Au over 8.5 m in hole CB-24-018."
    [i] = parse_intercepts(text)
    assert i.commodity == "Gold" and i.grade == 12.4 and i.width_m == 8.5
    assert i.grade_meters == 105.4 and i.above_benchmark
    assert i.hole_id == "CB-24-018"


def test_width_first_copper():
    [i] = parse_intercepts("Highlights include 40 m grading 2.1% Cu from surface.")
    assert i.commodity == "Copper" and i.unit == "%" and i.grade_meters == 84.0
    assert i.above_benchmark


def test_gpt_alias_and_below_benchmark():
    [i] = parse_intercepts("Assays returned 1.2 gpt gold over 3.0 metres.")
    assert i.commodity == "Gold" and i.unit == "g/t"
    assert not i.above_benchmark  # 3.6 gram-meters


def test_multiple_and_dedup():
    text = ("Hole A returned 6.1 g/t Au over 14.0 m; "
            "hole B returned 14.0 m @ 6.1 g/t Au and also 2.4% Ni over 12.0 m.")
    got = parse_intercepts(text)
    assert len(got) == 2  # duplicate gold intercept deduped


def test_hit_ratio():
    assert parse_hit_ratio("6 of 10 holes intersected mineralization") == (6, 10)
    assert parse_hit_ratio("all 12 holes hit the target zone") == (12, 12)
    assert parse_hit_ratio("no ratio here") is None


def test_drill_start():
    assert is_drill_start("Diamond drilling underway at the project")
    assert is_drill_start("Rigs mobilized to site")
    assert not is_drill_start("Company announces AGM results")


def test_percentile():
    assert percentile_rank(100, [10, 20, 30, 40]) == 100.0
    assert percentile_rank(25, [10, 20, 30, 40]) == 50.0
