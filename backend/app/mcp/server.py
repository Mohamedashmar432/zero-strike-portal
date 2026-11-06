"""Admin MCP server (docs/ADMIN_MCP.md): read-only diagnostic tools over the same services the
admin pages use. Auth is app.mcp.auth; every call is audited as "MCP tool called".

Tools are plain async functions so tests can call them directly; `build()` registers them on a
fresh MCPServer (one per app instance — a session manager can only be run once).
"""

import asyncio
import dataclasses
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
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.compliance_audit import ComplianceAudit
from app.models.finding import NOT_SUPPRESSED, Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.scan_engine import CustomRule, RulePackVersion
from app.models.system_log import SystemLog
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.models.webhook_channel import WebhookChannel
from app.routers import compliance as compliance_router
from app.routers import finding_reviews as finding_reviews_router
from app.routers import scans as scans_router
from app.services import (
    ai_analytics_service,
    ai_budget_service,
    alert_service,
    audit_service,
    cloud_scan_service,
    data_management_service,
    digest_service,
    live_alert_service,
    operations_service,
    project_stats_service,
    scan_engine_service,
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
        # Encrypted fields (alert_webhook_enc, ...) are excluded by name, so a secret field added later
        # cannot ride out in this dump; only whether one is set is reported.
        "workspace": ws.model_dump(
            mode="json",
            exclude={"id", "revision_id", "email_templates", "signup_notify_admin_ids"}
            | {f for f in type(ws).model_fields if f.endswith("_enc")},
        ),
        "workspace_secrets_set": {
            f: bool(getattr(ws, f)) for f in type(ws).model_fields if f.endswith("_enc")
        },
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


# --- full-portal read tools -------------------------------------------------------------------
# Same rules as above (audited, capped, clipped/redacted), plus `_safe_tool`: every output is also
# scrubbed of credential-shaped keys, so a field added to a model later cannot leak through a tool
# that forgot to allow-list it. Rows are built from explicit allow-lists in the first place.

_SECRET_KEYS = frozenset(
    {"password", "repo_token", "refresh_tokens", "api_key_secret_name", "client_secret", "webhook_url", "secret_value"}
)
_SECRET_SUFFIXES = ("_hash", "_enc", "_encrypted")
MAX_TEXT = 2_000


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if not (isinstance(k, str) and (k.lower() in _SECRET_KEYS or k.lower().endswith(_SECRET_SUFFIXES)))
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _safe_tool(fn):
    inner = _tool(fn)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return _scrub(await inner(*args, **kwargs))

    return wrapper


def _text(value: str | None) -> str | None:
    return _clip(value, MAX_TEXT)


def _plain(obj: Any) -> Any:
    """A frozen policy dataclass as plain JSON (frozensets become sorted lists)."""
    return {k: sorted(v) if isinstance(v, frozenset) else v for k, v in dataclasses.asdict(obj).items()}


async def _oid_doc(model, value: str, what: str):
    doc = await model.get(value) if PydanticObjectId.is_valid(value) else None
    if doc is None:
        raise ToolError(f"No such {what}")
    return doc


# Scan Engine ---------------------------------------------------------------------------------


@_safe_tool
async def list_scan_rules(
    query: str | None = None, state: str | None = None, noisy_only: bool = False, limit: int = 50
) -> dict[str, Any]:
    """Scan Engine rules with finding counts and false-positive rate, most false-positive tags first. query matches rule id or title; state: active | retired | custom (or any state the engine reports); noisy_only keeps rules over the noisy threshold."""
    stats = await scan_engine_service.rule_stats()
    rows = stats["rules"]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in (r.get("rule_id") or "").lower() or q in (r.get("title") or "").lower()]
    if state:
        rows = [r for r in rows if r.get("state") == state]
    if noisy_only:
        rows = [r for r in rows if r.get("noisy")]
    return {
        "total_matching": len(rows),
        "noisy_min_fp_tags": stats.get("noisy_min_fp_tags"),
        "noisy_min_fp_percent": stats.get("noisy_min_fp_percent"),
        "active_pack_version": stats.get("active_version"),
        "items": [{**r, "retire_reason": _text(r.get("retire_reason"))} for r in rows[: _cap(limit)]],
    }


