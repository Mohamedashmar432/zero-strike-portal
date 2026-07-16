# Updating the SAST Engine Version

The scanner (`../zero-strike-code-scanner`, aka the "SAST engine") has its own release cadence,
independent of the portal. This doc is the repeatable process for adopting a new scanner release
here — no new tooling, just the existing `SCANNER_REPO`/`SCANNER_REF` pin plus a rebuild/redeploy.

## 0. Where does the scanner actually run here? (read this first)

The portal does not have the scanner "built in" — it's a separate program (a `zerostrike`/
`zerostrike.exe` file) that the portal launches as a subprocess whenever a cloud scan runs. The
module responsible for that is `backend/app/services/cloud_scan_service.py` —
`_scan_and_ingest()` builds a command starting with `settings.scanner_binary_path` and runs it.
That setting is defined in `backend/app/core/config.py` (`scanner_binary_path`, default
`"zerostrike"` — "find a program called zerostrike on PATH"), overridable via `SCANNER_BINARY_PATH`
in `backend/.env`. It is read **once, at backend startup** (`main.py`'s lifespan) — editing `.env`
while the backend is already running does nothing until you restart it.

There are two entirely separate ways that binary file ends up on disk, and only one applies to any
given machine:

| | Running `uvicorn` directly (local dev) | Running via Docker (`deploy/`) |
|---|---|---|
| Who builds/fetches the scanner binary? | **Nobody — you do, manually** | The Dockerfile does it automatically at image-build time |
| Where does it come from? | A `zerostrike.exe` file you place on disk yourself (built from `../zero-strike-code-scanner`, or downloaded from a GitHub Release) | Cloned + compiled fresh inside the `golang:1.26-bookworm` build stage in `backend/Dockerfile`, which always has a C compiler regardless of your host machine |
| What you touch to update it | The binary file itself, plus `SCANNER_BINARY_PATH` in `backend/.env`, then **restart the backend process** | `SCANNER_REF` in `deploy/.env`/`docker-compose.yml`, then `docker compose build && up -d --build` |

**If Docker isn't installed on your machine, only the local-`uvicorn` column applies to you** — the
"Docker / deploy" instructions in step 3 below are for a deploy box or CI, not something you can run
locally in that case. Building the binary yourself locally also requires a working C compiler
(gcc/MinGW-w64 on PATH) — CGO is mandatory for real detection (see `backend/Dockerfile`'s comment on
this); without one, your only option is downloading a pre-built binary for your OS from the scanner
repo's GitHub Releases page.

## 1. Cut a release in the scanner repo

```
cd ../zero-strike-code-scanner
git tag -a vX.Y.Z -m "..."
git push origin vX.Y.Z
```

Pushing a `v*.*.*` tag triggers `.github/workflows/release.yml`, which builds native binaries on
`ubuntu-latest`/`windows-latest`/`macos-latest` and publishes a GitHub Release with `checksums.txt`.

**Known gap (v0.23.0 as published):** the Windows build job failed on a bug in the third-party
`egor-tensin/setup-mingw@v2` action (its Chocolatey-installed MinGW v16.1.0 tries to remove a
`libpthread.dll.a` that doesn't exist in that package), so `v0.23.0`'s GitHub Release shipped with
linux+darwin binaries only, no Windows asset. `.github/workflows/release.yml` has since been
updated to drop that action entirely and rely on `windows-latest`'s preinstalled MinGW-w64 toolchain
instead — check whether that change has been committed/pushed and a release actually run with it
before assuming a Windows binary exists for a given version; if not, you're in the same boat as
`v0.23.0` and need to either build locally (requires a C toolchain) or wait for the next release.

Verify the release before moving on:
- GitHub Release for the tag has the expected binaries (`zerostrike_<os>_<arch>`) + `checksums.txt`.
- Watching `gh run list`/the Actions tab, or via the API if `gh` isn't installed locally:
  `GET /repos/Mohamedashmar432/zero-strike-SAST-engine/releases/tags/vX.Y.Z`.

## 2. Bump the version pin in the portal

Three files, all in `zero-strike-portal`:

- `backend/Dockerfile` — `ARG SCANNER_REF=vX.Y.Z` (and `ARG SCANNER_REPO=...` only if the scanner's
  remote ever changes, which it shouldn't in normal operation).
- `deploy/docker-compose.yml` — matching `SCANNER_REF: ${SCANNER_REF:-vX.Y.Z}` default.
- `deploy/.env.example` — `SCANNER_REF=vX.Y.Z` (the documented prod pin; if you have a real
  `deploy/.env` on a deploy box, bump it there too — `.env` is gitignored and not templated from
  `.env.example` automatically).

## 3. Adopt it

**Local dev**: rebuild the binary from the tagged source (`make build-release VERSION=vX.Y.Z` in
the scanner repo — requires a working CGO toolchain, i.e. `gcc`/MinGW on PATH) or download the
pre-built binary for your OS/arch from the GitHub Release. Confirm `backend/.env`'s
`SCANNER_BINARY_PATH` still points at the file you just replaced, then **restart the backend
process** — `.env` is only read once at startup (`cloud_scan_service.py`), so a config change alone
does nothing until the process restarts. Sanity check: `./zerostrike --version` should print the
new tag, not `dev` or the old version.

**Docker / deploy**: from `deploy/`, run:

```
docker compose build backend
docker compose up -d --build
```

This re-clones the scanner repo at the new `SCANNER_REF` inside the `golang:1.26-bookworm` build
stage (which has a real C toolchain, so CGO always works here regardless of what's available on
your local machine), rebuilds, and re-runs the existing build-time smoke check (fails the image
build outright if CGO/tree-sitter detection ever regresses).

## 4. Publish to the self-hosted-CI download endpoint (REQUIRED — do not skip)

Separate from the above — this portal also serves scanner binaries to external CI/CD pipelines
(GitHub Actions, GitLab CI, Azure Pipelines) via GridFS, unrelated to how the portal runs its own
cloud scans. The portal's own "New scan → CI/CD" onboarding UI (`frontend/.../scans/new/page.tsx`)
unconditionally generates a `curl .../downloads/zerostrike/latest/linux-amd64` step for every user,
on every provider, because all three providers' default runners are Linux — so this is not
optional for any deployment that has real users setting up CI/CD scans. Skipping it means every
one of those pipelines 404s (see `docs/CICD_SCAN_BINARY_404.md` for the incident this caused).

Upload each OS/arch binary from the GitHub Release (admin JWT required, one call per
`(version, os, arch)`, no UI yet):

```
curl -X POST {BACKEND_PUBLIC_URL}/api/v1/admin/downloads/zerostrike \
  -H "Authorization: Bearer <admin JWT>" \
  -F "version=vX.Y.Z" -F "os=linux" -F "arch=amd64" \
  -F "file=@zerostrike_linux_amd64"
```

At minimum, publish `linux-amd64` every time — it's the only arch any current CI/CD onboarding
snippet asks for. `../zero-strike-code-scanner`'s `.github/workflows/release.yml` has a
"Publish binaries to the ZeroStrike portal" job that automates all five `(os, arch)` combos after
every tagged release (needs `ZS_PORTAL_ADMIN_EMAIL`/`ZS_PORTAL_ADMIN_PASSWORD` secrets configured
in that repo) — prefer fixing it there once over remembering this manual step per release.

## Verification

- `Scan.scanner_version` / `Report.scanner_version` on a freshly ingested scan should read the new
  tag (the scanner embeds its own version in the JSON report; the portal never gates on it, just
  records it).
- `cd backend && ./.venv/Scripts/pytest` should pass regardless — these are config/build changes,
  not application logic.
