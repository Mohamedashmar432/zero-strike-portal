"""Reads the AI call log (AIUsageEvent) for the two dashboard scopes.

project_id=None means portal scope -- every project's calls, for the admin. Any other value
scopes to that one project. That single parameter is the only difference between the two
dashboards, which is why one component can render both.

Aggregation shape: one $facet per request, so a dashboard is a single round trip rather than
five. The outer $match applies the scope once and spans two windows (this period and the one
before it); each facet's own leading $match picks the window it reports on, so the
period-over-period comparison costs no extra query.
"""

from datetime import datetime, timedelta, timezone

from app.models.ai_usage_event import AIUsageEvent
from app.models.project import Project

# A day bucket is the finest granularity that stays readable across the 90-day range and cheap to
# aggregate. Buckets are UTC -- the same basis every other timestamp in the portal is stored in.
_DAY_FORMAT = "%Y-%m-%d"


def _match(project_id: str | None, since: datetime) -> dict:
    match: dict = {"created_at": {"$gte": since}}
    if project_id is not None:
        match["project_id"] = project_id
    return match


def _totals_projection(row: dict) -> dict:
    requests = row.get("requests", 0)
    failed = row.get("failed", 0)
    return {
        "requests": requests,
        "failed": failed,
        # Percent, not a fraction -- the UI shows "98.2%" and shouldn't have to know to multiply.
        # An empty window is 100% rather than 0%: "no calls" is not "every call failed".
        "success_rate": round((requests - failed) / requests * 100, 1) if requests else 100.0,
        "prompt_tokens": row.get("prompt_tokens", 0),
        "completion_tokens": row.get("completion_tokens", 0),
        "cost_usd": round(row.get("cost_usd", 0.0), 6),
        "avg_duration_ms": int(row.get("avg_duration_ms") or 0),
    }


_SUMS = {
    "requests": {"$sum": 1},
    "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
    "prompt_tokens": {"$sum": "$prompt_tokens"},
    "completion_tokens": {"$sum": "$completion_tokens"},
    "cost_usd": {"$sum": "$cost_usd"},
    "avg_duration_ms": {"$avg": "$duration_ms"},
}


_ZERO_ROW: dict = {"requests": 0, "cost_usd": 0.0}


def _with_deltas(row: dict, previous: dict[str, dict]) -> dict:
    """Attach the change vs the previous window of the same length to one by-feature row."""
    prev = previous.get(row["feature"], _ZERO_ROW)
    return {
        **row,
        "prev_cost_usd": round(prev.get("cost_usd", 0.0), 6),
        "prev_requests": prev.get("requests", 0),
        "cost_delta_usd": round(row["cost_usd"] - prev.get("cost_usd", 0.0), 6),
        "requests_delta": row["requests"] - prev.get("requests", 0),
    }


def _vanished_features(current: list[dict], previous: dict[str, dict]) -> list[dict]:
    """Rows for features that spent in the previous window and nothing in this one. A feature
    that stopped is as much of an explanation for a spend change as one that started."""
    seen = {r["feature"] for r in current}
    return [
        {
            "feature": key,
            **{k: (0 if isinstance(v, int) else 0.0) for k, v in row.items() if k != "success_rate"},
            "success_rate": 100.0,
            "prev_cost_usd": round(row.get("cost_usd", 0.0), 6),
            "prev_requests": row.get("requests", 0),
            "cost_delta_usd": round(-row.get("cost_usd", 0.0), 6),
            "requests_delta": -row.get("requests", 0),
        }
        for key, row in previous.items()
        if key not in seen and row.get("requests", 0) > 0
    ]


