from pydantic import BaseModel, Field, field_validator

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")


class RemediationSettingsResponse(BaseModel):
    enabled: bool
    confidence_threshold: float
    max_findings_per_job: int
    blocking_severities: list[str]


class RemediationSettingsUpdateRequest(BaseModel):
    """All fields optional — a PUT patches only what it sends (see exclude_unset in the router)."""

    enabled: bool | None = None
    confidence_threshold: float | None = Field(default=None, ge=0, le=100)
    max_findings_per_job: int | None = Field(default=None, ge=1, le=100)
    blocking_severities: list[str] | None = None

    @field_validator("blocking_severities")
    @classmethod
    def _known_severities(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        bad = [s for s in v if s not in VALID_SEVERITIES]
        if bad:
            raise ValueError(f"Unknown severities {bad}; allowed: {list(VALID_SEVERITIES)}")
        return list(dict.fromkeys(v))  # dedupe, preserve order
