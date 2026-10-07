import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanStatusSummaryPills } from "@/components/scans/scan-status-summary-pills";
import type { QueueJob, QueueView } from "@/lib/api/operations";
import { QueueTag } from "./queue-tag";

const getQueue = vi.fn<() => Promise<QueueView>>();
vi.mock("@/lib/api/operations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/operations")>()),
  getQueue: () => getQueue(),
}));

const SUMMARY = {
  running: 2,
  queued: 3,
  avg_duration_seconds: 60,
  avg_is_default: false,
  oldest_queued_at: null,
};

function job(o: Partial<QueueJob>): QueueJob {
  return {
    kind: "cloud_scan",
    job_id: "j",
    project_id: "p1",
    project_name: "P",
    ref_id: "scan1",
    status: "queued",
    summary: "repo",
    stage: null,
    created_at: new Date().toISOString(),
    started_at: null,
    position: 2,
    estimated_start_at: new Date(Date.now() + 83_000).toISOString(),
    error_message: null,
    completed_at: null,
    ...o,
  };
}

function view(jobs: QueueJob[], aiCapacity = 3): QueueView {
  return {
    server_time: new Date().toISOString(),
    queues: [
      { kind: "cloud_scan", label: "Cloud scans", capacity: 2, ...SUMMARY },
      { kind: "ai_analysis", label: "AI analysis", capacity: aiCapacity, ...SUMMARY },
      { kind: "remediation", label: "Auto-fix", capacity: 1, ...SUMMARY },
      { kind: "compliance", label: "Compliance audits", capacity: 2, ...SUMMARY },
    ],
    jobs,
  };
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => getQueue.mockReset());

describe("queued tag", () => {
  test("a queued scan badge shows its place in line and a countdown", async () => {
    getQueue.mockResolvedValue(view([job({})]));
    wrap(<ScanStatusBadge status="queued" scanId="scan1" />);
    expect(await screen.findByText(/#2 · 1:2\d/)).toBeDefined();
  });

  test("AI, auto-fix and audit badges key on their own queue", async () => {
    getQueue.mockResolvedValue(
      view([
        job({ kind: "ai_analysis", ref_id: "scan1", position: 1 }),
        job({ kind: "remediation", ref_id: "scan1", position: 3 }),
        job({ kind: "compliance", ref_id: "audit1", position: 4 }),
      ])
    );
    wrap(
      <>
        <AiStatusBadge status="queued" refId="scan1" />
        <AiStatusBadge status="queued" kind="autofix" refId="scan1" />
        <AiStatusBadge status="queued" kind="audit" refId="audit1" />
      </>
    );
    expect(await screen.findByText(/#1 ·/)).toBeDefined();
    expect(await screen.findByText(/#3 ·/)).toBeDefined();
    expect(await screen.findByText(/#4 ·/)).toBeDefined();
  });

  test("a passed estimate says 'any moment' and a paused queue says so instead of a time", async () => {
    getQueue.mockResolvedValue(
      view(
        [
          job({ ref_id: "late", estimated_start_at: new Date(Date.now() - 5000).toISOString() }),
          job({ kind: "ai_analysis", ref_id: "paused", estimated_start_at: null, position: 1 }),
        ],
        0
      )
    );
    wrap(
      <>
        <ScanStatusBadge status="queued" scanId="late" />
        <AiStatusBadge status="queued" refId="paused" />
      </>
    );
    expect(await screen.findByText(/#2 · any moment/)).toBeDefined();
    expect(await screen.findByText(/#1 · paused/)).toBeDefined();
  });

  test("renders nothing for a job that is not queued, and never asks without an id", async () => {
    getQueue.mockResolvedValue(view([job({ status: "running" })]));
    wrap(<QueueTag kind="cloud_scan" refId="scan1" standalone />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/QUEUED/i)).toBeNull();

    getQueue.mockClear();
    wrap(<ScanStatusBadge status="queued" />);
    expect(getQueue).not.toHaveBeenCalled();
  });

  test("the project summary pill names the next start", async () => {
    getQueue.mockResolvedValue(view([job({ position: 3 }), job({ ref_id: "s2", position: 1 })]));
    wrap(
      <ScanStatusSummaryPills
        counts={{ pending: 0, queued: 2, running: 0, completed: 0, failed: 0 }}
        projectId="p1"
      />
    );
    expect(await screen.findByText(/next #1 ·/)).toBeDefined();
  });
});
