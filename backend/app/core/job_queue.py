"""Generic durable-queue primitives for any Beanie Document representing a long-running,
atomically-claimable unit of work: a `status` field, `created_at`/`updated_at`
timestamps, and a `retry_count`/`max_attempts` pair for reap-then-retry escalation.

Extracted from `scan_queue_service` so cloud scans and future AI jobs (finding
enrichment, auto-fix generation) share one proven mechanism instead of each
reimplementing atomic claim + crash-recovery reap:
- `claim_next` is a single atomic `find_one_and_update`, safe across any number of
  concurrent callers/replicas (Mongo serializes the write per-document).
- `reap_stuck` reclaims documents stuck in a "running" status past a caller-supplied
  timeout: requeue if there's retry budget left, otherwise terminally fail (dead-letter).
"""

import asyncio
import weakref
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

_drain_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def drain_lock(queue: str) -> asyncio.Lock:
    """Serializes one queue's drain within this process. A drain reads free capacity, then claims —
    read-then-write — and is called from the poll loop *and* whenever a job finishes or is created,
    so two overlapping drains could both see the same free slot and push the queue past its cap.

    Keyed by event loop because an asyncio.Lock binds to the loop it first waits on (tests run one
    loop per test).
    ponytail: per-process lock — exact on our single replica. Several replicas would need a
    Mongo-side slot counter ($inc guarded by $lt cap) instead.
    """
    locks = _drain_locks.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(queue, asyncio.Lock())


async def claim_next(model, queued_status: str, running_status: str, extra_unset: dict | None = None):
    """Atomically claim the oldest document in `queued_status`, moving it to
    `running_status`. Returns None if nothing is queued."""
    col = model.get_pymongo_collection()
    now = datetime.now(timezone.utc)
    update: dict = {"$set": {"status": running_status, "started_at": now, "updated_at": now}}
    if extra_unset:
        update["$unset"] = extra_unset
    raw = await col.find_one_and_update(
        {"status": queued_status},
        update,
        sort=[("created_at", 1)],
        return_document=ReturnDocument.BEFORE,
    )
    if raw is None:
        return None
    doc = model.model_validate(raw)
    # find_one_and_update returns the pre-update document, so without this the caller's copy
    # has started_at=None and any later save() would write that None back over the claim stamp.
    doc.started_at = now
    return doc


async def reap_stuck(
    model,
    running_status: str,
    queued_status: str,
    failed_status: str,
    stuck_after: timedelta,
    crash_message: str,
    dead_letter_message: str,
) -> None:
    """Reclaim documents stuck in `running_status` past `stuck_after`: requeue if
    `retry_count + 1 < max_attempts`, otherwise mark `failed_status` (dead-letter)."""
    cutoff = datetime.now(timezone.utc) - stuck_after
    stuck = await model.find(model.status == running_status, model.updated_at < cutoff).to_list()
    for doc in stuck:
        now = datetime.now(timezone.utc)
        doc.updated_at = now
        if doc.retry_count + 1 < doc.max_attempts:
            doc.retry_count += 1
            doc.status = queued_status
            doc.started_at = None
            # A retry starts the pipeline over, so a stage left from the dead attempt would
            # describe work nothing is doing. Only models that have the field (Scan,
            # RemediationJob) — the primitive stays usable by ones that don't.
            if hasattr(doc, "stage"):
                doc.stage = None
                if hasattr(doc, "stage_started_at"):
                    doc.stage_started_at = None
        else:
            doc.status = failed_status
            # Name the phase it died in. "Interrupted" alone sent whoever had to diagnose a
            # stuck scan back to reading the source to guess between clone, scan and ingest;
            # this is the one line that answers it (docs/OBSERVABILITY_SCAN_AND_AI.md).
            stage = getattr(doc, "stage", None)
            where = f" Last known phase: {stage}." if stage else ""
            base = dead_letter_message if doc.retry_count > 0 else crash_message
            doc.error_message = f"{base}{where}"
            doc.completed_at = now
        await doc.save()
