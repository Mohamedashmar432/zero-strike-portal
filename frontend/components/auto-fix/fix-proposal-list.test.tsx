import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import { compareProposals, FixProposalList } from "./fix-proposal-list";

// The threshold arrives as a prop from AutoFixSummary.confidence_threshold (NOT from the admin-only
// /remediation-settings endpoint), so it can just be passed in.
const THRESHOLD = 80;

function p(overrides: Partial<AiFixProposal> = {}): AiFixProposal {
  return {
    id: `id-${overrides.finding_id ?? "1"}`,
    finding_id: overrides.finding_id ?? "f1",
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

const MIXED = [
  p({ finding_id: "low1", finding_severity: "low", finding_rule_name: "Weak Hash", finding_file: "hash.py" }),
  p({ finding_id: "crit1", finding_severity: "critical", finding_rule_name: "Command Injection", finding_file: "b.py" }),
  p({ finding_id: "high1", finding_severity: "high", finding_rule_name: "SQL Injection", finding_file: "a.py" }),
  p({ finding_id: "crit2", finding_severity: "critical", finding_rule_name: "Path Traversal", finding_file: "a.py" }),
];

function list(props: Partial<React.ComponentProps<typeof FixProposalList>> = {}) {
  return render(
    <FixProposalList
      proposals={MIXED}
      selectedId={null}
      onSelect={vi.fn()}
      commentCounts={new Map()}
      threshold={THRESHOLD}
      {...props}
    />
  );
}

const rowNames = () =>
  screen
    .getAllByRole("button")
    .map((b) => b.textContent ?? "")
    .filter((t) => t.includes("Injection") || t.includes("Traversal") || t.includes("Hash"));

describe("FixProposalList", () => {
  test("orders by severity descending, then by file path", () => {
    list();
    const names = rowNames();
    // critical/a.py, critical/b.py, high/a.py, low/hash.py
    expect(names[0]).toContain("Path Traversal");
    expect(names[1]).toContain("Command Injection");
    expect(names[2]).toContain("SQL Injection");
    expect(names[3]).toContain("Weak Hash");
  });

  test("search matches the rule name", () => {
    list();
    fireEvent.change(screen.getByLabelText("Search fix proposals"), { target: { value: "traversal" } });
    const names = rowNames();
    expect(names).toHaveLength(1);
    expect(names[0]).toContain("Path Traversal");
  });

  test("search matches the file path", () => {
    list();
    fireEvent.change(screen.getByLabelText("Search fix proposals"), { target: { value: "hash.py" } });
    expect(rowNames()).toHaveLength(1);
  });

  test("search that matches nothing shows an explicit empty state", () => {
    list();
    fireEvent.change(screen.getByLabelText("Search fix proposals"), { target: { value: "zzzz" } });
    // getByText throws when absent, so reaching the assertion is itself the check.
    expect(screen.getByText("No proposals match these filters.")).toBeTruthy();
  });

  test("severity chips filter the list", () => {
    list();
    fireEvent.click(screen.getByRole("button", { name: "critical" }));
    const names = rowNames();
    expect(names).toHaveLength(2);
    expect(names.join(" ")).not.toContain("Weak Hash");
  });

  test("bucket chips split on can_fix and the confidence threshold", () => {
    const proposals = [
      p({ finding_id: "confident", confidence_score: 95 }),
      p({ finding_id: "shaky", confidence_score: 40, finding_rule_name: "Weak Hash" }),
      p({ finding_id: "manual", can_fix: false, confidence_score: 0, finding_rule_name: "Path Traversal" }),
    ];
    render(
      <FixProposalList
        proposals={proposals}
        selectedId={null}
        onSelect={vi.fn()}
        commentCounts={new Map()}
        threshold={THRESHOLD}
      />
    );
    expect(screen.getByRole("button", { name: /AI can fix 1/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Needs review 1/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Manual 1/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Needs review 1/ }));
    expect(rowNames()).toHaveLength(1);
    expect(rowNames()[0]).toContain("Weak Hash");
  });

  test("j and k move the selection through the visible order", () => {
    const onSelect = vi.fn();
    list({ onSelect, selectedId: "crit2" }); // first row
    const listEl = screen.getByRole("list", { name: "Fix proposals" });

    fireEvent.keyDown(listEl, { key: "j" });
    expect(onSelect).toHaveBeenLastCalledWith("crit1"); // second row

    onSelect.mockClear();
    fireEvent.keyDown(listEl, { key: "k" });
    expect(onSelect).toHaveBeenLastCalledWith("crit2"); // back to first
  });

  test("arrow keys work the same as j/k", () => {
    const onSelect = vi.fn();
    list({ onSelect, selectedId: "crit2" });
    const listEl = screen.getByRole("list", { name: "Fix proposals" });
    fireEvent.keyDown(listEl, { key: "ArrowDown" });
    expect(onSelect).toHaveBeenLastCalledWith("crit1");
  });

  test("keyboard navigation does not run past the ends of the list", () => {
    const onSelect = vi.fn();
    list({ onSelect, selectedId: "crit2" }); // already first
    const listEl = screen.getByRole("list", { name: "Fix proposals" });
    fireEvent.keyDown(listEl, { key: "k" });
    expect(onSelect).toHaveBeenLastCalledWith("crit2"); // clamped, not undefined
  });

  test("clicking a row selects that finding", () => {
    const onSelect = vi.fn();
    list({ onSelect });
    fireEvent.click(screen.getByRole("button", { name: /Path Traversal/ }));
    expect(onSelect).toHaveBeenCalledWith("crit2");
  });

  test("comment counts are shown on the rows that have them", () => {
    list({ commentCounts: new Map([["high1", 3]]) });
    expect(screen.getByRole("button", { name: /SQL Injection/ }).textContent).toContain("3");
  });
});

describe("compareProposals (shared with the workspace's default selection)", () => {
  test("puts the highest-severity proposal first regardless of API order", () => {
    // Regression: the workspace used to default to proposals[0] from the API, which on real data was
    // the lowest-severity finding — so the page opened on a MEDIUM with criticals listed above it.
    const apiOrder = [
      p({ finding_id: "med", finding_severity: "medium" }),
      p({ finding_id: "crit", finding_severity: "critical" }),
      p({ finding_id: "high", finding_severity: "high" }),
    ];
    expect([...apiOrder].sort(compareProposals)[0].finding_id).toBe("crit");
  });

  test("breaks severity ties by file then line", () => {
    const same = [
      p({ finding_id: "b20", finding_severity: "high", finding_file: "b.py", finding_start_line: 20 }),
      p({ finding_id: "a30", finding_severity: "high", finding_file: "a.py", finding_start_line: 30 }),
      p({ finding_id: "a10", finding_severity: "high", finding_file: "a.py", finding_start_line: 10 }),
    ];
    expect([...same].sort(compareProposals).map((x) => x.finding_id)).toEqual(["a10", "a30", "b20"]);
  });
});
