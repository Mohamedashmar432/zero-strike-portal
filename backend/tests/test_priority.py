from app.core.priority import compute_priority


def test_critical_severity_with_owasp_and_high_confidence_maxes_out():
    score, tier = compute_priority("critical", ["A03:2025"], "high")
    assert score == 10.0
    assert tier == "critical"


def test_high_severity_no_owasp_no_confidence_data_stays_high():
    score, tier = compute_priority("high", [], None)
    assert score == 6.0
    assert tier == "high"


def test_medium_severity_with_owasp_and_high_confidence_is_bumped_to_high_tier():
    score, tier = compute_priority("medium", ["A05:2025"], "high")
    assert score == 6.0
    assert tier == "high"


def test_high_severity_low_confidence_no_owasp_drops_to_medium_tier():
    score, tier = compute_priority("high", [], "low")
    assert score == 5.5
    assert tier == "medium"


def test_info_severity_with_owasp_and_high_confidence_never_leaves_low_tier():
    score, tier = compute_priority("info", ["A05:2025"], "high")
    assert score == 2.5
    assert tier == "low"


def test_unknown_severity_is_zero_baseline():
    score, tier = compute_priority(None, [], None)
    assert score == 0.0
    assert tier == "low"


def test_score_never_exceeds_ten():
    score, _ = compute_priority("critical", ["A01:2025", "A02:2025"], "high")
    assert score == 10.0
