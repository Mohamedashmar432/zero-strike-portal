import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.scan import Scan
from app.schemas.report import GoFindingIn, GoLocationIn, GoReportIn, GoStatsIn
from app.services import report_ingestion_service as ingest_svc

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"


def _load() -> GoReportIn:
    return GoReportIn.model_validate(json.loads(_FIXTURE.read_text()))


def test_parses_pascalcase_report():
    report = _load()
    assert report.scanner_scan_id == "b3f1c2d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
    assert report.scanner_version == "v0.22.0"
    assert report.git_commit.startswith("a1b2c3d4")
    assert len(report.findings) == 4
    assert {f.kind for f in report.findings} == {"sast", "secret", "sca", "config"}


def test_finding_field_mapping_by_kind(client):
    report = _load()
    by_kind = {f.kind: ingest_svc._map_finding("s1", "p1", f) for f in report.findings}

    sast = by_kind["sast"]
    assert sast.rule_id == "ZS-PY-001"
    assert sast.severity == "critical"
    assert sast.location.file == "app/db.py"
    assert sast.location.start_line == 42
    assert sast.cwe == ["CWE-89"]
    assert sast.evidence[0].snippet.startswith("cursor.execute")
    assert sast.taint_context is not None
    assert sast.taint_context.source_var == "q"
    assert len(sast.taint_context.path) == 2

    secret = by_kind["secret"]
    assert secret.secret is not None
    assert secret.secret.detector_id == "aws-access-key-id"
    assert secret.secret.entropy == 4.7

    sca = by_kind["sca"]
    assert sca.dependency is not None
    assert sca.dependency.package == "lodash"
    assert sca.dependency.advisory_ids == ["CVE-2021-23337", "GHSA-35jh-r3h4-6jhm"]
    assert sca.dependency.direct is True

    config = by_kind["config"]
    assert config.config is not None
    assert config.config.framework == "django"
    assert config.config.key == "DEBUG"


def test_map_finding_computes_priority_score_and_tier():
    report = _load()
    by_kind = {f.kind: ingest_svc._map_finding("s1", "p1", f) for f in report.findings}

    sast = by_kind["sast"]  # critical, high confidence, OWASP-tagged
    assert sast.priority_score == 10.0
    assert sast.priority_tier == "critical"

    secret = by_kind["secret"]  # high, high confidence, no OWASP tag
    assert secret.priority_score == 6.5
    assert secret.priority_tier == "high"

    sca = by_kind["sca"]  # medium, high confidence, OWASP-tagged
    assert sca.priority_score == 6.0
    assert sca.priority_tier == "high"

    config = by_kind["config"]  # low, medium confidence, OWASP-tagged
    assert config.priority_score == 3.5
    assert config.priority_tier == "low"


def test_duration_ns_to_ms_and_stats():
    report = _load()
    assert report.duration_ns == 4_200_000_000
    stats = ingest_svc._stats(report.stats)
    assert stats.by_kind == {"sast": 1, "secret": 1, "sca": 1, "config": 1}
    assert stats.files_scanned == 120
    # ByScanner is not modeled and must not leak into the portal stats.
    assert not hasattr(stats, "by_scanner")


def test_diagnostic_location_flattened_to_string():
    report = _load()
    diags = [ingest_svc._diagnostic(d) for d in report.diagnostics]
    assert diags[0].location == "build/gen.py"  # object -> string (file)
    assert diags[1].location is None  # null location stays None


def test_invalid_severity_and_kind_coerced_to_none(client):
    f = GoFindingIn(severity="SEVERE", kind="mystery", message="x", location=GoLocationIn(file="a.py"))
    mapped = ingest_svc._map_finding("s1", "p1", f)
    assert mapped.severity is None
    assert mapped.kind is None


def test_missing_message_falls_back_to_rule_name(client):
    f = GoFindingIn(rule_name="Some Rule", location=GoLocationIn(file="a.py"))
    mapped = ingest_svc._map_finding("s1", "p1", f)
    assert mapped.message == "Some Rule"


def test_normalize_finding_path_strips_root_prefix():
    assert (
        ingest_svc.normalize_finding_path("/tmp/zs-clones/abc/src/app.py", "/tmp/zs-clones/abc")
        == "src/app.py"
    )
    # Windows-style separators, still under the same root.
    assert (
        ingest_svc.normalize_finding_path(r"C:\scans\abc\src\app.py", r"C:\scans\abc")
        == "src/app.py"
    )


def test_normalize_finding_path_leaves_relative_paths_untouched():
    # CLI/CI-uploaded reports: root_path may be "." or unrelated to the file path.
    assert ingest_svc.normalize_finding_path("app/db.py", ".") == "app/db.py"
    assert ingest_svc.normalize_finding_path("app/db.py", None) == "app/db.py"


def test_map_finding_stamps_project_repo_id_and_normalizes_path():
    f = GoFindingIn(message="x", location=GoLocationIn(file="/tmp/zs-clones/abc/app/db.py"))
    mapped = ingest_svc._map_finding("s1", "p1", f, project_repo_id="repo-1", root_path="/tmp/zs-clones/abc")
    assert mapped.project_repo_id == "repo-1"
    assert mapped.location.file == "app/db.py"


def test_stats_tallies_by_owasp_across_all_ten_codes():
    findings = [
        ingest_svc._map_finding("s1", "p1", GoFindingIn(message="x", location=GoLocationIn(file="a.py"), owasp=["A05:2025"])),
        ingest_svc._map_finding("s1", "p1", GoFindingIn(message="x", location=GoLocationIn(file="b.py"), owasp=["A05:2025", "A03:2025"])),
        ingest_svc._map_finding("s1", "p1", GoFindingIn(message="x", location=GoLocationIn(file="c.py"), owasp=["not-a-real-code"])),
    ]
    stats = ingest_svc._stats(GoStatsIn(), findings)
    assert stats.by_owasp["A05:2025"] == 2
    assert stats.by_owasp["A03:2025"] == 1
    assert stats.by_owasp["A01:2025"] == 0
    assert len(stats.by_owasp) == 10
    assert "not-a-real-code" not in stats.by_owasp


def test_ingest_writes_findings_report_and_completes_scan(client):
    async def run():
        now = datetime.now(timezone.utc)
        scan = Scan(project_id="proj-x", scan_type="local", created_at=now, updated_at=now)
        await scan.insert()
        raw = _FIXTURE.read_text()
        count = await ingest_svc.ingest(scan, _load(), raw_json=raw)

        from app.models.finding import Finding
        from app.models.report import Report

        assert count == 4
        assert await Finding.find(Finding.scan_id == str(scan.id)).count() == 4
        report = await Report.find_one(Report.scan_id == str(scan.id))
        assert report is not None
        assert report.duration_ms == 4200
        assert report.scanner_version == "v0.22.0"
        assert report.raw_json == raw  # stored in Mongo, not on disk
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "completed"
        assert reloaded.completed_at is not None
        assert reloaded.git_commit.startswith("a1b2c3d4")

        # Re-ingest replaces rather than duplicates.
        await ingest_svc.ingest(scan, _load(), raw_json=raw)
        assert await Finding.find(Finding.scan_id == str(scan.id)).count() == 4
        assert await Report.find(Report.scan_id == str(scan.id)).count() == 1

    asyncio.run(run())
