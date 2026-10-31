"""The pure advisory rules (app/core/advisory.py). Package names are synthetic (example-widget).

Golden values were produced by running the Go scanner's own code, copied verbatim into a scratch program:
osv.go representativeID and cvss3BaseScore, and findings.BuildDependencyFinding's
sha256(eco|package|primary)[:16] fingerprint."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import advisory as adv
from app.services import audit_service

FIXTURES = Path(__file__).parent / "fixtures" / "osv"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
MAX_AGE = timedelta(hours=72)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_modified_csv_drops_partial_tail_and_bad_lines():
    text = (FIXTURES / "modified_id.csv").read_text()
    rows = adv.parse_modified_csv(text, drop_partial_tail=True)
    assert [i for _, i in rows] == ["GHSA-aaaa-bbbb-cccc", "MAL-2026-0001", "PYSEC-2026-1"]
    assert rows[1][0] == datetime(2026, 10, 30, 11, 59, 59, 500000, tzinfo=timezone.utc)
    # Without the flag the cut-off id would be taken as a (truncated) row.
    assert adv.parse_modified_csv(text, drop_partial_tail=False)[-1][1] == "GHSA-cut-off-by-a-ran"
    # A complete file (ends in a newline) loses nothing.
    assert len(adv.parse_modified_csv("2026-10-30T12:00:00Z,A-1\n", drop_partial_tail=True)) == 1


@pytest.mark.parametrize(
    "eco,name,expected",
    [
        ("PyPI", "Example_Widget.Py", "example-widget-py"),
        ("PyPI", "example__widget--py", "example-widget-py"),
        ("npm", "Example_Widget", "example_widget"),  # only PyPI folds separators
        ("Maven", "Org.Example:Widget", "org.example:widget"),
    ],
)
def test_normalize_package_name(eco, name, expected):
    assert adv.normalize_package_name(eco, name) == expected
    assert adv.dep_key(eco, name) == f"{eco}|{expected}"


def test_representative_id_prefers_ghsa_then_smallest():
    # Golden: Go representativeID on both inputs.
    assert adv.representative_id(["CVE-2026-0001", "GHSA-bbbb-cccc-dddd", "GHSA-aaaa-bbbb-cccc"]) == "GHSA-aaaa-bbbb-cccc"
    assert adv.representative_id(["PYSEC-2026-5", "CVE-2026-0001", "GO-2026-1"]) == "CVE-2026-0001"


def test_sca_fingerprint_matches_the_go_formula():
    # Golden: sha256("npm|example-widget|GHSA-aaaa-bbbb-cccc")[:16] computed by the Go formula.
    assert adv.sca_fingerprint("npm", "example-widget", "GHSA-aaaa-bbbb-cccc") == "f682ae5df1fadc42"
    # The package is hashed as the manifest spells it, not normalised.
    assert adv.sca_fingerprint("PyPI", "Example_Widget", "CVE-2026-0001") == "a1c6fc181528d94f"


@pytest.mark.parametrize(
    "vector,score",
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", 7.5),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", 5.3),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
        ("CVSS:3.0/AV:L/AC:H/PR:L/UI:R/S:C/C:L/I:L/A:N", 3.9),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
    ],
)
def test_cvss3_golden_vectors(vector, score):
    assert adv.cvss3_base_score(vector) == score


@pytest.mark.parametrize(
    "vector", ["CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", "AV:N/AC:L/Au:N/C:P/I:P/A:P", "", "CVSS:3.1/AV:N"]
)
def test_cvss3_rejects_other_or_incomplete_vectors(vector):
    assert adv.cvss3_base_score(vector) is None


def test_severity_precedence_label_then_cvss_then_medium():
    cvss = [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
    # The curated label wins over a vector that would say critical.
    assert adv.derive_severity({"database_specific": {"severity": "MODERATE"}, "severity": cvss}) == ("medium", 9.8)
    assert adv.derive_severity({"severity": cvss}) == ("critical", 9.8)
    # A vector under affected[] counts too, and the highest wins.
    nested = {"affected": [{"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"}]}], "severity": cvss}
    assert adv.derive_severity(nested) == ("critical", 9.8)
    # v2/v4 alone, or nothing at all, is medium.
    assert adv.derive_severity({"severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N"}]}) == ("medium", None)
    assert adv.derive_severity({}) == ("medium", None)


def test_malicious_is_critical_whatever_the_label():
    assert adv.derive_severity({"id": "MAL-2026-1", "database_specific": {"severity": "LOW"}}) == ("critical", None)
    assert adv.derive_severity(_fixture("MAL-2026-0001.json"))[0] == "critical"  # by origins too
    assert adv.derive_severity({"id": "GHSA-x", "aliases": ["MAL-1"]})[0] == "critical"


def test_normalize_advisory_from_fixture():
    a = adv.normalize_advisory(_fixture("GHSA-aaaa-bbbb-cccc.json"), "npm")
    assert a.id == "GHSA-aaaa-bbbb-cccc" and a.ids == ("GHSA-aaaa-bbbb-cccc", "CVE-2026-0001")
    assert a.severity == "high" and not a.malicious and not a.withdrawn
    (pkg,) = a.affected
    assert pkg.name_norm == "example-widget" and "1.2.3" in pkg.versions and pkg.fixed == ("1.2.4",)
    # Entries for another ecosystem are not this feed's business.
    assert adv.normalize_advisory(_fixture("GHSA-aaaa-bbbb-cccc.json"), "PyPI").affected == ()
    py = adv.normalize_advisory(_fixture("PYSEC-cvss-only.json"), "PyPI")
    assert py.severity == "critical" and py.cvss_score == 9.8 and py.affected[0].name_norm == "example-widget-py"


def test_is_new_uses_published_not_modified():
    fresh = adv.normalize_advisory(_fixture("GHSA-aaaa-bbbb-cccc.json"), "npm")
    assert adv.is_new(fresh, NOW, MAX_AGE)
    # Published 10 days ago but modified an hour ago: the common "old advisory edited" case.
    old = adv.normalize_advisory(
        {**_fixture("GHSA-aaaa-bbbb-cccc.json"), "published": "2026-10-20T10:00:00Z", "modified": "2026-10-30T11:00:00Z"}, "npm"
    )
    assert not adv.is_new(old, NOW, MAX_AGE)
    # In the future is not new either (a clock or feed fault), nor is a record with no published date.
    assert not adv.is_new(adv.normalize_advisory({**_fixture("GHSA-aaaa-bbbb-cccc.json"), "published": "2026-10-31T00:00:00Z"}, "npm"), NOW, MAX_AGE)
    assert not adv.is_new(adv.normalize_advisory({"id": "GHSA-nodate", "affected": []}, "npm"), NOW, MAX_AGE)


def test_withdrawn_is_not_new():
    withdrawn = adv.normalize_advisory(_fixture("GHSA-withdrawn.json"), "npm")
    assert withdrawn.withdrawn and not adv.is_new(withdrawn, NOW, MAX_AGE)


def test_severity_meets_and_off_never_meets():
    assert adv.severity_meets("critical", "high") and adv.severity_meets("high", "high")
    assert not adv.severity_meets("medium", "high")
    assert not adv.severity_meets("critical", "off")
    assert not adv.severity_meets("critical", "bogus")


def test_a_project_cannot_loosen_the_workspace_floor():
    assert adv.stricter("high", "medium") == "high"  # project asks for looser: floor stays
    assert adv.stricter("high", "critical") == "critical"
    assert adv.stricter("high", "off") == "off"
    assert adv.stricter("high", None) == "high"
    assert adv.stricter(None, "medium") == "medium"


def _row(i=0, severity="high", package="example-widget", **kw):
    loc = SimpleNamespace(
        repo_label="example/app",
        manifests=["package-lock.json"],
        direct=True,
        inventory_scan_id="s1",
        inventory_scanned_at=NOW - timedelta(days=1),
        git_commit="0123456789abcdef",
    )
    base = dict(
        advisory_id=f"GHSA-aaaa-bbbb-{i:04d}",
        advisory_ids=[f"GHSA-aaaa-bbbb-{i:04d}", f"CVE-2026-{i:04d}"],
        ecosystem="npm",
        package=package,
        version="1.2.3",
        severity=severity,
        cvss_score=7.5,
        malicious=False,
        published_at=NOW - timedelta(hours=3, minutes=i),
        fixed_versions=["1.2.4"],
        locations=[loc],
    )
    return SimpleNamespace(**{**base, **kw})


def test_single_advisory_message_has_released_fix_and_links():
    msg = adv.build_alert("Example Project", "p1", [_row()], NOW)
    assert msg.title == "Example Project: new HIGH advisory in example-widget 1.2.3"
    facts = dict(msg.facts)
    assert facts["Released"] == "30 Oct 2026 09:00 UTC (3h ago)"
    assert facts["Project"] == "Example Project"
    value = facts["GHSA-aaaa-bbbb-0000 · CVE-2026-0000"]
    assert "HIGH 7.5" in value and "example-widget 1.2.3 -> fix 1.2.4" in value and "1 repo: example/app" in value
    assert facts["Details"] == "https://osv.dev/vulnerability/GHSA-aaaa-bbbb-0000"
    assert "Published 30 Oct 2026 09:00 UTC (3h ago) on OSV.dev" in msg.text
    assert "Inventory as of scan 2026-10-29, commit 0123456." in msg.text and "Rescan to track it as a finding." in msg.text
    assert msg.link == "/projects/p1?tab=overview&src=alert"
    assert msg.notif_severity == "warning"


def test_message_never_claims_direct_or_transitive():
    msg = adv.build_alert("Example Project", "p1", [_row(), _row(1, locations=[SimpleNamespace(
        repo_label="x", manifests=["yarn.lock"], direct=False, inventory_scan_id=None, inventory_scanned_at=None, git_commit=None)])], NOW)
    blob = (msg.title + msg.text + json.dumps(msg.facts)).lower()
    assert "direct" not in blob and "transitive" not in blob


def test_no_fix_malicious_and_critical_wording():
    nofix = adv.build_alert("P", "p1", [_row(fixed_versions=[])], NOW)
    assert "fix none yet" in nofix.facts[2][1]
    mal = adv.build_alert("P", "p1", [_row(severity="critical", malicious=True, cvss_score=None)], NOW)
    assert mal.facts[2][1] == "MALICIOUS PACKAGE · remove example-widget 1.2.3"
    assert mal.notif_severity == "error"


def test_grouped_message_orders_worst_first_and_caps_facts():
    rows = [_row(i, severity="high" if i % 2 else "medium") for i in range(1, 9)] + [_row(99, severity="critical")]
    msg = adv.build_alert("P", "p1", rows, NOW)
    assert msg.title == "P: 9 new dependency advisories (1 critical, 4 high, 4 medium)"
    assert msg.facts[2][0].startswith("GHSA-aaaa-bbbb-0099")  # critical first
    assert len(msg.facts) <= 12 and ("More", "+4 more in the project") in msg.facts
    assert "Details" not in dict(msg.facts)


def test_card_with_twenty_advisories_fits_the_budget():
    from app.services import alert_service

    rows = [_row(i, package=f"example-widget-{i}") for i in range(20)]
    msg = adv.build_alert("Example Project", "p1", rows, NOW)
    card = alert_service.message_card(msg.title, msg.text, msg.link, msg.facts, tone="attention", eyebrow="New dependency advisory")
    assert len(json.dumps(card).encode()) < 12 * 1024


@pytest.mark.parametrize(
    "action,project_id,bucket",
    [
        ("Live Dependency Alert Raised", "p1", "project"),
        ("Advisory Watch Gap Skipped", None, "admin"),
        ("Advisory Watch Failed", None, "admin"),
        ("Live Alert Settings Changed", None, "admin"),
        ("Live Alert Check Triggered", None, "admin"),
    ],
)
def test_audit_action_names_are_not_misfiled_as_privilege(action, project_id, bucket):
    assert audit_service.classify(action, project_id) == bucket
