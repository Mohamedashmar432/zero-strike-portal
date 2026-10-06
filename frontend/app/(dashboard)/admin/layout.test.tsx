import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import AdminLayout from "./layout";

const auth = vi.hoisted(() => ({ role: "user" as "user" | "admin" }));
vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({ user: { id: "me", role: auth.role } }),
}));

function renderLayout() {
  render(
    <AdminLayout>
      <p>admin page body</p>
    </AdminLayout>
  );
}

describe("AdminLayout", () => {
  test("a member gets an Admins-only state and the page never mounts", () => {
    auth.role = "user";
    renderLayout();
    expect(screen.getByText("Admins only")).toBeTruthy();
    expect(screen.queryByText("admin page body")).toBeNull();
  });

  test("an admin gets the page", () => {
    auth.role = "admin";
    renderLayout();
    expect(screen.getByText("admin page body")).toBeTruthy();
    expect(screen.queryByText("Admins only")).toBeNull();
  });
});
