"""Look up a single GitHub repo from a URL + a one-off PAT — the "I know the repo, here's my token"
connect path, alongside the saved-credential picker (routers/repo_credentials.py) and the
credential-free public lookup (routers/public_repos.py).

POST, not GET: the PAT travels in the body so it can't land in a URL, an access log or browser
history. Nothing is stored here — the token is used for this one lookup and discarded; it's only
persisted (encrypted) if the user goes on to connect the repo.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.repo_credential import BranchResponse, RepoLookupRequest, RepoLookupResponse, RepoResponse
from app.services.repo_pat import RepoPatError, github

router = APIRouter(prefix="/repo-lookup/github", tags=["repo-lookup"])


@router.post("", response_model=RepoLookupResponse)
async def lookup_github_repo(payload: RepoLookupRequest, user: User = Depends(get_current_user)):
    owner, _, name = payload.repo_full_name.partition("/")
    if not owner or not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Enter as "owner/repo" or a full GitHub URL')
    try:
        # Repo + branches in one round trip: the caller would need both anyway, and asking for the
        # PAT once is the whole point of this flow.
        repo = await github.fetch_repo(payload.pat, owner, name)
        branches = await github.list_branches(payload.pat, owner, name)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return RepoLookupResponse(
        repo=RepoResponse(**repo), branches=[BranchResponse(**b) for b in branches]
    )
