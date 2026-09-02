Yes — the code shows a real stale-scan failure mode, and it’s handled as a backend lifecycle problem more than a frontend one.

What’s happening in the SAST scan flow

The cloud scan path is:

Queue claims a cloud scan

backend/app/services/scan_queue_service.py
drain_queue() pulls a queued scan and starts it, respecting max_concurrent_cloud_scans.
run_cloud_scan() executes the scan

backend/app/services/cloud_scan_service.py
It:
validates the repo URL
clones the repo into a temp workdir
runs the Go scanner subprocess with settings.scan_timeout_seconds
parses the scanner JSON output
calls report_ingestion_service.ingest(...)
Ingestion is what marks the scan complete

backend/app/services/report_ingestion_service.py
ingest(...) deletes old findings/report rows, stores the new report, then sets scan.status = "completed" and triggers follow-up work.
So a report only exists after the scanner finishes successfully enough to produce JSON and ingestion runs. If the scan stays running, the report never gets created.

Why large repos can get stuck running with no report

The backend has three clear stall points for big repositories:

1) Scanner subprocess timeout

In cloud_scan_service.py, the scanner runs with a hard timeout:

subprocess.run(..., timeout=settings.scan_timeout_seconds)
If it exceeds that, the code raises:
CloudScanError("command timed out after ...")
That means large repos can simply exceed the configured scan timeout and never reach ingestion.

2) Scanner out-of-memory / abnormal exit

cloud_scan_service.py treats exit code -9 specially:

rc == -9 → CloudScanError("scanner was killed (out of memory)...")
That is a strong signal for large-repo scans failing under memory pressure. If that happens, no report is ingested.

3) Queue/job gets stale while still marked running

There is explicit stuck-job recovery:

backend/app/core/job_queue.py supports reclaiming stuck running tasks.
backend/app/services/scan_queue_service.py has reap_stuck_scans().
Tests prove that scans with stale updated_at are moved from:
running → failed
or running → queued until retry budget is exhausted.
The stale detection uses:

settings.scan_timeout_seconds * settings.queue_stuck_multiplier
So if the scan is still marked running long after its last update, the recovery logic should eventually reap it. If that isn’t happening, the scan can appear permanently stale in the UI.

Why the app shows “waiting for scanner to report”

The scan detail page in:

frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx
only fetches the report when:

scan.status === "completed"
and it shows a waiting state otherwise:

“Waiting for the scanner to report…”
So the frontend is not the root cause. It is faithfully waiting on backend state. If the backend never transitions the scan out of running, the UI will never ask for a report.

Also, the report endpoint itself returns:

404 "No report for this scan yet"
when no Report document exists, which matches the symptom exactly.

The most likely root cause for your symptom

For large repositories, the strongest code-backed causes are:

scan timeout too low
scanner OOM / killed
scan task never gets reaped from running
scanner finished but never emitted valid JSON, so ingestion never ran
ingestion never executed because clone/scan errored earlier
The code is designed so that any exception in run_cloud_scan() calls _fail(...), which marks the scan failed and drains the queue. So if your scan is staying running forever, the more likely issue is not a normal exception path — it’s one of:

the subprocess is hanging longer than expected,
the worker process died before _fail() ran,
or the stuck-scan reap loop is not running frequently enough / not being invoked.
Evidence that the app can recover stale scans

There is explicit stale-scan recovery in the backend:

scan_queue_service.reap_stuck_scans()
scanner_status_service.queue_status() flags stuck running scans
admin_data includes a stuck-scan reaping path
tests confirm stale scans are moved out of running
So the system is intended to recover, but only if the reap/queue maintenance loop is actually running and the timestamps are being updated correctly.

What I would check first in this codebase

settings.scan_timeout_seconds

If this is too small for large repos, scans will time out before report generation.
settings.queue_stuck_multiplier

If too high, stale scans linger as running too long.
Whether the queue poll/reap loop is running in production

The code expects periodic reaping, not just one-off execution.
Whether the scanner is being killed by memory pressure

rc == -9 is explicitly treated as OOM.
Whether the scanner binary itself is producing valid JSON

GoReportIn.model_validate_json(out) must succeed before ingestion.
Frontend behavior is not the blocker

It only reflects backend scan status and report presence.
Bottom line

This is not a report-page bug first. The code shows that the report is only created after the scanner subprocess completes and ingestion succeeds. For large repos, the likely failure is in the cloud scan execution path:

timeout,
OOM kill,
or stale-running job recovery not firing.
If you want, I can go one level deeper and map the exact scan lifecycle across:

scan_queue_service.py
cloud_scan_service.py
report_ingestion_service.py
scanner_scans.py
frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx
and show exactly where a large repo can get stuck and what code change would fix it.

how we can fix it properly and implement the error handling, it need to scan any large repo smoothly ,

To fix large-repo scans properly, the backend needs to treat scans as bounded, recoverable jobs instead of one long-running subprocess that can hang forever. The code already has most of the pieces; the missing part is making the scan lifecycle fail fast, surface errors consistently, and recover stuck jobs automatically.

