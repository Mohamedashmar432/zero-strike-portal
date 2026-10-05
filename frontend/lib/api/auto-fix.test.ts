import { expect, test } from "vitest";
import { alreadyFixedLabel } from "./auto-fix";

test("alreadyFixedLabel shows sha7, and degrades without a commit", () => {
  expect(alreadyFixedLabel("1234567890abcdef")).toBe("Already fixed in 1234567");
  expect(alreadyFixedLabel(null)).toBe("Already fixed");
  expect(alreadyFixedLabel(undefined)).toBe("Already fixed");
});
