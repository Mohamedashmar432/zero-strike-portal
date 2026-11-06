import { describe, expect, test } from "vitest";
import { chunkIds, fixedViaPrLabel, needsAdminReview, statusChangeBlockReason } from "./vulnerabilities";

test("fixedViaPrLabel names the PR only when there is one", () => {
  const pr = { pr_number: 12, pr_url: null, pr_provider: "github", merged_at: null, merge_commit: null };
  expect(fixedViaPrLabel(pr)).toBe("Fixed via auto-fix PR #12");
  expect(fixedViaPrLabel(null)).toBeNull();
});

describe("statusChangeBlockReason", () => {
  test("allows non-resolving transitions with no reason or comment", () => {
    expect(statusChangeBlockReason("open", null, "")).toBeNull();
    expect(statusChangeBlockReason("in_progress", null, "")).toBeNull();
  });

  test("blocks accepting risk with no comment", () => {
    // No resolution reason needed — accepted risk is still an unresolved vulnerability — but a
    // comment always is, since there's no scanner evidence behind the decision at all.
    expect(statusChangeBlockReason("accepted_risk", null, "")).toMatch(/comment/i);
    expect(statusChangeBlockReason("accepted_risk", null, "   ")).toMatch(/comment/i);
  });

  test("allows accepting risk once explained", () => {
    expect(
      statusChangeBlockReason("accepted_risk", null, "Compensating control in the gateway blocks this path.")
    ).toBeNull();
    // A thin comment is refused with the same rule the server applies.
    expect(statusChangeBlockReason("accepted_risk", null, "n/a")).toMatch(/placeholder/i);
    expect(statusChangeBlockReason("accepted_risk", null, "Compensating control exists")).toMatch(/40 characters/);
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

  test("blocks a false positive with no comment", () => {
    expect(statusChangeBlockReason("resolved", "false_positive", "")).toMatch(/comment/i);
    expect(statusChangeBlockReason("resolved", "false_positive", "  ")).toMatch(/comment/i);
    expect(statusChangeBlockReason("resolved", "false_positive", "Test fixture only")).toBeNull();
  });

  test("allows other resolution reasons without a comment", () => {
    expect(statusChangeBlockReason("resolved", "duplicate", "")).toBeNull();
    expect(statusChangeBlockReason("resolved", "wont_fix", "")).toBeNull();
    expect(statusChangeBlockReason("resolved", "not_reproducible", "")).toBeNull();
  });
});

describe("admin-reviewed exemptions", () => {
  test("refuses a false positive on a dependency finding, pointing at accepted risk", () => {
    expect(statusChangeBlockReason("resolved", "false_positive", "not reachable", "sca")).toMatch(
      /accepted risk/
    );
    expect(statusChangeBlockReason("resolved", "false_positive", "not reachable", "sast")).toBeNull();
  });

  test("marks exactly the changes that wait for a portal admin", () => {
    expect(needsAdminReview("resolved", "false_positive", "sast")).toBe(true);
    expect(needsAdminReview("accepted_risk", null, "sca")).toBe(true);
    // Accepted risk now goes through review for every kind.
    expect(needsAdminReview("accepted_risk", null, "sast")).toBe(true);
    expect(needsAdminReview("accepted_risk", null, null)).toBe(true);
    // Every other transition applies immediately.
    expect(needsAdminReview("resolved", "fixed", "sast")).toBe(false);
    expect(needsAdminReview("resolved", "false_positive", "sca")).toBe(false);
  });
});

test("chunkIds splits a selection into API-sized batches", () => {
  const ids = Array.from({ length: 250 }, (_, i) => String(i));
  expect(chunkIds(ids).map((c) => c.length)).toEqual([100, 100, 50]);
  expect(chunkIds([])).toEqual([]);
});
