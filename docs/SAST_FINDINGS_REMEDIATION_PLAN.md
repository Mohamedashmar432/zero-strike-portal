# SAST findings remediation plan (portal self-scan, 2026-10-16)

Status: plan only, nothing implemented. Source: thinkShield report scan `6ad1b436` (2026-10-16) of this
repository's Azure DevOps mirror, branch `main`, 25 findings (18 high, 7 medium). Triage against the code
on `master`: 1 true positive, 9 low-value true positives, 15 false positives (60% FP rate).

The scanner (`../zero-strike-code-scanner`) is an independent repo with its own release cadence. This plan
keeps the two sides apart: **Workstream A** changes only this repo; **Workstream B** changes only the scanner
and reaches the portal solely through a new scanner tag pinned via `SCANNER_REF`. No secret values appear in
this document; the committed Fernet key, the JWT dev default and the seed passwords are referred to by
location only.

## 1. Goal and success metrics

Goal: remove the one real exposure (committed Fernet key), harden the low-value items that are cheap to
fix, and fix the scanner rules behind the 15 false positives without losing recall.

| Metric | Measured on | Target |
|---|---|---|
| M1, scanner precision | Re-scan of the **unchanged** portal commit with the new scanner build | 25 to **9** findings. All 15 FPs gone. `ZS-PY-146` on `backend/app/core/config.py` (the TP) still reported. |
| M2, portal hardening | Re-scan of the patched portal with the new scanner build | **1** finding (Popen, now `ZS-PY-147`, medium). The count is 4 if the seed-password suppressions (A6) are rejected. |
| M3, recall guard | `zerostrike-bench` gate in scanner CI | `--min-recall 0.90 --max-fp 0` still passes. Every changed rule ships with one positive fixture that still fires and one negative fixture taken from the portal false positive. |

The 9 findings left under M1: `ZS-PY-146` (TP), `ZS-PY-070` jwt default, Popen, 3 seed passwords, SHA1, empty
except, ip-address. `ZS-PY-020` stops firing on the JWT default because its value contains a placeholder
token, the same rule `ZS-PY-140/141` already apply. `ZS-PY-070` still reports that line, so it is
deduplicated, not lost.

M2 removes 8 of the 9: TP (A1), PY-070 (A1), SHA1 (A7), empty except (A5), ip-address (A8), 3 seed lines
(A6). The Popen residual is intentional (section 5).

## 2. Workstream A: portal fixes (this repo)

Constraints: backend tests run on mongomock (`./.venv/Scripts/pytest`), ruff line-length 110. Uncommitted
work already touches `backend/app/schemas/scan.py` and `backend/app/services/ai_remediation_service.py`, so
land it first or rebase A4 onto it.

### A1. Startup guard + remove the committed key (TP and JWT low-value TP)

**How "dev" is detected.** No existing setting reliably separates dev from prod. Each candidate fails:
- `cors_origins`, `frontend_origin`, `backend_public_url` default to localhost, and `deploy/.env.example` never
  sets the last two, so a compose deploy would read as dev.
- `trusted_proxy_hops` happens to be 1 in every image (Dockerfile `ENV`), but tying a secret guard to the
  proxy hop count is accidental coupling.
- `secrets_dir` existing on disk does not hold on ACA, which uses env secretrefs.

Decision: add `app_env: Literal["development", "production"] = "production"` to `Settings`. It **fails
closed**. A deploy that forgets the variable is treated as production and guarded. Only a developer's
`.env` (and the test conftest) opts into `development`.

Edits in `backend/app/core/config.py`:
- Line 10: `jwt_secret: str = ""` (drop the literal).
- Line 156: `oauth_encryption_key: str = ""` (drop the literal). Rewrite the comment at lines 153-155.
- Add `oauth_encryption_key_previous: list[str] = []`. These keys are decrypt-only, for rotation.
- Add a pure function `production_secret_problems(s: Settings) -> list[str]`:
  - JWT: problem if `jwt_secret` is empty or shorter than 32 characters. This also rejects the old
    `.env.example` default by length, so no literal is needed for comparison.
  - Fernet: problem if `oauth_encryption_key` is empty or `Fernet(key)` raises. The same check runs on each
    `oauth_encryption_key_previous` entry.
