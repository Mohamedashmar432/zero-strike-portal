"""Idempotent local-dev seed script.

Creates a fixed set of test users plus a demo project with owner/collaborator
membership, against whatever real MongoDB `MONGODB_URI` (in `.env`) points at —
Atlas or a local `mongod`. Never used by the test suite (that runs against an
in-memory `mongomock_motor` client and never touches a real database).

Passwords are documented in docs/TEST_USERS.md — keep both in sync if changed.

Usage (from backend/): ./.venv/Scripts/python scripts/seed_dev_users.py
"""

import asyncio
from datetime import datetime, timezone

from app.core.security import hash_password
from app.db.mongo import connect_to_mongo
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User

USERS = [
    {"email": "admin@zerostrike.dev", "name": "Admin", "password": "AdminDev!2026", "role": "admin"},
    {"email": "owner@zerostrike.dev", "name": "Owner", "password": "OwnerDev!2026", "role": "user"},
    {
        "email": "collaborator@zerostrike.dev",
        "name": "Collaborator",
        "password": "CollabDev!2026",
        "role": "user",
    },
]
DEMO_PROJECT_NAME = "Demo Project"


async def _upsert_user(spec: dict) -> User:
    """Re-running this must always leave the account matching docs/TEST_USERS.md exactly —
    otherwise a password changed via the app (or any other drift) silently breaks the
    documented login and nobody notices until someone tries it."""
    user = await User.find_one(User.email == spec["email"])
    if user:
        user.password_hash = hash_password(spec["password"])
        user.name = spec["name"]
        user.role = spec["role"]
        user.is_active = True
        await user.save()
        return user
    now = datetime.now(timezone.utc)
    user = User(
        email=spec["email"],
        password_hash=hash_password(spec["password"]),
        name=spec["name"],
        role=spec["role"],
        created_at=now,
        updated_at=now,
    )
    await user.insert()
    return user


async def _upsert_membership(project_id: str, user: User, role: str, invited_by: str) -> None:
    existing = await ProjectMember.find_one(
        ProjectMember.project_id == project_id, ProjectMember.invited_email == user.email
    )
    if existing:
        return
    now = datetime.now(timezone.utc)
    await ProjectMember(
        project_id=project_id,
        user_id=str(user.id),
        invited_email=user.email,
        role=role,
        invited_by=invited_by,
        invited_at=now,
        accepted_at=now,
    ).insert()


async def seed() -> None:
    await connect_to_mongo()

    admin, owner, collaborator = [await _upsert_user(spec) for spec in USERS]

    project = await Project.find_one(Project.name == DEMO_PROJECT_NAME, Project.owner_id == str(owner.id))
    if not project:
        now = datetime.now(timezone.utc)
        project = Project(
            name=DEMO_PROJECT_NAME,
            description="Seeded for local dev testing.",
            owner_id=str(owner.id),
            created_at=now,
            updated_at=now,
        )
        await project.insert()

    await _upsert_membership(str(project.id), owner, "owner", invited_by=str(owner.id))
    await _upsert_membership(str(project.id), collaborator, "collaborator", invited_by=str(owner.id))

    print("Seeded users (passwords in docs/TEST_USERS.md):")
    for u in (admin, owner, collaborator):
        print(f"  - {u.email} (role={u.role})")
    print(f"Seeded demo project: {project.name!r} ({project.id}), owner={owner.email}")


if __name__ == "__main__":
    asyncio.run(seed())
