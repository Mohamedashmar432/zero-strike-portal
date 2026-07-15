import { apiFetch } from "./client";

export type ProjectMember = {
  id: string;
  project_id: string;
  user_id: string | null;
  invited_email: string;
  name: string | null;
  role: "owner" | "collaborator";
  status: "pending" | "accepted";
  invited_by: string;
  invited_at: string;
  accepted_at: string | null;
};

export function listMembers(projectId: string) {
  return apiFetch<ProjectMember[]>(`/projects/${projectId}/members`);
}

export function inviteMember(projectId: string, email: string) {
  return apiFetch<ProjectMember>(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function removeMember(projectId: string, memberId: string) {
  return apiFetch<void>(`/projects/${projectId}/members/${memberId}`, { method: "DELETE" });
}

export function updateMemberRole(projectId: string, memberId: string, role: "owner" | "collaborator") {
  return apiFetch<ProjectMember>(`/projects/${projectId}/members/${memberId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}
