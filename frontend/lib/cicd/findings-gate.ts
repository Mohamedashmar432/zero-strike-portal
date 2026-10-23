/** Indents each line of a shell script so it sits under a YAML `|` block scalar. */
const block = (lines: string[], indent: number) => lines.map((l) => " ".repeat(indent) + l);

export const FINDINGS_MSG = "thinkShield: $crit critical and $high high severity findings. See the thinkShield portal.";

/**
 * The severity gate shared by every CI snippet: counts critical/high findings in the JSON report,
 * runs `warn` whenever there are any, exits 1 when they trip ZEROSTRIKE_FAIL_ON, and otherwise
 * runs `soft`. `fallback` applies when ZEROSTRIKE_FAIL_ON is unset (the snippet's chosen gate, so
 * deleting the env line does not silently loosen it). An unrecognised value is treated as "none".
 */
export function findingsGateLines(
  reportFile: string,
  warn: string[],
  soft: string[] = [],
  fallback: string = "none"
): string[] {
  return [
    // One "Severity" line per finding at this indent, so this does not count nested fields.
    `crit=$(grep -c '^      "Severity": "critical"' ${reportFile} || true)`,
    `high=$(grep -c '^      "Severity": "high"' ${reportFile} || true)`,
    "crit=${crit:-0}",
    "high=${high:-0}",
    'if [ "$crit" -gt 0 ] || [ "$high" -gt 0 ]; then',
    `  msg="${FINDINGS_MSG}"`,
    ...block(warn, 2),
    `  case "\${ZEROSTRIKE_FAIL_ON:-${fallback}}" in`,
    "    critical) blocking=$crit ;;",
    "    high) blocking=$((crit + high)) ;;",
    "    *) blocking=0 ;;",
    "  esac",
    '  if [ "$blocking" -gt 0 ]; then',
    '    echo "thinkShield: failing the pipeline (ZEROSTRIKE_FAIL_ON=$ZEROSTRIKE_FAIL_ON, $blocking blocking)"',
    "    exit 1",
    "  fi",
    ...block(soft, 2),
    "fi",
  ];
}
