import { apiFetch } from "./client";
import type { ScanStatus } from "./scans";
import type { Page } from "./users";

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type FindingKind = "sast" | "secret" | "sca" | "config";

export type FindingLocation = {
  file: string;
  start_line: number | null;
  end_line: number | null;
  start_col: number | null;
  end_col: number | null;
};

export type Finding = {
  id: string;
  scan_id: string;
  project_id: string;
  finding_id: string | null;
  fingerprint: string | null;
  rule_id: string | null;
  rule_name: string | null;
  category: string | null;
  severity: Severity | null;
  confidence: string | null;
  message: string;
  location: FindingLocation;
  language: string | null;
  evidence: { snippet: string | null; start_line: number | null; end_line: number | null }[];
  cwe: string[];
  owasp: string[];
  references: string[];
  metadata: Record<string, string>;
  kind: FindingKind | null;
  secret: { detector_id: string | null; entropy: number | null; redacted: string | null } | null;
  dependency: {
    ecosystem: string | null;
    package: string | null;
    installed_version: string | null;
    vulnerable_range: string | null;
    fixed_version: string | null;
    advisory_ids: string[];
    manifest: string | null;
    direct: boolean | null;
  } | null;
  config: { framework: string | null; config_file: string | null; key: string | null } | null;
  rationale: string | null;
  remediation: string | null;
  taint_context: {
    source_var: string | null;
    source_expr: string | null;
    sink: string | null;
    path: FindingLocation[];
  } | null;
  created_at: string;
};

// Re-export so callers can `import { ScanStatus } from findings` if convenient.
export type { ScanStatus };

export function listFindings(
  scanId: string,
  opts: { severity?: Severity; kind?: FindingKind; page?: number; pageSize?: number } = {}
) {
  const params = new URLSearchParams();
  if (opts.severity) params.set("severity", opts.severity);
  if (opts.kind) params.set("kind", opts.kind);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return apiFetch<Page<Finding>>(`/scans/${scanId}/findings?${params.toString()}`);
}
