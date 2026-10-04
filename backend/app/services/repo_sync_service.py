"""Repo Sync (docs/REPO_SYNC.md): bring one connected repo up to its remote branch head.

`git ls-remote` for the repo's selected branch; if the latest completed scan already covers that
commit there is nothing to do, otherwise a normal cloud scan is enqueued through the existing queue.
The fixed / still-open / new diff is NOT computed here -- it happens in vulnerability_service.
reconcile_scan when that scan ingests, so a failed scan can never mark anything fixed.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core import rate_limit
from app.core.config import settings
from app.models.project import Project
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User
from app.services import audit_service, git_workspace, project_repo_service, scan_service
from app.services import project_stats_service as stats_svc

_LEASE_SECONDS = 90


@dataclass(frozen=True)
class SyncResult:
    outcome: str  # up_to_date | scan_queued | already_syncing
    scan_id: str | None
    remote_head_sha: str | None
    repo: ProjectRepo


async def _acquire_lease(repo: ProjectRepo) -> bool:
    """Atomically take the repo's sync lease; False if another sync still holds it."""
    now = datetime.now(timezone.utc)
    res = await ProjectRepo.get_pymongo_collection().update_one(
        {"_id": repo.id, "$or": [{"sync_lease_until": None}, {"sync_lease_until": {"$lt": now}}]},
        {"$set": {"sync_lease_until": now + timedelta(seconds=_LEASE_SECONDS)}},
    )
    return res.matched_count == 1


async def _release_lease(repo: ProjectRepo) -> None:
    await ProjectRepo.get_pymongo_collection().update_one({"_id": repo.id}, {"$set": {"sync_lease_until": None}})


async def latest_completed_scan(repo: ProjectRepo) -> Scan | None:
    """Newest completed scan of this repo's scope, resolved the same way reconcile_scan does."""
    resolve = stats_svc.repo_key_resolver(await project_repo_service.list_repos(repo.project_id))
    completed = await Scan.find(Scan.project_id == repo.project_id, Scan.status == "completed").to_list()
    scoped = [s for s in completed if resolve(s) == str(repo.id)]
    return max(scoped, key=lambda s: s.created_at, default=None)


@dataclass(frozen=True)
class SyncOverview:
    scanned_commit: str | None
    scanned_branch: str | None
    last_synced_at: datetime | None
    active_scan_id: str | None
    sync_state: str  # syncing | up_to_date | behind | error | never | unknown


async def sync_overviews(project_id: str, repos: list[ProjectRepo]) -> dict[str, SyncOverview]:
    """Per-repo sync state for a project, from one lightweight scan query (no findings, no tokens).

    never      -- no completed scan of the repo yet
    unknown    -- scanned, but the remote head or the scanned commit is not known to compare
    behind     -- remote head differs from the scanned commit/branch
    up_to_date -- remote head equals the scanned commit on the selected branch
    error/syncing take precedence: the last head check failed / a scan is queued or running.
    """
    resolve = stats_svc.repo_key_resolver(repos)
    rows = (
        await Scan.get_pymongo_collection()
        .find(
            {"project_id": project_id, "status": {"$in": ["completed", "queued", "running"]}},
            {"status": 1, "git_commit": 1, "branch": 1, "completed_at": 1, "created_at": 1,
             "project_repo_id": 1, "repo_url": 1},
        )
        .sort("created_at", -1)
        .to_list(length=None)
    )
    latest: dict[str, dict] = {}
    active: dict[str, str] = {}
    for row in rows:  # newest first
        key = resolve(SimpleNamespace(project_repo_id=row.get("project_repo_id"), repo_url=row.get("repo_url")))
        if row["status"] == "completed":
            latest.setdefault(key, row)
        else:
            active.setdefault(key, str(row["_id"]))

    out: dict[str, SyncOverview] = {}
    for repo in repos:
        key = str(repo.id)
        last = latest.get(key)
        commit, branch = (last.get("git_commit"), last.get("branch")) if last else (None, None)
        if key in active:
            state = "syncing"
        elif repo.last_sync_error:
            state = "error"
        elif last is None:
            state = "never"
        elif not repo.remote_head_sha or not commit:
            state = "unknown"
        else:
            state = "up_to_date" if commit == repo.remote_head_sha and branch == repo.selected_branch else "behind"
        stamps = [t for t in (last.get("completed_at") if last else None,
                              None if repo.last_sync_error else repo.remote_head_checked_at) if t]
        out[key] = SyncOverview(
            scanned_commit=commit,
            scanned_branch=branch,
            last_synced_at=max(stamps, key=lambda t: t.replace(tzinfo=None)) if stamps else None,
            active_scan_id=active.get(key),
            sync_state=state,
        )
    return out


async def sync_repo(project: Project, repo: ProjectRepo, user: User, *, force: bool = False) -> SyncResult:
    project_id, repo_id = str(project.id), str(repo.id)
    rate_limit.enforce(
        f"repo-sync:{user.id}",
        settings.rate_limit_repo_sync_max_attempts,
        settings.rate_limit_repo_sync_window_seconds,
    )
    if not await _acquire_lease(repo):
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already in progress for this repo")
    try:
        active = await Scan.find(
            Scan.project_id == project_id,
            Scan.project_repo_id == repo_id,
            {"status": {"$in": ["queued", "running"]}},
        ).first_or_none()
        if active:
            return SyncResult("already_syncing", str(active.id), repo.remote_head_sha, repo)

        await audit_service.record(
            "Repo Sync Requested",
            actor_user_id=str(user.id),
            project_id=project_id,
            target_type="project_repo",
            target_id=repo_id,
            metadata={"branch": repo.selected_branch, "force": force},
        )
        token = project_repo_service.decrypt_pat(repo)
        now = datetime.now(timezone.utc)
        try:
            head = await git_workspace.remote_head(repo.clone_url, repo.selected_branch, token, "basic")
        except git_workspace.GitWorkspaceError as exc:
            message = git_workspace.sanitize(str(exc), token)
            await ProjectRepo.get_pymongo_collection().update_one(
                {"_id": repo.id},
                {"$set": {"last_sync_error": message, "remote_head_checked_at": now}},
            )
            await audit_service.record(
                "Repo Sync Failed",
                actor_user_id=str(user.id),
                project_id=project_id,
                target_type="project_repo",
                target_id=repo_id,
                metadata={"error": message},
            )
            raise HTTPException(status.HTTP_409_CONFLICT, f"Could not check the remote: {message}")

        await ProjectRepo.get_pymongo_collection().update_one(
            {"_id": repo.id},
            {"$set": {"remote_head_sha": head, "remote_head_checked_at": now, "last_sync_error": None}},
        )
        repo.remote_head_sha, repo.remote_head_checked_at, repo.last_sync_error = head, now, None

        # A last scan with no recorded commit (failed, or legacy) can never prove "up to date".
        last = await latest_completed_scan(repo)
        if not force and last and last.git_commit == head and last.branch == repo.selected_branch:
            return SyncResult("up_to_date", None, head, repo)

        scan = await scan_service.enqueue_repo_scan(
            project,
            user,
            repo_url=repo.clone_url,
            branch=repo.selected_branch,
            repo_token=token,
            repo_token_auth_scheme="basic",
            project_repo_id=repo_id,
            triggered_by="sync",
        )
        return SyncResult("scan_queued", str(scan.id), head, repo)
    finally:
        await _release_lease(repo)