- Add a `model_validator(mode="after")` on `Settings`:
  - production: raise `ValueError` listing every problem (names only, never values). `settings = Settings()`
    then fails at import, uvicorn never binds, and the container crash-loops with a readable message.
  - development with empty `jwt_secret`: set it to `secrets.token_urlsafe(48)` and `warnings.warn(...)`.
    Logging is not configured yet at that point. Tokens die on restart, which is acceptable for dev.
  - development with empty `oauth_encryption_key`: warn only.

Edits in `backend/app/core/security.py` (lines 82-89):
- Build a `MultiFernet([current, *previous])` once.
- `encrypt_secret` uses the current key.
- `decrypt_secret` tries all keys.
- If the key is empty, raise `RuntimeError("OAUTH_ENCRYPTION_KEY is not set ...")` naming the setting.

Edit in `backend/tests/conftest.py` (top env block): set `APP_ENV=development`, set `OAUTH_ENCRYPTION_KEY`
to `Fernet.generate_key().decode()`, and set a 64-char random `JWT_SECRET`.

**Rotation path.** Required if production ever ran on the committed key, and for every existing dev DB. Add
`backend/scripts/rotate_encryption_key.py`. It uses `MultiFernet.rotate()` to re-encrypt these fields:
- `AIProviderConfig.api_key_encrypted`
- `OAuthConnection.access_token_encrypted` and `refresh_token_encrypted`
- `ProjectRepo.pat_encrypted`
- `RepoCredential.pat_encrypted`

It is idempotent, supports `--dry-run` (counts only), and never prints a value. Procedure:
1. Set a new `OAUTH_ENCRYPTION_KEY`.
2. Put the old key in `OAUTH_ENCRYPTION_KEY_PREVIOUS`. Developers take it from git history themselves; it is
   not copied into docs.
3. Run the script.
4. Remove `_PREVIOUS`.

Tests, new file `backend/tests/test_config_guard.py`. Construct with `Settings(_env_file=None, ...)`.
- Production with empty or short `jwt_secret` raises, and the message names `JWT_SECRET`.
- Production with empty or invalid Fernet key raises, naming `OAUTH_ENCRYPTION_KEY`.
- Production with valid values constructs.
- Development with empty JWT gets a random value of at least 32 characters and emits a warning.
- `decrypt_secret` reads a token made with a previous key, and `encrypt_secret` output decrypts with the
  current key alone.

Tests, new file `backend/tests/test_rotate_encryption_key.py`: seed one row per field under key A, rotate to
key B, then assert:
- every row decrypts with B alone;
- a second run changes 0 rows;
- `--dry-run` writes nothing.

### A2. Deploy and docs (no code)

- `deploy/docker-compose.yml`:
  - Add the secret `oauth_encryption_key: file: ./secrets/oauth_encryption_key.txt` and list it under
    `backend.secrets`.
  - pydantic reads `/run/secrets/oauth_encryption_key` through the existing `secrets_dir`.
  - Add `deploy/secrets/oauth_encryption_key.txt.example` with generation instructions only.
- `deploy/.env.example`, line 45: change it to list `MONGODB_URI, JWT_SECRET, OAUTH_ENCRYPTION_KEY` as
  required secrets. Add a note that `APP_ENV` defaults to `production`.
- `backend/.env.azure.example`, line 28: make it required as `OAUTH_ENCRYPTION_KEY=secretref:oauth-encryption-key`,
  and move it out of the "Optional" block. AI provider keys and PATs are encrypted with it whether or not
  OAuth is used.
- `backend/.env.example`:
  - Add `APP_ENV=development`.
  - Set `JWT_SECRET=` blank, with an `openssl rand -hex 32` hint.
  - Uncomment `OAUTH_ENCRYPTION_KEY=` with its generation one-liner, and add a pointer to the rotation script
    for existing dev DBs.
