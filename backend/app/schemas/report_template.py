from pydantic import BaseModel

from app.models.workspace_settings import ReportTemplate


class ReportTemplateSettingsResponse(BaseModel):
    default_report_template: ReportTemplate


class ReportTemplateSettingsUpdateRequest(BaseModel):
    default_report_template: ReportTemplate
