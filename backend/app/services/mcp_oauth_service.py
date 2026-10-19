"""OAuth 2.1 authorization server for the user MCP endpoint (docs/USER_MCP_OAUTH.md).

`MongoOAuthProvider` implements the `mcp` SDK's OAuthAuthorizationServerProvider protocol over
Beanie documents; the SDK's routes do request parsing, redirect_uri exact-match, scope checks and
the PKCE S256 verification. What the SDK does not enforce is enforced here: the RFC 8707 resource
binding, the shape of the PKCE challenge, redirect_uri schemes at registration, single-use codes
and refresh rotation with reuse detection.

Raw codes and tokens exist only in a return value; Mongo holds sha256 hashes.
"""

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from beanie import PydanticObjectId
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from pymongo import ReturnDocument

from app.core import security
from app.core.config import settings
from app.models.mcp_oauth import (
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    OAuthGrant,
    OAuthToken as OAuthTokenDoc,
)
from app.models.user import User

SCOPE = "mcp:read"
ACCESS_PREFIX = "tsoa_"
REFRESH_PREFIX = "tsor_"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
REQUEST_TTL = timedelta(minutes=10)
MAX_REDIRECT_URIS = 5
MAX_CLIENT_NAME = 100
# Registration and /authorize are open to the internet and stored; bound what one call can store.
MAX_CLIENT_METADATA_BYTES = 4096
MAX_STATE = 512
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
# base64url(sha256) is exactly 43 characters; anything else cannot be an S256 challenge.
_S256_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_GRANT_LAST_USED_INTERVAL = timedelta(seconds=60)


def resource_url() -> str:
    """The canonical resource identifier tokens are bound to (RFC 8707)."""
    return settings.backend_public_url.rstrip("/") + "/mcp/user"


def resource_metadata_url() -> str:
    return settings.backend_public_url.rstrip("/") + "/.well-known/oauth-protected-resource/mcp/user"


def same_resource(value: str | None) -> bool:
    return value is not None and value.rstrip("/") == resource_url()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def redirect_host(uri: str) -> str:
    return urlparse(uri).netloc


def display_name(info: dict) -> str:
    """Client names are attacker-chosen text: cut to length and drop control characters."""
    name = "".join(c for c in str(info.get("client_name") or "") if c.isprintable()).strip()
    return name[:MAX_CLIENT_NAME] or "Unnamed application"


def _valid_redirect_uri(uri: AnyUrl) -> bool:
    if uri.fragment or uri.username or uri.password or not uri.host:
        return False
    if uri.scheme == "https":
        return True
    return uri.scheme == "http" and uri.host in _LOOPBACK_HOSTS


async def _user_allowed(user_id: str) -> User | None:
    user = await User.get(user_id) if user_id else None
    if user and user.is_active and user.approval_status == "approved":
        return user
    return None


async def _claim(model, filt: dict):
    """Atomically stamp `used_at` on one unused document; the pre-update row, or None if it was
    missing or already used. The compare-and-set is what makes codes and requests single-use."""
    raw = await model.get_pymongo_collection().find_one_and_update(
        {**filt, "used_at": None}, {"$set": {"used_at": _now()}}, return_document=ReturnDocument.BEFORE
    )
    return model.model_validate(raw) if raw else None


async def revoke_grant(grant_id: str) -> None:
    """Kill the grant and every token it ever minted — access and refresh alike."""
    grant = await OAuthGrant.get(grant_id) if grant_id else None
    if grant and grant.revoked_at is None:
        grant.revoked_at = _now()
        await grant.save()
    await OAuthTokenDoc.find(OAuthTokenDoc.grant_id == grant_id).delete()


async def _issue_tokens(grant: OAuthGrant) -> OAuthToken:
    now = _now()
    access = f"{ACCESS_PREFIX}{secrets.token_urlsafe(32)}"
    refresh = f"{REFRESH_PREFIX}{secrets.token_urlsafe(32)}"
    common = dict(
        grant_id=str(grant.id), user_id=grant.user_id, client_id=grant.client_id,
        scopes=grant.scopes, resource=grant.resource,
    )  # fmt: skip
    await OAuthTokenDoc(
        token_hash=security.hash_token(access), kind="access", expires_at=now + ACCESS_TTL, **common
    ).insert()
    await OAuthTokenDoc(
        token_hash=security.hash_token(refresh), kind="refresh", expires_at=now + REFRESH_TTL, **common
    ).insert()
    return OAuthToken(
        access_token=access,
        token_type="Bearer",
        expires_in=int(ACCESS_TTL.total_seconds()),
        scope=" ".join(grant.scopes),
        refresh_token=refresh,
    )


