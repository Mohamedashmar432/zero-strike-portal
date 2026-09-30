"""Azure Key Vault access for AI provider API keys (design: docs/KEYVAULT_BYOK.md).

The SDK is sync, so every call runs through asyncio.to_thread -- the same pattern
cloud_scan_service uses for subprocesses. Auth is DefaultAzureCredential (managed identity in
Azure, `az login` locally); no credential code of our own. Every Azure failure is re-raised as
SecretStoreError so callers never import azure types.
"""

import asyncio
import re
import time

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from app.core.config import settings

_MAX_NAME = 127  # Key Vault's limit; charset is [0-9a-zA-Z-]
_CACHE_TTL_SECONDS = 300

_client: SecretClient | None = None
# ponytail: per-process cache, so after a rotation another replica can serve the old key for up to
# the TTL. Fine while providers accept both keys; lower the TTL if it ever matters.
_cache: dict[str, tuple[float, str]] = {}


class SecretStoreError(Exception):
    """The vault could not be reached or refused the request."""


def enabled() -> bool:
    return bool(settings.azure_key_vault_url)


def secret_name(config_id: str, project_name: str | None) -> str:
    """`thinkshield-portal-<id>` for an admin key, `thinkshield-<slug>-<id>` for a project key. The
    config id is mandatory: a scope holds several configs (the failover chain)."""
    if project_name is None:
        return f"thinkshield-portal-{config_id}"
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
    slug = slug[: _MAX_NAME - len("thinkshield--") - len(config_id)].strip("-") or "project"
    return f"thinkshield-{slug}-{config_id}"


def _get_client() -> SecretClient:
    global _client
    if _client is None:
        _client = SecretClient(vault_url=settings.azure_key_vault_url, credential=DefaultAzureCredential())
    return _client


def _set(name: str, value: str, tags: dict[str, str]) -> None:
    client = _get_client()
    try:
        client.set_secret(name, value, tags=tags)
    except (ResourceExistsError, HttpResponseError) as exc:
        if not isinstance(exc, ResourceExistsError) and exc.status_code != 409:
            raise
        # The name was soft-deleted (key cleared earlier) and is still recoverable: bring it back,
        # then write the new version over it.
        client.begin_recover_deleted_secret(name).wait()
        client.set_secret(name, value, tags=tags)


def _delete(name: str) -> None:
    try:
        _get_client().begin_delete_secret(name)  # soft delete; not waited on, never purged
    except ResourceNotFoundError:
        pass


async def put(name: str, value: str, tags: dict[str, str]) -> None:
    try:
        await asyncio.to_thread(_set, name, value, tags)
    except Exception as exc:
        raise SecretStoreError(f"Key Vault write failed for {name}") from exc
    _cache[name] = (time.monotonic(), value)


async def get(name: str) -> str:
    hit = _cache.get(name)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    try:
        secret = await asyncio.to_thread(lambda: _get_client().get_secret(name))
    except Exception as exc:
        raise SecretStoreError(f"Key Vault read failed for {name}") from exc
    if secret.value is None:
        raise SecretStoreError(f"Key Vault secret {name} has no value")
    _cache[name] = (time.monotonic(), secret.value)
    return secret.value


async def delete(name: str) -> None:
    _cache.pop(name, None)
    try:
        await asyncio.to_thread(_delete, name)
    except Exception as exc:
        raise SecretStoreError(f"Key Vault delete failed for {name}") from exc
