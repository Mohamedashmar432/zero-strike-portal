import { describe, expect, it } from "vitest";
import { repoIdentity, repoName, safeRepoHref } from "./repo-identity";

describe("repoIdentity", () => {
  it("reads an Azure DevOps URL, decoding the repo name and keeping org / project as the owner", () => {
    expect(
      repoIdentity("https://dev.azure.com/thinkbridge-dev/thinkbridge-DevOps/_git/Visitor%20management")
    ).toEqual({ name: "Visitor management", owner: "thinkbridge-dev / thinkbridge-DevOps" });
  });

  it("reads GitHub / GitLab style URLs with or without .git and a trailing slash", () => {
    expect(repoIdentity("https://github.com/octocat/hello-world.git")).toEqual({ name: "hello-world", owner: "octocat" });
    expect(repoIdentity("https://github.com/octocat/hello-world/")).toEqual({ name: "hello-world", owner: "octocat" });
    expect(repoIdentity("https://gitlab.com/group/sub/proj")).toEqual({ name: "proj", owner: "group / sub" });
  });

  it("ignores credentials, query and fragment in the URL", () => {
    expect(repoIdentity("https://user:tok@github.com/o/r.git?x=1#frag")).toEqual({ name: "r", owner: "o" });
  });

  it("reads scp-style remotes and local paths", () => {
    expect(repoIdentity("git@github.com:org/repo.git")).toEqual({ name: "repo", owner: "org" });
    expect(repoIdentity("/home/dev/my_app")).toEqual({ name: "my_app", owner: "home / dev" });
    expect(repoIdentity("C:\\work\\my-app")).toEqual({ name: "my-app", owner: "C: / work" });
  });

  it("survives a malformed escape instead of throwing", () => {
    expect(repoIdentity("https://example.com/org/100%_done")?.name).toBe("100%_done");
  });

  it("returns null for nothing to name", () => {
    expect(repoIdentity("")).toBeNull();
    expect(repoIdentity(null)).toBeNull();
    expect(repoIdentity("https://github.com/")).toBeNull();
  });
});

describe("repoName / safeRepoHref", () => {
  it("falls back to the raw text, then a dash", () => {
    expect(repoName("https://github.com/")).toBe("https://github.com/");
    expect(repoName(undefined)).toBe("—");
  });

  it("only links http(s) URLs", () => {
    expect(safeRepoHref("https://github.com/o/r")).toBe("https://github.com/o/r");
    expect(safeRepoHref("javascript:alert(1)")).toBeNull();
    expect(safeRepoHref("/home/dev/app")).toBeNull();
  });
});
