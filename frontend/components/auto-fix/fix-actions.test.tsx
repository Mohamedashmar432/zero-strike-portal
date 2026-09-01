import { describe, expect, test } from "vitest";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import { fixCapabilities } from "./fix-actions";

function proposal(overrides: Partial<AiFixProposal> = {}): AiFixProposal {
  return {
    id: "p1",
    finding_id: "f1",
    scan_id: "s1",
    project_id: "pr1",
    status: "proposed",
    review_state: "proposed",
    can_fix: true,
    confidence_score: 90,
    original_code: "a",
    patched_code: "b",
    explanation: null,
    patch_scope: "single-file",
    file_path: "app.py",
    risk_notes: null,
    manual_review_reason: null,
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
    ...overrides,
  } as AiFixProposal;
}

describe("fixCapabilities", () => {
  // A batch apply that dies marks every in-flight proposal "failed" with a reason. Without this
  // the card only says "failed" and a partial batch outcome is unreadable.
  test("a failed proposal reports why it failed", () => {
    const caps = fixCapabilities(
      proposal({ review_state: "failed", failure_reason: "git clone failed" }),
      true
    );
    expect(caps.failedReason).toBe("git clone failed");
  });

  test("a reason left over from an earlier failure is not shown once the state moves on", () => {
    const caps = fixCapabilities(
      proposal({ review_state: "pr_open", failure_reason: "git clone failed" }),
      true
    );
    expect(caps.failedReason).toBeNull();
  });
});
