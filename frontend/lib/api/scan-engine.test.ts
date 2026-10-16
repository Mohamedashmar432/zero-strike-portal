import { describe, expect, test } from "vitest";
import { fpRateLabel, hasPendingChanges } from "./scan-engine";

describe("scan engine helpers", () => {
  test("fpRateLabel rounds a 0..1 rate to a whole percent", () => {
    expect(fpRateLabel(0)).toBe("0%");
    expect(fpRateLabel(0.4166)).toBe("42%");
    expect(fpRateLabel(1)).toBe("100%");
  });

  test("hasPendingChanges is true only when some list has entries", () => {
    const empty = { retired: [], restored: [], custom_added: [], custom_edited: [], custom_removed: [] };
    expect(hasPendingChanges(undefined)).toBe(false);
    expect(hasPendingChanges(empty)).toBe(false);
    expect(hasPendingChanges({ ...empty, custom_edited: ["ZS-CUSTOM-001"] })).toBe(true);
  });
});
