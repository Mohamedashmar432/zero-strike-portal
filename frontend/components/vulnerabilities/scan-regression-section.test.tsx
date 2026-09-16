import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { getScanRegression, type ScanRegressionResponse } from "@/lib/api/vulnerabilities";
import { ScanRegressionSection } from "./scan-regression-section";

vi.mock("@/lib/api/vulnerabilities", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/vulnerabilities")>(
    "@/lib/api/vulnerabilities"
  );
  return { ...actual, getScanRegression: vi.fn() };
});

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function bucket(count: number): ScanRegressionResponse["new"] {
  return { count, items: [] };
}

function response(over: Partial<ScanRegressionResponse> = {}): ScanRegressionResponse {
  return {
    scan_id: "s1",
    baseline_scan_id: "s0",
    has_baseline: true,
    new: bucket(0),
    unchanged: bucket(0),
    reopened: bucket(0),
    fixed: bucket(0),
    ...over,
  };
}

describe("ScanRegressionSection", () => {
  beforeEach(() => vi.mocked(getScanRegression).mockReset());

  test("renders the four outcome counts", async () => {
    vi.mocked(getScanRegression).mockResolvedValue(
      response({ new: bucket(3), reopened: bucket(1), fixed: bucket(7), unchanged: bucket(12) })
    );

    renderWithClient(<ScanRegressionSection projectId="p1" scanId="s1" />);

    await waitFor(() => expect(screen.getByText("3")).toBeTruthy());
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText(/New/i)).toBeTruthy();
    expect(screen.getByText(/Reopened/i)).toBeTruthy();
  });

  test("says so plainly when there is no baseline to compare against", async () => {
    // "0 fixed" against no baseline would read as "nothing was fixed" rather than
    // "there is nothing to compare against" — the distinction has to be stated.
    vi.mocked(getScanRegression).mockResolvedValue(
      response({ baseline_scan_id: null, has_baseline: false, new: bucket(5) })
    );

    const { container } = renderWithClient(<ScanRegressionSection projectId="p1" scanId="s1" />);

    await waitFor(() =>
      expect(container.textContent).toContain("First comparable scan; no baseline exists.")
    );
    expect(container.textContent).not.toContain("Compared with the previous completed scan");
  });

  test("shows the baseline note when a prior scan exists", async () => {
    vi.mocked(getScanRegression).mockResolvedValue(response());

    const { container } = renderWithClient(<ScanRegressionSection projectId="p1" scanId="s1" />);

    await waitFor(() =>
      expect(container.textContent).toContain("Compared with the previous completed scan")
    );
    expect(container.textContent).not.toContain("no baseline exists");
  });

  test("counts come from the bucket total, not the capped item preview", async () => {
    // The API returns at most a preview of `items`; `count` is the real number. A tile that
    // rendered items.length would under-report a large scan.
    vi.mocked(getScanRegression).mockResolvedValue(response({ fixed: { count: 400, items: [] } }));

    renderWithClient(<ScanRegressionSection projectId="p1" scanId="s1" />);

    await waitFor(() => expect(screen.getByText("400")).toBeTruthy());
  });
});
