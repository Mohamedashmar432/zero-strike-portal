import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { listApiKeys } from "@/lib/api/api-keys";
import { listProjectRepos, type ProjectRepo } from "@/lib/api/project-repos";
import { ApiError } from "@/lib/api/client";
import { getScannerBinaryInfo } from "@/lib/api/downloads";
import { getProject } from "@/lib/api/projects";
import { createCloudScan, type CreatedScan } from "@/lib/api/scans";
import NewScanPage from "./page";

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "p1" }),
  useRouter: () => ({ push: vi.fn(), replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/lib/api/projects", () => ({ getProject: vi.fn() }));
vi.mock("@/lib/api/downloads", () => ({ getScannerBinaryInfo: vi.fn() }));
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

describe("New scan: the wizard step lives in the URL", () => {
  afterEach(() => {
    vi.clearAllMocks();
    nav.search = "";
  });

  function renderPage() {
    vi.mocked(getProject).mockResolvedValue({ id: "p1", name: "Demo" } as never);
    vi.mocked(listApiKeys).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <NewScanPage />
      </QueryClientProvider>
    );
  }

  test("coming back to ?type=cicd (e.g. with Back from the tokens page) lands on that step", async () => {
    nav.search = "type=cicd";
    renderPage();
    expect(await screen.findByText(/Step 2 of 2 — CI\/CD scan/)).toBeTruthy();
  });

  test("an unknown ?type is ignored and the wizard starts at step 1", () => {
    nav.search = "type=bogus";
    renderPage();
    expect(screen.getByText(/Step 1 of 2/)).toBeTruthy();
  });

  test("choosing a type records it in the URL without adding a history entry, and going back clears it", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /CI\/CD/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/projects/p1/scans/new?type=cicd", { scroll: false });
    fireEvent.click(screen.getByRole("button", { name: /Change scan type/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/projects/p1/scans/new", { scroll: false });
  });
});

describe("New scan: CI/CD setup", () => {
  afterEach(() => vi.clearAllMocks());

  test("a project with no token gets a link to generate one, in the SAME tab so the session survives", async () => {
    await openCicdStep(false);
    // The button component renders the anchor with role="button", so find it by its text.
    const link = (await screen.findByText(/Generate a project token/)).closest("a")!;
    expect(link.getAttribute("href")).toBe("/projects/p1?tab=keys");
    // A new tab starts signed out (the session is in-memory + this tab's sessionStorage).
    expect(link.getAttribute("target")).toBeNull();
  });

  test("a project that already has a token says so and offers to manage tokens instead", async () => {
    await openCicdStep(true);
    expect(await screen.findByText(/Manage project tokens/)).toBeTruthy();
    expect(screen.queryByText(/Generate a project token/)).toBeNull();
  });

  test("the snippet carries the project's fail-on setting (default high), and keeps every line short", async () => {
    await openCicdStep(true);
    fireEvent.click(screen.getByRole("button", { name: "Azure Pipelines" }));
    const code = () => screen.getByText(/# azure-pipelines\.yml/).textContent ?? "";
    expect(code()).toContain("ZEROSTRIKE_FAIL_ON: high"); // default: critical or high fails the pipeline
    expect(screen.queryByText("When findings are found")).toBeNull(); // now a project setting
    // The scan command is split with line continuations, so nothing needs a horizontal scrollbar.
    expect(code()).toContain("./zerostrike scan . \\\n");
    expect(Math.max(...code().split("\n").map((l) => l.length))).toBeLessThan(120);
  });

  const binaryInfo = {
    version: "v1.2.3",
    os: "linux",
    arch: "amd64",
    filename: "zerostrike_linux_amd64",
    sha256: "x",
    size_bytes: 1,
    uploaded_at: "2026-10-01T00:00:00Z",
  };

  test("Azure DevOps Classic renders instructions and a script pinned to the published version, with no key details", async () => {
    vi.mocked(getScannerBinaryInfo).mockResolvedValue(binaryInfo);
    await openCicdStep(true);
    vi.mocked(listApiKeys).mockResolvedValue({
      items: [{ id: "k1", is_active: true, name: "SecretKeyName", key_prefix: "zs_abc123" }],
      total: 1,
      page: 1,
      page_size: 20,
    } as never);
    fireEvent.click(screen.getByRole("button", { name: "Azure DevOps Classic" }));
    expect(await screen.findByText(/Pinned to v1\.2\.3/)).toBeTruthy();
    expect(screen.getByText(/Bash task script/)).toBeTruthy();
    const body = document.body.textContent ?? "";
    expect(body).toContain("ZEROSTRIKE_TOKEN = $(ZEROSTRIKE_TOKEN)");
    expect(body).toContain("--config -");
    expect(body).not.toContain("SecretKeyName");
    expect(body).not.toContain("zs_abc123");
  });

  test("Azure DevOps Classic warns when no Linux scanner is published, and still renders the script", async () => {
    vi.mocked(getScannerBinaryInfo).mockRejectedValue(new ApiError(404, { detail: "Not found" }));
    await openCicdStep(true);
    fireEvent.click(screen.getByRole("button", { name: "Azure DevOps Classic" }));
    expect(await screen.findByText(/will fail with HTTP 404/)).toBeTruthy();
    expect(document.body.textContent).toContain("<ZEROSTRIKE_VERSION>");
  });
});
