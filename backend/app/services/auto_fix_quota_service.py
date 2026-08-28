"""Per-scan AI Auto-Fix quota: usage counting, enforcement, and the request/approval flow.

The single place quota policy is decided, so the two trigger endpoints in
ai_remediation.py cannot drift apart on what "used" means.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.ai_fix_proposal import AIFixProposal
from app.models.auto_fix_quota import AutoFixQuotaRequest, ScanAutoFixQuota
from app.models.scan import Scan
from app.services import remediation_settings_service

# Hard ceiling on a single request so a typo ("1000000") cannot be approved into an
# unbounded LLM spend by a distracted admin.
MAX_REQUESTABLE_ADDITIONAL = 500


async def _extra_granted(scan_id: str) -> int:
    quota = await ScanAutoFixQuota.find_one(ScanAutoFixQuota.scan_id == scan_id)
    return quota.extra_granted if quota else 0


async def charged_finding_ids(scan_id: str) -> set[str]:
    """Findings on this scan that already have a fix proposal, i.e. already paid for.

    Deduped in Python rather than with a `distinct` aggregation: Beanie's FindMany has
    no `.distinct()` in the pinned version, and the row count here is bounded by the
    scan's own allowance (tens, a few hundred at most after generous grants), so a
    single find is cheaper than an aggregation pipeline.
    """
    proposals = await AIFixProposal.find(AIFixProposal.scan_id == scan_id).to_list()
    return {p.finding_id for p in proposals}


async def count_used(scan_id: str) -> int:
    """Distinct findings charged against this scan.

    Counted from proposals rather than a stored tally, so regenerating or revising a
    fix for the same finding never charges twice, and a dismissed proposal still
    counts — the LLM spend happened either way.
    """
    return len(await charged_finding_ids(scan_id))


async def get_usage(scan_id: str, project_id: str) -> dict:
    cfg = await remediation_settings_service.get_settings()
    default_limit = cfg.auto_fix_findings_per_scan
    extra = await _extra_granted(scan_id)
    used = await count_used(scan_id)
    limit = default_limit + extra
    pending = await AutoFixQuotaRequest.find(
        AutoFixQuotaRequest.scan_id == scan_id,
        AutoFixQuotaRequest.status == "pending",
    ).count()
    return {
        "scan_id": scan_id,
        "project_id": project_id,
        "default_limit": default_limit,
        "extra_granted": extra,
        "limit": limit,
        "used": used,
        # Never negative: a lowered global default can leave used > limit.
        "remaining": max(0, limit - used),
        "pending_request_count": pending,
    }


async def remaining(scan_id: str) -> int:
    cfg = await remediation_settings_service.get_settings()
    limit = cfg.auto_fix_findings_per_scan + await _extra_granted(scan_id)
    return max(0, limit - await count_used(scan_id))


_EXHAUSTED = (
    "This scan has used its full AI Auto-Fix allowance ({limit} findings). "
    "Request additional headroom from an administrator to continue."
)


async def _notify_exhausted(scan_id: str, limit: int) -> None:
    """Tell the project its allowance ran out — but only while no request is already open.

    Without that check this fires on every retry of a blocked action, which is exactly the
    behaviour that teaches people to mute a notification channel. Once someone has asked for
    more headroom, they know; the admin decision is the next signal, not this one.
    """
    from app.services import notification_service

    quota = await ScanAutoFixQuota.find_one(ScanAutoFixQuota.scan_id == scan_id)
    project_id = quota.project_id if quota else None
    if project_id is None:
        scan = await Scan.get(scan_id)
        project_id = scan.project_id if scan else None
    if project_id is None:
        return
    pending = await AutoFixQuotaRequest.find(
        AutoFixQuotaRequest.scan_id == scan_id, AutoFixQuotaRequest.status == "pending"
    ).count()
    if pending:
        return
    await notification_service.notify(
        "autofix.quota_exhausted",
        project_id=project_id,
        title=f"Auto-fix allowance exhausted ({limit} findings)",
        body="Request additional headroom from an administrator to continue.",
        link=f"/projects/{project_id}/auto-fix/{scan_id}",
        severity="warning",
    )


async def allocate(scan_id: str, candidate_finding_ids: list[str]) -> list[str]:
    """Trim a set of findings to what the scan's remaining allowance permits.

    Findings that already have a proposal are free — they were charged when first
    generated, so a re-run over the same selection never consumes more. Only
    genuinely new findings draw down the allowance.
    """
    already = await charged_finding_ids(scan_id)
    free = [fid for fid in candidate_finding_ids if fid in already]
    fresh = [fid for fid in candidate_finding_ids if fid not in already]

    room = await remaining(scan_id)
    if room <= 0 and fresh:
        cfg = await remediation_settings_service.get_settings()
        limit = cfg.auto_fix_findings_per_scan + await _extra_granted(scan_id)
        await _notify_exhausted(scan_id, limit)
        raise HTTPException(status.HTTP_409_CONFLICT, _EXHAUSTED.format(limit=limit))

    # Preserve the caller's ordering (priority-sorted upstream) rather than putting
    # the already-fixed ones first.
    allowed = set(free) | set(fresh[:room])
    return [fid for fid in candidate_finding_ids if fid in allowed]


async def assert_can_fix_one(scan_id: str, finding_id: str) -> None:
    """Gate the single-finding trigger. Re-fixing an already-proposed finding is free."""
    already = await AIFixProposal.find_one(
        AIFixProposal.scan_id == scan_id, AIFixProposal.finding_id == finding_id
    )
    if already is not None:
        return
    if await remaining(scan_id) <= 0:
        cfg = await remediation_settings_service.get_settings()
        limit = cfg.auto_fix_findings_per_scan + await _extra_granted(scan_id)
        await _notify_exhausted(scan_id, limit)
        raise HTTPException(status.HTTP_409_CONFLICT, _EXHAUSTED.format(limit=limit))


# --- request / approval flow -------------------------------------------------


async def create_request(
    *, scan_id: str, project_id: str, requested_by: str, requested_additional: int, reason: str
) -> AutoFixQuotaRequest:
    if requested_additional < 1 or requested_additional > MAX_REQUESTABLE_ADDITIONAL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Request between 1 and {MAX_REQUESTABLE_ADDITIONAL} additional findings.",
        )
    if not reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A reason is required.")

    # One open request per scan, so an admin queue cannot be flooded and approvals
    # cannot stack unnoticed.
    existing = await AutoFixQuotaRequest.find_one(
        AutoFixQuotaRequest.scan_id == scan_id, AutoFixQuotaRequest.status == "pending"
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A request for this scan is already awaiting review.",
        )

    req = AutoFixQuotaRequest(
        scan_id=scan_id,
        project_id=project_id,
        requested_by=requested_by,
        requested_additional=requested_additional,
        reason=reason.strip(),
    )
    await req.insert()
    return req


async def decide_request(
    *,
    request_id: str,
    approve: bool,
    decided_by: str,
    granted_additional: int | None = None,
    decision_note: str | None = None,
) -> AutoFixQuotaRequest:
    req = await AutoFixQuotaRequest.get(request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Request is already {req.status}.")

    now = datetime.now(timezone.utc)
    if approve:
        granted = req.requested_additional if granted_additional is None else granted_additional
        if granted < 1 or granted > MAX_REQUESTABLE_ADDITIONAL:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Grant between 1 and {MAX_REQUESTABLE_ADDITIONAL} additional findings.",
            )
        quota = await ScanAutoFixQuota.find_one(ScanAutoFixQuota.scan_id == req.scan_id)
        if quota is None:
            quota = ScanAutoFixQuota(
                scan_id=req.scan_id, project_id=req.project_id, extra_granted=granted
            )
            quota.updated_by = decided_by
            await quota.insert()
        else:
            quota.extra_granted += granted
            quota.updated_at = now
            quota.updated_by = decided_by
            await quota.save()
        req.status = "approved"
        req.granted_additional = granted
    else:
        req.status = "rejected"
        req.granted_additional = None

    req.decision_note = (decision_note or "").strip() or None
    req.decided_by = decided_by
    req.decided_at = now
    await req.save()
    return req


async def list_requests(
    *, status_filter: str | None = None, project_id: str | None = None, limit: int = 100
) -> list[AutoFixQuotaRequest]:
    conditions = []
    if status_filter:
        conditions.append(AutoFixQuotaRequest.status == status_filter)
    if project_id:
        conditions.append(AutoFixQuotaRequest.project_id == project_id)
    query = AutoFixQuotaRequest.find(*conditions) if conditions else AutoFixQuotaRequest.find_all()
    return await query.sort("-created_at").limit(limit).to_list()