What the code already does

In backend/app/services/cloud_scan_service.py, run_cloud_scan():

creates a temp workdir
validates the repo URL
clones the repo
runs the scanner
ingests the report
on any exception, sanitizes the message, marks the scan failed, and drains the queue
always cleans up the workdir
The scanner execution path already has timeout/error handling:

_run_sync() wraps subprocess.run(..., timeout=timeout, check=False)
subprocess.TimeoutExpired becomes a CloudScanError
_scan_and_ingest() treats:
rc == -9 as likely OOM / too large repo
any non-0/1 exit code as a failure
invalid JSON as a failure at report validation time
The queue layer also already supports stuck-job recovery:

backend/app/services/scan_queue_service.py reaps running scans older than scan_timeout_seconds * queue_stuck_multiplier
stale scans are either requeued or failed with a retry budget
backend/app/services/scanner_status_service.py and the admin UI already expose stuck scans
So the main problem is not “no error handling exists” — it’s that large repos can still hit the current timeout/memory/queue boundaries and need better job lifecycle behavior.

The proper fix set

1) Make scanner execution explicitly resource-bounded

The scan subprocess needs stronger limits so large repos fail cleanly instead of stalling.

In cloud_scan_service.py:

keep timeout on clone and scan execution
add clearer handling for:
timeout
OOM / killed process
invalid report JSON
scanner binary not found
repo clone failure
ensure every failure path calls _fail(scan, message) so the scan always reaches a terminal state
The important behavior is already modeled in tests like backend/tests/test_cloud_scan_service.py:

clone failure marks failed
scanner exit failure marks failed
bad JSON marks failed
That’s the right contract to keep.

2) Never leave a scan in running if the worker dies

This is already the purpose of scan_queue_service.py, but it must remain the fallback for all crash cases.

The queue service should:

periodically reap stale running scans
requeue if retry budget remains
mark failed when retries are exhausted
include a useful error message like “stuck scan reaped” / “retries exhausted”
This behavior is already covered by backend/tests/test_scan_queue_service.py.

3) Ensure report ingestion is the only “completed” transition

backend/app/services/report_ingestion_service.py is the place that marks a scan completed.

That is good. Keep the rule:

only successful ingestion marks completed
failed scans never get upgraded later
after completion, drain the queue and enqueue follow-up work
That avoids partial/inconsistent terminal states.

4) Surface failure information to the UI

The frontend already renders failure states in:

frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx
frontend/app/(dashboard)/admin/scanner-status/page.tsx
So make sure backend failures populate:

status = "failed"
error_message = <sanitized reason>
completed_at when terminal
That way the scan detail page can show the failure alert immediately instead of looking stuck.

5) Improve stuck-scan visibility for admins

scanner_status_service.py already computes stuck scans using:

scan_timeout_seconds * queue_stuck_multiplier
And the admin page shows:

Stuck — pending reap
That’s exactly what you want for operational visibility. The fix is to keep that status accurate and ensure stale scans are aggressively reaped.

What I would change in practice

In cloud_scan_service.py

Make sure failures are classified and user-safe:

clone timeout → CloudScanError("git clone timed out ...")
scan timeout → CloudScanError("scanner timed out ...")
OOM/kill → CloudScanError("scanner was killed (out of memory) ...")
bad report JSON → CloudScanError("scanner produced invalid JSON")
subprocess missing → CloudScanError("scanner binary missing")
any unexpected exception → sanitize and mark failed
Also ensure finally always removes the temp dir, which the current code already does.

In scan_queue_service.py

Keep the stuck-scan reaper as the safety net, but make sure:

stale scans transition out of running
retries are bounded
a dead-letter path exists after retries are exhausted
In report_ingestion_service.py

Only mark completed after:

report validation succeeds
findings/report persistence succeeds
If ingestion fails, the scan should fail, not remain running.

In scanner_scans.py

When the scanner reports status updates, preserve:

status
error_message
completed_at for terminal states
That gives you correct state transitions from the scanner side too.

For large repos specifically

If you want scans to “smoothly” handle very large repos, timeouts alone are not enough. The current backend can fail cleanly, but performance still depends on scan cost. The most effective operational fixes are:

increase scanner timeout only where justified
tune memory/CPU for the scanner worker
reduce unnecessary scan scope if the scanner supports it
prefer incremental/delta scanning if your scanner can support it
keep queue concurrency low enough to avoid resource contention
The codebase already has the queue and stuck-scan framework to support this; the main gap is making sure large scans fail deterministically instead of stalling and that the UI gets the failure reason immediately.

Bottom line

The correct fix is:

Bound subprocess execution in cloud_scan_service.py
Convert every failure into a terminal failed scan
Use scan_queue_service.py to reap/retry stuck scans
Only let report_ingestion_service.py mark scans completed
Propagate sanitized error_message to the scan detail UI
Keep admin stuck-scan visibility active
If you want, I can next turn this into a concrete patch list file-by-file, or draft the exact code changes for cloud_scan_service.py and scan_queue_service.py.