import asyncio
from datetime import datetime, timedelta, timezone

from app.models.scan import Scan
from tests.test_auth_flow import register_and_login
from tests.test_cloud_scan_quota import _seed
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

_URL = "/api/v1/admin/project-insights"


def _insert(project_id, *, status, scan_type="cloud", age_days=0, error=None, repo_url=None, token=None):
    async def run():
        at = datetime.now(timezone.utc) - timedelta(days=age_days)
        await Scan(
            project_id=project_id,
            scan_type=scan_type,
            triggered_by="cloud" if scan_type == "cloud" else "ci",
            status=status,
            error_message=error,
            repo_url=repo_url,
            repo_token=token,
            created_at=at,
            updated_at=at,
        ).insert()

    asyncio.run(run())


def _row(body, pid):
    return next(p for p in body["projects"] if p["project_id"] == pid)


def test_non_admin_is_403_on_both_endpoints(client):
    owner = _headers(register_and_login(client, email="ins-owner@zerostrike.dev"))
    assert client.get(_URL, headers=owner).status_code == 403
    assert client.get(f"{_URL}/requests", headers=owner).status_code == 403


def test_counts_respect_the_window_and_split_by_type(client):
    owner = _headers(register_and_login(client, email="ins-owner2@zerostrike.dev"))
    pid = _create_project(client, owner, "Insights A")["id"]
    _insert(pid, status="completed")
    _insert(pid, status="failed", error="clone failed: repository not found")
    _insert(pid, status="queued")
    _insert(pid, status="running", scan_type="cicd")
    _insert(pid, status="completed", scan_type="cicd")
    _insert(pid, status="completed", age_days=60)  # outside the default 30d window
    admin = _admin_headers(client)

    body = client.get(_URL, headers=admin).json()
    row = _row(body, pid)
    assert row["cloud"] == {"total": 3, "completed": 1, "failed": 1, "active": 1}
    assert row["cicd"] == {"total": 2, "completed": 1, "failed": 0, "active": 1}
    assert row["last_error"]["message"] == "clone failed: repository not found"
    assert row["last_error"]["scan_type"] == "cloud"
    assert row["cloud_scan_quota"]["used"] == 3  # the 60-day-old scan is in an earlier month
    assert body["totals"]["cloud"]["total"] == 3
    assert body["totals"]["projects"] == 1
    assert body["totals"]["projects_created"] == 1

    wide = client.get(_URL, params={"since": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()}, headers=admin)
    assert _row(wide.json(), pid)["cloud"]["total"] == 4


def test_range_longer_than_366_days_is_rejected(client):
    admin = _admin_headers(client)
    since = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    assert client.get(_URL, params={"since": since}, headers=admin).status_code == 422


def test_requests_filter_page_and_never_expose_the_token(client):
    owner = _headers(register_and_login(client, email="ins-owner3@zerostrike.dev"))
    pid = _create_project(client, owner, "Insights B")["id"]
    _insert(pid, status="failed", error="boom", repo_url="https://x-access-token:ghp_SECRET@github.com/example/repo.git", token="enc-secret")
    _insert(pid, status="completed")
    _insert(pid, status="completed", scan_type="cicd")
    admin = _admin_headers(client)

    everything = client.get(f"{_URL}/requests", params={"project_id": pid}, headers=admin)
    assert everything.status_code == 200
    assert everything.json()["total"] == 3
    assert "enc-secret" not in everything.text and "ghp_SECRET" not in everything.text
    assert "repo_token" not in everything.text

    failed = client.get(f"{_URL}/requests", params={"project_id": pid, "status": "failed"}, headers=admin).json()
    assert failed["total"] == 1
    item = failed["items"][0]
    assert (item["project_name"], item["error_message"], item["quota_exempt"]) == ("Insights B", "boom", False)
    assert item["repo_url"] == "https://github.com/example/repo.git"  # userinfo stripped

    cicd = client.get(f"{_URL}/requests", params={"project_id": pid, "scan_type": "cicd"}, headers=admin).json()
    assert cicd["total"] == 1 and cicd["items"][0]["scan_type"] == "cicd"

    paged = client.get(f"{_URL}/requests", params={"project_id": pid, "limit": 2, "offset": 2}, headers=admin).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1
    assert client.get(f"{_URL}/requests", params={"limit": 201}, headers=admin).status_code == 422


def test_request_for_a_deleted_project_has_no_name(client):
    _seed("0" * 24, 1)
    admin = _admin_headers(client)
    items = client.get(f"{_URL}/requests", headers=admin).json()["items"]
    assert items[0]["project_name"] is None