- `docs/DEPLOYMENT_GUIDE.md`, `docs/LOCAL_DEV_SETUP.md`, `docs/oauth_connections_setup.md`, `README.md` (line 46):
  same three secrets, same `APP_ENV` note.
- `docs/AI_BYOK_AND_ANALYTICS.md` (line 131): replace "committed dev default, no rotation path" with a pointer
  to the rotation script.

Verification: `cd deploy && docker compose config --quiet`. Then run `grep -rn OAUTH_ENCRYPTION_KEY deploy backend/.env*.example docs`,
which must show every surface.

### A3. Deployment gate for A1 (must precede merge to the deployed branch)

Prod is Azure Container Apps. A1 crash-loops any deployment missing either secret. Before merge, the owner
lists env **names only**, for example:

```
az containerapp show -n <backend-app> -g <rg> --query "properties.template.containers[0].env[].name"
```

On the compose host, check that `deploy/secrets/oauth_encryption_key.txt` exists (`test -s`) without printing
it. If production has no override, it is running on the committed key. Rotate first (A1 procedure), then
deploy A1. See the open questions in section 6.

### A4. Branch argv validation (Popen low-value TP)

Facts:
- Clone argv is built at `backend/app/services/cloud_scan_service.py:289-292` and
  `backend/app/services/git_workspace.py:128-135` as `--branch <value>`.
- git's option parser consumes the next argv as the value, so a leading `-` becomes a bogus branch name, not
  an option. Exploitability is low.
- Only `git_workspace.remote_head` (line 154) validates today, with `_BRANCH_RE` (line 145).

Change:
- Move that check into `backend/app/core/git_ref.py: validate_branch_name(value) -> str`. It keeps the
  regex, rejects a leading `-` and `..`, and caps length at 255.
- Use it in four places:
  1. a `field_validator("branch")` on `ScanCreateRequest` (`backend/app/schemas/scan.py:15`; 422 at write time);
  2. `selected_branch` in `backend/app/schemas/project_repo.py` (lines 24, 52, 67);
  3. as defense in depth, at the top of `cloud_scan_service._clone` and `git_workspace.clone_repo`, raising
     the module's own error before any subprocess runs;
  4. `remote_head`, which drops its inline copy.
- Do **not** add it to `ScannerCreateScanRequest.branch`. That value is CI display metadata that never
  reaches git, and an upload must not fail over metadata (same rule as `sanitize_repo_url`).

Tests:
- `backend/tests/test_cloud_scan_service.py`: POST a cloud scan with branch `-x`, `--upload-pack=y` and `a..b`
  and expect 422.
- A monkeypatched `_run` that fails the test if it is called proves `_clone` refuses before spawning git.
- A valid `feature/x-1.2` still clones in the existing happy-path test.

### A5. Narrow the empty except (`backend/app/services/project_stats_service.py:48-51`)

Change it to `except (InvalidId, TypeError): continue`, importing from `bson.errors`, with a one-line comment
saying legacy rows may carry a non-ObjectId `created_by`. `ZS-PY-024` requires `broad: true`, so this clears
the finding. More importantly, a real bug no longer hides behind `Exception`.

Test (`backend/tests/test_dashboard_stats.py`): `_resolve_scanner_names` over scans whose `created_by` values
are `"not-an-oid"`, `None` and a valid user id returns only the valid user's name.

### A6. Seed script guard (`backend/scripts/seed_dev_users.py`)

The real risk is not the documented dev passwords. It is this script resetting an admin password against
whatever `MONGODB_URI` points at. The guard goes at the top of the `__main__` block (line 134), before any
connection:
- if `settings.app_env != "development"`, print a refusal naming `APP_ENV` and `sys.exit(2)`;
- echo the target DB name (`settings.mongodb_db_name`) in the confirmation prompt.

