"""Durable, atomically-claimable AI-analysis job, mirroring how Scan works for the
cloud-scan queue (see app.core.job_queue, app.services.scan_queue_service).

One job represents either enriching a single finding (kind="finding", scoped by its
fingerprint) or synthesizing a whole scan (kind="scan", scoped by scan_id). `scope_key`
is the de-duplication key: routers/ai_analysis.py looks for an active (queued/running)
job with this (kind, scope_key) before inserting a new one, so triggering analysis twice
on an already-in-flight scope returns the existing job instead of creating a duplicate.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

AIJobKind = Literal["finding", "scan"]
AIJobStatus = Literal["queued", "running", "completed", "failed"]


class AIAnalysisJob(Document):
    kind: AIJobKind
    project_id: str
    scan_id: str
    fingerprint: str | None = None  # set for kind="finding"; None for kind="scan"
    scope_key: str  # fingerprint for kind="finding", scan_id for kind="scan" -- the uniqueness key
    force: bool = False
    status: AIJobStatus = "queued"
    retry_count: int = 0
    max_attempts: int = 2
    created_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    # Live progress for the "AI analyzing · N%" tag: number of enrichment batches (chunks)
    # done vs total. Set once the chunk count is known and bumped as each chunk finishes.
    # 0/0 = not started; the frontend derives % and a rough ETA from these + started_at.
    progress_completed: int = 0
    progress_total: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_analysis_jobs"
        # NOTE: a partial unique index on (kind, scope_key) filtered to status in
        # ["queued", "running"] was tried here first (to dead-simple-guard against a race
        # between the app-level check and the insert below), but mongomock_motor -- used by
        # this repo's test suite -- creates the index as a plain (non-partial) unique index,
        # ignoring partialFilterExpression entirely. That silently breaks the legitimate case of
        # re-triggering analysis (a new job with the same scope_key) once a prior job for that
        # same scope has already reached a terminal status. Per this feature's spec, falling
        # back to the application-level check as the *primary* duplicate-prevention mechanism
        # (see _active_job in routers/ai_analysis.py, which looks for an existing queued/running
        # job before inserting) plus a plain non-unique compound index for that query's shape.
        indexes = [
            IndexModel([("status", 1), ("created_at", 1)]),  # oldest-queued claim query (job_queue.claim_next)
            IndexModel([("kind", 1), ("scope_key", 1), ("status", 1)]),
        ]
