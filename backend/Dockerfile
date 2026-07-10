# syntax=docker/dockerfile:1

# --- Stage 1: build the CGO-enabled Go scanner binary -------------------------
# CGO is MANDATORY: a CGO_ENABLED=0 build registers zero tree-sitter parsers and
# silently detects nothing (SAST becomes a no-op). The build-time smoke check
# below fails the image build if that ever regresses.
FROM golang:1.26-bookworm AS scanner-builder

ARG SCANNER_REPO=https://github.com/zerostrike/scanner.git
ARG SCANNER_REF=v0.22.0
ENV CGO_ENABLED=1

WORKDIR /src
# Private repo? Provide auth via BuildKit secret:
#   docker build --secret id=scanner_git_token,env=SCANNER_GIT_TOKEN ...
RUN --mount=type=secret,id=scanner_git_token \
    sh -eux -c '\
      if [ -f /run/secrets/scanner_git_token ]; then \
        git config --global credential.helper "!f() { echo username=x-access-token; echo password=$(cat /run/secrets/scanner_git_token); }; f"; \
      fi; \
      git clone --depth 1 --branch "${SCANNER_REF}" "${SCANNER_REPO}" .'
RUN go build -o /out/zerostrike ./cmd/zerostrike

# Smoke check: a real CGO build must find the vulnerable pattern below. A
# parserless build finds nothing and this RUN fails, blocking a broken image.
# ponytail: this fixture is tuned to fire ZS-PY SQL-injection taint; if the rule
# set changes and it stops matching, update the sample rather than dropping the gate.
RUN mkdir -p /smoke && printf '%s\n' \
      'import sqlite3' \
      'from flask import request' \
      'def handler():' \
      "    q = request.args.get('q')" \
      "    sql = 'SELECT * FROM users WHERE name = ' + q" \
      "    sqlite3.connect('db').cursor().execute(sql)" \
      > /smoke/vuln.py \
    && /out/zerostrike scan /smoke --format json > /smoke/out.json \
    && grep -q '"RuleID"' /smoke/out.json \
    && echo "scanner smoke check passed (findings present -> CGO parsers active)"

# --- Stage 2: the FastAPI backend --------------------------------------------
FROM python:3.12-slim

# git is needed for server-side cloud-scan cloning; ca-certificates for TLS clone/OSV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=scanner-builder /out/zerostrike /usr/local/bin/zerostrike

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e .

# Non-root runtime. Ephemeral clone dir owned by the app user (reports persist in Mongo).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/zs-clones \
    && chown -R appuser:appuser /app /tmp/zs-clones
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
