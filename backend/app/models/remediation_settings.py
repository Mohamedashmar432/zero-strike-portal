"""Admin-configured policy for AI Auto-Fix — a singleton, created lazily on first read
(see remediation_settings_service). It is the DB-backed override layer over the code-level
`remediation_*` defaults in app.core.config; the defaults below mirror those values so a
fresh document behaves identically to the pre-existing env-only behaviour.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field


class RemediationSettings(Document):
    enabled: bool = True
    confidence_threshold: float = 80.0  # mirrors settings.remediation_confidence_threshold
    max_findings_per_job: int = 20  # mirrors settings.remediation_max_findings_per_job
    # Base AI Auto-Fix allowance per SCAN. Distinct from max_findings_per_job, which
    # caps one propose run: a scan can be run through several jobs, and this is the
    # total distinct findings that may ever be fixed on it. Admins raise it globally
    # here, or per-scan by approving an AutoFixQuotaRequest.
    auto_fix_findings_per_scan: int = 10
    # mirrors ai_remediation_apply_service._BLOCKING_SEVERITIES — which new-finding severities
    # abort a PR during the apply re-scan.
    blocking_severities: list[str] = Field(default_factory=lambda: ["critical", "high", "medium"])

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str | None = None

    class Settings:
        name = "remediation_settings"
