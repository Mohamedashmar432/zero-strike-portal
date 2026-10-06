import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { getProjectAiBudget, updateProjectAiBudget, type AiBudget } from "@/lib/api/ai";
import { ProjectAiBudgetCard } from "./project-ai-budget-card";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api/ai", () => ({
  getProjectAiBudget: vi.fn(),
  updateProjectAiBudget: vi.fn(),
}));

const BUDGET: AiBudget = {
  usd_monthly: 50,
  tokens_monthly: null,
  alert_percent: 80,
  hard_stop: false,
  period_start: "2026-10-01T00:00:00Z",
  used_usd: 42,
  used_tokens: 1_200_000,
  requests: 31,
  unpriced_requests: 2,
};

function setup(canManage: boolean) {
  vi.mocked(getProjectAiBudget).mockResolvedValue(BUDGET);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectAiBudgetCard projectId="p1" canManage={canManage} />
    </QueryClientProvider>
  );
  return client;
}

describe("ProjectAiBudgetCard", () => {
  afterEach(() => vi.clearAllMocks());

  test("shows month-to-date usage against the limit and flags unpriced calls", async () => {
    setup(true);
    expect(await screen.findByText("$42.00 of $50.00 (84%)")).toBeDefined();
    expect(screen.getByText(/1,200,000 · no limit/)).toBeDefined();
    expect(screen.getByText(/2 had no known price/)).toBeDefined();
  });

  test("saves limits, blank meaning no limit", async () => {
    setup(true);
    vi.mocked(updateProjectAiBudget).mockResolvedValue({ ...BUDGET, tokens_monthly: 2_000_000, hard_stop: true });
    fireEvent.change(await screen.findByLabelText("Monthly token limit"), { target: { value: "2000000" } });
    fireEvent.change(screen.getByLabelText("Monthly spend limit (USD)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("switch", { name: "Pause AI when a limit is reached" }));
    fireEvent.click(screen.getByRole("button", { name: "Save budget" }));
    await waitFor(() =>
      expect(updateProjectAiBudget).toHaveBeenCalledWith("p1", {
        usd_monthly: null,
        tokens_monthly: 2_000_000,
        alert_percent: 80,
        hard_stop: true,
      })
    );
  });

  test("a background refetch does not wipe a half-typed edit", async () => {
    // Found in browser QA: React Query refetches on window focus, and the form used to re-seed on
    // every new server copy, so clicking back into the window erased what had just been typed.
    const client = setup(true);
    const field = (await screen.findByLabelText("Monthly spend limit (USD)")) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "75" } });
    await client.refetchQueries();
    await waitFor(() => expect(getProjectAiBudget).toHaveBeenCalledTimes(2));
    expect(field.value).toBe("75");
  });

  test("an alert threshold outside 1-99 cannot be saved", async () => {
    setup(true);
    fireEvent.change(await screen.findByLabelText("Alert at (% of limit)"), { target: { value: "100" } });
    expect((screen.getByRole("button", { name: "Save budget" }) as HTMLButtonElement).disabled).toBe(true);
  });

  test("members see the budget read-only", async () => {
    setup(false);
    expect(await screen.findByText(/Only a project owner or admin/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Save budget" })).toBeNull();
    expect((screen.getByLabelText("Monthly spend limit (USD)") as HTMLInputElement).disabled).toBe(true);
  });
});
