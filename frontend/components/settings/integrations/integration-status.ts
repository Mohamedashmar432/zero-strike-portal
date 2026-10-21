import type { CredentialStatus } from "@/lib/api/repo-credentials";
import type { McpToken } from "@/lib/api/mcp-tokens";

export type StatusTone = "ok" | "warn" | "bad" | "muted" | "pending";
export type IntegrationStatus = { tone: StatusTone; label: string; hint?: string };

const DAY_MS = 86_400_000;
// A token that ends within this many days is flagged so it can be reissued before an agent loses access.
export const EXPIRY_WARNING_DAYS = 7;

/** What a saved credential's status query says. The check is a live provider call, so it has four states. */
export function credentialStatus(query: {
  isLoading: boolean;
  isError: boolean;
  data?: CredentialStatus;
}): IntegrationStatus {
  if (query.isLoading) return { tone: "pending", label: "Checking" };
  if (query.isError || !query.data) {
    return { tone: "muted", label: "Unknown", hint: "Could not reach the portal to check this credential." };
  }
  if (query.data.status === "connected") return { tone: "ok", label: "Connected" };
  return { tone: "bad", label: "Needs reconnect", hint: query.data.detail ?? "The provider rejected this token." };
}

export function mcpTokenStatus(token: McpToken, now = Date.now()): IntegrationStatus {
  if (token.revoked_at) return { tone: "muted", label: "Revoked" };
  if (!token.is_active) return { tone: "muted", label: "Expired" };
  const days = Math.ceil((new Date(token.expires_at).getTime() - now) / DAY_MS);
  if (days <= EXPIRY_WARNING_DAYS) {
    return { tone: "warn", label: days <= 1 ? "Expires today" : `Expires in ${days}d` };
  }
  return { tone: "ok", label: "Active" };
}
