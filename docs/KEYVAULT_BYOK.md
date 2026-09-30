# AI provider keys in Azure Key Vault

Status: in progress on branch `feat/keyvault-byok` (started 2026-09-30).

## Goal

AI provider API keys — both the portal-wide admin keys (`AIProviderConfig.project_id = None`) and
per-project BYOK keys — are stored in Azure Key Vault, not in MongoDB. Mongo keeps only the
secret's *name*. The backend fetches the value at call time.

Before this change the key sat in Mongo as `api_key_encrypted`, a Fernet ciphertext keyed by
`settings.oauth_encryption_key`. Anyone holding a DB dump plus that one env var had every key.

## Design

**Where the key lives.** `AIProviderConfig.api_key_secret_name: str | None`. No key material in
Mongo when the vault is configured.

**Secret naming.** `thinkshield-<project-slug>-<config_id>` for a project key,
`thinkshield-portal-<config_id>` for an admin key. The config id is required, not optional: a scope
holds several provider configs (the failover chain), so project id alone would collide. The slug is
the project name lowercased with every non-alphanumeric run collapsed to `-` and truncated so the
whole name fits Key Vault's 127-char `[0-9a-zA-Z-]` limit. The name is fixed at creation and stored,
so renaming a project never orphans a secret. The project id also goes into the secret's tags
(`project_id`, `config_id`, `scope`) for lookup from the Azure side.

**Backend selection.** `settings.azure_key_vault_url` (env `AZURE_KEY_VAULT_URL`). Empty (the
default, and what tests use) means the vault is off and keys keep the existing Fernet path, so local
dev and the mongomock suite work without Azure. Set means every *new or changed* key goes to the
vault.

**Auth.** `DefaultAzureCredential`, with no credential code of our own:
- prod (Azure Container Apps): the app's managed identity;
- local dev: `az login`, or a service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` /
  `AZURE_CLIENT_SECRET` env vars.

The identity needs the **Key Vault Secrets Officer** RBAC role on the vault. Officer, not User,
because the backend writes, deletes and recovers secrets as well as reading them.

**Client.** The SDK is sync (`azure-keyvault-secrets` + `azure-identity`), and each call runs through
`asyncio.to_thread`, the same pattern `cloud_scan_service` uses for subprocesses. A small in-process
TTL cache (5 min) sits in front of reads.

**Read path** (`ai_provider_config_service.get_api_key`, async):
1. `api_key_secret_name` set → vault (cached);
2. else `api_key_encrypted` set → Fernet decrypt (legacy rows, and vault-off mode);
3. else `None`.

`is_ready` checks *that a key is referenced* and does not fetch it, so building the failover chain
never costs a vault call.

**Write order.** This is chosen so a crash can only orphan a secret, never leave a reference to a
missing one:
- create: allocate the config id → write the secret → insert the doc;
- update with a new key: write a new secret version (same name) → save the doc. The legacy
  `api_key_encrypted` is cleared once a vault name is set;
- clear key: save the doc with the reference removed → soft-delete the secret;
- delete config, delete project, or admin purge: delete the doc(s) → soft-delete the secret(s).

**Soft delete.** Key Vault keeps deleted secrets recoverable for the vault's retention window
(7–90 days). The backend never purges; that is the vault's retention policy's job. Re-setting a key
on a config whose secret was cleared hits a "deleted but recoverable" conflict, so the store
recovers the deleted secret, then writes the new version over it.

**Failure behaviour.**
- Vault unreachable on a write: 503 "Key Vault unavailable, key not saved". Nothing is written to
  Mongo.
- Vault unreachable on a read inside an LLM call: the failure surfaces as `LLMTransientError`, so the
  call fails over to the next config **in the same scope only**. The BYOK rule still holds: a
  project never falls back to the portal key.
- Test-connection routes: the error renders like any other failed test.

**Rotation staleness.** Another replica's cache can serve the previous key version for up to the
5-minute TTL after a rotation. That is acceptable here: providers accept both keys until the old one
is revoked. If it ever matters, lower the TTL.

## Migration

`backend/scripts/migrate_ai_keys_to_keyvault.py` moves every row that has `api_key_encrypted` and no
`api_key_secret_name`: decrypt → write the secret → set the name → clear the ciphertext. It is
idempotent and safe to re-run. It needs `AZURE_KEY_VAULT_URL` plus working Azure credentials.

Until it runs, legacy rows still work through the Fernet fallback. Once every environment is
migrated, a follow-up can drop `api_key_encrypted` and the fallback.

## Infra checklist (per environment)

- [ ] Vault is RBAC-enabled (dev vault: yes).
- [ ] Soft delete on; purge protection recommended in prod.
- [ ] Container App system-assigned identity has **Key Vault Secrets Officer** on the vault.
- [ ] `AZURE_KEY_VAULT_URL` set in the backend env (`backend/.env`, `.env.azure`).
- [ ] Key Vault diagnostic logs routed to Log Analytics, so secret reads are audited outside the app.
- [ ] Dev and prod use separate vaults.

## Out of scope

Repo tokens (`RepoCredential`) and OAuth tokens (`OAuthConnection`) still use Fernet. The same
store can take them later; they are left out to keep this change reviewable.
