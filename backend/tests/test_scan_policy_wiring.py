"""Policy actually reaching the machinery: scanner argv flags, and the auto-audit trigger.

A settings screen that saves a value nothing reads is the exact failure mode this branch
exists to remove, so these assert the effect rather than the stored value.
"""

import asyncio
from datetime import datetime, timezone

import app.services.cloud_scan_service as css
from app.models.compliance_audit import ComplianceAudit
from app.models.project import Project
from app.models.scan import Scan
from app.services import compliance_queue_service, workspace_settings_service as wss
from tests.test_cloud_scan_service import _make_cloud_scan, _patch_subprocess


def _capture_scanner_argv(monkeypatch, tmp_path) -> list[list[str]]:
    """Same fake subprocess as the cloud-scan tests, but recording every argv it sees."""
    calls: list[list[str]] = []
    _patch_subprocess(monkeypatch, tmp_path)
    real_run = css.subprocess.run

    def recording_run(cmd, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(css.subprocess, "run", recording_run)
    return calls


def _scanner_argv(calls: list[list[str]]) -> list[str]:
    return next(cmd for cmd in calls if cmd[0] != "git")


def test_default_workspace_settings_produce_the_previously_hardcoded_flags(
    client, monkeypatch, tmp_path
):
    calls = _capture_scanner_argv(monkeypatch, tmp_path)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))

    asyncio.run(run())
    argv = _scanner_argv(calls)
    # Regression guard: an existing workspace must behave exactly as it did before these
    # flags became configurable.
    assert "--enable-secrets" in argv
    assert "--enable-sca" in argv
    assert "--enable-framework-checks" in argv


def test_disabling_an_analyser_workspace_wide_removes_its_flag(client, monkeypatch, tmp_path):
    calls = _capture_scanner_argv(monkeypatch, tmp_path)

    async def run():
        await wss.update_workspace_settings(scan_enable_sca=False)
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))

    asyncio.run(run())
    argv = _scanner_argv(calls)
    assert "--enable-sca" not in argv
    assert "--enable-secrets" in argv  # the others are untouched


def test_a_project_override_beats_the_workspace_default(client, monkeypatch, tmp_path):
    calls = _capture_scanner_argv(monkeypatch, tmp_path)

    async def run():
        await wss.update_workspace_settings(scan_enable_secrets=False)
        now = datetime.now(timezone.utc)
        project = Project(
            name="Override Scan",
            owner_id="owner",
            scan_enable_secrets=True,  # this project wants secrets on regardless
            created_at=now,
            updated_at=now,
        )
        await project.insert()

        scan = _make_cloud_scan()
        scan.project_id = str(project.id)
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))

    asyncio.run(run())
    assert "--enable-secrets" in _scanner_argv(calls)


# --- auto-audit --------------------------------------------------------------


async def _project_and_completed_scan(auto_audit: bool | None) -> tuple[Project, Scan]:
    now = datetime.now(timezone.utc)
    project = Project(
        name="Auto Audit",
        owner_id="owner",
        compliance_auto_audit_on_scan=auto_audit,
        created_at=now,
        updated_at=now,
    )
    await project.insert()
    scan = Scan(
        project_id=str(project.id),
        scan_type="cloud",
        triggered_by="cloud",
        status="completed",
        created_at=now,
        updated_at=now,
    )
    await scan.insert()
    return project, scan


def test_auto_audit_does_not_fire_when_the_policy_is_off(client):
    async def run():
        _, scan = await _project_and_completed_scan(auto_audit=False)
        assert await compliance_queue_service.enqueue_auto_audit(scan) is None
        assert await ComplianceAudit.find_all().count() == 0

    asyncio.run(run())


def test_auto_audit_queues_a_deterministic_audit_when_enabled(client):
    async def run():
        _, scan = await _project_and_completed_scan(auto_audit=True)
        audit = await compliance_queue_service.enqueue_auto_audit(scan)
        assert audit is not None
        # Never with_ai_narrative: this fires unattended, so it must not be able to spend
        # on LLM calls.
        assert audit.depth == "deterministic"
        assert audit.scope == "latest"
        assert audit.created_by is None
        assert set(audit.frameworks) == {"soc2", "iso27001"}

    asyncio.run(run())


def test_auto_audit_does_not_stack_when_one_is_already_in_flight(client):
    async def run():
        _, scan = await _project_and_completed_scan(auto_audit=True)
        first = await compliance_queue_service.enqueue_auto_audit(scan)
        second = await compliance_queue_service.enqueue_auto_audit(scan)
        # A project whose repos all finish at once must not queue one audit per repo for the
        # same evidence set.
        assert str(first.id) == str(second.id)
        assert await ComplianceAudit.find_all().count() == 1

    asyncio.run(run())


def test_auto_audit_is_refused_when_there_is_no_scan_evidence(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(
            name="No Evidence",
            owner_id="owner",
            compliance_auto_audit_on_scan=True,
            created_at=now,
            updated_at=now,
        )
        await project.insert()
        # A scan that is not completed contributes no evidence, so an audit here would report
        # every code-assessable control as passing off nothing at all.
        scan = Scan(
            project_id=str(project.id),
            scan_type="cloud",
            triggered_by="cloud",
            status="failed",
            created_at=now,
            updated_at=now,
        )
        await scan.insert()
        assert await compliance_queue_service.enqueue_auto_audit(scan) is None

    asyncio.run(run())


# --- retention ---------------------------------------------------------------


def test_retention_reaper_skips_projects_with_no_retention_set(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(name="Keep Forever", owner_id="o", created_at=now, updated_at=now)
        await project.insert()
        audit = ComplianceAudit(
            project_id=str(project.id),
            frameworks=["soc2"],
            scope="latest",
            depth="deterministic",
            status="completed",
            created_at=now.replace(year=now.year - 5),
            updated_at=now,
        )
        await audit.insert()

        await compliance_queue_service.reap_expired_audits()
        # None means keep forever; reaping it would silently destroy evidence.
        assert await ComplianceAudit.find_all().count() == 1

    asyncio.run(run())


def test_retention_reaper_deletes_audits_past_the_window(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(
            name="Short Retention",
            owner_id="o",
            compliance_evidence_retention_days=30,
            created_at=now,
            updated_at=now,
        )
        await project.insert()
        old = ComplianceAudit(
            project_id=str(project.id),
            frameworks=["soc2"],
            scope="latest",
            depth="deterministic",
            status="completed",
            created_at=now.replace(year=now.year - 1),
            updated_at=now,
        )
        await old.insert()
        recent = ComplianceAudit(
            project_id=str(project.id),
            frameworks=["soc2"],
            scope="latest",
            depth="deterministic",
            status="completed",
            created_at=now,
            updated_at=now,
        )
        await recent.insert()

        await compliance_queue_service.reap_expired_audits()
        remaining = await ComplianceAudit.find_all().to_list()
        assert [str(a.id) for a in remaining] == [str(recent.id)]

    asyncio.run(run())
