"""Singleton: the advisory watcher's cursors, run lease and feed health (services/live_alert_service.py).

`key` carries a unique index so the singleton can be created with an upsert that two replicas racing at
first boot cannot turn into two documents. Every state write after the lease is taken is conditioned on
`lease_owner == run_id`, so a run that lost its lease (it outlived it, or was force-superseded) cannot
move a cursor or overwrite health."""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

STATE_KEY = "singleton"


class AdvisoryWatchState(Document):
    key: str = STATE_KEY
    # Per ecosystem: everything modified at or before this instant has been processed. Missing/None =
    # not started yet; the first run records the feed head and alerts nothing (never backfills).
    cursors: dict[str, datetime | None] = Field(default_factory=dict)
    lease_owner: str | None = None
    lease_until: datetime | None = None
    last_run_started_at: datetime | None = None
    last_run_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_status: Literal["ok", "partial", "error"] | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    failing_since: datetime | None = None
    unreachable_alerted_at: datetime | None = None
    last_gap_at: datetime | None = None
    last_gap_hours: float | None = None
    last_advisory_id: str | None = None
    last_advisory_published_at: datetime | None = None
    last_run_summary: dict = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "advisory_watch_state"
        indexes = [IndexModel([("key", 1)], unique=True)]
