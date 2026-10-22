import { describe, expect, test } from "vitest";
import { azureClassicBashScript } from "./azure-classic";

const gen = (origin: string, version: string | null = "v1.2.3") =>
  azureClassicBashScript({ origin, version, failOn: "high" });

describe("azureClassicBashScript", () => {
  test("downloads the pinned version exactly once and never doubles /api/v1", () => {
    for (const origin of ["https://p.example", "https://p.example/", "https://p.example/api/v1/"]) {
      const s = gen(origin);
      expect(s.split("/api/v1/downloads/zerostrike/v1.2.3/linux-amd64")).toHaveLength(2);
      expect(s).not.toContain("/api/v1/api/v1");
      expect(s).toContain("https://p.example/api/v1/downloads");
    }
  });

  test("has the required hardening and payload pieces", () => {
    const s = gen("https://p.example");
    for (const t of [
      "set -euo pipefail",
      "curl --fail --location",
      "chmod +x",
      "sha256sum -c",
      "BUILD_SOURCESDIRECTORY",
      "azure_pipelines",
      "_build/results?buildId=",
      "--config -",
      "ZEROSTRIKE_FAIL_ON",
    ]) {
      expect(s).toContain(t);
    }
  });

  test("never leaks the token or traces", () => {
    const s = gen("https://p.example");
    expect(s).not.toContain("--token");
    expect(s).not.toContain('echo "$ZEROSTRIKE_TOKEN"');
    expect(s).not.toContain("set -x");
    expect(s).not.toContain("--server");
  });

  test("an unpublished version renders the placeholder", () => {
    expect(gen("https://p.example", null)).toContain("<ZEROSTRIKE_VERSION>");
  });
});
