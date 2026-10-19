"""Persist backend log records (WARNING and above) to Mongo's `system_logs` collection.

`emit()` runs on whatever thread logged — the event loop, or a worker thread running the
scanner subprocess — so it only parks a plain dict on a thread-safe queue. `flush_loop()`, a
task started in the app lifespan, batches those into Mongo. A log write must never slow down
or break the request that logged, so a full queue drops the record and a failed insert drops
the batch: stdout still has every line.
"""

import asyncio
import json
import logging
import queue
from datetime import datetime, timezone

from app.models.system_log import SystemLog

_MAX_QUEUED = 10_000
_MAX_MESSAGE = 4_000
_FLUSH_SECONDS = 2.0
# Keys structlog adds that are already stored as columns.
_COLUMN_KEYS = {"event", "level", "timestamp", "exception", "logger"}

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=_MAX_QUEUED)


def _to_row(record: logging.LogRecord) -> dict:
    message = record.getMessage()
    context: dict = {}
    exception = None
    # structlog's JSONRenderer hands stdlib one JSON string per event; unpack it so the
    # event text and its bound fields (request_id, scan_id, ...) are queryable, not a blob.
    if message.startswith("{"):
        try:
            event = json.loads(message)
        except ValueError:
            event = None
        if isinstance(event, dict) and "event" in event:
            message = str(event["event"])
            exception = event.get("exception")
            context = {k: v for k, v in event.items() if k not in _COLUMN_KEYS}
    if exception is None and record.exc_info:
        exception = logging.Formatter().formatException(record.exc_info)
    return {
        "level": record.levelname.lower(),
        "logger": record.name,
        "message": message[:_MAX_MESSAGE],
        "context": context,
        "exception": exception[:_MAX_MESSAGE * 4] if exception else None,
        "created_at": datetime.fromtimestamp(record.created, timezone.utc),
    }


class MongoLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # A client hanging up mid-request (e.g. an MCP agent killed mid-call) is not a server
        # fault; persisting it would only bury real errors in System Logs and summarize_errors.
        if record.exc_info and record.exc_info[0] is not None and record.exc_info[0].__name__ == "ClientDisconnect":
            return
        try:
            _queue.put_nowait(_to_row(record))
        except queue.Full:
            pass  # ponytail: drop under a flood; stdout keeps the line. Count drops if it ever matters.
        except Exception:
            self.handleError(record)


def install(level: int = logging.WARNING) -> None:
    root = logging.getLogger()
    if not any(isinstance(h, MongoLogHandler) for h in root.handlers):
        root.addHandler(MongoLogHandler(level))


def _drain() -> list[dict]:
    rows = []
    while True:
        try:
            rows.append(_queue.get_nowait())
        except queue.Empty:
            return rows


async def flush() -> None:
    rows = _drain()
    if not rows:
        return
    try:
        await SystemLog.get_pymongo_collection().insert_many(rows, ordered=False)
    except Exception:
        # Deliberately silent: logging this failure would enqueue another row for the same
        # broken sink. The lines are already on stdout.
        pass


async def flush_loop() -> None:
    try:
        while True:
            await asyncio.sleep(_FLUSH_SECONDS)
            await flush()
    finally:
        await flush()  # shutdown: keep whatever was logged in the last interval
