from typing import Literal

from beanie import Document

ReportTemplate = Literal["standard", "executive"]


class WorkspaceSettings(Document):
    """Singleton — at most one document ever exists (see report_template_service,
    which creates it lazily on first read). Workspace-wide preferences that apply to
    every project unless a project sets its own override (see Project.report_template).
    """

    default_report_template: ReportTemplate = "standard"

    # "Project BYOK": when True, each project brings its own AI provider + key and is fully
    # isolated -- a project's key serves only that project and never falls back to the
    # portal-wide provider, and a project without one has AI disabled entirely. When False
    # (the default) every project shares the admin's portal-wide provider, as it always has.
    # Read through ai_provider_config_service.byok_enabled(); enforced in
    # ai_provider_config_service.resolve_failover_configs().
    project_byok_enabled: bool = False

    class Settings:
        name = "workspace_settings"
