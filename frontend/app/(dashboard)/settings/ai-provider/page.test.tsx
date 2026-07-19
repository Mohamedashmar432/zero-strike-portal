import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { toast } from "sonner";
import {
  activateAiProvider,
  createAiProvider,
  deleteAiProvider,
  listAiProviders,
  testAiProviderConnection,
  updateAiProvider,
  type AiProviderConfig,
} from "@/lib/api/ai";
import { ApiError } from "@/lib/api/client";
import AiProviderSettingsPage from "./page";

const mockUseHasRole = vi.fn();
vi.mock("@/lib/hooks/use-has-role", () => ({
  useHasRole: () => mockUseHasRole(),
}));

vi.mock("@/lib/api/ai", () => ({
  listAiProviders: vi.fn(),
  createAiProvider: vi.fn(),
  updateAiProvider: vi.fn(),
  deleteAiProvider: vi.fn(),
  activateAiProvider: vi.fn(),
  deactivateAiProvider: vi.fn(),
  testAiProviderConnection: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function makeProvider(overrides: Partial<AiProviderConfig> = {}): AiProviderConfig {
  return {
    id: "p1",
    name: "Prod Anthropic",
    provider: "anthropic",
    model_name: "claude-sonnet-5",
    base_url: null,
    temperature: 0.2,
    is_active: true,
    has_api_key: true,
    total_requests: 0,
    total_failed_requests: 0,
    total_prompt_tokens: 0,
    total_completion_tokens: 0,
    total_cost_usd: 0,
    last_used_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
    ...overrides,
  };
}

async function openDialog(triggerName: string) {
  fireEvent.click(screen.getByRole("button", { name: triggerName }));
  return screen.findByRole("dialog");
}

// base-ui's Select needs a full pointer-event sequence (not just `click`) to actually commit
// a selection under jsdom -- verified against components/ui/select.tsx.
async function selectProviderOption(trigger: HTMLElement, optionName: string) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1 });
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: optionName });
  fireEvent.pointerDown(option, { button: 0, pointerId: 1 });
  fireEvent.pointerUp(option, { button: 0, pointerId: 1 });
  fireEvent.click(option);
}