@_safe_tool
async def list_noisy_rules(limit: int = 50) -> dict[str, Any]:
    """Rules whose false-positive tags crossed the workspace noisy threshold, worst first."""
    stats = await scan_engine_service.rule_stats()
    rows = [r for r in stats["rules"] if r.get("noisy")]
    return {
        "total_noisy": len(rows),
        "noisy_min_fp_tags": stats.get("noisy_min_fp_tags"),
        "noisy_min_fp_percent": stats.get("noisy_min_fp_percent"),
        "items": rows[: _cap(limit)],
    }


@_safe_tool
async def get_scan_rule(rule_id: str, history_limit: int = 50) -> dict[str, Any]:
    """One rule: its stats row, retirement/custom state, and who tagged which project's finding a false positive (names the project, never its code)."""
    stats = await scan_engine_service.rule_stats()
    row = next((r for r in stats["rules"] if r.get("rule_id") == rule_id), None)
    if row is None:
        raise ToolError("No such rule (it has produced no finding and is neither retired nor custom)")
    history = await scan_engine_service.rule_fp_history(rule_id, _cap(history_limit))
    custom = await CustomRule.find_one(CustomRule.rule_id == rule_id)
    return {
        "rule": {**row, "retire_reason": _text(row.get("retire_reason"))},
        "fp_history": [{**h, "comment": _text(h.get("comment"))} for h in history],
        "custom_rule": {
            "language": custom.language,
            "created_by": custom.created_by,
            "last_validated_at": custom.last_validated_at,
            "yaml": _clip(custom.yaml, MAX_EXCEPTION),
        }
        if custom
        else None,
    }


@_safe_tool
async def get_rule_pack(versions: int = 10) -> dict[str, Any]:
    """The active rule pack (version, retired rules, custom rule metadata), recent versions, and the unpublished pending changes."""
    pack = await scan_engine_service.active_pack()
    recent = await RulePackVersion.find().sort("-version").limit(_cap(versions)).to_list()
    changes = await scan_engine_service.pending_changes()
    return {
        "active": {
            "version": pack.version,
            "changelog": _text(pack.changelog),
            "published_by": pack.published_by,
            "published_at": pack.published_at,
            "retired_rule_ids": pack.retired_rule_ids,
            "custom_rules": [
                {"rule_id": c.rule_id, "language": c.language, "yaml_chars": len(c.yaml)} for c in pack.custom_rules
            ],
        }
        if pack
        else None,
        "recent_versions": [
            {
                "version": v.version,
                "changelog": _text(v.changelog),
                "published_by": v.published_by,
                "published_at": v.published_at,
                "retired_count": len(v.retired_rule_ids),
                "custom_rule_count": len(v.custom_rules),
                "rolled_back_from": v.rolled_back_from,
            }
            for v in recent
        ],
        "pending_changes": changes,
        "has_pending_changes": scan_engine_service.has_changes(changes),
    }


# Scans, findings, vulnerabilities ----------------------------------------------------------------


