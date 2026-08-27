from pathlib import Path

from app.services import data_management_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"


def _seed_project_with_scan(client, headers, name):
    """A project plus a real ingested scan — gives us Scan + Finding + Report rows."""
    project_id = client.post("/api/v1/projects", json={"name": name}, headers=headers).json()["id"]
    raw_token = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": "scanner", "expires_in_days": 30},
        headers=headers,
    ).json()["raw_token"]
    sh = {"Authorization": f"Bearer {raw_token}"}
    scan_id = client.post(
        "/api/v1/scans", json={"project_id": project_id, "scanner_version": "v0.22.0"}, headers=sh
    ).json()["scan_id"]
    client.post(
        f"/api/v1/scans/{scan_id}/upload/json",
        content=_FIXTURE.read_bytes(),
        headers={**sh, "Content-Type": "application/json"},
    )
    return project_id


def _totals(client, headers, project_id=None):
    qs = f"?project_id={project_id}" if project_id else ""
    body = client.get(f"/api/v1/admin/data/stats{qs}", headers=headers).json()
    return {c["key"]: c["total"] for c in body["categories"]}


# --- expand() is pure, so test the implication graph without a client ---


def test_expand_pulls_in_implied_categories():
    assert data_management_service.expand(["scan_data"]) == [
        "scan_data",
        "ai_artifacts",
        "compliance",
    ]


def test_expand_of_projects_covers_every_project_scoped_category():
    assert set(data_management_service.expand(["projects"])) == {
        "projects",
        "scan_data",
        "ai_artifacts",
        "compliance",
        "ai_usage",
    }


def test_expand_ignores_unknown_keys_and_dedupes():
    assert data_management_service.expand(["compliance", "compliance", "nope"]) == ["compliance"]


# --- auth ---


def test_non_admin_cannot_read_stats_or_purge(client):
    tokens = register_and_login(client, email="data-plain@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.get("/api/v1/admin/data/stats", headers=headers).status_code == 403
    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["scan_data"], "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 403


def test_stats_requires_authentication(client):
    assert client.get("/api/v1/admin/data/stats").status_code == 401


# --- stats ---


def test_stats_counts_seeded_scan_data(client):
    headers = _admin_headers(client, email="data-stats@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Stats Project")

    body = client.get("/api/v1/admin/data/stats", headers=headers).json()
    keys = [c["key"] for c in body["categories"]]
    assert keys == ["scan_data", "ai_artifacts", "compliance", "ai_usage", "audit_log", "projects"]

    by_key = {c["key"]: c for c in body["categories"]}
    assert by_key["scan_data"]["total"] > 0
    assert by_key["projects"]["total"] > 0
    # Collection names are surfaced so the UI can show exactly what dies.
    assert "scans" in [c["name"] for c in by_key["scan_data"]["collections"]]


def test_stats_scoped_to_a_project_excludes_other_projects(client):
    headers = _admin_headers(client, email="data-scope@zerostrike.dev")
    keep_id = _seed_project_with_scan(client, headers, "Keep")
    _seed_project_with_scan(client, headers, "Other")

    portal = _totals(client, headers)
    scoped = _totals(client, headers, keep_id)
    assert scoped["scan_data"] < portal["scan_data"]

    body = client.get(f"/api/v1/admin/data/stats?project_id={keep_id}", headers=headers).json()
    projects = next(c for c in body["categories"] if c["key"] == "projects")
    counts = {c["name"]: c["count"] for c in projects["collections"]}
    assert counts["projects"] == 1  # the scoped project itself, not the other one
    assert counts["api_keys"] == 1


# --- purge validation (must reject before deleting anything) ---


def test_purge_rejects_wrong_confirmation_phrase(client):
    headers = _admin_headers(client, email="data-confirm@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Confirm Project")
    before = _totals(client, headers)

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["scan_data"], "confirm": "delete"},
        headers=headers,
    )
    assert r.status_code == 422
    assert _totals(client, headers) == before


