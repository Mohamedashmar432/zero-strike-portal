import { describe, expect, test } from "vitest";
import { statusChangeBlockReason } from "./vulnerabilities";

describe("statusChangeBlockReason", () => {
  test("allows non-resolving transitions with no reason or comment", () => {
    expect(statusChangeBlockReason("open", null, "")).toBeNull();
    expect(statusChangeBlockReason("in_progress", null, "")).toBeNull();
    // Accepted risk is still an unresolved vulnerability — it needs no resolution reason.
    expect(statusChangeBlockReason("accepted_risk", null, "")).toBeNull();
  });

  test("blocks resolving without a reason", () => {
    expect(statusChangeBlockReason("resolved", null, "")).toMatch(/reason/i);
  });

  test("blocks a manual 'fixed' with no comment", () => {
    // Scanner evidence is preferred over an unexplained human claim, so this one needs saying.
    expect(statusChangeBlockReason("resolved", "fixed", "")).toMatch(/comment/i);
    expect(statusChangeBlockReason("resolved", "fixed", "   ")).toMatch(/comment/i);
  });

  test("allows a manual 'fixed' once explained", () => {
    expect(statusChangeBlockReason("resolved", "fixed", "Verified by hand in staging")).toBeNull();
  });

  test("allows other resolution reasons without a comment", () => {
    expect(statusChangeBlockReason("resolved", "false_positive", "")).toBeNull();
    expect(statusChangeBlockReason("resolved", "duplicate", "")).toBeNull();
    expect(statusChangeBlockReason("resolved", "wont_fix", "")).toBeNull();
    expect(statusChangeBlockReason("resolved", "not_reproducible", "")).toBeNull();
  });
});
