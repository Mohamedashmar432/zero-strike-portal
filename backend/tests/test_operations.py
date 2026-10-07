import asyncio
from datetime import datetime, timedelta, timezone

import app.services.cloud_scan_service as cloud_scan_service
import app.services.scan_queue_service as scan_queue_service
from app.models.scan import Scan
from app.services import operations_service
from app.services.operations_service import estimate_starts
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
AVG = timedelta(minutes=2)


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --- estimate_starts: the arithmetic behind every countdown -------------------------------------


def test_free_slots_start_now_then_jobs_wait_a_full_turn():
    # cap 2, nothing running: two start now, the third waits one average job.
    assert estimate_starts([], 3, 2, AVG, NOW) == [NOW, NOW, NOW + AVG]


def test_queued_jobs_take_the_earliest_slot_to_free_up():
    # Both slots busy: one job is 90s in (frees in 30s), the other just started (frees in 2m).
    running = [NOW - timedelta(seconds=90), NOW]
    starts = estimate_starts(running, 3, 2, AVG, NOW)
    assert starts == [NOW + timedelta(seconds=30), NOW + AVG, NOW + timedelta(seconds=150)]


def test_an_overdue_running_job_is_treated_as_finishing_now():
    assert estimate_starts([NOW - timedelta(hours=1)], 1, 1, AVG, NOW) == [NOW]


def test_over_cap_only_the_last_finishers_free_a_slot():
    # 3 running against a cap of 2 (e.g. the cap was just lowered): the first one to finish only
    # brings the queue back to its cap, so the next queued job waits for the second.
    running = [NOW - timedelta(seconds=100), NOW - timedelta(seconds=60), NOW]
    assert estimate_starts(running, 1, 2, AVG, NOW) == [NOW + timedelta(seconds=60)]


def test_nothing_queued_estimates_nothing():
    assert estimate_starts([NOW], 0, 2, AVG, NOW) == []


# --- the drain race -----------------------------------------------------------------------------


def test_overlapping_drains_never_exceed_the_cap(client, monkeypatch):
    """drain_queue reads free capacity, then claims. The poll loop, a finishing scan and a newly
    created one can all call it at once; without serializing, each sees the same free slots and the
    queue runs past max_concurrent_cloud_scans."""

    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr(cloud_scan_service, "run_cloud_scan", _noop)
    monkeypatch.setattr(scan_queue_service.settings, "max_concurrent_cloud_scans", 2)

    # mongomock answers without yielding to the event loop, so the drains would never interleave.
    # Real Motor yields on every round trip; this puts that yield back between "read capacity"
    # and "claim", which is exactly where the race lives.
    real_capacity = scan_queue_service._capacity

    async def _capacity_then_yield():
        free = await real_capacity()
        await asyncio.sleep(0)
        return free

    monkeypatch.setattr(scan_queue_service, "_capacity", _capacity_then_yield)

    async def run():
        base = datetime.now(timezone.utc)
        for i in range(6):
            await Scan(
                project_id="race",
                scan_type="cloud",
                triggered_by="cloud",
                status="queued",
                repo_url="https://github.com/example/repo",
                created_at=base + timedelta(seconds=i),
                updated_at=base,
            ).insert()
        await asyncio.gather(*(scan_queue_service.drain_queue() for _ in range(4)))
        await asyncio.sleep(0)
        assert await Scan.find(Scan.status == "running", Scan.project_id == "race").count() == 2

    asyncio.run(run())


# --- endpoints ----------------------------------------------------------------------------------


def _queued_scan(project_id, created_at, **kw):
    return Scan(
        project_id=project_id,
        scan_type="cloud",
        triggered_by="cloud",
        repo_url="https://github.com/acme/widgets.git",
        branch="main",
        created_at=created_at,
        updated_at=created_at,
        **{"status": "queued", **kw},
    )


