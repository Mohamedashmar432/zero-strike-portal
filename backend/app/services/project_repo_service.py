"""Manages repos connected to a project for cloud scans (ProjectRepo) — a project may hold several.
Each connection stores its own copy of the encrypted PAT at connect time (via a saved RepoCredential
or an inline one-off PAT), decoupled from whichever credential it came from — see ProjectRepo's
docstring for why that matters."""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core import security
from app.models.project_repo import ProjectRepo
from app.models.user import User
from app.schemas.project_repo import ProjectRepoCreateRequest
from app.services import repo_credential_service


async def add_repo(project_id: str, payload: ProjectRepoCreateRequest, user: User) -> ProjectRepo:
    if payload.credential_id:
        credential = await repo_credential_service.get_own_credential_or_404(user, payload.credential_id)
        provider = credential.provider
        organization = credential.organization
        ado_project = credential.ado_project
        pat_encrypted = credential.pat_encrypted
        source_credential_id = str(credential.id)
    else:
        provider = payload.provider
        organization = payload.organization
        ado_project = payload.ado_project
        pat_encrypted = security.encrypt_secret(payload.pat)
        source_credential_id = None

    now = datetime.now(timezone.utc)
    repo = ProjectRepo(
        project_id=project_id,
        provider=provider,
        organization=organization,
        ado_project=ado_project,
        repo_full_name=payload.repo_full_name,
        clone_url=payload.clone_url,
        selected_branch=payload.selected_branch,
        label=payload.label,
        pat_encrypted=pat_encrypted,
        source_credential_id=source_credential_id,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await repo.insert()
    return repo


async def list_repos(project_id: str) -> list[ProjectRepo]:
    return await ProjectRepo.find(ProjectRepo.project_id == project_id).to_list()


async def get_project_repo_or_404(project_id: str, repo_id: str) -> ProjectRepo:
    repo = await ProjectRepo.get(repo_id)
    if not repo or repo.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repo connection not found")
    return repo


async def remove_repo(project_id: str, repo_id: str) -> None:
    repo = await get_project_repo_or_404(project_id, repo_id)
    await repo.delete()


async def update_branch(project_id: str, repo_id: str, branch: str) -> ProjectRepo:
    repo = await get_project_repo_or_404(project_id, repo_id)
    repo.selected_branch = branch
    repo.updated_at = datetime.now(timezone.utc)
    await repo.save()
    return repo


def decrypt_pat(repo: ProjectRepo) -> str:
    return security.decrypt_secret(repo.pat_encrypted)
