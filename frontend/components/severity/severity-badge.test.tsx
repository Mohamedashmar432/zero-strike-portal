import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { SeverityBadge } from "./severity-badge";

describe("SeverityBadge", () => {
  test.each(["critical", "high", "medium", "low", "info"] as const)("renders the %s label", (severity) => {
    render(<SeverityBadge severity={severity} />);
    expect(screen.getByText(severity)).toBeDefined();
  });
});