describe("AiProviderSettingsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test("non-admins see the admins-only empty state and no table", () => {
    mockUseHasRole.mockReturnValue(false);
    renderWithClient(<AiProviderSettingsPage />);
    expect(screen.getByText("Admins only")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("admins with zero providers see the empty state and an Add provider CTA", async () => {
    mockUseHasRole.mockReturnValue(true);
    vi.mocked(listAiProviders).mockResolvedValue([]);
    renderWithClient(<AiProviderSettingsPage />);

    expect(await screen.findByText("No AI providers configured")).toBeDefined();
    expect(screen.getAllByRole("button", { name: "Add provider" }).length).toBe(2);
  });

  test("renders an active provider with formatted usage stats, a green Active badge, and a Deactivate action", async () => {
    mockUseHasRole.mockReturnValue(true);
    const provider = makeProvider({
      total_requests: 42,
      total_failed_requests: 3,
      total_prompt_tokens: 120000,
      total_completion_tokens: 30000,
      total_cost_usd: 12.5,
      last_used_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    });
    vi.mocked(listAiProviders).mockResolvedValue([provider]);
    renderWithClient(<AiProviderSettingsPage />);

    expect(await screen.findByText("Prod Anthropic")).toBeDefined();
    expect(screen.getByText("Anthropic")).toBeDefined();
    expect(screen.getByText("claude-sonnet-5")).toBeDefined();
    expect(screen.getByText("Active")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Set Active" })).toBeNull();
    expect(screen.getByText(/42 req, 3 failed/)).toBeDefined();
    expect(screen.getByText(/150K tokens/)).toBeDefined();
    expect(screen.getByText(/\$12\.50/)).toBeDefined();
    expect(screen.getByText("1 hour ago")).toBeDefined();
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeDefined();
  });

  test("a provider with no usage yet shows zero counts and Never used", async () => {
    mockUseHasRole.mockReturnValue(true);
    vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
    renderWithClient(<AiProviderSettingsPage />);

    expect(await screen.findByText(/^0 req$/)).toBeDefined();
    expect(screen.getByText("Never used")).toBeDefined();
  });

  test("inactive provider shows Set Active, and activating it calls activateAiProvider", async () => {
    mockUseHasRole.mockReturnValue(true);
    const provider = makeProvider({ id: "p2", is_active: false });
    vi.mocked(listAiProviders).mockResolvedValue([provider]);
    vi.mocked(activateAiProvider).mockResolvedValue([{ ...provider, is_active: true }]);
    renderWithClient(<AiProviderSettingsPage />);

    const setActiveBtn = await screen.findByRole("button", { name: "Set Active" });
    fireEvent.click(setActiveBtn);
    await waitFor(() => expect(activateAiProvider).toHaveBeenCalledWith("p2"));
  });

  test("renders one row per provider", async () => {
    mockUseHasRole.mockReturnValue(true);
    vi.mocked(listAiProviders).mockResolvedValue([
      makeProvider({ id: "p1", name: "One" }),
      makeProvider({ id: "p2", name: "Two", is_active: false }),
      makeProvider({ id: "p3", name: "Three", is_active: false }),
    ]);
    renderWithClient(<AiProviderSettingsPage />);

    expect(await screen.findByText("One")).toBeDefined();
    expect(screen.getByText("Two")).toBeDefined();
    expect(screen.getByText("Three")).toBeDefined();
    expect(screen.getAllByRole("row").length).toBe(4); // 1 header row + 3 data rows
  });

  describe("Add dialog", () => {
    test("submitting blank shows required-field errors and does not call createAiProvider", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.click(within(dialog).getByRole("button", { name: "Add provider" }));

      expect(await within(dialog).findByText("Name is required")).toBeDefined();
      expect(within(dialog).getByText("Model name is required")).toBeDefined();
      expect(createAiProvider).not.toHaveBeenCalled();
    });

    test("switching to a self-hosted provider and leaving base_url blank shows the base_url error", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Local" } });
      fireEvent.change(within(dialog).getByLabelText("Model name"), { target: { value: "local-model" } });
      await selectProviderOption(within(dialog).getByRole("combobox"), "Custom");

      fireEvent.click(within(dialog).getByRole("button", { name: "Add provider" }));

      expect(await within(dialog).findByText("Base URL is required for this provider")).toBeDefined();
      expect(createAiProvider).not.toHaveBeenCalled();
    });

    test("leaving api_key blank shows the required error and does not call createAiProvider", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "New provider" } });
      fireEvent.change(within(dialog).getByLabelText("Model name"), { target: { value: "gpt-5" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Add provider" }));

      expect(await within(dialog).findByText("An API key is required")).toBeDefined();
      expect(createAiProvider).not.toHaveBeenCalled();
    });

    test("a valid submission calls createAiProvider with the expected payload and closes the dialog", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      vi.mocked(createAiProvider).mockResolvedValue(makeProvider({ id: "new" }));
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "New provider" } });
      fireEvent.change(within(dialog).getByLabelText("Model name"), { target: { value: "gpt-5" } });
      fireEvent.change(within(dialog).getByLabelText("API key"), { target: { value: "sk-test" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Add provider" }));

      await waitFor(() =>
        expect(createAiProvider).toHaveBeenCalledWith({
          name: "New provider",
          provider: "anthropic",
          model_name: "gpt-5",
          base_url: undefined,
          api_key: "sk-test",
        })
      );
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    });
  });

  describe("Edit dialog", () => {
    test("opens pre-filled from the clicked row, with a blank api_key and the 'leave blank to keep' placeholder", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider({ has_api_key: true })]);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Edit");
      expect(await within(dialog).findByDisplayValue("Prod Anthropic")).toBeDefined();
      expect(within(dialog).getByDisplayValue("claude-sonnet-5")).toBeDefined();
      const apiKeyInput = within(dialog).getByLabelText("API key") as HTMLInputElement;
      expect(apiKeyInput.value).toBe("");
      expect(apiKeyInput.placeholder).toMatch(/saved — leave blank to keep/);
    });

    test("submitting without touching api_key calls updateAiProvider with api_key omitted", async () => {
      mockUseHasRole.mockReturnValue(true);
      const provider = makeProvider();
      vi.mocked(listAiProviders).mockResolvedValue([provider]);
      vi.mocked(updateAiProvider).mockResolvedValue(provider);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Edit");
      await within(dialog).findByDisplayValue("Prod Anthropic");
      fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

      await waitFor(() => expect(updateAiProvider).toHaveBeenCalledTimes(1));
      const [id, input] = vi.mocked(updateAiProvider).mock.calls[0];
      expect(id).toBe("p1");
      expect(input.api_key).toBeUndefined();
      expect(input.name).toBe("Prod Anthropic");
    });
  });

  describe("Test connection", () => {
    test("from the dialog (draft, no id) calls testAiProviderConnection without an id, and shows a success toast", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      vi.mocked(testAiProviderConnection).mockResolvedValue(undefined);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Draft" } });
      fireEvent.change(within(dialog).getByLabelText("Model name"), { target: { value: "gpt-5" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));

      await waitFor(() =>
        expect(testAiProviderConnection).toHaveBeenCalledWith(
          expect.objectContaining({ id: undefined, provider: "anthropic", model_name: "gpt-5" })
        )
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Connection successful"));
    });

    test("failure from the dialog shows an error toast with the ApiError message", async () => {
      mockUseHasRole.mockReturnValue(true);
      vi.mocked(listAiProviders).mockResolvedValue([makeProvider()]);
      vi.mocked(testAiProviderConnection).mockRejectedValue(new ApiError(400, { detail: "bad key" }));
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      const dialog = await openDialog("Add provider");
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Draft" } });
      fireEvent.change(within(dialog).getByLabelText("Model name"), { target: { value: "gpt-5" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("bad key"));
    });

    test("from a saved row calls testAiProviderConnection with that row's id", async () => {
      mockUseHasRole.mockReturnValue(true);
      const provider = makeProvider();
      vi.mocked(listAiProviders).mockResolvedValue([provider]);
      vi.mocked(testAiProviderConnection).mockResolvedValue(undefined);
      renderWithClient(<AiProviderSettingsPage />);
      await screen.findByText("Prod Anthropic");

      fireEvent.click(screen.getByRole("button", { name: "Test" }));
      await waitFor(() =>
        expect(testAiProviderConnection).toHaveBeenCalledWith({
          id: "p1",
          provider: "anthropic",
          model_name: "claude-sonnet-5",
          base_url: undefined,
        })
      );
    });
  });

  test("Delete calls deleteAiProvider immediately, with no confirmation UI rendered first", async () => {
    mockUseHasRole.mockReturnValue(true);
    const provider = makeProvider();
    vi.mocked(listAiProviders).mockResolvedValue([provider]);
    vi.mocked(deleteAiProvider).mockResolvedValue(undefined);
    renderWithClient(<AiProviderSettingsPage />);
    await screen.findByText("Prod Anthropic");

    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(deleteAiProvider).toHaveBeenCalledWith("p1"));
  });
});