def _scan_row(s: Scan) -> dict:
    return {
        "id": str(s.id),
        "project_id": s.project_id,
        "scan_type": s.scan_type,
        "triggered_by": s.triggered_by,
        "status": s.status,
        "stage": s.stage,
        "stage_started_at": s.stage_started_at,
        "scanner_version": s.scanner_version,
        "hostname": s.hostname,
        "git_commit": s.git_commit,
        "branch": s.branch,
        "scan_label": s.scan_label,
        "repo_url": redact(s.repo_url) if s.repo_url else None,
        "ci_provider": s.ci_provider,
        "ci_build_id": s.ci_build_id,
        "ci_build_number": s.ci_build_number,
        "ci_build_url": s.ci_build_url,
        "started_at": s.started_at,
        "completed_at": s.completed_at,
        "error_message": _text(s.error_message),
        "rule_pack_version": s.rule_pack_version,
        "suppressed_count": s.suppressed_count,
        "custom_rules_ran": s.custom_rules_ran,
        "retry_count": s.retry_count,
        "max_attempts": s.max_attempts,
        "quota_exempt": s.quota_exempt,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


@_safe_tool
async def list_scans(
    project_id: str | None = None, status: str | None = None, scan_type: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Scans across the portal, newest first. status: pending | queued | running | completed | failed; scan_type: cloud | cicd."""
    criteria: list = []
    if project_id:
        criteria.append(Scan.project_id == project_id)
    if status:
        criteria.append(Scan.status == status)
    if scan_type:
        criteria.append(Scan.scan_type == scan_type)
    q = Scan.find(*criteria)
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {"total": await q.count(), "items": [_scan_row(s) for s in rows]}


@_safe_tool
async def get_scan(id: str) -> dict[str, Any]:
    """One scan: status, stage, error, scanner version, CI fields, rule pack version and severity counts."""
    scan = await _oid_doc(Scan, id, "scan")
    severity = (await project_stats_service.get_severity_by_scan_ids([id])).get(id)
    return {
        **_scan_row(scan),
        "severity": severity.model_dump(mode="json") if severity else None,
        "finding_count": await Finding.find(Finding.scan_id == id).count(),
    }


def _loc(location) -> dict | None:
    return location.model_dump(exclude_none=True) if location else None


@_safe_tool
async def list_findings(
    scan_id: str,
    severity: str | None = None,
    rule: str | None = None,
    include_suppressed: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Raw findings of one scan, highest priority first. Secret findings carry their location only. include_suppressed adds false-positive/retired-rule findings that do not count."""
    await _oid_doc(Scan, scan_id, "scan")
    criteria: list = [Finding.scan_id == scan_id]
    if not include_suppressed:
        criteria.append(NOT_SUPPRESSED)
    if severity:
        criteria.append(Finding.severity == severity)
    if rule:
        criteria.append(Finding.rule_id == rule)
    q = Finding.find(*criteria)
    rows = await q.sort("-priority_score").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "id": str(f.id),
                "scan_id": f.scan_id,
                "project_id": f.project_id,
                "rule_id": f.rule_id,
                "rule_name": f.rule_name,
                "kind": f.kind,
                "severity": f.severity,
                "priority_tier": f.priority_tier,
                # A secret finding's message can quote the value; its rule and location identify it.
                "message": None if f.kind == "secret" else _text(f.message),
                "location": _loc(f.location),
                "suppressed": f.suppressed,
                "suppressed_reason": f.suppressed_reason,
            }
            for f in rows
        ],
    }


@_safe_tool
async def get_finding(id: str) -> dict[str, Any]:
    """One finding with guidance and triage state. A secret finding exposes its masked value only: no snippet, no scanner metadata."""
    f = await _oid_doc(Finding, id, "finding")
    out = scans_router._to_finding_response(f).model_dump(mode="json", exclude_none=True)
    out["message"] = _text(f.message)
    if f.kind == "secret":
        out.pop("evidence", None)
        out.pop("metadata", None)
    else:
        for e in out.get("evidence", []):
            if e.get("snippet"):
                e["snippet"] = redact(e["snippet"])
    vuln = (
        await Vulnerability.find_one(Vulnerability.project_id == f.project_id, Vulnerability.fingerprint == f.fingerprint)
        if f.fingerprint
        else None
    )
    out["triage"] = (
        {
            "vulnerability_id": str(vuln.id),
            "status": vuln.status,
            "resolution_reason": vuln.resolution_reason,
            "review_status": vuln.review.status if vuln.review else None,
        }
        if vuln
        else None
    )
    return _redact_context(out)


@_safe_tool
async def list_vulnerabilities(
    project_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Tracked vulnerabilities (the portal's Vulnerabilities page), most recently seen first. status: open | in_progress | resolved | accepted_risk."""
    criteria: list = []
    if project_id:
        criteria.append(Vulnerability.project_id == project_id)
    if status:
        criteria.append(Vulnerability.status == status)
    if severity:
        criteria.append(Vulnerability.current_severity == severity)
    if rule:
        criteria.append(Vulnerability.current_rule_id == rule)
    q = Vulnerability.find(*criteria)
    rows = await q.sort("-last_seen_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "vulnerability_id": str(v.id),
                "project_id": v.project_id,
                "finding_id": v.latest_finding_id,
                "scan_id": v.current_scan_id,
                "status": v.status,
                "resolution_reason": v.resolution_reason,
                "review_status": v.review.status if v.review else None,
                "rule_id": v.current_rule_id,
                "rule_name": v.current_rule_name,
                "kind": v.current_kind,
                "severity": v.current_severity,
                "message": None if v.current_kind == "secret" else _text(v.current_message),
                "location": _loc(v.current_location),
                "first_seen_at": v.first_seen_at,
                "last_seen_at": v.last_seen_at,
            }
            for v in rows
        ],
    }


