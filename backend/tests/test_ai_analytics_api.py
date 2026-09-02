"""The AI usage dashboard at both scopes: a project's own calls, and portal-wide."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.ai_usage_event import AIUsageEvent
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Analytics Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _seed(events: list[dict]) -> None:
    now = datetime.now(timezone.utc)

    async def go():
        for e in events:
            await AIUsageEvent(
                project_id=e.get("project_id"),
                scope="project" if e.get("project_id") else "portal",
                provider=e.get("provider", "openai"),
                model_name=e.get("model_name", "gpt-4o"),
                feature=e.get("feature", "analysis"),
                status=e.get("status", "success"),
                error_type=e.get("error_type"),
                error_code=e.get("error_code"),
                duration_ms=e.get("duration_ms", 100),
                prompt_tokens=e.get("prompt_tokens", 10),
                completion_tokens=e.get("completion_tokens", 5),
                cost_usd=e.get("cost_usd", 0.01),
                created_at=now - timedelta(days=e.get("days_ago", 0)),
            ).insert()

    asyncio.run(go())


def test_project_analytics_never_leak_another_projects_spend(client):
    owner = register_and_login(client, email="an-owner1@zerostrike.dev")
    mine = _create_project(client, _headers(owner), name="Mine")
    theirs = _create_project(client, _headers(owner), name="Theirs")

    _seed(
        [
            {"project_id": mine["id"], "cost_usd": 0.10, "prompt_tokens": 100},
            {"project_id": mine["id"], "cost_usd": 0.05, "prompt_tokens": 50},
            {"project_id": theirs["id"], "cost_usd": 9.99, "prompt_tokens": 9999},
        ]
    )

    r = client.get(f"/api/v1/projects/{mine['id']}/ai-analytics", headers=_headers(owner))
    assert r.status_code == 200
    totals = r.json()["totals"]
    assert totals["requests"] == 2
    assert round(totals["cost_usd"], 4) == 0.15
    assert totals["prompt_tokens"] == 150
    # by_project is the portal-wide breakdown; a project must never be handed the cross-project view.
    assert r.json()["by_project"] == []


def test_failures_are_counted_and_shown_in_the_success_rate(client):
    owner = register_and_login(client, email="an-owner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    _seed(
        [
            {"project_id": project["id"], "status": "success"},
            {"project_id": project["id"], "status": "success"},
            {"project_id": project["id"], "status": "success"},
            {"project_id": project["id"], "status": "failed", "error_type": "LLMPermanentError"},
        ]
    )

    totals = client.get(
        f"/api/v1/projects/{project['id']}/ai-analytics", headers=_headers(owner)
    ).json()["totals"]
    assert (totals["requests"], totals["failed"]) == (4, 1)
    assert totals["success_rate"] == 75.0


def test_empty_window_reports_zero_spend_not_a_fabricated_number(client):
    owner = register_and_login(client, email="an-owner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    body = client.get(
        f"/api/v1/projects/{project['id']}/ai-analytics", headers=_headers(owner)
    ).json()
    assert body["totals"]["requests"] == 0
    assert body["totals"]["cost_usd"] == 0.0
    # No calls is not "everything failed" -- the KPI must not read 0% success on a quiet project.
    assert body["totals"]["success_rate"] == 100.0
    assert body["timeseries"] == [] and body["by_feature"] == []


def test_the_days_window_excludes_older_events(client):
    owner = register_and_login(client, email="an-owner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    _seed(
        [
            {"project_id": project["id"], "days_ago": 1},
            {"project_id": project["id"], "days_ago": 45},
        ]
    )

    url = f"/api/v1/projects/{project['id']}/ai-analytics"
    assert client.get(url, params={"days": 7}, headers=_headers(owner)).json()["totals"]["requests"] == 1
    assert client.get(url, params={"days": 90}, headers=_headers(owner)).json()["totals"]["requests"] == 2


def test_breakdowns_split_by_feature_and_model(client):
    owner = register_and_login(client, email="an-owner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    _seed(
        [
            {"project_id": project["id"], "feature": "analysis", "cost_usd": 0.30},
            {"project_id": project["id"], "feature": "analysis", "cost_usd": 0.20},
            {"project_id": project["id"], "feature": "autofix", "cost_usd": 1.00,
             "provider": "anthropic", "model_name": "claude-sonnet-4-5"},
        ]
    )

    body = client.get(
        f"/api/v1/projects/{project['id']}/ai-analytics", headers=_headers(owner)
    ).json()
    by_feature = {row["feature"]: row for row in body["by_feature"]}
    assert by_feature["analysis"]["requests"] == 2
    assert round(by_feature["analysis"]["cost_usd"], 4) == 0.50
    assert by_feature["autofix"]["requests"] == 1
    # Sorted by spend so the most expensive feature is the first thing the chart shows.
    assert body["by_feature"][0]["feature"] == "autofix"

    by_model = {(m["provider"], m["model_name"]): m for m in body["by_model"]}
    assert set(by_model) == {("openai", "gpt-4o"), ("anthropic", "claude-sonnet-4-5")}


def test_non_member_cannot_read_a_projects_ai_analytics(client):
    owner = register_and_login(client, email="an-owner6@zerostrike.dev")
    outsider = register_and_login(client, email="an-outsider6@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    assert (
        client.get(f"/api/v1/projects/{project['id']}/ai-analytics", headers=_headers(outsider)).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/projects/{project['id']}/ai-events", headers=_headers(outsider)).status_code
        == 403
    )


# --- portal scope ---------------------------------------------------------------------------


def test_portal_analytics_are_admin_only_and_span_every_project(client):
    admin_headers = _admin_headers(client, email="an-admin1@zerostrike.dev")
    owner = register_and_login(client, email="an-owner7@zerostrike.dev")
    a = _create_project(client, _headers(owner), name="Alpha")
    b = _create_project(client, _headers(owner), name="Beta")

    _seed(
        [
            {"project_id": a["id"], "cost_usd": 1.00},
            {"project_id": b["id"], "cost_usd": 4.00},
        ]
    )

    assert client.get("/api/v1/admin/ai-analytics", headers=_headers(owner)).status_code == 403

    body = client.get("/api/v1/admin/ai-analytics", headers=admin_headers).json()
    assert body["totals"]["requests"] == 2
    assert round(body["totals"]["cost_usd"], 4) == 5.00

    by_project = {row["project_name"]: row for row in body["by_project"]}
    assert set(by_project) == {"Alpha", "Beta"}
    # Ranked by spend -- the point of the portal view is "who is costing what".
    assert body["by_project"][0]["project_name"] == "Beta"


def test_portal_view_can_be_narrowed_to_one_project(client):
    admin_headers = _admin_headers(client, email="an-admin2@zerostrike.dev")
    owner = register_and_login(client, email="an-owner8@zerostrike.dev")
    a = _create_project(client, _headers(owner), name="Alpha")
    b = _create_project(client, _headers(owner), name="Beta")
    _seed([{"project_id": a["id"]}, {"project_id": b["id"]}, {"project_id": b["id"]}])

    body = client.get(
        "/api/v1/admin/ai-analytics", params={"project_id": b["id"]}, headers=admin_headers
    ).json()
    assert body["totals"]["requests"] == 2


# --- the call log ---------------------------------------------------------------------------


def test_event_log_is_newest_first_paginated_and_filterable(client):
    owner = register_and_login(client, email="an-owner9@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    _seed(
        [
            {"project_id": project["id"], "feature": "analysis", "days_ago": 3},
            {"project_id": project["id"], "feature": "autofix", "days_ago": 2},
            {"project_id": project["id"], "feature": "autofix", "days_ago": 1,
             "status": "failed", "error_type": "LLMTransientError"},
        ]
    )

    url = f"/api/v1/projects/{project['id']}/ai-events"
    page = client.get(url, headers=_headers(owner)).json()
    assert page["total"] == 3
    assert [i["feature"] for i in page["items"]] == ["autofix", "autofix", "analysis"]
    assert page["items"][0]["error_type"] == "LLMTransientError"
    assert page["items"][0]["project_name"] == "Analytics Demo"

    first = client.get(url, params={"page_size": 2}, headers=_headers(owner)).json()
    assert len(first["items"]) == 2 and first["total"] == 3

    only_failed = client.get(url, params={"status": "failed"}, headers=_headers(owner)).json()
    assert only_failed["total"] == 1

    only_autofix = client.get(url, params={"feature": "autofix"}, headers=_headers(owner)).json()
    assert only_autofix["total"] == 2


def test_event_log_never_carries_prompt_or_response_content(client):
    """Prompts here contain customer source and findings; the log is metadata only, by design."""
    owner = register_and_login(client, email="an-owner10@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    _seed([{"project_id": project["id"]}])

    item = client.get(f"/api/v1/projects/{project['id']}/ai-events", headers=_headers(owner)).json()[
        "items"
    ][0]
    assert not {"prompt", "messages", "response", "content", "completion"} & set(item)


# --- spend attribution: which workflow moved the number ---


def test_feature_rows_carry_the_change_against_the_previous_window(client):
    """Descriptive totals don't explain a bill. Each feature reports its own previous-window
    spend and delta so "spend doubled" resolves to "remediation doubled"."""
    owner = register_and_login(client, email="an-delta@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Delta")
    _seed(
        [
            # This window (last 30 days): autofix up sharply, compliance flat.
            {"project_id": project["id"], "feature": "autofix", "cost_usd": 1.00, "days_ago": 2},
            {"project_id": project["id"], "feature": "autofix", "cost_usd": 1.00, "days_ago": 3},
            {"project_id": project["id"], "feature": "compliance", "cost_usd": 0.10, "days_ago": 4},
            # Previous window (31-60 days ago).
            {"project_id": project["id"], "feature": "autofix", "cost_usd": 0.20, "days_ago": 40},
            {"project_id": project["id"], "feature": "compliance", "cost_usd": 0.10, "days_ago": 41},
            {"project_id": project["id"], "feature": "repo_doc", "cost_usd": 0.50, "days_ago": 42},
            # Outside both windows entirely — must not colour either number.
            {"project_id": project["id"], "feature": "autofix", "cost_usd": 5.00, "days_ago": 200},
        ]
    )

    r = client.get(
        f"/api/v1/projects/{project['id']}/ai-analytics?days=30", headers=_headers(owner)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert round(body["totals"]["cost_usd"], 2) == 2.10
    assert round(body["previous_totals"]["cost_usd"], 2) == 0.80

    rows = {row["feature"]: row for row in body["by_feature"]}
    assert round(rows["autofix"]["cost_delta_usd"], 2) == 1.80
    assert rows["autofix"]["requests_delta"] == 1
    assert round(rows["compliance"]["cost_delta_usd"], 2) == 0.00
    # A feature that stopped spending still appears, as a negative delta — otherwise a drop is
    # invisible and the totals look unexplained.
    assert rows["repo_doc"]["cost_usd"] == 0.0
    assert round(rows["repo_doc"]["cost_delta_usd"], 2) == -0.50
    assert rows["repo_doc"]["requests_delta"] == -1


def test_failure_reasons_break_down_why_calls_failed(client):
    """The totals say how many calls failed; this says whether the fix is a bigger context
    window, a new key, or patience. Rows predating error_code group under "unknown" rather than
    dropping out, so the reasons still add up to the failure count."""
    owner = register_and_login(client, email="an-owner-fr@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Reasons")

    _seed(
        [
            {"project_id": project["id"], "status": "failed", "error_code": "context_length_exceeded"},
            {"project_id": project["id"], "status": "failed", "error_code": "context_length_exceeded"},
            {"project_id": project["id"], "status": "failed", "error_code": "auth_failed"},
            {"project_id": project["id"], "status": "failed"},  # legacy row, no error_code
            {"project_id": project["id"], "status": "success"},
        ]
    )

    r = client.get(f"/api/v1/projects/{project['id']}/ai-analytics", headers=_headers(owner))
    assert r.status_code == 200
    body = r.json()
    assert body["failure_reasons"] == [
        {"error_code": "context_length_exceeded", "count": 2},
        {"error_code": "auth_failed", "count": 1},
        {"error_code": "unknown", "count": 1},
    ]
    assert sum(row["count"] for row in body["failure_reasons"]) == body["totals"]["failed"]
