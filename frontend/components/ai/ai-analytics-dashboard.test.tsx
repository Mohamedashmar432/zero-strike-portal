import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  getPortalAiAnalytics,
  getProjectAiAnalytics,
  listPortalAiEvents,
  listProjectAiEvents,
  type AiAnalytics,
  type AiUsageEventPage,
} from "@/lib/api/ai";
import { AiAnalyticsDashboard } from "./ai-analytics-dashboard";

vi.mock("@/lib/api/ai", () => ({
  getProjectAiAnalytics: vi.fn(),
  getPortalAiAnalytics: vi.fn(),
  listProjectAiEvents: vi.fn(),
  listPortalAiEvents: vi.fn(),
}));

// recharts measures its container, which jsdom reports as 0x0 — charts render nothing without
// this. The assertions below are about numbers and copy, not SVG geometry.
vi.mock("@/components/ui/chart", () => ({
  ChartContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ChartTooltip: () => null,
  ChartTooltipContent: () => null,
}));

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const EMPTY_TOTALS = {
  requests: 0,
  failed: 0,
  success_rate: 100,
  prompt_tokens: 0,
  completion_tokens: 0,
  cost_usd: 0,
  avg_duration_ms: 0,
};

function analytics(overrides: Partial<AiAnalytics> = {}): AiAnalytics {
  return {
    days: 30,
    totals: EMPTY_TOTALS,
    timeseries: [],
    by_feature: [],
    by_model: [],
    by_project: [],
    ...overrides,
  };
}

function events(overrides: Partial<AiUsageEventPage> = {}): AiUsageEventPage {
  return { items: [], total: 0, page: 1, page_size: 15, ...overrides };
}

beforeEach(() => {
  vi.mocked(listProjectAiEvents).mockResolvedValue(events());
  vi.mocked(listPortalAiEvents).mockResolvedValue(events());
});

describe("AiAnalyticsDashboard", () => {
  test("shows a real empty state rather than fabricated numbers", async () => {
    vi.mocked(getProjectAiAnalytics).mockResolvedValue(analytics());
    renderWithClient(<AiAnalyticsDashboard scope="project" projectId="p1" />);

    expect(await screen.findByText("No AI calls in this window")).toBeDefined();
    expect(screen.getByText("$0.00")).toBeDefined();
    // A quiet project reads 100% success, not 0% — "no calls" is not "everything failed".
    expect(screen.getByText("100%")).toBeDefined();
  });

  test("renders the KPI row from the totals", async () => {
    vi.mocked(getProjectAiAnalytics).mockResolvedValue(
      analytics({
        totals: {
          requests: 120,
          failed: 6,
          success_rate: 95,
          prompt_tokens: 40_000,
          completion_tokens: 10_000,
          cost_usd: 12.5,
          avg_duration_ms: 2400,
        },
        timeseries: [
          { date: "2026-08-01", requests: 60, failed: 3, success_rate: 95, prompt_tokens: 20_000, completion_tokens: 5_000, cost_usd: 6.25 },
        ],
        by_feature: [{ feature: "autofix", ...EMPTY_TOTALS, requests: 120, cost_usd: 12.5 }],
      }),
    );
    renderWithClient(<AiAnalyticsDashboard scope="project" projectId="p1" />);

    expect(await screen.findByText("$12.50")).toBeDefined();
    expect(screen.getByText("120")).toBeDefined();
    expect(screen.getByText("95%")).toBeDefined();
    expect(screen.getByText("2.4s")).toBeDefined();
    expect(screen.getByText("6 failed")).toBeDefined();
  });

  test("project scope never asks for the portal-wide data", async () => {
    vi.mocked(getProjectAiAnalytics).mockResolvedValue(analytics());
    renderWithClient(<AiAnalyticsDashboard scope="project" projectId="p1" />);

    await waitFor(() => expect(getProjectAiAnalytics).toHaveBeenCalledWith("p1", 30));
    expect(getPortalAiAnalytics).not.toHaveBeenCalled();
  });

  test("portal scope shows the per-project breakdown and the project column", async () => {
    vi.mocked(getPortalAiAnalytics).mockResolvedValue(
      analytics({
        totals: { ...EMPTY_TOTALS, requests: 3, cost_usd: 9 },
        by_project: [
          { project_id: "p2", project_name: "Beta", ...EMPTY_TOTALS, requests: 2, cost_usd: 8 },
          { project_id: "p1", project_name: "Alpha", ...EMPTY_TOTALS, requests: 1, cost_usd: 1 },
        ],
      }),
    );
    vi.mocked(listPortalAiEvents).mockResolvedValue(
      events({
        total: 1,
        items: [
          {
            id: "e1",
            created_at: "2026-08-10T10:00:00Z",
            project_id: "p2",
            project_name: "Beta",
            scan_id: null,
            scope: "project",
            feature: "autofix",
            provider: "anthropic",
            model_name: "claude-sonnet-4-5",
            status: "failed",
            error_type: "LLMTransientError",
            duration_ms: 900,
            prompt_tokens: 10,
            completion_tokens: 2,
            cost_usd: 0.004,
          },
        ],
      }),
    );

    renderWithClient(<AiAnalyticsDashboard scope="portal" />);

    expect(await screen.findByText("Spend by project")).toBeDefined();
    expect(screen.getByText("Project")).toBeDefined();
    // A failure names its error type, and carries an icon as well as colour.
    expect(screen.getByText("LLMTransientError")).toBeDefined();
    // Sub-cent spend must not read as free.
    expect(screen.getByText("<$0.01")).toBeDefined();
  });

  test("a project view has no project column in the log", async () => {
    vi.mocked(getProjectAiAnalytics).mockResolvedValue(analytics());
    vi.mocked(listProjectAiEvents).mockResolvedValue(
      events({
        total: 1,
        items: [
          {
            id: "e1",
            created_at: "2026-08-10T10:00:00Z",
            project_id: "p1",
            project_name: "Alpha",
            scan_id: null,
            scope: "project",
            feature: "analysis",
            provider: "openai",
            model_name: "gpt-4o",
            status: "success",
            error_type: null,
            duration_ms: 1200,
            prompt_tokens: 100,
            completion_tokens: 20,
            cost_usd: 0.05,
          },
        ],
      }),
    );

    renderWithClient(<AiAnalyticsDashboard scope="project" projectId="p1" />);

    expect(await screen.findByText("Finding analysis")).toBeDefined();
    expect(screen.queryByText("Project")).toBeNull();
  });
});
