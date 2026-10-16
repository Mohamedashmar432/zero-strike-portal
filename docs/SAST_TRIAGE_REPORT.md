# SAST Triage Report: thinkShield scanning its own portal

Scan date: 2026-10-16 (scan ID 6ad1b436). Triage by Sonnet 5.5 against the real code; plan by Opus 5.5; implementation by Sonnet 5.5; verification by Haiku 4.5. No secret values appear in this document.

## 1. Summary

| Measure | Value |
|---|---|
| Total findings reported | 25 (18 High, 7 Medium) |
| True positive | 1 (4%) |
| Low-value true positive (real, severity overstated) | 9 (36%) |
| False positive | 15 (60%) |
| Strict precision (true positives only) | 4% |
| Lenient precision (true + low-value) | 40% |

After the fixes, a re-scan with the patched scanner reports 7 findings. Of those, 4 are in an untracked generated folder (`brag-output-*`, not portal source), 1 is a new false positive on a template file, and 2 are the Popen finding (now Medium) and the `ip-address` dependency advisory.

## 2. The true finding

| Finding | Location | Status |
|---|---|---|
| Hardcoded encryption key (High) | `backend/app/core/config.py` | Fixed. The committed Fernet key default was removed. A startup guard now refuses to boot in production without a valid key. Rotation script added. |

Open point for the owner: if production ever ran on the committed key, that key is in git history and should be treated as public. Rotate it and the credentials it protected.

## 3. Low-value true positives

| Finding | Why it is real but overstated | Status |
|---|---|---|
| Hardcoded JWT secret, reported twice on one line | A dev default with no production guard. Production loads it from a secret file. Medium at most. | Fixed. Default removed, 32-character minimum enforced in production. |
| Popen with tainted command | Argument list, `shell=False`. Only residual risk was a branch name starting with `-`. | Fixed. Branch names are validated before clone. The scanner now grades this Medium (new rule ZS-PY-147), so it is still reported by design. |
| Seed script passwords (3) | Dev-only fixtures, but the script had no environment guard. | Fixed. Script refuses to run outside development; findings suppressed with a documented ignore. |
| SHA1 dedup key | Non-security use (job dedup). | Fixed. Marked `usedforsecurity=False`; hash output unchanged, so queued jobs still dedupe. |
| Empty `except: pass` | Skips malformed ids on purpose but catches too much. | Fixed. Narrowed to the specific exceptions. |
| Vulnerable `ip-address` (transitive) | No direct use found; backend has its own SSRF validation. | Partly fixed. Lockfile hand-edited to 10.7.4 but `npm install` was not run, and the scan still flags the lockfile. Needs a real install and re-check. |

## 4. False positives and why

| Count | Finding | Why it is false | Scanner fix |
|---|---|---|---|
| 8 | Hardcoded Credential on `"bearer"`/`"basic"`, `token_type`, `TOKEN_URL` constants, `"not-needed"` placeholder | The rule matches the variable name (token, secret, key) and never judges the value. These are scheme names, public URLs and a dummy placeholder. | Value filters (placeholders, scheme names, URLs), name-suffix filter (`_url`, `_type`, `_scheme`), handle leading underscores. |
| 1 | Hardcoded credential on `"secret": "Secrets"` | A display-label map; the key name matched. | Label-alternation filter on the dict/kwarg rules (Python, TS, JS). |
| 1 | `generic-api-key` on `has_api_key=...call(...)` | A boolean keyword argument holding a function call, not a literal. | Secrets scanner drops unquoted values that are code references (followed by `.`, `(`, `[`, or snake_case). |
| 2 | `rmtree` with tainted path | Every caller passes a `mkdtemp` directory or a fixed root. The rule treated any function parameter as attacker input. | Require a real taint source (`require_real_source`). |
| 1 | `setInterval` with tainted string | The argument is an arrow function. The rule fired on any call. | Skip function-valued arguments, as the sibling `setTimeout` rule already did. |
| 3 | Sensitive Value Logged | Logged `secret_name` (an identifier) or an argument already wrapped in `sanitize()`. The rule matched the words "secret" and "token". | New `logged_identifier` filter: ignore name/id suffixes and arguments passed through a sanitizer. |

Root cause across all 15: rules matched on names and call shapes without checking the value or real data flow, and some rules lacked filters their sibling rules already had.

## 5. How to improve the scanner further

1. Judge the value, not only the name. Credential rules should require a quoted literal with enough entropy or a known secret prefix, and skip URLs, enum or scheme words, and placeholders.
2. Treat taint as a data-flow question. A function parameter is not attacker input; require a path from an HTTP handler or other real source. The fix introduced one regression here (see 6).
3. Share filters across sibling rules. Most false positives came from a rule missing a filter its twin had. Add a lint that fails CI when rules in the same family diverge on filters.
4. Make the benchmark the gate. Every rule change ships a positive fixture that must still fire and a negative fixture from the real false positive. `--max-fp 0` already enforces this (now TP=556, FP=0, FN=0).
5. Report once per root cause. The JWT line was reported twice (credential and weak key); deduplicate across rules on the same line.
6. Fix the dependency check. `npm audit` on the same lockfile lists 28 advisories (two critical, including `next`); the scanner reported 1. This is a larger gap than any false positive here.
7. Downgrade by context: seed scripts, examples and templates should be a lower-severity class. The new false positive on `deploy/secrets/mongodb_uri.txt.example` (a placeholder connection string) shows this is still missing; also exclude generated output folders by default.
8. Re-test periodically against real repos. Measure precision on a labelled set of scans like this one, not only on the synthetic corpus.

## 6. Known cost of the fixes (false-negative risk)

- `rmtree`: a helper that deletes a path set by a request handler in another function is no longer reported. Recorded as a known gap in the scanner benchmark README.
- Credential rule: a real secret in a variable named like `auth_header`, `*_name` or `*_id` is no longer reported.
- Log rule: any callee whose name contains `sanitiz`, `redact`, `mask`, `scrub` or `hash` is trusted to have removed the secret.
- Hash rule: `usedforsecurity=False` is trusted without checking.
- A password literally equal to its own label (for example `"password": "passwords"`) is suppressed.
- ZS-PY-146 (the real key finding) is absent from the re-scan only because the key was removed; its continued detection is shown by a synthetic fixture, not by the re-scan.

## 7. Not yet done

- Backend restart and browser QA pass; `docker compose config` check.
- Production must set `JWT_SECRET` and `OAUTH_ENCRYPTION_KEY` before the startup guard ships, and developer `.env` files need `APP_ENV=development`.
- Scanner release steps: `baseline.json`, release notes, version tag, `SCANNER_REF` bump in the portal.
- Nothing is committed or pushed in either repo.
