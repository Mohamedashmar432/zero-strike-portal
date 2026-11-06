import { createHash } from "node:crypto";
import { expect, test } from "vitest";
import { EMPTY_STYLE_HASH, SONNER_STYLE_HASH } from "./csp-hashes";

const sha256 = (s: string) => `sha256-${createHash("sha256").update(s).digest("base64")}`;

test("the allow-listed sonner stylesheet hash matches the installed sonner", async () => {
  await import("sonner"); // injects its <style> into document.head on import
  const css = [...document.head.querySelectorAll("style")].map((s) => s.textContent ?? "").join("");
  expect(css).toContain("data-sonner-toaster");
  expect(sha256(css)).toBe(SONNER_STYLE_HASH);
});

test("the empty-style hash is the hash of the empty string", () => {
  expect(sha256("")).toBe(EMPTY_STYLE_HASH);
});
