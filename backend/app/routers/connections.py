from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.deps import get_current_user
from app.models.oauth_connection import OAuthConnection
from app.models.user import User
from app.schemas.connection import AuthorizeResponse, AzureProjectResponse, ConnectionResponse, OrgResponse, RepoResponse
from app.services import audit_service, connection_service
from app.services.oauth import OAuthProviderError

router = APIRouter(prefix="/connections", tags=["connections"])

_STATE_COOKIE = "zs_oauth_state"
# URL segments are hyphenated (matches the "audit-logs" convention); internal representation stays
# the snake_case Literal used on OAuthConnection.provider.
_URL_TO_PROVIDER = {"github": "github", "azure-devops": "azure_devops"}
_PROVIDER_TO_URL = {v: k for k, v in _URL_TO_PROVIDER.items()}


def _provider_or_404(url_segment: str) -> str:
    if url_segment not in _URL_TO_PROVIDER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    return _URL_TO_PROVIDER[url_segment]


def _to_response(conn: OAuthConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=str(conn.id), provider=conn.provider, account_login=conn.account_login, connected_at=conn.connected_at
    )


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(user: User = Depends(get_current_user)):
    return [_to_response(c) for c in await connection_service.list_connections(user)]


@router.post("/{provider}/authorize", response_model=AuthorizeResponse)
async def authorize(provider: str, request: Request, response: Response, user: User = Depends(get_current_user)):
    authorize_url, jti = connection_service.build_authorize_url(user, _provider_or_404(provider))
    response.set_cookie(
        _STATE_COOKIE,
        jti,
        max_age=600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/api/v1/connections",
    )
    return AuthorizeResponse(authorize_url=authorize_url)


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
):
    resolved = _provider_or_404(provider)
    cookie_jti = request.cookies.get(_STATE_COOKIE)
    base = f"{settings.frontend_origin}/settings/integrations"

    def _redirect(**query: str) -> RedirectResponse:
        resp = RedirectResponse(f"{base}?{urlencode(query)}", status_code=status.HTTP_302_FOUND)
        resp.delete_cookie(_STATE_COOKIE, path="/api/v1/connections")
        return resp

    if not code or not state:
        return _redirect(error="missing_code")
    try:
        conn = await connection_service.handle_callback(resolved, code, state, cookie_jti)
    except (HTTPException, OAuthProviderError):
        return _redirect(error="oauth_failed")

    await audit_service.record(
        "Connection Connected",
        actor_user_id=conn.user_id,
        target_type="oauth_connection",
        target_id=str(conn.id),
        metadata={"provider": conn.provider, "account_login": conn.account_login},
    )
    return _redirect(connected=provider)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(provider: str, user: User = Depends(get_current_user)):
    resolved = _provider_or_404(provider)
    conn = await connection_service.get_own_connection_or_404(user, resolved)
    await connection_service.disconnect(user, resolved)
    await audit_service.record(
        "Connection Disconnected",
        actor_user_id=str(user.id),
        target_type="oauth_connection",
        target_id=str(conn.id),
        metadata={"provider": resolved},
    )


@router.get("/github/repos", response_model=list[RepoResponse])
async def github_repos(
    query: str | None = Query(None), page: int = Query(1, ge=1), user: User = Depends(get_current_user)
):
    repos = await connection_service.list_repos(user, "github", query=query, page=page)
    return [RepoResponse(**r) for r in repos]


@router.get("/azure-devops/orgs", response_model=list[OrgResponse])
async def azure_orgs(user: User = Depends(get_current_user)):
    return [OrgResponse(**o) for o in await connection_service.list_azure_orgs(user)]


@router.get("/azure-devops/orgs/{org}/projects", response_model=list[AzureProjectResponse])
async def azure_projects(org: str, user: User = Depends(get_current_user)):
    return [AzureProjectResponse(**p) for p in await connection_service.list_azure_projects(user, org)]


@router.get("/azure-devops/orgs/{org}/projects/{project}/repos", response_model=list[RepoResponse])
async def azure_repos(org: str, project: str, user: User = Depends(get_current_user)):
    repos = await connection_service.list_azure_repos(user, org, project)
    return [RepoResponse(**r) for r in repos]
