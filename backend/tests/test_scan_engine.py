"""Scan Engine admin API and service: stats, retire/restore, custom rules, versions."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.project import Project
from app.models.scan import Scan
from app.models.scan_engine import RulePackVersion
from app.models.vulnerability import Vulnerability
from app.services import cloud_scan_service as css
from app.services import scan_engine_service as engine
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

BASE = "/api/v1/admin/scan-engine"
_VALID_YAML = (
    "id: ZS-CUSTOM-001\nname: Custom Marker\nlanguage: python\nseverity: high\n"
    "match:\n  kind: call\n  callee: custom_danger\n"
)


@pytest.fixture()
def admin(client):
    return _admin_headers(client)


def _fake_scanner(monkeypatch, *, vulnerable_fires=True, safe_fires=False):
    async def fake(sample_dir, rules_dir):
        fires = vulnerable_fires if sample_dir.endswith("vulnerable") else safe_fires
        return {"ZS-CUSTOM-001"} if fires else set()

    monkeypatch.setattr(engine, "_run_scanner_on", fake)


def _custom(client, admin, yaml=_VALID_YAML):
    return client.post(
        f"{BASE}/custom-rules",
        json={"yaml": yaml, "vulnerable_sample": "custom_danger(x)", "safe_sample": "print(x)"},
        headers=admin,
    )


def test_every_endpoint_rejects_a_non_admin(client):
    tokens = register_and_login(client, email="member@zerostrike.dev")
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    calls = [
        ("get", f"{BASE}/rules", None),
        ("get", f"{BASE}/rules/ZS-PY-001/history", None),
        ("post", f"{BASE}/rules/ZS-PY-001/retire", {"reason": "x"}),
        ("post", f"{BASE}/rules/ZS-PY-001/restore", None),
        ("put", f"{BASE}/thresholds", {"min_fp_tags": 5, "min_fp_percent": 40}),
        ("get", f"{BASE}/custom-rules", None),
        ("post", f"{BASE}/custom-rules", {"yaml": "a", "vulnerable_sample": "b", "safe_sample": "c"}),
        ("delete", f"{BASE}/custom-rules/ZS-CUSTOM-001", None),
        ("get", f"{BASE}/pending", None),
        ("get", f"{BASE}/versions", None),
        ("get", f"{BASE}/versions/1", None),
        ("post", f"{BASE}/versions", {"changelog": "x"}),
        ("post", f"{BASE}/versions/1/rollback", {}),
    ]
    for method, url, body in calls:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, headers=h, **kwargs)
        assert r.status_code == 403, (method, url, r.status_code)


async def _vuln(project_id, rule_id, fp, *, false_positive, comment="not reachable"):
    now = datetime.now(timezone.utc)
    await Vulnerability(
        project_id=project_id,
        repo_scope_key="__unlinked__",
        fingerprint=fp,
        status="resolved" if false_positive else "open",
        resolution_reason="false_positive" if false_positive else None,
        resolution_comment=comment if false_positive else None,
        resolved_by_user_id="u1" if false_positive else None,
        resolved_at=now if false_positive else None,
        current_rule_id=rule_id,
        current_rule_name=f"Title {rule_id}",
        current_severity="high",
        first_seen_at=now,
        last_seen_at=now,
    ).insert()


def test_rule_stats_flag_noisy_rules_and_sort_by_fp_tags(client, admin):
    async def seed():
        now = datetime.now(timezone.utc)
        p = Project(name="Proj A", owner_id="o", created_at=now, updated_at=now)
        await p.insert()
        pid = str(p.id)
        for i in range(5):  # 5 of 6 tagged: noisy
            await _vuln(pid, "ZS-NOISY", f"n{i}", false_positive=True)
        await _vuln(pid, "ZS-NOISY", "n-open", false_positive=False)
        await _vuln(pid, "ZS-QUIET", "q1", false_positive=True)
        for i in range(9):  # 1 of 10 tagged: under the percent floor
            await _vuln(pid, "ZS-BIG", f"b{i}", false_positive=False)
        await _vuln(pid, "ZS-BIG", "b-fp", false_positive=True)

    asyncio.run(seed())
    data = client.get(f"{BASE}/rules", headers=admin).json()
    rows = {r["rule_id"]: r for r in data["rules"]}
    assert data["rules"][0]["rule_id"] == "ZS-NOISY"
    assert rows["ZS-NOISY"]["noisy"] is True and rows["ZS-NOISY"]["fp_tags"] == 5
    assert rows["ZS-NOISY"]["total_findings"] == 6 and rows["ZS-NOISY"]["projects_affected"] == 1
    assert rows["ZS-QUIET"]["noisy"] is False and rows["ZS-BIG"]["noisy"] is False
    assert data["noisy_min_fp_tags"] == 5 and data["noisy_min_fp_percent"] == 40
    hist = client.get(f"{BASE}/rules/ZS-NOISY/history", headers=admin).json()["fp_tags"]
    assert len(hist) == 5 and hist[0]["project_name"] == "Proj A" and hist[0]["comment"] == "not reachable"


def test_retired_rule_is_hidden_from_vulnerability_list_and_summary_until_restored(client, admin):
    pid = client.post("/api/v1/projects", json={"name": "Retire Demo"}, headers=admin).json()["id"]

    async def seed():
        await _vuln(pid, "ZS-RETIRE-ME", "r1", false_positive=False)
        await _vuln(pid, "ZS-KEEP", "k1", false_positive=False)

    asyncio.run(seed())

    def visible():
        items = client.get(f"/api/v1/projects/{pid}/vulnerabilities", headers=admin).json()["items"]
        return {v["fingerprint"] for v in items}

    def open_count():
        return client.get(f"/api/v1/projects/{pid}/vulnerabilities/summary", headers=admin).json()["open"]

    assert visible() == {"r1", "k1"} and open_count() == 2
    assert client.post(f"{BASE}/rules/ZS-RETIRE-ME/retire", json={"reason": "noisy"}, headers=admin).is_success
    assert visible() == {"r1", "k1"}  # a draft changes nothing until it is published
    assert client.post(f"{BASE}/versions", json={"changelog": "retire"}, headers=admin).is_success
    assert visible() == {"k1"} and open_count() == 1
    assert client.post(f"{BASE}/rules/ZS-RETIRE-ME/restore", headers=admin).is_success
    assert client.post(f"{BASE}/versions", json={"changelog": "restore"}, headers=admin).is_success
    assert visible() == {"r1", "k1"} and open_count() == 2


def test_crossing_the_noisy_threshold_notifies_admins_once(client, admin):
    async def run():
        from app.services import workspace_settings_service as wss

        await wss.update_workspace_settings(noisy_rule_min_fp_tags=2, noisy_rule_min_fp_percent=50)
        await _vuln("p1", "ZS-NOISY", "a", false_positive=True)
        await engine.check_rule_noisy("ZS-NOISY")  # 1 tag: below the floor
        await _vuln("p1", "ZS-NOISY", "b", false_positive=True)
        await engine.check_rule_noisy("ZS-NOISY")
        await engine.check_rule_noisy("ZS-NOISY")  # already notified
        return await Notification.find(Notification.event == "scan_engine.rule_noisy").to_list()

    assert len(asyncio.run(run())) == 1  # one admin, one notification


def test_retire_publish_and_restore_flow(client, admin):
    retire = f"{BASE}/rules/ZS-PY-001/retire"
    assert client.post(retire, json={"reason": ""}, headers=admin).status_code == 422
    assert client.post(retire, json={"reason": "too noisy"}, headers=admin).status_code == 200
    assert client.get(f"{BASE}/pending", headers=admin).json()["retired"] == ["ZS-PY-001"]

    assert client.post(f"{BASE}/versions", json={"changelog": ""}, headers=admin).status_code == 422
    v1 = client.post(f"{BASE}/versions", json={"changelog": "retire ZS-PY-001"}, headers=admin)
    assert v1.status_code == 201 and v1.json()["version"] == 1
    assert asyncio.run(engine.retired_rule_ids()) == {"ZS-PY-001"}
    assert client.get(f"{BASE}/pending", headers=admin).json()["retired"] == []
    # nothing changed since: publishing again is refused
    assert client.post(f"{BASE}/versions", json={"changelog": "again"}, headers=admin).status_code == 409

    assert client.post(f"{BASE}/rules/ZS-PY-001/restore", headers=admin).status_code == 200
    v2 = client.post(f"{BASE}/versions", json={"changelog": "restore"}, headers=admin).json()
    assert v2["version"] == 2
    assert asyncio.run(engine.retired_rule_ids()) == set()
    assert [v["version"] for v in client.get(f"{BASE}/versions", headers=admin).json()] == [2, 1]


def test_roll_back_republishes_old_contents_as_a_new_version(client, admin):
    client.post(f"{BASE}/rules/ZS-PY-001/retire", json={"reason": "r"}, headers=admin)
    client.post(f"{BASE}/versions", json={"changelog": "v1"}, headers=admin)
    client.post(f"{BASE}/rules/ZS-PY-001/restore", headers=admin)
    client.post(f"{BASE}/versions", json={"changelog": "v2"}, headers=admin)

    rb = client.post(f"{BASE}/versions/1/rollback", json={}, headers=admin)
    assert rb.status_code == 201
    assert rb.json()["version"] == 3 and rb.json()["rolled_back_from"] == 1
    assert asyncio.run(engine.retired_rule_ids()) == {"ZS-PY-001"}
    assert client.get(f"{BASE}/versions/2", headers=admin).json()["retired_rule_ids"] == []  # history intact
    assert client.post(f"{BASE}/versions/99/rollback", json={}, headers=admin).status_code == 404


def test_a_concurrent_publish_fails_cleanly_with_409(client, admin, monkeypatch):
    client.post(f"{BASE}/rules/ZS-PY-001/retire", json={"reason": "r"}, headers=admin)
    # Another admin already took version 1; ours still believes none exists.
    asyncio.run(RulePackVersion(version=1, changelog="theirs", published_by="x").insert())

    async def stale():
        return None

    monkeypatch.setattr(engine, "active_pack", stale)
    r = client.post(f"{BASE}/versions", json={"changelog": "mine"}, headers=admin)
    assert r.status_code == 409


def test_custom_rule_must_fire_on_vulnerable_and_not_on_safe(client, admin, monkeypatch):
    _fake_scanner(monkeypatch)
    ok = _custom(client, admin)
    assert ok.status_code == 200 and ok.json()["rule_id"] == "ZS-CUSTOM-001"

    _fake_scanner(monkeypatch, vulnerable_fires=False)
    r = _custom(client, admin)
    assert r.status_code == 422 and "vulnerable sample" in r.json()["detail"]

    _fake_scanner(monkeypatch, safe_fires=True)
    r = _custom(client, admin)
    assert r.status_code == 422 and "safe sample" in r.json()["detail"]


def test_custom_rule_id_must_use_the_custom_prefix(client, admin, monkeypatch):
    _fake_scanner(monkeypatch)
    r = _custom(client, admin, _VALID_YAML.replace("ZS-CUSTOM-001", "ZS-PY-001"))
    assert r.status_code == 422 and "ZS-CUSTOM" in r.json()["detail"]
    assert _custom(client, admin, "not: [valid").status_code == 422


def test_published_custom_rule_reaches_cloud_scans_via_extra_rules(client, admin, monkeypatch, tmp_path):
    from tests.test_cloud_scan_service import _make_cloud_scan
    from tests.test_scan_policy_wiring import _capture_scanner_argv, _scanner_argv

    calls = _capture_scanner_argv(monkeypatch, tmp_path)

    async def scan_once() -> Scan:
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        return await Scan.get(scan.id)

    asyncio.run(scan_once())
    assert "--extra-rules" not in _scanner_argv(calls)  # no custom rules yet: flag omitted

    _fake_scanner(monkeypatch)
    assert _custom(client, admin).status_code == 200
    client.post(f"{BASE}/versions", json={"changelog": "add custom"}, headers=admin)
    calls.clear()
    stored = asyncio.run(scan_once())
    assert "--extra-rules" in _scanner_argv(calls)
    assert stored.custom_rules_ran is True and stored.rule_pack_version == 1


def test_admin_actions_write_audit_rows(client, admin):
    client.post(f"{BASE}/rules/ZS-PY-001/retire", json={"reason": "r"}, headers=admin)
    client.post(f"{BASE}/versions", json={"changelog": "c"}, headers=admin)
    actions = {a.action for a in asyncio.run(AuditLog.find_all().to_list())}
    assert {"Scan Engine Rule Retired", "Scan Engine Rule Pack Published"} <= actions
