# Deployment options: Vercel + Railway/Render

Research/recommendation only — no platform config files created here. The current
production deployment (`deploy/`, single-VM Docker Compose + Caddy) is unaffected;
this is an evaluation of splitting frontend (Vercel) and backend (Railway or Render)
onto managed PaaS platforms instead.

## Frontend → Vercel: clean fit, no caveats

The frontend is a standard Next.js app (`output: "standalone"`, no unusual native
dependencies) — this maps directly onto Vercel's native build (`next build`).
Vercel doesn't use `frontend/Dockerfile` at all; that file stays relevant only to
the current Docker Compose deployment.

Set as Vercel project env vars, pointed at wherever the backend ends up:
- `NEXT_PUBLIC_API_BASE_URL=https://<your-backend-host>/api/v1`
- `NEXT_PUBLIC_SCANNER_SERVER_ORIGIN=https://<your-backend-host>`

## Backend: must be an always-on container, not serverless

`backend/app/main.py`'s `lifespan` spawns a long-lived `asyncio.Task`
(`scan_queue_service.poll_loop()`) that polls every 5s for the life of the process
to drain the Mongo-backed cloud-scan queue and reap stuck scans. **Any host that
freezes or kills the process between requests breaks this silently** — queued cloud
scans just wouldn't get picked up. This rules out Vercel serverless/edge functions
or any Lambda-style FaaS for the backend; it needs Railway's or Render's standard
persistent "web service" tier (an always-running container), not a function.

## Railway vs. Render, for this specific backend

Both support deploying straight from `backend/Dockerfile`. Two things about this
backend matter more than usual for picking between them:

**1. The Docker build is heavy.** The image compiles the *entire separate scanner
repo* from scratch in a `golang:1.26-bookworm` stage with `CGO_ENABLED=1` (needs a
real C toolchain — not a slim/alpine Go image or a "just run `go build`" buildpack),
then gates the build on an actual scan-and-grep smoke test before it's allowed to
finish. There's no existing CI data on how long this takes (the repo's only
workflow never runs `docker build`) — recommend timing `docker build -f
backend/Dockerfile .` locally once before committing to either platform's build
limits. If it turns out slow/flaky on-platform, both Railway and Render support
deploying a pre-built image (build once via GitHub Actions, push to GHCR, point the
platform at the image) instead of building from source on their infra — this
sidesteps build-time limits entirely.

**2. The always-on requirement collides with free tiers differently** (verified
live — training data on PaaS pricing goes stale fast):

- **Render's free web-service tier spins down after 15 minutes of inactivity**
  (30–60s cold start on the next request). For this backend that's a functional
  regression, not just a perf hit: the poll loop stops firing while asleep, so a
  cloud scan queued during that window sits un-drained until *something* happens to
  wake the instance. Render's paid **Starter** tier ($7/mo+) is always-on and has no
  such gap.
- **Railway has no realistic perpetual free tier anymore** — signing up gives a
  30-day/$5 one-time trial credit, which reverts to a $0/mo plan with only $1/mo of
  credit once it's gone (not enough to keep a service running continuously). The
  **Hobby plan** ($5/mo flat fee + $5/mo included usage credit) does give a real
  always-on container with no inactivity-based sleep; one small instance (0.5 vCPU/
  0.5GB) typically runs ~$0.80–1/mo in actual usage, comfortably inside the included
  credit.

**Recommendation: Railway's Hobby plan for the backend.** It's the cheaper way to
get an honestly-always-on process for this specific app, because Render only
matches that once you're paying for its Starter tier or above — Render's free tier
would silently drop queued cloud scans during idle periods, which is a correctness
bug for this app, not a tradeoff. Render is a fine choice if you prefer its
dashboard/ecosystem, but pick at least Starter, not Free.

## What doesn't change

- **MongoDB stays Atlas either way** — it's already the only external managed
  service (`deploy/secrets/mongodb_uri.txt.example` is an Atlas SRV string; Mongo
  was never a container in `deploy/docker-compose.yml`). Splitting compute across
  Vercel/Railway/Render doesn't touch the data layer.
- **Caddy (TLS/reverse-proxy in the current compose stack) becomes unnecessary** —
  Vercel and Railway/Render both terminate TLS and handle custom domains natively.
- Environment variables/secrets move from Docker Compose's file-based secrets
  (`deploy/secrets/*.txt`) to each platform's own encrypted env var store — same
  values (`MONGODB_URI`, `JWT_SECRET`, etc.), different storage mechanism.

## Sources

Render and Railway pricing/behavior facts above were verified via live search this
session (training data is several months stale for fast-moving PaaS pricing):
- [Render Pricing 2026: Plans, Costs and Alternatives](https://kuberns.com/blogs/render-pricing/)
- [Pricing | Render](https://render.com/pricing)
- [Deploy for Free – Render Docs](https://render.com/docs/free)
- [Pricing Plans | Railway Docs](https://docs.railway.com/pricing/plans)
- [Pricing | Railway](https://railway.com/pricing)
- [Free Trial | Railway Docs](https://docs.railway.com/pricing/free-trial)
