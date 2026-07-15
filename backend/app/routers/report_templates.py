from fastapi import APIRouter, Depends, Response

from app.core.deps import require_admin
from app.models.user import User
from app.models.workspace_settings import ReportTemplate
from app.reporting import sample_data
from app.schemas.report_template import ReportTemplateSettingsResponse, ReportTemplateSettingsUpdateRequest
from app.services import pdf_report_service, report_template_service

router = APIRouter(prefix="/report-templates", tags=["report-templates"])


@router.get("/settings", response_model=ReportTemplateSettingsResponse)
async def get_report_template_settings():
    settings = await report_template_service.get_workspace_settings()
    return ReportTemplateSettingsResponse(default_report_template=settings.default_report_template)


@router.put("/settings", response_model=ReportTemplateSettingsResponse)
async def update_report_template_settings(
    payload: ReportTemplateSettingsUpdateRequest, user: User = Depends(require_admin)
):
    settings = await report_template_service.set_default_report_template(payload.default_report_template)
    return ReportTemplateSettingsResponse(default_report_template=settings.default_report_template)


@router.get("/{template}/preview")
async def preview_report_template(template: ReportTemplate):
    scan, report, findings = sample_data.build_sample_report()
    html = pdf_report_service.render_scan_report_html(
        scan, report, findings, template, project_name="Sample Project (sample data)"
    )
    return Response(content=html, media_type="text/html")
