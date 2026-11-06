"""The scheduled Teams digest (docs/DIGEST_V2_AND_DEV_ALERTS.md, scheduling rules in
docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 6).

Three separable pieces: `build_preview` gathers the numbers (async, reads Mongo), `build_cards` /
`build_project_cards` turn them into Adaptive Cards 1.4 built from column sets (pure functions --
unit-tested against a fixture), and `run_due` / `scheduler_loop` decide when to send. A send claims its
period with one atomic `find_one_and_update` on `DigestSettings.last_sent_for`, so a restart or a second
replica can never double-send.

Critical/High are *current exposure* (each repo's latest completed scan, via project_stats_service),
not a sum over every scan in the period. The new-CVE count comes from findings' advisory ids, which are
OSV.dev lookups made at scan time -- the portal holds no CVE feed, so the card gives a count and never
claims a feed date. A channel scoped to projects gets one card per project instead of the global digest.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from pymongo import ReturnDocument

from app.core.config import settings
from app.core.repo_url import sanitize_repo_url
from app.models.digest_settings import DigestSettings
from app.models.project import Project
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.models.vulnerability import Vulnerability
from app.models.webhook_channel import WebhookChannel
from app.schemas.digest import (
    DigestPreview,
    DigestRow,
    DigestSendError,
    DigestSendResponse,
    DigestTotals,
    OutdatedPipeline,
    QuotaWarning,
    ScannerHealth,
    StaleProject,
)
from app.services import (
    audit_service,
    cloud_scan_quota_service,
    cloud_scan_service,
    project_insights_service,
    project_stats_service,
    webhook_channel_service,
)

logger = structlog.get_logger(__name__)

STALE_AFTER = timedelta(days=30)
QUOTA_WARN_FRACTION = 0.8
_SLOT_GRACE = timedelta(hours=6)  # a slot missed by more than this (portal was down) is skipped, not sent late
# Teams refuses a message over ~28 KB (Power Automate reports RequestEntityTooLarge), and a Workflows
# webhook still answers 202 first, so an oversize card is accepted by the portal's POST and then never
# appears. That is why the digest is several small cards, not one: a project row costs ~1.2 KB, so 10 per
# card is ~13 KB. Workflows re-wraps each card in a larger, escaped message; _MAX_CARD_BYTES is the budget
# a test holds every card to.
_MAX_CARD_BYTES = 20_000
_ROWS_PER_CARD = 10
_MAX_PROJECT_CARDS = 6  # 60 projects; the summary card names how many were left out (totals cover them)
_MAX_OUTDATED_ROWS = 15
_MAX_SCOPED_CARDS = 20  # one card per project on a scoped channel; a longer list is cut here
# Workflows runs each post as its own flow, so posts sent back to back can land out of order; the cards
# are also numbered "n/N" so a reader can still tell.
_CARD_GAP_SECONDS = 2.0


# --- settings ---------------------------------------------------------------------------------


async def get_settings() -> DigestSettings:
    row = await DigestSettings.find_one()
    if row is None:
        row = DigestSettings()
        await row.insert()
    return row


# --- gathering --------------------------------------------------------------------------------


def _norm_version(version: str | None) -> str:
    return (version or "").strip().lstrip("vV")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", _norm_version(version)))


async def _outdated_pipelines(
    latest: str | None, names: dict[str, str], start: datetime, end: datetime
) -> list[OutdatedPipeline]:
    """CI/CD scans created in [start, end) whose scanner differs from the newest published binary,
    grouped by (project, repository, runner host, version): oldest version first, then most runs."""
    if not latest or not names:
        return []
    pipeline = [
        {
            "$match": {
                "scan_type": "cicd",
                "scanner_version": {"$ne": None},
                "project_id": {"$in": list(names)},
                "created_at": {"$gte": start, "$lt": end},
            }
        },
        {
            "$group": {
                "_id": {"p": "$project_id", "r": "$repo_url", "h": "$hostname", "v": "$scanner_version"},
                "runs": {"$sum": 1},
                "last": {"$max": "$created_at"},
            }
        },
    ]
    # Motor's aggregate() is a cursor, not awaitable (see dashboard_service._severity_groups).
    rows = await Scan.get_pymongo_collection().aggregate(pipeline).to_list(length=None)
    out: list[OutdatedPipeline] = []
    for row in rows:
        key = row["_id"]
        if _norm_version(key["v"]) == _norm_version(latest):
            continue
        repo = sanitize_repo_url(key.get("r"))
        repository = (repo.split("://", 1)[-1] if repo else "-") + (f" ({key['h']})" if key.get("h") else "")
        out.append(
            OutdatedPipeline(
                project_id=key["p"],
                project=names[key["p"]],
                repository=repository,
                scanner_version=key["v"],
                runs=row["runs"],
                last_run_at=_utc(row["last"]),
            )
        )
    return sorted(out, key=lambda o: (_version_key(o.scanner_version), -o.runs, o.project, o.repository))


async def _vulnerability_stats(pids: list[str], start: datetime, end: datetime) -> dict[str, dict]:
    """Per project, over every repo: all vulnerabilities, resolved (all-time), first seen in [start, end),
    and false positives (resolved as one, or an admin-accepted false-positive review)."""
    in_period = {"$and": [{"$gte": ["$first_seen_at", start]}, {"$lt": ["$first_seen_at", end]}]}
    false_positive = {
        "$or": [
            {"$eq": ["$resolution_reason", "false_positive"]},
            {"$and": [{"$eq": ["$review.kind", "false_positive"]}, {"$eq": ["$review.status", "accepted"]}]},
        ]
    }
    pipeline = [
        {"$match": {"project_id": {"$in": pids}}},
        {
            "$group": {
                "_id": "$project_id",
                "total": {"$sum": 1},
                "resolved": {"$sum": {"$cond": [{"$eq": ["$status", "resolved"]}, 1, 0]}},
                "new": {"$sum": {"$cond": [in_period, 1, 0]}},
                "fp": {"$sum": {"$cond": [false_positive, 1, 0]}},
            }
        },
    ]
    rows = await Vulnerability.get_pymongo_collection().aggregate(pipeline).to_list(length=None)
    return {row["_id"]: row for row in rows}


async def _scanner_health(
    names: dict[str, str], new_cve_count: int, start: datetime, end: datetime
) -> ScannerHealth:
    newest = await ScannerBinary.find_all().sort("-uploaded_at").first_or_none()
    latest = newest.version if newest else None
    outdated = await _outdated_pipelines(latest, names, start, end)
    return ScannerHealth(
        engine_available=cloud_scan_service.scanner_available(),
        backend_scanner_version=settings.scanner_build_ref or "unknown",
        latest_binary_version=latest,
        projects_outdated=len({o.project_id for o in outdated}),
        outdated_pipelines=outdated,
        new_advisory_count=new_cve_count,
    )


async def build_preview(
    digest: DigestSettings, now: datetime | None = None, project_ids: list[str] | None = None
) -> DigestPreview:
    """`project_ids` overrides the digest's own project scope (a scoped channel's list)."""
    end = now or datetime.now(timezone.utc)
    start = end - (timedelta(days=7) if digest.frequency == "weekly" else timedelta(days=1))

    projects = [p for p in await Project.find_all().sort(-Project.id).to_list() if not p.is_archived]
    scope = project_ids if project_ids is not None else digest.project_ids
    if scope:
        chosen = set(scope)
        projects = [p for p in projects if str(p.id) in chosen]
    pids = [str(p.id) for p in projects]

    counts = await project_insights_service.scan_counts(start, end) if pids else {}
    quotas = await cloud_scan_quota_service.usage_many(projects) if pids else {}
    cves = await project_insights_service.new_cves(pids, start, end) if pids else {}
    vulns = await _vulnerability_stats(pids, start, end) if pids else {}

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
        mine_vulns = vulns.get(pid, {})
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
                resolved=mine_vulns.get("resolved", 0),
                new_findings=mine_vulns.get("new", 0),
                false_positives=mine_vulns.get("fp", 0),
                vulnerabilities=mine_vulns.get("total", 0),
            )
        )

    totals = DigestTotals(
        **{
            f: sum(getattr(r, f) for r in rows)
            for f in ("pipeline_runs", "pipeline_failed", "cloud_scans", "cloud_failed", "critical", "high")
        }
    )

    stale: list[StaleProject] = []
    if digest.include_stale_projects:
        for p in projects:
            reference = p.last_scan_at or p.created_at
            if _utc(reference) < end - STALE_AFTER:
                stale.append(StaleProject(project_id=str(p.id), name=p.name, last_scan_at=_utc(p.last_scan_at)))
    warnings: list[QuotaWarning] = []
    for p in projects:
        q = quotas[str(p.id)]
        if q.limit > 0 and q.used >= QUOTA_WARN_FRACTION * q.limit:
            warnings.append(QuotaWarning(project_id=str(p.id), name=p.name, used=q.used, limit=q.limit))
    new_cve_count = len({advisory for found in cves.values() for advisory, _sev, _first in found})
    return DigestPreview(
        period_start=start,
        period_end=end,
        rows=rows,
        totals=totals,
        scanner=await _scanner_health({str(p.id): p.name for p in projects}, new_cve_count, start, end),
        stale_projects=stale,
        quota_warnings=warnings,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- the card (pure) --------------------------------------------------------------------------

# Column set, not the 1.5 Table element: legacy Office 365 connector webhooks (webhook.office.com)
# render Adaptive Cards only up to 1.4 and drop a Table without an error, so the rows vanished.
_PROJECT_COLUMNS = ("Project", "CI/CD", "Cloud", "Critical", "High", "Fail rate", "Resolved", "New findings")
_PROJECT_WIDTHS = (30, 10, 10, 10, 10, 11, 11, 13)
_PROJECT_CENTERED = {1, 2, 3, 4, 5, 6, 7}
_OUTDATED_COLUMNS = ("Project", "Repository", "Scanner used", "Runs", "Last run (UTC)")
_OUTDATED_WIDTHS = (22, 34, 14, 8, 18)
_OUTDATED_CENTERED = {3}


def _text(value: str, *, bold: bool = False, color: str | None = None, center: bool = False) -> dict:
    block: dict = {"type": "TextBlock", "text": value, "wrap": True, "size": "Small"}
    if center:
        block["horizontalAlignment"] = "Center"
    if bold:
        block["weight"] = "Bolder"
    if color:
        block["color"] = color
    return block


def _grid_row(
    cells: list[dict], widths: tuple[int, ...], *, style: str | None = None, separator: bool = False
) -> dict:
    row: dict = {
        "type": "ColumnSet",
        "spacing": "Small",
        "columns": [
            {"type": "Column", "width": w, "verticalContentAlignment": "Center", "items": [c]}
            for w, c in zip(widths, cells)
        ],
    }
    if style:
        row["style"] = style
    if separator:
        row["separator"] = True
    return row


def _header_row(columns: tuple[str, ...], widths: tuple[int, ...], centered: set[int]) -> dict:
    cells = [_text(c, bold=True, center=i in centered) for i, c in enumerate(columns)]
    return _grid_row(cells, widths, style="emphasis")


def _pct(part: int, whole: int) -> str:
    return "-" if whole <= 0 else f"{part / whole:.0%}"


def _fail_rate(r) -> str:
    return _pct(r.pipeline_failed + r.cloud_failed, r.pipeline_runs + r.cloud_scans)


def _row_cells(r) -> list[dict]:
    failed = bool(r.pipeline_failed + r.cloud_failed)
    return [
        _text(r.name, bold=True),
        _text(str(r.pipeline_runs), center=True),
        _text(str(r.cloud_scans), center=True),
        _text(str(r.critical), bold=True, color="Attention" if r.critical else None, center=True),
        _text(str(r.high), bold=True, color="Warning" if r.high else None, center=True),
        _text(_fail_rate(r), color="Attention" if failed else None, center=True),
        _text(str(r.resolved), center=True),
        _text(str(r.new_findings), center=True),
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


def _period(preview: DigestPreview) -> str:
    return f"{preview.period_start:%d %b %Y %H:%M} to {preview.period_end:%d %b %Y %H:%M} UTC"


def _open_action(frontend_origin: str, path: str, title: str) -> list[dict] | None:
    return [{"type": "Action.OpenUrl", "title": title, "url": f"{frontend_origin}{path}"}] if frontend_origin else None


def _outdated_section(s: ScannerHealth) -> list[dict]:
    heading = {"type": "TextBlock", "text": "Pipelines on an older scanner", "weight": "Bolder", "wrap": True}
    if not s.latest_binary_version:
        return [heading, _note("No scanner binary is published, so pipeline versions cannot be compared.", spacing="None")]
    if not s.outdated_pipelines:
        return [heading, _note(f"Every pipeline in this period used {s.latest_binary_version}.", spacing="None")]
    shown = s.outdated_pipelines[:_MAX_OUTDATED_ROWS]
    rows = [_header_row(_OUTDATED_COLUMNS, _OUTDATED_WIDTHS, _OUTDATED_CENTERED)]
    for i, o in enumerate(shown):
        cells = [
            _text(o.project, bold=True),
            _text(o.repository),
            _text(o.scanner_version, color="Warning"),
            _text(str(o.runs), center=True),
            _text(f"{o.last_run_at:%d %b %Y %H:%M}" if o.last_run_at else "-"),
        ]
        rows.append(_grid_row(cells, _OUTDATED_WIDTHS, separator=i > 0))
    if len(s.outdated_pipelines) > len(shown):
        rows.append(_note(f"+ {len(s.outdated_pipelines) - len(shown)} more.", spacing="Medium"))
    return [heading, *rows]


def _health_part(preview: DigestPreview) -> _Part:
    s = preview.scanner
    facts = [
        ("Scanner in backend", s.backend_scanner_version),
        ("Latest published binary", s.latest_binary_version or "None published"),
        ("Projects on an older scanner", str(s.projects_outdated)),
        ("New CVEs added", str(s.new_advisory_count)),
        ("Scan engine", "Available" if s.engine_available else "NOT AVAILABLE"),
    ]
    body = [
        {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]},
        {"type": "Container", "spacing": "Medium", "separator": True, "items": _outdated_section(s)},
    ]
    return _Part(
        "SCANNER",
        "Scanner ready" if s.engine_available else "Scanner NOT ready",
        f"{s.backend_scanner_version} · {s.new_advisory_count} new CVEs in this period",
        body,
        style="good" if s.engine_available else "attention",
    )


def _project_parts(preview: DigestPreview) -> tuple[list[_Part], int]:
    """Project status cards, `_ROWS_PER_CARD` per card, worst exposure first; and how many projects
    did not fit in `_MAX_PROJECT_CARDS` (the summary card names them as left out)."""
    ordered = sorted(preview.rows, key=_rank, reverse=True)
    shown = ordered[: _ROWS_PER_CARD * _MAX_PROJECT_CARDS]
    parts: list[_Part] = []
    for start in range(0, len(shown), _ROWS_PER_CARD):
        chunk = shown[start : start + _ROWS_PER_CARD]
        body = [_header_row(_PROJECT_COLUMNS, _PROJECT_WIDTHS, _PROJECT_CENTERED)]
        body += [_grid_row(_row_cells(r), _PROJECT_WIDTHS, separator=i > 0) for i, r in enumerate(chunk)]
        body.append(
            _note(
                "CI/CD and Cloud count scans created in this period; Fail rate is failed over all of them. "
                "Critical and High are current exposure (latest scan per repository). Resolved is all-time; "
                "New findings were first seen in this period.",
                spacing="Medium",
            )
        )
        parts.append(_Part("PROJECT STATUS", f"Projects {start + 1}-{start + len(chunk)} of {len(ordered)}", None, body))
    return parts, len(ordered) - len(shown)


def _summary_part(preview: DigestPreview, left_out: int, frontend_origin: str) -> _Part:
    t = preview.totals
    end = preview.period_end
    failed = t.pipeline_failed + t.cloud_failed
    body: list[dict] = [
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                _kpi("CI/CD scans", t.pipeline_runs, None),
                _kpi("Cloud scans", t.cloud_scans, None),
                _kpi("Failed scans", failed, "Attention" if failed else None),
            ],
        }
    ]
    if left_out:
        body.append(_note(f"{left_out} more projects were not listed on the project cards (totals include them)."))
    return _Part(
        "SUMMARY",
        f"Security digest, {end:%a %d %b %Y}",
        f"Updated {end:%H:%M} UTC · period {_period(preview)}",
        body,
        actions=_open_action(frontend_origin, "/admin/control-panel", "Open Control Panel"),
    )


def build_cards(preview: DigestPreview, *, frontend_origin: str = "") -> list[dict]:
    """The global digest as ordered Adaptive Cards 1.4: scanner, then project status
    (`_ROWS_PER_CARD` per card), then a dated three-KPI summary. Pure: the same preview always yields the
    same cards. Totals always cover every project; only the project cards are capped."""
    project_parts, left_out = _project_parts(preview)
    parts = [_health_part(preview), *project_parts, _summary_part(preview, left_out, frontend_origin)]
    return [_envelope(part, i, len(parts)) for i, part in enumerate(parts, 1)]


def _project_digest_part(preview: DigestPreview, r: DigestRow, frontend_origin: str) -> _Part:
    failed = r.pipeline_failed + r.cloud_failed
    body = [
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                _kpi("Total scans", r.pipeline_runs + r.cloud_scans, None),
                _kpi("CI/CD scans", r.pipeline_runs, None),
                _kpi("Cloud scans", r.cloud_scans, None),
                _kpi("Failed scans", failed, "Attention" if failed else None),
            ],
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Resolved (all time)", "value": str(r.resolved)},
                {"title": "False-positive rate", "value": _pct(r.false_positives, r.vulnerabilities)},
            ],
        },
    ]
    return _Part(
        "PROJECT DIGEST",
        r.name,
        _period(preview),
        body,
        actions=_open_action(frontend_origin, f"/projects/{r.project_id}", "Open project"),
    )


def build_project_cards(preview: DigestPreview, *, frontend_origin: str = "") -> list[dict]:
    """One card per project in the preview, for a channel scoped to those projects. Carries nothing
    about any other project."""
    rows = sorted(preview.rows, key=_rank, reverse=True)[:_MAX_SCOPED_CARDS]
    return [_envelope(_project_digest_part(preview, r, frontend_origin), i, len(rows)) for i, r in enumerate(rows, 1)]



# --- sending ----------------------------------------------------------------------------------


async def _post_cards(channel: WebhookChannel, cards: list[dict]) -> str | None:
    """Post the cards to one channel in order; the error text of the first failure, else None. Stops
    there: a digest missing its middle is worse than one that says which card it stopped at."""
    if not cards:
        return "no active project in this channel's scope"
    for i, card in enumerate(cards, 1):
        if i > 1:
            await asyncio.sleep(_CARD_GAP_SECONDS)
        ok, _status, error = await webhook_channel_service.send_card(channel, card)
        if not ok:
            return f"card {i} of {len(cards)}: {error or 'failed'}"
    return None


async def send_digest(digest: DigestSettings, *, now: datetime | None = None) -> DigestSendResponse:
    """Post the digest to every enabled channel with `include_digest`: the global digest to a channel with
    no project scope, one card per listed project to a scoped one (it never sees other projects' numbers).
    Never raises."""
    errors: list[DigestSendError] = []
    sent = 0
    card_count = 0
    try:
        channels = await WebhookChannel.find(
            WebhookChannel.enabled == True, WebhookChannel.include_digest == True  # noqa: E712
        ).to_list()
        if not channels:
            return DigestSendResponse(sent=0, errors=[])
        origin = settings.frontend_origin
        global_cards: list[dict] | None = None
        plans: list[list[dict]] = []
        for channel in channels:
            if channel.project_ids:
                preview = await build_preview(digest, now, project_ids=channel.project_ids)
                plans.append(build_project_cards(preview, frontend_origin=origin))
            else:
                if global_cards is None:
                    global_cards = build_cards(await build_preview(digest, now), frontend_origin=origin)
                plans.append(global_cards)
        results = await asyncio.gather(*(_post_cards(c, cards) for c, cards in zip(channels, plans)))
        for channel, error in zip(channels, results):
            if error is None:
                sent += 1
            else:
                errors.append(DigestSendError(channel_id=str(channel.id), name=channel.name, error=error))
        card_count = max(len(cards) for cards in plans)
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
