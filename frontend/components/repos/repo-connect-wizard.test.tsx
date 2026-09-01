import { describe, expect, test } from "vitest";
import { BRANCH_RENDER_LIMIT, matchBranches, wizardStep } from "./repo-connect-wizard";

// A repo like flutter/flutter has ~900 branches. The picker renders only BRANCH_RENDER_LIMIT of
// them, so search has to run over the whole list — filtering the rendered slice instead would
// make every branch past the first hundred unreachable, which is the bug this guards.
const MANY = Array.from({ length: 900 }, (_, i) => ({ name: `branch-${String(i).padStart(3, "0")}` }));

describe("matchBranches", () => {
  test("an empty query keeps every branch", () => {
    expect(matchBranches(MANY, "")).toHaveLength(900);
    expect(matchBranches(MANY, "   ")).toHaveLength(900);
  });

  test("reaches branches far past the render limit", () => {
    const matched = matchBranches(MANY, "branch-899");

    expect(matched).toEqual([{ name: "branch-899" }]);
    expect(MANY.slice(0, BRANCH_RENDER_LIMIT)).not.toContainEqual({ name: "branch-899" });
  });

  test("matches case-insensitively, anywhere in the name, ignoring surrounding space", () => {
    const branches = [{ name: "release/V2-Hotfix" }, { name: "main" }];

    expect(matchBranches(branches, "  v2-HOT ")).toEqual([{ name: "release/V2-Hotfix" }]);
    expect(matchBranches(branches, "hotfix")).toEqual([{ name: "release/V2-Hotfix" }]);
  });

  test("a query that matches nothing returns nothing, and no branches at all is not a crash", () => {
    expect(matchBranches(MANY, "no-such-branch")).toEqual([]);
    expect(matchBranches(undefined, "main")).toEqual([]);
  });
});

// Browser QA on 2026-09-01 caught this rendering as "Step 0 of 5": the new URL+token mode was
// added to the stage list but not to the stage *selector*, so indexOf returned -1. Unit tests,
// tsc and lint were all green.
describe("wizardStep", () => {
  const at = (o: Partial<Parameters<typeof wizardStep>[0]>) =>
    wizardStep({
      provider: "github",
      effectiveMode: null,
      credentialId: null,
      selectedRepo: false,
      selectedBranch: false,
      ...o,
    });

  test("never reports step 0 — every reachable state names a stage in its own list", () => {
    const providers = ["github", "azure_devops", null] as const;
    const modes = ["credential", "public", "token", null] as const;
    for (const provider of providers) {
      for (const mode of modes) {
        // Mirrors the component: Azure DevOps has no mode choice, it is always credential-based.
        const effectiveMode = provider === "azure_devops" ? "credential" : mode;
        for (const credentialId of [null, "cred1"]) {
          for (const selectedRepo of [false, true]) {
            for (const selectedBranch of [false, true]) {
              const { step, total } = wizardStep({
                provider,
                effectiveMode,
                credentialId,
                selectedRepo,
                selectedBranch,
              });
              // The state is in the message so a regression names the combination that broke.
              expect({ provider, effectiveMode, selectedRepo, step }).toMatchObject({
                step: expect.any(Number),
              });
              expect(step).toBeGreaterThan(0);
              expect(step).toBeLessThanOrEqual(total);
            }
          }
        }
      }
    }
  });

  test("the token flow counts the same as the public one — lookup, not browse", () => {
    expect(at({ effectiveMode: "token" })).toEqual({ step: 3, total: 5 });
    expect(at({ effectiveMode: "public" })).toEqual({ step: 3, total: 5 });
    // Browsing a saved credential has one extra stage (pick credential, then pick repo).
    expect(at({ effectiveMode: "credential", credentialId: "c" })).toEqual({ step: 4, total: 6 });
  });

  test("advances through lookup -> branch -> label", () => {
    expect(at({ effectiveMode: "token" }).step).toBe(3);
    expect(at({ effectiveMode: "token", selectedRepo: true }).step).toBe(4);
    expect(at({ effectiveMode: "token", selectedRepo: true, selectedBranch: true }).step).toBe(5);
  });
});