def test_purge_rejects_unknown_category_without_deleting(client):
    headers = _admin_headers(client, email="data-unknown@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Unknown Project")
    before = _totals(client, headers)

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["scan_data", "users"], "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "users" in r.json()["detail"]
    assert _totals(client, headers) == before


def test_purge_requires_at_least_one_category(client):
    headers = _admin_headers(client, email="data-empty@zerostrike.dev")
    r = client.post(
        "/api/v1/admin/data/purge", json={"categories": [], "confirm": "DELETE"}, headers=headers
    )
    assert r.status_code == 422


# --- purge behaviour ---


def test_purge_scan_data_clears_scans_but_keeps_projects_and_users(client):
    headers = _admin_headers(client, email="data-purge@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Purge Project")
    assert _totals(client, headers)["scan_data"] > 0

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["scan_data"], "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_deleted"] > 0
    assert body["deleted"]["scans"] > 0

    after = _totals(client, headers)
    assert after["scan_data"] == 0
    assert after["projects"] > 0  # projects survive a scan-data purge
    # The admin is still logged in and listed — users are never purgeable.
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200


def test_purge_scoped_to_one_project_leaves_the_other_intact(client):
    headers = _admin_headers(client, email="data-scoped-purge@zerostrike.dev")
    doomed_id = _seed_project_with_scan(client, headers, "Doomed")
    _seed_project_with_scan(client, headers, "Survivor")
    survivor_scans = _totals(client, headers)["scan_data"] - _totals(client, headers, doomed_id)["scan_data"]

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["scan_data"], "project_id": doomed_id, "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 200

    assert _totals(client, headers, doomed_id)["scan_data"] == 0
    assert _totals(client, headers)["scan_data"] == survivor_scans


def test_purging_projects_also_removes_their_scan_data(client):
    headers = _admin_headers(client, email="data-projects@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Everything")

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["projects"], "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 200
    assert set(r.json()["categories"]) == {
        "projects",
        "scan_data",
        "ai_artifacts",
        "compliance",
        "ai_usage",
    }

    after = _totals(client, headers)
    assert after["projects"] == 0
    assert after["scan_data"] == 0
    assert client.get("/api/v1/projects", headers=headers).json()["total"] == 0


def test_purge_is_recorded_in_the_audit_log_even_when_the_log_itself_is_purged(client):
    headers = _admin_headers(client, email="data-audit@zerostrike.dev")
    _seed_project_with_scan(client, headers, "Audited")

    r = client.post(
        "/api/v1/admin/data/purge",
        json={"categories": ["audit_log"], "confirm": "DELETE"},
        headers=headers,
    )
    assert r.status_code == 200

    # Recorded after the wipe, so exactly one entry remains: the purge itself.
    logs = client.get("/api/v1/audit-logs", headers=headers).json()["items"]
    actions = [entry["action"] for entry in logs]
    assert actions == ["admin.data.purge"]


def test_reap_stuck_scans_is_admin_only_and_succeeds(client):
    headers = _admin_headers(client, email="data-reap@zerostrike.dev")
    tokens = register_and_login(client, email="data-reap-plain@zerostrike.dev")
    plain = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.post("/api/v1/admin/data/reap-stuck-scans", headers=plain).status_code == 403
    r = client.post("/api/v1/admin/data/reap-stuck-scans", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"reaped": True}


# --- regression: project deletion must not orphan collections ---


def test_deleting_a_project_leaves_no_rows_behind_for_it(client):
    headers = _admin_headers(client, email="data-cascade@zerostrike.dev")
    project_id = _seed_project_with_scan(client, headers, "Cascade")
    assert _totals(client, headers, project_id)["scan_data"] > 0

    assert client.delete(f"/api/v1/projects/{project_id}", headers=headers).status_code == 204

    scoped = _totals(client, headers, project_id)
    # The audit trail deliberately outlives the project it describes — everything else goes.
    leftovers = {key: total for key, total in scoped.items() if key != "audit_log" and total}
    assert leftovers == {}, leftovers
