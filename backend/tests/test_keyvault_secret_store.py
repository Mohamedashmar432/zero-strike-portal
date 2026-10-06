import asyncio
from datetime import datetime, timezone

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from fastapi import HTTPException

from app.core import security
from app.core.config import settings
from app.models.ai_provider_config import AIProviderConfig
from app.models.project import Project
from app.services import ai_provider_config_service as svc
from app.services import data_management_service, llm_client, secret_store


class _Secret:
    def __init__(self, value):
        self.value = value


class _Poller:
    def __init__(self, on_wait=None):
        self._on_wait = on_wait

    def wait(self):
        if self._on_wait:
            self._on_wait()


class FakeVault:
    """In-memory stand-in for azure SecretClient, including the soft-delete conflict."""

    def __init__(self):
        self.secrets: dict[str, str] = {}
        self.tags: dict[str, dict] = {}
        self.deleted: set[str] = set()
        self.recovered: list[str] = []
        self.fail = False

    def _check(self):
        if self.fail:
            raise RuntimeError("vault down")

    def set_secret(self, name, value, tags=None):
        self._check()
        if name in self.deleted:
            raise ResourceExistsError("deleted but recoverable")
        self.secrets[name] = value
        self.tags[name] = tags or {}

    def get_secret(self, name):
        self._check()
        if name not in self.secrets:
            raise ResourceNotFoundError("nope")
        return _Secret(self.secrets[name])

    def begin_delete_secret(self, name):
        self._check()
        if name not in self.secrets:
            raise ResourceNotFoundError("nope")
        self.deleted.add(name)
        return _Poller()

    def begin_recover_deleted_secret(self, name):
        self._check()
        self.recovered.append(name)
        return _Poller(lambda: self.deleted.discard(name))


