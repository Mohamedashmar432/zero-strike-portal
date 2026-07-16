# Running ZeroStrike Portal on localhost

Step-by-step guide to get the full stack (backend + frontend + a real MongoDB)
running on your machine, plus how to log in with seeded test accounts. See
`CLAUDE.md` for the terse command reference this doc expands on.

## 1. Prerequisites

- Python >= 3.11, Node (see `frontend/package.json`).
- The sibling scanner repo built, for local/CLI scans:
  ```
  cd ../zero-strike-code-scanner
  go build -o zerostrike.exe ./cmd/zerostrike
  ```
  Build with a C compiler on `PATH` (CGO enabled) if you want real SAST detection —
  a CGO-disabled build still runs but silently finds nothing beyond secrets/SCA/
  framework checks (the binary itself warns about this on scan).

## 2. MongoDB — Atlas free tier

The app always talks to an external MongoDB, in dev and prod alike (nothing here
bundles a local Mongo). Easiest path:

1. Create a free account at mongodb.com/atlas, create a free **M0** cluster.
2. Database Access → add a database user (username/password).
3. Network Access → allow your current IP (or `0.0.0.0/0` for local-dev
   convenience — don't do this for a shared/prod cluster).
4. Copy the connection string (Connect → Drivers) — looks like
   `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?...`.

## 3. Backend `.env`

```
cd backend
cp .env.example .env
```

Fill in (only these 5 are active by default in `.env.example`):

| Var | What to put |
|---|---|
| `MONGODB_URI` | Your Atlas connection string from step 2 |
| `MONGODB_DB_NAME` | Leave as `zerostrike` unless you want a different DB name |
| `JWT_SECRET` | Any random string, e.g. `openssl rand -hex 32` |
| `CORS_ORIGINS` | Leave as `["http://localhost:3000"]` |
| `SCANNER_BINARY_PATH` | Absolute path to the binary built in step 1 |

Everything else in `.env.example` is commented out and **optional**:
`GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`, `AZURE_DEVOPS_CLIENT_ID`/
`AZURE_DEVOPS_CLIENT_SECRET`, `OAUTH_ENCRYPTION_KEY` — only needed if you're testing
GitHub/Azure DevOps repo-import OAuth. `CLONE_WORKDIR_PATH`, `SCAN_TIMEOUT_SECONDS`,
`MAX_CONCURRENT_CLOUD_SCANS` — cloud-scan tuning, defaults are fine for local dev.
Every field in `backend/app/core/config.py` has a default, so the app boots even if
you leave these commented out.

## 4. Frontend `.env.local`

```
cd frontend
cp .env.example .env.local
```

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_SCANNER_SERVER_ORIGIN=http://localhost:8000
```

(These are the only two `NEXT_PUBLIC_*` vars the frontend reads anywhere.)

## 5. Install & run

Use two separate terminals — both servers run in the foreground and stay attached
to their terminal (Ctrl+C to stop).

**Terminal 1 — backend:**
```
cd backend
python -m venv .venv
./.venv/Scripts/pip install -e ".[dev]"
./.venv/Scripts/uvicorn app.main:app --reload
```
The venv only needs creating/installing once; on later runs just re-run the
`uvicorn` line. After "Application startup complete", it's serving on :8000 — but
expect a several-second pause at "Waiting for application startup" first time it
boots: that's `lifespan` opening the connection to your Atlas cluster over the
network, not a hang.

**Terminal 2 — frontend:**
```
cd frontend
npm install
npm run dev
```
Serves on :3000 once you see "Ready".

Open http://localhost:3000.

If either port is already taken (a previous server still running in another
window), `npm run dev` auto-picks the next free port and prints it — use that URL
instead, or find and stop the stale process:
```
netstat -ano | findstr :8000     # or :3000 — last column is the PID
taskkill /PID <pid> /F
```

## 6. Seed test users

```
cd backend
./.venv/Scripts/python scripts/seed_dev_users.py
```

Creates 3 accounts + a demo project — see `docs/TEST_USERS.md` for the exact
emails/passwords. Safe to re-run.

## 7. Verify it's actually working

1. Log in as `owner@zerostrike.dev` — you should land on the dashboard and see
   "Demo Project" under Projects.
2. Open "Demo Project" → Project Tokens tab → generate a token.
3. Run a local scan with the CLI binary from step 1:
   ```
   ./zerostrike.exe scan . --server http://localhost:8000 --token <the generated token>
   ```
   (No `--project-id` needed — the token alone identifies the project.) Confirm the
   scan shows up under the project with findings.
4. Log in as `collaborator@zerostrike.dev` — confirm you also see "Demo Project"
   (proves the seeded membership works).
5. Log in as `admin@zerostrike.dev` — confirm `/admin/users` and `/admin/audit-log`
   render (a non-admin user gets a 403 from the API on these).
