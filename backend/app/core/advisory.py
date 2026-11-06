"""Pure advisory logic for live dependency alerts (docs/LIVE_DEPENDENCY_ALERTS.md section 5).

No I/O, no Mongo, no clock: every function takes what it needs, so the rules that decide whether an
advisory is new, how bad it is, and what the alert says are unit-tested without a feed or a database.

`representative_id`, `sca_fingerprint` and `cvss3_base_score` are ports of the Go scanner
(internal/scanner/sca/osv.go, internal/findings/builder.go). They must agree with it exactly: the
fingerprint is how an admin-accepted exemption recognises the same dependency finding, and the severity
is what a CI gate would have decided had the scanner seen the advisory.
"""

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# The ecosystems the Go scanner parses manifests for (internal/scanner/sca).
SUPPORTED_ECOSYSTEMS = ("npm", "PyPI", "Go", "Maven", "NuGet")

SEVERITIES = ("critical", "high", "medium", "low")
_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_PEP503 = re.compile(r"[-_.]+")

_MAX_SUMMARY = 200
_MAX_FIXED = 3
_MAX_FACT_ADVISORIES = 5
_MAX_IMPACT = 140  # the advisory's one-line summary, as shown in an alert fact


# --- the feed index ---------------------------------------------------------------------------


def _parse_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_modified_csv(text: str, *, drop_partial_tail: bool) -> list[tuple[datetime, str]]:
    """`<RFC3339 modified>,<ID>` rows in file order (newest first). A Range read can end mid-line, so
    with `drop_partial_tail` a final line that has no newline is discarded rather than mis-parsed as a
    row with a truncated id. Malformed lines are skipped."""
    lines = text.split("\n")
    if drop_partial_tail and lines and not text.endswith("\n"):
        lines = lines[:-1]
    rows: list[tuple[datetime, str]] = []
    for line in lines:
        stamp, sep, advisory_id = line.strip().partition(",")
        modified = _parse_time(stamp) if sep else None
        if modified is None or not advisory_id.strip():
            continue
        rows.append((modified, advisory_id.strip()))
    return rows


# --- identity ---------------------------------------------------------------------------------


def normalize_package_name(ecosystem: str, name: str) -> str:
    """Lowercase; PyPI additionally collapses runs of - _ . to one "-" (PEP 503). Same as the scanner."""
    name = (name or "").lower()
    return _PEP503.sub("-", name) if ecosystem == "PyPI" else name


def dep_key(ecosystem: str, name: str) -> str:
    return f"{ecosystem}|{normalize_package_name(ecosystem, name)}"


def representative_id(ids: list[str] | tuple[str, ...]) -> str:
    """The id an advisory is known by: a GHSA if there is one (it carries the reviewed severity), else the
    lexicographically smallest. Deterministic so the fingerprint built from it is stable across runs."""
    ordered = sorted(ids)
    if not ordered:
        raise ValueError("representative_id needs at least one id")
    for advisory_id in ordered:
        if advisory_id.startswith("GHSA-"):
            return advisory_id
    return ordered[0]


def sca_fingerprint(ecosystem: str, package: str, primary_id: str) -> str:
    """sha256("<ecosystem>|<package>|<primary id>")[:16] -- findings.BuildDependencyFinding. `package` is
    the name as the manifest spells it (not normalised), exactly what the scanner hashed."""
    return hashlib.sha256(f"{ecosystem}|{package}|{primary_id}".encode()).hexdigest()[:16]


# --- severity ---------------------------------------------------------------------------------

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.5}