The literals stay because `docs/TEST_USERS.md` and `tests/test_seed_dev_users.py` depend on them. Annotate
lines 30, 31 and 35 with `# zerostrike-ignore: ZS-PY-141 -- dev-only accounts documented in docs/TEST_USERS.md;
script refuses outside APP_ENV=development`. The scanner's `internal/suppress` honors rule-scoped markers.

Test (`backend/tests/test_seed_dev_users.py`): call the extracted `main()` with `settings.app_env`
monkeypatched to `production`. Expect `SystemExit(2)` and no `connect_to_mongo` call (monkeypatched sentinel).

### A7. SHA1 dedup key (`backend/app/routers/ai_remediation.py:673`)

Add `usedforsecurity=False` to the `hashlib.sha1(...)` call. The digest is byte-identical, so queued-job dedup
is unchanged. If B9 is not shipped, the fallback is `# zerostrike-ignore: ZS-PY-011`.

Test (`backend/tests/test_remediation_batch_apply.py`): for a fixed id list, `_apply_scope_key` equals the
previous expression computed inline in the test without the flag, and a single id keeps the `apply:{id}` shape.

### A8. ip-address advisory (`frontend/package-lock.json`)

The chain is `shadcn` to `@modelcontextprotocol/sdk` to `express-rate-limit` to `ip-address@10.2.0`.
`npm audit` reports `<=10.7.0` vulnerable, the latest is 10.7.4, and the fix is in range.

Steps:
1. Run `cd frontend && npm update ip-address`.
2. Run `npm ls ip-address`, which must show 10.7.1 or later.
3. Fallback: `"overrides": {"ip-address": "^10.7.4"}` in `package.json`.

Follow-up: consider moving `shadcn` (a CLI) from `dependencies` to `devDependencies`.

Verify with `npm run lint` and `npx tsc --noEmit`. Do **not** run `npm run build` while `npm run dev` is up.

## 3. Workstream B: scanner rule fixes (`../zero-strike-code-scanner`, separate PRs and release)

Layout confirmed at v0.37.0:
- Rules: `internal/rules/data/<lang>/ZS-*.yaml`.
- Filter schema: `internal/rules/loader.go` (`filterYAML`) and `internal/rules/rules.go`.
- Evaluation: `internal/engine/engine.go` (`evalFilter`, about lines 330-460).
- Secrets: `internal/scanner/secrets/scanner.go`.
- Positive fixtures: `benchmark/corpus/<lang>/cases/*` plus `manifest.yaml`.
- Negative fixtures: `benchmark/corpus/fp/cases/*` with `expect: []`, gated at `--max-fp 0`.
- Unit-level fixtures: `internal/engine/integration_precision_test.go` (`//go:build cgo`; helpers
  `loadPythonRules`, `matchSource`, `loadTSRules`, `matchTSSource`, `hasRule`).

Every change gets both directions: a `TestPrecision_*` test plus an fp-corpus file for the false positive,
and a positive test or corpus case for recall.

### B1. ZS-PY-020 Hardcoded Credential (8 FPs)

Root cause: it matches on the name alone (`password|secret|api_key|token`). It lacks the value filters that
the sibling rules `ZS-PY-140/141` already carry. The sentinel-name filter is also anchored as
`^[$@]?(INSECURE|PLACEHOLDER|...)_`, so `_PLACEHOLDER_API_KEY` with its leading underscore escapes it.

Changes in `internal/rules/data/python/ZS-PY-020.yaml`:
- (a) Change the sentinel prefix anchor to `^[$@_]*`.
- (b) Copy PY-140's two `rhs_literal` not-filters: the placeholder vocabulary, and the exact sentinel values
  `bearer|basic|none|true|...`.
- (c) Add a `not: lhs_identifier` metadata-suffix filter:
  `(?i)(_url|_uri|_endpoint|_type|_scheme|_name|_id|_header|_prefix|_path|_field|_param)$`.
  This covers `TOKEN_URL`, `token_type`, and `repo_token_auth_scheme`, including the conditional expression
  at `scans.py:156`, whose whole text matches the loose `rhs_literal`. Use the suffix filter rather than
  tightening `rhs_literal`, which would drop literal credentials inside conditional expressions.

