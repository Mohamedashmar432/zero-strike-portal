import { render, screen } from "@testing-library/react";
import { Sparkles } from "lucide-react";
import { describe, expect, test } from "vitest";
import { EmptyState } from "./empty-state";

describe("EmptyState", () => {
  test("renders title and description", () => {
    render(<EmptyState icon={Sparkles} title="Coming soon" description="Not available yet" />);
    expect(screen.getByText("Coming soon")).toBeDefined();
    expect(screen.getByText("Not available yet")).toBeDefined();
  });

  test("omits description when not provided", () => {
    render(<EmptyState title="No data" />);
    expect(screen.getByText("No data")).toBeDefined();
  });
});
