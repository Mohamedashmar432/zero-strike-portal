"""Human-readable titles for the OWASP Top 10 category codes the Go scanner emits.

The scanner's rule YAML corpus tags findings with codes like "A05:2025" (see the sibling
zero-strike-code-scanner repo, internal/rules/data/**/*.yaml) but defines no titles
anywhere — these are the standard, current OWASP Top 10 category names, mapped 1:1 by
position onto those codes.
"""

OWASP_TOP_10: dict[str, str] = {
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
}

# Stable A01..A10 order for chart x-axes / summary responses.
OWASP_CODES_ORDERED: list[str] = list(OWASP_TOP_10)
