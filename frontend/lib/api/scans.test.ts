import { describe, expect, it } from "vitest";
import { formatAlreadyScanned } from "./scans";

describe("formatAlreadyScanned", () => {
  it("names the branch and the 7-char commit", () => {
    expect(formatAlreadyScanned({ branch: "main", git_commit: "abcdef1234567890" })).toBe(
      "Already scanned at main@abcdef1"
    );
  });

  it("falls back to the remote head when the scan carries no commit", () => {
    expect(formatAlreadyScanned({ branch: "main", git_commit: null }, "1234567890abcdef")).toBe(
      "Already scanned at main@1234567"
    );
  });

  it("degrades to a bare statement when nothing is known", () => {
    expect(formatAlreadyScanned({ branch: null, git_commit: null })).toBe("Already scanned");
  });
});
