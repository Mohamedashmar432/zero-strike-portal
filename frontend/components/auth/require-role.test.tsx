import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { RequireRole } from "./require-role";

const mockUseAuth = vi.fn();
vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => mockUseAuth(),
}));

describe("RequireRole", () => {
  test("renders children when the user has the role", () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin" } });
    render(
      <RequireRole role="admin">
        <p>Secret</p>
      </RequireRole>
    );
    expect(screen.getByText("Secret")).toBeDefined();
  });

  test("renders nothing when the user has a different role", () => {
    mockUseAuth.mockReturnValue({ user: { role: "user" } });
    render(
      <RequireRole role="admin">
        <p>Secret</p>
      </RequireRole>
    );
    expect(screen.queryByText("Secret")).toBeNull();
  });

  test("renders nothing when there is no user", () => {
    mockUseAuth.mockReturnValue({ user: null });
    render(
      <RequireRole role="admin">
        <p>Secret</p>
      </RequireRole>
    );
    expect(screen.queryByText("Secret")).toBeNull();
  });
});
