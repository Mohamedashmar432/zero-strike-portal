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

from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument


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
    return model.model_validate(raw)


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
        else:
            doc.status = failed_status
            doc.error_message = dead_letter_message if doc.retry_count > 0 else crash_message
            doc.completed_at = now
        await doc.save()
