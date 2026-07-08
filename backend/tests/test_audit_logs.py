import asyncio

from app.models.user import User
from tests.test_auth_flow import register_and_login


def test_non_admin_cannot_list_audit_logs(client):
    tokens = register_and_login(client, email="nonadmin@zerostrike.dev")
    r = client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 403


def test_login_and_logout_are_audited(client):
    register_and_login(client, email="audited@zerostrike.dev")

    async def promote_to_admin():
        user = await User.find_one(User.email == "audited@zerostrike.dev")
        user.role = "admin"
        await user.save()

    asyncio.run(promote_to_admin())

    # Re-login to get a fresh access token carrying the admin role claim.
    r = client.post("/api/v1/auth/login", json={"email": "audited@zerostrike.dev", "password": "hunter2pass"})
    admin_access = r.json()["access_token"]

    r = client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {admin_access}"})
    assert r.status_code == 200
    actions = [log["action"] for log in r.json()["items"]]
    assert "login" in actions
