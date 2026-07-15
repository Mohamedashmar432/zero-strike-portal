// Human-readable titles for the OWASP Top 10 category codes the scanner emits
// (A01:2025..A10:2025) — mirrors backend/app/core/owasp.py. No official "2025" list is
// published anywhere; these are the standard, current OWASP Top 10 category names.
export const OWASP_TITLES: Record<string, string> = {
  "A01:2025": "Broken Access Control",
  "A02:2025": "Cryptographic Failures",
  "A03:2025": "Injection",
  "A04:2025": "Insecure Design",
  "A05:2025": "Security Misconfiguration",
  "A06:2025": "Vulnerable and Outdated Components",
  "A07:2025": "Identification and Authentication Failures",
  "A08:2025": "Software and Data Integrity Failures",
  "A09:2025": "Security Logging and Monitoring Failures",
  "A10:2025": "Server-Side Request Forgery",
};

export const OWASP_CODES_ORDERED = Object.keys(OWASP_TITLES);

export type OwaspCategoryCount = { code: string; title: string; count: number };

// All 10 categories, always present (0-filled) — a scan/project's by_owasp response may
// omit categories with no findings, but the chart should never silently truncate.
export function owaspChartData(byOwasp: Record<string, number> | undefined): OwaspCategoryCount[] {
  return OWASP_CODES_ORDERED.map((code) => ({
    code,
    title: OWASP_TITLES[code] ?? code,
    count: byOwasp?.[code] ?? 0,
  }));
}
