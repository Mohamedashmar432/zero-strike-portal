import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { ControlStatus } from "@/lib/api/compliance";
import { ControlStatusBadge } from "./control-status-badge";

describe("ControlStatusBadge", () => {
  test.each([
    ["pass", "Pass"],
    ["fail", "Fail"],
    ["partial", "Partial"],
    ["not_applicable", "Not applicable"],
    ["needs_manual_review", "Needs manual review"],
  ] as const)("renders the %s label", (status, label) => {
    render(<ControlStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeDefined();
  });

  test("a passing control uses the success token, a failing one the critical token", () => {
    const { container, rerender } = render(<ControlStatusBadge status="pass" />);
    expect(container.firstElementChild?.className).toContain("text-status-success");
    rerender(<ControlStatusBadge status="fail" />);
    expect(container.firstElementChild?.className).toContain("text-severity-critical");
  });

  test("falls back to needs-manual-review rather than rendering an empty badge", () => {
    // Defensive: a status the frontend doesn't know yet must not render blank, because a
    // blank badge next to a control reads as "no problem here".
    render(<ControlStatusBadge status={undefined as unknown as ControlStatus} />);
    expect(screen.getByText("Needs manual review")).toBeDefined();
  });
});
