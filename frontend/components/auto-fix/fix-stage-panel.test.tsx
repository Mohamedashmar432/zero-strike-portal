import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import { FixStagePanel } from "./fix-stage-panel";

function proposal(overrides: Partial<AiFixProposal> = {}): AiFixProposal {
  return {
    id: "p1",
    finding_id: "f1",
    scan_id: "s1",
    project_id: "pr1",
    finding_rule_name: "SQL Injection",
    finding_severity: "high",
    finding_file: "app.py",
    finding_start_line: 10,
    status: "proposed",
    review_state: "proposed",
    can_fix: true,
    confidence_score: 90,
    original_code: "a",
    patched_code: "b",
    unified_diff: null,
    explanation: null,
    patch_scope: "single-file",
    file_path: "app.py",
    risk_notes: null,
    dependency_update: null,
    manual_review_reason: null,
    branch_name: null,
    pr_url: null,
    pr_number: null,
    triage: null,
    critique: null,
    validation: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    ...overrides,
  };
}

const text = (el: HTMLElement) => el.textContent ?? "";

describe("FixStagePanel", () => {
  test("an uncritiqued patch is reported as not reviewed, never as passing", () => {
    // The important negative: "skipped" must not be dressed up as a clean review, or a reviewer
    // trusts an unreviewed patch.
    const { container } = render(<FixStagePanel proposal={proposal({ critique: { skipped: "disabled" } })} />);
    expect(text(container)).toContain("not performed");
    expect(text(container)).not.toContain("looks correct");
  });

  test("an unavailable reviewer tells the reader the patch is unreviewed", () => {
    const { container } = render(
      <FixStagePanel proposal={proposal({ critique: { skipped: "unavailable" } })} />
    );
    expect(text(container)).toContain("unreviewed");
  });

  test("no_patch does NOT warn about an unreviewed patch", () => {
    // Regression from an E2E run: the backend collapsed "critic failed" and "nothing to review" into
    // one reason, so findings with no patch told the reviewer to carefully read a patch that
    // didn't exist.
    const { container } = render(
      <FixStagePanel proposal={proposal({ can_fix: false, critique: { skipped: "no_patch" } })} />
    );
    const t = text(container);
    expect(t).toContain("no patch to review");
    expect(t).not.toContain("read it carefully");
  });

  test("a reject verdict is rendered with its reasoning and issues", () => {
    const { container } = render(
      <FixStagePanel
        proposal={proposal({
          critique: {
            verdict: "reject",
            reasoning: "Escapes output instead of parameterizing.",
            issues: ["still concatenates uid"],
          },
        })}
      />
    );
    const t = text(container);
    expect(t).toContain("rejected this patch");
    expect(t).toContain("Escapes output instead of parameterizing.");
    expect(t).toContain("still concatenates uid");
  });

  test("a pass verdict surfaces reviewer confidence and any redraft", () => {
    const { container } = render(
      <FixStagePanel
        proposal={proposal({
          critique: { verdict: "pass", adjusted_confidence: 84, redrafted: true },
        })}
      />
    );
    const t = text(container);
    expect(t).toContain("looks correct");
    expect(t).toContain("84%");
    expect(t).toContain("redrafted once");
  });

  test("a triaged-out finding explains why and that no tokens were spent", () => {
    const { container } = render(
      <FixStagePanel
        proposal={proposal({
          can_fix: false,
          triage: { eligible: false, reason: "Rotate the credential first.", strategy: "rotate-secret" },
        })}
      />
    );
    const t = text(container);
    expect(t).toContain("not automatically fixable");
    expect(t).toContain("rotate the credential");
    expect(t).toContain("Rotate the credential first.");
    expect(t).toContain("no tokens were spent");
  });

  test("validation that cleared the finding reads as a scanner result, not an AI opinion", () => {
    const { container } = render(
      <FixStagePanel
        proposal={proposal({
          validation: { target_cleared: true, new_finding_count: 0, scope_ok: true, baseline_count: 12, post_count: 11 },
        })}
      />
    );
    const t = text(container);
    expect(t).toContain("resolved on re-scan");
    expect(t).toContain("not an AI judgement");
    expect(t).toContain("12 → 11");
  });

  test("a fixable proposal with no validation yet says when the check will run", () => {
    const { container } = render(<FixStagePanel proposal={proposal({ triage: { eligible: true } })} />);
    expect(text(container)).toContain("runs when you create the pull request");
  });

  test("a proposal with no recorded stages says so instead of rendering an empty list", () => {
    const { container } = render(<FixStagePanel proposal={proposal()} />);
    expect(text(container)).toContain("No pipeline details");
  });
});
