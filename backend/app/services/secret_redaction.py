"""Best-effort secret redaction for repo file content before it is placed in an LLM prompt
(see docs/AI_AUTOFIX_DESIGN.md, concern #2). Runs on every file-bearing remediation tool
result. Replaces matched secrets with a placeholder while PRESERVING LINE COUNT, so excerpt
line numbers the agent reasons about stay truthful.

This is a defense-in-depth pass, not a guarantee: high-precision patterns for the common
credential shapes + high-entropy assignment values, plus deterministic redaction of any line
the scanner already flagged as a secret. Residual risk is documented; sensitive repos should
prefer a self-hosted provider.
"""

import math
import re

PLACEHOLDER = "«REDACTED:SECRET»"

# High-precision patterns for well-known credential shapes. Deliberately narrow to avoid
# shredding ordinary code.
_PATTERNS: list[re.Pattern] = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub personal access token
    re.compile(r"gho_[A-Za-z0-9]{36}"),  # GitHub OAuth token
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),  # GitHub fine-grained PAT
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),  # GitLab PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style secret key
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),  # PEM private-key header
    re.compile(r"[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s:@/]+@", re.IGNORECASE),  # user:pass@host in URL
]

# Assignment of a secret-looking key to a long, high-entropy literal:  API_KEY = "…"
_ASSIGN = re.compile(
    r"""(?ix)
    \b(\w*(?:secret|token|passwd|password|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)\w*)
    \s*[:=]\s*
    (['"]?)([A-Za-z0-9+/_\-=.]{16,})(['"]?)
    """
)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _redact_line(line: str) -> str:
    for pat in _PATTERNS:
        line = pat.sub(PLACEHOLDER, line)

    def _assign_sub(m: re.Match) -> str:
        value = m.group(3)
        # Only redact the value if it actually looks random (avoids nuking e.g. api_key = "default").
        if _shannon_entropy(value) >= 3.5 or len(value) >= 32:
            return f"{m.group(1)}={m.group(2)}{PLACEHOLDER}{m.group(4)}"
        return m.group(0)

    return _ASSIGN.sub(_assign_sub, line)


def redact(text: str, known_secret_lines: set[int] | None = None) -> str:
    """Redact secrets in `text`, preserving line count. `known_secret_lines` are 1-based line
    numbers the scanner already flagged (Finding.kind == "secret") -- those whole lines are
    blanked deterministically regardless of pattern match."""
    known = known_secret_lines or set()
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if i in known:
            out.append(PLACEHOLDER)
        else:
            out.append(_redact_line(line))
    result = "\n".join(out)
    # Preserve a trailing newline if the input had one (splitlines drops it).
    if text.endswith("\n"):
        result += "\n"
    return result