@_safe_tool
async def list_finding_reviews(status: str = "pending", limit: int = 50) -> dict[str, Any]:
    """The admin review queue of false-positive / accepted-risk requests. status: pending | accepted | rejected | revoked."""
    if status not in finding_reviews_router._STATUSES:
        raise ToolError(f"status must be one of: {', '.join(finding_reviews_router._STATUSES)}")
    q = Vulnerability.find({"review.status": status})
    rows = await q.sort("-review.requested_at").limit(_cap(limit)).to_list()
    items = [i.model_dump(mode="json") for i in await finding_reviews_router._items(rows)]
    for i in items:
        i["message"] = None if i.get("kind_of_finding") == "secret" else _text(i.get("message"))
    return {
        "total": await q.count(),
        "pending_count": await Vulnerability.find({"review.status": "pending"}).count(),
        "items": _redact_context(items),
    }


# Compliance, auto-fix --------------------------------------------------------------------------


@_safe_tool
async def list_compliance_audits(project_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Compliance audits, newest first, with framework scores and coverage."""
    q = ComplianceAudit.find(ComplianceAudit.project_id == project_id) if project_id else ComplianceAudit.find()
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": _redact_context([compliance_router._to_list_item(a).model_dump(mode="json") for a in rows]),
    }


@_safe_tool
async def get_compliance_audit(id: str) -> dict[str, Any]:
    """One audit with its control verdicts, failing controls first."""
    audit = await _oid_doc(ComplianceAudit, id, "audit")
    out = compliance_router._to_response(audit).model_dump(mode="json")
    order = {"fail": 0, "needs_manual_review": 1}
    out["controls"].sort(key=lambda c: order.get(c.get("status"), 9))
    return _redact_context(out)


@_safe_tool
async def list_fix_proposals(
    project_id: str | None = None,
    scan_id: str | None = None,
    status: str | None = None,
    review_state: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Auto-fix proposals with review state and PR status. Code and diffs are not included."""
    criteria: list = []
    if project_id:
        criteria.append(AIFixProposal.project_id == project_id)
    if scan_id:
        criteria.append(AIFixProposal.scan_id == scan_id)
    if status:
        criteria.append(AIFixProposal.status == status)
    if review_state:
        criteria.append(AIFixProposal.review_state == review_state)
    q = AIFixProposal.find(*criteria)
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "id": str(p.id),
                "project_id": p.project_id,
                "scan_id": p.scan_id,
                "finding_id": p.finding_id,
                "file": p.file_path,
                "status": p.status,
                "review_state": p.review_state,
                "can_fix": p.can_fix,
                "confidence_score": p.confidence_score,
                "patch_scope": p.patch_scope,
                "provider": p.provider,
                "model_name": p.model_name,
                "remediation_job_id": p.remediation_job_id,
                "explanation": _text(p.explanation),
                "risk_notes": _text(p.risk_notes),
                "manual_review_reason": _text(p.manual_review_reason),
                "failure_reason": _text(p.failure_reason),
                "branch_name": p.branch_name,
                "pr_url": p.pr_url,
                "pr_state": p.pr_state,
                "created_at": p.created_at,
            }
            for p in rows
        ],
    }


