import { describe, expect, test } from "vitest";
import { formatBytes, formatCountdown, formatDuration } from "./operations";

describe("formatCountdown", () => {
  test("minutes and zero-padded seconds, rounding up so it never shows 0:00 early", () => {
    expect(formatCountdown(245_000)).toBe("4:05");
    expect(formatCountdown(400)).toBe("0:01");
  });

  test("hours when the wait is long", () => {
    expect(formatCountdown(3_723_000)).toBe("1:02:03");
  });

  test("a passed estimate is null, so the caller can say 'any moment' instead of a negative time", () => {
    expect(formatCountdown(0)).toBeNull();
    expect(formatCountdown(-5000)).toBeNull();
  });
});

describe("formatDuration / formatBytes", () => {
  test("durations", () => {
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(180)).toBe("3m");
    expect(formatDuration(7500)).toBe("2h 5m");
  });

  test("bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536 * 1024 * 1024)).toBe("1.5 GB");
    expect(formatBytes(null)).toBe("—");
  });
});
