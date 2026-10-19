"""Admin MCP server (docs/ADMIN_MCP.md): read-only diagnostic tools over the same services the
admin pages use. Auth is app.mcp.auth; every call is audited as "MCP tool called".

Tools are plain async functions so tests can call them directly; `build()` registers them on a
fresh MCPServer (one per app instance — a session manager can only be run once).
"""

import asyncio
import functools
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from beanie import PydanticObjectId
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from app.core.config import settings
from app.db.mongo import get_database
from app.mcp.auth import McpAuthMiddleware, current_principal
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.system_log import SystemLog
from app.models.user import User
from app.services import (
    ai_analytics_service,
    audit_service,
    cloud_scan_service,
    data_management_service,
    operations_service,
    scanner_status_service,
    system_metrics,
    workspace_settings_service,
)
from app.services.secret_redaction import redact

MAX_LIMIT = 200
MAX_MESSAGE = 2_000
MAX_EXCEPTION = 8_000
_LEVELS_AT_OR_ABOVE = {
    "warning": ["warning", "error", "critical"],
    "error": ["error", "critical"],
    "critical": ["critical"],
}
JOB_KINDS = {q.kind: q for q in operations_service.QUEUES}


def _cap(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _clip(text: str | None, size: int) -> str | None:
    """Truncate then redact; None passes through."""
    if text is None:
        return None
    return redact(text[:size] + ("...[truncated]" if len(text) > size else ""))


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so datetimes/ObjectIds become strings."""
    return json.loads(json.dumps(value, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o)))


def _redact_context(ctx: Any) -> Any:
    """Every string at any depth — a clone URL with credentials can sit inside a nested dict."""
    if isinstance(ctx, str):
        return _clip(ctx, MAX_MESSAGE)
    if isinstance(ctx, dict):
        return {k: _redact_context(v) for k, v in ctx.items()}
    if isinstance(ctx, (list, tuple)):
        return [_redact_context(v) for v in ctx]
    return ctx


def _since(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=max(1, minutes))


def _tool(fn):
    """Audit the call, then run it. Fails closed: no principal, or a failed audit write, means no
    tool output."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        principal = current_principal.get()
        if principal is None:
            raise PermissionError("Not authenticated")
        arguments = {k: (v[:200] if isinstance(v, str) else v) for k, v in kwargs.items() if v is not None}
        await audit_service.record(
            "MCP tool called",
            actor_user_id=principal.user_id,
            target_type="mcp_tool",
            target_id=fn.__name__,
            metadata={"tool": fn.__name__, "arguments": arguments, "token_id": principal.token_id},
        )
        return _jsonable(await fn(*args, **kwargs))

    return wrapper


def _log_row(r: SystemLog, *, full: bool = False) -> dict:
    row = {
        "id": str(r.id),
        "level": r.level,
        "logger": r.logger,
        "message": _clip(r.message, MAX_MESSAGE),
        "created_at": r.created_at,
        "request_id": (r.context or {}).get("request_id"),
        "scan_id": (r.context or {}).get("scan_id"),
    }
    if full:
        row["context"] = _redact_context(r.context)
        row["exception"] = _clip(r.exception, MAX_EXCEPTION)
    else:
        row["has_exception"] = bool(r.exception)
    return row


def _audit_row(a: AuditLog) -> dict:
    project_id = audit_service.effective_project_id(a)
    return {
        "id": str(a.id),
        "created_at": a.created_at,
        "actor_type": a.actor_type,
        "actor_user_id": a.actor_user_id,
        "action": a.action,
        "category": audit_service.classify(a.action, project_id),
        "target_type": a.target_type,
        "target_id": a.target_id,
        "project_id": project_id,
        "metadata": a.metadata,
        "ip_address": a.ip_address,
    }


# --- tools ------------------------------------------------------------------


@_tool
async def get_system_health() -> dict[str, Any]:
    """Is the portal healthy right now? Mongo ping, scanner binary, queue depths, CPU/memory, error count last hour."""
    try:
        await get_database().command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    now = datetime.now(timezone.utc)
    (queues, _), load = await asyncio.gather(
        operations_service._all_queues(now),
        asyncio.to_thread(system_metrics.sample, str(cloud_scan_service._workdir_root())),
    )
    hour_ago = now - timedelta(hours=1)
    errors = await SystemLog.find({"created_at": {"$gte": hour_ago}, "level": {"$in": ["error", "critical"]}}).count()
    warnings = await SystemLog.find({"created_at": {"$gte": hour_ago}, "level": "warning"}).count()
    return {
        "mongo": mongo_ok,
        "scanner_binary_present": cloud_scan_service.scanner_available(),
        "queues": [q.model_dump(mode="json") for q in queues],
        "system": load,
        "errors_last_hour": errors,
        "warnings_last_hour": warnings,
    }


@_tool
async def get_operations_overview() -> dict[str, Any]:
    """What is queued/running in all four queues (cloud scan, AI analysis, auto-fix, compliance), avg run times, 24h failures."""
    result = (await operations_service.overview()).model_dump(mode="json")
    for job in result["recent_failures"]:
        job["error_message"] = _clip(job.get("error_message"), MAX_MESSAGE)
    return result


@_tool
async def get_scanner_status() -> dict[str, Any]:
    """Scanner binary checklist, scanner queue, clone workspace state and recent scanner failures."""
    result = (await scanner_status_service.get_status()).model_dump(mode="json")
    return json.loads(redact(json.dumps(result)))


@_tool
async def list_system_logs(
    level: str = "warning",
    logger: str | None = None,
    contains: str | None = None,
    request_id: str | None = None,
    scan_id: str | None = None,
    since_minutes: int = 60,
    limit: int = 50,
) -> dict[str, Any]:
    """Recent WARNING+ backend log lines, newest first. level is the minimum: warning | error | critical."""
    levels = _LEVELS_AT_OR_ABOVE.get(level)
    if levels is None:
        raise ToolError("level must be one of: warning, error, critical")
    query: dict = {"created_at": {"$gte": _since(since_minutes)}, "level": {"$in": levels}}
    if logger:
        query["logger"] = logger
    if contains:
        query["message"] = {"$regex": re.escape(contains), "$options": "i"}
    if request_id:
        query["context.request_id"] = request_id
    if scan_id:
        query["context.scan_id"] = scan_id
    total = await SystemLog.find(query).count()
    rows = await SystemLog.find(query).sort("-created_at").limit(_cap(limit)).to_list()
    return {"total": total, "items": [_log_row(r) for r in rows]}


@_tool
async def get_system_log(id: str) -> dict[str, Any]:
    """One log row with its full (redacted) traceback and context."""
    row = await SystemLog.get(id) if PydanticObjectId.is_valid(id) else None
    if row is None:
        raise ToolError("No such log row")
    return _log_row(row, full=True)


@_tool
async def summarize_errors(since_minutes: int = 1440, level: str = "error", limit: int = 20) -> dict[str, Any]:
    """Top error groups in a window: (logger, level, message head) -> count, first/last seen, one sample id."""
    levels = _LEVELS_AT_OR_ABOVE.get(level)
    if levels is None:
        raise ToolError("level must be one of: warning, error, critical")
    # ponytail: grouped in Python over the newest 5000 rows; a flood beyond that undercounts the tail.
    rows = (
        await SystemLog.find({"created_at": {"$gte": _since(since_minutes)}, "level": {"$in": levels}})
        .sort("-created_at")
        .limit(5000)
        .to_list()
    )
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r.logger, r.level, _clip(r.message[:100], 100))
        g = groups.setdefault(
            key,
            {
                "logger": key[0], "level": key[1], "message_head": key[2], "count": 0,
                "first_seen": r.created_at, "last_seen": r.created_at, "sample_id": str(r.id),
            },
        )
        g["count"] += 1
        g["first_seen"] = min(g["first_seen"], r.created_at)
        g["last_seen"] = max(g["last_seen"], r.created_at)
    top = sorted(groups.values(), key=lambda g: g["count"], reverse=True)[: _cap(limit)]
    return {"rows_examined": len(rows), "groups": top}


