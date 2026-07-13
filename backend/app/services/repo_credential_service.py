"""Orchestrates saved GitHub/Azure DevOps Personal Access Tokens (RepoCredential) — a per-user
library of reusable credentials, independent of any project. A credential is validated by attempting
a real list_repos call (no token-introspection endpoint exists for either provider — same approach
zero-strike-cli uses) and is only ever usable by the user who saved it, no admin bypass."""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core import security
from app.models.repo_credential import RepoCredential
from app.models.user import User
from app.services.repo_pat import RepoPatError, azure_devops, github


async def _list_repos_for_validation(provider: str, pat: str, organization: str, ado_project: str | None) -> None:
    if provider == "github":
        await github.list_repos(pat)
    else:
        await azure_devops.list_repos(pat, organization, ado_project)


async def create_credential(
    user: User,
    provider: str,
    pat: str,
    organization: str,
    ado_project: str | None,
    label: str | None,
) -> RepoCredential:
    try:
        await _list_repos_for_validation(provider, pat, organization, ado_project)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    now = datetime.now(timezone.utc)
    credential = RepoCredential(
        user_id=str(user.id),
        provider=provider,
        organization=organization,
        ado_project=ado_project,
        label=label,
        pat_encrypted=security.encrypt_secret(pat),
        created_at=now,
        updated_at=now,
    )
    await credential.insert()
    return credential


async def list_credentials(user: User) -> list[RepoCredential]:
    return await RepoCredential.find(RepoCredential.user_id == str(user.id)).to_list()


async def get_own_credential_or_404(user: User, credential_id: str) -> RepoCredential:
    """IDOR-safe by construction: filters by owner, 404s (never 403s) on a mismatch."""
    credential = await RepoCredential.get(credential_id)
    if not credential or credential.user_id != str(user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    return credential


async def delete_credential(user: User, credential_id: str) -> None:
    credential = await get_own_credential_or_404(user, credential_id)
    await credential.delete()


def decrypt_pat(credential: RepoCredential) -> str:
    return security.decrypt_secret(credential.pat_encrypted)


async def list_repos(user: User, credential_id: str, *, query: str | None = None, page: int = 1) -> list[dict]:
    credential = await get_own_credential_or_404(user, credential_id)
    pat = decrypt_pat(credential)
    try:
        if credential.provider == "github":
            return await github.list_repos(pat, query, page)
        return await azure_devops.list_repos(pat, credential.organization, credential.ado_project)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


async def list_branches(user: User, credential_id: str, repo_id: str) -> list[dict]:
    """repo_id means "owner/repo" for GitHub, or the repo GUID for Azure DevOps."""
    credential = await get_own_credential_or_404(user, credential_id)
    pat = decrypt_pat(credential)
    try:
        if credential.provider == "github":
            owner, _, repo = repo_id.partition("/")
            return await github.list_branches(pat, owner, repo)
        return await azure_devops.list_branches(pat, credential.organization, credential.ado_project, repo_id)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
