import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  getFindingAnalysis,
  triggerFindingAnalysis,
  type AiAnalysisResult,
  type FindingInsight,
} from "@/lib/api/ai";
import type { Finding } from "@/lib/api/findings";
import { FindingItem } from "./page";

vi.mock("@/lib/api/ai", () => ({
  getFindingAnalysis: vi.fn(),
  triggerFindingAnalysis: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const baseFinding: Finding = {
  id: "finding-1",
  scan_id: "scan-1",
  project_id: "project-1",
  project_repo_id: null,
  finding_id: null,
  fingerprint: "abc123",
  rule_id: "rule-1",
  rule_name: "SQL Injection",
  category: "injection",
  severity: "high",
  confidence: null,
  priority_score: null,
  priority_tier: null,
  message: "Possible SQL injection",
  location: { file: "app.py", start_line: 10, end_line: 10, start_col: null, end_col: null },
  language: "python",
  evidence: [],
  cwe: [],
  owasp: [],
  references: [],
  metadata: {},
  kind: "sast",
  secret: null,
  dependency: null,
  config: null,
  rationale: "Untrusted input reaches a SQL query.",
  remediation: null,
  taint_context: null,
  created_at: "2026-01-01T00:00:00Z",
};

const notRequested: AiAnalysisResult<FindingInsight> = {
  status: "not_requested",
  error_message: null,
  started_at: null,
  progress_completed: 0,
  progress_total: 0,
  insight: null,
};

describe("FindingItem AI analysis", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test("disabled with a hint when no AI provider is configured", () => {
    renderWithClient(<FindingItem finding={baseFinding} expanded onToggle={() => {}} aiEnabled={false} />);
    const button = screen.getByRole("button", { name: /analyze with ai/i });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("title")).toMatch(/configure an ai provider/i);
    expect(getFindingAnalysis).not.toHaveBeenCalled();
  });

  test("disabled with a hint when the finding has no fingerprint", () => {
    renderWithClient(
      <FindingItem finding={{ ...baseFinding, fingerprint: null }} expanded onToggle={() => {}} aiEnabled />
    );
    const button = screen.getByRole("button", { name: /analyze with ai/i });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("title")).toMatch(/isn't available for this finding/i);
  });

  test("enabled and idle when a provider is configured and the finding has a fingerprint", async () => {
    vi.mocked(getFindingAnalysis).mockResolvedValue(notRequested);
    renderWithClient(<FindingItem finding={baseFinding} expanded onToggle={() => {}} aiEnabled />);
    const button = await screen.findByRole("button", { name: /analyze with ai/i });
    expect(button.hasAttribute("disabled")).toBe(false);
  });

  test("idle -> loading -> completed flow", async () => {
    vi.mocked(getFindingAnalysis).mockResolvedValue(notRequested);
    let resolveTrigger: (value: AiAnalysisResult<FindingInsight>) => void = () => {};
    vi.mocked(triggerFindingAnalysis).mockReturnValue(
      new Promise((resolve) => {
        resolveTrigger = resolve;
      })
    );

    renderWithClient(<FindingItem finding={baseFinding} expanded onToggle={() => {}} aiEnabled />);

    const button = await screen.findByRole("button", { name: /analyze with ai/i });
    fireEvent.click(button);

    const loadingButton = await screen.findByRole("button", { name: /analyzing/i });
    expect(loadingButton.hasAttribute("disabled")).toBe(true);
    expect(screen.getAllByText("AI Analysis").length).toBeGreaterThan(0);

    resolveTrigger({
      status: "completed",
      error_message: null,
      started_at: null,
      progress_completed: 0,
      progress_total: 0,
      insight: {
        is_false_positive: false,
        false_positive_confidence: 0.9,
        analysis_confidence: 0.9,
        verdict_reasoning: null,
        improved_description: "This is a real SQL injection.",
        adjusted_severity: null,
        severity_reasoning: null,
        owasp: [],
        cwe: [],
        cvss_score: null,
        explanation: "User input flows directly into the query.",
        similar_finding_count: 2,
        provider: "anthropic",
        model_name: "claude-sonnet-5",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });

    expect(await screen.findByText("Likely valid")).toBeDefined();
    expect(screen.getByText("User input flows directly into the query.")).toBeDefined();
    // AI confidence comes from analysis_confidence (not the false-positive score).
    expect(screen.getByText(/AI confidence: 90%/i)).toBeDefined();
    // Recurring-finding tag (informative, not "duplicate").
    expect(screen.getByText(/Found in 2 other locations/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /re-analyze/i })).toBeDefined();
    // The original trigger button is replaced by Re-analyze once there's a terminal result.
    expect(screen.queryByRole("button", { name: /^analyze with ai$/i })).toBeNull();
  });

  test("shows an AI severity overlay when the AI adjusts the scanner severity", async () => {
    // baseFinding.severity is "high"; the AI downgrades it to "low".
    vi.mocked(getFindingAnalysis).mockResolvedValue({
      status: "completed",
      error_message: null,
      started_at: null,
      progress_completed: 0,
      progress_total: 0,
      insight: {
        is_false_positive: true,
        false_positive_confidence: 0.8,
        analysis_confidence: null,
        verdict_reasoning: "parameterized query",
        improved_description: null,
        adjusted_severity: "low",
        severity_reasoning: "user input never reaches the sink",
        owasp: [],
        cwe: [],
        cvss_score: null,
        explanation: null,
        similar_finding_count: 0,
        provider: "anthropic",
        model_name: "claude-sonnet-5",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });

    renderWithClient(<FindingItem finding={baseFinding} expanded onToggle={() => {}} aiEnabled />);

    // The overlay marker + the AI's new severity, and the reasoning in the AI subsection.
    expect(await screen.findByText("AI→")).toBeDefined();
    expect(screen.getAllByText("low").length).toBeGreaterThan(0);
    expect(screen.getByText(/user input never reaches the sink/i)).toBeDefined();
  });
});
