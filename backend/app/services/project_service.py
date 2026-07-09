from fastapi import HTTPException, status

from app.models.api_key import ApiKey
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User


async def get_membership(project_id: str, user_id: str) -> ProjectMember | None:
    return await ProjectMember.find_one(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
    )


async def role_in_project(project_id: str, user: User) -> str | None:
    """Returns "admin" for platform admins, else the membership role, else None."""
    if user.role == "admin":
        return "admin"
    membership = await get_membership(project_id, str(user.id))
    return membership.role if membership else None


async def require_member(project_id: str, user: User) -> str:
    role = await role_in_project(project_id, user)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this project")
    return role


async def require_owner_or_admin(project_id: str, user: User) -> str:
    role = await role_in_project(project_id, user)
    if role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner or admin privileges required")
    return role


async def get_project_or_404(project_id: str) -> Project:
    project = await Project.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def delete_project_cascade(project: Project) -> None:
    await ProjectMember.find(ProjectMember.project_id == str(project.id)).delete()
    await ApiKey.find(ApiKey.project_id == str(project.id)).delete()
    await project.delete()
