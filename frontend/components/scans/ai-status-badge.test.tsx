import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { AiStatusBadge } from "./ai-status-badge";

describe("AiStatusBadge", () => {
  test("renders an analyzing tag with progress percent and ETA while in progress", () => {
    // Started 20s ago, 2 of 8 batches done -> 25%, and ~60s left (20s/2 * 6 remaining).
    const startedAt = new Date(Date.now() - 20_000).toISOString();
    render(
      <AiStatusBadge status="in_progress" startedAt={startedAt} progressCompleted={2} progressTotal={8} />
    );
    expect(screen.getByText("AI ANALYZING")).toBeDefined();
    expect(screen.getByText(/25% ·/)).toBeDefined();
    expect(screen.getByText(/left/)).toBeDefined();
    // No "ago" elapsed text anymore.
    expect(screen.queryByText(/ago/i)).toBeNull();
  });

  test("shows just the label when progress isn't known yet", () => {
    render(<AiStatusBadge status="in_progress" startedAt={null} progressTotal={0} />);
    expect(screen.getByText("AI ANALYZING")).toBeDefined();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  test("renders queued and failed states", () => {
    const { rerender } = render(<AiStatusBadge status="queued" />);
    expect(screen.getByText("AI QUEUED")).toBeDefined();
    rerender(<AiStatusBadge status="failed" />);
    expect(screen.getByText("AI FAILED")).toBeDefined();
  });

  test.each(["completed", "not_requested", null, undefined] as const)(
    "renders nothing for %s",
    (status) => {
      const { container } = render(<AiStatusBadge status={status} />);
      expect(container.firstChild).toBeNull();
    }
  );
});
