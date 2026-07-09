import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.scan import Scan
from app.schemas.report import GoFindingIn, GoLocationIn, GoReportIn
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


def test_ingest_writes_findings_report_and_completes_scan(client):
    async def run():
        now = datetime.now(timezone.utc)
        scan = Scan(project_id="proj-x", scan_type="local", created_at=now, updated_at=now)
        await scan.insert()
        count = await ingest_svc.ingest(scan, _load(), json_path="/data/artifacts/x/y/report.json")

        from app.models.finding import Finding
        from app.models.report import Report

        assert count == 4
        assert await Finding.find(Finding.scan_id == str(scan.id)).count() == 4
        report = await Report.find_one(Report.scan_id == str(scan.id))
        assert report is not None
        assert report.duration_ms == 4200
        assert report.scanner_version == "v0.22.0"
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "completed"
        assert reloaded.completed_at is not None
        assert reloaded.git_commit.startswith("a1b2c3d4")

        # Re-ingest replaces rather than duplicates.
        await ingest_svc.ingest(scan, _load(), json_path="/data/artifacts/x/y/report.json")
        assert await Finding.find(Finding.scan_id == str(scan.id)).count() == 4
        assert await Report.find(Report.scan_id == str(scan.id)).count() == 1

    asyncio.run(run())
