"""Per-project monthly AI budgets (design: docs/AI_PRICING_AND_BUDGETS.md).

Usage is summed from AIUsageEvent for the current UTC calendar month. Two thresholds per limit --
the project's alert percent and 100% -- each email the project owner once per month. The claim is
an atomic $addToSet guarded on the key being absent, so concurrent calls and replicas cannot both
send it.
"""

from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId

from app.models.ai_usage_event import AIUsageEvent
from app.models.project import Project
from app.services import notification_service

logger = structlog.get_logger(__name__)


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def month_to_date(project_id: str) -> dict:
    # The raw collection, as ai_analytics_service does: Beanie's aggregate() wrapper awaits the
    # cursor, which the mongomock driver the tests run on cannot do.
    cursor = AIUsageEvent.get_pymongo_collection().aggregate(
        [
            {"$match": {"project_id": project_id, "status": "success", "created_at": {"$gte": _month_start()}}},
            {
                "$group": {
                    "_id": None,
                    "cost_usd": {"$sum": "$cost_usd"},
                    "tokens": {"$sum": {"$add": ["$prompt_tokens", "$completion_tokens"]}},
                    "requests": {"$sum": 1},
                    "unpriced_requests": {"$sum": {"$cond": [{"$eq": ["$cost_known", False]}, 1, 0]}},
                }
            },
        ]
    )
    rows = await cursor.to_list(length=1)
    row = rows[0] if rows else {}
    return {
        "cost_usd": float(row.get("cost_usd", 0.0)),
        "tokens": int(row.get("tokens", 0)),
        "requests": int(row.get("requests", 0)),
        "unpriced_requests": int(row.get("unpriced_requests", 0)),
        "period_start": _month_start(),
    }


def _limits(project: Project) -> list[tuple[str, float, str]]:
    """(metric, limit, unit label) for each limit the project has set."""
    out = []
    if project.ai_budget_usd_monthly:
        out.append(("usd", float(project.ai_budget_usd_monthly), "spend"))
    if project.ai_budget_tokens_monthly:
        out.append(("tokens", float(project.ai_budget_tokens_monthly), "tokens"))
    return out


def _fmt(metric: str, value: float) -> str:
    return f"${value:,.2f}" if metric == "usd" else f"{int(value):,} tokens"


async def hard_stop_reason(project_id: str) -> str | None:
    """A readable refusal when the project has hard stop on and has reached a limit, else None."""
    project = await _load(project_id)
    if project is None or not project.ai_budget_hard_stop:
        return None
    limits = _limits(project)
    if not limits:
        return None
    usage = await month_to_date(project_id)
    for metric, limit, _ in limits:
        used = usage["cost_usd"] if metric == "usd" else usage["tokens"]
        if used >= limit:
            return (
                f"This project has reached its monthly AI budget ({_fmt(metric, used)} of "
                f"{_fmt(metric, limit)}). A project owner or admin can raise it under "
                "Project → Settings → AI budget."
            )
    return None


async def check_thresholds(project_id: str) -> None:
    """Alert the owner on each newly crossed threshold. Never raises: it runs after a provider call
    that already succeeded."""
    try:
        project = await _load(project_id)
        if project is None:
            return
        limits = _limits(project)
        if not limits:
            return
        usage = await month_to_date(project_id)
        month = _month_start().strftime("%Y-%m")
        for metric, limit, unit in limits:
            used = usage["cost_usd"] if metric == "usd" else usage["tokens"]
            pct = used / limit * 100
            for threshold in sorted({project.ai_budget_alert_percent, 100}, reverse=True):
                if pct < threshold:
                    continue
                key = f"{month}:{metric}:{threshold}"
                claimed = await Project.get_pymongo_collection().update_one(
                    {"_id": project.id, "ai_budget_alerts_sent": {"$ne": key}},
                    {"$addToSet": {"ai_budget_alerts_sent": key}},
                )
                if claimed.modified_count:
                    await _alert(project, metric, unit, used, limit, threshold, usage["period_start"])
                break  # the highest crossed threshold is the one worth saying; lower ones are implied
    except Exception:
        logger.exception("ai budget threshold check failed", project_id=project_id)


async def _alert(project: Project, metric, unit, used, limit, threshold, period_start) -> None:
    reached = threshold >= 100
    stop = " AI calls for this project are now paused." if reached and project.ai_budget_hard_stop else ""
    title = (
        f"{project.name}: AI {unit} budget reached"
        if reached
        else f"{project.name}: {threshold}% of the AI {unit} budget used"
    )
    body = (
        f"{project.name} has used {_fmt(metric, used)} of its {_fmt(metric, limit)} monthly AI "
        f"{unit} budget since {period_start:%d %b %Y} (UTC).{stop}"
    )
    await notification_service.notify(
        "ai.budget_threshold",
        project_id=str(project.id),
        title=title,
        body=body,
        link=f"/projects/{project.id}?tab=settings",
        severity="error" if reached else "warning",
        only_user_ids=[project.owner_id],
    )


async def _load(project_id: str) -> Project | None:
    try:
        return await Project.get(PydanticObjectId(project_id))
    except Exception:
        return None
