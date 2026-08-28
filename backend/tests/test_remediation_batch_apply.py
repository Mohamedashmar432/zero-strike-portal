"""Batch apply: many approved proposals, ONE branch and ONE PR (docs/AUTOFIX_BATCH_PR.md).

The flaw these lock down: proposal granularity used to be PR granularity, so a 40-finding scan
opened 40 PRs. Batching only the *write* is safe as long as a single bad patch can't take the
others down with it — which is what most of this file exercises.

Same mocking boundary as test_remediation_apply.py (git + PR are faked), but the fake scanner is
content-aware: a finding clears when its file actually holds the patched text. That is what makes
the drop-and-retry path testable rather than merely asserted.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.core import security
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import Finding, LocationEmbedded
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.services import ai_remediation_apply_service as apply_svc
from app.services import git_workspace
from app.services.repo_write import github as gh_write


def _orig(name):
    return f"# {name}\nq = 'SELECT * FROM u WHERE id=' + uid\n"


def _patched(name):
    return f"# {name}\nq = 'SELECT * FROM u WHERE id=%s'\n"


async def _seed_batch(files, *, drifted=()):
    """One scan, one repo, one proposal per file. `drifted` files are cloned with content that no
    longer contains the proposal's original_code."""
    now = datetime.now(timezone.utc)
    repo = ProjectRepo(
        project_id="p", provider="github", organization="o", repo_full_name="o/r",
        clone_url="https://github.com/o/r.git", selected_branch="main",
        pat_encrypted=security.encrypt_secret("ghp_token"),
        created_by="u", created_at=now, updated_at=now,
    )
    await repo.insert()
    scan = Scan(
        project_id="p", scan_type="cloud", status="completed", repo_url="https://github.com/o/r.git",
        project_repo_id=str(repo.id), branch="main", created_at=now, updated_at=now,
    )
    await scan.insert()

    proposals = []
    for name in files:
        finding = Finding(
            scan_id=str(scan.id), project_id="p", fingerprint=f"fp-{name}", rule_name=f"Rule {name}",
            message="m", location=LocationEmbedded(file=name, start_line=2), severity="high", created_at=now,
        )
        await finding.insert()
        proposal = AIFixProposal(
            finding_id=str(finding.id), scan_id=str(scan.id), project_id="p", can_fix=True,
            confidence_score=95, original_code=_orig(name), patched_code=_patched(name),
            file_path=name, explanation="parameterize", review_state="approved",
        )
        await proposal.insert()
        proposals.append(proposal)

    ids = [str(p.id) for p in proposals]
    job = RemediationJob(
        kind="apply", project_id="p", scan_id=str(scan.id), proposal_id=ids[0], proposal_ids=ids,
        scope_key="apply:batch:test", trace_id="t", max_attempts=1, approver_user_id="u",
    )
    await job.insert()
    return proposals, job, set(drifted)


