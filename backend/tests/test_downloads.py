import asyncio
import hashlib

from app.models.user import User
from tests.test_auth_flow import register_and_login


def _admin_headers(client, email="dlAdmin@zerostrike.dev"):
    tokens = register_and_login(client, email=email)

    async def promote():
        user = await User.find_one(User.email == email)
        user.role = "admin"
        await user.save()

    asyncio.run(promote())
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2pass"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _publish(client, headers, version, os_, arch, content):
    return client.post(
        "/api/v1/admin/downloads/zerostrike",
        data={"version": version, "os": os_, "arch": arch},
        files={"file": (f"zerostrike-{os_}-{arch}", content, "application/octet-stream")},
        headers=headers,
    )


def test_admin_can_publish_and_public_can_download(client):
    headers = _admin_headers(client)
    content = b"fake-binary-bytes-linux-amd64"

    r = _publish(client, headers, "v0.23.0", "linux", "amd64", content)
    assert r.status_code == 200
    assert r.json()["sha256"] == hashlib.sha256(content).hexdigest()

    dl = client.get("/api/v1/downloads/zerostrike/v0.23.0/linux-amd64")
    assert dl.status_code == 200
    assert dl.content == content
    assert dl.headers["x-checksum-sha256"] == hashlib.sha256(content).hexdigest()
    assert 'filename="zerostrike_linux_amd64"' in dl.headers["content-disposition"]


def test_latest_resolves_to_most_recent_upload(client):
    headers = _admin_headers(client, email="dlAdmin2@zerostrike.dev")
    _publish(client, headers, "v0.22.0", "linux", "amd64", b"old-bytes")
    _publish(client, headers, "v0.23.0", "linux", "amd64", b"new-bytes")

    dl = client.get("/api/v1/downloads/zerostrike/latest/linux-amd64")
    assert dl.status_code == 200
    assert dl.content == b"new-bytes"


def test_reupload_same_version_os_arch_replaces(client):
    headers = _admin_headers(client, email="dlAdmin3@zerostrike.dev")
    _publish(client, headers, "v0.24.0", "windows", "amd64", b"first-build")
    _publish(client, headers, "v0.24.0", "windows", "amd64", b"second-build")

    dl = client.get("/api/v1/downloads/zerostrike/v0.24.0/windows-amd64")
    assert dl.content == b"second-build"


def test_checksums_txt_lists_all_arches_for_version(client):
    headers = _admin_headers(client, email="dlAdmin4@zerostrike.dev")
    _publish(client, headers, "v0.25.0", "linux", "amd64", b"linux-bytes")
    _publish(client, headers, "v0.25.0", "darwin", "arm64", b"darwin-bytes")

    r = client.get("/api/v1/downloads/zerostrike/v0.25.0/checksums.txt")
    assert r.status_code == 200
    assert hashlib.sha256(b"linux-bytes").hexdigest() in r.text
    assert "zerostrike_linux_amd64" in r.text
    assert "zerostrike_darwin_arm64" in r.text


def test_download_unknown_version_is_404(client):
    r = client.get("/api/v1/downloads/zerostrike/v9.9.9/linux-amd64")
    assert r.status_code == 404


def test_download_invalid_os_arch_is_400(client):
    r = client.get("/api/v1/downloads/zerostrike/latest/plan9-amd64")
    assert r.status_code == 400


def test_publish_requires_admin(client):
    tokens = register_and_login(client, email="notadmin@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = _publish(client, headers, "v0.23.0", "linux", "amd64", b"x")
    assert r.status_code == 403
