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
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from pymongo import ReturnDocument

from app.core.config import settings
from app.models.digest_settings import DigestSettings
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
_OSV_PROBE_URL = "https://api.osv.dev/v1/vulns/GHSA-jfh8-c2jp-5v3q"
_MAX_TABLE_ROWS = 25
_RUNNER_LOOKBACK = timedelta(days=14)


# --- settings ---------------------------------------------------------------------------------


async def get_settings() -> DigestSettings:
    row = await DigestSettings.find_one()
    if row is None:
        row = DigestSettings()
        await row.insert()
    return row


# --- gathering --------------------------------------------------------------------------------


async def _probe_osv() -> bool:
    """Whether OSV.dev answers from this server. Any HTTP response counts as reachable; only a
    network failure or timeout does not. Tests replace this -- they never touch the network."""
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            await client.get(_OSV_PROBE_URL)
        return True
    except Exception:
        return False


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


async def _scanner_health(new_ids: list[str]) -> ScannerHealth:
    newest = await ScannerBinary.find_all().sort("-uploaded_at").first_or_none()
    latest = newest.version if newest else None
    pack = await scan_engine_service.active_pack()
    return ScannerHealth(
        engine_available=cloud_scan_service.scanner_available(),
        backend_scanner_version=settings.scanner_build_ref or "unknown",
        latest_binary_version=latest,
        outdated_ci_runners=await _outdated_ci_runners(latest),
        rule_pack_version=pack.version if pack else None,
        rule_count=len(pack.custom_rules) if pack else 0,
        osv_reachable=await _probe_osv(),
        new_cve_ids=new_ids[:5],
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
        scanner=await _scanner_health([a for a, _, _ in all_new]),
        stale_projects=stale,
        quota_warnings=warnings,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- the card (pure) --------------------------------------------------------------------------

_SEV_LETTER = {"critical": "C", "high": "H", "medium": "M", "low": "L", "info": "I"}
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
        "separator": separator,
        "columns": [
            {"type": "Column", "width": w, "verticalContentAlignment": "Center", "items": [c]}
            for w, c in zip(_WIDTHS, cells)
        ],
    }
    if style:
        row["style"] = style
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


def build_card(preview: DigestPreview, *, frontend_origin: str = "") -> dict:
    """Adaptive Card 1.4 for the digest. Pure: the same preview always yields the same card."""
    period = f"{preview.period_start:%d %b %Y %H:%M} to {preview.period_end:%d %b %Y %H:%M} UTC"
    t = preview.totals
    shown = sorted(preview.rows, key=_rank, reverse=True)[:_MAX_TABLE_ROWS]

    body: list[dict] = [
        {
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": "THINKSHIELD · SECURITY DIGEST",
                    "size": "Small",
                    "weight": "Bolder",
                    "isSubtle": True,
                    "wrap": True,
                },
                {
                    "type": "TextBlock",
                    "text": f"{len(preview.rows)} projects",
                    "size": "Large",
                    "weight": "Bolder",
                    "spacing": "None",
                    "wrap": True,
                },
                {"type": "TextBlock", "text": period, "size": "Small", "isSubtle": True, "spacing": "None", "wrap": True},
            ],
        },
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
        {"type": "TextBlock", "text": "Projects", "weight": "Bolder", "spacing": "Large", "wrap": True},
        _grid_row([_text(c, bold=True, center=i in _CENTERED) for i, c in enumerate(_COLUMNS)], style="emphasis"),
    ]
    for i, r in enumerate(shown):
        body.append(_grid_row(_row_cells(r.name, r, _cves_text(r.new_cves)), separator=i > 0))
    body.append(
        _grid_row(_row_cells("Total", t, str(t.new_cves.count) if t.new_cves.count else "-", bold=True), style="emphasis")
    )
    if len(preview.rows) > len(shown):
        body.append(
            {
                "type": "TextBlock",
                "text": f"+ {len(preview.rows) - len(shown)} more projects (totals include them).",
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
            }
        )
    body.append(
        {
            "type": "TextBlock",
            "text": "Pipeline and Cloud count runs in this period. Critical and High are current exposure "
            "(latest scan per repository).",
            "isSubtle": True,
            "size": "Small",
            "wrap": True,
        }
    )

    s = preview.scanner
    facts = [
        ("Scan engine", "Available" if s.engine_available else "NOT AVAILABLE"),
        ("Scanner in backend", s.backend_scanner_version),
        ("Latest published binary", s.latest_binary_version or "None published"),
        ("CI runners on an older scanner", str(s.outdated_ci_runners)),
        ("Rule pack", f"v{s.rule_pack_version} ({s.rule_count} custom rules)" if s.rule_pack_version else "None published"),
        ("Vulnerability data", "OSV.dev, live at scan time: " + ("reachable" if s.osv_reachable else "NOT REACHABLE")),
    ]
    if s.new_cve_ids:
        facts.append(("New advisories this period", ", ".join(s.new_cve_ids)))
    body.append(
        {
            "type": "Container",
            "spacing": "Large",
            "style": "good" if s.engine_available and s.osv_reachable else "attention",
            "items": [
                {"type": "TextBlock", "text": "Scanner health", "weight": "Bolder", "wrap": True},
                {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]},
            ],
        }
    )

    attention: list[str] = []
    if t.cloud_failed or t.pipeline_failed:
        attention.append(f"{t.pipeline_failed} pipeline run(s) and {t.cloud_failed} cloud scan(s) failed this period")
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
    card: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if frontend_origin:
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": "Open Control Panel", "url": f"{frontend_origin}/admin/control-panel"}
        ]
    return card


# --- sending ----------------------------------------------------------------------------------


async def send_digest(digest: DigestSettings, *, now: datetime | None = None) -> DigestSendResponse:
    """Post the current digest to every enabled channel with `include_digest`. Never raises."""
    errors: list[DigestSendError] = []
    sent = 0
    try:
        channels = await WebhookChannel.find(
            WebhookChannel.enabled == True, WebhookChannel.include_digest == True  # noqa: E712
        ).to_list()
        if not channels:
            return DigestSendResponse(sent=0, errors=[])
        card = build_card(await build_preview(digest, now), frontend_origin=settings.frontend_origin)
        results = await asyncio.gather(*(webhook_channel_service.send_card(c, card) for c in channels))
        for channel, (ok, _status, error) in zip(channels, results):
            if ok:
                sent += 1
            else:
                errors.append(DigestSendError(channel_id=str(channel.id), name=channel.name, error=error or "failed"))
    except Exception as exc:
        logger.warning("digest send failed", exc_info=True)
        errors.append(DigestSendError(channel_id="", name="digest", error=type(exc).__name__))
    return DigestSendResponse(sent=sent, errors=errors)


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
