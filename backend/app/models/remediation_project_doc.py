"""Per-project AI remediation overview (the "like a CLAUDE.md" doc, see docs/AI_AUTOFIX_DESIGN.md).

Generated once by exploring a cloned repo during the propose phase: languages, frameworks, entry
points, dependency manifests, and security-relevant areas. Stored server-side and reused as context
for every fix on that repo, and shown/downloadable in the Auto-Fix UI (never committed to the repo).

Cached by (project_id, project_repo_id, base_commit_sha) so it's generated once per commit and
reused across findings and re-runs; a new commit regenerates it.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class RemediationProjectDoc(Document):
    project_id: str
    # None for a hand-pasted (non-connected) repo — then keyed by repo_url + commit instead.
    project_repo_id: str | None = None
    repo_url: str | None = None
    base_commit_sha: str | None = None
    markdown: str
    provider: str | None = None
    model_name: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_remediation_project_docs"
        indexes = [
            IndexModel([("project_id", 1), ("project_repo_id", 1), ("base_commit_sha", 1)]),
            IndexModel([("project_id", 1), ("generated_at", -1)]),
        ]
