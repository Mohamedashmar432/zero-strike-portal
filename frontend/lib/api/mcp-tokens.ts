import { apiFetch } from "./client";

export type McpToken = {
  id: string;
  label: string;
  prefix: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  is_active: boolean;
};

export type McpTokenCreated = McpToken & { raw_token: string };

export const MCP_EXPIRY_CHOICES = [7, 30, 90] as const;

export function listMcpTokens() {
  return apiFetch<McpToken[]>("/admin/mcp-tokens");
}

export function createMcpToken(input: { label: string; expires_in_days: number }) {
  return apiFetch<McpTokenCreated>("/admin/mcp-tokens", { method: "POST", body: JSON.stringify(input) });
}

export function renameMcpToken(id: string, label: string) {
  return apiFetch<McpToken>(`/admin/mcp-tokens/${id}`, { method: "PATCH", body: JSON.stringify({ label }) });
}

export function revokeMcpToken(id: string) {
  return apiFetch<void>(`/admin/mcp-tokens/${id}`, { method: "DELETE" });
}

/** The backend's origin (never the frontend's): MCP clients call `<origin>/mcp` directly. */
export function mcpServerOrigin(): string {
  const env = process.env.NEXT_PUBLIC_SCANNER_SERVER_ORIGIN;
  if (env) return env.replace(/\/$/, "");
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (base && /^https?:\/\//.test(base)) return base.replace(/\/api\/v1\/?$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "https://your-portal";
}

// --scope user: without it Claude Code files the server under the current folder (local scope), keyed by
// that path's exact spelling, so a different folder or an editor that opens it as `c:\` vs `C:\` never sees it.
export function mcpAddCommand(origin: string, token: string): string {
  return `claude mcp add --scope user --transport http thinkshield ${origin}/mcp --header "Authorization: Bearer ${token}"`;
}
