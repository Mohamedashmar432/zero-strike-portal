import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { User } from "@/lib/api/auth";
import { listUsers, updateUser } from "@/lib/api/users";
import AdminUsersPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({ user: { id: "me" } }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api/users", () => ({
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  approveUser: vi.fn(),
  rejectUser: vi.fn(),
  deleteUser: vi.fn(),
}));

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "member@example.com",
    name: "Member",
    role: "user",
    is_active: true,
    approval_status: "approved",
    ...overrides,
  };
}

function setup(users: User[]) {
  vi.mocked(listUsers).mockResolvedValue({ items: users, total: users.length, page: 1, page_size: 20 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AdminUsersPage />
    </QueryClientProvider>
  );
}

// Secondary row actions live behind the "⋯" menu (components/common/row-actions.tsx).
async function clickRowMenuItem(name: string | RegExp) {
  fireEvent.click(await screen.findByRole("button", { name: /^Actions for/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name }));
}

describe("AdminUsersPage role changes", () => {
  afterEach(() => vi.clearAllMocks());

  test("Promote asks for confirmation and changes the role only after confirming", async () => {
    vi.mocked(updateUser).mockResolvedValue(user({ role: "admin" }));
    setup([user()]);

    await clickRowMenuItem(/^Promote to/);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Make member@example.com an administrator?")).toBeTruthy();
    expect(updateUser).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: /^Promote to/ }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { role: "admin" }));
  });

  test("cancelling the role confirmation changes nothing", async () => {
    setup([user()]);

    await clickRowMenuItem(/^Promote to/);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(updateUser).not.toHaveBeenCalled();
  });

  test("Demote asks for confirmation before removing administrator access", async () => {
    vi.mocked(updateUser).mockResolvedValue(user());
    setup([user({ role: "admin" })]);

    await clickRowMenuItem(/^Demote to/);
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Remove administrator access from member@example.com?")
    ).toBeTruthy();
    expect(updateUser).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: /^Demote to/ }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { role: "user" }));
  });
});
