"""Orchestrates saved GitHub/Azure DevOps Personal Access Tokens (RepoCredential) — a per-user
library of reusable credentials, independent of any project. A credential is validated by attempting
a real list_repos call (no token-introspection endpoint exists for either provider — same approach
zero-strike-cli uses) and is only ever usable by the user who saved it, no admin bypass."""

from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status

from app.core import security
from app.models.repo_credential import RepoCredential
from app.models.user import User
from app.services.repo_pat import RepoPatError, azure_devops, github


async def validate_pat(provider: str, pat: str, organization: str, ado_project: str | None) -> None:
    """Raises RepoPatError if the token can't actually list repos for this provider/org."""
    if provider == "github":
        await github.list_repos(pat)
    elif ado_project:
        await azure_devops.list_repos(pat, organization, ado_project)
    else:
        # Org-wide credential: the project is picked per connection, so prove org access instead.
        await azure_devops.list_projects(pat, organization)


async def create_credential(
    user: User,
    provider: str,
    pat: str,
    organization: str,
    ado_project: str | None,
    label: str | None,
) -> RepoCredential:
    try:
        await validate_pat(provider, pat, organization, ado_project)
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


async def check_status(user: User, credential_id: str) -> tuple[bool, str | None]:
    """(is_connected, reason). Proves the stored token still works with a real provider call — there
    is no introspection endpoint for either provider — so it costs one API request."""
    credential = await get_own_credential_or_404(user, credential_id)
    try:
        pat = decrypt_pat(credential)
    except InvalidToken:
        return False, "The stored token can no longer be read. Reconnect to save it again."
    try:
        await validate_pat(credential.provider, pat, credential.organization, credential.ado_project)
    except RepoPatError as e:
        return False, str(e)
    return True, None


async def update_credential(user: User, credential_id: str, changes: dict) -> RepoCredential:
    """Apply label / organization / ado_project edits. Moving to a different org or project re-checks
    the stored token against it first, so a typo can't leave a credential pointing nowhere."""
    credential = await get_own_credential_or_404(user, credential_id)
    if "label" in changes:
        credential.label = (changes["label"] or "").strip() or None
    organization = (changes.get("organization") or credential.organization).strip()
    ado_project = (changes["ado_project"] if "ado_project" in changes else credential.ado_project) or None
    if ado_project:
        ado_project = ado_project.strip() or None
    if credential.provider == "github":
        ado_project = None
    if (organization, ado_project) != (credential.organization, credential.ado_project):
        try:
            await validate_pat(credential.provider, decrypt_pat(credential), organization, ado_project)
        except InvalidToken:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The stored token can no longer be read. Reconnect first.")
        except RepoPatError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        credential.organization, credential.ado_project = organization, ado_project
    credential.updated_at = datetime.now(timezone.utc)
    await credential.save()
    return credential


async def reconnect_credential(user: User, credential_id: str, pat: str) -> RepoCredential:
    """Replace the stored token with a new one, validated against the credential's own org/project.
    Project connections hold their own copy of the token (see ProjectRepo), so they are unaffected."""
    credential = await get_own_credential_or_404(user, credential_id)
    try:
        await validate_pat(credential.provider, pat, credential.organization, credential.ado_project)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    credential.pat_encrypted = security.encrypt_secret(pat)
    credential.updated_at = datetime.now(timezone.utc)
    await credential.save()
    return credential


async def delete_credential(user: User, credential_id: str) -> None:
    credential = await get_own_credential_or_404(user, credential_id)
    await credential.delete()


def decrypt_pat(credential: RepoCredential) -> str:
    return security.decrypt_secret(credential.pat_encrypted)


def _ado_project(credential: RepoCredential, ado_project: str | None) -> str:
    """The caller's pick wins; a legacy credential saved against one project falls back to it."""
    project = ado_project or credential.ado_project
    if not project:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose an Azure DevOps project first")
    return project


async def list_projects(user: User, credential_id: str) -> list[dict]:
    credential = await get_own_credential_or_404(user, credential_id)
    if credential.provider != "azure_devops":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only Azure DevOps credentials have projects")
    try:
        return await azure_devops.list_projects(decrypt_pat(credential), credential.organization)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


async def list_repos(
    user: User,
    credential_id: str,
    *,
    query: str | None = None,
    page: int = 1,
    ado_project: str | None = None,
) -> list[dict]:
    credential = await get_own_credential_or_404(user, credential_id)
    pat = decrypt_pat(credential)
    try:
        if credential.provider == "github":
            return await github.list_repos(pat, query, page)
        return await azure_devops.list_repos(pat, credential.organization, _ado_project(credential, ado_project))
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


async def list_branches(
    user: User, credential_id: str, repo_id: str, *, ado_project: str | None = None
) -> list[dict]:
    """repo_id means "owner/repo" for GitHub, or the repo GUID for Azure DevOps."""
    credential = await get_own_credential_or_404(user, credential_id)
    pat = decrypt_pat(credential)
    try:
        if credential.provider == "github":
            owner, _, repo = repo_id.partition("/")
            return await github.list_branches(pat, owner, repo)
        return await azure_devops.list_branches(
            pat, credential.organization, _ado_project(credential, ado_project), repo_id
        )
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
