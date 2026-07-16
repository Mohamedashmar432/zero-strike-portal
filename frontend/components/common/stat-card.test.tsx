import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { StatCard } from "./stat-card";

describe("StatCard", () => {
  test("renders label and value", () => {
    render(<StatCard label="Total scans" value={42} />);
    expect(screen.getByText("Total scans")).toBeDefined();
    expect(screen.getByText("42")).toBeDefined();
  });

  test("shows a skeleton instead of the value while loading", () => {
    const { container } = render(<StatCard label="Total scans" value={42} isLoading />);
    expect(screen.queryByText("42")).toBeNull();
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
  });
});
