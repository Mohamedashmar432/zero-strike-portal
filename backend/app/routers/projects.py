from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.common import Page
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.schemas.project_member import MemberInviteRequest, MemberResponse
from app.services import audit_service, project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_project_response(project: Project, my_role: str) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        is_archived=project.is_archived,
        scan_count=project.scan_count,
        last_scan_at=project.last_scan_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,
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


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)
    return _to_project_response(project, role)


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
