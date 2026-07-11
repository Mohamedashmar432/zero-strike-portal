# GitHub / Azure DevOps OAuth Setup

Sprint 4 lets a portal user connect their GitHub and/or Azure DevOps account and import a repo
directly into a cloud scan instead of pasting a URL + access token. The code is already in place;
this doc is what **you** need to configure outside the code for it to work — one OAuth App
registration per provider, plus four settings in `backend/.env`.

Nothing here is required for the rest of the portal (local/CI/CD scans, manual-URL cloud scans) —
it only gates the "Import from GitHub" / "Import from Azure DevOps" pickers.

## 1. Decide your backend's public URL

Both providers redirect the user's browser back to your backend after they approve access, so they
need a URL they can reach — not `localhost` unless you're testing locally with the provider apps
also pointed at `localhost`.

- **Local dev**: `http://localhost:8000` (the default already baked into `config.py`)
- **Production**: your real domain, e.g. `https://portal.example.com` (whatever Caddy fronts)

This value is `BACKEND_PUBLIC_URL` in `backend/.env` — set it *before* registering the OAuth Apps
below, since the callback URLs you register there must match it exactly.

## 2. Register a GitHub OAuth App

1. Go to **github.com/settings/developers** → **OAuth Apps** → **New OAuth App** (use an
   organization's developer settings instead if you want the connection scoped to an org's apps
   page, not required).
2. Fill in:
   - **Application name**: anything recognizable, e.g. "ZeroStrike Portal (local)"
   - **Homepage URL**: your `BACKEND_PUBLIC_URL` (or the frontend origin — GitHub doesn't use this
     value functionally)
   - **Authorization callback URL**: `{BACKEND_PUBLIC_URL}/api/v1/connections/github/callback`
     — e.g. `http://localhost:8000/api/v1/connections/github/callback` for local dev
3. Click **Register application**.
4. Copy the **Client ID** shown on the app page.
5. Click **Generate a new client secret** and copy it immediately — GitHub only shows it once.

You do **not** need to request any special permissions beyond the default; the portal asks for the
`repo` and `read:user` scopes at connect time (visible on GitHub's consent screen when a user
clicks "Connect GitHub").

## 3. Register an Azure DevOps OAuth App

Azure DevOps OAuth Apps are registered on a **separate page** from the main Azure/Entra portal —
don't look for this in portal.azure.com.

1. Go to **app.vsaex.visualstudio.com/app/register** (sign in with the Microsoft account tied to
   your Azure DevOps org).
2. Fill in:
   - **Company name**, **Application name**, **Application website**: anything recognizable
   - **Authorization callback URL**: `{BACKEND_PUBLIC_URL}/api/v1/connections/azure-devops/callback`
     — e.g. `http://localhost:8000/api/v1/connections/azure-devops/callback` for local dev
   - **Authorized scopes**: check **Code (read)** and **Identity (read)**
3. Click **Create Application**.
4. Copy the **App ID** (this is the client ID) and **Client Secret** shown on the confirmation page.

**If the connect flow fails immediately at the Azure DevOps consent screen** with no useful
error: check the target org's policy at **Organization Settings → Policies → "Third-party
application access via OAuth"**. Some orgs (especially ones under stricter conditional-access
policies) have this switched off by default, and there's no client-side fix for that — an org
admin has to turn it on.

## 4. Generate an encryption key (production only)

Connected accounts' access/refresh tokens are encrypted at rest with a
[Fernet](https://cryptography.io/en/latest/fernet/) key. A fixed development key is already baked
into `config.py` so local dev works with no setup — **do not reuse it in production**. Generate a
real one:

```bash
cd backend
./.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 5. Set the environment variables

Add these to `backend/.env` (see `backend/.env.example` for the full commented block):

```
GITHUB_CLIENT_ID=<client id from step 2>
GITHUB_CLIENT_SECRET=<client secret from step 2>
AZURE_DEVOPS_CLIENT_ID=<app id from step 3>
AZURE_DEVOPS_CLIENT_SECRET=<client secret from step 3>
OAUTH_ENCRYPTION_KEY=<key from step 4 — production only>
BACKEND_PUBLIC_URL=http://localhost:8000
FRONTEND_ORIGIN=http://localhost:3000
```

Restart the backend (`uvicorn` picks up `.env` on startup, not live) after editing.

## 6. Try it

1. Log into the portal, open the account menu (top right) → **Integrations**.
2. Click **Connect GitHub** (or **Connect Azure DevOps**) — you're redirected to the provider's
   consent screen, then straight back to the Integrations page with a "Connected" toast.
3. Open any project → **New scan** → **Cloud** → the dialog now shows **Manual URL** /
   **GitHub** / **Azure DevOps** tabs. Pick a repo (Azure DevOps: pick an org, then a project,
   then a repo) and start the scan — no URL or token needed.

## Known caveat to watch for on the first real GitHub-sourced cloud scan

The clone step (`cloud_scan_service.py`) authenticates with `Authorization: Bearer <token>` — this
is confirmed to work for Azure DevOps OAuth tokens, but wasn't empirically verified against a real
GitHub OAuth App token before this shipped (no live GitHub app/network access at implementation
time). If a GitHub-imported cloud scan fails at the clone step specifically (check
`scans/{id}` → error message will say `git clone failed`), the fix is a one-line change in
`cloud_scan_service.py`'s `_clone()`: send `Authorization: Basic <base64("x-access-token:"+token)>`
instead of the Bearer header for GitHub-sourced tokens. Azure DevOps-sourced scans are not affected
either way.
