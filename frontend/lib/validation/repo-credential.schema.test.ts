import { describe, expect, test } from "vitest";
import { normalizeAdoOrganization } from "./repo-credential.schema";

describe("normalizeAdoOrganization", () => {
  test("keeps a bare org name", () => {
    expect(normalizeAdoOrganization("  my-org ")).toBe("my-org");
  });

  test("strips a pasted dev.azure.com URL down to the org", () => {
    expect(normalizeAdoOrganization("https://dev.azure.com/my-org")).toBe("my-org");
    expect(normalizeAdoOrganization("https://dev.azure.com/my-org/Some%20Project/_git/repo")).toBe("my-org");
    expect(normalizeAdoOrganization("dev.azure.com/my-org/")).toBe("my-org");
  });

  test("handles the legacy visualstudio.com host", () => {
    expect(normalizeAdoOrganization("https://my-org.visualstudio.com/Project")).toBe("my-org");
  });
});
