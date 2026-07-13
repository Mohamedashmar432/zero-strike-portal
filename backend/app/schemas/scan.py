from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from app.models.scan import ScanStatus


class ScanCreateRequest(BaseModel):
    scan_type: Literal["local", "cloud", "cicd"]
    scan_label: str | None = None
    repo_url: str | None = None
    branch: str | None = None
    ci_provider: Literal["github_actions", "gitlab_ci", "azure_pipelines"] | None = None
    # Transient: used to clone a private repo for a cloud scan, never persisted on the Scan.
    repo_token: str | None = None
    # Alternative to repo_token: resolve the clone credential from a connected GitHub/Azure DevOps
    # account (see connection_service.get_decrypted_token) instead of a hand-pasted token.
    connection_id: str | None = None
    # Alternative to repo_url/repo_token/connection_id: resolve everything (repo_url, branch, and
    # credential) from a repo already connected to the project (see ProjectRepo) — set by the
    # "Use connected repo" picker.
    project_repo_id: str | None = None

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
    scan_type: Literal["local", "cloud", "cicd"]
    triggered_by: Literal["cli", "ci", "cloud", "manual"]
    status: ScanStatus
    api_key_id: str | None
    scanner_version: str | None
    hostname: str | None
    git_commit: str | None
    branch: str | None
    scan_label: str | None
    repo_url: str | None
    ci_provider: Literal["github_actions", "gitlab_ci", "azure_pipelines"] | None
    created_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


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


class ScannerCreateScanResponse(BaseModel):
    scan_id: str
    status: str
    project_id: str
    project_name: str


class ScannerStatusUpdateRequest(BaseModel):
    status: ScanStatus
    error_message: str | None = None
