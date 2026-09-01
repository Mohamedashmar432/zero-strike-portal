import { describe, expect, test } from "vitest";
import { BRANCH_RENDER_LIMIT, matchBranches } from "./repo-connect-wizard";

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
