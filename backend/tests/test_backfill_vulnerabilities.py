import asyncio
from datetime import datetime, timedelta, timezone

from app.models.finding import Finding, LocationEmbedded
from app.models.project import Project
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.vulnerability import Vulnerability
from app.scripts.backfill_vulnerabilities import backfill


def _now():
    return datetime.now(timezone.utc)


async def _seed_project_with_scans() -> tuple[str, str]:
    """A repo scanned twice: an older scan with two findings, a newer one with one."""
    now = _now()
    project = await Project(name="Backfill", owner_id="o1", created_at=now, updated_at=now).insert()
    pid = str(project.id)
    repo = await ProjectRepo(
        project_id=pid,
        provider="github",
        organization="acme",
        repo_full_name="acme/repo-a",
        clone_url="https://github.com/acme/repo-a.git",
        selected_branch="main",
        created_by="o1",
        created_at=now,
        updated_at=now,
    ).insert()

    async def _scan(fingerprints: list[str], created_at: datetime) -> str:
        scan = await Scan(
            project_id=pid,
            scan_type="cloud",
            status="completed",
            project_repo_id=str(repo.id),
            created_at=created_at,
            updated_at=created_at,
        ).insert()
        for fp in fingerprints:
            await Finding(
                scan_id=str(scan.id),
                project_id=pid,
                project_repo_id=str(repo.id),
                fingerprint=fp,
                severity="high",
                message="msg",
                location=LocationEmbedded(file="app.py"),
            ).insert()
        return str(scan.id)

    await _scan(["fp-old-1", "fp-old-2"], now - timedelta(days=2))
    newest = await _scan(["fp-new-1"], now)
    return pid, newest


def test_backfill_seeds_from_the_latest_scan_only(client):
    async def run():
        pid, newest = await _seed_project_with_scans()

        totals = await backfill()

        assert totals["scans"] == 1, "only the latest completed scan per repo scope is replayed"
        vulns = await Vulnerability.find(Vulnerability.project_id == pid).to_list()
        assert {v.fingerprint for v in vulns} == {"fp-new-1"}
        assert vulns[0].current_scan_id == newest
        assert vulns[0].status == "open"

    asyncio.run(run())


def test_backfill_never_marks_anything_fixed(client):
    """Seeding from one scan cannot prove an issue disappeared — it must not claim it did."""

    async def run():
        pid, _ = await _seed_project_with_scans()

        await backfill()

        vulns = await Vulnerability.find(Vulnerability.project_id == pid).to_list()
        assert all(v.status != "resolved" for v in vulns)
        assert all(v.resolution_reason is None for v in vulns)
        assert all(v.last_regression_state != "fixed" for v in vulns)

    asyncio.run(run())


def test_backfill_is_idempotent(client):
    async def run():
        pid, _ = await _seed_project_with_scans()

        first = await backfill()
        before = {v.fingerprint: v.first_seen_at for v in await Vulnerability.find_all().to_list()}

        second = await backfill()

        assert first["vulnerabilities_created"] == 1
        assert second["vulnerabilities_created"] == 0, "a second run creates nothing"
        after = await Vulnerability.find(Vulnerability.project_id == pid).to_list()
        assert len(after) == 1, "no duplicates"
        for v in after:
            assert v.first_seen_at == before[v.fingerprint], "first_seen_at is never rewritten"

    asyncio.run(run())


def test_backfill_counts_unfingerprinted_observations_as_skipped(client):
    async def run():
        now = _now()
        project = await Project(name="NoFp", owner_id="o1", created_at=now, updated_at=now).insert()
        scan = await Scan(
            project_id=str(project.id),
            scan_type="cloud",
            status="completed",
            created_at=now,
            updated_at=now,
        ).insert()
        await Finding(
            scan_id=str(scan.id),
            project_id=str(project.id),
            fingerprint=None,
            severity="low",
            message="msg",
            location=LocationEmbedded(file="app.py"),
        ).insert()

        totals = await backfill()

        assert totals["skipped_no_fingerprint"] == 1
        assert await Vulnerability.find_all().count() == 0

    asyncio.run(run())
