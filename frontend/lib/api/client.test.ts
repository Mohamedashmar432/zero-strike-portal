import { describe, expect, test } from "vitest";
import { ApiError, retryUnlessForbiddenOrMissing } from "./client";

describe("retryUnlessForbiddenOrMissing", () => {
  test.each([403, 404])("never retries a %s", (status) => {
    expect(retryUnlessForbiddenOrMissing(0, new ApiError(status, { detail: "x" }))).toBe(false);
  });

  test("retries other failures once", () => {
    expect(retryUnlessForbiddenOrMissing(0, new ApiError(500, {}))).toBe(true);
    expect(retryUnlessForbiddenOrMissing(1, new ApiError(500, {}))).toBe(false);
    expect(retryUnlessForbiddenOrMissing(0, new Error("network"))).toBe(true);
  });
});
