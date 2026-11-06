import { describe, expect, test } from "vitest";
import { filterRules, fpRateLabel, hasPendingChanges, type RuleRow } from "./scan-engine";

describe("scan engine helpers", () => {
  test("fpRateLabel rounds a 0..1 rate to a whole percent", () => {
    expect(fpRateLabel(0)).toBe("0%");
    expect(fpRateLabel(0.4166)).toBe("42%");
    expect(fpRateLabel(1)).toBe("100%");
  });

  test("hasPendingChanges is true only when some list has entries", () => {
    const empty = { retired: [], restored: [], custom_added: [], custom_edited: [], custom_removed: [] };
    expect(hasPendingChanges(undefined)).toBe(false);
    expect(hasPendingChanges(empty)).toBe(false);
    expect(hasPendingChanges({ ...empty, custom_edited: ["ZS-CUSTOM-001"] })).toBe(true);
  });

  test("filterRules matches id, title, language, category and CWE case-insensitively", () => {
    const row = (o: Partial<RuleRow>): RuleRow => ({
      rule_id: "ZS-X", title: null, severity: null, language: null, category: null, cwe: [],
      total_findings: 0, fp_tags: 0, fp_rate: 0, projects_affected: 0, state: "active",
      noisy: false, pending: false, retire_reason: null, ...o,
    });
    const rules = [
      row({ rule_id: "ZS-PY-001", title: "Dangerous eval()", language: "python", category: "dangerous-functions", cwe: ["CWE-95"] }),
      row({ rule_id: "ZS-GO-002", title: "Weak hash", language: "go", category: "crypto", cwe: ["CWE-328"] }),
    ];
    expect(filterRules(rules, "  ")).toHaveLength(2);
    expect(filterRules(rules, "zs-py").map((r) => r.rule_id)).toEqual(["ZS-PY-001"]);
    expect(filterRules(rules, "WEAK")[0].rule_id).toBe("ZS-GO-002");
    expect(filterRules(rules, "python")).toHaveLength(1);
    expect(filterRules(rules, "crypto")).toHaveLength(1);
    expect(filterRules(rules, "cwe-95")).toHaveLength(1);
    expect(filterRules(rules, "nope")).toHaveLength(0);
  });
});
