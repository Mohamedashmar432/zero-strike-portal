import { describe, expect, test } from "vitest";
import {
  refetchWhileAnyItemActive,
  refetchWhileAutoFixActive,
  refetchWhileStatusActive,
} from "./polling";

function q<T>(data: T | undefined) {
  return { state: { data } };
}

describe("refetchWhileStatusActive", () => {
  const check = refetchWhileStatusActive<{ status?: string }>(3000);

  test.each(["pending", "running", "in_progress"])("polls while status is %s", (status) => {
    expect(check(q({ status }))).toBe(3000);
  });

  test.each(["completed", "failed", undefined])("stops polling once status is %s", (status) => {
    expect(check(q({ status }))).toBe(false);
  });

  test("stops polling when there's no data yet", () => {
    expect(check(q(undefined))).toBe(false);
  });
});

describe("refetchWhileAnyItemActive", () => {
  const check = refetchWhileAnyItemActive<{ status?: string }>(3000);

  test("polls if any item is still pending/running", () => {
    expect(check(q({ items: [{ status: "completed" }, { status: "running" }] }))).toBe(3000);
  });

  test("stops once every item is settled", () => {
    expect(check(q({ items: [{ status: "completed" }, { status: "failed" }] }))).toBe(false);
  });

  test("stops on an empty list", () => {
    expect(check(q({ items: [] }))).toBe(false);
  });
});

describe("refetchWhileAutoFixActive", () => {
  const check = refetchWhileAutoFixActive<{
    status?: string;
    insight?: { proposals?: { review_state?: string }[] } | null;
  }>(3000);

  test.each(["queued", "in_progress"])("polls while the propose job is %s", (status) => {
    expect(check(q({ status }))).toBe(3000);
  });

  // The reason this helper exists: the propose job finishes, then a *separate* apply job drives
  // approved -> applying -> pr_open. Stopping at "completed" would freeze the UI on "Applying…".
  test.each(["approved", "applying"])("keeps polling a completed job while a proposal is %s", (review_state) => {
    expect(check(q({ status: "completed", insight: { proposals: [{ review_state }] } }))).toBe(3000);
  });

  test("stops once the job is done and no proposal is mid-apply", () => {
    expect(
      check(q({ status: "completed", insight: { proposals: [{ review_state: "pr_open" }] } }))
    ).toBe(false);
  });

  test("stops when there are no proposals at all", () => {
    expect(check(q({ status: "completed", insight: null }))).toBe(false);
  });

  test("stops polling when there's no data yet", () => {
    expect(check(q(undefined))).toBe(false);
  });
});