Fixtures:
- Negative: `benchmark/corpus/fp/cases/credential_shaped_names.py` holding the 7 portal shapes (scheme
  annotations, conditional, `token_type`, two `TOKEN_URL`s, `_PLACEHOLDER_API_KEY`).
- Positive: keep `TestPrecision_OrdinaryHardcodedCredentialStillFires`. Add `api_token = "<synthetic 32-char
  mixed alnum>"` and `_SECRET_TOKEN = "<synthetic>"`, so a leading underscore alone does not suppress.

FN risk: a real secret held in a variable whose name ends in a metadata suffix, such as `auth_header =
"Bearer <token>"`. Mitigation: `ZS-SEC-*` value-shape detectors still cover known token formats. Add an
`auth_header` positive to the secrets corpus to document the boundary.

### B2. ZS-PY-141 Hardcoded Credential in Object/Kwarg (`"secret": "Secrets"` in pdf_report_service.py:38)

Change: extend the second not-filter's alternation in `ZS-PY-141.yaml` to plural and label forms:
`(secrets?|passwords?|tokens?|credentials?|api[ _-]?keys?)`. Apply the same change to `ZS-TS-141` and
`ZS-JS-141` for parity.

Fixtures:
- Negative: `fp/cases/label_map.py` (`{"secret": "Secrets", "password": "Passwords"}`).
- Positive: the existing `python/cases/vuln_hardcoded_creds.py`, plus a precision test showing that a
  seed-style `{"password": "<synthetic mixed>"}` still fires.

FN risk: a password literally equal to its own label. This is negligible, and the case is already excluded
for the singular form.

### B3. ZS-SEC-003 generic-api-key (`has_api_key=ai_provider_config_service.has_api_key(config)`)

Root cause: the pattern `api[_\-]?key\s*[:=]\s*["']?([a-zA-Z0-9_\-]{20,64})["']?` has an optional quote. It
matches inside `has_api_key=` and captures a module name.

Change in `internal/scanner/secrets/scanner.go`:
- Capture the opening quote as its own group.
- Switch `scanContent` to `FindSubmatchIndex` for this detector, using a new `detector` flag such as
  `rejectCodeRefs`.
- Reject an **unquoted** capture when it is followed by `.`, `(` or `[`, or when it is all-lowercase
  snake_case with at least one `_`, which is the shape of an identifier.

Dotenv and compose lines are already handled by the structured passes, so unquoted real keys in those
files are unaffected.

Tests in `scanner_test.go`:
- `TestSecretsScanner_APIKey_CallExpressionNotFlagged` (the portal line).
- `TestSecretsScanner_APIKey_UnquotedYAMLStillFlagged` (`api_key: <synthetic high-entropy>`).
- The existing `TestSecretsScanner_APIKey_HighEntropy` must stay green.
- Negative corpus: `fp/cases/api_key_kwarg_call.py`.

FN risk: an unquoted key that is lowercase snake_case. Real keys are almost never that shape.

### B4. ZS-TS-055 / ZS-JS-057 setInterval (`frontend/components/queue/queue-tag.tsx:16`)

Root cause: `ZS-TS-055` has a bare `tainted_argument: true`. It has no index, no `require_real_source`, and
no function-argument exclusion. Its sibling `ZS-TS-054` (setTimeout) already received all three.

Change:
- Copy TS-054's filter block verbatim into `ZS-TS-055.yaml`: `tainted_argument_index: 0`,
  `require_real_source: true`, and `argument_kind_not_at {index: 0, kinds: [function_def]}`.
- Add the `argument_kind_not_at` block to `ZS-JS-057.yaml`.

Fixtures:
- Negative: `fp/cases/arrow_setinterval.tsx` (the queue-tag shape), plus a `TestPrecision_ArrowFunctionSetIntervalSuppressed`.
- Positive: the existing `ts/cases/vuln_setinterval_string.ts` (`location.hash` source), plus a mirror of
  `TestPrecision_RealSourceStillFiresSetTimeout` for setInterval.
