"""The scheduled Teams digest (docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 6).

Three separable pieces: `build_preview` gathers the numbers (async, reads Mongo), `build_card` turns
them into an Adaptive Card 1.5 `Table` (a pure function -- unit-tested against a fixture), and
`run_due` / `scheduler_loop` decide when to send. A send claims its period with one atomic
`find_one_and_update` on `DigestSettings.last_sent_for`, so a restart or a second replica can never
double-send.

Critical/High are *current exposure* (each repo's latest completed scan, via project_stats_service),
not a sum over every scan in the period. New CVE ids come from findings' advisory ids, which are OSV.dev
lookups made at scan time -- the portal holds no CVE feed, so the card never claims a feed date.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from pymongo import ReturnDocument

from app.core.config import settings
from app.models.digest_settings import DigestSettings
from app.models.finding import Finding
from app.models.project import Project
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.models.webhook_channel import WebhookChannel
from app.schemas.digest import (
    DigestPreview,
    DigestRow,
    DigestSendError,
    DigestSendResponse,
    DigestTotals,
    NewAdvisory,
    QuotaWarning,
    ScannerHealth,
    StaleProject,
)
from app.schemas.project_insights import CveRef, NewCves
from app.services import (
    audit_service,
    cloud_scan_quota_service,
    cloud_scan_service,
    project_insights_service,
    project_stats_service,
    scan_engine_service,
    webhook_channel_service,
)

logger = structlog.get_logger(__name__)

STALE_AFTER = timedelta(days=30)
QUOTA_WARN_FRACTION = 0.8
_SLOT_GRACE = timedelta(hours=6)  # a slot missed by more than this (portal was down) is skipped, not sent late
# The two OSV.dev endpoints the scanner itself calls at scan time (scanner: internal/scanner/sca/osv.go).
_OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
_OSV_PROBE_URL = "https://api.osv.dev/v1/vulns/GHSA-jfh8-c2jp-5v3q"
_OSV_BATCH_PROBE = {"queries": [{"package": {"name": "lodash", "ecosystem": "npm"}, "version": "4.17.20"}]}
# Teams refuses a message over ~28 KB (Power Automate reports RequestEntityTooLarge), and a Workflows
# webhook still answers 202 first, so an oversize card is accepted by the portal's POST and then never
# appears. That is why the digest is several small cards, not one: a project row costs ~1.2 KB, so 10 per
# card is ~13 KB. Workflows re-wraps each card in a larger, escaped message; _MAX_CARD_BYTES is the budget
# a test holds every card to.
_MAX_CARD_BYTES = 20_000
_ROWS_PER_CARD = 10
_MAX_PROJECT_CARDS = 6  # 60 projects; the summary card names how many were left out (totals cover them)
_MAX_ADVISORIES = 8
# Workflows runs each post as its own flow, so posts sent back to back can land out of order; the cards
# are also numbered "n/N" so a reader can still tell.
_CARD_GAP_SECONDS = 2.0
_RUNNER_LOOKBACK = timedelta(days=14)


# --- settings ---------------------------------------------------------------------------------


async def get_settings() -> DigestSettings:
    row = await DigestSettings.find_one()
    if row is None:
        row = DigestSettings()
        await row.insert()
    return row


# --- gathering --------------------------------------------------------------------------------


@dataclass(frozen=True)
class OsvProbe:
    """Round-trip in ms of each OSV.dev endpoint the scanner calls; None = unreachable or a 5xx."""

    batch_ms: int | None
    vuln_ms: int | None
    checked_at: datetime

    @property
    def reachable(self) -> bool:
        return self.batch_ms is not None and self.vuln_ms is not None


async def _probe_osv_live(transport: httpx.AsyncBaseTransport | None = None) -> OsvProbe:
    async def timed(client: httpx.AsyncClient, method: str, url: str, **kw) -> int | None:
        started = time.perf_counter()
        try:
            resp = await client.request(method, url, **kw)
        except Exception:
            return None
        return None if resp.status_code >= 500 else round((time.perf_counter() - started) * 1000)

    async with httpx.AsyncClient(timeout=3, follow_redirects=False, transport=transport) as client:
        batch, vuln = await asyncio.gather(
            timed(client, "POST", _OSV_BATCH_URL, json=_OSV_BATCH_PROBE), timed(client, "GET", _OSV_PROBE_URL)
        )
    return OsvProbe(batch_ms=batch, vuln_ms=vuln, checked_at=datetime.now(timezone.utc))


async def _probe_osv() -> OsvProbe:
    """Whether OSV.dev answers from this server, per endpoint. Any non-5xx HTTP response counts as
    reachable; a network failure or timeout does not. Tests replace this -- they never touch the network."""
    return await _probe_osv_live()


def _norm_version(version: str | None) -> str:
    return (version or "").strip().lstrip("vV")


async def _outdated_ci_runners(latest: str | None) -> int:
    """CI runners (project + hostname) whose most recent scan reported a scanner older than -- or at
    least different from -- the newest published binary."""
    if not latest:
        return 0
    pipeline = [
        {
            "$match": {
                "scan_type": "cicd",
                "scanner_version": {"$ne": None},
                "created_at": {"$gte": datetime.now(timezone.utc) - _RUNNER_LOOKBACK},
            }
        },
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": {"p": "$project_id", "h": "$hostname"}, "v": {"$first": "$scanner_version"}}},
    ]
    # Motor's aggregate() is a cursor, not awaitable (see dashboard_service._severity_groups).
    rows = await Scan.get_pymongo_collection().aggregate(pipeline).to_list(length=None)
    return sum(1 for row in rows if _norm_version(row["v"]) != _norm_version(latest))


def _advisory_summary(found: list[tuple[str, str, datetime]]) -> list[NewAdvisory]:
    """One row per advisory id across projects: its worst severity and how many projects first reported it."""
    by_id: dict[str, tuple[str, int]] = {}
    for advisory_id, severity, _first in found:
        worst, projects = by_id.get(advisory_id, ("", 0))
        by_id[advisory_id] = (max(worst, severity, key=lambda v: _SEV_RANK.get(v, 0)), projects + 1)
    rows = [NewAdvisory(id=i, severity=sev or "info", projects=n) for i, (sev, n) in by_id.items()]
    return sorted(rows, key=lambda a: (-_SEV_RANK.get(a.severity, 0), -a.projects, a.id))


async def _last_dependency_scan_at() -> datetime | None:
    row = await Finding.find(Finding.kind == "sca").sort("-created_at").first_or_none()
    return _utc(row.created_at) if row else None


async def _scanner_health(advisories: list[NewAdvisory]) -> ScannerHealth:
    newest = await ScannerBinary.find_all().sort("-uploaded_at").first_or_none()
    latest = newest.version if newest else None
    pack = await scan_engine_service.active_pack()
    osv = await _probe_osv()
    return ScannerHealth(
        engine_available=cloud_scan_service.scanner_available(),
        backend_scanner_version=settings.scanner_build_ref or "unknown",
        latest_binary_version=latest,
        outdated_ci_runners=await _outdated_ci_runners(latest),
        rule_pack_version=pack.version if pack else None,
        rule_count=len(pack.custom_rules) if pack else 0,
        osv_reachable=osv.reachable,
        osv_batch_ms=osv.batch_ms,
        osv_vuln_ms=osv.vuln_ms,
        osv_checked_at=osv.checked_at,
        last_dependency_scan_at=await _last_dependency_scan_at(),
        new_cve_ids=[a.id for a in advisories[:5]],
        new_advisories=advisories[:_MAX_ADVISORIES],
        new_advisory_count=len(advisories),
    )


async def build_preview(digest: DigestSettings, now: datetime | None = None) -> DigestPreview:
    end = now or datetime.now(timezone.utc)
    start = end - (timedelta(days=7) if digest.frequency == "weekly" else timedelta(days=1))

    projects = [p for p in await Project.find_all().sort(-Project.id).to_list() if not p.is_archived]
    if digest.project_ids:
        chosen = set(digest.project_ids)
        projects = [p for p in projects if str(p.id) in chosen]
    pids = [str(p.id) for p in projects]

    counts = await project_insights_service.scan_counts(start, end) if pids else {}
    quotas = await cloud_scan_quota_service.usage_many(projects) if pids else {}
    cves = await project_insights_service.new_cves(pids, start, end) if pids else {}

    severity: dict = {}
    scan_ids_by_project: dict[str, list[str]] = {}
    if pids:
        posture = await project_stats_service.current_posture_scan_ids(pids)
        scan_ids_by_project = posture.scan_ids_by_project
        severity = await project_stats_service.get_severity_by_scan_ids(posture.all_scan_ids)

    rows: list[DigestRow] = []
    for p in projects:
        pid = str(p.id)
        mine = counts.get(pid)
        crit = sum(severity[s].critical for s in scan_ids_by_project.get(pid, []) if s in severity)
        high = sum(severity[s].high for s in scan_ids_by_project.get(pid, []) if s in severity)
        rows.append(
            DigestRow(
                project_id=pid,
                name=p.name,
                pipeline_runs=mine["cicd"].total if mine else 0,
                pipeline_failed=mine["cicd"].failed if mine else 0,
                cloud_scans=mine["cloud"].total if mine else 0,
                cloud_failed=mine["cloud"].failed if mine else 0,
                critical=crit,
                high=high,
                quota_used=quotas[pid].used,
                quota_limit=quotas[pid].limit,
                new_cves=project_insights_service.new_cves_block(cves.get(pid, [])),
            )
        )

    all_new = sorted((c for found in cves.values() for c in found), key=lambda t: t[2], reverse=True)
    totals = DigestTotals(
        **{
            f: sum(getattr(r, f) for r in rows)
            for f in (
                "pipeline_runs",
                "pipeline_failed",
                "cloud_scans",
                "cloud_failed",
                "critical",
                "high",
                "quota_used",
                "quota_limit",
            )
        },
        new_cves=NewCves(count=len(all_new), latest=[CveRef(id=a, severity=s) for a, s, _ in all_new[:2]]),
    )

    stale: list[StaleProject] = []
    if digest.include_stale_projects:
        for p in projects:
            reference = p.last_scan_at or p.created_at
            if _utc(reference) < end - STALE_AFTER:
                stale.append(StaleProject(project_id=str(p.id), name=p.name, last_scan_at=_utc(p.last_scan_at)))
    warnings = [
        QuotaWarning(project_id=r.project_id, name=r.name, used=r.quota_used, limit=r.quota_limit)
        for r in rows
        if r.quota_limit > 0 and r.quota_used >= QUOTA_WARN_FRACTION * r.quota_limit
    ]
    return DigestPreview(
        period_start=start,
        period_end=end,
        rows=rows,
        totals=totals,
        scanner=await _scanner_health(_advisory_summary(all_new)),
        stale_projects=stale,
        quota_warnings=warnings,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- the card (pure) --------------------------------------------------------------------------

_SEV_LETTER = {"critical": "C", "high": "H", "medium": "M", "low": "L", "info": "I"}
_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
# Column set, not the 1.5 Table element: legacy Office 365 connector webhooks (webhook.office.com)
# render Adaptive Cards only up to 1.4 and drop a Table without an error, so the rows vanished.
_COLUMNS = ("Project", "Pipeline", "Cloud", "Critical", "High", "Quota", "New CVEs")
_WIDTHS = (30, 14, 14, 10, 10, 10, 22)
_CENTERED = {3, 4, 5}


def _text(value: str, *, bold: bool = False, color: str | None = None, center: bool = False) -> dict:
    block: dict = {"type": "TextBlock", "text": value, "wrap": True, "size": "Small"}
    if center:
        block["horizontalAlignment"] = "Center"
    if bold:
        block["weight"] = "Bolder"
    if color:
        block["color"] = color
    return block


def _grid_row(cells: list[dict], *, style: str | None = None, separator: bool = False) -> dict:
    row: dict = {
        "type": "ColumnSet",
        "spacing": "Small",
        "columns": [
            {"type": "Column", "width": w, "verticalContentAlignment": "Center", "items": [c]}
            for w, c in zip(_WIDTHS, cells)
        ],
    }
    if style:
        row["style"] = style
    if separator:
        row["separator"] = True
    return row


def _runs(total: int, failed: int) -> str:
    return f"{total} ({failed} failed)" if failed else str(total)


def _cves_text(cves: NewCves) -> str:
    if not cves.count:
        return "-"
    latest = ", ".join(f"{c.id} ({_SEV_LETTER.get(c.severity, '?')})" for c in cves.latest)
    return f"{cves.count}: {latest}"


def _quota_text(used: int, limit: int) -> str:
    return f"{used}/{limit}"


def _row_cells(name: str, r, cves: str, *, bold: bool = False) -> list[dict]:
    near_limit = r.quota_limit > 0 and r.quota_used >= r.quota_limit * 0.8
    return [
        _text(name, bold=True),
        _text(_runs(r.pipeline_runs, r.pipeline_failed), bold=bold, color="Attention" if r.pipeline_failed else None),
        _text(_runs(r.cloud_scans, r.cloud_failed), bold=bold, color="Attention" if r.cloud_failed else None),
        _text(str(r.critical), bold=True, color="Attention" if r.critical else None, center=True),
        _text(str(r.high), bold=True, color="Warning" if r.high else None, center=True),
        _text(_quota_text(r.quota_used, r.quota_limit), bold=bold, color="Warning" if near_limit else None, center=True),
        _text(cves, bold=bold, color="Attention" if cves != "-" else None),
    ]


def _kpi(label: str, value: int, color: str | None) -> dict:
    return {
        "type": "Column",
        "width": "stretch",
        "items": [
            {
                "type": "TextBlock",
                "text": str(value),
                "size": "ExtraLarge",
                "weight": "Bolder",
                "color": color or "Default",
                "horizontalAlignment": "Center",
            },
            {
                "type": "TextBlock",
                "text": label.upper(),
                "size": "Small",
                "isSubtle": True,
                "wrap": True,
                "horizontalAlignment": "Center",
                "spacing": "None",
            },
        ],
    }


def _rank(r) -> tuple:
    # Worst first: exposure, then failures, then activity -- the rows a reader must see are on top.
    return (r.critical, r.high, r.pipeline_failed + r.cloud_failed, r.pipeline_runs + r.cloud_scans)


@dataclass(frozen=True)
class _Part:
    label: str
    title: str
    subtitle: str | None
    body: list[dict]
    style: str = "emphasis"
    actions: list[dict] | None = None


def _envelope(part: _Part, index: int, total: int) -> dict:
    header = [
        {
            "type": "TextBlock",
            "text": f"THINKSHIELD · SECURITY DIGEST · {index}/{total} · {part.label}",
            "size": "Small",
            "weight": "Bolder",
            "isSubtle": True,
            "wrap": True,
        },
        {"type": "TextBlock", "text": part.title, "size": "Large", "weight": "Bolder", "spacing": "None", "wrap": True},
    ]
    if part.subtitle:
        header.append(
            {"type": "TextBlock", "text": part.subtitle, "size": "Small", "isSubtle": True, "spacing": "None", "wrap": True}
        )
    card: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": [{"type": "Container", "style": part.style, "bleed": True, "items": header}, *part.body],
    }
    if part.actions:
        card["actions"] = part.actions
    return card


def _note(text: str, *, spacing: str = "Small") -> dict:
    return {"type": "TextBlock", "text": text, "isSubtle": True, "size": "Small", "wrap": True, "spacing": spacing}


def _ms(value: int | None) -> str:
    return "NOT REACHABLE" if value is None else f"reachable, {value} ms"


def _health_part(preview: DigestPreview) -> _Part:
    s = preview.scanner
    ready = s.engine_available and s.osv_reachable
    engine = [
        ("Scan engine", "Available" if s.engine_available else "NOT AVAILABLE"),
        ("Scanner in backend", s.backend_scanner_version),
        ("Latest published binary", s.latest_binary_version or "None published"),
        ("CI runners on an older scanner", str(s.outdated_ci_runners)),
        ("Rule pack", f"v{s.rule_pack_version} ({s.rule_count} custom rules)" if s.rule_pack_version else "None published"),
    ]
    feed = [
        ("Source", "OSV.dev, queried live at scan time. The scanner keeps no local CVE database."),
        ("Batch lookup", _ms(s.osv_batch_ms)),
        ("Advisory lookup", _ms(s.osv_vuln_ms)),
        ("Checked", f"{s.osv_checked_at:%d %b %Y %H:%M} UTC" if s.osv_checked_at else "-"),
        (
            "Last dependency scan",
            f"{s.last_dependency_scan_at:%d %b %Y %H:%M} UTC" if s.last_dependency_scan_at else "None recorded",
        ),
    ]
    since = f"{preview.period_start:%d %b %H:%M} UTC"
    advisories: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"New advisories since {since}: {s.new_advisory_count}",
            "weight": "Bolder",
            "wrap": True,
        }
    ]
    if s.new_advisories:
        advisories += [
            {
                "type": "TextBlock",
                "text": f"- {a.id} ({a.severity}), {a.projects} project{'s' if a.projects != 1 else ''}",
                "wrap": True,
                "size": "Small",
                "spacing": "None",
                "color": "Attention" if a.severity in ("critical", "high") else "Default",
            }
            for a in s.new_advisories
        ]
        if s.new_advisory_count > len(s.new_advisories):
            advisories.append(_note(f"+ {s.new_advisory_count - len(s.new_advisories)} more advisories."))
    else:
        advisories.append(_note("No advisory was first reported by any project in this period.", spacing="None"))
    body = [
        {
            "type": "Container",
            "spacing": "Medium",
            "items": [
                {"type": "TextBlock", "text": "Scanner", "weight": "Bolder", "wrap": True},
                {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in engine]},
            ],
        },
        {
            "type": "Container",
            "spacing": "Medium",
            "separator": True,
            "items": [
                {"type": "TextBlock", "text": "CVE data (OSV.dev)", "weight": "Bolder", "wrap": True},
                {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in feed]},
            ],
        },
        {"type": "Container", "spacing": "Medium", "separator": True, "items": advisories},
    ]
    return _Part(
        "SCANNER HEALTH",
        "Scanner ready, CVE feed live" if ready else "Scanner NOT ready",
        f"{s.backend_scanner_version} · {s.new_advisory_count} new advisories in this period",
        body,
        style="good" if ready else "attention",
    )


def _project_parts(preview: DigestPreview) -> tuple[list[_Part], int]:
    """Project status cards, `_ROWS_PER_CARD` per card, worst exposure first; and how many projects
    did not fit in `_MAX_PROJECT_CARDS` (the summary card names them as left out)."""
    ordered = sorted(preview.rows, key=_rank, reverse=True)
    shown = ordered[: _ROWS_PER_CARD * _MAX_PROJECT_CARDS]
    parts: list[_Part] = []
    for start in range(0, len(shown), _ROWS_PER_CARD):
        chunk = shown[start : start + _ROWS_PER_CARD]
        body = [_grid_row([_text(c, bold=True, center=i in _CENTERED) for i, c in enumerate(_COLUMNS)], style="emphasis")]
        body += [_grid_row(_row_cells(r.name, r, _cves_text(r.new_cves)), separator=i > 0) for i, r in enumerate(chunk)]
        body.append(
            _note(
                "Pipeline and Cloud count runs in this period. Critical and High are current exposure "
                "(latest scan per repository).",
                spacing="Medium",
            )
        )
        parts.append(_Part("PROJECT STATUS", f"Projects {start + 1}-{start + len(chunk)} of {len(ordered)}", None, body))
    return parts, len(ordered) - len(shown)


def _summary_part(preview: DigestPreview, left_out: int, frontend_origin: str) -> _Part:
    t, s = preview.totals, preview.scanner
    end = preview.period_end
    period = f"{preview.period_start:%d %b %Y %H:%M} to {end:%d %b %Y %H:%M} UTC"
    ready = s.engine_available and s.osv_reachable
    body: list[dict] = [
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                _kpi("Pipeline runs", t.pipeline_runs, None),
                _kpi("Pipeline failed", t.pipeline_failed, "Attention" if t.pipeline_failed else None),
                _kpi("Cloud scans", t.cloud_scans, None),
                _kpi("Cloud failed", t.cloud_failed, "Attention" if t.cloud_failed else None),
                _kpi("Critical", t.critical, "Attention" if t.critical else None),
                _kpi("High", t.high, "Warning" if t.high else None),
            ],
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Projects", "value": str(len(preview.rows))},
                {
                    "title": "Scanner",
                    "value": f"{'Ready' if ready else 'NOT READY'} ({s.backend_scanner_version}), OSV.dev "
                    + ("live" if s.osv_reachable else "NOT REACHABLE"),
                },
                {"title": "New advisories", "value": str(s.new_advisory_count)},
            ],
        },
    ]
    if left_out:
        body.append(_note(f"{left_out} more projects were not listed on the project cards (totals include them)."))
    attention: list[str] = []
    if t.cloud_failed or t.pipeline_failed:
        attention.append(f"{t.pipeline_failed} pipeline run(s) and {t.cloud_failed} cloud scan(s) failed this period")
    if not ready:
        attention.append("The scanner or its CVE feed is not ready; see the scanner health card")
    if preview.quota_warnings:
        attention.append(
            "At 80% or more of cloud-scan quota: "
            + ", ".join(f"{w.name} ({w.used}/{w.limit})" for w in preview.quota_warnings[:10])
        )
    if preview.stale_projects:
        attention.append(
            "No scan in 30 days: "
            + ", ".join(p.name for p in preview.stale_projects[:10])
            + (f" and {len(preview.stale_projects) - 10} more" if len(preview.stale_projects) > 10 else "")
        )
    if attention:
        body.append(
            {
                "type": "Container",
                "spacing": "Medium",
                "style": "warning",
                "items": [
                    {"type": "TextBlock", "text": "Needs attention", "weight": "Bolder", "wrap": True},
                    *({"type": "TextBlock", "text": f"- {line}", "wrap": True, "spacing": "Small"} for line in attention),
                ],
            }
        )
    actions = (
        [{"type": "Action.OpenUrl", "title": "Open Control Panel", "url": f"{frontend_origin}/admin/control-panel"}]
        if frontend_origin
        else None
    )
    return _Part(
        "SUMMARY", f"Security digest, {end:%a %d %b %Y}", f"Updated {end:%H:%M} UTC · period {period}", body, actions=actions
    )


def build_cards(preview: DigestPreview, *, frontend_origin: str = "") -> list[dict]:
    """The digest as ordered Adaptive Cards 1.4: scanner health and CVE feed status, then project status
    (`_ROWS_PER_CARD` per card), then a dated summary. Pure: the same preview always yields the same
    cards. Totals always cover every project; only the project cards are capped."""
    project_parts, left_out = _project_parts(preview)
    parts = [_health_part(preview), *project_parts, _summary_part(preview, left_out, frontend_origin)]
    return [_envelope(part, i, len(parts)) for i, part in enumerate(parts, 1)]


# --- sending ----------------------------------------------------------------------------------


async def _post_cards(channel: WebhookChannel, cards: list[dict]) -> str | None:
    """Post the cards to one channel in order; the error text of the first failure, else None. Stops
    there: a digest missing its middle is worse than one that says which card it stopped at."""
    for i, card in enumerate(cards, 1):
        if i > 1:
            await asyncio.sleep(_CARD_GAP_SECONDS)
        ok, _status, error = await webhook_channel_service.send_card(channel, card)
        if not ok:
            return f"card {i} of {len(cards)}: {error or 'failed'}"
    return None


async def send_digest(digest: DigestSettings, *, now: datetime | None = None) -> DigestSendResponse:
    """Post the current digest to every enabled channel with `include_digest`. Never raises."""
    errors: list[DigestSendError] = []
    sent = 0
    card_count = 0
    try:
        channels = await WebhookChannel.find(
            WebhookChannel.enabled == True, WebhookChannel.include_digest == True  # noqa: E712
        ).to_list()
        if not channels:
            return DigestSendResponse(sent=0, errors=[])
        cards = build_cards(await build_preview(digest, now), frontend_origin=settings.frontend_origin)
        results = await asyncio.gather(*(_post_cards(c, cards) for c in channels))
        for channel, error in zip(channels, results):
            if error is None:
                sent += 1
            else:
                errors.append(DigestSendError(channel_id=str(channel.id), name=channel.name, error=error))
        card_count = len(cards)
    except Exception as exc:
        logger.warning("digest send failed", exc_info=True)
        errors.append(DigestSendError(channel_id="", name="digest", error=type(exc).__name__))
    return DigestSendResponse(sent=sent, errors=errors, cards=card_count)


async def record_outcome(result: DigestSendResponse, *, no_channels_ok: bool = False) -> None:
    """Stamp the result on the settings row and write the admin audit row (system actor)."""
    if result.errors:
        status, error = "error", "; ".join(f"{e.name}: {e.error}" for e in result.errors)[:500]
    elif result.sent == 0 and not no_channels_ok:
        status, error = "error", "No webhook channel has the digest switched on"
    else:
        status, error = "sent", None
    await DigestSettings.get_pymongo_collection().update_one(
        {}, {"$set": {"last_sent_at": datetime.now(timezone.utc), "last_status": status, "last_error": error}}
    )
    await audit_service.record(
        "Digest Sent" if status == "sent" else "Digest Send Failed",
        actor_type="system",
        target_type="digest",
        metadata={"channels": result.sent, "errors": len(result.errors)},
    )


# --- scheduling -------------------------------------------------------------------------------


def slot_key(digest: DigestSettings, now: datetime) -> str | None:
    """The period key if `now` is inside a send slot (the configured time, for up to 6 hours after),
    else None. Today's and yesterday's slot are both checked so a late-evening slot survives midnight."""
    for back in (0, 1):
        day = now - timedelta(days=back)
        slot = day.replace(hour=digest.hour_utc, minute=digest.minute_utc, second=0, microsecond=0)
        if not (slot <= now < slot + _SLOT_GRACE):
            continue
        if digest.frequency == "weekly" and slot.weekday() != digest.weekday:
            continue
        return f"{'W' if digest.frequency == 'weekly' else 'D'}:{slot:%Y-%m-%d}"
    return None


async def claim_slot(key: str) -> DigestSettings | None:
    """Atomically take this period. Exactly one caller (process or replica) gets the settings back."""
    await get_settings()
    raw = await DigestSettings.get_pymongo_collection().find_one_and_update(
        {"enabled": True, "last_sent_for": {"$ne": key}},
        {"$set": {"last_sent_for": key}},
        return_document=ReturnDocument.AFTER,
    )
    return DigestSettings.model_validate(raw) if raw else None


async def run_due(now: datetime | None = None) -> bool:
    """Send the digest if one is due and nobody has claimed this period. Returns whether it sent."""
    now = now or datetime.now(timezone.utc)
    digest = await get_settings()
    if not digest.enabled:
        return False
    key = slot_key(digest, now)
    if key is None:
        return False
    claimed = await claim_slot(key)
    if claimed is None:
        return False
    await record_outcome(await send_digest(claimed, now=now))
    return True


async def scheduler_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await run_due()
        except Exception:
            logger.warning("digest scheduler tick failed", exc_info=True)