def _install(monkeypatch, files, *, drifted=(), broken=(), collateral=None, push_rc=0, push_err=""):
    """Content-aware git + scanner fakes.

    broken:     files whose fingerprint survives even once patched (the fix didn't work).
    collateral: {patched_file: located_in_file} — patching `patched_file` introduces a new HIGH
                finding located in `located_in_file`.
    """
    state = {"scans": 0, "prs": [], "workdir": None}
    collateral = collateral or {}

    async def fake_clone(repo_url, branch, workdir, token=None, auth_scheme="bearer", **kw):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        state["workdir"] = workdir
        for name in files:
            body = "totally different content\n" if name in drifted else _orig(name)
            (Path(workdir) / name).write_text(body, encoding="utf-8")

    def _patched_now():
        wd = Path(state["workdir"])
        return {n for n in files if (wd / n).read_text(encoding="utf-8") == _patched(n)}

    async def fake_run_scanner(workdir):
        state["scans"] += 1
        done = _patched_now()
        out = [
            SimpleNamespace(fingerprint=f"fp-{n}", severity="high",
                            location=SimpleNamespace(file=n))
            for n in files
            if n not in done or n in broken
        ]
        for src, located_in in collateral.items():
            if src in done:
                out.append(SimpleNamespace(fingerprint=f"fp-new-{src}", severity="high",
                                           location=SimpleNamespace(file=located_in)))
        return SimpleNamespace(findings=out, scanner_version="1.2.3"), "{}"

    async def fake_git(args, workdir, token=None, auth_scheme="bearer", timeout=120):
        if args[:2] == ["diff", "--name-only"]:
            wd = Path(workdir)
            changed = [n for n in files if wd.joinpath(n).read_text(encoding="utf-8") != (
                "totally different content\n" if n in drifted else _orig(n))]
            return 0, "".join(f"{n}\n" for n in sorted(changed)), ""
        if args[:3] == ["checkout", "--", "."]:
            wd = Path(workdir)
            for n in files:
                body = "totally different content\n" if n in drifted else _orig(n)
                wd.joinpath(n).write_text(body, encoding="utf-8")
            return 0, "", ""
        if args[:1] == ["rev-parse"]:
            return 0, "deadbeef\n", ""
        if args[0] == "push":
            return push_rc, "", push_err
        return 0, "", ""

    async def fake_pr(token, owner, repo, *, head, base, title, body):
        state["prs"].append({"title": title, "body": body, "head": head})
        return {"pr_url": f"https://github.com/{owner}/{repo}/pull/{len(state['prs'])}", "pr_number": len(state["prs"])}

    monkeypatch.setattr(git_workspace, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(git_workspace, "clone_repo", fake_clone)
    monkeypatch.setattr(git_workspace, "run_scanner", fake_run_scanner)
    monkeypatch.setattr(git_workspace, "git", fake_git)
    monkeypatch.setattr(gh_write, "open_pull_request", fake_pr)
    return state


async def _reload(proposals):
    return [await AIFixProposal.get(p.id) for p in proposals]


def test_batch_of_three_opens_exactly_one_pr(client, monkeypatch):
    files = ["a.py", "b.py", "c.py"]
    state = _install(monkeypatch, files)

    async def run():
        proposals, job, _ = await _seed_batch(files)
        await apply_svc.run_job(job)
        out = await _reload(proposals)
        assert [p.review_state for p in out] == ["pr_open"] * 3
        # One PR, and every proposal points at it — this is the whole fix.
        assert len(state["prs"]) == 1
        assert len({p.pr_url for p in out}) == 1
        assert len({p.branch_name for p in out}) == 1
        assert out[0].branch_name.startswith("zerostrike/fix-batch-")
        # One clone, one baseline + one post scan — not 2 per finding.
        assert state["scans"] == 2
        # Per-finding traceability survives inside the batch PR.
        body = state["prs"][0]["body"]
        for name in files:
            assert name in body
        assert "3 findings" in state["prs"][0]["title"]

    asyncio.run(run())


def test_batch_drops_the_drifted_fix_and_ships_the_rest(client, monkeypatch):
    files = ["a.py", "b.py", "c.py"]
    state = _install(monkeypatch, files, drifted=["b.py"])

    async def run():
        proposals, job, _ = await _seed_batch(files, drifted=["b.py"])
        await apply_svc.run_job(job)
        a, b, c = await _reload(proposals)
        assert b.review_state == "manual_review"
        assert "Source changed" in b.manual_review_reason
        assert a.review_state == c.review_state == "pr_open"
        assert a.pr_url == c.pr_url
        assert len(state["prs"]) == 1
        assert "skipped" in state["prs"][0]["body"]

    asyncio.run(run())


def test_batch_drops_the_fix_that_fails_rescan_and_retries_the_rest(client, monkeypatch):
    files = ["a.py", "b.py", "c.py"]
    state = _install(monkeypatch, files, broken=["b.py"])

    async def run():
        proposals, job, _ = await _seed_batch(files)
        await apply_svc.run_job(job)
        a, b, c = await _reload(proposals)
        assert b.review_state == "manual_review"
        assert "did not clear" in b.manual_review_reason
        assert a.review_state == c.review_state == "pr_open"
        assert len(state["prs"]) == 1
        # baseline + first judgement + one bounded retry judgement. Never loops.
        assert state["scans"] == 3

    asyncio.run(run())


def test_batch_drops_the_fix_that_introduces_a_new_finding_in_its_own_file(client, monkeypatch):
    files = ["a.py", "b.py"]
    state = _install(monkeypatch, files, collateral={"a.py": "a.py"})

    async def run():
        proposals, job, _ = await _seed_batch(files)
        await apply_svc.run_job(job)
        a, b = await _reload(proposals)
        assert a.review_state == "manual_review"
        assert "introduced new" in a.manual_review_reason
        assert b.review_state == "pr_open"
        assert len(state["prs"]) == 1

    asyncio.run(run())


def test_batch_aborts_when_a_new_finding_cannot_be_attributed(client, monkeypatch):
    # A patch broke a file nothing in the batch touched: there is no safe subset to retry, so the
    # whole batch stops rather than guessing which fix to blame.
    files = ["a.py", "b.py"]
    state = _install(monkeypatch, files, collateral={"a.py": "untouched/other.py"})

    async def run():
        proposals, job, _ = await _seed_batch(files)
        await apply_svc.run_job(job)
        out = await _reload(proposals)
        assert [p.review_state for p in out] == ["manual_review"] * 2
        assert all("outside the patched files" in p.manual_review_reason for p in out)
        assert state["prs"] == []

    asyncio.run(run())


def test_batch_of_one_keeps_the_single_fix_pr_shape(client, monkeypatch):
    state = _install(monkeypatch, ["a.py"])

    async def run():
        proposals, job, _ = await _seed_batch(["a.py"])
        await apply_svc.run_job(job)
        (p,) = await _reload(proposals)
        assert p.review_state == "pr_open"
        assert p.branch_name.startswith("zerostrike/fix-") and "batch" not in p.branch_name
        assert state["prs"][0]["title"] == "zero-strike/security fix: Rule a.py"

    asyncio.run(run())


def test_legacy_apply_job_without_proposal_ids_still_runs(client, monkeypatch):
    # Rows written before batching set only the singular proposal_id; they must keep applying.
    _install(monkeypatch, ["a.py"])

    async def run():
        proposals, job, _ = await _seed_batch(["a.py"])
        job.proposal_ids = []
        await job.save()
        await apply_svc.run_job(job)
        (p,) = await _reload(proposals)
        assert p.review_state == "pr_open"

    asyncio.run(run())
