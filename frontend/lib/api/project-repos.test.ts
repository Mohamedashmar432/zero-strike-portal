import { describe, expect, test } from "vitest";
import { formatSyncCounts, refetchWhileAnyRepoSyncing, shortSha, type ProjectRepo } from "./project-repos";

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
