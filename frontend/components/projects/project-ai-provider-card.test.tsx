import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { deleteProjectAiProvider, listProjectAiProviders, type AiProviderConfig } from "@/lib/api/ai";
import { ProjectAiProviderCard } from "./project-ai-provider-card";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api/ai", () => ({
  getAiSettings: vi.fn(() => Promise.resolve({ project_byok_enabled: true })),
  listProjectAiProviders: vi.fn(),
  createProjectAiProvider: vi.fn(),
  updateProjectAiProvider: vi.fn(),
  deleteProjectAiProvider: vi.fn(),
  activateProjectAiProvider: vi.fn(),
  testProjectAiProvider: vi.fn(),
}));

const KEY = {
  id: "k1",
  name: "Team key",
  project_id: "p1",
  provider: "openai",
  model_name: "gpt-4o",
  base_url: null,
  is_active: true,
  has_api_key: true,
  key_storage: "encrypted_database",
  key_vault_secret_name: null,
} as unknown as AiProviderConfig;

function setup() {
  vi.mocked(listProjectAiProviders).mockResolvedValue([KEY]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectAiProviderCard projectId="p1" canManage />
    </QueryClientProvider>
  );
}

// Secondary row actions live behind the "⋯" menu (components/common/row-actions.tsx).
async function clickRowMenuItem(name: string | RegExp) {
  fireEvent.click(await screen.findByRole("button", { name: /^Actions for/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name }));
}

describe("ProjectAiProviderCard", () => {
  afterEach(() => vi.clearAllMocks());

  test("Remove asks for confirmation and removes the key only after confirming", async () => {
    vi.mocked(deleteProjectAiProvider).mockResolvedValue(undefined);
    setup();

    await clickRowMenuItem("Remove");
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Remove this project's AI key?")).toBeTruthy();
    // The active key is the project's only provider, so the consequence must be spelled out.
    expect(within(dialog).getByText(/does not fall back to the portal/)).toBeTruthy();
    expect(deleteProjectAiProvider).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(deleteProjectAiProvider).toHaveBeenCalledWith("p1", "k1"));
  });

  test("cancelling the confirmation removes nothing", async () => {
    setup();

    await clickRowMenuItem("Remove");
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(deleteProjectAiProvider).not.toHaveBeenCalled();
  });
});