@pytest.fixture()
def vault(client, monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(settings, "azure_key_vault_url", "https://fake.vault.azure.net")
    monkeypatch.setattr(secret_store, "_get_client", lambda: fake)
    secret_store._cache.clear()
    yield fake
    secret_store._cache.clear()


def _create(project_id=None, api_key="sk-secret"):
    return svc.create_config(
        name="P", provider="openai", model_name="gpt-4o", base_url=None, temperature=0.0,
        api_key=api_key, created_by=None, project_id=project_id,
    )


def _update(config, **kw):
    args = dict(
        name="P", provider="openai", model_name="gpt-4o", base_url=None, temperature=None,
        api_key=None, clear_api_key=False, updated_by=None,
    )
    return svc.update_config(str(config.id), **{**args, **kw})


async def _project(name):
    now = datetime.now(timezone.utc)
    return await Project(name=name, owner_id="u", created_at=now, updated_at=now).insert()


def test_secret_name_format_and_sanitising():
    assert secret_store.secret_name("abc123", None) == "thinkshield-portal-abc123"
    assert secret_store.secret_name("abc123", "  My App_v2!! ") == "thinkshield-my-app-v2-abc123"
    assert secret_store.secret_name("abc123", "!!!") == "thinkshield-project-abc123"


def test_secret_name_truncated_to_vault_limit():
    cid = "a" * 24
    name = secret_store.secret_name(cid, "x" * 500)
    assert len(name) <= 127 and name.endswith(f"-{cid}") and name.startswith("thinkshield-x")
    # truncation must not leave a dangling hyphen before the id
    assert "--" not in secret_store.secret_name(cid, "x" * 100 + "-" * 50 + "y" * 100)


def test_create_stores_key_in_vault_not_mongo(vault):
    async def run():
        config = await _create()
        stored = await AIProviderConfig.get(config.id)
        assert stored.api_key_secret_name == f"thinkshield-portal-{config.id}"
        assert stored.api_key_encrypted is None
        assert vault.secrets[stored.api_key_secret_name] == "sk-secret"
        assert vault.tags[stored.api_key_secret_name]["scope"] == "portal"
        assert svc.has_api_key(stored) and await svc.is_ready(stored)
        assert await svc.get_api_key(stored) == "sk-secret"

    asyncio.run(run())


def test_project_key_named_from_project_and_tagged(vault):
    async def run():
        project = await _project("Acme Web")
        config = await _create(project_id=str(project.id))
        assert config.api_key_secret_name == f"thinkshield-acme-web-{config.id}"
        assert vault.tags[config.api_key_secret_name]["project_id"] == str(project.id)

    asyncio.run(run())


def test_update_rotates_key_under_same_name(vault):
    async def run():
        config = await _create()
        name = config.api_key_secret_name
        updated = await _update(config, api_key="sk-new")
        assert updated.api_key_secret_name == name
        assert vault.secrets[name] == "sk-new"
        assert await svc.get_api_key(updated) == "sk-new"

    asyncio.run(run())


def test_clear_deletes_secret_and_nulls_reference_then_reset_recovers(vault):
    async def run():
        await _create()  # takes the active slot; an active config may not lose its key
        config = await _create()
        name = config.api_key_secret_name
        cleared = await _update(config, clear_api_key=True)
        assert cleared.api_key_secret_name is None and cleared.api_key_encrypted is None
        assert name in vault.deleted and not svc.has_api_key(cleared)

        again = await _update(cleared, api_key="sk-again")
        assert vault.recovered == [again.api_key_secret_name]
        assert vault.secrets[again.api_key_secret_name] == "sk-again"
        assert await svc.get_api_key(again) == "sk-again"

    asyncio.run(run())


def test_delete_config_deletes_secret(vault):
    async def run():
        config = await _create()
        await svc.delete_config(str(config.id))
        assert config.api_key_secret_name in vault.deleted
        assert await AIProviderConfig.find().count() == 0

    asyncio.run(run())


def test_delete_config_survives_vault_failure(vault):
    async def run():
        config = await _create()
        vault.fail = True
        await svc.delete_config(str(config.id))
        assert await AIProviderConfig.find().count() == 0

    asyncio.run(run())


def test_project_purge_deletes_project_secrets_only(vault):
    async def run():
        project = await _project("Doomed")
        mine = await _create(project_id=str(project.id))
        portal = await _create()
        await data_management_service.purge_project(str(project.id))
        assert mine.api_key_secret_name in vault.deleted
        assert portal.api_key_secret_name not in vault.deleted
        remaining = await AIProviderConfig.find().to_list()
        assert [c.id for c in remaining] == [portal.id]

    asyncio.run(run())


def test_purge_not_blocked_by_vault_failure(vault):
    async def run():
        project = await _project("Doomed")
        await _create(project_id=str(project.id))
        vault.fail = True
        await data_management_service.purge_project(str(project.id))
        assert await AIProviderConfig.find().count() == 0

    asyncio.run(run())


def test_vault_failure_on_create_is_503_and_inserts_nothing(vault):
    async def run():
        vault.fail = True
        with pytest.raises(HTTPException) as exc:
            await _create()
        assert exc.value.status_code == 503
        assert await AIProviderConfig.find().count() == 0

    asyncio.run(run())


def test_vault_read_failure_becomes_transient_llm_error(vault):
    async def run():
        config = await _create()
        secret_store._cache.clear()
        vault.fail = True
        with pytest.raises(llm_client.LLMTransientError):
            await llm_client.load_api_key(config)

    asyncio.run(run())


def test_vault_off_uses_fernet(client):
    async def run():
        assert not secret_store.enabled()
        config = await _create()
        assert config.api_key_secret_name is None
        assert security.decrypt_secret(config.api_key_encrypted) == "sk-secret"
        assert await svc.get_api_key(config) == "sk-secret"

    asyncio.run(run())


def test_legacy_ciphertext_still_readable_with_vault_on(vault):
    async def run():
        config = AIProviderConfig(
            provider="openai", model_name="m", api_key_encrypted=security.encrypt_secret("legacy")
        )
        assert await svc.get_api_key(config) == "legacy"
        assert await svc.is_ready(config)

    asyncio.run(run())


def _status_key_vault_flag(client):
    from tests.test_auth_flow import register_and_login

    tokens = register_and_login(client, "kv-status@example.com")
    r = client.get("/api/v1/ai/status", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    return r.json()["key_vault_enabled"]


def test_ai_status_reports_key_vault_on(vault, client):
    assert _status_key_vault_flag(client) is True


def test_ai_status_reports_key_vault_off(client):
    assert _status_key_vault_flag(client) is False
