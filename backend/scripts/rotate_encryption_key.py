"""Re-encrypt every Fernet-protected field under the current OAUTH_ENCRYPTION_KEY.

Procedure:
  1. Set a new OAUTH_ENCRYPTION_KEY.
  2. Put the old key in OAUTH_ENCRYPTION_KEY_PREVIOUS (a JSON list).
  3. Run this script (use --dry-run first; it only counts).
  4. Remove OAUTH_ENCRYPTION_KEY_PREVIOUS.

Idempotent: a value that already decrypts under the current key alone is left untouched. Never
prints a secret value, only per-field counts.

Usage (from backend/):
    ./.venv/Scripts/python -m scripts.rotate_encryption_key --dry-run
    ./.venv/Scripts/python -m scripts.rotate_encryption_key
"""

import argparse
import asyncio

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings
from app.db.mongo import connect_to_mongo
from app.models.ai_provider_config import AIProviderConfig
from app.models.oauth_connection import OAuthConnection
from app.models.project_repo import ProjectRepo
from app.models.repo_credential import RepoCredential

FIELDS = [
    (AIProviderConfig, "api_key_encrypted"),
    (OAuthConnection, "access_token_encrypted"),
    (OAuthConnection, "refresh_token_encrypted"),
    (ProjectRepo, "pat_encrypted"),
    (RepoCredential, "pat_encrypted"),
]


def _needs_rotation(value: str, current: Fernet) -> bool:
    try:
        current.decrypt(value.encode())
    except InvalidToken:
        return True
    return False


async def rotate(dry_run: bool = False) -> dict[str, int]:
    """Returns {"Model.field": rows rotated (or that would be, when dry_run)}."""
    if not settings.oauth_encryption_key:
        raise SystemExit("OAUTH_ENCRYPTION_KEY is not set.")
    current = Fernet(settings.oauth_encryption_key.encode())
    multi = MultiFernet([current, *(Fernet(k.encode()) for k in settings.oauth_encryption_key_previous)])
    counts: dict[str, int] = {}
    for model, field in FIELDS:
        changed = 0
        async for doc in model.find():
            value = getattr(doc, field)
            if not value or not _needs_rotation(value, current):
                continue
            changed += 1
            if not dry_run:
                setattr(doc, field, multi.rotate(value.encode()).decode())
                await doc.save()
        counts[f"{model.__name__}.{field}"] = changed
    return counts


async def _main(dry_run: bool) -> None:
    await connect_to_mongo()
    for name, n in (await rotate(dry_run)).items():
        print(f"{name}: {n} row(s) {'would be ' if dry_run else ''}rotated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encrypt stored secrets under the current key.")
    parser.add_argument("--dry-run", action="store_true", help="Count rows only; write nothing.")
    asyncio.run(_main(parser.parse_args().dry_run))
