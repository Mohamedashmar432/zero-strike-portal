# Observability: where a scan or an AI job is stuck, and why it failed

## Why this exists

`product-flaw.md` is the artefact that motivated this work. It is a competent read of the
cloud-scan code that ends in five paragraphs of *guessing* which of five stall points a real
stuck scan hit — timeout, OOM, unreaped job, invalid JSON, clone failure — and closes with a
list of settings to go check by hand. The guessing is not a weakness of the analysis. It is the
finding: **nothing in the portal records where a running scan actually is, so the only way to
answer "where did it stop" is to re-read the source and reason about it.**

The same hole exists on the AI side. `AIUsageEvent` records that a call failed and stores the
*exception class name* (`LLMPermanentError`) — which is exactly the granularity at which
"context window exceeded", "your API key is wrong" and "that model does not exist" are
indistinguishable. All three are `LLMPermanentError`. All three need different action from the
user.

This layer closes both. It is diagnostics only: no new infrastructure, no new collection, no
tracing backend. It reuses the pattern `RemediationJob.stage` already established — a coarse,
advisory sub-phase of `status="running"` that nothing may gate logic on.

## The rule that must not be softened

**`stage` is advisory. `status` remains the only thing claimed, reaped, or branched on.**
`app.core.job_queue` claims and reaps on `status`; adding a stage must not give it a second
state machine to disagree with. Every stage write is a best-effort annotation — if one fails,
the job carries on. Enforced by keeping stage writes out of the control flow (a helper that
swallows its own errors), never in an `if`.

Second rule, inherited from `AIUsageEvent`'s docstring and not relaxed here: **no raw provider
message is ever stored.** Provider error text can echo prompt content, and prompts carry
customer source code, findings and secrets. The "specific error" this layer adds is a
*classified code* derived from litellm's exception type, drawn from a closed vocabulary. That
gives the actionable detail without putting free text from a third party into a queryable
collection.

## Phase 1 — Scan pipeline stage + heartbeat

`Scan` gains:

- `stage: ScanStage | None` — `validating | cloning | scanning | ingesting`, set only while
  `status="running"`, mirroring `RemediationJob.stage`.
- `stage_started_at: datetime | None` — so "cloning for 22 minutes" is readable directly
  instead of subtracted from `started_at` by every caller.

