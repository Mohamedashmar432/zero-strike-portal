"""Which PDF report template applies: a project's own override, falling back to the
workspace-wide default.

The singleton itself is owned by workspace_settings_service — this module is the
report-template-shaped view of it, kept as its own name because that is what the
report routers and PDF service already ask for.
"""

from app.models.project import Project
from app.models.workspace_settings import ReportTemplate, WorkspaceSettings
from app.services import workspace_settings_service


async def get_workspace_settings() -> WorkspaceSettings:
    return await workspace_settings_service.get_workspace_settings()


async def set_default_report_template(template: ReportTemplate) -> WorkspaceSettings:
    return await workspace_settings_service.update_workspace_settings(
        default_report_template=template
    )


async def get_effective_template(project: Project) -> ReportTemplate:
    return await workspace_settings_service.effective_report_template(project)
