from fastapi import APIRouter, Depends, Query, status

from app.core.deps import get_current_user
from app.models.repo_credential import RepoCredential
from app.models.user import User
from app.schemas.repo_credential import (
    BranchResponse,
    RepoCredentialCreateRequest,
    RepoCredentialResponse,
    RepoResponse,
)
from app.services import audit_service, repo_credential_service

router = APIRouter(prefix="/repo-credentials", tags=["repo-credentials"])


def _to_response(credential: RepoCredential) -> RepoCredentialResponse:
    return RepoCredentialResponse(
        id=str(credential.id),
        provider=credential.provider,
        organization=credential.organization,
        ado_project=credential.ado_project,
        label=credential.label,
        created_at=credential.created_at,
    )


@router.get("", response_model=list[RepoCredentialResponse])
async def list_credentials(user: User = Depends(get_current_user)):
    return [_to_response(c) for c in await repo_credential_service.list_credentials(user)]


@router.post("", response_model=RepoCredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(payload: RepoCredentialCreateRequest, user: User = Depends(get_current_user)):
    credential = await repo_credential_service.create_credential(
        user, payload.provider, payload.pat, payload.organization, payload.ado_project, payload.label
    )
    await audit_service.record(
        "Repo Credential Added",
        actor_user_id=str(user.id),
        target_type="repo_credential",
        target_id=str(credential.id),
        metadata={"provider": credential.provider, "organization": credential.organization},
    )
    return _to_response(credential)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: str, user: User = Depends(get_current_user)):
    credential = await repo_credential_service.get_own_credential_or_404(user, credential_id)
    await repo_credential_service.delete_credential(user, credential_id)
    await audit_service.record(
        "Repo Credential Removed",
        actor_user_id=str(user.id),
        target_type="repo_credential",
        target_id=str(credential.id),
        metadata={"provider": credential.provider},
    )


@router.get("/{credential_id}/repos", response_model=list[RepoResponse])
async def list_repos(
    credential_id: str,
    query: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
):
    repos = await repo_credential_service.list_repos(user, credential_id, query=query, page=page)
    return [RepoResponse(**r) for r in repos]


@router.get("/{credential_id}/repos/{repo_id:path}/branches", response_model=list[BranchResponse])
async def list_branches(credential_id: str, repo_id: str, user: User = Depends(get_current_user)):
    branches = await repo_credential_service.list_branches(user, credential_id, repo_id)
    return [BranchResponse(**b) for b in branches]