- Also confirm that `.tsx` routes to the TS rule set.

FN risk: a string built from a parameter that a caller feeds from a real source. TS-054 accepted the same
trade-off.

### B5. ZS-PY-065 rmtree (2 FPs, `backend/app/services/workdir_hygiene.py:63,65`)

Root cause: `path` is a parameter of `rmtree_logged`. Every parameter is seeded as weak taint, and every
caller passes a `mkdtemp` result.

Change: add `require_real_source: true` to the existing filter in `ZS-PY-065.yaml`.

Fixtures:
- Negative: `fp/cases/rmtree_helper_param.py` (the helper plus a `tempfile.mkdtemp` caller).
- Positive: the existing `python/cases/vuln_shutil_rmtree.py` (`request.args` real source).

FN risk, the highest in this plan: a helper deleting a parameter that a request handler in another function
fills. Before merging, run the positive two-function variant through `matchSourceWithGraphs(..., true)`:
- If interprocedural flow still reports it, add it as a positive fixture.
- If it does not, record it as a known gap in `benchmark/README.md`. Do not ship silently.

### B6. ZS-PY-022 Sensitive Value Logged (3 FPs)

Root cause: `argument_identifier_matches` (engine.go:411) matches any identifier anywhere in the argument
subtree. That includes:
- keyword **names** (`secret_name=`);
- metadata identifiers (`config.api_key_secret_name`);
- arguments already wrapped in a sanitizer (`git_workspace.sanitize(str(exc), token)`).

Change: add an engine filter rather than a `not:` filter. A `not:` filter would suppress a whole call that
logs a secret alongside a `_name` field.
- New filter field `logged_identifier`, with `pattern`, `exclude_suffix` and `sanitizer_callee` (regexes).
  Add it to `filterYAML` (loader.go), `Filter` (rules.go, with a doc comment), and the regex compile checks in
  `validator.go`.
- Evaluate it in `engine.go` next to `ArgumentIdentifierMatches`. It walks argument subtrees with three
  differences:
  1. keyword-argument name nodes are skipped (values only);
  2. it does not descend into a call whose callee matches `sanitizer_callee` (`(?i)(sanitiz|redact|mask|scrub|hash)`);
  3. each identifier must match `pattern` and must not match `exclude_suffix`
     (`(?i)_(name|id|type|scheme|url|path|count|len|prefix)$`).
- `ZS-PY-022.yaml` switches to it. Leave `ArgumentIdentifierMatches` untouched, because other rules use it.

Tests in `integration_precision_test.go`:
- Negatives: the three portal lines.
- Positives: `logging.info(password)` (existing corpus), `logger.warning("x", token=token)`, and
  `logger.info("x", user_name=u, password=pw)`. The last proves per-identifier, not per-call, evaluation.
- Negative corpus: `fp/cases/logging_secret_metadata.py`.

FN risk: a custom sanitizer that does not actually redact. The callee regex is deliberately narrow.

Verify first: how the Python IR represents a keyword argument (whether the name is an Identifier child or
only `Attrs["kwarg_name"]`). Dump one parse in a scratch test.

### B7. ZS-PY-057 Popen severity (FP class 5; the portal instance stays as a low-value TP)

Root cause: `cmd` is a `list[str]` parameter with `shell` unset. Parameter-only taint reported it as High
CWE-78, but the worst case is argument injection.

Change:
- `ZS-PY-057.yaml` keeps High but adds `any_of: [{tainted_argument, tainted_argument_index: 0,
  require_real_source: true}, {kwarg: {name: shell, value_pattern: "^True$"}}]`.
- New `ZS-PY-147.yaml`, "subprocess argv built from a function parameter": medium, confidence low, CWE-88.
  It matches `tainted_argument_index: 0` and carries a `not:` of the same real-source/shell condition.

Nothing previously reported is dropped; it is re-graded. Fixtures:
- `vuln_subprocess_popen.py` stays on 057.
- New `python/cases/vuln_subprocess_param_argv.py` expects 147.
- A precision test asserts the portal shape gives 147 and not 057.

