import { describe, expect, it } from "vitest";
import type { McpToken } from "@/lib/api/mcp-tokens";
import { credentialStatus, mcpTokenStatus } from "./integration-status";

const NOW = Date.parse("2026-10-21T00:00:00Z");
const inDays = (d: number) => new Date(NOW + d * 86_400_000).toISOString();

function token(over: Partial<McpToken>): McpToken {
  return {
    id: "t1",
    label: "laptop",
    prefix: "tsmcp_abc123",
    created_at: inDays(-1),
    expires_at: inDays(30),
    revoked_at: null,
    last_used_at: null,
    last_used_ip: null,
    is_active: true,
    ...over,
  };
}

describe("mcpTokenStatus", () => {
  it("is Active well before expiry", () => {
    expect(mcpTokenStatus(token({}), NOW)).toMatchObject({ tone: "ok", label: "Active" });
  });

  it("warns inside the last week and says today on the last day", () => {
    expect(mcpTokenStatus(token({ expires_at: inDays(5) }), NOW)).toMatchObject({ tone: "warn", label: "Expires in 5d" });
    expect(mcpTokenStatus(token({ expires_at: inDays(0.4) }), NOW)).toMatchObject({ tone: "warn", label: "Expires today" });
  });

  it("revoked wins over expired, and both are muted rather than alarming", () => {
    const revoked = token({ revoked_at: inDays(-1), is_active: false, expires_at: inDays(-2) });
    expect(mcpTokenStatus(revoked, NOW)).toMatchObject({ tone: "muted", label: "Revoked" });
    expect(mcpTokenStatus(token({ is_active: false, expires_at: inDays(-2) }), NOW)).toMatchObject({
      tone: "muted",
      label: "Expired",
    });
  });
});

describe("credentialStatus", () => {
  it("shows Checking while the provider call is in flight", () => {
    expect(credentialStatus({ isLoading: true, isError: false })).toMatchObject({ tone: "pending", label: "Checking" });
  });

  it("is Connected or Needs reconnect, carrying the provider's reason", () => {
    const checked_at = "2026-10-21T00:00:00Z";
    expect(
      credentialStatus({ isLoading: false, isError: false, data: { status: "connected", detail: null, checked_at } })
    ).toMatchObject({ tone: "ok", label: "Connected" });
    expect(
      credentialStatus({
        isLoading: false,
        isError: false,
        data: { status: "invalid", detail: "Bad credentials", checked_at },
      })
    ).toEqual({ tone: "bad", label: "Needs reconnect", hint: "Bad credentials" });
  });

  it("is Unknown, not Needs reconnect, when the check itself could not run", () => {
    expect(credentialStatus({ isLoading: false, isError: true })).toMatchObject({ tone: "muted", label: "Unknown" });
  });
});
