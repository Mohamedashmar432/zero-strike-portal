"""The evaluator is a pure function — these tests need no Mongo, no LLM and no client."""

import pytest

from app.core.compliance_catalog import FRAMEWORKS
from app.services.compliance_audit_service import EvidenceItem, evaluate


def _item(
    fingerprint="fp-1",
    severity="high",
    kind="sast",
    category="injection",
    owasp=(),
    cwe=(),
    scan_id="scan-1",
):
    return EvidenceItem(
        fingerprint=fingerprint,
        scan_id=scan_id,
        rule_id="rule-a",
        severity=severity,
        kind=kind,
        category=category,
        owasp=tuple(owasp),
        cwe=tuple(cwe),
        file="app/main.py",
        line=12,
        message="something bad",
    )


def _by_id(results):
    return {r.control_id: r for r in results}


def _evaluate(framework, items, evidence_cap=25, scan_count=1):
    return evaluate(framework, items, scan_count=scan_count, evidence_cap=evidence_cap)


def test_unknown_framework_raises():
    with pytest.raises(ValueError):
        _evaluate("not-a-framework", [])


def test_no_matching_findings_passes_with_an_explicitly_hedged_rationale():
    # Evidence exists (an unrelated dependency finding), just nothing this control matches.
    _, results = _evaluate("soc2", [_item(kind="sca", category="dependency", owasp=("A06:2025",))])
    injection = _by_id(results)["CC8.1"]
    assert injection.status == "pass"
    assert injection.evidence_total == 0
    # A pass must never read as "the control is implemented".
    assert "not proof the control is implemented" in injection.rationale
    assert "detected nothing matching" in injection.rationale


def test_a_high_severity_match_fails_the_control():
    _, results = _evaluate("soc2", [_item(severity="high", category="injection")])
    control = _by_id(results)["CC8.1"]
    assert control.status == "fail"
    assert control.evidence_total == 1
    assert control.severity_counts == {"high": 1}
    assert control.evidence[0].file == "app/main.py"


def test_only_medium_severity_matches_downgrade_to_partial():
    _, results = _evaluate("soc2", [_item(severity="medium", category="injection")])
    control = _by_id(results)["CC8.1"]
    assert control.status == "partial"
    assert "none at critical or high severity" in control.rationale


def test_controls_without_a_selector_are_needs_manual_review_not_pass():
    _, results = _evaluate("soc2", [_item()])
    governance = _by_id(results)["CC1.1"]
    assert governance.status == "needs_manual_review"
    assert governance.evidence == []
    assert "Governance control" in governance.rationale


def test_secret_findings_match_despite_having_no_owasp_codes():
    """kind=secret arrives from the scanner with owasp=[] and cwe=[] — an owasp-only mapping
    would miss every hardcoded credential."""
    item = _item(severity="low", kind="secret", category="secret", owasp=(), cwe=())
    _, results = _evaluate("soc2", [item])
    secrets = _by_id(results)["CC6.6"]
    # A committed secret fails at ANY severity, not just critical/high.
    assert secrets.status == "fail"
    assert secrets.evidence_total == 1


def test_dependency_findings_match_despite_having_no_owasp_codes():
    item = _item(severity="critical", kind="sca", category="dependency", owasp=(), cwe=())
    _, results = _evaluate("soc2", [item])
    assert _by_id(results)["CC7.3"].status == "fail"


def test_one_finding_can_satisfy_multiple_controls_across_frameworks():
    item = _item(severity="critical", kind="secret", category="secret")
    for framework, control_id in (
        ("soc2", "CC6.6"),
        ("iso27001", "A.8.12"),
        ("gdpr", "Art.5(1)(f)"),
        ("hipaa", "164.308(a)(5)(ii)(D)-tech"),
    ):
        _, results = _evaluate(framework, [item])
        assert _by_id(results)[control_id].status == "fail", framework


def test_evidence_is_capped_but_the_total_stays_exact():
    items = [_item(fingerprint=f"fp-{i}", category="injection") for i in range(40)]
    _, results = _evaluate("soc2", items, evidence_cap=5)
    control = _by_id(results)["CC8.1"]
    assert len(control.evidence) == 5
    assert control.evidence_total == 40


def test_evidence_is_ordered_worst_severity_first():
    items = [
        _item(fingerprint="fp-low", severity="low", category="injection"),
        _item(fingerprint="fp-crit", severity="critical", category="injection"),
        _item(fingerprint="fp-med", severity="medium", category="injection"),
    ]
    _, results = _evaluate("soc2", items, evidence_cap=3)
    assert [e.fingerprint for e in _by_id(results)["CC8.1"].evidence] == [
        "fp-crit",
        "fp-med",
        "fp-low",
    ]


def test_findings_with_no_severity_do_not_fail_a_control():
    """report_ingestion nulls out severities it doesn't recognise; an unrated finding is
    evidence worth surfacing but not grounds for asserting a control failure."""
    _, results = _evaluate("soc2", [_item(severity=None, category="injection")])
    control = _by_id(results)["CC8.1"]
    assert control.status == "partial"
    assert control.severity_counts == {"unknown": 1}


def test_summary_counts_are_consistent_with_the_control_results():
    items = [
        _item(severity="critical", category="injection"),
        _item(fingerprint="fp-2", severity="medium", kind="secret", category="secret"),
    ]
    for key in FRAMEWORKS:
        summary, results = _evaluate(key, items)
        assert summary.controls_total == len(results)
        assert (
            summary.passed
            + summary.failed
            + summary.partial
            + summary.not_applicable
            + summary.needs_manual_review
            == summary.controls_total
        )
        assert summary.assessed_total == sum(
            1 for c in FRAMEWORKS[key].controls if c.selector is not None
        )
        # v1 never emits not_applicable — it's reserved in the contract only.
        assert summary.not_applicable == 0


def test_evaluation_is_deterministic_for_the_same_evidence():
    items = [_item(fingerprint=f"fp-{i}", category="injection") for i in range(10)]
    first = _evaluate("iso27001", items)[1]
    second = _evaluate("iso27001", list(reversed(items)))[1]
    assert [(r.control_id, r.status, r.evidence_total) for r in first] == [
        (r.control_id, r.status, r.evidence_total) for r in second
    ]
    assert [e.fingerprint for e in first[0].evidence] == [e.fingerprint for e in second[0].evidence]
