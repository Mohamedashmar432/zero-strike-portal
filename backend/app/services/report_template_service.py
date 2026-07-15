"""Resolves which PDF report template applies: a project's own override, falling back
to the single workspace-wide default. See WorkspaceSettings — at most one document
ever exists, created lazily on first read.
"""

from app.models.project import Project
from app.models.workspace_settings import ReportTemplate, WorkspaceSettings


async def get_workspace_settings() -> WorkspaceSettings:
    settings = await WorkspaceSettings.find_one()
    if settings is None:
        settings = WorkspaceSettings()
        await settings.insert()
    return settings


async def set_default_report_template(template: ReportTemplate) -> WorkspaceSettings:
    settings = await get_workspace_settings()
    settings.default_report_template = template
    await settings.save()
    return settings


async def get_effective_template(project: Project) -> ReportTemplate:
    if project.report_template is not None:
        return project.report_template
    settings = await get_workspace_settings()
    return settings.default_report_template
