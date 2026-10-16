"""Scan Engine ("engine room") documents: rule overrides, custom rules and published rule packs.

A *rule pack version* is the unit that takes effect: an immutable snapshot of (retired rule ids +
custom rules). `RuleOverride` and `CustomRule` are the admin's working copy; publishing freezes the
working copy as the next `RulePackVersion`, and the highest version is the active one.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RuleOverride(Document):
    """Working-copy state of one scanner rule. A rule with no row is active."""

    rule_id: str
    state: Literal["retired", "active"]
    reason: str
    updated_by: str
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "rule_overrides"
        indexes = [IndexModel([("rule_id", 1)], unique=True)]


class CustomRule(Document):
    """Working-copy custom rule. Only saved once it fired on the vulnerable sample and stayed
    silent on the safe one (scan_engine_service.save_custom_rule)."""

    rule_id: str  # ZS-CUSTOM-...
    yaml: str
    vulnerable_sample: str
    safe_sample: str
    language: str
    last_validated_at: datetime
    created_by: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "custom_rules"
        indexes = [IndexModel([("rule_id", 1)], unique=True)]


class PackCustomRule(BaseModel):
    """A custom rule frozen into a pack. Samples travel with it so a rollback can restore the working
    copy completely (the rule stays editable and re-validatable)."""

    rule_id: str
    yaml: str
    language: str = ""
    vulnerable_sample: str = ""
    safe_sample: str = ""


class RulePackVersion(Document):
    version: int
    retired_rule_ids: list[str] = Field(default_factory=list)
    custom_rules: list[PackCustomRule] = Field(default_factory=list)
    changelog: str
    published_by: str
    published_at: datetime = Field(default_factory=_now)
    # Set when this version was created by rolling back to an older one.
    rolled_back_from: int | None = None

    class Settings:
        name = "rule_pack_versions"
        # The unique index is what makes concurrent publishes safe: both read max+1, one insert wins.
        indexes = [IndexModel([("version", 1)], unique=True)]


class NoisyRuleAlert(Document):
    """One row per rule that has already triggered the `scan_engine.rule_noisy` notification."""

    rule_id: str
    notified_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "noisy_rule_alerts"
        indexes = [IndexModel([("rule_id", 1)], unique=True)]
