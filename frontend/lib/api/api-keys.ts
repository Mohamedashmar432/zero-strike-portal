import { apiFetch } from "./client";
import type { Page } from "./users";

export type ApiKey = {
  id: string;
  project_id: string;
  label: string;
  prefix: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  is_active: boolean;
};

export type ApiKeyCreated = ApiKey & { raw_token: string };

export function listApiKeys(projectId: string, page = 1, pageSize = 20) {
  return apiFetch<Page<ApiKey>>(`/apikeys?project_id=${projectId}&page=${page}&page_size=${pageSize}`);
}

export function createApiKey(projectId: string, input: { label: string; expires_in_days: number }) {
  return apiFetch<ApiKeyCreated>("/apikeys", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, ...input }),
  });
}

export function revokeApiKey(id: string) {
  return apiFetch<void>(`/apikeys/${id}`, { method: "DELETE" });
}
