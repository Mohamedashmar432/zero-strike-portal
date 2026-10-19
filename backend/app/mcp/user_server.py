"""User MCP server at /mcp/user (docs/USER_MCP_OAUTH.md): read-only, membership-scoped tools behind
an OAuth access token. A principal type distinct from the admin `tsmcp_` token and from the JWT
user — each endpoint refuses the others' credentials.

Auth wrapper + OAuth routes live here; tools reuse the portal routers' own response shaping so a
user sees through MCP what the portal already shows them, never more.
"""

import functools
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from beanie import PydanticObjectId
from beanie.operators import In
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import rate_limit
from app.core.config import settings
from app.mcp.server import _cap, _clip, _jsonable
from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.compliance_audit import ComplianceAudit
from app.models.finding import NOT_SUPPRESSED, Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.routers import ai_analysis as ai_analysis_router
from app.routers import compliance as compliance_router
from app.routers import scans as scans_router
from app.schemas.dashboard import SeverityCounts
from app.services import (
    ai_analysis_service,
    audit_service,
    mcp_oauth_service,
    project_repo_service,
    project_service,
    project_stats_service,
    scan_engine_service,
    vulnerability_service,
)
from app.services.mcp_oauth_service import ACCESS_PREFIX, SCOPE, provider
from app.services.secret_redaction import redact

MAX_TEXT = 2_000
_CONTROL_ORDER = {"fail": 0, "partial": 1, "needs_manual_review": 2, "pass": 3, "not_applicable": 4}
REGISTER_LIMIT = (10, 3600)  # registrations per IP per hour
# /authorize is unauthenticated and writes a pending request per call; a real client makes a handful.
AUTHORIZE_LIMIT = (30, 600)


@dataclass(frozen=True)
class UserPrincipal:
    user: User
    client_id: str
    grant_id: str


current_user: ContextVar[UserPrincipal | None] = ContextVar("mcp_user_principal", default=None)
# The project a tool call resolved to, set only after membership was confirmed — so a non-member's
# probe is never written into someone else's project audit trail.
_audited_project: ContextVar[str | None] = ContextVar("mcp_user_audited_project", default=None)


# --- auth wrapper ------------------------------------------------------------------------------


class UserMcpAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        scheme, _, raw = request.headers.get("authorization", "").partition(" ")
        raw = raw.strip()
        if scheme.lower() != "bearer" or not raw:
            await self._refuse(scope, receive, send, 401, None, "Authentication required")
            return
        # The prefix check turns away admin tsmcp_ tokens and JWTs before any lookup.
        token = await provider.load_access_token(raw) if raw.startswith(ACCESS_PREFIX) else None
        if token is None or not mcp_oauth_service.same_resource(token.resource):
            await self._refuse(scope, receive, send, 401, "invalid_token", "Invalid or expired access token")
            return
        if SCOPE not in token.scopes:
            await self._refuse(scope, receive, send, 403, "insufficient_scope", f"Required scope: {SCOPE}")
            return
        user = await User.get(token.subject) if token.subject and PydanticObjectId.is_valid(token.subject) else None
        # Re-checked on every request: deactivating the account ends MCP access at once.
        if not user or not user.is_active or user.approval_status != "approved":
            if user:
                await audit_service.record(
                    "MCP app access denied",
                    actor_user_id=str(user.id),
                    target_type="mcp_app",
                    target_id=token.client_id,
                    metadata={"reason": "account inactive or not approved", "grant_id": token.claims["grant_id"]},
                )
            await self._refuse(scope, receive, send, 403, "access_denied", "Account is not active")
            return
        reset = current_user.set(UserPrincipal(user, token.client_id, token.claims["grant_id"]))
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(reset)

    @staticmethod
    async def _refuse(
        scope: Scope, receive: Receive, send: Send, status: int, error: str | None, detail: str
    ) -> None:
        parts = ([f'error="{error}"'] if error else []) + [
            f'resource_metadata="{mcp_oauth_service.resource_metadata_url()}"'
        ]
        await JSONResponse(
            {"error": error or "invalid_request", "error_description": detail},
            status_code=status,
            headers={"WWW-Authenticate": "Bearer " + ", ".join(parts)},
        )(scope, receive, send)