async def get_analytics(*, project_id: str | None, days: int = 30) -> dict:
    """Totals, a daily time series, and breakdowns by feature / model / (portal only) project.

    Every window is also compared against the one immediately before it, per feature. "Which
    feature spent the money" is only half an answer; "spend rose $12 and remediation is $11 of
    it" is the half someone can act on.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_prev = now - timedelta(days=days * 2)

    # The outer $match spans BOTH windows; each facet narrows to the one it reports on. One
    # round trip still, and the previous window costs no extra query.
    current = {"$match": {"created_at": {"$gte": since}}}
    previous = {"$match": {"created_at": {"$lt": since}}}

    facets: dict = {
        "totals": [current, {"$group": {"_id": None, **_SUMS}}],
        "prev_totals": [previous, {"$group": {"_id": None, **_SUMS}}],
        "timeseries": [
            current,
            {
                "$group": {
                    "_id": {"$dateToString": {"format": _DAY_FORMAT, "date": "$created_at"}},
                    **_SUMS,
                }
            },
            {"$sort": {"_id": 1}},
        ],
        "by_feature": [
            current,
            {"$group": {"_id": "$feature", **_SUMS}},
            {"$sort": {"cost_usd": -1, "_id": 1}},
        ],
        "prev_by_feature": [previous, {"$group": {"_id": "$feature", **_SUMS}}],
        "by_model": [
            current,
            {"$group": {"_id": {"provider": "$provider", "model_name": "$model_name"}, **_SUMS}},
            {"$sort": {"cost_usd": -1}},
        ],
        # WHY calls failed, over the same window. The totals already say how many failed; this is
        # the row that says whether the fix is a bigger context window, a new key, or patience.
        # Rows predating error_code have none, so they group under "unknown" rather than dropping
        # out and making the reasons not add up to the failure count.
        "failure_reasons": [
            current,
            {"$match": {"status": "failed"}},
            {"$group": {"_id": {"$ifNull": ["$error_code", "unknown"]}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
        ],
    }
    if project_id is None:
        facets["by_project"] = [
            current,
            {"$group": {"_id": "$project_id", **_SUMS}},
            {"$sort": {"cost_usd": -1}},
            # ponytail: 50 projects is far past what the chart can render legibly; the log table
            # below it is the drill-down. Paginate this only if someone runs more than 50 projects.
            {"$limit": 50},
        ]

    cursor = AIUsageEvent.get_pymongo_collection().aggregate(
        [{"$match": _match(project_id, since_prev)}, {"$facet": facets}]
    )
    rows = await cursor.to_list(length=1)
    faceted = rows[0] if rows else {}

    totals_rows = faceted.get("totals") or []
    prev_totals_rows = faceted.get("prev_totals") or []
    prev_totals = _totals_projection(prev_totals_rows[0] if prev_totals_rows else {})
    prev_by_feature = {
        (r["_id"] or "unknown"): _totals_projection(r) for r in faceted.get("prev_by_feature", [])
    }
    result = {
        "days": days,
        "totals": _totals_projection(totals_rows[0] if totals_rows else {}),
        "previous_totals": prev_totals,
        "timeseries": [
            {"date": r["_id"], **{k: v for k, v in _totals_projection(r).items() if k != "avg_duration_ms"}}
            for r in faceted.get("timeseries", [])
        ],
        "by_feature": [
            _with_deltas({"feature": r["_id"] or "unknown", **_totals_projection(r)}, prev_by_feature)
            for r in faceted.get("by_feature", [])
        ],
        "by_model": [
            {
                "provider": (r["_id"] or {}).get("provider") or "unknown",
                "model_name": (r["_id"] or {}).get("model_name"),
                **_totals_projection(r),
            }
            for r in faceted.get("by_model", [])
        ],
        "by_project": [],
        "failure_reasons": [
            {"error_code": r["_id"], "count": r["count"]} for r in faceted.get("failure_reasons", [])
        ],
    }
    result["by_feature"].extend(_vanished_features(result["by_feature"], prev_by_feature))

    if project_id is None:
        rows = faceted.get("by_project", [])
        names = await _project_names([r["_id"] for r in rows if r["_id"]])
        result["by_project"] = [
            {
                "project_id": r["_id"],
                "project_name": names.get(r["_id"]) or _missing_project_label(r["_id"]),
                **_totals_projection(r),
            }
            for r in rows
        ]
    return result


def _missing_project_label(project_id: str | None) -> str:
    """Deleted projects keep their spend visible rather than vanishing from the totals -- the money
    was still spent, and a gap in the chart is harder to explain than a label.

    The id fragment matters: a workspace that has deleted more than one project would otherwise get
    two or more identically-labelled bars, which is indistinguishable from a rendering bug.
    """
    if not project_id:
        return "Portal (no project)"
    # "#<fragment>" rather than "(<fragment>)": recharts wraps axis labels into tspans and eats the
    # space before a bracket, and a bare tail of a non-ObjectId legacy id reads as a stray word
    # ("(roject)") instead of an identifier.
    return f"Deleted project #{project_id[-6:]}"


async def _project_names(project_ids: list[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    projects = await Project.find({"_id": {"$in": [_as_object_id(p) for p in project_ids if p]}}).to_list()
    return {str(p.id): p.name for p in projects}


def _as_object_id(value: str):
    from beanie import PydanticObjectId

    try:
        return PydanticObjectId(value)
    except Exception:
        # A malformed id can only come from a hand-edited document; matching nothing is right.
        return value


async def list_events(
    *,
    project_id: str | None,
    page: int = 1,
    page_size: int = 25,
    days: int = 30,
    feature: str | None = None,
    status: str | None = None,
) -> dict:
    """The paginated call log itself, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = _match(project_id, since)
    if feature:
        query["feature"] = feature
    if status:
        query["status"] = status

    total = await AIUsageEvent.find(query).count()
    events = (
        await AIUsageEvent.find(query)
        .sort("-created_at", "-_id")
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    names = await _project_names([e.project_id for e in events if e.project_id])
    return {
        "items": [
            {
                "id": str(e.id),
                "created_at": e.created_at,
                "project_id": e.project_id,
                "project_name": names.get(e.project_id or "") if e.project_id else None,
                "scan_id": e.scan_id,
                "scope": e.scope,
                "feature": e.feature,
                "provider": e.provider,
                "model_name": e.model_name,
                "status": e.status,
                "error_type": e.error_type,
                "error_code": e.error_code,
                "attempt": e.attempt,
                "failover_from": e.failover_from,
                "duration_ms": e.duration_ms,
                "prompt_tokens": e.prompt_tokens,
                "completion_tokens": e.completion_tokens,
                "cost_usd": round(e.cost_usd, 6),
            }
            for e in events
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
