# Local dev test users

These are **local-dev-only** credentials, seeded by
`backend/scripts/seed_dev_users.py`. They don't exist in production — nothing here
runs a seed step. The app enforces no password complexity rules (any non-empty
string works, per `backend/app/schemas/auth.py`), so these are intentionally simple
and memorable rather than "secure."

| Role | Email | Password | Notes |
|---|---|---|---|
| Platform admin | `admin@zerostrike.dev` | `AdminDev!2026` | Can see `/admin/users`, `/admin/audit-log`. Elevated directly in the DB — there's no public way to self-register as admin. |
| Project owner | `owner@zerostrike.dev` | `OwnerDev!2026` | Owns the seeded "Demo Project". |
| Project collaborator | `collaborator@zerostrike.dev` | `CollabDev!2026` | Pre-accepted `collaborator` member on "Demo Project" — no invite step needed to start testing. |

## (Re)creating them

```
cd backend
./.venv/Scripts/python scripts/seed_dev_users.py
```

Safe to re-run — it looks up by email/project before inserting, so it won't error
or duplicate anything on repeat runs.

Requires `MONGODB_URI` in `backend/.env` to point at a real, reachable MongoDB
(Atlas or local) — see `docs/LOCAL_DEV_SETUP.md`.
