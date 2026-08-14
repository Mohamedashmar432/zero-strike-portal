import { describe, expect, test } from "vitest";
import type { ControlResult, ControlStatus, FrameworkSummary } from "@/lib/api/compliance";
import { groupControlsByFramework } from "./page";

function summary(framework: string): FrameworkSummary {
  return {
    framework,
    framework_title: framework.toUpperCase(),
    scope_note: "",
    controls_total: 0,
    assessed_total: 0,
    passed: 0,
    failed: 0,
    partial: 0,
    not_applicable: 0,
    needs_manual_review: 0,
    compliance_score: 0,
  };
}

function control(framework: string, control_id: string, status: ControlStatus): ControlResult {
  return {
    framework,
    control_id,
    control_title: control_id,
    control_reference: control_id,
    status,
    domain: "General Controls",
    description: "",
    recommendation: "",
    rationale: "",
    ai_explanation: null,
    ai_remediation: null,
    evidence: [],
    evidence_total: 0,
    severity_counts: {},
  };
}

describe("groupControlsByFramework", () => {
  test("puts each control under its own framework and never leaks across sections", () => {
    const groups = groupControlsByFramework(
      [summary("soc2"), summary("gdpr")],
      [
        control("gdpr", "Art.32", "fail"),
        control("soc2", "CC6.1", "pass"),
        control("gdpr", "Art.30", "needs_manual_review"),
      ]
    );
    expect(groups.map((g) => g.summary.framework)).toEqual(["soc2", "gdpr"]);
    expect(groups[0].controls.map((c) => c.control_id)).toEqual(["CC6.1"]);
    expect(groups[1].controls.map((c) => c.control_id)).toEqual(["Art.32", "Art.30"]);
  });

  test("orders worst status first so failures are never buried below passes", () => {
    const groups = groupControlsByFramework(
      [summary("soc2")],
      [
        control("soc2", "pass-1", "pass"),
        control("soc2", "manual-1", "needs_manual_review"),
        control("soc2", "fail-1", "fail"),
        control("soc2", "na-1", "not_applicable"),
        control("soc2", "partial-1", "partial"),
      ]
    );
    expect(groups[0].controls.map((c) => c.control_id)).toEqual([
      "fail-1",
      "partial-1",
      "manual-1",
      "na-1",
      "pass-1",
    ]);
  });

  test("does not mutate the caller's control array", () => {
    const controls = [control("soc2", "pass-1", "pass"), control("soc2", "fail-1", "fail")];
    const before = controls.map((c) => c.control_id);
    groupControlsByFramework([summary("soc2")], controls);
    expect(controls.map((c) => c.control_id)).toEqual(before);
  });

  test("a framework with no controls yields an empty section rather than being dropped", () => {
    const groups = groupControlsByFramework([summary("soc2"), summary("hipaa")], [
      control("soc2", "CC6.1", "fail"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[1].controls).toEqual([]);
  });
});
