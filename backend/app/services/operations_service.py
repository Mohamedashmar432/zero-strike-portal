"""One read-only view over the four Mongo-backed job queues (cloud scan, AI analysis, auto-fix,
compliance): what is running, what is waiting and roughly when it starts, and what failed.

Feeds two surfaces (docs/OPERATIONS_AND_QUEUEING.md): the queued tag + start-time countdown shown
wherever a job is queued, and the admin Operations page. It never claims or changes a job — the queue services own
that — so it is safe to poll.
"""

import asyncio
import heapq
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from beanie.operators import In

from app.core.config import settings
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_remediation_job import RemediationJob
from app.models.compliance_audit import ComplianceAudit
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.user import User
from app.schemas.operations import (
    OperationsResponse,
    QueueResponse,
    QueueJob,
    QueueSummary,
    SystemLoad,
)
from app.services import cloud_scan_service, system_metrics

AVG_SAMPLE = 20  # most recent completed jobs averaged per queue
MIN_HISTORY = 3  # below this, the per-queue default guess beats a noisy average
MAX_LISTED = 200  # ponytail: queued jobs listed per queue; a deeper backlog still counts, just isn't listed
FAILURE_WINDOW = timedelta(hours=24)

# Explicit projection: a queued Scan carries `repo_token`, which must never be read into this view.
_FIELDS = {
    "_id": 1, "project_id": 1, "status": 1, "stage": 1, "created_at": 1, "started_at": 1,
    "completed_at": 1, "error_message": 1, "scan_id": 1, "kind": 1, "triggered_by": 1,
    "repo_url": 1, "branch": 1, "frameworks": 1, "proposal_ids": 1, "finding_ids": 1, "fingerprint": 1,
}


@dataclass(frozen=True)
class _Queue:
    kind: str
    label: str
    model: type
    capacity_setting: str
    default_seconds: int  # ETA guess until the queue has history
    filter: dict


QUEUES = [
    _Queue("cloud_scan", "Cloud scans", Scan, "max_concurrent_cloud_scans", 180, {"scan_type": "cloud"}),
    _Queue("ai_analysis", "AI analysis", AIAnalysisJob, "max_concurrent_ai_jobs", 90, {}),
    _Queue("remediation", "Auto-fix", RemediationJob, "max_concurrent_remediation_jobs", 300, {}),
    _Queue("compliance", "Compliance audits", ComplianceAudit, "max_concurrent_compliance_audits", 60, {}),
]


def _utc(dt: datetime | None) -> datetime | None:
    # Motor hands back naive datetimes that are UTC; comparing them to aware ones raises.
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def estimate_starts(
    running_started: list[datetime], queued: int, capacity: int, avg: timedelta, now: datetime
) -> list[datetime]:
    """When each queued job (in queue order) should start, assuming every job takes `avg`.

    Each running job frees its slot at start+avg — or now, if it is already past that. With k jobs
    running against a cap of c, only the last c of those to finish free a slot (the first k-c just
    bring an over-cap queue back down to c), and c-k slots are free right away. Each queued job then
    takes the earliest slot to free up, and holds it for `avg`.
    """
    capacity = max(capacity, 1)
    ends = sorted(max(s + avg, now) for s in running_started)
    k = len(ends)
    slots = [now] * max(0, capacity - k) + ends[max(0, k - capacity):]
    heapq.heapify(slots)
    starts = []
    for _ in range(queued):
        t = heapq.heappop(slots)
        starts.append(t)
        heapq.heappush(slots, t + avg)
    return starts


def _summary(q: _Queue, doc: dict) -> str:
    if q.kind == "cloud_scan":
        repo = (doc.get("repo_url") or "").rstrip("/").removesuffix(".git").rsplit("/", 1)[-1] or "repository"
        branch = f" @ {doc['branch']}" if doc.get("branch") else ""
        via = " (repo sync)" if doc.get("triggered_by") == "sync" else ""
        return f"{repo}{branch}{via}"
    if q.kind == "ai_analysis":
        return "Single finding analysis" if doc.get("kind") == "finding" else "Scan analysis"
    if q.kind == "remediation":
        if doc.get("kind") == "apply":
            n = len(doc.get("proposal_ids") or []) or 1
            return f"Open PR for {n} fix{'es' if n != 1 else ''}"
        n = len(doc.get("finding_ids") or [])
        return f"Generate fixes for {n} finding{'s' if n != 1 else ''}"
    return "Audit: " + ", ".join(f.upper() for f in doc.get("frameworks") or [])


def _ref_id(q: _Queue, doc: dict) -> str:
    if q.kind in ("cloud_scan", "compliance"):
        return str(doc["_id"])
    # A single-finding AI job shares its scan_id with the scan-level analysis; key it on the finding.
    if q.kind == "ai_analysis" and doc.get("kind") == "finding":
        return doc.get("fingerprint") or ""
    return doc.get("scan_id", "")


def _job(q: _Queue, doc: dict, status: str, **extra) -> QueueJob:
    return QueueJob(
        kind=q.kind,
        job_id=str(doc["_id"]),
        project_id=doc["project_id"],
        ref_id=_ref_id(q, doc),
        status=status,
        summary=_summary(q, doc),
        stage=doc.get("stage"),
        created_at=_utc(doc["created_at"]),
        started_at=_utc(doc.get("started_at")),
        **extra,
    )


