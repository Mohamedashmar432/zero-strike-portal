"""AI-generated per-finding enrichment (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md).

Deliberately its own collection, not fields on Finding: report_ingestion_service.ingest()
deletes and recreates Finding docs on every scan, so anything stored there would be lost
(and re-computed, re-costing an LLM call) on every re-scan. Keying by (fingerprint,
project_id) instead lets a finding that's stable across rescans reuse its cached insight.

Schema only for now -- no service writes to this collection yet (AI Analysis is a later
phase); this exists so Finding/Report never become the dumping ground for AI content
once that phase starts.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AIFindingInsight(Document):
    fingerprint: str
    project_id: str

    # Enrichment, mirroring zero-strike-cli's SecurityAgentRunner output shape.
    owasp: list[str] = Field(default_factory=list)
    cwe: list[str] = Field(default_factory=list)
    cvss_score: float | None = None
    explanation: str | None = None

    # Verdict/quality-review, beyond what the CLI does: does this finding actually hold up?
    is_false_positive: bool | None = None
    false_positive_confidence: float | None = None
    verdict_reasoning: str | None = None
    # Display-only AI severity overlay: when the AI judges the scanner's severity clearly wrong,
    # it sets adjusted_severity (else None). The scanner's Finding.severity stays the immutable
    # source of truth for counts/priority/dashboards -- this is a labeled, auditable overlay,
    # never written back onto the Finding.
    adjusted_severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    severity_reasoning: str | None = None
    # AI-refined explanation/recommendation. The scanner-produced Finding.message/
    # rationale/remediation are never overwritten -- this is a separate, clearly-labeled
    # layer so the original detection stays traceable/auditable.
    improved_description: str | None = None

    provider: str | None = None
    model_name: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_finding_insights"
        indexes = [
            IndexModel([("fingerprint", 1), ("project_id", 1)], unique=True),
            IndexModel([("project_id", 1)]),
        ]
