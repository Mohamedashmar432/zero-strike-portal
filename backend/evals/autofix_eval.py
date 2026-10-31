"""Live Auto-Fix eval: runs the real agent + critic over synthetic vulnerable files using the
portal-wide provider configured in the dev database, then scores each proposal. Costs tokens, so it
is opt-in and never part of pytest (only score() is unit-tested).

    cd backend && ./.venv/Scripts/python -m evals.autofix_eval [project_id]

Run it before and after any change to an Auto-Fix prompt, tool or model, and compare pass count,
calls, tokens and cost. Usage rows land in AIUsageEvent under job_id "eval-<timestamp>".
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from app.db.mongo import connect_to_mongo
from app.models.ai_usage_event import AIUsageEvent
from app.services import ai_remediation_agent, llm_client, remediation_critic
from app.services.remediation_tools import SubmitFixProposalArgs, ToolContext

CASES = Path(__file__).parent / "fixtures" / "autofix"


def score(case: dict, p: SubmitFixProposalArgs) -> list[str]:
    """Failure reasons for one proposal; [] means pass."""
    exp = case["expect"]
    if p.can_fix != exp["can_fix"]:
        return [f"can_fix={p.can_fix}, expected {exp['can_fix']}"]
    if not p.can_fix:
        return []
    if p.file_path != case["file"]:
        return [f"wrong file: {p.file_path}"]
    patched = p.patched_code or ""
    fails = [f"still contains {s!r}" for s in exp.get("must_not_contain", []) if s in patched]
    any_of = exp.get("must_contain_any", [])
    if any_of and not any(s in patched for s in any_of):
        fails.append(f"contains none of {any_of}")
    return fails


async def _run_case(case_dir: Path, job_id: str, project_id: str | None) -> dict:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    repo = case_dir / "repo"
    ctx = ToolContext(
        provider="", repo_full_name="", branch="main", allowed_paths=[case["file"]],
        project_id=project_id, scan_id=None, trace_id=job_id,
        finding_context={
            "finding_id": case["id"], "file_path": case["file"], "language": case["language"],
            "original_code": case["snippet"], "start_line": case["line"], "end_line": case["line"],
        },
        workdir=str(repo),
    )
    bundle = {k: case[k] for k in ("rule_id", "cwe", "message", "file", "line", "snippet")}
    bundle["finding_id"] = case["id"]
    excerpt = (repo / case["file"]).read_text(encoding="utf-8")
    started = time.perf_counter()
    with llm_client.call_scope(job_id=job_id, finding_id=case["id"]):
        try:
            draft = await ai_remediation_agent.run_agent(bundle, ctx, ai_remediation_agent.budgets_from_settings())
        except llm_client.LLMError as exc:  # report it per case, as the pipeline would, not as a crash
            return {"id": case["id"], "fails": [f"provider error: {type(exc).__name__}"],
                    "seconds": round(time.perf_counter() - started, 1), "critic": "skipped"}
        verdict = await remediation_critic.critique(
            bundle, draft, project_id=project_id, scan_id=None, file_excerpt=excerpt
        )
    if verdict is not None:
        draft = remediation_critic.apply_to_draft(draft, verdict)
    return {
        "id": case["id"], "fails": score(case, draft), "seconds": round(time.perf_counter() - started, 1),
        "critic": verdict.normalized_verdict if verdict else "skipped",
    }


async def main(project_id: str | None) -> None:
    await connect_to_mongo()
    job_id = f"eval-{int(time.time())}"
    results = [await _run_case(d, job_id, project_id) for d in sorted(p for p in CASES.iterdir() if p.is_dir())]
    events = await AIUsageEvent.find({"job_id": job_id}).to_list()
    for r in results:
        mine = [e for e in events if e.finding_id == r["id"]]
        tokens = sum(e.prompt_tokens + e.completion_tokens for e in mine)
        status = "PASS" if not r["fails"] else "FAIL " + "; ".join(r["fails"])
        print(f"{r['id']:<18} {status:<40} calls={len(mine):<3} tokens={tokens:<7} "
              f"cached={sum(e.cached_prompt_tokens for e in mine):<6} critic={r['critic']:<8} {r['seconds']}s")
    passed = sum(1 for r in results if not r["fails"])
    cost = sum(e.cost_usd for e in events)
    print(f"\n{passed}/{len(results)} passed · {len(events)} calls · ${cost:.4f} · job_id={job_id}")


if __name__ == "__main__":
    # With Project BYOK on, a call with no project has no key it may use; pass a project id whose own
    # provider should run the eval (its usage is billed to that project).
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
