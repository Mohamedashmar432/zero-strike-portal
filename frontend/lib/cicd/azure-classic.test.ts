import { describe, expect, test } from "vitest";
import { azureClassicInlineScript, azureClassicScriptUrl } from "./azure-classic";

const gen = (origin: string) => azureClassicInlineScript({ origin, failOn: "high" });

describe("azureClassicInlineScript", () => {
  test("fits Azure DevOps' 5000-character inline limit", () => {
    expect(gen("https://a-very-long-portal-hostname.example.com").length).toBeLessThan(5000);
  });

  test("never doubles /api/v1 and bakes in the origin and gate as overridable defaults", () => {
    for (const origin of ["https://p.example", "https://p.example/", "https://p.example/api/v1/"]) {
      const s = gen(origin);
      expect(s).not.toContain("/api/v1/api/v1");
      expect(s).toContain('ZEROSTRIKE_PORTAL_URL="${ZEROSTRIKE_PORTAL_URL:-https://p.example}"');
      expect(s).toContain('ZEROSTRIKE_FAIL_ON="${ZEROSTRIKE_FAIL_ON:-high}"');
    }
    expect(azureClassicScriptUrl("https://p.example/")).toBe("https://p.example/api/v1/downloads/ci/azure-classic.sh");
  });

  test("fails the task when the download fails, and never carries the token", () => {
    const s = gen("https://p.example");
    expect(s.startsWith("set -e")).toBe(true);
    expect(s).toContain("curl -fsSL");
    expect(s).not.toContain("ZEROSTRIKE_TOKEN");
    expect(s).not.toContain("| bash");
  });
});
