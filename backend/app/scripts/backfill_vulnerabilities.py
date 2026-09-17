"""Seed canonical Vulnerability rows for projects that were scanned before they existed.

Run with:  python -m app.scripts.backfill_vulnerabilities

Seeds from each repo scope's LATEST completed scan only, with fixed-detection disabled. That
restriction is the whole point rather than a shortcut: a single scan is evidence of what is
present, never of what disappeared, so replaying one can prove nothing was fixed. Claiming
otherwise would invent remediation history that no scan ever observed. `first_seen_at` is
therefore honestly the date of that scan, not a guess at when the issue actually appeared.

Idempotent and rerunnable — reconcile_scan upserts on (project_id, repo_scope_key, fingerprint)
and leaves first_seen_at alone once set, so a second run is a no-op. Safe to re-run after a
partial failure.
"""

import asyncio

import structlog

from app.models.finding import Finding
from app.models.project import Project
from app.models.scan import Scan
from app.db.mongo import close_mongo_connection, connect_to_mongo
from app.services import project_stats_service, vulnerability_service

logger = structlog.get_logger(__name__)


async def backfill() -> dict[str, int]:
    """Returns the run's totals. Exposed separately from main() so tests can call it."""
    totals = {
        "projects": 0,
        "scans": 0,
        "vulnerabilities_created": 0,
        "observations_reused": 0,
        "skipped_no_fingerprint": 0,
    }

    projects = await Project.find_all().to_list()
    totals["projects"] = len(projects)
    if not projects:
        return totals

    coverage = await project_stats_service.current_posture_scan_ids([str(p.id) for p in projects])

    for project_id, scan_ids in coverage.scan_ids_by_project.items():
        for scan_id in scan_ids:
            scan = await Scan.get(scan_id)
            if scan is None:
                continue
            findings = await Finding.find(Finding.scan_id == scan_id).to_list()
            result = await vulnerability_service.reconcile_scan(scan, findings, detect_fixed=False)
            totals["scans"] += 1
            totals["vulnerabilities_created"] += result.new
            totals["observations_reused"] += result.unchanged + result.reopened
            totals["skipped_no_fingerprint"] += result.untracked
            logger.info(
                "backfilled scan",
                project_id=project_id,
                scan_id=scan_id,
                created=result.new,
                reused=result.unchanged + result.reopened,
                no_fingerprint=result.untracked,
            )

    return totals


async def _main() -> None:
    await connect_to_mongo()
    try:
        totals = await backfill()
        logger.info("backfill complete", **totals)
        print(  # noqa: T201 -- operator-facing summary, this is a CLI
            "backfill complete: "
            f"{totals['projects']} projects, {totals['scans']} scans, "
            f"{totals['vulnerabilities_created']} vulnerabilities created, "
            f"{totals['observations_reused']} already present, "
            f"{totals['skipped_no_fingerprint']} observations skipped (no fingerprint)"
        )
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(_main())
