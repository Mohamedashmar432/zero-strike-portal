from datetime import datetime
from typing import Literal

from beanie import Document
from pymongo import IndexModel

# Single source of truth for the status enum — import this everywhere a Scan status
# is typed (schemas, etc.) instead of repeating the Literal, which used to drift.
ScanStatus = Literal["pending", "queued", "running", "completed", "failed"]
ScanType = Literal["local", "cloud", "cicd"]


class Scan(Document):
    project_id: str
    api_key_id: str | None = None
    scan_type: ScanType
    triggered_by: Literal["cli", "ci", "cloud", "manual"] = "cli"
    status: ScanStatus = "pending"
    scanner_version: str | None = None
    hostname: str | None = None
    git_commit: str | None = None
    branch: str | None = None
    scan_label: str | None = None
    repo_url: str | None = None
    # Set at creation for cloud scans started from a connected repo (see ProjectRepo).
    # None for local/CI scans and for cloud scans started from a hand-pasted repo_url —
    # historical scans predating this field are also None; aggregations fall back to
    # matching on repo_url for those.
    project_repo_id: str | None = None
    # Transient: only set while status="queued" (cloud scans), cleared atomically at claim time.
    repo_token: str | None = None
    # Transient, same lifecycle as repo_token. GitHub's git-over-HTTPS backend only accepts Basic
    # auth for token clones (PAT or OAuth token as the password) -- Bearer gets a silent "invalid
    # credentials" rejection -- so every GitHub-sourced token uses "basic". "bearer" is for Azure
    # DevOps OAuth (AAD) tokens; Azure DevOps PATs also use "basic".
    repo_token_auth_scheme: Literal["bearer", "basic"] = "bearer"
    ci_provider: Literal["github_actions", "gitlab_ci", "azure_pipelines"] | None = None
    created_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    # Reap-then-retry escalation (see app.core.job_queue.reap_stuck): a scan stuck
    # "running" past the crash-recovery window is requeued if retry_count+1 < max_attempts,
    # otherwise terminally failed. Defaults preserve the original always-terminal reap
    # behavior for cloud scans (0+1 is never < 1). NOTE: repo_token is cleared at the
    # first claim (see scan_queue_service._claim_next) and never restored, so raising
    # max_attempts above 1 for a token-authenticated repo would make a retried attempt
    # clone without auth — fine for public repos, not yet solved for private ones.
    retry_count: int = 0
    max_attempts: int = 1
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "scans"
        indexes = [
            IndexModel([("project_id", 1), ("started_at", -1)]),
            IndexModel([("status", 1)]),
            IndexModel([("status", 1), ("created_at", 1)]),  # oldest-queued claim query
            IndexModel([("project_id", 1), ("created_at", -1)]),
            IndexModel([("project_id", 1), ("scan_type", 1)]),
            IndexModel([("project_repo_id", 1), ("created_at", 1)]),
        ]
