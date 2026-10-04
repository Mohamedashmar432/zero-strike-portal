import { describe, expect, test } from "vitest";
import { auditDetail } from "./audit-logs";

describe("auditDetail", () => {
  test("a role change names the account and both roles", () => {
    expect(
      auditDetail({ metadata: { email: "a@example.com", from_role: "user", to_role: "admin" } })
    ).toBe("a@example.com: Normal User → Portal Admin");
  });

  test("falls back to the email alone, and to null when there is nothing to say", () => {
    expect(auditDetail({ metadata: { email: "a@example.com" } })).toBe("a@example.com");
    expect(auditDetail({ metadata: {} })).toBeNull();
    expect(auditDetail({ metadata: { email: 5 } })).toBeNull();
  });
});
