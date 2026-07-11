import asyncio
from datetime import datetime, timedelta, timezone

from app.core import security
from app.core.config import settings
from app.models.user import RefreshTokenRecord, User
from app.services import auth_service


def _make_user(email: str) -> User:
    now = datetime.now(timezone.utc)
    return User(
        email=email,
        password_hash=security.hash_password("whatever123"),
        name="Prune Test",
        created_at=now,
        updated_at=now,
    )


def test_issue_token_pair_prunes_old_revoked_and_expired_but_keeps_active_records(client):
    async def run():
        user = _make_user("prune1@zerostrike.dev")
        await user.insert()

        now = datetime.now(timezone.utc)
        # Comfortably past the retention cutoff (settings.refresh_token_retention_days).
        stale = now - timedelta(days=settings.refresh_token_retention_days + 1)

        old_revoked = RefreshTokenRecord(
            jti="old-revoked",
            token_hash="hash-a",
            issued_at=stale - timedelta(days=1),
            expires_at=stale + timedelta(days=30),  # unexpired by expiry, but revoked long ago
            revoked_at=stale,
        )
        old_expired_never_revoked = RefreshTokenRecord(
            jti="old-expired",
            token_hash="hash-b",
            issued_at=stale - timedelta(days=1),
            expires_at=stale,  # expired before the retention cutoff, never revoked
            revoked_at=None,
        )
        currently_valid = RefreshTokenRecord(
            jti="still-valid",
            token_hash="hash-c",
            issued_at=now,
            expires_at=now + timedelta(days=30),
            revoked_at=None,
        )
        user.refresh_tokens = [old_revoked, old_expired_never_revoked, currently_valid]
        await user.save()

        await auth_service.issue_token_pair(user)
        return user

    user = asyncio.run(run())

    jtis = {r.jti for r in user.refresh_tokens}
    assert "old-revoked" not in jtis
    assert "old-expired" not in jtis
    assert "still-valid" in jtis
    # The surviving pre-existing record plus the one issue_token_pair just appended.
    assert len(user.refresh_tokens) == 2
