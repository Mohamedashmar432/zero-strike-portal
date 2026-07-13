# Local dev test users

These are **local-dev-only** credentials, seeded by
`backend/scripts/seed_dev_users.py`. They don't exist in production — nothing here
runs a seed step. The app enforces no password complexity rules (any non-empty
string works, per `backend/app/schemas/auth.py`), so these are intentionally simple
and memorable rather than "secure."

| Role | Email | Password | Notes |
|---|---|---|---|
| Platform admin | `admin@zerostrike.dev` | `AdminDev!2026` | Can see `/admin/users`, `/admin/audit-log`. There's no public way to self-register as admin — `POST /auth/register` always creates a plain `user`. |
| Project owner | `owner@zerostrike.dev` | `OwnerDev!2026` | Owns the seeded "Demo Project". |
| Project collaborator | `collaborator@zerostrike.dev` | `CollabDev!2026` | Pre-accepted `collaborator` member on "Demo Project" — no invite step needed to start testing. |

### Promoting a user to admin

Any existing admin can turn any user into an admin (or revert one back to a plain
user) from **Admin → Users** in the portal, or directly via
`PATCH /api/v1/users/{user_id}` with `{"role": "admin"}` (admin-only, see
`backend/app/routers/users.py`). The same page/endpoint lists every registered
user (`GET /api/v1/users`), paginated.

## (Re)creating them

```
cd backend
./.venv/Scripts/python scripts/seed_dev_users.py
```

Safe to re-run — it upserts by email, and **always resyncs password/name/role**
to the values above, so if one of these accounts drifted (e.g. someone used the
app's change-password flow, or logged in and got promoted/demoted while testing),
re-running this script puts it back to exactly what's documented here.

Requires `MONGODB_URI` in `backend/.env` to point at a real, reachable MongoDB
(Atlas or local) — see `docs/LOCAL_DEV_SETUP.md`.