class _RateLimited:
    """Per-IP limit on a raw ASGI endpoint — used on the SDK's open /register and /authorize."""

    def __init__(self, app: ASGIApp, name: str, limit: tuple[int, int]):
        self.app, self.name, self.limit = app, name, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            ip = rate_limit.client_ip(Request(scope))
            if not rate_limit.limiter.check(f"{self.name}:{ip}", *self.limit):
                await JSONResponse(
                    {"error": "temporarily_unavailable", "error_description": "Too many requests"},
                    status_code=429,
                    headers={"Retry-After": str(self.limit[1])},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def oauth_routes() -> list[Route]:
    """Discovery documents + /register /authorize /token /revoke, built by the SDK over our provider."""
    # AuthSettings keeps a path-less origin as written (no trailing slash), which RFC 8414's exact
    # issuer comparison needs; a bare AnyHttpUrl would append one.
    urls = AuthSettings(
        issuer_url=settings.backend_public_url.rstrip("/"),
        resource_server_url=mcp_oauth_service.resource_url(),
        validate_token_resource=False,
    )
    issuer = urls.issuer_url
    routes = create_auth_routes(
        provider,
        issuer_url=issuer,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    routes += create_protected_resource_routes(
        resource_url=urls.resource_server_url,
        authorization_servers=[issuer],
        scopes_supported=[SCOPE],
        resource_name="thinkShield portal",
    )
    for route in routes:
        if route.path == "/register":
            route.app = _RateLimited(route.app, "mcp-register", REGISTER_LIMIT)
        elif route.path == "/authorize":
            route.app = _RateLimited(route.app, "mcp-authorize", AUTHORIZE_LIMIT)
    return routes


# --- tool plumbing -----------------------------------------------------------------------------


def _user() -> User:
    principal = current_user.get()
    if principal is None:
        raise PermissionError("Not authenticated")
    return principal.user


def _text(value: str | None) -> str | None:
    return _clip(value, MAX_TEXT)


def _tool(fn):
    """Run the call, then audit it (fails closed: if the audit write fails there is no output).
    The row carries the project only once membership was confirmed."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        principal = current_user.get()
        if principal is None:
            raise PermissionError("Not authenticated")
        reset = _audited_project.set(None)
        outcome = "ok"
        try:
            return _jsonable(await fn(*args, **kwargs))
        except ToolError:
            outcome = "refused"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            arguments = {k: (v[:200] if isinstance(v, str) else v) for k, v in kwargs.items() if v is not None}
            await audit_service.record(
                "MCP tool called",
                actor_user_id=str(principal.user.id),
                project_id=_audited_project.get(),
                target_type="mcp_tool",
                target_id=fn.__name__,
                metadata={
                    "tool": fn.__name__,
                    "arguments": arguments,
                    "outcome": outcome,
                    "client_id": principal.client_id,
                    "grant_id": principal.grant_id,
                },
            )
            _audited_project.reset(reset)

    return wrapper


async def _project(project_id: str) -> Project:
    """The project if the caller may see it; a non-member and a missing id get the same error."""
    project = (
        await Project.get(project_id) if project_id and PydanticObjectId.is_valid(project_id) else None
    )
    if project is None or await project_service.role_in_project(project_id, _user()) is None:
        raise ToolError("Project not found")
    _audited_project.set(project_id)
    return project


async def _scan(scan_id: str) -> Scan:
    scan = await Scan.get(scan_id) if scan_id and PydanticObjectId.is_valid(scan_id) else None
    if scan is None or await project_service.role_in_project(scan.project_id, _user()) is None:
        raise ToolError("Scan not found")
    _audited_project.set(scan.project_id)
    return scan


async def _finding(finding_id: str) -> Finding:
    finding = await Finding.get(finding_id) if finding_id and PydanticObjectId.is_valid(finding_id) else None
    if finding is None or await project_service.role_in_project(finding.project_id, _user()) is None:
        raise ToolError("Finding not found")
    _audited_project.set(finding.project_id)
    return finding


async def _audit_record(audit_id: str) -> ComplianceAudit:
    audit = await ComplianceAudit.get(audit_id) if audit_id and PydanticObjectId.is_valid(audit_id) else None
    if audit is None or await project_service.role_in_project(audit.project_id, _user()) is None:
        raise ToolError("Compliance audit not found")
    _audited_project.set(audit.project_id)
    return audit


def _loc(location) -> dict | None:
    return location.model_dump(exclude_none=True) if location else None


async def _member_project_ids(user: User) -> dict[str, str]:
    """{project_id: role} for every project the caller can see."""
    if user.role == "admin":
        return {str(p.id): "admin" for p in await Project.find_all().to_list()}
    return {m.project_id: m.role for m in await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()}


def _scan_dict(scan: Scan, severity: SeverityCounts | None, ai=None) -> dict:
    return scans_router._to_response(scan, ai, severity).model_dump(mode="json", exclude_none=True)


# --- tools -------------------------------------------------------------------------------------


@_tool
async def list_my_projects(limit: int = 50) -> dict[str, Any]:
    """Projects I can see: id, name, my role, last scan status/time, open findings by severity."""
    user = _user()
    roles = await _member_project_ids(user)
    ids = list(roles)[: _cap(limit)]
    oids = [PydanticObjectId(i) for i in ids]
    projects = await Project.find(In(Project.id, oids)).to_list() if oids else []
    stats = await project_stats_service.get_projects_stats(user, ids) if ids else {}
    items = []
    for p in projects:
        pid = str(p.id)
        last = await Scan.find(Scan.project_id == pid).sort("-created_at").first_or_none()
        item = stats.get(pid)
        items.append(
            {
                "id": pid,
                "name": p.name,
                "my_role": roles[pid],
                "is_archived": p.is_archived,
                "last_scan": {"id": str(last.id), "status": last.status, "created_at": last.created_at}
                if last
                else None,
                "open_findings_by_severity": item.current_findings_by_severity.model_dump() if item else {},
            }
        )
    return {"items": items, "total": len(roles)}


@_tool
async def get_project_overview(project_id: str) -> dict[str, Any]:
    """One project's posture: current severity counts, trend over the last scans, connected repos."""
    project = await _project(project_id)
    user = _user()
    item = (await project_stats_service.get_projects_stats(user, [project_id])).get(project_id)
    recent = (
        await Scan.find(Scan.project_id == project_id, Scan.status == "completed")
        .sort("-created_at")
        .limit(10)
        .to_list()
    )
    by_scan = await project_stats_service.get_severity_by_scan_ids([str(s.id) for s in recent])
    repos = await project_repo_service.list_repos(project_id)
    return {
        "id": project_id,
        "name": project.name,
        "description": _text(project.description),
        "is_archived": project.is_archived,
        "my_role": await project_service.role_in_project(project_id, user),
        "open_findings_by_severity": item.current_findings_by_severity.model_dump() if item else {},
        "scan_status_counts": item.scan_status_counts.model_dump() if item else {},
        "scan_count": project.scan_count,
        "last_scan_at": project.last_scan_at,
        "trend": [
            {
                "scan_id": str(s.id),
                "created_at": s.created_at,
                "branch": s.branch,
                "findings_by_severity": by_scan.get(str(s.id), SeverityCounts()).model_dump(),
            }
            for s in reversed(recent)
        ],
        "repos": [
            {"id": str(r.id), "provider": r.provider, "name": r.repo_full_name, "branch": r.selected_branch, "label": r.label}
            for r in repos
        ],
    }


@_tool
async def list_scans(
    project_id: str, status: str | None = None, scan_type: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Scans for a project, newest first. Filter by status (queued/running/completed/failed/...) or scan_type (cloud/cicd)."""
    await _project(project_id)
    criteria = [Scan.project_id == project_id]
    if status:
        criteria.append(Scan.status == status)
    if scan_type:
        criteria.append(Scan.scan_type == scan_type)
    query = Scan.find(*criteria)
    scans = await query.sort("-created_at").limit(_cap(limit)).to_list()
    severity = await project_stats_service.get_severity_by_scan_ids([str(s.id) for s in scans])
    return {"items": [_scan_dict(s, severity.get(str(s.id))) for s in scans], "total": await query.count()}


@_tool
async def get_scan(scan_id: str) -> dict[str, Any]:
    """One scan: status, error message, timing and the finding summary by severity."""
    scan = await _scan(scan_id)
    ai = await ai_analysis_service.latest_scan_ai_status([scan_id])
    severity = await project_stats_service.get_severity_by_scan_ids([scan_id])
    return _scan_dict(scan, severity.get(scan_id), ai.get(scan_id))


def _finding_row(f: Finding) -> dict:
    return {
        "id": str(f.id),
        "scan_id": f.scan_id,
        "rule_id": f.rule_id,
        "rule_name": f.rule_name,
        "kind": f.kind,
        "severity": f.severity,
        "priority_tier": f.priority_tier,
        "message": _text(f.message),
        "location": _loc(f.location),
    }


def _vulnerability_row(v: Vulnerability) -> dict:
    return {
        "vulnerability_id": str(v.id),
        "finding_id": v.latest_finding_id,
        "scan_id": v.current_scan_id,
        "status": v.status,
        "fix_status": vulnerability_service.derive_fix_status(v.status, v.resolution_reason, v.reopened_at),
        "rule_id": v.current_rule_id,
        "rule_name": v.current_rule_name,
        "kind": v.current_kind,
        "severity": v.current_severity,
        "priority_tier": v.current_priority_tier,
        "message": _text(v.current_message),
        "location": _loc(v.current_location),
        "first_seen_at": v.first_seen_at,
        "last_seen_at": v.last_seen_at,
    }


@_tool
async def list_findings(
    project_id: str | None = None,
    scan_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule: str | None = None,
    file: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Findings for a scan (that scan's raw findings) or a project (its tracked vulnerabilities, as the portal's Vulnerabilities page lists them). Give exactly one of scan_id / project_id. Filters: severity, rule (rule id), file (path substring); status (open/in_progress/resolved/accepted_risk) applies to project listings only."""
    if bool(project_id) == bool(scan_id):
        raise ToolError("Provide exactly one of project_id or scan_id")
    if scan_id:
        if status:
            raise ToolError("status filters tracked vulnerabilities; use project_id")
        scan = await _scan(scan_id)
        criteria: list = [Finding.scan_id == scan_id, NOT_SUPPRESSED]
        if severity:
            criteria.append(Finding.severity == severity)
        if rule:
            criteria.append(Finding.rule_id == rule)
        if file:
            criteria.append({"location.file": {"$regex": re.escape(file), "$options": "i"}})
        query = Finding.find(*criteria)
        rows = await query.limit(_cap(limit)).to_list()
        return {"project_id": scan.project_id, "items": [_finding_row(f) for f in rows], "total": await query.count()}
    await _project(project_id)
    criteria = [Vulnerability.project_id == project_id]
    retired = await scan_engine_service.retired_rule_ids()  # same exclusion as the portal's list
    if retired:
        criteria.append({"current_rule_id": {"$nin": sorted(retired)}})
    if status:
        criteria.append(Vulnerability.status == status)
    if severity:
        criteria.append(Vulnerability.current_severity == severity)
    if rule:
        criteria.append(Vulnerability.current_rule_id == rule)
    if file:
        criteria.append({"current_location.file": {"$regex": re.escape(file), "$options": "i"}})
    query = Vulnerability.find(*criteria)
    rows = await query.sort("-last_seen_at").limit(_cap(limit)).to_list()
    return {"project_id": project_id, "items": [_vulnerability_row(v) for v in rows], "total": await query.count()}


@_tool
async def get_finding(finding_id: str) -> dict[str, Any]:
    """One finding: location, description, remediation guidance, triage status and any AI insight."""
    f = await _finding(finding_id)
    out = scans_router._to_finding_response(f).model_dump(mode="json", exclude_none=True)
    out["message"] = _text(f.message)
    if f.kind == "secret":
        # The vulnerabilities page shows a secret finding's rule and location, never its content.
        # Keep the masked value only: no source snippets, no scanner metadata.
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
        {"vulnerability_id": str(vuln.id), "status": vuln.status, "resolution_reason": vuln.resolution_reason}
        if vuln
        else None
    )
    insight = (
        await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == f.fingerprint, AIFindingInsight.project_id == f.project_id
        )
        if f.fingerprint
        else None
    )
    out["ai_insight"] = (
        ai_analysis_router._to_finding_insight(insight).model_dump(mode="json", exclude_none=True)
        if insight
        else None
    )
    return out


@_tool
async def list_compliance_audits(project_id: str, limit: int = 20) -> dict[str, Any]:
    """Compliance audits for a project, newest first, with framework scores and coverage."""
    await _project(project_id)
    query = ComplianceAudit.find(ComplianceAudit.project_id == project_id)
    audits = await query.sort(-ComplianceAudit.created_at).limit(_cap(limit)).to_list()
    return {
        "items": [compliance_router._to_list_item(a).model_dump(mode="json") for a in audits],
        "total": await query.count(),
    }


@_tool
async def get_compliance_audit(audit_id: str) -> dict[str, Any]:
    """One audit with its control verdicts, failing controls first."""
    audit = await _audit_record(audit_id)
    out = compliance_router._to_response(audit).model_dump(mode="json")
    out["controls"].sort(key=lambda c: _CONTROL_ORDER.get(c["status"], 9))
    return out


@_tool
async def list_fix_proposals(scan_id: str, limit: int = 50) -> dict[str, Any]:
    """Auto-fix proposals for a scan with review state and pull request status. Code and diffs are not included; open the PR for those."""
    await _scan(scan_id)
    query = AIFixProposal.find(AIFixProposal.scan_id == scan_id)
    proposals = await query.sort("-created_at").limit(_cap(limit)).to_list()
    oids = [PydanticObjectId(p.finding_id) for p in proposals if PydanticObjectId.is_valid(p.finding_id)]
    findings = {str(f.id): f for f in await Finding.find(In(Finding.id, oids)).to_list()} if oids else {}
    items = []
    for p in proposals:
        f = findings.get(p.finding_id)
        items.append(
            {
                "id": str(p.id),
                "finding_id": p.finding_id,
                "rule_name": f.rule_name if f else None,
                "severity": f.severity if f else None,
                "file": f.location.file if f else p.file_path,
                "start_line": f.location.start_line if f else None,
                "status": p.status,
                "review_state": p.review_state,
                "can_fix": p.can_fix,
                "confidence_score": p.confidence_score,
                "patch_scope": p.patch_scope,
                "explanation": _text(p.explanation),
                "risk_notes": _text(p.risk_notes),
                "manual_review_reason": _text(p.manual_review_reason),
                "failure_reason": _text(p.failure_reason),
                "branch_name": p.branch_name,
                "pr_url": p.pr_url,
                "pr_number": p.pr_number,
                "pr_state": p.pr_state,
                "pr_merged_at": p.pr_merged_at,
            }
        )
    return {"items": items, "total": await query.count()}


TOOLS = [
    list_my_projects, get_project_overview, list_scans, get_scan, list_findings, get_finding,
    list_compliance_audits, get_compliance_audit, list_fix_proposals,
]


def build() -> tuple[UserMcpAuthMiddleware, MCPServer]:
    """A fresh server and its auth-wrapped ASGI app, mounted at /mcp/user by main.create_app."""
    server = MCPServer("thinkshield-portal-user")
    for fn in TOOLS:
        server.add_tool(fn, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    inner = server.streamable_http_app(
        streamable_http_path="/mcp/user",
        stateless_http=True,
        json_response=True,
        # The bearer token is the gate; the localhost-only Host allow-list would 421 real hostnames.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return UserMcpAuthMiddleware(inner), server