def _round_up1(x: float) -> float:
    """CVSS v3.1 Roundup, on integers so 4.000000001 does not climb a step (osv.go roundUp1). Go's
    math.Round is half-away-from-zero, so floor(x + 0.5) here rather than Python's banker's round()."""
    n = math.floor(x * 100000 + 0.5)
    if n % 10000 == 0:
        return n / 100000
    return (n // 10000 + 1) / 10


def cvss3_base_score(vector: str) -> float | None:
    """CVSS v3.0/v3.1 base score from its vector string, or None when it is not a complete, valid v3 base
    vector (osv.go cvss3BaseScore returns ok=false)."""
    parts = (vector or "").split("/")
    if not parts or not parts[0].startswith("CVSS:3."):
        return None
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        key, sep, value = part.partition(":")
        if not sep:
            return None
        metrics[key] = value
    scope = metrics.get("S")
    if scope not in ("U", "C"):
        return None
    changed = scope == "C"
    pr_table = _PR_CHANGED if changed else _PR_UNCHANGED
    weights = (
        _AV.get(metrics.get("AV", "")),
        _AC.get(metrics.get("AC", "")),
        pr_table.get(metrics.get("PR", "")),
        _UI.get(metrics.get("UI", "")),
        _CIA.get(metrics.get("C", "")),
        _CIA.get(metrics.get("I", "")),
        _CIA.get(metrics.get("A", "")),
    )
    if any(w is None for w in weights):
        return None
    av, ac, pr, ui, c, i, a = weights
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (iss - 0.029) - 3.25 * math.pow(iss - 0.02, 15) if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * av * ac * pr * ui
    if changed:
        return _round_up1(min(1.08 * (impact + exploitability), 10))
    return _round_up1(min(impact + exploitability, 10))


def _severity_from_score(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"  # the scanner calls a 0.0 "info"; an alert has no such tier


def is_malicious(record: dict) -> bool:
    """A MAL-* report (OSV's malicious-packages feed), by its own id, an alias, or its origins."""
    ids = [record.get("id") or "", *(record.get("aliases") or [])]
    if any(isinstance(i, str) and i.startswith("MAL-") for i in ids):
        return True
    origins = (record.get("database_specific") or {}).get("malicious-packages-origins")
    return bool(origins)


def derive_severity(record: dict) -> tuple[str, float | None]:
    """(severity, cvss score if one was computed). Order, as in the scanner: a malicious package is
    critical; else the curated label (GitHub's reviewed severity); else the highest CVSS v3 base score
    over the record and its affected entries; else medium (a v2/v4 vector alone cannot be scored here)."""
    if is_malicious(record):
        return "critical", None
    label = str((record.get("database_specific") or {}).get("severity") or "").upper()
    label_map = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "MEDIUM": "medium", "LOW": "low"}
    best: float | None = None
    vectors = list(record.get("severity") or [])
    for entry in record.get("affected") or []:
        vectors.extend(entry.get("severity") or [])
    for vector in vectors:
        if not isinstance(vector, dict) or vector.get("type") != "CVSS_V3":
            continue
        score = cvss3_base_score(str(vector.get("score") or ""))
        if score is not None and (best is None or score > best):
            best = score
    if label in label_map:
        return label_map[label], best
    if best is not None:
        return _severity_from_score(best), best
    return "medium", None


def severity_meets(severity: str, minimum: str | None) -> bool:
    """Whether `severity` is at least `minimum`. "off" (or anything unknown) never meets."""
    if minimum not in _RANK or severity not in _RANK:
        return False
    return _RANK[severity] >= _RANK[minimum]


def stricter(a: str | None, b: str | None) -> str:
    """The stricter of two minimum severities, where "off" is the strictest and None defers to the other.
    A project override goes through this, so it can tighten the workspace floor but never lower it."""
    if a is None and b is None:
        raise ValueError("stricter needs at least one value")
    if a is None:
        return b  # type: ignore[return-value]
    if b is None:
        return a

    def weight(v: str) -> int:
        return 5 if v == "off" else _RANK.get(v, 0)

    return a if weight(a) >= weight(b) else b


# --- the advisory -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AffectedPkg:
    ecosystem: str
    name: str
    name_norm: str
    # OSV's explicit affected-versions list; ranges are never evaluated here (OSV's own matcher does that).
    versions: frozenset[str] = frozenset()
    fixed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Advisory:
    id: str  # representative id
    ids: tuple[str, ...]  # representative first, then every other id and alias, sorted
    summary: str
    severity: str
    cvss_score: float | None
    malicious: bool
    published: datetime | None
    modified: datetime | None
    withdrawn: bool
    affected: tuple[AffectedPkg, ...] = ()


def normalize_advisory(record: dict, ecosystem: str) -> Advisory:
    """An OSV record -> the fields alerting needs. Only `affected` entries in `ecosystem` are kept."""
    raw_id = str(record.get("id") or "")
    aliases = [a for a in (record.get("aliases") or []) if isinstance(a, str) and a]
    all_ids = [i for i in dict.fromkeys([raw_id, *aliases]) if i]
    rep = representative_id(all_ids) if all_ids else raw_id
    ids = (rep, *sorted(i for i in all_ids if i != rep))
    severity, score = derive_severity(record)
    affected: list[AffectedPkg] = []
    for entry in record.get("affected") or []:
        pkg = entry.get("package") or {}
        name = pkg.get("name")
        if not name or pkg.get("ecosystem") != ecosystem:
            continue
        fixed: list[str] = []
        for rng in entry.get("ranges") or []:
            if rng.get("type") == "GIT":
                continue
            for event in rng.get("events") or []:
                value = event.get("fixed")
                if value and value not in fixed:
                    fixed.append(value)
        affected.append(
            AffectedPkg(
                ecosystem=ecosystem,
                name=name,
                name_norm=normalize_package_name(ecosystem, name),
                versions=frozenset(str(v) for v in (entry.get("versions") or [])),
                fixed=tuple(fixed[:_MAX_FIXED]),
            )
        )
    return Advisory(
        id=rep,
        ids=ids,
        summary=str(record.get("summary") or "")[:_MAX_SUMMARY],
        severity=severity,
        cvss_score=score,
        malicious=is_malicious(record),
        published=_parse_time(record.get("published")),
        modified=_parse_time(record.get("modified")),
        withdrawn=bool(record.get("withdrawn")),
        affected=tuple(affected),
    )


def is_new(adv: Advisory, now: datetime, max_age: timedelta) -> bool:
    """Published inside the window and not withdrawn. `modified` is deliberately ignored: an old advisory
    being edited today is common and is the findings flow's business, not a new alert."""
    if adv.published is None or adv.withdrawn:
        return False
    return now - max_age <= adv.published <= now


# --- the alert --------------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertMessage:
    title: str
    text: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    link: str = ""
    notif_severity: str = "warning"  # error for critical/malicious, else warning


def _when(moment: datetime) -> str:
    moment = moment.astimezone(timezone.utc)
    return f"{moment.day} {moment:%b %Y %H:%M} UTC"


def _ago(moment: datetime, now: datetime) -> str:
    seconds = max(0, int((now - moment).total_seconds()))
    return f"{seconds // 3600}h ago" if seconds >= 3600 else f"{seconds // 60}m ago"


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _fact_for(row) -> tuple[str, str]:
    cve = next((i for i in row.advisory_ids if i.startswith("CVE-")), None)
    key = f"{row.advisory_id} · {cve}" if cve and cve != row.advisory_id else row.advisory_id
    if row.malicious:
        return key, f"MALICIOUS PACKAGE · remove {row.package} {row.version}"
    locations = list(row.locations)
    sev = row.severity.upper() + (f" {row.cvss_score:.1f}" if row.cvss_score is not None else "")
    fix = f"fix {row.fixed_versions[0]}" if row.fixed_versions else "no fix yet"
    parts = [sev, f"{row.package} {row.version} -> {fix}"]
    impact = " ".join((getattr(row, "summary", "") or "").split())
    if impact:
        parts.append(impact if len(impact) <= _MAX_IMPACT else impact[: _MAX_IMPACT - 3].rstrip() + "...")
    # No direct/transitive wording: the scanner's Direct flag is unreliable in every ecosystem (a real
    # npm lockfile reported 735 of 807 entries direct), so it is stored as raw data but never shown.
    manifest_part = next((m for loc in locations for m in loc.manifests), None)
    labels = list(dict.fromkeys(loc.repo_label for loc in locations if loc.repo_label))
    count = max(len(locations), 1)
    repos = f"{count} repo{'s' if count != 1 else ''}"
    if labels:
        repos += f": {', '.join(labels[:2])}" + (f" +{len(labels) - 2}" if len(labels) > 2 else "")
    parts.append(repos)
    if manifest_part:
        parts.append(manifest_part)
    return key, " · ".join(parts)


def build_alert(project_name: str, project_id: str, rows: list, now: datetime) -> AlertMessage:
    """The one grouped message a project gets per run. `rows` are ledger rows (LiveDependencyAlert, or any
    object with the same attributes): advisory_id, advisory_ids, summary, ecosystem, package, version, severity,
    cvss_score, malicious, published_at, fixed_versions and locations[repo_label, manifests, direct,
    inventory_scanned_at, git_commit]. Only the advisory's one-line summary is shown
    (truncated); its `details` text is never included: it is third-party prose that would land in a Teams channel unfiltered."""
    if not rows:
        raise ValueError("build_alert needs at least one row")
    ordered = sorted(
        rows,
        key=lambda r: (-_RANK.get(r.severity, 0), -_utc(r.published_at).timestamp()),
    )
    counts = {s: sum(r.severity == s for r in rows) for s in SEVERITIES}
    if len(rows) == 1:
        only = rows[0]
        title = f"{project_name}: new {only.severity.upper()} advisory in {only.package} {only.version}"
    else:
        breakdown = ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s])
        title = f"{project_name}: {len(rows)} new dependency advisories ({breakdown})"

    newest = max((_utc(r.published_at) for r in rows), default=now)
    scanned = [
        (_utc(loc.inventory_scanned_at), loc.git_commit)
        for r in rows
        for loc in r.locations
        if loc.inventory_scanned_at is not None
    ]
    lines = [
        f"Published {_when(newest)} ({_ago(newest, now)}) on OSV.dev. "
        "Your latest scan of this project uses an affected version."
    ]
    if scanned:
        when, commit = max(scanned, key=lambda s: s[0])
        lines.append(f"Inventory as of scan {when:%Y-%m-%d}" + (f", commit {commit[:7]}." if commit else "."))
    lines.append("Rescan to track it as a finding.")

    facts: list[tuple[str, str]] = [("Released", f"{_when(newest)} ({_ago(newest, now)})"), ("Project", project_name)]
    facts.extend(_fact_for(r) for r in ordered[:_MAX_FACT_ADVISORIES])
    if len(ordered) > _MAX_FACT_ADVISORIES:
        facts.append(("More", f"+{len(ordered) - _MAX_FACT_ADVISORIES} more in the project"))
    if len(rows) == 1:
        facts.append(("Details", f"https://osv.dev/vulnerability/{rows[0].advisory_id}"))

    hot = any(r.severity == "critical" or r.malicious for r in rows)
    return AlertMessage(
        title=title,
        text="\n".join(lines),
        facts=facts[:12],
        link=f"/projects/{project_id}?tab=overview&src=alert",
        notif_severity="error" if hot else "warning",
    )