async def _avg_duration(q: _Queue) -> tuple[timedelta, bool]:
    docs = (
        await q.model.get_pymongo_collection()
        .find(
            {"status": "completed", "started_at": {"$ne": None}, "completed_at": {"$ne": None}, **q.filter},
            {"started_at": 1, "completed_at": 1},
        )
        .sort("completed_at", -1)
        .limit(AVG_SAMPLE)
        .to_list(AVG_SAMPLE)
    )
    durations = [(d["completed_at"] - d["started_at"]).total_seconds() for d in docs]
    # Sub-second "runs" are not work (seeded rows, an instant no-op); averaging them in turns every
    # countdown into "any moment".
    durations = [s for s in durations if s >= 1]
    if len(durations) < MIN_HISTORY:
        return timedelta(seconds=q.default_seconds), True
    return timedelta(seconds=sum(durations) / len(durations)), False


async def _queue_state(q: _Queue, now: datetime) -> tuple[QueueSummary, list[QueueJob]]:
    col = q.model.get_pymongo_collection()
    running = await col.find({"status": "running", **q.filter}, _FIELDS).sort("started_at", 1).to_list(None)
    queued_total = await col.count_documents({"status": "queued", **q.filter})
    queued = (
        await col.find({"status": "queued", **q.filter}, _FIELDS)
        .sort("created_at", 1)
        .limit(MAX_LISTED)
        .to_list(MAX_LISTED)
    )
    avg, is_default = await _avg_duration(q)
    capacity = getattr(settings, q.capacity_setting)
    # A cap of 0 pauses the queue: nothing will start until an admin raises it, so there is no honest
    # start time to give — and "any moment" would be a promise the queue cannot keep.
    starts: list[datetime | None] = (
        estimate_starts([_utc(d.get("started_at")) or now for d in running], len(queued), capacity, avg, now)
        if capacity > 0
        else [None] * len(queued)
    )

    jobs = [_job(q, d, "running") for d in running]
    jobs += [
        _job(q, d, "queued", position=i + 1, estimated_start_at=start)
        for i, (d, start) in enumerate(zip(queued, starts))
    ]
    summary = QueueSummary(
        kind=q.kind,
        label=q.label,
        capacity=capacity,
        running=len(running),
        queued=queued_total,
        avg_duration_seconds=round(avg.total_seconds(), 1),
        avg_is_default=is_default,
        oldest_queued_at=_utc(queued[0]["created_at"]) if queued else None,
    )
    return summary, jobs


async def _all_queues(now: datetime) -> tuple[list[QueueSummary], list[QueueJob]]:
    states = await asyncio.gather(*(_queue_state(q, now) for q in QUEUES))
    return [s for s, _ in states], [j for _, jobs in states for j in jobs]


async def _name_projects(jobs: list[QueueJob]) -> None:
    ids = {j.project_id for j in jobs if PydanticObjectId.is_valid(j.project_id)}
    if not ids:
        return
    names = {
        str(p.id): p.name for p in await Project.find(In(Project.id, [PydanticObjectId(i) for i in ids])).to_list()
    }
    for j in jobs:
        j.project_name = names.get(j.project_id)


async def _recent_failures(now: datetime, limit: int = 25) -> list[QueueJob]:
    since = now - FAILURE_WINDOW
    failures: list[QueueJob] = []
    for q in QUEUES:
        docs = (
            await q.model.get_pymongo_collection()
            .find({"status": "failed", "completed_at": {"$gte": since}, **q.filter}, _FIELDS)
            .sort("completed_at", -1)
            .limit(limit)
            .to_list(limit)
        )
        failures += [
            _job(q, d, "failed", error_message=d.get("error_message"), completed_at=_utc(d.get("completed_at")))
            for d in docs
        ]
    failures.sort(key=lambda j: j.completed_at or now, reverse=True)
    return failures[:limit]


async def visible_queue(user: User) -> QueueResponse:
    """Queued/running jobs in every project this user can see (all of them for an admin), each
    positioned against the *whole* queue — the wait depends on everyone ahead, not only on the
    user's own projects. Jobs in other projects are counted in the summaries but never returned."""
    now = datetime.now(timezone.utc)
    queues, jobs = await _all_queues(now)
    if user.role != "admin":
        memberships = await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()
        mine = {m.project_id for m in memberships}
        jobs = [j for j in jobs if j.project_id in mine]
    return QueueResponse(server_time=now, queues=queues, jobs=jobs)


async def overview() -> OperationsResponse:
    now = datetime.now(timezone.utc)
    (queues, jobs), failures, system = await asyncio.gather(
        _all_queues(now),
        _recent_failures(now),
        asyncio.to_thread(system_metrics.sample, str(cloud_scan_service._workdir_root())),
    )
    await _name_projects(jobs + failures)
    return OperationsResponse(
        server_time=now, system=SystemLoad(**system), queues=queues, jobs=jobs, recent_failures=failures
    )
