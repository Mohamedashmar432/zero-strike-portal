import { apiFetch } from "./client";
import type { User } from "./auth";

export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export function listUsers(page = 1, pageSize = 20) {
  return apiFetch<Page<User>>(`/users?page=${page}&page_size=${pageSize}`);
}

export function updateMyProfile(payload: { name?: string; email?: string }) {
  return apiFetch<User>("/users/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function changePassword(currentPassword: string, newPassword: string) {
  return apiFetch<void>("/users/me/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export function updateUser(id: string, payload: { role?: User["role"]; is_active?: boolean }) {
  return apiFetch<User>(`/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteUser(id: string) {
  return apiFetch<void>(`/users/${id}`, {
    method: "DELETE",
  });
}
