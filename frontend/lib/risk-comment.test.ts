import { expect, test } from "vitest";
import { checkRiskComment, riskCommentWords } from "./risk-comment";

test("words need two or more letters", () => {
  expect(riskCommentWords("a b cc 12 d_e fgh")).toEqual(["cc", "fgh"]);
});

test("rejects empty, short, and placeholder comments", () => {
  expect(checkRiskComment("").ok).toBe(false);
  expect(checkRiskComment("   ").message).toMatch(/required/);
  expect(checkRiskComment("n/a").ok).toBe(false);
  expect(checkRiskComment("Accepted").ok).toBe(false);
  expect(checkRiskComment("short but several words here ok").ok).toBe(false);
});

test("rejects one repeated word even when long enough", () => {
  expect(checkRiskComment("risk risk risk risk risk risk risk risk risk risk").ok).toBe(false);
});

test("needs at least six words", () => {
  const c = checkRiskComment("Compensatingcontrolsareinplaceatthegatewaylayerx yes");
  expect(c.ok).toBe(false);
  expect(c.words).toBeLessThan(6);
});

test("accepts a real justification and reports counts", () => {
  const c = checkRiskComment("  Gateway WAF blocks this path and the endpoint is internal only.  ");
  expect(c.ok).toBe(true);
  expect(c.message).toBeNull();
  expect(c.chars).toBeGreaterThanOrEqual(40);
  expect(c.words).toBeGreaterThanOrEqual(6);
});
