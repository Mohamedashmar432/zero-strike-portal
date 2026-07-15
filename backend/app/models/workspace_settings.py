from typing import Literal

from beanie import Document

ReportTemplate = Literal["standard", "executive"]


class WorkspaceSettings(Document):
    """Singleton — at most one document ever exists (see report_template_service,
    which creates it lazily on first read). Workspace-wide preferences that apply to
    every project unless a project sets its own override (see Project.report_template).
    """

    default_report_template: ReportTemplate = "standard"

    class Settings:
        name = "workspace_settings"
