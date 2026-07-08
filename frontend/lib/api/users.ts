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

export function updateMyProfile(name: string) {
  return apiFetch<User>("/users/me", {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}
