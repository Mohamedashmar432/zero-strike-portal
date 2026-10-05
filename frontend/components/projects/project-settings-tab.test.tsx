import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { getProject, updateProject } from "@/lib/api/projects";
import { ProjectSettingsTab } from "./project-settings-tab";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api/projects", () => ({
  getProject: vi.fn(),
  updateProject: vi.fn(() => Promise.resolve({})),
  deleteProject: vi.fn(),
}));
vi.mock("@/components/projects/project-ai-provider-card", () => ({ ProjectAiProviderCard: () => null }));
vi.mock("@/components/projects/project-policy-card", () => ({ ProjectPolicyCard: () => null }));
vi.mock("@/components/reports/report-template-picker", () => ({ ReportTemplatePicker: () => null }));

function setup(project: Record<string, unknown>) {
  vi.mocked(getProject).mockResolvedValue({ id: "p1", name: "Demo", description: "", ...project } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectSettingsTab projectId="p1" />
    </QueryClientProvider>
  );
}

afterEach(() => vi.clearAllMocks());

describe("archive / restore", () => {
  test("archiving asks for confirmation, then sends is_archived: true", async () => {
    setup({ my_role: "owner", is_archived: false });
    fireEvent.click(await screen.findByRole("button", { name: "Archive project" }));
    expect(updateProject).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { is_archived: true }));
  });

  test("an archived project offers Restore", async () => {
    setup({ my_role: "owner", is_archived: true });
    fireEvent.click(await screen.findByRole("button", { name: "Restore project" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { is_archived: false }));
  });

  test("a collaborator sees no archive control", async () => {
    setup({ my_role: "collaborator", is_archived: false });
    await screen.findByText(/owner or admin access/);
    expect(screen.queryByRole("button", { name: "Archive project" })).toBeNull();
  });
});
