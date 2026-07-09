import { apiFetch } from "./client";
import type { Page } from "./users";

export type Project = {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  is_archived: boolean;
  scan_count: number;
  last_scan_at: string | null;
  created_at: string;
  updated_at: string;
  my_role: "owner" | "collaborator" | "admin";
};

export function listProjects(page = 1, pageSize = 20) {
  return apiFetch<Page<Project>>(`/projects?page=${page}&page_size=${pageSize}`);
}

export function getProject(id: string) {
  return apiFetch<Project>(`/projects/${id}`);
}

export function createProject(input: { name: string; description?: string }) {
  return apiFetch<Project>("/projects", { method: "POST", body: JSON.stringify(input) });
}

export function updateProject(
  id: string,
  patch: { name?: string; description?: string; is_archived?: boolean }
) {
  return apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteProject(id: string) {
  return apiFetch<void>(`/projects/${id}`, { method: "DELETE" });
}
