"""Unauthenticated GitHub repo/branch lookups, used by the "connect a public repo — no credential"
flow (see project_repo_service.add_repo). Requires a logged-in portal user (like every other repo
browsing endpoint) even though the GitHub call itself carries no token, purely to keep this from
being an open proxy for anyone to hammer GitHub's API through our server."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.repo_credential import BranchResponse, RepoResponse
from app.services.repo_pat import RepoPatError, github

router = APIRouter(prefix="/public-repos/github", tags=["public-repos"])


@router.get("/{owner}/{repo}", response_model=RepoResponse)
async def get_public_repo(owner: str, repo: str, user: User = Depends(get_current_user)):
    try:
        data = await github.fetch_public_repo(owner, repo)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if data["private"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This repository is private — add a Personal Access Token")
    return RepoResponse(**data)


@router.get("/{owner}/{repo}/branches", response_model=list[BranchResponse])
async def get_public_repo_branches(owner: str, repo: str, user: User = Depends(get_current_user)):
    try:
        branches = await github.list_public_branches(owner, repo)
    except RepoPatError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return [BranchResponse(**b) for b in branches]
