"""One-off, idempotent migration: move Fernet-encrypted AI provider keys into Azure Key Vault.

For every AIProviderConfig with `api_key_encrypted` and no `api_key_secret_name`: decrypt, write the
secret, store its name, clear the ciphertext. Re-running skips rows already moved. Needs
AZURE_KEY_VAULT_URL and working Azure credentials (see docs/KEYVAULT_BYOK.md). Prints counts only,
never key values.

Usage (from backend/):
    python scripts/migrate_ai_keys_to_keyvault.py
"""

from __future__ import annotations

import asyncio
import sys

from app.core import security
from app.db.mongo import close_mongo_connection, connect_to_mongo
from app.models.ai_provider_config import AIProviderConfig
from app.services import ai_provider_config_service, secret_store


async def main() -> int:
    if not secret_store.enabled():
        print("AZURE_KEY_VAULT_URL is not set; refusing to run.")
        return 1

    await connect_to_mongo()
    migrated = failed = skipped = 0
    try:
        for config in await AIProviderConfig.find_all().to_list():
            if config.api_key_secret_name or not config.api_key_encrypted:
                skipped += 1
                continue
            try:
                await ai_provider_config_service._store_key(
                    config, security.decrypt_secret(config.api_key_encrypted)
                )
                await config.save()
                migrated += 1
            except Exception as exc:  # noqa: BLE001 - keep going; the row stays on Fernet and can be retried
                print(f"  config {config.id} FAILED: {type(exc).__name__}")
                failed += 1
    finally:
        await close_mongo_connection()

    print(f"migrated {migrated}, skipped {skipped}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
