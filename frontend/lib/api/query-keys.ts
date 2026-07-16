/**
 * Centralized TanStack Query key builders. Ad hoc inline arrays drift -- e.g. two files
 * independently building ["projects", projectId, "repos"] -- which silently breaks cache
 * invalidation when only one of the copies gets updated. Use these instead of typing key
 * arrays by hand (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md, G12).
 */
export const queryKeys = {
  admin: {
    auditLogs: () => ["admin", "audit-logs"] as const,
    scannerStatus: () => ["admin", "scanner-status"] as const,
    users: (page?: number) =>
      page === undefined ? (["admin", "users"] as const) : (["admin", "users", page] as const),
  },
  dashboard: {
    stats: () => ["dashboard", "stats"] as const,
  },
  projects: {
    all: () => ["projects"] as const,
    stats: () => ["projects", "stats"] as const,
    detail: (projectId: string) => ["projects", projectId] as const,
    members: (projectId: string) => ["projects", projectId, "members"] as const,
    scans: (projectId: string) => ["projects", projectId, "scans"] as const,
    repos: (projectId: string) => ["projects", projectId, "repos"] as const,
    apiKeys: (projectId: string) => ["projects", projectId, "apiKeys"] as const,
    owaspSummary: (projectId: string, projectRepoId: string) =>
      ["projects", projectId, "owasp-summary", projectRepoId] as const,
    repoScanHistory: (projectId: string, repoId: string) =>
      ["projects", projectId, "repos", repoId, "scan-history"] as const,
  },
  scans: {
    detail: (scanId: string) => ["scans", scanId] as const,
    report: (scanId: string) => ["scans", scanId, "report"] as const,
    findings: (
      scanId: string,
      filters: { severity?: string; kind?: string; owasp?: string; priority?: string }
    ) =>
      [
        "scans",
        scanId,
        "findings",
        filters.severity ?? "",
        filters.kind ?? "",
        filters.owasp ?? "",
        filters.priority ?? "",
      ] as const,
  },
  repoCredentials: {
    all: () => ["repo-credentials"] as const,
    repos: (credentialId: string, query: string) =>
      ["repo-credentials", credentialId, "repos", query] as const,
    branches: (credentialId: string, repoId: string) =>
      ["repo-credentials", credentialId, "branches", repoId] as const,
  },
  settings: {
    reportTemplate: () => ["settings", "report-template"] as const,
  },
};