def test_queue_positions_against_the_whole_queue_and_hides_other_projects(client, monkeypatch):
    monkeypatch.setattr(operations_service.settings, "max_concurrent_cloud_scans", 1)
    owner = register_and_login(client, email="opsowner@zerostrike.dev")
    project = client.post("/api/v1/projects", json={"name": "ops"}, headers=_h(owner)).json()
    pid = project["id"]
    now = datetime.now(timezone.utc)

    async def seed():
        # Another project's scan is running and one of its scans is ahead of ours in the queue.
        await _queued_scan("someone-else", now - timedelta(minutes=1), status="running", started_at=now).insert()
        await _queued_scan("someone-else", now - timedelta(seconds=30)).insert()
        mine = _queued_scan(pid, now, repo_token="ghp_must_not_leak")
        await mine.insert()
        return str(mine.id)

    mine_id = asyncio.run(seed())
    r = client.get("/api/v1/queue", headers=_h(owner))
    assert r.status_code == 200
    body = r.json()
    assert "ghp_must_not_leak" not in r.text

    assert [j["project_id"] for j in body["jobs"]] == [pid]
    job = body["jobs"][0]
    assert job["ref_id"] == mine_id
    assert job["summary"] == "widgets @ main"
    assert job["position"] == 2  # one scan from another project is ahead of it
    eta = datetime.fromisoformat(job["estimated_start_at"].replace("Z", "+00:00"))
    # Two default-length scans (180s) ahead: the running one, then the queued one.
    assert timedelta(seconds=300) < eta - now < timedelta(seconds=420)

    cloud = next(q for q in body["queues"] if q["kind"] == "cloud_scan")
    assert (cloud["running"], cloud["queued"], cloud["capacity"]) == (1, 2, 1)


def test_queue_shows_only_projects_the_caller_belongs_to_and_admins_see_all(client):
    owner = register_and_login(client, email="opsmember1@zerostrike.dev")
    pid = client.post("/api/v1/projects", json={"name": "ops2"}, headers=_h(owner)).json()["id"]

    async def seed():
        await _queued_scan(pid, datetime.now(timezone.utc)).insert()

    asyncio.run(seed())
    stranger = register_and_login(client, email="opsmember2@zerostrike.dev")
    r = client.get("/api/v1/queue", headers=_h(stranger))
    assert r.status_code == 200
    assert r.json()["jobs"] == []  # counted in the summaries, never listed
    assert next(q for q in r.json()["queues"] if q["kind"] == "cloud_scan")["queued"] >= 1

    admin = client.get("/api/v1/queue", headers=_admin_headers(client, email="opsqueueadmin@zerostrike.dev"))
    assert pid in {j["project_id"] for j in admin.json()["jobs"]}
    assert client.get("/api/v1/queue").status_code == 401


def test_admin_operations_shows_load_queues_and_failures(client):
    user = register_and_login(client, email="opsplain@zerostrike.dev")
    assert client.get("/api/v1/admin/operations", headers=_h(user)).status_code == 403

    now = datetime.now(timezone.utc)

    async def seed():
        await _queued_scan(
            "p-fail", now, status="failed", completed_at=now, error_message="git clone failed: auth required"
        ).insert()

    asyncio.run(seed())
    r = client.get("/api/v1/admin/operations", headers=_admin_headers(client, email="opsadmin@zerostrike.dev"))
    assert r.status_code == 200
    body = r.json()
    assert {q["kind"] for q in body["queues"]} == {"cloud_scan", "ai_analysis", "remediation", "compliance"}
    assert 0 <= body["system"]["cpu_percent"] <= 100
    assert body["system"]["memory_limit_bytes"] > 0
    failure = next(f for f in body["recent_failures"] if f["project_id"] == "p-fail")
    assert failure["error_message"] == "git clone failed: auth required"
    assert failure["status"] == "failed"


def test_zero_length_runs_do_not_drag_the_average_to_zero(client):
    """Seeded or instant rows (started_at == completed_at) are not runs. Averaging them in made the
    dev DB report a 0s cloud scan, so every countdown read 'starting any moment'."""

    async def run():
        t = datetime.now(timezone.utc)
        for _ in range(5):
            await _queued_scan("avg", t, status="completed", started_at=t, completed_at=t).insert()
        q = next(q for q in operations_service.QUEUES if q.kind == "cloud_scan")
        avg, is_default = await operations_service._avg_duration(q)
        assert is_default and avg == timedelta(seconds=q.default_seconds)

    asyncio.run(run())


def test_a_paused_queue_gives_no_start_time(client, monkeypatch):
    """Cap 0 means nothing starts until an admin raises it; an ETA would be a false promise."""
    monkeypatch.setattr(operations_service.settings, "max_concurrent_cloud_scans", 0)

    async def run():
        await _queued_scan("paused", datetime.now(timezone.utc)).insert()
        _, jobs = await operations_service._queue_state(operations_service.QUEUES[0], datetime.now(timezone.utc))
        job = next(j for j in jobs if j.project_id == "paused")
        assert job.position == 1 and job.estimated_start_at is None

    asyncio.run(run())
