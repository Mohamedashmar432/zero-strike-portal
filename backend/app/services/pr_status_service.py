"""Auto-fix PR state: read back from the provider whether a PR the portal opened was merged.

docs/CLONE_LIFECYCLE_AND_SCAN_REUSE.md, phase D. The apply step opens a PR and records it on every
AIFixProposal it shipped (a batch shares one pr_url), and until now the portal never looked again.
`refresh_repo_prs` reads each still-open PR of one connected repo from the provider REST API with
the repo's own read credential and stores pr_state / pr_merged_at / pr_merge_commit on those
proposals. It runs on Repo Sync and on demand; it never fails either: a provider error is stored on
the proposal (sanitized) and audited, and the caller carries on.

What this deliberately does not do: mark anything fixed. A merge is a claim about the branch, not
proof the finding is gone -- only the next scan's reconcile_scan can say that. The merged state feeds
the "N auto-fix PRs merged since last sync" reminder and the "Fixed via auto-fix PR #N" attribution.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import structlog
from beanie.operators import In
from bson import ObjectId

from app.models.ai_fix_proposal import AIFixProposal
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.services import audit_service, git_workspace, project_repo_service
from app.services import project_stats_service as stats_svc
from app.services.repo_write import RepoWriteError
from app.services.repo_write import azure_devops as ado_write
from app.services.repo_write import github as gh_write

logger = structlog.get_logger(__name__)

# A PR read within this window is not re-read: the Repos tab refreshes on load, and a page someone
# keeps reloading must not turn into one provider call per PR per reload.
_RECHECK_AFTER = timedelta(seconds=60)


@dataclass
class PrRefreshResult:
    checked: int = 0
    open: int = 0
    merged: int = 0
    closed: int = 0
    newly_merged: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoPrCounts:
    open_prs: int = 0
    merged_since_sync: int = 0


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


async def _repo_scan_ids(project_id: str, repo: ProjectRepo, repos: list[ProjectRepo] | None = None) -> set[str]:
    """Every scan of this repo's scope, resolved the way reconcile_scan does (project_repo_id, or the
    clone URL for scans that predate it)."""
    resolve = stats_svc.repo_key_resolver(repos if repos is not None else await project_repo_service.list_repos(project_id))
    rows = await Scan.get_pymongo_collection().find(
        {"project_id": project_id}, {"project_repo_id": 1, "repo_url": 1}
    ).to_list(length=None)
    key = str(repo.id)
    return {
        str(r["_id"])
        for r in rows
        if resolve(SimpleNamespace(project_repo_id=r.get("project_repo_id"), repo_url=r.get("repo_url"))) == key
    }


async def _pr_proposals(project_id: str, scan_ids: set[str]) -> list[AIFixProposal]:
    if not scan_ids:
        return []
    return await AIFixProposal.find(
        AIFixProposal.project_id == project_id,
        In(AIFixProposal.scan_id, list(scan_ids)),
        AIFixProposal.pr_number != None,  # noqa: E711 -- Mongo null match
    ).to_list()


async def _read_state(repo: ProjectRepo, pr_number: int, token: str | None) -> dict:
    if repo.provider == "github":
        owner, _, name = repo.repo_full_name.partition("/")
        return await gh_write.get_pull_request_state(token, owner, name, pr_number)
    if not token:
        raise RepoWriteError("No read credential is stored for this repository.")
    project = repo.ado_project or repo.repo_full_name.split("/")[0]
    return await ado_write.get_pull_request_state(token, "basic", repo.organization, project, pr_number)


async def refresh_repo_prs(
    project_id: str, repo: ProjectRepo, *, actor_user_id: str | None, force: bool = False
) -> PrRefreshResult:
    """Re-read every not-yet-final auto-fix PR of one repo. Never raises for a provider failure."""
    result = PrRefreshResult()
    proposals = await _pr_proposals(project_id, await _repo_scan_ids(project_id, repo))
    now = datetime.now(timezone.utc)
    # One provider call per PR, not per proposal: a batch PR is shared by all its proposals.
    by_pr: dict[int, list[AIFixProposal]] = {}
    for p in proposals:
        if p.pr_state in ("merged", "closed"):
            continue  # final; a closed PR reopened later is rare enough to leave to the next PR
        checked = _as_utc(p.pr_checked_at)
        if not force and checked and now - checked < _RECHECK_AFTER:
            continue
        by_pr.setdefault(int(p.pr_number), []).append(p)
    if not by_pr:
        return result

    token = project_repo_service.decrypt_pat(repo)
    for pr_number, group in by_pr.items():
        result.checked += 1
        try:
            state = await _read_state(repo, pr_number, token)
        except Exception as exc:  # noqa: BLE001 -- a provider failure must never fail the caller
            message = git_workspace.sanitize(
                str(exc) if isinstance(exc, RepoWriteError) else f"PR status check failed: {type(exc).__name__}",
                token,
            )[:300]
            result.errors.append(f"PR #{pr_number}: {message}")
            for p in group:
                p.pr_check_error, p.pr_checked_at = message, now
                await p.save()
            await audit_service.record(
                "Auto-Fix PR Status Check Failed",
                actor_user_id=actor_user_id,
                project_id=project_id,
                target_type="project_repo",
                target_id=str(repo.id),
                metadata={"pr_number": pr_number, "error": message},
            )
            continue

        new_state = state["state"]
        setattr(result, new_state, getattr(result, new_state) + 1)
        was = group[0].pr_state
        for p in group:
            p.pr_state = new_state
            p.pr_merged_at = _parse_time(state.get("merged_at")) if new_state == "merged" else None
            p.pr_merge_commit = state.get("merge_commit") if new_state == "merged" else None
            p.pr_checked_at, p.pr_check_error = now, None
            p.updated_at = now
            await p.save()
        if new_state != was and new_state in ("merged", "closed"):
            if new_state == "merged":
                result.newly_merged += 1
            await audit_service.record(
                "Auto-Fix PR Merged" if new_state == "merged" else "Auto-Fix PR Closed",
                actor_user_id=actor_user_id,
                project_id=project_id,
                target_type="project_repo",
                target_id=str(repo.id),
                metadata={
                    "pr_number": pr_number,
                    "pr_url": group[0].pr_url,
                    "merge_commit": group[0].pr_merge_commit,
                    "proposals": len(group),
                },
            )
    return result


async def repo_pr_counts(
    project_id: str, repos: list[ProjectRepo], last_synced: dict[str, datetime | None]
) -> dict[str, RepoPrCounts]:
    """Per repo: auto-fix PRs still open, and PRs merged after the repo's last completed sync (the
    Repos-tab reminder). Distinct PRs, not proposals. Reads stored state only -- no provider call."""
    if not repos:
        return {}
    proposals = await AIFixProposal.find(
        AIFixProposal.project_id == project_id,
        AIFixProposal.pr_number != None,  # noqa: E711
    ).to_list()
    if not proposals:
        return {}
    resolve = stats_svc.repo_key_resolver(repos)
    scan_rows = await Scan.get_pymongo_collection().find(
        {"_id": {"$in": [_oid(p.scan_id) for p in proposals if _oid(p.scan_id) is not None]}},
        {"project_repo_id": 1, "repo_url": 1},
    ).to_list(length=None)
    repo_of_scan = {
        str(r["_id"]): resolve(SimpleNamespace(project_repo_id=r.get("project_repo_id"), repo_url=r.get("repo_url")))
        for r in scan_rows
    }
    open_prs: dict[str, set] = {}
    merged: dict[str, set] = {}
    for p in proposals:
        key = repo_of_scan.get(p.scan_id)
        if key is None:
            continue
        pr_key = p.pr_url or p.pr_number
        if p.pr_state == "merged":
            since = _as_utc(last_synced.get(key))
            merged_at = _as_utc(p.pr_merged_at)
            if since is None or (merged_at is not None and merged_at > since):
                merged.setdefault(key, set()).add(pr_key)
        elif p.pr_state in (None, "open"):
            open_prs.setdefault(key, set()).add(pr_key)
    return {
        str(r.id): RepoPrCounts(
            open_prs=len(open_prs.get(str(r.id), ())), merged_since_sync=len(merged.get(str(r.id), ()))
        )
        for r in repos
    }


def _oid(value: str):
    try:
        return ObjectId(value)
    except Exception:  # noqa: BLE001
        return None


async def merged_pr_for_findings(finding_ids: list[str]) -> AIFixProposal | None:
    """The most recently merged auto-fix PR among these findings' proposals, or None. The read-time
    join behind "Fixed via auto-fix PR #N" -- nothing is stored on the Vulnerability."""
    if not finding_ids:
        return None
    rows = await AIFixProposal.find(
        In(AIFixProposal.finding_id, finding_ids), AIFixProposal.pr_state == "merged"
    ).to_list()
    return max(rows, key=lambda p: _as_utc(p.pr_merged_at) or datetime.min.replace(tzinfo=timezone.utc), default=None)