@_safe_tool
async def list_remediation_jobs(
    project_id: str | None = None, status: str | None = None, kind: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Auto-fix jobs (propose / apply), newest first. status: queued | running | completed | failed; kind: propose | apply."""
    criteria: list = []
    if project_id:
        criteria.append(RemediationJob.project_id == project_id)
    if status:
        criteria.append(RemediationJob.status == status)
    if kind:
        criteria.append(RemediationJob.kind == kind)
    q = RemediationJob.find(*criteria)
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "id": str(j.id),
                "kind": j.kind,
                "project_id": j.project_id,
                "scan_id": j.scan_id,
                "status": j.status,
                "stage": j.stage,
                "progress_completed": j.progress_completed,
                "progress_total": j.progress_total,
                "quota_skipped": j.quota_skipped,
                "skipped_existing": j.skipped_existing,
                "proposal_count": len(j.proposal_ids),
                "provider": j.provider,
                "model_name": j.model_name,
                "retry_count": j.retry_count,
                "leftover_branch": j.leftover_branch,
                "trace_id": j.trace_id,
                "started_at": j.started_at,
                "completed_at": j.completed_at,
                "created_at": j.created_at,
                "error_message": _text(j.error_message),
            }
            for j in rows
        ],
    }


# AI usage and budgets ----------------------------------------------------------------------------


@_safe_tool
async def get_ai_usage(project_id: str | None = None, days: int = 30) -> dict[str, Any]:
    """AI usage analytics (calls, tokens, cost, errors, latency by feature), portal-wide or for one project."""
    days = max(1, min(days, 365))
    return {
        "project_id": project_id,
        "days": days,
        "analytics": await ai_analytics_service.get_analytics(project_id=project_id, days=days),
    }


@_safe_tool
async def get_ai_budgets(limit: int = 50) -> dict[str, Any]:
    """Projects that have an AI budget, with month-to-date spend, limits and hard-stop state."""
    projects = await Project.find().sort("-created_at").to_list()
    items = []
    for p in projects:
        if p.ai_budget_usd_monthly is None and p.ai_budget_tokens_monthly is None:
            continue
        usage = await ai_budget_service.month_to_date(str(p.id))
        items.append(
            {
                "project_id": str(p.id),
                "project_name": p.name,
                "limit_usd_monthly": p.ai_budget_usd_monthly,
                "limit_tokens_monthly": p.ai_budget_tokens_monthly,
                "alert_percent": p.ai_budget_alert_percent,
                "hard_stop": p.ai_budget_hard_stop,
                "alerts_sent": p.ai_budget_alerts_sent,
                "month_to_date": usage,
                "hard_stop_reason": await ai_budget_service.hard_stop_reason(str(p.id)),
            }
        )
    return {"items": items[: _cap(limit)], "total": len(items)}


# People, channels, config ------------------------------------------------------------------------


@_safe_tool
async def list_users(role: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Portal users: role, active flag, approval status, sign-in times. role: admin | user; status: approved | pending | rejected. No credentials."""
    criteria: list = []
    if role:
        criteria.append(User.role == role)
    if status:
        criteria.append(User.approval_status == status)
    q = User.find(*criteria)
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "is_active": u.is_active,
                "approval_status": u.approval_status,
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
                "last_seen_at": u.last_seen_at,
            }
            for u in rows
        ],
    }


@_safe_tool
async def list_webhook_channels(limit: int = 50) -> dict[str, Any]:
    """Teams webhook channels: name, host only (never the URL), subscribed events, project scope, last delivery status."""
    rows = await WebhookChannel.find().sort("name").limit(_cap(limit)).to_list()
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "enabled": c.enabled,
                "host": alert_service.host_of(c.url_enc),
                "events": c.events,
                "project_ids": c.project_ids,
                "include_digest": c.include_digest,
                "migrated_from_workspace": c.migrated_from_workspace,
                "last_delivery_at": c.last_delivery_at,
                "last_status": c.last_status,
                "last_error": _text(c.last_error),
            }
            for c in rows
        ]
    }


@_safe_tool
async def get_digest_status() -> dict[str, Any]:
    """Digest schedule, scope and the outcome of the last send."""
    d = await digest_service.get_settings()
    return {
        "enabled": d.enabled,
        "frequency": d.frequency,
        "time_utc": f"{d.hour_utc:02d}:{d.minute_utc:02d}",
        "weekday": d.weekday,
        "project_ids": d.project_ids,
        "include_stale_projects": d.include_stale_projects,
        "last_sent_for": d.last_sent_for,
        "last_sent_at": d.last_sent_at,
        "last_status": d.last_status,
        "last_error": _text(d.last_error),
        "digest_channels": await WebhookChannel.find(WebhookChannel.include_digest == True).count(),  # noqa: E712
    }


@_safe_tool
async def get_live_alert_status() -> dict[str, Any]:
    """Live dependency advisory watcher: enabled, last run, per-ecosystem lag, failures, coverage, recent alerts."""
    return _redact_context((await live_alert_service.status()).model_dump(mode="json"))


