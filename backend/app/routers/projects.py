from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.user import User
from app.schemas.common import Page
from app.schemas.project import (
    OwaspSummaryResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectStatsItem,
    ProjectStatsResponse,
    ProjectUpdateRequest,
    ScanHistoryItem,
)
from app.schemas.project_member import MemberInviteRequest, MemberResponse, MemberRoleUpdateRequest
from app.schemas.project_repo import (
    ProjectRepoCreateRequest,
    ProjectRepoReauthRequest,
    ProjectRepoResponse,
    ProjectRepoUpdateRequest,
)
from app.services import audit_service, project_repo_service, project_service, project_stats_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_project_response(
    project: Project, my_role: str, stats: ProjectStatsItem | None = None
) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        is_archived=project.is_archived,
        scan_count=project.scan_count,
        last_scan_at=project.last_scan_at,
        report_template=project.report_template,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,
        total_findings=stats.total_findings if stats else None,
        findings_by_severity=stats.findings_by_severity if stats else None,
        scan_status_counts=stats.scan_status_counts if stats else None,
        risk_repo_count=stats.risk_repo_count if stats else None,
        total_repo_count=stats.total_repo_count if stats else None,
    )


def _to_project_repo_response(repo: ProjectRepo) -> ProjectRepoResponse:
    return ProjectRepoResponse(
        id=str(repo.id),
        project_id=repo.project_id,
        provider=repo.provider,
        organization=repo.organization,
        ado_project=repo.ado_project,
        repo_full_name=repo.repo_full_name,
        clone_url=repo.clone_url,
        selected_branch=repo.selected_branch,
        label=repo.label,
        created_at=repo.created_at,
    )


