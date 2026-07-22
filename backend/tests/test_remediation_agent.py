"""Unit tests for the remediation agent loop + tool dispatch (no DB).

The loop is exercised with a scripted fake llm_client.get_tool_completion so all budget/repair
branches are deterministic.
"""

import asyncio
import json

from app.services import llm_client, remediation_tools
from app.services.ai_remediation_agent import AgentBudgets, run_agent
from app.services.remediation_tools import ToolContext

BUDGETS = AgentBudgets(max_steps=5, token_budget=100000, max_invalid=2)


def _ctx():
    return ToolContext(
        provider="anthropic",
        repo_full_name="o/r",
        branch="main",
        allowed_paths=["app.py"],
        project_id="p",
        scan_id="s",
        trace_id="t",
        finding_context={
            "finding_id": "F1",
            "file_path": "app.py",
            "language": "python",
            "original_code": "q = 'SELECT * FROM u WHERE id=' + id",
            "start_line": 10,
            "end_line": 10,
        },
    )


def _tool_call(name, args: dict, cid="c1"):
    return llm_client.LLMToolCall(id=cid, name=name, arguments=json.dumps(args))


def _resp(tool_calls, content=None):
    return llm_client.LLMToolResponse(content=content, tool_calls=tool_calls, prompt_tokens=10, completion_tokens=10)


def _script(monkeypatch, responses):
    it = iter(responses)

    async def fake(messages, **kwargs):
        return next(it)

    monkeypatch.setattr(llm_client, "get_tool_completion", fake)


def test_happy_path_reads_then_submits(monkeypatch):
    submit = {
        "finding_id": "F1", "can_fix": True, "confidence_score": 90, "file_path": "app.py",
        "original_code": "x", "patched_code": "y", "explanation": "parameterized the query",
        "patch_scope": "single-line",
    }
    _script(monkeypatch, [
        _resp([_tool_call("read_excerpt", {"path": "app.py", "start_line": 10, "end_line": 10})]),
        _resp([_tool_call("submit_fix_proposal", submit)]),
    ])
    result = asyncio.run(run_agent({"finding_id": "F1"}, _ctx(), BUDGETS))
    assert result.can_fix is True
    assert result.confidence_score == 90
    assert result.file_path == "app.py"


def test_scope_violation_then_repair(monkeypatch):
    bad = {"finding_id": "F1", "can_fix": True, "confidence_score": 80, "file_path": "OTHER.py",
           "explanation": "e"}
    good = {"finding_id": "F1", "can_fix": True, "confidence_score": 80, "file_path": "app.py",
            "original_code": "x", "patched_code": "y", "explanation": "e"}
    _script(monkeypatch, [
        _resp([_tool_call("submit_fix_proposal", bad)]),   # file outside allowed_paths -> repair
        _resp([_tool_call("submit_fix_proposal", good)]),
    ])
    result = asyncio.run(run_agent({"finding_id": "F1"}, _ctx(), BUDGETS))
    assert result.file_path == "app.py"


def test_provider_never_calls_tool_bails(monkeypatch):
    # Every response is prose with no tool_calls -> exceeds max_invalid -> can_fix=False bail.
    _script(monkeypatch, [_resp([], content="here is some prose") for _ in range(10)])
    result = asyncio.run(run_agent({"finding_id": "F1"}, _ctx(), BUDGETS))
    assert result.can_fix is False
    assert result.finding_id == "F1"


def test_step_budget_exhaustion_force_submits_then_bails(monkeypatch):
    # Keeps calling a read tool forever; force-submit call also yields no submit -> bail.
    read = _resp([_tool_call("read_file", {"path": "app.py"})])
    _script(monkeypatch, [read] * 20)
    result = asyncio.run(run_agent({"finding_id": "F1"}, _ctx(), AgentBudgets(2, 100000, 2)))
    assert result.can_fix is False


def test_dispatch_read_excerpt_and_path_scope():
    ctx = _ctx()

    async def run():
        ok = await remediation_tools.dispatch(
            "read_excerpt", json.dumps({"path": "app.py", "start_line": 10, "end_line": 10}), ctx
        )
        bad = await remediation_tools.dispatch("read_file", json.dumps({"path": "../secrets.py"}), ctx)
        diff = await remediation_tools.dispatch(
            "compute_diff", json.dumps({"path": "app.py", "patched_code": "safe"}), ctx
        )
        unknown = await remediation_tools.dispatch("rm_rf", "{}", ctx)
        return ok, bad, diff, unknown

    ok, bad, diff, unknown = asyncio.run(run())
    assert "content" in ok and ok["content"]
    assert "error" in bad  # path traversal rejected
    assert diff["touches_allowed_paths"] is True and "unified_diff" in diff
    assert "error" in unknown
