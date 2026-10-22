import { apiFetch } from "./client";

export type AlertTrigger = "critical" | "high" | "vulnerable_package" | "scan_failed";

export interface ProjectAlerts {
  webhook_enabled: boolean;
  webhook_configured: boolean;
  /** Host only: the URL path is the secret and is never sent back. */
  webhook_host: string | null;
  email_enabled: boolean;
  emails: string[];
  triggers: AlertTrigger[];
}

export interface ProjectAlertsInput {
  /** Omit to keep the stored URL; "" removes it. */
  webhook_url?: string;
  webhook_enabled?: boolean;
  email_enabled?: boolean;
  emails?: string[];
  triggers?: AlertTrigger[];
}

export interface GlobalAlerts {
  webhook_enabled: boolean;
  webhook_configured: boolean;
  webhook_host: string | null;
}

export const getProjectAlerts = (id: string) => apiFetch<ProjectAlerts>(`/projects/${id}/alerts`);
export const updateProjectAlerts = (id: string, body: ProjectAlertsInput) =>
  apiFetch<ProjectAlerts>(`/projects/${id}/alerts`, { method: "PUT", body: JSON.stringify(body) });
export const testProjectAlerts = (id: string) =>
  apiFetch<{ message: string }>(`/projects/${id}/alerts/test`, { method: "POST" });

export const getGlobalAlerts = () => apiFetch<GlobalAlerts>("/workspace-settings/alerts");
export const updateGlobalAlerts = (body: { webhook_url?: string; webhook_enabled?: boolean }) =>
  apiFetch<GlobalAlerts>("/workspace-settings/alerts", { method: "PUT", body: JSON.stringify(body) });
export const testGlobalAlerts = () =>
  apiFetch<{ message: string }>("/workspace-settings/alerts/test", { method: "POST" });