def _to_member_response(member: ProjectMember, name: str | None) -> MemberResponse:
    return MemberResponse(
        id=str(member.id),
        project_id=member.project_id,
        user_id=member.user_id,
        invited_email=member.invited_email,
        name=name,
        role=member.role,
        status="accepted" if member.accepted_at else "pending",
        invited_by=member.invited_by,
        invited_at=member.invited_at,
        accepted_at=member.accepted_at,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreateRequest, user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    project = Project(
        name=payload.name,
        description=payload.description,
        owner_id=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await project.insert()
    await ProjectMember(
        project_id=str(project.id),
        user_id=str(user.id),
        invited_email=user.email,
        role="owner",
        invited_by=str(user.id),
        invited_at=now,
        accepted_at=now,
    ).insert()
    await audit_service.record(
        "Project Created", actor_user_id=str(user.id), project_id=str(project.id), metadata={"name": project.name}
    )
    return _to_project_response(project, "owner")


@router.get("", response_model=Page)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    if user.role == "admin":
        total = await Project.count()
        projects = await Project.find_all().skip((page - 1) * page_size).limit(page_size).to_list()
        items = [_to_project_response(p, "admin") for p in projects]
        return Page(items=items, total=total, page=page, page_size=page_size)

    memberships = await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()
    role_by_project = {m.project_id: m.role for m in memberships}
    total = len(role_by_project)
    project_ids = list(role_by_project.keys())[(page - 1) * page_size : (page - 1) * page_size + page_size]
    object_ids = [PydanticObjectId(pid) for pid in project_ids]
    projects = await Project.find(In(Project.id, object_ids)).to_list() if object_ids else []
    items = [_to_project_response(p, role_by_project[str(p.id)]) for p in projects]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=ProjectStatsResponse)
async def get_projects_stats(
    project_ids: list[str] | None = Query(None), user: User = Depends(get_current_user)
):
    # Registered before GET /{project_id} — FastAPI matches same-segment-count routes in
    # registration order, so this would otherwise be swallowed by /{project_id} with
    # project_id="stats" and 404 on the ObjectId parse.
    return ProjectStatsResponse(items=await project_stats_service.get_projects_stats(user, project_ids))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)
    stats = await project_stats_service.get_projects_stats(user, [project_id])
    return _to_project_response(project, role, stats.get(project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, payload: ProjectUpdateRequest, user: User = Depends(get_current_user)
):
    project = await project_service.get_project_or_404(project_id)
    role = await project_service.require_owner_or_admin(project_id, user)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.is_archived is not None:
        project.is_archived = payload.is_archived
    if payload.report_template is not None:
        project.report_template = None if payload.report_template == "inherit" else payload.report_template
    project.updated_at = datetime.now(timezone.utc)
    await project.save()
    await audit_service.record(
        "Project Updated", actor_user_id=str(user.id), project_id=project_id, metadata={"name": project.name}
    )
    return _to_project_response(project, role)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    await audit_service.record(
        "Project Deleted", actor_user_id=str(user.id), project_id=project_id, metadata={"name": project.name}
    )
    await project_service.delete_project_cascade(project)


@router.post("/{project_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    project_id: str, payload: MemberInviteRequest, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)

    if await ProjectMember.find_one(
        ProjectMember.project_id == project_id, ProjectMember.invited_email == payload.email
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member of this project")

    invitee = await User.find_one(User.email == payload.email)
    now = datetime.now(timezone.utc)
    member = ProjectMember(
        project_id=project_id,
        user_id=str(invitee.id) if invitee else None,
        invited_email=payload.email,
        invited_by=str(user.id),
        invited_at=now,
        accepted_at=now if invitee else None,
    )
    await member.insert()
    await audit_service.record(
        "User Invited",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="user",
        target_id=str(invitee.id) if invitee else None,
        metadata={"email": payload.email},
    )
    return _to_member_response(member, invitee.name if invitee else None)


@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(project_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    members = await ProjectMember.find(ProjectMember.project_id == project_id).to_list()
    user_ids = [PydanticObjectId(m.user_id) for m in members if m.user_id]
    users_by_id = {str(u.id): u for u in await User.find(In(User.id, user_ids)).to_list()} if user_ids else {}
    return [_to_member_response(m, users_by_id[m.user_id].name if m.user_id in users_by_id else None) for m in members]


@router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(project_id: str, member_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)

    member = await ProjectMember.get(member_id)
    if not member or member.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if member.role == "owner":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the project owner")

    is_self = member.user_id == str(user.id)
    if not is_self and role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner or admin privileges required")

    await member.delete()
    await audit_service.record(
        "Member Removed",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="user",
        target_id=member.user_id,
        metadata={"role": member.role},
    )


@router.patch("/{project_id}/members/{member_id}", response_model=MemberResponse)
async def update_member_role(
    project_id: str, member_id: str, payload: MemberRoleUpdateRequest, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)

    member = await ProjectMember.get(member_id)
    if not member or member.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")

    if member.role == "owner" and payload.role != "owner":
        owner_count = await ProjectMember.find(
            ProjectMember.project_id == project_id, ProjectMember.role == "owner"
        ).count()
        if owner_count <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot demote the last owner")

    member.role = payload.role
    await member.save()
    await audit_service.record(
        "Member Role Updated",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="user",
        target_id=member.user_id,
        metadata={"role": member.role},
    )
    invitee = await User.get(member.user_id) if member.user_id else None
    return _to_member_response(member, invitee.name if invitee else None)


@router.get("/{project_id}/repos", response_model=list[ProjectRepoResponse])
async def list_project_repos(project_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    repos = await project_repo_service.list_repos(project_id)
    return [_to_project_repo_response(r) for r in repos]


@router.post("/{project_id}/repos", response_model=ProjectRepoResponse, status_code=status.HTTP_201_CREATED)
async def add_project_repo(
    project_id: str, payload: ProjectRepoCreateRequest, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    repo = await project_repo_service.add_repo(project_id, payload, user)
    await audit_service.record(
        "Project Repo Connected",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="project_repo",
        target_id=str(repo.id),
        metadata={"provider": repo.provider, "repo_full_name": repo.repo_full_name},
    )
    return _to_project_repo_response(repo)


@router.patch("/{project_id}/repos/{repo_id}", response_model=ProjectRepoResponse)
async def update_project_repo(
    project_id: str, repo_id: str, payload: ProjectRepoUpdateRequest, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    repo = await project_repo_service.update_branch(project_id, repo_id, payload.selected_branch)
    return _to_project_repo_response(repo)


@router.delete("/{project_id}/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_repo(project_id: str, repo_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    await project_repo_service.remove_repo(project_id, repo_id)
    await audit_service.record(
        "Project Repo Removed",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="project_repo",
        target_id=repo_id,
    )


@router.post("/{project_id}/repos/{repo_id}/reauth", response_model=ProjectRepoResponse)
async def reauth_project_repo(
    project_id: str, repo_id: str, payload: ProjectRepoReauthRequest, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    repo = await project_repo_service.reauth_repo(project_id, repo_id, payload.pat)
    await audit_service.record(
        "Project Repo Re-authenticated",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="project_repo",
        target_id=repo_id,
    )
    return _to_project_repo_response(repo)


@router.get("/{project_id}/repos/{repo_id}/scan-history", response_model=list[ScanHistoryItem])
async def get_repo_scan_history(
    project_id: str, repo_id: str, limit: int = Query(30, ge=1, le=200), user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    return await project_stats_service.get_repo_scan_history(project_id, repo_id, limit)


@router.get("/{project_id}/owasp-summary", response_model=OwaspSummaryResponse)
async def get_project_owasp_summary(
    project_id: str, project_repo_id: str | None = Query(None), user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    by_owasp = await project_stats_service.get_owasp_summary(project_id, project_repo_id)
    return OwaspSummaryResponse(project_id=project_id, project_repo_id=project_repo_id, by_owasp=by_owasp)
