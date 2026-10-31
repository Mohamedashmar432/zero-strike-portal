"""Store the scanner's dependency inventory (docs/LIVE_DEPENDENCY_ALERTS.md section 3/5).

`build_snapshot` is pure; `upsert_from_report` is the ingest hook and never raises -- a scan that produced
a valid report has completed whether or not its inventory could be stored. The snapshot is per
(project, repo scope) and replaced wholesale. A report with no `Dependencies` key (an older scanner, or a
run without --enable-sca) leaves the previous snapshot alone, while an empty list is a real, empty
inventory and replaces it."""

from datetime import datetime, timezone

import structlog

from app.core.advisory import dep_key
from app.core.timeutils import as_utc
from app.models.dependency_inventory import MAX_DEPS, MAX_MANIFESTS, DependencyInventory, InventoryDep
from app.models.project import Project
from app.models.scan import Scan
from app.schemas.report import GoReportIn
from app.services import pdf_report_service, project_repo_service
from app.services import project_stats_service as stats_svc

logger = structlog.get_logger(__name__)


def _manifest(path: str | None, root_path: str | None) -> str | None:
    from app.services.report_ingestion_service import normalize_finding_path

    if not path:
        return None
    return normalize_finding_path(path, root_path).replace("\\", "/") or None


def build_snapshot(
    scan: Scan, report: GoReportIn, scope_key: str, repo_label: str, *, project_repo_id: str | None = None
) -> DependencyInventory:
    """Merge the report's entries by (ecosystem, package, version): the same package pinned in two
    manifests is one dependency with two manifests. Capped at MAX_DEPS, flagged `truncated`."""
    merged: dict[tuple[str, str, str], InventoryDep] = {}
    truncated = False
    for ref in report.dependencies or []:
        ecosystem, package, version = (ref.ecosystem or "").strip(), (ref.package or "").strip(), (ref.version or "").strip()
        if not (ecosystem and package and version):
            continue
        key = (ecosystem, package, version)
        dep = merged.get(key)
        if dep is None:
            if len(merged) >= MAX_DEPS:
                truncated = True
                continue
            dep = merged[key] = InventoryDep(
                k=dep_key(ecosystem, package), ecosystem=ecosystem, package=package, version=version, direct=ref.direct
            )
        manifest = _manifest(ref.manifest, report.root_path)
        if manifest and manifest not in dep.manifests and len(dep.manifests) < MAX_MANIFESTS:
            dep.manifests.append(manifest)
        if ref.direct:
            dep.direct = True
    now = datetime.now(timezone.utc)
    return DependencyInventory(
        project_id=scan.project_id,
        repo_scope_key=scope_key,
        project_repo_id=project_repo_id,
        repo_label=repo_label,
        scan_id=str(scan.id),
        scan_type=scan.scan_type,
        git_commit=report.git_commit or scan.git_commit,
        branch=report.branch or scan.branch,
        scanner_version=report.scanner_version or scan.scanner_version,
        scanned_at=now,  # ingest time: the scan's own completed_at is stamped after this hook
        dep_count=len(merged),
        truncated=truncated,
        deps=list(merged.values()),
        updated_at=now,
    )


async def upsert_from_report(scan: Scan, report: GoReportIn) -> bool:
    """Replace this scope's snapshot from the report. Returns whether one was written. Never raises."""
    if report.dependencies is None:
        return False
    try:
        repos = await project_repo_service.list_repos(scan.project_id)
        scope_key = stats_svc.repo_key_resolver(repos)(scan)
        repo = next((r for r in repos if str(r.id) == scope_key), None)
        if repo is not None:
            label = repo.label or repo.repo_full_name
            project_repo_id: str | None = scope_key
        else:
            name, _ = pdf_report_service.repo_identity(scan.repo_url)
            label = name if name != "-" else "CI/CD pipeline"
            project_repo_id = None
        snapshot = build_snapshot(scan, report, scope_key, label, project_repo_id=project_repo_id)
        collection = DependencyInventory.get_pymongo_collection()
        doc = snapshot.model_dump(exclude={"id", "revision_id"})
        await collection.replace_one(
            {"project_id": scan.project_id, "repo_scope_key": scope_key}, doc, upsert=True
        )
        return True
    except Exception:
        logger.warning("dependency inventory update failed", scan_id=str(scan.id), exc_info=True)
        return False


async def coverage() -> dict:
    """How much of the portal has an inventory: feeds the Control Panel's "N of M projects" line."""
    collection = DependencyInventory.get_pymongo_collection()
    active = {
        str(d["_id"])
        for d in await Project.get_pymongo_collection().find({"is_archived": False}, {"_id": 1}).to_list(None)
    }
    inventories = await collection.find({}, {"project_id": 1, "scan_type": 1, "scanned_at": 1}).to_list(None)
    with_inventory = {i["project_id"] for i in inventories} & active
    oldest = min((i["scanned_at"] for i in inventories if i.get("scanned_at")), default=None)
    return {
        "projects_active": len(active),
        "projects_with_inventory": len(with_inventory),
        "inventories_cloud": sum(i.get("scan_type") == "cloud" for i in inventories),
        "inventories_cicd": sum(i.get("scan_type") == "cicd" for i in inventories),
        "oldest_inventory_at": as_utc(oldest),
    }
