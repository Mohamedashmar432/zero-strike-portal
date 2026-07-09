from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class ScanCreateRequest(BaseModel):
    scan_type: Literal["local", "cloud", "cicd"]
    scan_label: str | None = None
    repo_url: str | None = None
    ci_provider: Literal["github_actions", "gitlab_ci", "azure_pipelines"] | None = None

    @model_validator(mode="after")
    def _validate_type_config(self):
        if self.scan_type == "cloud" and not self.repo_url:
            raise ValueError("repo_url is required for cloud scans")
        if self.scan_type == "cicd" and not self.ci_provider:
            raise ValueError("ci_provider is required for CI/CD scans")
        return self


class ScanResponse(BaseModel):
    id: str
    project_id: str
    scan_type: Literal["local", "cloud", "cicd"]
    triggered_by: Literal["cli", "ci", "cloud", "manual"]
    status: Literal["pending", "running", "completed", "failed"]
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


class ScanMockCompleteRequest(BaseModel):
    status: Literal["completed", "failed"] = "completed"
    error_message: str | None = None
