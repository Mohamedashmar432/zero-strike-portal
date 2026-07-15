import asyncio
from datetime import datetime, timezone

from app.models.project import Project
from app.services import report_template_service


def test_get_workspace_settings_creates_default_singleton_on_first_read(client):
    async def run():
        settings = await report_template_service.get_workspace_settings()
        assert settings.default_report_template == "standard"
        again = await report_template_service.get_workspace_settings()
        assert str(again.id) == str(settings.id)

    asyncio.run(run())


def test_set_default_report_template_persists(client):
    async def run():
        await report_template_service.set_default_report_template("executive")
        settings = await report_template_service.get_workspace_settings()
        assert settings.default_report_template == "executive"

    asyncio.run(run())


def test_effective_template_prefers_project_override(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(
            name="p", owner_id="u1", created_at=now, updated_at=now, report_template="executive"
        )
        await project.insert()
        await report_template_service.set_default_report_template("standard")

        assert await report_template_service.get_effective_template(project) == "executive"

    asyncio.run(run())


def test_effective_template_falls_back_to_workspace_default(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(name="p2", owner_id="u1", created_at=now, updated_at=now)
        await project.insert()
        await report_template_service.set_default_report_template("executive")

        assert await report_template_service.get_effective_template(project) == "executive"

    asyncio.run(run())
