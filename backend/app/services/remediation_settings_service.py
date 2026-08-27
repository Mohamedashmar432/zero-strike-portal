"""Singleton admin policy for AI Auto-Fix (see RemediationSettings). Mirrors
report_template_service: at most one document ever exists, created lazily on first read.
"""

from datetime import datetime, timezone

from app.models.remediation_settings import RemediationSettings


async def get_settings() -> RemediationSettings:
    cfg = await RemediationSettings.find_one()
    if cfg is None:
        cfg = RemediationSettings()
        await cfg.insert()
    return cfg


async def update_settings(
    *,
    updated_by: str | None = None,
    enabled: bool | None = None,
    confidence_threshold: float | None = None,
    max_findings_per_job: int | None = None,
    auto_fix_findings_per_scan: int | None = None,
    blocking_severities: list[str] | None = None,
) -> RemediationSettings:
    cfg = await get_settings()
    if enabled is not None:
        cfg.enabled = enabled
    if confidence_threshold is not None:
        cfg.confidence_threshold = confidence_threshold
    if max_findings_per_job is not None:
        cfg.max_findings_per_job = max_findings_per_job
    if auto_fix_findings_per_scan is not None:
        cfg.auto_fix_findings_per_scan = auto_fix_findings_per_scan
    if blocking_severities is not None:
        cfg.blocking_severities = blocking_severities
    cfg.updated_at = datetime.now(timezone.utc)
    cfg.updated_by = updated_by
    await cfg.save()
    return cfg
