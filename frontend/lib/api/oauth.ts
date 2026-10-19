import { apiFetch } from "./client";

export type ConsentRequest = {
  request_id: string;
  client_name: string;
  redirect_host: string;
  scopes: string[];
  account_email: string;
  expires_at: string;
};

export type ConnectedApp = {
  id: string;
  client_name: string;
  redirect_host: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
};

export function getConsentRequest(requestId: string) {
  return apiFetch<ConsentRequest>(`/oauth/requests/${encodeURIComponent(requestId)}`);
}

export function decideConsent(requestId: string, decision: "approve" | "deny") {
  return apiFetch<{ redirect_to: string }>(`/oauth/requests/${encodeURIComponent(requestId)}/${decision}`, {
    method: "POST",
  });
}

export function listConnectedApps() {
  return apiFetch<ConnectedApp[]>("/oauth/connected-apps");
}

export function revokeConnectedApp(id: string) {
  return apiFetch<void>(`/oauth/connected-apps/${id}`, { method: "DELETE" });
}

/** What a user pastes into an AI client; the backend's origin, never the frontend's. */
export function userMcpUrl(origin: string): string {
  return `${origin}/mcp/user`;
}
