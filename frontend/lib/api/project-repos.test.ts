import { describe, expect, test } from "vitest";
import { refetchWhileAnyRepoSyncing, shortSha, type ProjectRepo } from "./project-repos";

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
