"""Manages repos connected to a project for cloud scans (ProjectRepo) — a project may hold several.
Each connection stores its own copy of the encrypted PAT at connect time (via a saved RepoCredential
or an inline one-off PAT), decoupled from whichever credential it came from — see ProjectRepo's
docstring for why that matters."""

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status

from app.core import security
from app.models.project_repo import ProjectRepo
from app.models.user import User
from app.schemas.project_repo import ProjectRepoCreateRequest
from app.services import repo_credential_service
from app.services.repo_pat import RepoPatError, github


async def add_repo(project_id: str, payload: ProjectRepoCreateRequest, user: User) -> ProjectRepo:
    if payload.public:
        owner, _, _name = payload.repo_full_name.partition("/")
        try:
            await github.fetch_public_repo(owner, _name)
        except RepoPatError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        provider = "github"
        organization = owner
        ado_project = None
        pat_encrypted = None
        source_credential_id = None
    elif payload.credential_id:
        credential = await repo_credential_service.get_own_credential_or_404(user, payload.credential_id)
        provider = credential.provider
        organization = credential.organization
        # An org-wide Azure DevOps credential has no project of its own — the wizard sends the pick.
        ado_project = (payload.ado_project or credential.ado_project) if provider == "azure_devops" else None
        if provider == "azure_devops" and not ado_project:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ado_project is required for Azure DevOps")
        pat_encrypted = credential.pat_encrypted
        source_credential_id = str(credential.id)
    else:
        provider = payload.provider
        # GitHub never sends one (the API doesn't scope by org) — the owner segment is the honest
        # value for the display column, instead of a field the user has to guess at.
        organization = payload.organization or payload.repo_full_name.partition("/")[0]
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


def normalize_repo_url(url: str | None) -> str:
    """Comparison key for a clone URL: lowercase scheme and host, no trailing "/" or ".git".
    "https://GitHub.com/o/r.git/" and "https://github.com/o/r" name the same repo, so an ad-hoc
    scan of either must land on the connected repo rather than in the Unlinked bucket."""
    url = (url or "").strip()
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.lower().endswith(".git"):
        path = path[:-4].rstrip("/")
    if not parts.scheme or not parts.netloc:
        return path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def repo_url_regex(url: str) -> dict:
    """A Mongo `$regex` matching every spelling of `url` that normalize_repo_url folds together
    (host case, trailing ".git", trailing "/"), for queries that cannot normalise stored rows."""
    parts = urlsplit(normalize_repo_url(url))
    prefix = f"{re.escape(parts.scheme)}://{re.escape(parts.netloc)}" if parts.netloc else ""
    return {"$regex": rf"^(?i:{prefix}){re.escape(parts.path)}(\.git)?/?$"}


async def find_repo_by_url(project_id: str, url: str | None) -> ProjectRepo | None:
    """The project's connected repo whose clone URL normalises to the same key as `url`."""
    key = normalize_repo_url(url)
    if not key:
        return None
    return next((r for r in await list_repos(project_id) if normalize_repo_url(r.clone_url) == key), None)


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
    # The remembered head and any error belonged to the old branch.
    repo.remote_head_sha = None
    repo.remote_head_checked_at = None
    repo.last_sync_error = None
    repo.updated_at = datetime.now(timezone.utc)
    await repo.save()
    return repo


def decrypt_pat(repo: ProjectRepo) -> str | None:
    # None for a public repo connected with no credential at all (see add_repo) — the clone runs
    # anonymously, so there's nothing to decrypt.
    return security.decrypt_secret(repo.pat_encrypted) if repo.pat_encrypted else None


async def reauth_repo(project_id: str, repo_id: str, new_pat: str) -> ProjectRepo:
    """Replace this repo's stored token in place. Scoped to this one repo only — never
    touches the RepoCredential it may have originally been connected from (see
    ProjectRepo's docstring: a connected repo's credential is intentionally decoupled
    from any saved credential)."""
    repo = await get_project_repo_or_404(project_id, repo_id)
    try:
        await repo_credential_service.validate_pat(repo.provider, new_pat, repo.organization, repo.ado_project)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    repo.pat_encrypted = security.encrypt_secret(new_pat)
    repo.updated_at = datetime.now(timezone.utc)
    await repo.save()
    return repo