Check that `internal/findings/deduplicator.go` (which references rule titles) does not merge 147 into 057.

### B8. ZS-PY-011 SHA1 (optional, pairs with A7)

Change: add `not: {kind: call, filters: [{kwarg: {name: usedforsecurity, value_pattern: "^False$"}}]}` to
`ZS-PY-011.yaml` and `ZS-PY-007.yaml`.

Fixtures:
- Negative: `fp/cases/sha1_not_for_security.py`.
- Positive: the existing `vuln_sha1.py`, plus a `usedforsecurity=True` case that still fires.

FN risk: an author asserting the flag falsely. It is an explicit, greppable claim, the same trust model as
a suppression comment.

### B9. Corpus baseline and release

- Regenerate `baseline.json` from `zerostrike-bench --json-out`, because B7 adds a rule and fixtures.
- Add release notes under `docs/release-notes/`.
- Tag the next scanner minor (v0.38.0).

Portal follow-up:
- Bump `SCANNER_REF` in `backend/Dockerfile` (ARG, line 8), the `deploy/docker-compose.yml` fallback, and
  `deploy/.env.example`.
- In the tb-SAST-portal mirror, keep its own newer `SCANNER_REF` rule.

## 4. Ordered task list

Each portal task is one PR-sized change. B tasks are independent of A until T-B10.

| # | Task | Verify |
|---|---|---|
| T0 | Baseline: build scanner HEAD (v0.37.0). Re-scan a clean export of portal `master` (`git archive master` into scratch, which avoids untracked dirs like `brag-output-*`) with the cloud flags. Record count and IDs. Some FPs may already be fixed after v0.36.1. | `zerostrike scan <export> --format json --enable-secrets --enable-sca --enable-framework-checks > t0.json`, then count the findings array |
| T-A3 | Owner confirms prod env/secret **names** (A3). Blocks merging T-A1. | Owner sign-off |
| T-A1 | `app_env`, guard, MultiFernet, conftest | `cd backend && ./.venv/Scripts/pytest tests/test_config_guard.py -q && ./.venv/Scripts/pytest -q && ./.venv/Scripts/ruff check .` |
| T-A1b | Rotation script | `./.venv/Scripts/pytest tests/test_rotate_encryption_key.py -q` |
| T-A2 | Deploy and docs | `cd deploy && docker compose config --quiet` |
| T-A4 | Branch validation | `./.venv/Scripts/pytest tests/test_cloud_scan_service.py tests/test_remediation_apply.py -q` |
| T-A5 | Narrow except | `./.venv/Scripts/pytest tests/test_dashboard_stats.py -q` |
| T-A6 | Seed guard and suppressions | `./.venv/Scripts/pytest tests/test_seed_dev_users.py -q` |
| T-A7 | SHA1 `usedforsecurity=False` | `./.venv/Scripts/pytest tests/test_remediation_batch_apply.py -q` |
| T-A8 | ip-address bump | `cd frontend && npm update ip-address && npm ls ip-address && npm run lint && npx tsc --noEmit` |
| T-AQ | Restart the backend on :8001 without `--reload`. Confirm boot under `APP_ENV=development`. Confirm boot is **refused** with `APP_ENV=production` and an empty key. Browser pass on the new-scan form: a branch of `-x` shows a readable 422 toast. | Per CLAUDE.md "Definition of done" |
| T-B1..B8 | One scanner PR per rule (B1-B8) | `go test ./internal/rules/... ./internal/scanner/secrets/... -count=1` and `CGO_ENABLED=1 go test ./internal/engine/ -run TestPrecision -count=1` |
| T-B9 | Corpus gate, baseline, tag | `go run ./cmd/zerostrike-bench --corpus benchmark/corpus --min-recall 0.90 --max-fp 0` |
| T-M1 | Re-scan the **T0 export** with the new build | Target 9 findings; `ZS-PY-146` present at `backend/app/core/config.py` |
| T-B10 | Bump portal `SCANNER_REF` | Backend image build smoke check passes (Dockerfile) |
| T-M2 | Re-scan the patched portal export | Target 1 (`ZS-PY-147`, `cloud_scan_service.py`) |

