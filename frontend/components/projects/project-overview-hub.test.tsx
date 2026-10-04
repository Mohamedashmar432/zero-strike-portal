import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { ProjectAutoFixScanItem } from "@/lib/api/auto-fix";
import type { Project, ProjectScanActivity } from "@/lib/api/projects";
import { ProjectOverviewHub, proposalCounts, providerLabel } from "./project-overview-hub";

vi.mock("@/lib/api/compliance", () => ({
  listProjectAudits: vi.fn(() => Promise.resolve({ items: [], total: 0, page: 1, page_size: 1 })),
  listFrameworks: vi.fn(() =>
    Promise.resolve({
      items: [
        { key: "soc2", title: "SOC 2" },
        { key: "iso27001", title: "ISO 27001" },
      ],
    })
  ),
}));
vi.mock("@/lib/api/auto-fix", () => ({
  listProjectAutoFix: vi.fn(() => Promise.resolve({ items: [] })),
}));
vi.mock("@/components/projects/project-repo-breakdown", () => ({
  ProjectRepoBreakdown: () => null,
}));

const PROJECT = {
  id: "p1",
  name: "Empty",
  total_findings: 0,
  findings_by_severity: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
} as unknown as Project;

function item(proposed: number, prCreated: number) {
  return { summary: { proposed, pr_created: prCreated } } as unknown as ProjectAutoFixScanItem;
}

describe("ProjectOverviewHub on an empty project", () => {
  test("shows real empty states, never mockup numbers or unsupported frameworks", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <ProjectOverviewHub
          project={PROJECT}
          onNavigateTab={() => {}}
          aiUsage={{
            enabled: false,
            active_provider: null,
            active_model: null,
            total_requests: 0,
            total_prompt_tokens: 0,
            total_completion_tokens: 0,
            total_cost_usd: 0,
          }}
        />
      </QueryClientProvider>
    );

    expect(await screen.findByText("None yet")).toBeTruthy();
    expect(screen.getByText("No AI provider available for this project")).toBeTruthy();
    expect(await screen.findByText(/check this project against SOC 2 and ISO 27001/)).toBeTruthy();

    const text = container.textContent ?? "";
    for (const fake of ["Ready to Merge", "Claude 3.5 Sonnet", "24,810", "PCI-DSS", "HIPAA", "NIST"]) {
      expect(text).not.toContain(fake);
    }
  });
});

describe("ProjectOverviewHub health score", () => {
  const AI = {
    enabled: false,
    active_provider: null,
    active_model: null,
    total_requests: 0,
    total_prompt_tokens: 0,
    total_completion_tokens: 0,
    total_cost_usd: 0,
  };
  const COUNTS = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

  function renderHub(activity?: ProjectScanActivity) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ProjectOverviewHub project={PROJECT} activity={activity} onNavigateTab={() => {}} aiUsage={AI} />
      </QueryClientProvider>
    );
  }

  function activityWith(status: string): ProjectScanActivity {
    return {
      repos: [{ repo_id: "r1", repo_label: "r", provider: null, scans: [{ status } as never] }],
      current_findings: COUNTS,
      current_findings_total: 0,
    };
  }

  test("shows a dash instead of 100 before any completed scan", () => {
    renderHub(activityWith("failed"));
    expect(screen.getByText("Shown after the first completed scan.")).toBeTruthy();
    expect(screen.queryByText("100")).toBeNull();
  });

  test("shows the heuristic score once a scan has completed", () => {
    renderHub(activityWith("completed"));
    expect(screen.getByText("100")).toBeTruthy();
    expect(screen.queryByText("Shown after the first completed scan.")).toBeNull();
  });
});

describe("proposalCounts", () => {
  test("sums proposals and opened PRs across every scan", () => {
    expect(proposalCounts([item(3, 1), item(2, 0), item(0, 4)])).toEqual({
      awaitingReview: 5,
      prsOpened: 5,
    });
    expect(proposalCounts([])).toEqual({ awaitingReview: 0, prsOpened: 0 });
  });
});

describe("providerLabel", () => {
  test("names provider and model, and is null when nothing would serve", () => {
    const base = { enabled: true, total_requests: 0, total_prompt_tokens: 0, total_completion_tokens: 0, total_cost_usd: 0 };
    expect(providerLabel({ ...base, active_provider: "openai", active_model: "gpt-4o" })).toBe("openai · gpt-4o");
    expect(providerLabel({ ...base, active_provider: null, active_model: null })).toBeNull();
    expect(providerLabel(undefined)).toBeNull();
  });
});
