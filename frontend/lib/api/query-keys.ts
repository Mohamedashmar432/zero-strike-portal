/**
 * Centralized TanStack Query key builders. Ad hoc inline arrays drift -- e.g. two files
 * independently building ["projects", projectId, "repos"] -- which silently breaks cache
 * invalidation when only one of the copies gets updated. Use these instead of typing key
 * arrays by hand (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md, G12).
 */
export const queryKeys = {
  admin: {
    auditLogs: () => ["admin", "audit-logs"] as const,
    dataStats: (projectId?: string) => ["admin", "data-stats", projectId ?? ""] as const,
    scannerStatus: () => ["admin", "scanner-status"] as const,
    autoFixQuotaRequests: (status?: string) =>
      status === undefined
        ? (["admin", "auto-fix-quota-requests"] as const)
        : (["admin", "auto-fix-quota-requests", status] as const),
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
    scanActivity: (projectId: string) => ["projects", projectId, "scan-activity"] as const,
    aiUsage: (projectId: string) => ["projects", projectId, "ai-usage"] as const,
    aiProviders: (projectId: string) => ["projects", projectId, "ai-provider"] as const,
    aiAnalytics: (projectId: string, days: number) =>
      ["projects", projectId, "ai-analytics", days] as const,
    aiEvents: (projectId: string, filters: Record<string, unknown>) =>
      ["projects", projectId, "ai-events", filters] as const,
  },
  scans: {
    detail: (scanId: string) => ["scans", scanId] as const,
    report: (scanId: string) => ["scans", scanId, "report"] as const,
    findings: (
      scanId: string,
      filters: {
        severity?: string;
        kind?: string;
        owasp?: string;
        priority?: string;
        page?: number;
        pageSize?: number;
      }
    ) =>
      [
        "scans",
        scanId,
        "findings",
        filters.severity ?? "",
        filters.kind ?? "",
        filters.owasp ?? "",
        filters.priority ?? "",
        filters.page ?? 1,
        filters.pageSize ?? 15,
      ] as const,
  },
  ai: {
    providers: {
      all: () => ["ai", "providers"] as const,
    },
    // Scoped: BYOK makes the answer per-project, so a project's status must not share a cache
    // entry with the portal-level one.
    status: (projectId?: string) => ["ai", "status", projectId ?? ""] as const,
    settings: () => ["ai", "settings"] as const,
    portalAnalytics: (days: number, projectId?: string) =>
      ["ai", "portal-analytics", days, projectId ?? ""] as const,
    portalEvents: (filters: Record<string, unknown>) => ["ai", "portal-events", filters] as const,
    findingInsight: (findingId: string) => ["ai", "finding", findingId] as const,
    scanInsight: (scanId: string) => ["ai", "scan", scanId] as const,
    autofix: {
      scan: (scanId: string) => ["ai", "autofix", "scan", scanId] as const,
      finding: (findingId: string) => ["ai", "autofix", "finding", findingId] as const,
      proposal: (proposalId: string) => ["ai", "autofix", "proposal", proposalId] as const,
      projectList: (projectId: string) => ["ai", "autofix", "project", projectId] as const,
      conversation: (proposalId: string) => ["ai", "autofix", "conversation", proposalId] as const,
      // Per-scan auto-fix allowance, and the request queue behind it.
      quota: (scanId: string) => ["ai", "autofix", "quota", scanId] as const,
      quotaRequests: (scanId: string) => ["ai", "autofix", "quota-requests", scanId] as const,
      comments: (findingId: string) => ["ai", "autofix", "comments", findingId] as const,
      commentSummary: (scanId: string) => ["ai", "autofix", "commentSummary", scanId] as const,
      activity: (scanId: string) => ["ai", "autofix", "activity", scanId] as const,
      settings: () => ["ai", "autofix", "settings"] as const,
    },
  },
  compliance: {
    frameworks: () => ["compliance", "frameworks"] as const,
    projectAudits: (projectId: string) => ["compliance", "project", projectId] as const,
    audit: (auditId: string) => ["compliance", "audit", auditId] as const,
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