@_tool
async def trace_request(request_id: str) -> dict[str, Any]:
    """Everything one request touched: system logs carrying the request_id, plus audit rows."""
    logs = await SystemLog.find({"context.request_id": request_id}).sort("created_at").limit(MAX_LIMIT).to_list()
    audits = await AuditLog.find({"metadata.request_id": request_id}).sort("created_at").limit(MAX_LIMIT).to_list()
    return {
        "request_id": request_id,
        "system_logs": [_log_row(r, full=True) for r in logs],
        "audit_logs": [_audit_row(a) for a in audits],
    }


@_tool
async def list_audit_logs(
    days: int = 1,
    category: str | None = None,
    action_contains: str | None = None,
    actor_user_id: str | None = None,
    project_id: str | None = None,
    failures_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Who did what, newest first. category: privilege | project | admin."""
    days = max(1, min(days, 90))
    query: dict = {"created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}}
    if actor_user_id:
        query["actor_user_id"] = actor_user_id
    if project_id:
        query["project_id"] = project_id
    patterns = [re.escape(action_contains)] if action_contains else []
    if failures_only:
        patterns.append("fail")
    for p in patterns:
        query.setdefault("$and", []).append({"action": {"$regex": p, "$options": "i"}})
    # ponytail: category is derived from the action name, so it is applied in Python over the
    # newest 2000 matching rows.
    rows = await AuditLog.find(query).sort("-created_at").limit(2000).to_list()
    items = [_audit_row(a) for a in rows]
    if category:
        items = [i for i in items if i["category"] == category]
    return {"total_matching": len(items), "items": items[: _cap(limit)]}


@_tool
async def inspect_job(kind: str, id: str) -> dict[str, Any]:
    """Full state of one job. kind: cloud_scan | ai_analysis | remediation | compliance."""
    q = JOB_KINDS.get(kind)
    if q is None:
        raise ToolError(f"kind must be one of: {', '.join(JOB_KINDS)}")
    doc = None
    if PydanticObjectId.is_valid(id):
        # Inclusion projection: a Scan carries repo_token, which must never be read here.
        fields = {**operations_service._FIELDS, "updated_at": 1, "retry_count": 1, "max_attempts": 1}
        doc = await q.model.get_pymongo_collection().find_one({"_id": PydanticObjectId(id)}, fields)
    if doc is None:
        raise ToolError("No such job")
    doc["id"] = str(doc.pop("_id"))
    doc["error_message"] = _clip(doc.get("error_message"), MAX_MESSAGE)
    if doc.get("repo_url"):
        doc["repo_url"] = redact(doc["repo_url"])
    pid = doc.get("project_id") or ""
    project = await Project.get(pid) if PydanticObjectId.is_valid(pid) else None
    return {"kind": q.kind, "project_name": project.name if project else None, **doc}


@_tool
async def list_failed_jobs(limit: int = 50) -> dict[str, Any]:
    """Failures from the last 24 hours across all four queues, newest first, with error messages."""
    failures = await operations_service._recent_failures(datetime.now(timezone.utc), _cap(limit))
    await operations_service._name_projects(failures)
    items = [j.model_dump(mode="json") for j in failures]
    for j in items:
        j["error_message"] = _clip(j.get("error_message"), MAX_MESSAGE)
    return {"window_hours": 24, "items": items}


@_tool
async def get_ai_health(days: int = 7, limit: int = 20) -> dict[str, Any]:
    """Portal-wide AI usage: calls, error rate, latency, cost, plus the most recent failed calls."""
    days = max(1, min(days, 365))
    analytics = await ai_analytics_service.get_analytics(project_id=None, days=days)
    failed = await ai_analytics_service.list_events(
        project_id=None, page=1, page_size=_cap(limit), days=days, status="failed"
    )
    return {"days": days, "analytics": analytics, "recent_failed_calls": failed["items"]}


@_tool
async def get_runtime_config() -> dict[str, Any]:
    """Allow-listed non-secret settings (timeouts, concurrency, scanner path, which integrations are configured) plus workspace settings."""
    s = settings
    allowed = (
        "app_env", "mcp_enabled", "scanner_binary_path", "scanner_build_ref", "scan_timeout_seconds",
        "max_concurrent_cloud_scans", "scanner_max_workers", "clone_min_free_mb", "clone_max_repo_mb",
        "queue_poll_interval_seconds", "queue_stuck_multiplier", "max_concurrent_ai_jobs",
        "ai_job_timeout_seconds", "ai_llm_request_timeout_seconds", "max_concurrent_remediation_jobs",
        "remediation_job_timeout_seconds", "remediation_critic_enabled", "max_concurrent_compliance_audits",
        "compliance_audit_timeout_seconds", "access_token_ttl_minutes", "refresh_token_ttl_days",
        "trusted_proxy_hops", "cors_origins", "smtp_port", "smtp_use_tls",
    )
    ws = await workspace_settings_service.get_workspace_settings()
    return {
        "settings": {k: getattr(s, k) for k in allowed},
        "configured": {
            "smtp": bool(s.smtp_host),
            "oauth_encryption_key": bool(s.oauth_encryption_key),
            "azure_key_vault": bool(s.azure_key_vault_url),
            "github_oauth": bool(s.github_client_id and s.github_client_secret),
            "azure_devops_oauth": bool(s.azure_devops_client_id and s.azure_devops_client_secret),
        },
        "workspace": ws.model_dump(
            mode="json", exclude={"id", "revision_id", "email_templates", "signup_notify_admin_ids"}
        ),
    }


@_tool
async def get_data_stats(project_id: str | None = None) -> dict[str, Any]:
    """Collection document counts by category, optionally for one project."""
    return {"project_id": project_id, "categories": await data_management_service.get_stats(project_id)}


@_tool
async def list_projects(limit: int = 50) -> dict[str, Any]:
    """Projects with member count and last scan status/time, so ids from other tools mean something."""
    projects = await Project.find().sort("-created_at").limit(_cap(limit)).to_list()
    items = []
    for p in projects:
        pid = str(p.id)
        last = await Scan.find(Scan.project_id == pid).sort("-created_at").first_or_none()
        items.append(
            {
                "id": pid,
                "name": p.name,
                "is_archived": p.is_archived,
                "member_count": await ProjectMember.find(ProjectMember.project_id == pid).count(),
                "scan_count": p.scan_count,
                "last_scan": {"id": str(last.id), "status": last.status, "created_at": last.created_at}
                if last
                else None,
            }
        )
    return {"items": items}


@_tool
async def lookup_user(email_or_id: str) -> dict[str, Any]:
    """One user by email or id: role, active, approval, created, last login. There is no list tool."""
    user = await (
        User.get(email_or_id)
        if PydanticObjectId.is_valid(email_or_id)
        else User.find_one(User.email == email_or_id.strip().lower())
    )
    if user is None:
        raise ToolError("No such user")
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "approval_status": user.approval_status,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


TOOLS = [
    get_system_health, get_operations_overview, get_scanner_status, list_system_logs, get_system_log,
    summarize_errors, trace_request, list_audit_logs, inspect_job, list_failed_jobs, get_ai_health,
    get_runtime_config, get_data_stats, list_projects, lookup_user,
]


def build() -> tuple[McpAuthMiddleware, MCPServer]:
    """A fresh server and its auth-wrapped ASGI app, mounted at /mcp by main.create_app."""
    server = MCPServer("thinkshield-portal")
    for fn in TOOLS:
        server.add_tool(fn, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    inner = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # The bearer token is the gate; the default localhost-only Host allow-list would 421
        # every request behind the real hostname.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return McpAuthMiddleware(inner), server
