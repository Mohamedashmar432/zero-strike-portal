import { describe, expect, test } from "vitest";
import { summarizeSkipped } from "./batch-approve-bar";

// Skips are a race — a PR opened while the reviewer was reading, another write already in flight —
// so a real batch comes back with a MIX of reasons. Reporting skipped[0] told the reviewer about
// one of them and silently dropped the rest.
describe("summarizeSkipped", () => {
  test("nothing skipped means no description at all, not an empty line", () => {
    expect(summarizeSkipped([])).toBeNull();
  });

  test("names every distinct reason with its count", () => {
    const summary = summarizeSkipped([
      { reason: "A PR is already open for this fix." },
      { reason: "A write is already in flight for this fix." },
      { reason: "A PR is already open for this fix." },
    ]);

    expect(summary).toBe(
      "3 left out — 2 × A PR is already open for this fix. 1 × A write is already in flight for this fix."
    );
  });

  test("the total counts proposals, not distinct reasons", () => {
    const summary = summarizeSkipped(Array.from({ length: 5 }, () => ({ reason: "Same reason." })));

    expect(summary).toBe("5 left out — 5 × Same reason.");
  });
});
