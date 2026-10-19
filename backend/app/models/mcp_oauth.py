"""Authorization-server state for the user MCP endpoint (docs/USER_MCP_OAUTH.md). Codes and tokens
are stored only as sha256 hashes; every short-lived collection carries a TTL index (Mongo reaps
about a minute late, so readers also check `expires_at` themselves)."""

from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import Field
from pymongo import IndexModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OAuthClient(Document):
    """A dynamically registered client. `info` is the SDK's OAuthClientInformationFull as JSON.
    The name inside it is display text only and is never trusted."""

    client_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    info: dict
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "oauth_clients"


class OAuthAuthorizationRequest(Document):
    """A pending /authorize request waiting on the user's consent. Single use, 10-minute TTL."""

    request_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    state: str | None = None
    scopes: list[str]
    code_challenge: str
    resource: str
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime
    used_at: datetime | None = None

    class Settings:
        name = "oauth_authorization_requests"
        indexes = [IndexModel([("expires_at", 1)], expireAfterSeconds=0, name="ttl")]


class OAuthCode(Document):
    """An authorization code, bound to user + client + redirect_uri + PKCE challenge + resource."""

    code_hash: Indexed(str, unique=True)  # type: ignore[valid-type]
    user_id: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    resource: str
    expires_at: datetime
    used_at: datetime | None = None
    grant_id: str | None = None  # set when exchanged, so a replayed code can revoke what it minted

    class Settings:
        name = "oauth_codes"
        indexes = [IndexModel([("expires_at", 1)], expireAfterSeconds=0, name="ttl")]


class OAuthGrant(Document):
    """What the user sees under Connected apps: one authorization, however many token rotations."""

    user_id: Indexed(str)  # type: ignore[valid-type]
    client_id: str
    client_name: str
    redirect_host: str
    scopes: list[str]
    resource: str
    created_at: datetime = Field(default_factory=_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    class Settings:
        name = "oauth_grants"


class OAuthToken(Document):
    """An access or refresh token. A used refresh token is kept (until it expires) so that
    presenting it again is recognised as theft and revokes the grant."""

    token_hash: Indexed(str, unique=True)  # type: ignore[valid-type]
    kind: str  # "access" | "refresh"
    grant_id: Indexed(str)  # type: ignore[valid-type]
    user_id: str
    client_id: str
    scopes: list[str]
    resource: str
    expires_at: datetime
    used_at: datetime | None = None

    class Settings:
        name = "oauth_tokens"
        indexes = [IndexModel([("expires_at", 1)], expireAfterSeconds=0, name="ttl")]
