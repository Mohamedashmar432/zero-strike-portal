import { apiFetch } from "./client";

// See docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md, "API contract for Part 2".
export type WebhookEvent = {
  key: string;
  label: string;
  description: string;
  audience: string;
  group: string;
};

export type WebhookChannel = {
  id: string;
  name: string;
  url_host: string;
  enabled: boolean;
  events: string[];
  project_ids: string[];
  include_digest: boolean;
  last_delivery_at: string | null;
  last_status: "ok" | "error" | null;
  last_error: string | null;
  created_at: string;
};

export type WebhookChannelInput = {
  name: string;
  /** Write-only. Omit on update to keep the stored URL. */
  url?: string;
  enabled: boolean;
  events: string[];
  project_ids: string[];
  include_digest: boolean;
};

export type WebhookTestResult = { ok: boolean; status: number | null; error: string | null };

export const listWebhookEvents = () => apiFetch<WebhookEvent[]>("/admin/webhook-channels/events");
export const listWebhookChannels = () => apiFetch<WebhookChannel[]>("/admin/webhook-channels");

export const createWebhookChannel = (body: WebhookChannelInput) =>
  apiFetch<WebhookChannel>("/admin/webhook-channels", { method: "POST", body: JSON.stringify(body) });

export const updateWebhookChannel = (id: string, body: Partial<WebhookChannelInput>) =>
  apiFetch<WebhookChannel>(`/admin/webhook-channels/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteWebhookChannel = (id: string) =>
  apiFetch<void>(`/admin/webhook-channels/${id}`, { method: "DELETE" });

export const testWebhookChannel = (id: string) =>
  apiFetch<WebhookTestResult>(`/admin/webhook-channels/${id}/test`, { method: "POST" });
