import asyncio

from app.core.security import verify_password
from app.models.user import User
from scripts.seed_dev_users import USERS, _upsert_user


def test_upsert_user_resyncs_password_on_existing_account(client):
    """Regression test: an account that drifted from docs/TEST_USERS.md (e.g. someone used
    the app's change-password flow) must be resynced back to the documented password the
    next time the seed script runs, not silently left broken."""
    spec = USERS[1]  # owner@zerostrike.dev

    async def _run():
        await _upsert_user(spec)
        user = await User.find_one(User.email == spec["email"])
        user.password_hash = "stale-hash-from-a-manual-password-change"
        await user.save()

        await _upsert_user(spec)
        return await User.find_one(User.email == spec["email"])

    user = asyncio.run(_run())
    assert verify_password(spec["password"], user.password_hash)


def test_seed_main_refuses_outside_development(monkeypatch):
    import pytest

    import scripts.seed_dev_users as seed_mod

    def _sentinel(*a, **k):
        raise AssertionError("must not connect when refusing")

    monkeypatch.setattr(seed_mod.settings, "app_env", "production")
    monkeypatch.setattr(seed_mod, "connect_to_mongo", _sentinel)
    monkeypatch.setattr(seed_mod, "_drop_database", _sentinel)
    with pytest.raises(SystemExit) as exc:
        seed_mod.main(["--reset", "--yes"])
    assert exc.value.code == 2
