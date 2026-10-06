import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
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
