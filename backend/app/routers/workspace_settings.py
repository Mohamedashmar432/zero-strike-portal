"""Workspace defaults (portal admin) and per-project policy overrides (project owner).

Two routers, deliberately split by principal:

- `router` — /workspace-settings, portal admin only for writes. Any signed-in user may read
  it, because a project owner cannot decide what to override without seeing what they are
  inheriting from.
- `project_router` — /projects/{id}/policy, readable by any member, writable by the project
  owner (or a portal admin). The tighten-only rule lives in workspace_settings_service, not
  here, so it holds for every reader of the resolved policy and not just for this endpoint.
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, require_admin
from app.models.project import Project
from app.models.user import User
from app.models.workspace_settings import WorkspaceSettings
from app.schemas.workspace_settings import (
    ProjectPolicyResponse,
    ProjectPolicyUpdateRequest,
    WorkspaceSettingsResponse,
    WorkspaceSettingsUpdateRequest,
)
from app.services import audit_service, project_service, workspace_settings_service

router = APIRouter(prefix="/workspace-settings", tags=["workspace-settings"])
project_router = APIRouter(tags=["workspace-settings"])


def _to_response(ws: WorkspaceSettings) -> WorkspaceSettingsResponse:
    return WorkspaceSettingsResponse(
        default_report_template=ws.default_report_template,
        project_byok_enabled=ws.project_byok_enabled,
        scan_enable_secrets=ws.scan_enable_secrets,
        scan_enable_sca=ws.scan_enable_sca,
        scan_enable_framework_checks=ws.scan_enable_framework_checks,
        compliance_frameworks=ws.compliance_frameworks,
        compliance_audit_scope=ws.compliance_audit_scope,
        compliance_audit_ai_narrative=ws.compliance_audit_ai_narrative,
        compliance_auto_audit_on_scan=ws.compliance_auto_audit_on_scan,
        compliance_evidence_retention_days=ws.compliance_evidence_retention_days,
    )


@router.get("", response_model=WorkspaceSettingsResponse)
async def get_workspace_settings(user: User = Depends(get_current_user)):
    """Readable by any signed-in user — a project owner needs to see what they inherit."""
    return _to_response(await workspace_settings_service.get_workspace_settings())


@router.put("", response_model=WorkspaceSettingsResponse)
async def update_workspace_settings(
    payload: WorkspaceSettingsUpdateRequest, user: User = Depends(require_admin)
):
    changed = payload.model_dump(exclude_unset=True)
    ws = await workspace_settings_service.update_workspace_settings(
        updated_by=str(user.id), **changed
    )
    await audit_service.record(
        "Workspace Settings Updated",
        actor_user_id=str(user.id),
        target_type="workspace_settings",
        metadata=changed,
    )
    return _to_response(ws)


async def _policy_response(project: Project, *, can_manage: bool) -> ProjectPolicyResponse:
    scan = await workspace_settings_service.effective_scan_options(project)
    compliance = await workspace_settings_service.effective_compliance_policy(project)
    remediation = await workspace_settings_service.effective_remediation_policy(project)
    workspace_remediation = await workspace_settings_service.effective_remediation_policy(None)
    template = await workspace_settings_service.effective_report_template(project)
    return ProjectPolicyResponse(
        scan_enable_secrets=project.scan_enable_secrets,
        scan_enable_sca=project.scan_enable_sca,
        scan_enable_framework_checks=project.scan_enable_framework_checks,
        compliance_frameworks=project.compliance_frameworks,
        compliance_audit_scope=project.compliance_audit_scope,
        compliance_auto_audit_on_scan=project.compliance_auto_audit_on_scan,
        compliance_evidence_retention_days=project.compliance_evidence_retention_days,
        auto_fix_enabled=project.auto_fix_enabled,
        auto_fix_confidence_threshold=project.auto_fix_confidence_threshold,
        report_template=project.report_template,
        effective_scan_enable_secrets=scan.enable_secrets,
        effective_scan_enable_sca=scan.enable_sca,
        effective_scan_enable_framework_checks=scan.enable_framework_checks,
        effective_compliance_frameworks=compliance.frameworks,
        effective_compliance_audit_scope=compliance.audit_scope,
        effective_compliance_audit_ai_narrative=compliance.audit_ai_narrative,
        effective_compliance_auto_audit_on_scan=compliance.auto_audit_on_scan,
        effective_compliance_evidence_retention_days=compliance.evidence_retention_days,
        effective_auto_fix_enabled=remediation.enabled,
        effective_auto_fix_confidence_threshold=remediation.confidence_threshold,
        effective_report_template=template,
        workspace_auto_fix_enabled=workspace_remediation.enabled,
        workspace_auto_fix_confidence_threshold=workspace_remediation.confidence_threshold,
        can_manage=can_manage,
    )


@project_router.get("/projects/{project_id}/policy", response_model=ProjectPolicyResponse)
async def get_project_policy(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)
    return await _policy_response(project, can_manage=role in ("owner", "admin"))


@project_router.put("/projects/{project_id}/policy", response_model=ProjectPolicyResponse)
async def update_project_policy(
    project_id: str, payload: ProjectPolicyUpdateRequest, user: User = Depends(get_current_user)
):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)

    # exclude_unset, not exclude_none: an explicit null here means "stop overriding, go back
    # to inheriting", which is a real edit and must not be dropped as if it were absent.
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(project, field, value)
    await project.save()

    await audit_service.record(
        "Project Policy Updated",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="project_policy",
        target_id=project_id,
        metadata=changed,
    )
    return await _policy_response(project, can_manage=True)
