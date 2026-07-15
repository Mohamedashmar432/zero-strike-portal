import { apiFetch } from "./client";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export type ReportTemplateId = "standard" | "executive";

export function getWorkspaceReportTemplate() {
  return apiFetch<{ default_report_template: ReportTemplateId }>("/report-templates/settings");
}

export function updateWorkspaceReportTemplate(template: ReportTemplateId) {
  return apiFetch<{ default_report_template: ReportTemplateId }>("/report-templates/settings", {
    method: "PUT",
    body: JSON.stringify({ default_report_template: template }),
  });
}

// No auth required (sample data only) — used directly as an <iframe src>.
export function reportTemplatePreviewUrl(template: ReportTemplateId) {
  return `${API_BASE_URL}/report-templates/${template}/preview`;
}
