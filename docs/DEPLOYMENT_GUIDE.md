# Deploying from GitHub: server, Vercel, Railway

Step-by-step instructions for taking this repo from GitHub to a running deployment.
Two independent paths — pick one:

- **Path A** — single server, Docker Compose + Caddy (what `deploy/` is built for).
- **Path B** — Vercel (frontend) + Railway (backend), managed PaaS, no server to patch.

See `docs/DEPLOYMENT_OPTIONS.md` for the reasoning behind Path B (why Railway over
Render, why the backend can't be serverless). This doc just executes it.

Both paths need the repo pushed to GitHub and a MongoDB Atlas cluster — do these first.

## 0. Shared prerequisites

**Push to GitHub** (skip if already there):
```
git remote add origin https://github.com/<you>/zero-strike-portal.git
git push -u origin main
```

**MongoDB Atlas** (both paths use this — nothing here runs Mongo as a container):
1. Create a free account at mongodb.com/atlas → create an **M0** (free tier) cluster.
2. Database Access → add a database user (username/password).
3. Network Access → add `0.0.0.0/0`. Railway and Vercel/your VM don't have fixed
   IPs you can allowlist individually, so this is the practical option — rely on the
   database user's password, not IP allowlisting, for access control.
4. Connect → Drivers → copy the connection string:
   `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority`

**JWT secret** (both paths need one):
```
openssl rand -hex 32
```

---

## Path A: single server (Docker Compose + Caddy)

Needs a VM (any provider) with a public IP, a domain's DNS **A record** pointed at
it, and Docker + the Compose plugin installed. Caddy handles TLS automatically via
Let's Encrypt, so no separate cert step.

1. **DNS**: point your domain (e.g. `portal.example.com`) at the VM's IP before
   starting — Caddy requests the TLS cert on first boot and needs it resolvable.

2. **On the VM**, clone the repo and go to the deploy folder:
   ```
   git clone https://github.com/<you>/zero-strike-portal.git
   cd zero-strike-portal/deploy
   ```

3. **Configure env**:
   ```
   cp .env.example .env
   ```
   Edit `.env`:
   | Var | Value |
   |---|---|
   | `CADDY_DOMAIN` | your domain, e.g. `portal.example.com` |
   | `CADDY_EMAIL` | your email (Let's Encrypt renewal notices) |
   | `CORS_ORIGINS` | `["https://portal.example.com"]` (your domain) |
   | `NEXT_PUBLIC_SCANNER_SERVER_ORIGIN` | `https://portal.example.com` |
   Leave `NEXT_PUBLIC_API_BASE_URL=/api/v1` as-is — Caddy proxies `/api/*` to the
   backend on the same origin, so the frontend never needs a separate host.

4. **Configure secrets** (kept out of `.env`/git on purpose):
   ```
   cp secrets/mongodb_uri.txt.example secrets/mongodb_uri.txt
   cp secrets/jwt_secret.txt.example secrets/jwt_secret.txt
   ```
   Put your Atlas connection string in `secrets/mongodb_uri.txt` and the
   `openssl rand -hex 32` value in `secrets/jwt_secret.txt` (no quotes, no trailing
   newline needed either way).

5. **Build and start**:
   ```
   docker compose up -d --build
   ```
   First build compiles the Go scanner from source (`golang:1.26-bookworm`, CGO
   enabled) — expect several minutes. `docker compose logs -f backend` to watch it.

6. **Verify**:
   ```
   curl https://portal.example.com/api/v1/health
   ```
   and open `https://portal.example.com` in a browser — should load the login page
   with a valid TLS cert.

**Redeploying after a push**: `git pull && docker compose up -d --build` on the VM.

---

## Path B: Vercel (frontend) + Railway (backend)

### B1. Backend on Railway

1. railway.app → **New Project** → **Deploy from GitHub repo** → select
   `zero-strike-portal`.
2. This is a monorepo — in the service's **Settings → Source**, set
   **Root Directory** to `backend`. Railway will detect `backend/Dockerfile` and
   build from it automatically (no separate Railway config file needed).
3. **Settings → Networking** → **Generate Domain** — gives you something like
   `zero-strike-backend-production.up.railway.app`. Note this URL, the frontend
   needs it.
4. **Variables**, add:
   | Var | Value |
   |---|---|
   | `MONGODB_URI` | your Atlas connection string |
   | `MONGODB_DB_NAME` | `zerostrike` |
   | `JWT_SECRET` | the `openssl rand -hex 32` value |
   | `CORS_ORIGINS` | `["https://<your-vercel-domain>"]` — fill in after B2, once you know it |
   | `BACKEND_PUBLIC_URL` | `https://<your-railway-domain>` (this service's own URL, from step 3 above) |
   | `FRONTEND_ORIGIN` | `https://<your-vercel-domain>` — fill in after B2, same as `CORS_ORIGINS` |

   `BACKEND_PUBLIC_URL`/`FRONTEND_ORIGIN` are required for GitHub/Azure DevOps "Connect a repo"
   OAuth and password-reset emails to work in production — left at their `localhost` defaults,
   the OAuth redirect_uri won't match what's registered with the provider, and reset-link/
   post-connect redirects will point at `localhost` instead of your real Vercel URL.
5. Deploy (push to `main` triggers it automatically once connected). Watch build
   logs — the scanner-build stage takes a few minutes on first build.
6. **Verify**: `curl https://<your-railway-domain>/api/v1/health`.

Confirm the plan is **Hobby**, not the default trial credit — the backend runs a
persistent background poll loop (see `docs/DEPLOYMENT_OPTIONS.md`), so it must never
sleep or freeze between requests. A free/trial-credit plan that idles the container
will silently stop draining queued cloud scans.

### B2. Frontend on Vercel

1. vercel.com → **Add New Project** → import `zero-strike-portal` from GitHub.
2. **Root Directory** → `frontend` (monorepo — Vercel needs this set explicitly).
   Framework preset auto-detects as Next.js.
3. **Environment Variables**:
   | Var | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | `https://<your-railway-domain>/api/v1` |
   | `NEXT_PUBLIC_SCANNER_SERVER_ORIGIN` | `https://<your-railway-domain>` |
4. **Deploy**. Note the resulting `*.vercel.app` domain (or your custom domain if
   you attach one under **Settings → Domains**).

### B3. Close the loop

Go back to Railway's backend variables and fill in the two placeholders from B1 step 4 that
needed the Vercel domain: `CORS_ORIGINS` (`["https://<your-app>.vercel.app"]`, or your custom
domain if you attached one) and `FRONTEND_ORIGIN` (same value, no brackets — it's a single URL,
not a list). Redeploy the backend service for it to take effect.

**Verify**: open the Vercel URL, log in page should load and API calls (check
Network tab) should hit the Railway domain without CORS errors.

---

## Both paths: create your first admin user

Registration (`/register` or `POST /api/v1/auth/register`) always creates a
`role: "user"` account — nothing bootstraps an admin automatically. After
registering your own account, promote it via Atlas:

Atlas UI → your cluster → **Browse Collections** → `zerostrike.users` → find your
user document → edit → set `role` to `"admin"`. Or via `mongosh`:
```
db.users.updateOne({ email: "you@example.com" }, { $set: { role: "admin" } })
```
Log out and back in — `/admin/users` and `/admin/audit-log` should now render.
