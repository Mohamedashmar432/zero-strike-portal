import { describe, expect, test } from "vitest";
import { ApiError, isSessionExpiry, retryUnlessForbiddenOrMissing } from "./client";

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

describe("isSessionExpiry", () => {
  test("a 401 on an app route means the session is over", () => {
    expect(isSessionExpiry("/projects")).toBe(true);
    expect(isSessionExpiry("/admin/scan-engine/rules")).toBe(true);
  });

  test("a 401 from the auth routes (wrong password, dead refresh) stays where it is", () => {
    expect(isSessionExpiry("/auth/login")).toBe(false);
    expect(isSessionExpiry("/auth/refresh")).toBe(false);
  });
});