class MongoOAuthProvider:
    # --- clients -------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        doc = await OAuthClient.find_one(OAuthClient.client_id == client_id)
        return OAuthClientInformationFull.model_validate(doc.info) if doc else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = client_info.redirect_uris or []
        if not uris or len(uris) > MAX_REDIRECT_URIS or not all(_valid_redirect_uri(u) for u in uris):
            raise RegistrationError(
                "invalid_redirect_uri",
                "redirect_uris must be https:// URLs, or http:// on 127.0.0.1, localhost or [::1]",
            )
        if client_info.scope is not None and set(client_info.scope.split()) - {SCOPE}:
            raise RegistrationError("invalid_client_metadata", f"The only supported scope is {SCOPE}")
        info = client_info.model_dump(mode="json", exclude_none=True)
        if len(client_info.client_name or "") > MAX_CLIENT_NAME or len(json.dumps(info)) > MAX_CLIENT_METADATA_BYTES:
            raise RegistrationError("invalid_client_metadata", "Client metadata is too large")
        await OAuthClient(client_id=client_info.client_id, info=info).insert()

    # --- authorization -------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # The SDK passes `resource` through unchecked. Ours is the only resource this server
        # protects, so a token for anything else is refused here, and an omitted one is pinned.
        if params.resource is not None and not same_resource(params.resource):
            raise AuthorizeError("invalid_target", "Unknown resource")
        if not _S256_CHALLENGE.match(params.code_challenge or ""):
            raise AuthorizeError("invalid_request", "code_challenge must be a base64url SHA-256 (43 characters)")
        if params.state and len(params.state) > MAX_STATE:
            raise AuthorizeError("invalid_request", f"state must be at most {MAX_STATE} characters")
        scopes = params.scopes or [SCOPE]
        if set(scopes) - {SCOPE}:
            raise AuthorizeError("invalid_scope", f"The only supported scope is {SCOPE}")
        request_id = secrets.token_urlsafe(24)
        await OAuthAuthorizationRequest(
            request_id=request_id,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            state=params.state,
            scopes=scopes,
            code_challenge=params.code_challenge,
            resource=resource_url(),
            expires_at=_now() + REQUEST_TTL,
        ).insert()
        return f"{settings.frontend_origin.rstrip('/')}/oauth/consent?request={request_id}"

    # --- consent (called by routers/oauth_consent.py, not by the SDK) ----------------------

    async def pending_request(self, request_id: str) -> OAuthAuthorizationRequest | None:
        req = await OAuthAuthorizationRequest.find_one(OAuthAuthorizationRequest.request_id == request_id)
        if not req or req.used_at or _aware(req.expires_at) <= _now():
            return None
        return req

    async def approve(self, request_id: str, user: User) -> tuple[OAuthAuthorizationRequest, str] | None:
        """Consume the pending request and mint its code. Returns (request, redirect_to), or None
        when the request is unknown, expired or already used."""
        req = await _claim(OAuthAuthorizationRequest, {"request_id": request_id})
        if not req or _aware(req.expires_at) <= _now():
            return None
        raw = secrets.token_urlsafe(32)
        await OAuthCode(
            code_hash=security.hash_token(raw),
            user_id=str(user.id),
            client_id=req.client_id,
            redirect_uri=req.redirect_uri,
            redirect_uri_provided_explicitly=req.redirect_uri_provided_explicitly,
            code_challenge=req.code_challenge,
            scopes=req.scopes,
            resource=req.resource,
            expires_at=_now() + CODE_TTL,
        ).insert()
        return req, construct_redirect_uri(req.redirect_uri, code=raw, state=req.state)

    async def deny(self, request_id: str) -> tuple[OAuthAuthorizationRequest, str] | None:
        req = await _claim(OAuthAuthorizationRequest, {"request_id": request_id})
        if not req or _aware(req.expires_at) <= _now():
            return None
        return req, construct_redirect_uri(req.redirect_uri, error="access_denied", state=req.state)

    # --- code exchange -------------------------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        doc = await OAuthCode.find_one(OAuthCode.code_hash == security.hash_token(authorization_code))
        if not doc or doc.client_id != client.client_id:
            return None
        if doc.used_at is not None:
            # A replayed code: assume it leaked and kill whatever it already minted.
            if doc.grant_id:
                await revoke_grant(doc.grant_id)
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=doc.scopes,
            expires_at=_aware(doc.expires_at).timestamp(),
            client_id=doc.client_id,
            code_challenge=doc.code_challenge,
            redirect_uri=AnyUrl(doc.redirect_uri),
            redirect_uri_provided_explicitly=doc.redirect_uri_provided_explicitly,
            resource=doc.resource,
            subject=doc.user_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_hash = security.hash_token(authorization_code.code)
        claimed = await _claim(OAuthCode, {"code_hash": code_hash})
        if claimed is None:  # lost a race with a concurrent exchange of the same code
            replayed = await OAuthCode.find_one(OAuthCode.code_hash == code_hash)
            if replayed and replayed.grant_id:
                await revoke_grant(replayed.grant_id)
            raise TokenError("invalid_grant", "authorization code already used")
        if not same_resource(claimed.resource) or not await _user_allowed(claimed.user_id):
            raise TokenError("invalid_grant", "authorization code is no longer valid")
        grant = OAuthGrant(
            user_id=claimed.user_id,
            client_id=client.client_id,
            client_name=display_name(client.model_dump()),
            redirect_host=redirect_host(claimed.redirect_uri),
            scopes=claimed.scopes,
            resource=claimed.resource,
        )
        await grant.insert()
        await OAuthCode.find_one(OAuthCode.code_hash == code_hash).update({"$set": {"grant_id": str(grant.id)}})
        return await _issue_tokens(grant)

    # --- refresh -------------------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        doc = await OAuthTokenDoc.find_one(OAuthTokenDoc.token_hash == security.hash_token(refresh_token))
        if not doc or doc.kind != "refresh" or doc.client_id != client.client_id:
            return None
        if doc.used_at is not None:
            await revoke_grant(doc.grant_id)  # a rotated token came back: theft, revoke it all
            return None
        grant = await OAuthGrant.get(doc.grant_id)
        if not grant or grant.revoked_at is not None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=doc.client_id,
            scopes=doc.scopes,
            expires_at=int(_aware(doc.expires_at).timestamp()),
            resource=doc.resource,
            subject=doc.user_id,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        token_hash = security.hash_token(refresh_token.token)
        claimed = await _claim(OAuthTokenDoc, {"token_hash": token_hash, "kind": "refresh"})
        if claimed is None:
            replayed = await OAuthTokenDoc.find_one(OAuthTokenDoc.token_hash == token_hash)
            if replayed:
                await revoke_grant(replayed.grant_id)
            raise TokenError("invalid_grant", "refresh token already used")
        grant = await OAuthGrant.get(claimed.grant_id)
        if not grant or grant.revoked_at is not None or not await _user_allowed(grant.user_id):
            raise TokenError("invalid_grant", "grant is no longer valid")
        if not set(scopes) <= set(grant.scopes):
            raise TokenError("invalid_scope", "Cannot widen scope")
        # Rotate both: older access tokens of this grant stop working as the new pair is minted.
        await OAuthTokenDoc.find(OAuthTokenDoc.grant_id == str(grant.id), OAuthTokenDoc.kind == "access").delete()
        return await _issue_tokens(grant)

    # --- resource-server side ------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        doc = await OAuthTokenDoc.find_one(OAuthTokenDoc.token_hash == security.hash_token(token))
        if not doc or doc.kind != "access" or _aware(doc.expires_at) <= _now():
            return None
        grant = await OAuthGrant.get(doc.grant_id)
        if not grant or grant.revoked_at is not None:
            return None
        now = _now()
        if grant.last_used_at is None or now - _aware(grant.last_used_at) >= _GRANT_LAST_USED_INTERVAL:
            grant.last_used_at = now
            await grant.save()
        return AccessToken(
            token=token,
            client_id=doc.client_id,
            scopes=doc.scopes,
            expires_at=int(_aware(doc.expires_at).timestamp()),
            resource=doc.resource,
            subject=doc.user_id,
            claims={"grant_id": doc.grant_id},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        doc = await OAuthTokenDoc.find_one(OAuthTokenDoc.token_hash == security.hash_token(token.token))
        if doc:
            await revoke_grant(doc.grant_id)


provider = MongoOAuthProvider()


async def list_grants(user: User) -> list[OAuthGrant]:
    return (
        await OAuthGrant.find(OAuthGrant.user_id == str(user.id), OAuthGrant.revoked_at == None)  # noqa: E711
        .sort("-created_at")
        .to_list()
    )


async def revoke_user_grant(user: User, grant_id: str) -> OAuthGrant | None:
    """Revoke one of the caller's own grants; None if it does not exist or is not theirs."""
    grant = await OAuthGrant.get(grant_id) if PydanticObjectId.is_valid(grant_id) else None
    if not grant or grant.user_id != str(user.id) or grant.revoked_at is not None:
        return None
    await revoke_grant(str(grant.id))
    return grant
