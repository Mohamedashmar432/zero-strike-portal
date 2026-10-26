import asyncio
from datetime import datetime, timedelta, timezone

from app.core import security
from app.core.config import settings
from app.models.user import RefreshTokenRecord, User
from tests.test_auth_flow import register_and_login


def _expiry(refresh_token: str) -> datetime:
    return datetime.fromtimestamp(security.decode_token(refresh_token)["exp"], tz=timezone.utc)


def _login(client, email, **body):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2pass", **body})
    assert r.status_code == 200
    return r.json()


def test_remember_me_lasts_seven_days_and_plain_sign_in_twelve_hours(client):
    register_and_login(client, email="life@zerostrike.dev")
    now = datetime.now(timezone.utc)

    remembered = _expiry(_login(client, "life@zerostrike.dev", remember_me=True)["refresh_token"])
    assert abs(remembered - (now + timedelta(days=7))) < timedelta(minutes=1)

    plain = _expiry(_login(client, "life@zerostrike.dev")["refresh_token"])
    assert abs(plain - (now + timedelta(hours=12))) < timedelta(minutes=1)


def test_refreshing_never_extends_a_session(client):
    """Rotation carries the sign-in's expiry forward, so a token kept busy still dies on schedule."""
    register_and_login(client, email="life2@zerostrike.dev")
    tokens = _login(client, "life2@zerostrike.dev", remember_me=True)
    signed_in_until = _expiry(tokens["refresh_token"])

    for _ in range(3):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200
        tokens = r.json()
        assert _expiry(tokens["refresh_token"]) == signed_in_until


def test_a_session_issued_under_the_old_30_day_ttl_is_cut_to_seven_days_on_refresh(client):
    register_and_login(client, email="life3@zerostrike.dev")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=30)

    async def plant():
        user = await User.find_one(User.email == "life3@zerostrike.dev")
        legacy_token, _, _ = security.create_refresh_token(str(user.id), expires_at)
        claims = security.decode_token(legacy_token)
        user.refresh_tokens.append(
            RefreshTokenRecord(
                jti=claims["jti"],
                token_hash=security.hash_token(legacy_token),
                issued_at=now,
                expires_at=expires_at,
            )
        )
        await user.save()
        return legacy_token

    legacy = asyncio.run(plant())
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": legacy})
    assert r.status_code == 200
    assert _expiry(r.json()["refresh_token"]) <= now + timedelta(days=settings.refresh_token_ttl_days, minutes=1)
