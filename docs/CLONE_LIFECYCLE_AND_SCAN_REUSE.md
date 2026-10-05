# Clone lifecycle and scan reuse

Status: phases A, B and C built on `feat/repo-sync`; D not started. Date: 2026-10-05.

## Question

After a Repo Sync, a user opens New scan, picks Cloud scan and selects the same, already-synced
repo. Does the portal clone it again? If users keep doing this, do clones pile up until the
container's storage fills?

## Findings (from `backend/app/services/cloud_scan_service.py`, `scan_service.py`, `routers/scans.py`)

1. **Yes, it clones again.** The manual path (`routers/scans.py: create_scan` with
   `project_repo_id`) calls `scan_service.enqueue_repo_scan` directly. Unlike Repo Sync it has
   no up-to-date check (no `git ls-remote`, no comparison with the last completed scan's commit)
   and no "a scan for this repo is already queued/running" check. Every click queues a full
   clone + scan, even of a commit that was scanned a minute ago.
2. **Clones do not accumulate in normal operation.** Each scan gets its own
   `tempfile.mkdtemp(prefix="zs-clone-")` under `zs-clones/`, cloned with `--depth 1`, and is
   removed by `shutil.rmtree(workdir)` in a `finally` that runs on success, failure, timeout and
   task cancellation. At most `max_concurrent_cloud_scans` (default 2) clones exist per replica
   at once, plus AI remediation workdirs (`zs-remediate-*`), which follow the same pattern.
   Peak disk is roughly 2 x the largest repo, not unbounded.
3. **Where it can leak (real, but bounded):**
   - `rmtree(..., ignore_errors=True)` swallows failures silently. A file still held open
     (a surviving grandchild process; mostly a Windows problem, `_kill_tree` already mitigates
     it) leaves the directory behind with no log line.
   - A hard process death (OOM kill, container restart mid-scan) skips the `finally`. On Azure
     Container Apps the replica's filesystem is ephemeral, so a restart discards those dirs; a
     long-lived replica or a mounted `CLONE_WORKDIR_PATH` volume would keep them.
   - There is no sweep of stale `zs-clone-*` / `zs-remediate-*` dirs at startup or in the poll
     loop, and no free-disk check before cloning.
   - There is no cap on clone size. `--depth 1` limits history, not blobs, so one repo with
     large binaries can fill the disk by itself.
4. **The real cost today is waste, not a leak:** duplicate clones and scans of unchanged
   commits (CPU, bandwidth, a queue slot, new Scan/Finding rows), and two simultaneous scans of
   the same repo when the user clicks Sync and New scan together.

## Plan

Rejected: a persistent per-repo clone cache reused across scans. It would be per replica, needs
locking across concurrent scans, keeps the repo token's working tree on disk, and goes stale.
The `ls-remote` short circuit already gives the main benefit (no clone at all when nothing
changed) without keeping anything on disk.

### Phase A: one entry point for scanning a connected repo
- `create_scan` with `project_repo_id` goes through `repo_sync_service.sync_repo` (same lease,
  active-scan check, `ls-remote`, up-to-date short circuit, audit), passing `force` and the
  user's scan label. Responses: 202 `scan_queued`, 200 `up_to_date` (with the existing scan id),
  200 `already_syncing` (with the active scan id).
- Ad-hoc `repo_url` scans (not a connected repo): refuse a second active scan for the same
  (project, repo_url, branch) with a 409 naming the active scan.
- Frontend New scan dialog: on `up_to_date` show "Already scanned at main@abc1234" with
  View results and Rescan anyway (`force: true`); on `already_syncing` link to the running scan.
- Tests: manual scan of an up-to-date repo inserts no Scan; second manual scan while one is
  active inserts none; `force` still scans; ad-hoc duplicate gets 409.

### Phase B: disk safety
- Replace `ignore_errors=True` with an `onerror` handler that logs the path and error
  (cleanup stays best-effort and never fails the scan).
- Sweep: at startup and on each `poll_loop` tick, delete `zs-clone-*` / `zs-remediate-*` dirs
  under `workdir_root()` older than `scan_timeout_seconds * queue_stuck_multiplier`. Age-based,
  so it cannot delete a live scan's workdir.
- Free-disk preflight: `shutil.disk_usage(workdir_root())` before cloning; below
  `clone_min_free_mb` (new setting, default 1024) the scan fails with a readable message
  instead of filling the disk.
- Size guard: after cloning, fail the scan if the workdir exceeds `clone_max_repo_mb`
  (default 2048). **Built without `--filter=blob:limit`**: a partial clone only defers large blobs and
  `git checkout` of the tip then fetches every blob it needs for the working tree, so the bytes land
  on disk anyway (verified with a 6 MB blob: present in the worktree, nothing reported missing). No
  `clone_max_blob_mb` setting exists. The guards are the free-disk preflight and the post-clone cap.
- Tests: sweep deletes only old dirs; preflight failure marks the scan failed with the message;
  cleanup failure is logged.

### Phase C: visibility
- Admin scanner status shows the clone workdir count, total size and free disk, so a leak shows
  up before it causes an outage.

### Phase D: close the auto-fix -> merge -> sync loop

How auto-fix uses clones today: propose and apply each make their own fresh clone of the latest
branch (`zs-remediate-propose-*`, `zs-remediate-*`) and delete it; proposals and patches live in
Mongo, so a container restart loses nothing but an in-flight job (reaped by the remediation queue).
Gaps: the portal never learns a PR was merged, nothing tells the developer to Sync afterwards, and
auto-fix can propose fixes for findings a later scan already shows as fixed.

- **PR status on Sync (and on demand).** When a repo is synced, and via
  `POST /projects/{id}/repos/{repo_id}/pr-status/refresh`, read the state of every proposal/job
  with an open PR for that repo from the provider REST API (GitHub `GET /repos/{o}/{r}/pulls/{n}`,
  Azure DevOps `GET .../pullrequests/{id}`) using the repo's existing read credential; never put
  the token in a URL or log. Store `pr_state` (`open|merged|closed`), `pr_merged_at`,
  `pr_merge_commit` on the proposal/job. Provider errors are recorded and never fail the sync.
- **Attribution.** When reconcile marks a vulnerability fixed and one of its findings has a
  proposal whose PR is merged, the vulnerability detail shows "Fixed via auto-fix PR #N"
  (read-time join, no new Vulnerability field).
- **Reminder, not auto-scan.** Repos tab shows "N auto-fix PRs merged since last sync - Sync now"
  when any merged PR's `pr_merged_at` is newer than the repo's `last_synced_at`. No scheduled
  scans (decided 2026-10-05: nothing scans without a user action).
- **Don't spend AI on fixed findings.** `trigger_scan_auto_fix` skips findings whose
  `vulnerability_id` is `fix_status=fixed`, and refuses (409, readable) a scan that is not the
  latest completed scan of its repo ("A newer scan exists; run auto-fix on it"). The workspace
  still lists every finding (CLAUDE.md invariant); skipped rows say "Already fixed in sha7".
- **Leftover branch.** If apply pushed a branch but the PR call failed, record the branch name on
  the job and show it with the failure, so it can be cleaned up or the PR opened manually.
- Tests: provider responses stubbed (merged/open/closed/404/auth error); reminder count; trigger
  skips fixed findings and 409s on a superseded scan; attribution shows only for merged PRs.

### Verification
- pytest/ruff/tsc/lint/vitest; browser pass: New scan on a synced repo shows "Already
  scanned", Rescan anyway queues one scan, Sync + New scan together give one scan.
- After release, `/health` or admin status on prod shows zero leftover workdirs after a batch
  of scans.