CGO note: engine integration tests need a C toolchain. On Windows without gcc, rely on scanner CI.

## 5. Explicitly not done

- **SHA1 stays SHA1.** Changing the algorithm changes `apply:batch:*` dedup keys, so an already-queued
  batch would no longer match. A7 only adds the behavior-neutral flag.
- **Popen is not suppressed.** `_run_sync` is a generic runner. Suppressing it would hide any future caller
  that passes unvalidated argv. Validation lives at the call sites (A4), and the residual medium finding is
  accurate.
- **Seed passwords are not moved to env vars.** `docs/TEST_USERS.md` and the resync test are a deliberate
  contract. The guard (A6) addresses the actual risk, and the suppression records the decision.
- **No git history rewrite** for the committed key. The ADO mirror and existing clones already hold it, so
  rotation (A1) is the remedy.
- **No engine-wide change to `ArgumentIdentifierMatches`.** B6 adds a new filter instead, so other rules keep
  their recall.
- **Sibling rules not touched** in this pass: `ZS-TS-014`/`ZS-JS-009` logging, `ZS-PY-070` sentinel naming,
  Go/Java/C# credential rules. They can follow once B1/B6 prove out.
- **No `ScannerCreateScanRequest.branch` validation** (display metadata; see A4).
- **The other npm advisories are out of scope** here (see risk R5).

## 6. Risks and open questions

Risks:

- **R1.** A1 fails closed. Developers whose `.env` lacks `APP_ENV=development` get a refused boot, and so does
  any deploy without both secrets. The error must name the missing settings. A3 gates the merge.
- **R2.** Any environment that ran on the committed Fernet key must be treated as having that key public:
  - the key is in git history and in the ADO mirror;
  - if a DB dump or backup ever left the trust boundary, the encrypted PATs, OAuth tokens and AI provider
    keys should be rotated at their providers, not just re-encrypted.
  Flag this for security/compliance review. No compliance conclusion is drawn here.
- **R3.** `_BRANCH_RE` rejects valid but unusual branch names (`+`, `@`, non-ASCII). Before A4, the owner
  should count existing `ProjectRepo.selected_branch` values that fail the regex. Clones of those would start
  failing with a clear message.
- **R4.** B5 (`require_real_source` on rmtree) carries the largest false-negative risk. It is mitigated or
  documented per B5.
- **R5.** **SCA recall gap.** The scan reported 1 vulnerable dependency. `npm audit` on the same lockfile
  (2026-10-16) lists 28 vulnerable packages, including `next` (critical, fix 16.4.2) and `proxy-addr`
  (critical). That is a separate, likely more urgent portal item, and a scanner SCA false-negative to
  investigate.

Open questions for the owner (not verifiable from code):

1. Does production (ACA) set `OAUTH_ENCRYPTION_KEY`, and does the compose host have a key file? If not,
   since when, and which collections hold rows encrypted under the default?
2. Which scanner version produced scan `6ad1b436`? The portal pins v0.36.1 and scanner HEAD is v0.37.0. T0
   answers whether any of the 15 FPs is already fixed.
3. The scan ran on the ADO mirror's `main`, not this repo's `master`. Are line numbers and contents
   equivalent for the flagged files?
4. Is the fail-closed `APP_ENV` default acceptable? The alternative is `ENV APP_ENV=production` in
   `backend/Dockerfile` with a `development` default, which fails open for any non-container deploy.
5. Is suppressing the three seed-password lines (A6) acceptable, or must M2 count them?
6. The report rendered the non-secret identifier at `data_management_service.py:194` as `«REDACTED:SECRET»`.
   Is report-side over-redaction a known issue in the scanner's report writer?
7. How does the Python IR represent keyword arguments (B6 prerequisite)? Confirm with a scratch parse
   before writing the filter.
