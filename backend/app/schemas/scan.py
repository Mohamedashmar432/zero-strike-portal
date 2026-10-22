import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.git_ref import validate_branch_name
from app.core.repo_url import sanitize_repo_url
from app.models.scan import CiProvider, ScanStage, ScanStatus
from app.schemas.dashboard import SeverityCounts


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class ScanCreateRequest(BaseModel):
    scan_type: Literal["cloud", "cicd"]
    scan_label: str | None = None
    repo_url: str | None = None
    branch: str | None = None
    ci_provider: CiProvider | None = None
    # Transient: used to clone a private repo for a cloud scan, never persisted on the Scan.
    repo_token: str | None = None
    # Alternative to repo_token: resolve the clone credential from a connected GitHub/Azure DevOps
    # account (see connection_service.get_decrypted_token) instead of a hand-pasted token.
    connection_id: str | None = None
    # Alternative to repo_url/repo_token/connection_id: resolve everything (repo_url, branch, and
    # credential) from a repo already connected to the project (see ProjectRepo) — set by the
    # "Use connected repo" picker.
    project_repo_id: str | None = None
    # With project_repo_id: scan even when the remote head is already covered by a completed scan
    # ("Rescan anyway"). Ignored for ad-hoc repo_url scans, which have no head check.
    force: bool = False

    @field_validator("branch")
    @classmethod
    def _validate_branch(cls, v: str | None) -> str | None:
        return validate_branch_name(v) if v else v

    @model_validator(mode="after")
    def _validate_type_config(self):
        if self.scan_type == "cloud" and not (self.repo_url or self.project_repo_id):
            raise ValueError("repo_url or project_repo_id is required for cloud scans")
        if self.scan_type == "cicd" and not self.ci_provider:
            raise ValueError("ci_provider is required for CI/CD scans")
        if self.repo_token and self.connection_id:
            raise ValueError("Provide either repo_token or connection_id, not both")
        return self


class ScanResponse(BaseModel):
    id: str
    project_id: str
    scan_type: Literal["cloud", "cicd"]
    triggered_by: Literal["cli", "ci", "cloud", "manual", "sync"]
    status: ScanStatus
    api_key_id: str | None
    scanner_version: str | None
    hostname: str | None
    git_commit: str | None
    branch: str | None
    scan_label: str | None
    repo_url: str | None
    project_repo_id: str | None
    ci_provider: CiProvider | None
    ci_build_id: str | None = None
    ci_build_number: str | None = None
    ci_build_url: str | None = None
    created_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    # Which phase of the cloud-scan pipeline this is in (running) or stopped in (failed).
    # Diagnostics only -- see Scan.stage; the UI must key behaviour off `status`, never this.
    stage: ScanStage | None = None
    stage_started_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Denormalized (read-side join) from the latest scan-level AIAnalysisJob, so any list/detail
    # view can show an "AI analyzing · N%" tag without a separate per-row request. None = never
    # requested. progress_* are batch counts (completed/total) while active, 0/0 otherwise.
    ai_analysis_status: Literal["queued", "in_progress", "completed", "failed"] | None = None
    ai_analysis_started_at: datetime | None = None
    ai_analysis_progress_completed: int = 0
    ai_analysis_progress_total: int = 0
    # Denormalized (read-side join) per-scan severity breakdown, batched for the whole list page
    # (see project_stats_service.get_severity_by_scan_ids) -- avoids a per-row report fetch.
    findings_by_severity: SeverityCounts | None = None
    rule_pack_version: int | None = None
    suppressed_count: int = 0
    custom_rules_ran: bool = False


class ScanCreateResponse(ScanResponse):
    """POST /projects/{id}/scans. The scan fields are always populated so existing callers keep
    working: for `scan_queued` it is the new scan; for `up_to_date` the completed scan that already
    covers the remote head; for `already_syncing` the queued/running scan. Only `outcome` says
    which, and only `scan_queued` creates anything."""

    outcome: Literal["scan_queued", "up_to_date", "already_syncing"] = "scan_queued"
    remote_head_sha: str | None = None


# --- Scanner-facing (api-key-authed) contract, matches the Go scanner's internal/portal client ---


class ScannerCreateScanRequest(BaseModel):
    # Optional: the API token alone already resolves to a project server-side. Kept for
    # backward compatibility with older scanner CLI versions that still send it — when
    # present, it's checked against the token's project as a client-error guard.
    project_id: str | None = None
    scanner_version: str | None = None
    hostname: str | None = None
    git_commit: str | None = None
    branch: str | None = None
    scan_label: str | None = None
    # Optional: older scanners omit it. Sanitized, never rejected -- see sanitize_repo_url.
    repo_url: str | None = None

    @field_validator("repo_url", mode="before")
    @classmethod
    def _clean_repo_url(cls, v):
        """Strip userinfo/query/fragment (a token can ride in any of them) and syntax-check. A bad
        value becomes None rather than a 422: the scan upload must never fail over display metadata."""
        return sanitize_repo_url(v)

    # Optional CI context. Older scanners omit all of it (and the model ignores unknown keys), so a
    # legacy body still means triggered_by="cli". "cloud"/"manual"/"sync" are portal-originated and
    # can never be claimed by a scanner.
    triggered_by: Literal["cli", "ci"] | None = None
    ci_provider: CiProvider | None = None
    ci_build_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    ci_build_number: str | None = Field(default=None, max_length=128)
    ci_build_url: str | None = Field(default=None, max_length=2048)

    @field_validator("ci_provider", "ci_build_id", "ci_build_number", "ci_build_url", mode="before")
    @classmethod
    def _blank_ci_to_none(cls, v):
        """Pipeline variables that did not resolve arrive as "" -- treat as absent, not as an error."""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("ci_build_number")
    @classmethod
    def _clean_build_number(cls, v: str | None) -> str | None:
        if v is not None and _CONTROL_CHARS.search(v):
            raise ValueError("ci_build_number must not contain control characters")
        return v

    @field_validator("ci_build_url")
    @classmethod
    def _clean_build_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if _CONTROL_CHARS.search(v) or re.search(r"\s", v):
            raise ValueError("ci_build_url must not contain whitespace or control characters")
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("ci_build_url must be an http(s) URL with a host")
        if parts.username or parts.password:
            raise ValueError("ci_build_url must not contain credentials")
        return v

    @model_validator(mode="after")
    def _validate_ci_metadata(self):
        has_ci = any((self.ci_provider, self.ci_build_id, self.ci_build_number, self.ci_build_url))
        if has_ci and self.triggered_by != "ci":
            raise ValueError("CI metadata requires triggered_by='ci'")
        if self.triggered_by == "ci" and not self.ci_provider:
            raise ValueError("ci_provider is required when triggered_by='ci'")
        return self


class ScannerCreateScanResponse(BaseModel):
    scan_id: str
    status: str
    project_id: str
    project_name: str


class ScannerStatusUpdateRequest(BaseModel):
    status: ScanStatus
    error_message: str | None = None
