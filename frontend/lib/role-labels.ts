const ROLE_LABELS: Record<string, string> = {
  admin: "Portal Admin",
  owner: "Project Admin",
  collaborator: "Member",
  user: "Normal User",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
