import { describe, expect, test } from "vitest";
import type { ComplianceAuditSummary, Framework, FrameworkSummary } from "@/lib/api/compliance";
import { frameworkLabels, latestSummaryFor } from "./project-compliance-frameworks-section";

const CATALOG: Framework[] = [
  {
    key: "soc2",
    title: "SOC 2 (Trust Services Criteria)",
    scope_note: "",
    controls_total: 18,
    assessed_total: 10,
    controls: [],
  },
];

function fwSummary(framework: string, passed: number): FrameworkSummary {
  return {
    framework,
    framework_title: framework.toUpperCase(),
    scope_note: "",
    controls_total: 10,
    assessed_total: 5,
    passed,
    failed: 0,
    partial: 0,
    not_applicable: 0,
    needs_manual_review: 5,
    compliance_score: Math.round((passed / 5) * 100),
    coverage_percent: 50,
  };
}

function audit(
  id: string,
  status: ComplianceAuditSummary["status"],
  summaries: FrameworkSummary[]
): ComplianceAuditSummary {
  return {
    id,
    project_id: "p1",
    frameworks: summaries.map((s) => s.framework),
    scope: "latest",
    depth: "deterministic",
    status,
    error_message: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-08-07T00:00:00Z",
    progress_completed: 0,
    progress_total: 0,
    findings_total: 0,
    summaries,
  };
}

describe("latestSummaryFor", () => {
  // The list arrives newest-first from the API, so "first match wins" == "most recent".
  test("returns the newest completed audit's summary for that framework", () => {
    const found = latestSummaryFor(
      [
        audit("newest", "completed", [fwSummary("soc2", 9)]),
        audit("older", "completed", [fwSummary("soc2", 2)]),
      ],
      "soc2"
    );
    expect(found?.audit.id).toBe("newest");
    expect(found?.summary.passed).toBe(9);
  });

  test("skips in-flight and failed audits so a card never shows unfinished numbers", () => {
    const found = latestSummaryFor(
      [
        audit("running", "in_progress", [fwSummary("soc2", 0)]),
        audit("queued", "queued", [fwSummary("soc2", 0)]),
        audit("broken", "failed", [fwSummary("soc2", 0)]),
        audit("good", "completed", [fwSummary("soc2", 7)]),
      ],
      "soc2"
    );
    expect(found?.audit.id).toBe("good");
    expect(found?.summary.passed).toBe(7);
  });

  test("returns null when the framework has never been audited", () => {
    expect(latestSummaryFor([audit("a", "completed", [fwSummary("soc2", 3)])], "hipaa")).toBeNull();
  });

  test("returns null for an empty history rather than throwing", () => {
    expect(latestSummaryFor([], "soc2")).toBeNull();
  });

  test("picks the right framework out of a multi-framework audit", () => {
    const found = latestSummaryFor(
      [audit("multi", "completed", [fwSummary("soc2", 4), fwSummary("gdpr", 6)])],
      "gdpr"
    );
    expect(found?.summary.passed).toBe(6);
  });
});

describe("frameworkLabels", () => {
  test("uses the summaries' titles for a completed audit", () => {
    const a = audit("a", "completed", [fwSummary("soc2", 1), fwSummary("gdpr", 1)]);
    expect(frameworkLabels(a, CATALOG)).toBe("SOC2, GDPR");
  });

  test("falls back to the catalog for an audit with no summaries", () => {
    // A failed or still-queued audit has no summaries — the user must not see "soc2".
    const a = { ...audit("a", "failed", []), frameworks: ["soc2"] };
    expect(frameworkLabels(a, CATALOG)).toBe("SOC 2 (Trust Services Criteria)");
  });

  test("falls back to the raw key only when the catalog cannot resolve it", () => {
    const a = { ...audit("a", "failed", []), frameworks: ["retired-framework"] };
    expect(frameworkLabels(a, CATALOG)).toBe("retired-framework");
    expect(frameworkLabels(a, undefined)).toBe("retired-framework");
  });
});
