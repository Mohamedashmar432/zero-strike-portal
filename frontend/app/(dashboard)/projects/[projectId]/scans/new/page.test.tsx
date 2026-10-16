import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { listApiKeys } from "@/lib/api/api-keys";
import { listProjectRepos, type ProjectRepo } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { createCloudScan, type CreatedScan } from "@/lib/api/scans";
import NewScanPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "p1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/lib/api/projects", () => ({ getProject: vi.fn() }));
vi.mock("@/lib/api/api-keys", () => ({ listApiKeys: vi.fn() }));
vi.mock("@/lib/api/project-repos", () => ({ listProjectRepos: vi.fn() }));
vi.mock("@/lib/api/scans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/scans")>()),
  createCloudScan: vi.fn(),
}));

const repo = {
  id: "r1",
  provider: "github",
  repo_full_name: "octocat/repo",
  label: null,
  selected_branch: "main",
} as unknown as ProjectRepo;

const upToDate = {
  id: "s1",
  status: "completed",
  branch: "main",
  git_commit: "abcdef1234567",
  outcome: "up_to_date",
  remote_head_sha: "abcdef1234567",
} as unknown as CreatedScan;

async function showAlreadyScannedNotice() {
  vi.mocked(getProject).mockResolvedValue({ id: "p1", name: "Demo" } as never);
  vi.mocked(listProjectRepos).mockResolvedValue([repo]);
  vi.mocked(createCloudScan).mockResolvedValue(upToDate);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NewScanPage />
    </QueryClientProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: /Cloud/ }));
  fireEvent.click(await screen.findByRole("button", { name: /octocat\/repo/ }));
  fireEvent.click(screen.getByRole("button", { name: "Start cloud scan" }));
  expect(await screen.findByText(/Already scanned at main@abcdef1/)).toBeTruthy();
}

describe("New scan: the Already-scanned notice belongs to the selection it answered", () => {
  afterEach(() => vi.clearAllMocks());

  test("switching to URL mode clears it", async () => {
    await showAlreadyScannedNotice();
    fireEvent.click(screen.getByRole("button", { name: /scan a repo by URL instead/ }));
    expect(screen.queryByText(/Already scanned/)).toBeNull();
  });

  test("re-selecting a connected repo clears it", async () => {
    await showAlreadyScannedNotice();
    fireEvent.click(screen.getByRole("button", { name: /octocat\/repo/ }));
    expect(screen.queryByText(/Already scanned/)).toBeNull();
  });
});

async function openCicdStep(activeKeys: boolean) {
  vi.mocked(getProject).mockResolvedValue({ id: "p1", name: "Demo" } as never);
  vi.mocked(listApiKeys).mockResolvedValue({
    items: activeKeys ? [{ id: "k1", is_active: true }] : [],
    total: 0,
    page: 1,
    page_size: 20,
  } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NewScanPage />
    </QueryClientProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: /CI\/CD/ }));
}

describe("New scan: CI/CD setup", () => {
  afterEach(() => vi.clearAllMocks());

  test("a project with no token gets a link to generate one, in a new tab so the wizard keeps its place", async () => {
    await openCicdStep(false);
    // The button component renders the anchor with role="button", so find it by its text.
    const link = (await screen.findByText(/Generate a project token/)).closest("a")!;
    expect(link.getAttribute("href")).toBe("/projects/p1?tab=keys");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  test("a project that already has a token says so and offers to manage tokens instead", async () => {
    await openCicdStep(true);
    expect(await screen.findByText(/Manage project tokens/)).toBeTruthy();
    expect(screen.queryByText(/Generate a project token/)).toBeNull();
  });

  test("the snippet carries the fail-on setting the engineer picked, and keeps every line short", async () => {
    await openCicdStep(true);
    fireEvent.click(screen.getByRole("button", { name: "Azure Pipelines" }));
    const code = () => screen.getByText(/# azure-pipelines\.yml/).textContent ?? "";
    expect(code()).toContain("ZEROSTRIKE_FAIL_ON: none"); // default: findings only warn
    fireEvent.click(screen.getByRole("button", { name: "Fail on critical or high" }));
    expect(code()).toContain("ZEROSTRIKE_FAIL_ON: high");
    // The scan command is split with line continuations, so nothing needs a horizontal scrollbar.
    expect(code()).toContain("./zerostrike scan . \\\n");
    expect(Math.max(...code().split("\n").map((l) => l.length))).toBeLessThan(120);
  });
});
