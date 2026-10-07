# Operations and queueing: capacity, ETAs, admin load view

Written 2026-10-06. Covers how much concurrent work one backend instance takes on, what happens when
several projects ask for heavy work at once, and the two surfaces added on top: a queue position with
a start-time countdown for users, and an admin Operations page with live queue and container load.

## What the backend actually runs

Every heavy operation in the portal is a document in a Mongo-backed queue, claimed by an atomic
`find_one_and_update` (`app/core/job_queue.py`) and drained by a poll loop started in `main.lifespan`.
There is no Redis or Celery, and none is needed at this scale. Four queues exist, each with its own
concurrency cap, counted globally from Mongo:

| Queue | What one job does | Cap (setting) | Default | Per-job wall-clock bound |
| --- | --- | --- | --- | --- |
| Cloud scan | `git clone --depth 1`, scanner subprocess, ingest | `max_concurrent_cloud_scans` | 2 | `scan_timeout_seconds` = 900 s |
| AI analysis | LLM enrichment of a scan's findings, up to `ai_analysis_concurrency` (3) LLM calls in parallel inside one job | `max_concurrent_ai_jobs` | 3 | `ai_job_timeout_seconds` = 300 s |
| Auto-fix (remediation) | `propose`: LLM agent loop. `apply`: clone, patch, re-scan, push, open PR | `max_concurrent_remediation_jobs` | 1 | `remediation_job_timeout_seconds` = 600 s |
| Compliance audit | Pure in-memory evaluation, optional LLM narrative | `max_concurrent_compliance_audits` | 2 | `compliance_audit_timeout_seconds` = 300 s |

Local and CI scans run on someone else's machine and only upload a report; they never touch a queue.
Repo Sync enqueues ordinary cloud scans, so it shares the cloud-scan cap.

The worst-case simultaneous load on one instance is therefore two scanner subprocesses (each capped at
`scanner_max_workers` = 2 goroutine workers) plus one auto-fix apply, which clones and re-scans too, so
three heavy subprocesses, plus up to nine in-flight LLM HTTP calls from AI analysis. CPU-bound work
runs in threads or subprocesses, so the event loop stays responsive to API traffic throughout.

## Five or six projects at once

Say six projects each start a cloud scan within the same minute. Two start immediately and four wait
in `queued`, served oldest-first (`created_at` ascending). As each scan finishes, ingestion re-drains
the queue, so the next one starts within seconds instead of waiting for the 5-second poll. With a
typical scan of two to three minutes, the sixth project waits roughly two scan-lengths. Nothing is
dropped and nothing fails because of the load. A container restart mid-scan is caught by the reaper
(heartbeat silence past `scan_timeout_seconds * queue_stuck_multiplier`) and the scan is failed with
a message naming the phase it died in.

The same holds for the other queues: each one is FIFO and bounded independently, so a burst of AI
analysis cannot starve cloud scans or the reverse.

**What was wrong:** `drain_queue()` read the free capacity, then claimed jobs one by one. It is called
from the poll loop and again whenever a job finishes or is created, so two drains could overlap, both
see the same free slot, and both claim, pushing the queue past its cap. That breaks the memory budget
the caps exist to protect. Each queue's drain now holds a per-process lock (`job_queue.drain_lock`),
which closes the race on the single-replica deployment we run. Running several replicas would need a
Mongo-side slot counter instead, and the lock's comment says so.

**Also found while load-testing (fixed):** every portal clone inherited the host's git credential
helper. `GIT_TERMINAL_PROMPT=0` silences terminal prompts but not helpers, so on a machine with Git
Credential Manager a clone of a private or missing repo opened a sign-in dialog nobody would answer,
holding a cloud-scan slot until the 15-minute timeout. It could also have offered the host's stored
credentials to a URL a portal user chose. `git_hardening_entries` now clears `credential.helper` for
every clone (scans and auto-fix alike), and such a clone fails in about two seconds with "Repository
not found, or it is private and needs an access token" ahead of git's own message.

**Known gap:** a backend restart strands whatever was running. The reaper reclaims a cloud scan only
after `scan_timeout_seconds * queue_stuck_multiplier` (45 minutes by default) of heartbeat silence,
although a live scan heartbeats every 30 seconds. Until then the stranded scan holds a slot. Shortening
the window to a few missed heartbeats is the fix, and is left for a separate change because it alters
crash-recovery timing for every queue.

**Not done, deliberately:** per-project fairness. One project that queues ten scans is served ahead of
a project that queues one a second later. Add a round-robin claim by `project_id` if that becomes a
real complaint; FIFO is the predictable default.

## Tuning

Raise a cap only when the Operations page shows memory headroom while that queue is full. A cloud scan
on a large repo is the memory peak; the scanner subprocess is what the OOM killer takes first
("scanner exited -9"). Lower `scanner_max_workers` before lowering `max_concurrent_cloud_scans`, since
fewer workers slows a scan while a smaller cap makes everyone wait.

## Queued tag and start-time estimate (users)

Wherever a job can be queued, its status badge carries its place in line and a countdown:
"QUEUED · #2 · 1:23" on a cloud scan, "AI QUEUED · #1 · 0:40", "FIX QUEUED · …", "AUDIT QUEUED · …".
That covers the dashboard's recent scans, a project's scans tab and history, vulnerability
occurrences, the scan, auto-fix and audit pages, the auto-fix and compliance lists, and a repo row
whose sync scan is waiting. The projects list's "3 QUEUED" pill names the project's next start. Detail
pages also show a sentence-length notice with what the job is waiting on. Once the estimate passes the
tag reads "any moment"; on a queue whose limit is 0 it reads "paused" and gives no time.

All of it reads one endpoint, `GET /api/v1/queue`: every queued or running job in the projects the
caller belongs to (all projects for an admin), each positioned against the whole queue, with per-queue
summaries. The frontend shares a single query (`queryKeys.queue()`), so a list of twenty queued rows
makes one request every five seconds, and only while a queued tag is on screen. `ScanStatusBadge`
takes `scanId` and `AiStatusBadge` takes `refId`; a new list that shows either badge gets the tag by
passing the id (`components/queue/queue-tag.tsx`).

The estimate comes from `operations_service.estimate_starts`. It assumes each running job ends at its
start time plus the queue's recent average duration (mean of the last 20 completed runs, ignoring runs
under a second, with a fixed default per queue until there are three). It then hands each queued job
the earliest slot to free up, in queue order. A running job already past the average is treated as
finishing now. The response carries `server_time`, so countdowns run on the server's clock rather than
the browser's.

## Admin Operations page

`GET /api/v1/admin/operations` (admins) returns, per queue: running and queued counts against the cap,
average duration, the oldest wait, and the running and queued jobs with project names, stages and
ETAs. It also returns failures across all queues in the last 24 hours with their error messages, and
the container's CPU and memory.

CPU and memory are read from the container's cgroup v2 files when present, which is what the
container is actually limited to, and fall back to psutil's host view on a developer machine. The
response says which source it used. The numbers describe the replica that served the request. The page
polls every 3 seconds.
