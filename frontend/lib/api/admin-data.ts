import { apiFetch } from "./client";

export type CollectionCount = { name: string; count: number };

export type CategoryStats = {
  key: string;
  label: string;
  description: string;
  destructive: boolean;
  implies: string[];
  total: number;
  collections: CollectionCount[];
};

export type DataStats = {
  project_id: string | null;
  categories: CategoryStats[];
};

export type PurgeResult = {
  categories: string[];
  deleted: Record<string, number>;
  total_deleted: number;
};

export function getDataStats(projectId?: string) {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiFetch<DataStats>(`/admin/data/stats${qs}`);
}

export function purgeData(categories: string[], projectId?: string) {
  return apiFetch<PurgeResult>("/admin/data/purge", {
    method: "POST",
    body: JSON.stringify({ categories, project_id: projectId ?? null, confirm: "DELETE" }),
  });
}

export function reapStuckScans() {
  return apiFetch<{ reaped: boolean }>("/admin/data/reap-stuck-scans", { method: "POST" });
}
