import { describe, expect, test } from "vitest";
import { formatMergedPrReminder, formatSyncCounts, formatSyncFinishedMessage, headCommitForSelectedBranch, refetchWhileAnyRepoSyncing, shortSha, type ProjectRepo } from "./project-repos";

test("formatMergedPrReminder pluralizes and stays quiet at zero", () => {
  expect(formatMergedPrReminder(1)).toBe("1 auto-fix PR merged since last sync");
  expect(formatMergedPrReminder(3)).toBe("3 auto-fix PRs merged since last sync");
  expect(formatMergedPrReminder(0)).toBeNull();
});

const repo = (sync_state: ProjectRepo["sync_state"]) => ({ sync_state }) as ProjectRepo;

describe("refetchWhileAnyRepoSyncing", () => {
  const check = refetchWhileAnyRepoSyncing(4000);

  test("polls while any repo is syncing", () => {
    expect(check({ state: { data: [repo("up_to_date"), repo("syncing")] } })).toBe(4000);
  });

  test.each(["up_to_date", "behind", "error", "never", "unknown"] as const)("stops for %s", (s) => {
    expect(check({ state: { data: [repo(s)] } })).toBe(false);
  });

  test("stops with no data", () => {
    expect(check({ state: {} })).toBe(false);
  });
});

test("shortSha truncates and tolerates null", () => {
  expect(shortSha("0123456789abcdef")).toBe("0123456");
  expect(shortSha(null)).toBe("");
});

test("formatSyncCounts lists fixed, new and reopened", () => {
  expect(formatSyncCounts(3, 2, 1)).toBe("3 fixed, 2 new, 1 reopened");
  expect(formatSyncCounts(0, 0, 0)).toBe("0 fixed, 0 new, 0 reopened");
});

test("headCommitForSelectedBranch hides a commit scanned on another branch", () => {
  const base = { scanned_commit: "0123456789", scanned_branch: "main", selected_branch: "main" };
  expect(headCommitForSelectedBranch(base)).toBe("0123456789");
  expect(headCommitForSelectedBranch({ ...base, selected_branch: "dev" })).toBeNull();
  expect(headCommitForSelectedBranch({ ...base, scanned_commit: null })).toBeNull();
});

describe("formatSyncFinishedMessage", () => {
  const reg = {
    has_baseline: true,
    baseline_branch_mismatch: false,
    commit: "0123456789",
    branch: "dev",
    new: { count: 4 },
    fixed: { count: 1 },
    reopened: { count: 0 },
  };

  test("diffs against a baseline", () => {
    expect(formatSyncFinishedMessage("r", reg)).toBe("Sync of r finished: 1 fixed, 4 new, 0 reopened");
  });

  test("establishes a baseline on a branch mismatch or when there is none", () => {
    const want = "Sync of r finished: Baseline established at 0123456 on dev — 4 findings tracked";
    expect(formatSyncFinishedMessage("r", { ...reg, baseline_branch_mismatch: true })).toBe(want);
    expect(formatSyncFinishedMessage("r", { ...reg, has_baseline: false })).toBe(want);
  });
});
