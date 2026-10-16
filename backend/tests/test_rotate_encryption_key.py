import asyncio
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from app.core.config import settings
from app.models.ai_provider_config import AIProviderConfig
from app.models.oauth_connection import OAuthConnection
from app.models.project_repo import ProjectRepo
from app.models.repo_credential import RepoCredential
from scripts.rotate_encryption_key import rotate

NOW = datetime.now(timezone.utc)


def _seed(key_a: Fernet) -> None:
    enc = lambda v: key_a.encrypt(v.encode()).decode()  # noqa: E731

    async def go():
        await AIProviderConfig(api_key_encrypted=enc("k1")).insert()
        await OAuthConnection(
            user_id="u", provider="github", account_login="a", external_account_id="1",
            access_token_encrypted=enc("at"), refresh_token_encrypted=enc("rt"),
            connected_at=NOW, updated_at=NOW,
        ).insert()  # fmt: skip
        await ProjectRepo(
            project_id="p", provider="github", organization="o", repo_full_name="o/r",
            clone_url="https://x/o/r", selected_branch="main", pat_encrypted=enc("pat1"),
            created_by="u", created_at=NOW, updated_at=NOW,
        ).insert()  # fmt: skip
        await RepoCredential(
            user_id="u", provider="github", organization="o", pat_encrypted=enc("pat2"),
            created_at=NOW, updated_at=NOW,
        ).insert()  # fmt: skip

    asyncio.run(go())


def _decrypts_with(key: Fernet) -> bool:
    async def go():
        vals = [
            (await AIProviderConfig.find_one()).api_key_encrypted,
            (o := await OAuthConnection.find_one()).access_token_encrypted,
            o.refresh_token_encrypted,
            (await ProjectRepo.find_one()).pat_encrypted,
            (await RepoCredential.find_one()).pat_encrypted,
        ]
        return [key.decrypt(v.encode()) for v in vals]

    return len(asyncio.run(go())) == 5


def test_rotate_dry_run_idempotent(client, monkeypatch):
    old_key, new = Fernet.generate_key(), Fernet.generate_key()
    _seed(Fernet(old_key))
    monkeypatch.setattr(settings, "oauth_encryption_key", new.decode())
    monkeypatch.setattr(settings, "oauth_encryption_key_previous", [old_key.decode()])

    dry = asyncio.run(rotate(dry_run=True))
    assert sum(dry.values()) == 5
    assert asyncio.run(rotate(dry_run=True)) == dry  # nothing was written

    done = asyncio.run(rotate())
    assert sum(done.values()) == 5
    assert _decrypts_with(Fernet(new))  # raises if any row still needs the old key
    assert sum(asyncio.run(rotate()).values()) == 0