@_safe_tool
async def get_project(id: str) -> dict[str, Any]:
    """One project's full configuration, its overrides, and the effective (workspace-resolved) policies."""
    p = await _oid_doc(Project, id, "project")
    return {
        "id": str(p.id),
        "name": p.name,
        "description": _text(p.description),
        "owner_id": p.owner_id,
        "is_archived": p.is_archived,
        "member_count": await ProjectMember.find(ProjectMember.project_id == id).count(),
        "scan_count": p.scan_count,
        "last_scan_at": p.last_scan_at,
        "total_findings": p.total_findings,
        "finding_severity_counts": p.finding_severity_counts,
        "cicd_fail_on": p.cicd_fail_on,
        "report_template": p.report_template,
        "cloud_scan_monthly_limit": p.cloud_scan_monthly_limit,
        "overrides": {
            "scan_enable_secrets": p.scan_enable_secrets,
            "scan_enable_sca": p.scan_enable_sca,
            "scan_enable_framework_checks": p.scan_enable_framework_checks,
            "compliance_frameworks": p.compliance_frameworks,
            "compliance_audit_scope": p.compliance_audit_scope,
            "compliance_auto_audit_on_scan": p.compliance_auto_audit_on_scan,
            "compliance_evidence_retention_days": p.compliance_evidence_retention_days,
            "auto_fix_enabled": p.auto_fix_enabled,
            "auto_fix_confidence_threshold": p.auto_fix_confidence_threshold,
            "live_alert_min_severity": p.live_alert_min_severity,
        },
        "ai_budget": {
            "usd_monthly": p.ai_budget_usd_monthly,
            "tokens_monthly": p.ai_budget_tokens_monthly,
            "alert_percent": p.ai_budget_alert_percent,
            "hard_stop": p.ai_budget_hard_stop,
        },
        "alerts": {
            "webhook_configured": bool(p.alert_webhook_enc),
            "webhook_host": alert_service.host_of(p.alert_webhook_enc),
            "webhook_enabled": p.alert_webhook_enabled,
            "email_enabled": p.alert_email_enabled,
            "email_count": len(p.alert_emails),
            "triggers": p.alert_triggers,
        },
        "effective": {
            "scan_options": _plain(await workspace_settings_service.effective_scan_options(p)),
            "compliance": _plain(await workspace_settings_service.effective_compliance_policy(p)),
            "remediation": _plain(await workspace_settings_service.effective_remediation_policy(p)),
            "live_alerts": _plain(await workspace_settings_service.effective_live_alert_policy(p)),
        },
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


@_safe_tool
async def list_api_keys(project_id: str, limit: int = 50) -> dict[str, Any]:
    """A project's scanner API keys: label, prefix, scope, created, expiry, revoked, last used. Never the key or its hash."""
    q = ApiKey.find(ApiKey.project_id == project_id)
    rows = await q.sort("-created_at").limit(_cap(limit)).to_list()
    return {
        "total": await q.count(),
        "items": [
            {
                "id": str(k.id),
                "label": k.label,
                "prefix": k.prefix,
                "scope": k.scope,
                "created_by": k.created_by,
                "created_at": k.created_at,
                "expires_at": k.expires_at,
                "revoked_at": k.revoked_at,
                "last_used_at": k.last_used_at,
                "last_used_ip": k.last_used_ip,
            }
            for k in rows
        ],
    }


NEW_TOOLS = [
    list_scan_rules, list_noisy_rules, get_scan_rule, get_rule_pack, list_scans, get_scan, list_findings,
    get_finding, list_vulnerabilities, list_finding_reviews, list_compliance_audits, get_compliance_audit,
    list_fix_proposals, list_remediation_jobs, get_ai_usage, get_ai_budgets, list_users,
    list_webhook_channels, get_digest_status, get_live_alert_status, get_project, list_api_keys,
]


TOOLS = [
    get_system_health, get_operations_overview, get_scanner_status, list_system_logs, get_system_log,
    summarize_errors, trace_request, list_audit_logs, inspect_job, list_failed_jobs, get_ai_health,
    get_runtime_config, get_data_stats, list_projects, lookup_user,
    *NEW_TOOLS,
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
