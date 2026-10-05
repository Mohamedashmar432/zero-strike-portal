import { describe, expect, it } from "vitest";
import { cloneWorkspaceWarning, formatMegabytes, type CloneWorkspaceStatus } from "./scanner-status";

const base: CloneWorkspaceStatus = { workdir_count: 1, total_mb: 100, free_mb: 5000, min_free_mb: 1024, max_repo_mb: 2048 };

describe("formatMegabytes", () => {
  it("switches to GB at 1024 MB", () => {
    expect(formatMegabytes(512)).toBe("512 MB");
    expect(formatMegabytes(1536)).toBe("1.5 GB");
  });
});

describe("cloneWorkspaceWarning", () => {
  it("is quiet when disk is fine and directories match running work", () => {
    expect(cloneWorkspaceWarning(base, 1)).toBeNull();
    expect(cloneWorkspaceWarning({ ...base, workdir_count: 0 }, 0)).toBeNull();
  });

  it("flags free disk below the floor first", () => {
    expect(cloneWorkspaceWarning({ ...base, free_mb: 100, workdir_count: 9 }, 0)).toMatch(/below the 1.0 GB floor/);
  });

  it("flags leftover directories", () => {
    expect(cloneWorkspaceWarning({ ...base, workdir_count: 3 }, 1)).toMatch(/leftovers/);
  });

  it("ignores the floor when it is disabled", () => {
    expect(cloneWorkspaceWarning({ ...base, free_mb: 0, min_free_mb: 0, workdir_count: 0 }, 0)).toBeNull();
  });
});
