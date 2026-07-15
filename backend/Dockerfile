# syntax=docker/dockerfile:1

# --- Stage 1: build the CGO-enabled Go scanner binary -------------------------
# CGO is MANDATORY: a CGO_ENABLED=0 build registers zero tree-sitter parsers and
# silently detects nothing (SAST becomes a no-op). The build-time smoke check
# below fails the image build if that ever regresses.
FROM golang:1.26-bookworm AS scanner-builder

ARG SCANNER_REPO=https://github.com/Mohamedashmar432/zero-strike-SAST-engine.git
ARG SCANNER_REF=v0.24.0
ENV CGO_ENABLED=1

WORKDIR /src
# ponytail: no BuildKit secret mount here — Railway's builder rejects any
# `--mount=type=secret` outright (build fails even when unused), and SCANNER_REPO
# is public by default so no auth is needed. Private repo on a builder that
# supports BuildKit secrets? Add the mount back locally; on Railway, build the
# image via CI where secrets work and push to GHCR instead (docs/DEPLOYMENT_OPTIONS.md).
RUN git clone --depth 1 --branch "${SCANNER_REF}" "${SCANNER_REPO}" .
RUN go build -o /out/zerostrike ./cmd/zerostrike

# Smoke check: a real CGO build must find the vulnerable pattern below. A
# parserless build finds nothing and this RUN fails, blocking a broken image.
# ponytail: fires ZS-PY-005 (os.system() command injection) — a single-expression
# rule, not a cross-line taint flow, so it's less likely to silently stop matching
# across scanner versions than the previous SQL-injection fixture (confirmed via
# local docker build against v0.23.1: that fixture no longer matches any rule,
# while CGO/tree-sitter parsing itself is fine — Diagnostics comes back clean).
# If this rule ID also stops matching a future scanner version, update the sample
# rather than dropping the gate.
RUN mkdir -p /smoke && printf '%s\n' \
      'import os' \
      'from flask import request' \
      'def handler():' \
      "    cmd = request.args.get('cmd')" \
      '    os.system(cmd)' \
      > /smoke/vuln.py \
    ; /out/zerostrike scan /smoke --format json > /smoke/out.json 2>/smoke/err.log ; \
    grep -q '"RuleID"' /smoke/out.json \
      && echo "scanner smoke check passed (findings present -> CGO parsers active)" \
      || { echo "=== smoke check FAILED — /out/zerostrike stdout ==="; cat /smoke/out.json; \
           echo "=== stderr ==="; cat /smoke/err.log; exit 1; }

# --- Stage 2: the FastAPI backend --------------------------------------------
FROM python:3.12-slim

# git is needed for server-side cloud-scan cloning; ca-certificates for TLS clone/OSV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=scanner-builder /out/zerostrike /usr/local/bin/zerostrike

WORKDIR /app
# ponytail: one COPY, not two — Railway's remote build cache has been observed
# returning "failed to calculate checksum of ref ...: not found" on a stale/evicted
# COPY layer here; a single instruction avoids depending on that intermediate ref.
COPY . .
RUN pip install --no-cache-dir -e .

# Non-root runtime. Ephemeral clone dir owned by the app user (reports persist in Mongo).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/zs-clones \
    && chown -R appuser:appuser /app /tmp/zs-clones
USER appuser

EXPOSE 8000
# ponytail: shell form, not exec form — Railway assigns its own $PORT and routes
# external traffic there; a hardcoded --port 8000 leaves the app unreachable even
# though it starts up healthy. ${PORT:-8000} keeps 8000 as the default for
# docker-compose/local runs that never set $PORT.
#
# --proxy-headers/--forwarded-allow-ips: this container is never directly internet-exposed
# (only the caddy service publishes ports, per deploy/docker-compose.yml) — Caddy's
# reverse_proxy sets X-Forwarded-For, so trusting it here is what makes request.client.host
# reflect the real visitor IP instead of Caddy's internal container IP (needed for
# per-IP rate limiting on /auth/*). In local dev (no proxy in front), there's no
# X-Forwarded-For header, so uvicorn falls back to the direct-connection peer as before.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
