import { describe, expect, test } from "vitest";
import type {
  ComplianceAudit,
  ControlResult,
  ControlStatus,
  FrameworkSummary,
} from "@/lib/api/compliance";
import { coveragePercentOf, groupControlsByFramework, scanCoverageGaps } from "./page";

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
    coverage_percent: 0,
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

function auditFixture(overrides: Partial<ComplianceAudit> = {}): ComplianceAudit {
  return {
    id: "a1",
    project_id: "p1",
    frameworks: ["soc2"],
    scope: "latest",
    depth: "deterministic",
    status: "completed",
    error_message: null,
    started_at: "2026-08-01T00:00:00Z",
    completed_at: "2026-08-01T00:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    progress_completed: 1,
    progress_total: 1,
    findings_total: 3,
    summaries: [summary("soc2")],
    scan_ids: ["s1"],
    repos_in_scope: 3,
    repos_with_scans: 3,
    newest_scan_at: "2026-08-01T00:00:00Z",
    findings_truncated: false,
    ai_note: null,
    reused: false,
    controls: [],
    ...overrides,
  };
}

describe("scanCoverageGaps", () => {
  test("full coverage with fresh scans raises nothing", () => {
    expect(scanCoverageGaps(auditFixture())).toEqual({
      missingRepos: 0,
      staleDays: 0,
      hasGap: false,
    });
  });

  test("repos in scope with no completed scan are a gap — controls would read Pass off nothing", () => {
    const gaps = scanCoverageGaps(auditFixture({ repos_in_scope: 9, repos_with_scans: 2 }));
    expect(gaps.missingRepos).toBe(7);
    expect(gaps.hasGap).toBe(true);
  });

  test("evidence age is measured against when the audit ran, not against now", () => {
    const gaps = scanCoverageGaps(
      auditFixture({
        newest_scan_at: "2026-05-01T00:00:00Z",
        completed_at: "2026-08-01T00:00:00Z",
      })
    );
    expect(gaps.staleDays).toBe(92);
    expect(gaps.hasGap).toBe(true);
  });

  test("a scan count that exceeds the repo count never reports negative missing repos", () => {
    // scope="history" resolves many scans per repo, so repos_with_scans can equal repos_in_scope
    // while scan_ids is longer -- the counts must not go out of range either way.
    expect(scanCoverageGaps(auditFixture({ repos_in_scope: 1, repos_with_scans: 3 })).missingRepos)
      .toBe(0);
  });
});

describe("coveragePercentOf", () => {
  test("is derived from the control counts, not from the stored field", () => {
    // An audit that ran before coverage_percent existed serialises it as 0, not null -- so a
    // `??` fallback would not fire and the card would claim 0% assessable. Deriving is correct
    // for historical and new audits alike.
    const legacy: FrameworkSummary = {
      ...summary("soc2"),
      controls_total: 18,
      assessed_total: 10,
      coverage_percent: 0,
    };
    expect(coveragePercentOf(legacy)).toBe(56);
  });

  test("a framework with no controls is 0%, not a divide-by-zero", () => {
    expect(coveragePercentOf(summary("soc2"))).toBe(0);
  });
});