`cloud_scan_service.run_cloud_scan` stamps each transition, and each stamp also touches
`updated_at`. That second effect matters on its own: today `updated_at` never moves between
claim and terminal state, so the reaper's staleness window (`scan_timeout_seconds *
queue_stuck_multiplier` since `updated_at`) really means "started long ago", not "made no
progress". With per-stage stamps it becomes a real heartbeat, and a scan that is genuinely
advancing through a huge repo is distinguishable from one that is wedged.

`_run_sync` also keeps the **tail of stderr on the timeout path**. Today a timeout discards
everything the process wrote, which throws away the one line that says which file the scanner
was chewing on when the budget ran out — the single most useful fact about a large-repo hang.
Bounded to the last 2000 bytes and sanitized like every other message.

## Phase 2 — AI job stage and classified failure reason

`AIAnalysisJob` gains `stage` and `trace_id`, reaching parity with `RemediationJob`, which has
both. An analysis job sitting at 3/12 chunks currently cannot tell you whether it is chunking,
waiting on a provider, or persisting; `trace_id` is what lets its log lines be pulled together
at all.

`AIUsageEvent` gains:

- `error_code` — a closed vocabulary classified from the litellm exception:
  `context_length_exceeded | rate_limited | auth_failed | model_not_found | permission_denied |
  bad_request | timeout | connection_error | provider_unavailable | malformed_response |
  not_configured | unknown`. This is the field that turns "AI is broken" into "your key is
  wrong" vs "your prompt is too long for this model's window".
- `attempt` and `failover_from` — a failover across three providers currently writes three
  rows that read as three unrelated failures. With these it reads as one chain, which is the
  difference between "the portal is down" and "provider 1 rate-limited, provider 2 served it".

`error_type` stays as-is: it is what existing rows and the analytics reader already carry, and
`error_code` is strictly additional detail beneath it.

## Phase 3 — Surface it

- **Scan detail page** — while running, say the stage and how long it has been in it, replacing
  the bare "Waiting for the scanner to report…" that gave `product-flaw.md` nothing to work
  with.
- **Admin scanner-status** — stage column on running and stuck scans, so the queue view says
  *what* the stuck job was doing.
- **Admin ai-analytics event log** — `error_code` column and a failure-reason breakdown, so the
  most common failure is visible without opening a single row.

## Phase 4 — Checks

One runnable check per phase, in the existing suites, plus the browser pass the repo's
definition of done requires (`CLAUDE.md`). Specifically: a stage is recorded and advances; a
stage write that raises does not fail the scan; a timeout message carries the stderr tail; each
litellm exception class maps to its expected `error_code`; a failover chain writes rows whose
`attempt` increments.

## What the browser pass caught

Recorded because a QA pass that found nothing and one that was never run look identical later
(`CLAUDE.md`).

- **"for 5 hours" on a scan seconds old.** `stageElapsed` used `new Date()` on a backend
  timestamp, and the backend serializes naive UTC (Mongo returns tz-naive datetimes), so the
  browser read it as local time and skewed every elapsed reading by the viewer's UTC offset —
  at UTC+5:30 a scan that had just started claimed to have been stuck for hours, which is worse
  than showing nothing. Fixed by using the repo's existing `parseApiDate`. `timeAgo` on the same
  page had the identical latent defect and was fixed with it.
- Verified live: the Phase column renders "Running the scanner" for a running cloud scan; a
  failed scan's alert reads "Scan failed while running the scanner" with the timeout message and
  the scanner stderr tail naming the file it died on; `reap_stuck` against the real database
  produces "Reclaimed: worker likely crashed mid-scan Last known phase: cloning."; the "Why calls
  failed" card breaks 13 failures into their causes with pre-`error_code` rows grouped as
  "Unclassified failure" so the counts still sum to the failure total, and the call log labels a
  failure "Invalid API key" / "Prompt too long for the model" while older rows fall back to the
  exception class name. Zero console errors, all requests 2xx, both roles exercised (the admin
  surfaces correctly refuse a member session).

## Large-repo validation (2026-09-02)

Run against `microsoft/vscode` — 872 MB, 12,999 TS/JS files, 17,299 files scanned — through the
whole portal pipeline, with the scanner rebuilt from `zero-strike-SAST-engine` v0.34.0:

```
running/- -> running/cloning -> running/scanning -> running/ingesting -> completed/-
572 s end to end (clone 40 s, scan 524 s, ingest 4 s), 4,822 findings, no hang
```

Two things this proved that no unit test could:

- **The stage sequence is real.** Every phase was observable live while the scan ran, which is
  the entire point of the layer, and `stage` cleared to `None` on success.
- **The 16 MB ceiling is not hypothetical.** The report came to 12.4 MB. The scan completed and
  the run's diagnostics say exactly what happened: *"Raw report JSON (12.4 MB) exceeded the 8 MB
  inline storage limit and was not kept. All 4822 findings were ingested normally."* Before this
  fix that insert blew up **after** every `Finding` had been written — a scan marked failed that
  actually had 4,822 findings and no report to show for them.

`django/django` (3,036 files) also completes clean at 110 s / 1,039 findings, matching a direct
scanner run exactly, which is the cheaper regression case to re-run.

Not covered: an OOM kill (`rc == -9`) still needs a memory-capped container to reproduce, and
this host is not one. `--workers` now actually bounds the SAST stage (engine v0.34.0), which is
the setting that path depends on.

## Large repos: what actually has to be true {#large-repos}

The first production run after this shipped failed at ~38 minutes with *"Scan failed while
running the scanner — Reclaimed: worker likely crashed mid-scan Last known phase: scanning."*
The stage layer did its job (it named the phase), and the message was still wrong in the way
that mattered: nothing had crashed on purpose, and two separate things were broken.

**1. The deployed scanner was ten releases old.** `backend/Dockerfile` bakes the engine in at
image-build time from `ARG SCANNER_REF`, which was pinned at `v0.24.0` — before every
large-repo fix in engine v0.34.0, and in particular before `--workers` had any effect on the
SAST stage. That stage holds a tree-sitter parser and a whole file's AST per goroutine, so the
old build ignored the portal's `--workers 2` and fanned out to `runtime.NumCPU()` regardless.
On a memory-capped container that is an OOM kill of *the container*, not of the child — which is
why `rc == -9` was never seen: the backend process died with it, so nothing was left to run
`_fail()`. Pinning `SCANNER_REF` and redeploying is not optional here; it is the fix.

**2. Phase stamps are not a heartbeat.** `_stage` writes `updated_at` at phase boundaries, and
`scanning` — the phase that takes the time — has no boundary in the middle of it. So
`updated_at` froze when scanning began and the reaper reclaimed the scan
`scan_timeout_seconds * queue_stuck_multiplier` later, whether or not the worker was alive.
`_heartbeat` now touches `updated_at` every 30s for as long as the worker is working, which
finally separates the two failures the message used to conflate:

| What happened | What bounds it | What the user is told |
| --- | --- | --- |
| Scan is legitimately slower than the budget | the scanner subprocess's own timeout | "scan timed out after Ns … raise SCAN_TIMEOUT_SECONDS", plus the scanner's last output |
| Worker died (container restart, OOM) | the reaper, once the heartbeat stops | "the worker … stopped reporting, so it was restarted or killed mid-scan" |

The heartbeat binds `asyncio.sleep` at import (`_real_sleep`). Several tests patch that global to
skip retry backoff, and a liveness loop whose only yield point is a patched-to-instant sleep
becomes a busy loop that starves the event loop — an unrelated patch silently disabling the
mechanism is worse than the sleep being slightly awkward to read.

**Three settings a large repo actually depends on** (`deploy/.env.example` carries the same note):
`SCAN_TIMEOUT_SECONDS` bounds clone and scan *separately* and is the real ceiling on repo size;
`SCANNER_MAX_WORKERS` is a **memory** bound, not a speed one, and is a no-op before engine
v0.34.0; `MAX_CONCURRENT_CLOUD_SCANS` multiplies the per-scan memory, because each concurrent
scan is another clone plus another scanner subprocess in the same container.

## Deliberately not done

- No OpenTelemetry / distributed tracing. There is one process and one Mongo; a `trace_id` in
  structlog plus a stage on the job answers the questions being asked. Revisit if the backend
  is ever split.
- No per-file scanner progress. That would need the Go scanner to stream progress, and the
  scanner is an independent repo with its own release cadence (`CLAUDE.md`). Stage granularity
  stops at the subprocess boundary.
- No stage history table. The current stage plus `stage_started_at` answers "where is it
  stuck"; a full timeline per scan is a different feature and an unbounded write.
- No new settings knobs. Every threshold reuses `scan_timeout_seconds` and
  `queue_stuck_multiplier`.
