import { describe, expect, test } from "vitest";
import { wizardStep } from "./page";

describe("wizardStep", () => {
  test("starts on the framework step until at least one framework is picked", () => {
    expect(wizardStep([], false)).toBe(1);
    // Confirming scope can't skip past step 1 — the step is derived from state, so an
    // out-of-order flag can't put the wizard somewhere its inputs don't support.
    expect(wizardStep([], true)).toBe(1);
  });

  test("moves to scope once frameworks are chosen", () => {
    expect(wizardStep(["soc2"], false)).toBe(2);
    expect(wizardStep(["soc2", "gdpr"], false)).toBe(2);
  });

  test("reaches review only after scope is confirmed", () => {
    expect(wizardStep(["soc2"], true)).toBe(3);
  });

  test("clearing the frameworks sends the wizard back to step 1", () => {
    expect(wizardStep(["soc2"], true)).toBe(3);
    expect(wizardStep([], true)).toBe(1);
  });
});
