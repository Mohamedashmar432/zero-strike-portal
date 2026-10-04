# Security review triage: third-party report, 29 September 2026

Source: a HarmonyEngine "Security Overview" share (security score 33/100, 9 findings: 5 high, 3 medium,
1 low). Each finding below was checked against the code on `master` plus the uncommitted working tree
as of 29 September 2026. The review also found two issues the report did not raise, and one of them is
the most serious item here.

## Verdict summary

| # | Finding | Report | Verdict | Our severity |
|---|---------|--------|---------|--------------|
| N1 | Git option injection via `ProjectRepo.clone_url` in threat-model cloning (**missed by report**) | — | **True positive, reproduced** | **Critical** |
| N2 | Client-controlled `X-Forwarded-For` defeats every rate limit (**missed; related to #2**) | — | **True positive, reproduced** | **High** |
| 1 | `clone_repo` follows redirects without revalidation | High | True positive | High |
| 2 | Login rate limit lacks an account-wide threshold | Medium | True positive (worse than stated, see N2) | High |
| 3 | `validate_repo_url` DNS rebinding (TOCTOU) | High | True positive | Medium |
| 4 | `cicdInstallCmd` runs an unverified `latest` binary | High | True positive, design-level | Medium |
| 5 | Versioned scanner artifacts can be silently replaced | High | True positive, admin-only | Medium |
| 6 | `_to_finding_response` exposes raw detected secrets | High | **Mostly false positive**; narrow residual | Low–Medium |
| 7 | `render_proposal_section` Markdown injection | Medium | Partially true; code fences already safe | Low |
| 8 | `verify_password` 72-byte bcrypt truncation | Medium | True, negligible impact | Low |
| 9 | `update_member_role` concurrent last-owner demotion | Low | True positive | Low |

None of the nine findings is fabricated. Most are real, but the report overrates the supply-chain and
secret-exposure items and underrates the rate-limit bypass. It also missed the one Critical.

## Missed findings

### N1. Command execution through `clone_url` (Critical)

`threat_model_service.py:398` calls `clone_repo(repo.clone_url, ...)` **without** `validate_repo_url`.
The cloud-scan and remediation paths call it; this path does not. `ProjectRepo.clone_url` is an
unvalidated `str` (`schemas/project_repo.py:21`, stored as-is in `project_repo_service.add_repo`), and
`git_workspace.clone_repo` places it on the argv with no `--` separator.

A value such as `--upload-pack=<command>` is parsed by git as an option, so git runs the command. This
was reproduced locally with git 2.54 against an empty directory, and the injected command executed.

Reachability: registration is open, any user can create a project and becomes its owner, owners can add
repos (`require_owner_or_admin`), and owners can trigger a threat model. So any self-registered account
can reach code execution on the backend host. `file://` and local-path URLs are also accepted on this
path, which allows reading local repositories.

Exposure: the threat-model feature is **uncommitted** (untracked files in the working tree), so it is not
in production yet. It must be fixed before it merges.

### N2. Rate limits are bypassable by spoofing `X-Forwarded-For` (High)

`backend/Dockerfile:93` runs uvicorn with `--proxy-headers --forwarded-allow-ips='*'`. With every hop
trusted, uvicorn 0.51 takes the **leftmost** `X-Forwarded-For` entry, which is the one the client
supplies. This was verified against the installed middleware: two requests carrying spoofed values
`1.1.1.1, <real>` and `2.2.2.2, <real>` were recorded as clients `1.1.1.1` and `2.2.2.2`.

Every limiter key includes `request.client.host`: `login:{ip}:{email}`, `register:{ip}` and
forgot-password. An attacker who rotates the header gets a fresh bucket on every request, so login
brute force against one account is effectively unlimited. Audit-log `ip_address` values can be spoofed
the same way.

## Reported findings

**1. Redirects (True, High).** Neither `git_workspace._token_env` nor the env builder in
`cloud_scan_service.py:214` sets `http.followRedirects`, and git's default (`initial`) follows redirects
on the first request. An allowed public host can therefore redirect the clone to an internal or
metadata address. This is blind SSRF, and the `http.extraHeader` bearer token may also be forwarded.

**2. Account-wide login limit (True, High with N2).** The only login bucket is `login:{ip}:{email}`,
10 attempts per 60 s (`config.py:167`), with no bucket keyed on email alone. On its own this is Medium,
because distributed IPs multiply the allowance. N2 lets a single host do the same thing.

**3. DNS rebinding (True, Medium).** `validate_repo_url` resolves the host once with `getaddrinfo`, and
git resolves it again on its own. A short-TTL record can pass the check and then point at a private
address. The blocklist also uses `is_private`/`is_loopback`/… instead of `not is_global`, which leaves
the 100.64.0.0/10 shared range open. The fix needs an IP pin, and the complete answer is worker egress
filtering at the network layer.

**4. Unverified CI install (True, Medium).** `scans/new/page.tsx:213` generates
`curl …/latest/linux-amd64 -o zerostrike && chmod +x` with no digest check. The download runs over TLS
from the operator's own portal, and publishing requires admin, so exploiting this requires a
compromised admin or portal. That makes it a hardening gap, not a High. Checksums from the same origin
only catch corruption. Real integrity needs a signature whose key lives outside the portal.

**5. Mutable versions (True, Medium).** `download_service.publish` replaces an existing
version/os/arch, and `test_reupload_same_version_os_arch_replaces` locks that in. This is deliberate
(pipeline retries, `download_service.py:133`) but lets a CI job pinned to a version receive different
bytes later. Admin-only.

**6. Secret exposure (Mostly false positive).** The dedicated secret detector never stores the secret.
`BuildSecretFinding` in the scanner (`internal/findings/builder.go:107`) hashes it, emits no evidence,
and keeps only `redacted` (the first 4 characters plus `****`). The residual is SAST rules such as
Hardcoded Credential (CWE-798, e.g. `ZS-GO-005`), which carry the flagged source line verbatim in
`evidence[].snippet`. That line can contain a literal password, and it is shown to every project member
and in exported reports. The portal already has `secret_redaction.redact`, but uses it only on LLM
prompts.

**7. Markdown injection (Partially true, Low).** Code blocks use `_fence`, which lengthens the fence
when the body contains backticks, so repo code cannot break out. The frontend does not render Markdown
as HTML, and GitHub sanitizes PR bodies. What remains is spoofed links or headings through the file path
(inline backticks), the scanner `message`, the LLM `insight.explanation` (which can be prompt-injected
by repo content) and comments in the PR body. The result is misleading text with no script execution.

**8. bcrypt 72 bytes (True, Low).** `hash_password` and `verify_password` silently truncate to 72 bytes.
Passwords that share their first 72 bytes are equivalent, but an attacker must already know those
72 bytes, so the practical impact is only that users are misled about password strength. An Argon2id
migration is not justified by this alone.

**9. Last-owner race (True, Low).** `update_member_role` counts owners and then saves (non-atomic), so
two concurrent demotions can both pass. A portal admin can re-promote someone, so the damage is
recoverable.

## Fix plan

Ordered by risk. Each step lists its regression test.

**P0 — before threat models merge (N1)**
- `clone_repo`: call `validate_repo_url(repo_url)` inside it, so no caller can skip the check, and put
  `"--"` before `repo_url` in both `git_workspace.clone_repo` and the `cloud_scan_service` clone argv.
- Validate `clone_url` when a `ProjectRepo` is created or updated (http/https only, reject a leading
  `-`), via a Pydantic validator on the request schemas.
- Add `protocol.allow=never` and `protocol.https.allow=always` (plus `http` if needed) to both git env
  builders. This also shuts off `file://` and `ext::`.
- Test: a `clone_url` of `--upload-pack=...` is rejected at the API with a 422, and `clone_repo` refuses
  it even when the check is bypassed.

**P1 — rate limiting (N2, #2)**
- Stop trusting client-supplied XFF: set `--forwarded-allow-ips` to the actual proxy range, or derive
  the client IP from the **rightmost** XFF entry (the one the platform edge appended).
- Add a second, email-only bucket on login (for example 20 per 15 minutes), checked alongside the
  per-IP bucket. Normalize email to lowercase in the key.
- Test: 11 logins for one email with rotating XFF values produce a 429.

**P1 — SSRF hardening (#1, #3)**
- Add `http.followRedirects=false` to both git env builders.
- Pin resolution: resolve once in `validate_repo_url`, return the vetted IP, and pass
  `http.curloptResolve=<host>:<port>:<ip>` to git so git cannot re-resolve. Switch the blocklist to
  `not ip.is_global`.
- Infra: egress deny to RFC1918, link-local and metadata ranges on the backend container. This is the
  only complete control.
- Test: a mocked host that resolves to `100.64.0.1` is rejected, and the clone env contains
  `followRedirects=false`.

**P2 — supply chain (#4, #5)**
- `publish`: a same-version re-upload with the same sha256 is a no-op (retry-safe); a different sha256
  returns 409. Invert the existing test.
- CI snippet: pin a concrete version and verify the digest
  (`echo "<sha>  zerostrike" | sha256sum -c`) before `chmod +x`.
- Later: sign releases (cosign or minisign) with a key outside the portal, and verify the signature in
  the snippet.

**P2 — evidence redaction (#6)**
- At ingest, run `secret_redaction.redact` over `evidence[].snippet` for findings with CWE-798 or
  category `authentication`, so the stored copy, API responses and reports are all covered at once.

**P3 — low**
- #8: reject passwords over 72 UTF-8 bytes on register, reset and change instead of truncating. Keep
  the truncation in `verify_password` so existing hashes still verify.
- #9: demote only when the conditional update matches. Count owners inside the same update filter, or
  re-check after the write and roll back.
- #7: escape backticks in the inline file path, and render `message` and `explanation` as quoted text.

## Implementation design (decided 29 September 2026)

Four work packages. Each owns a disjoint set of files so they can land independently.

**WP-A: git and SSRF (N1, #1, #3).** Files: `services/git_workspace.py`, `services/cloud_scan_service.py`,
the `clone_url` request schemas (`schemas/project_repo.py`, `schemas/connection.py`,
`schemas/repo_credential.py`), and their tests.
- `validate_repo_url` keeps its name and callers, and now *returns* the vetted IP list. The blocklist
  becomes `not ip.is_global`. It also rejects a leading `-` and userinfo in the URL.
- One helper builds the hardened git env for both clone sites: `protocol.allow=never`,
  `protocol.https.allow=always`, `protocol.http.allow=always`, `http.followRedirects=false`, and
  `http.curloptResolve=<host>:<port>:<ip>` pinned to the first vetted IP. Adding `http.curloptResolve`
  requires git 2.37 or later.
- `clone_repo` validates internally, so no caller can skip it. Both clone argvs put `--` before the URL.
- The request schemas get a syntax-only validator: http(s), a host present, no leading `-`. DNS is
  checked at clone time, not at write time, because DNS can change in between.

**WP-B: client IP, rate limits, passwords (N2, #2, #8).** Files: `core/rate_limit.py`, `core/config.py`,
`routers/auth.py`, `core/security.py`, the auth and user schemas, `Dockerfile`, and the other
`request.client` call sites.
- Add `trusted_proxy_hops: int = 0` to the config, plus a `client_ip(request)` helper. With `N` hops it
  takes the `N`th-from-right `X-Forwarded-For` entry; with 0 it uses the socket peer. Drop
  `--proxy-headers --forwarded-allow-ips='*'` from the Dockerfile and set `TRUSTED_PROXY_HOPS=1`. This
  works for both Caddy (which overwrites the header) and an appending edge.
- Add an account bucket on login, `login-account:{email.lower()}`, configured as
  `rate_limit_login_account_max_attempts=20` per `rate_limit_login_account_window_seconds=900`.
- Passwords over 72 UTF-8 bytes get a 422 on register, reset and change. `verify_password` keeps
  truncating so existing hashes still verify.

**WP-C: scanner distribution (#4, #5).** Files: `services/download_service.py`, `tests/test_downloads.py`,
and `frontend/app/(dashboard)/projects/[projectId]/scans/new/page.tsx`.
- A re-publish with the same sha256 is a no-op; a different sha256 returns 409.
- The CI snippet downloads `checksums.txt` for the same version and runs `sha256sum -c` before
  `chmod +x`.

**WP-D: evidence, Markdown, owner race (#6, #7, #9).** Files: `services/report_ingestion_service.py`,
`services/remediation_brief_service.py`, `routers/projects.py`, and their tests.
- `secret_redaction.redact` is applied to every `evidence[].snippet` at ingest, and the fingerprint is
  untouched. Findings already stored are not backfilled.
- The inline file path uses a backtick-safe inline-code helper, and the scanner `message` has Markdown
  link and image syntax escaped.
- `update_member_role` saves, recounts owners, and reverts with a 409 if none remain.

## Status and deferred work (29 September 2026)

WP-A to WP-D are implemented but not yet committed. The full suite passes (845 tests), plus a browser
pass covering the clone-URL 422, the login 429 and the password 422.

One correction was made after review. The first version rejected any userinfo in the URL, which would
have broken every Azure DevOps repo, because ADO's `remoteUrl` is `https://{org}@dev.azure.com/...`.
Only a password in the URL is rejected now, and a regression test covers the ADO URL shape.

Production is Azure Container Apps. `TRUSTED_PROXY_HOPS=1` assumes ACA ingress is the only proxy.
Set it to 2 if Front Door or Application Gateway is added in front.

Deferred, to plan later:
- A live redirect test, and a live DNS-rebinding test, of the git clone hardening.
- Dedicated tests for the 72-byte limit on reset-password and change-password.
- A backfill that masks secrets in findings stored before this change, and masking of `Report.raw_json`
  (stored at rest, never served).
- Signed scanner releases with a key held outside the portal (#4).
- Network-level egress deny from the backend to private, link-local and metadata ranges (#3).
- After deploying, confirming that ACA's `X-Forwarded-For` has the real client IP as its rightmost entry.

Per the definition of done in `CLAUDE.md`, P0 and P1 each need a browser pass. That pass must cover the
repo-add refusal toast and the login 429 path, and confirm the wire status codes.
