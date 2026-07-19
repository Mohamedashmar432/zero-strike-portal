import { describe, expect, test } from "vitest";
import { refetchWhileAnyItemActive, refetchWhileStatusActive } from "./polling";

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
