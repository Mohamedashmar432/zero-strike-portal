"""Admin-reviewed exemptions: a finding stops blocking CI only after a portal admin accepts it.

A project member asks (`request_review`) -- false positive for code findings, accepted risk for any
finding -- with a comment. The finding keeps blocking while the request is pending. A
portal admin accepts or rejects it (`decide`), and can later revoke an acceptance (`revoke`).

An accepted review is an *exemption*: `accepted_exemptions` is the single source both consumers
read -- report ingestion (portal counts) and the scanner create-scan response (the CI gate) -- so
the two can never disagree. An exemption is (fingerprint, file): the fingerprint has no path in it,
so matching it alone would also silence the same snippet in another file of the repo.

See docs/FINDING_REVIEW.md.
"""

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.vulnerability import FindingReview, ReviewKind, Vulnerability
from app.models.workspace_settings import WorkspaceSettings
from app.services import audit_service, notification_service, workspace_settings_service

_REVIEW_LINK = "/admin/finding-reviews"


def normalize_path(path: str | None) -> str:
    """The comparison form of a scanner-reported path: forward slashes, no leading "./"."""
    p = (path or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


# Accepting a risk is a standing exemption from the CI gate, so its justification has to say something.
# Mirrored in the frontend's status dialog (its live counter).
MIN_RISK_COMMENT_CHARS = 40
_MIN_RISK_COMMENT_WORDS = 6
_PLACEHOLDER_COMMENTS = frozenset({"n/a", "na", "none", "test", "testing", "asdf", "todo", "tbd", "ok", "accepted"})


def validate_risk_comment(comment: str | None) -> str:
    """The trimmed justification for an accepted risk, or a 422. At least MIN_RISK_COMMENT_CHARS, six
    words of two or more letters, and not a placeholder or one word repeated."""
    text = (comment or "").strip()
    words = re.findall(r"[^\W\d_]{2,}", text)
    if (
        len(text) < MIN_RISK_COMMENT_CHARS
        or len(words) < _MIN_RISK_COMMENT_WORDS
        or text.lower() in _PLACEHOLDER_COMMENTS
        or len({w.lower() for w in words}) < 3
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Accepting a risk needs a real justification: at least {MIN_RISK_COMMENT_CHARS} characters "
            f"and {_MIN_RISK_COMMENT_WORDS} words explaining why it is acceptable.",
        )
    return text


def kinds_allowed(vuln: Vulnerability) -> tuple[ReviewKind, ...]:
    """The review kinds a finding may get. Any finding can be accepted as a risk; only code findings
    can be called a false positive, because a dependency finding is a published advisory against the
    installed version -- almost always real."""
    return ("accepted_risk",) if vuln.current_kind == "sca" else ("false_positive", "accepted_risk")


def _review_required(kind: ReviewKind, ws) -> bool:
    """Whether a request of this kind waits for a portal admin. Two independent switches."""
    return ws.risk_acceptance_review_required if kind == "accepted_risk" else ws.finding_review_required


def _apply_acceptance(vuln: Vulnerability, review: FindingReview, now: datetime) -> None:
    """What an accepted review does to the vulnerability, shared by an admin's `decide` and the
    auto-accept in `request_review` so the two can never drift. Sets the same status/reason a direct
    triage used to, so every existing reader (fix_status, the Scan Engine's false-positive stats,
    reconcile's "dispositional reason" rule) keeps working."""
    if review.kind == "false_positive":
        vuln.status = "resolved"
        vuln.resolution_reason = "false_positive"
        vuln.resolved_at = now
        vuln.resolved_by_user_id = review.requested_by_user_id
    else:
        vuln.status = "accepted_risk"
        vuln.resolution_reason = None
        vuln.resolved_at = None
        vuln.resolved_by_user_id = None
    vuln.resolution_comment = review.request_comment


async def request_review(vuln: Vulnerability, kind: ReviewKind, comment: str, user: User) -> Vulnerability:
    if kind not in kinds_allowed(vuln):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Dependency findings cannot be marked as false positive. Request accepted risk instead.",
        )
    if kind == "accepted_risk":
        comment = validate_risk_comment(comment)
    else:
        comment = (comment or "").strip()
        if not comment:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment explaining why is required")
    if vuln.review and vuln.review.status == "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "This finding is already exempted by an admin")
    if vuln.review and vuln.review.status == "pending" and vuln.review.kind != kind:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A different kind of review is already pending for this finding. Wait for the admin's decision.",
        )
    file_path = normalize_path(vuln.current_location.file if vuln.current_location else None)
    if not file_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "This finding has no file location to exempt")

    now = datetime.now(timezone.utc)
    review = vuln.review = FindingReview(
        kind=kind,
        file_path=file_path,
        requested_by_user_id=str(user.id),
        requested_at=now,
        request_comment=comment,
    )
    label = "false positive" if kind == "false_positive" else "accepted risk"

    ws = await workspace_settings_service.get_workspace_settings()
    if not _review_required(kind, ws):
        # Admin review is off for this kind: the request is its own acceptance. Nothing is pending, so no
        # admin is asked.
        review.status = "accepted"
        review.reviewed_by_user_id = str(user.id)
        review.reviewed_at = now
        off = "admin review is off" if kind == "false_positive" else "admin review of risk acceptance is off"
        review.review_comment = f"Auto-accepted: {off}"
        _apply_acceptance(vuln, review, now)
        vuln.updated_at = now
        await vuln.save()
        await audit_service.record(
            "Finding Review Auto-Accepted",
            actor_type="user",
            actor_user_id=str(user.id),
            project_id=vuln.project_id,
            target_type="vulnerability",
            target_id=str(vuln.id),
            metadata={"kind": kind, "file": file_path, "rule_id": vuln.current_rule_id or "", "comment": comment},
        )
        await notification_service.notify(
            "finding.review_decided",
            project_id=vuln.project_id,
            title=f"Your {label} request was accepted",
            body=f"{vuln.current_rule_name or vuln.current_rule_id} in {file_path}: accepted -- it no longer "
            f"blocks CI ({off}).",
            link=f"/projects/{vuln.project_id}/vulnerabilities/{vuln.id}",
            severity="info",
            only_user_ids=[str(user.id)],
        )
        if kind == "false_positive":
            from app.services import scan_engine_service

            await scan_engine_service.check_rule_noisy(vuln.current_rule_id)
        return vuln

    vuln.updated_at = now
    await vuln.save()

    await audit_service.record(
        "Finding Review Requested",
        actor_type="user",
        actor_user_id=str(user.id),
        project_id=vuln.project_id,
        target_type="vulnerability",
        target_id=str(vuln.id),
        metadata={"kind": kind, "file": file_path, "rule_id": vuln.current_rule_id or "", "comment": comment},
    )
    await notification_service.notify(
        "finding.review_requested",
        project_id=vuln.project_id,
        title=f"Review requested: {label}",
        body=f"{user.email} asks to exempt {vuln.current_rule_name or vuln.current_rule_id} in {file_path}: {comment}",
        link=_REVIEW_LINK,
        severity="warning",
    )
    return vuln


async def decide(vuln: Vulnerability, accept: bool, comment: str | None, admin: User) -> Vulnerability:
    review = vuln.review
    if review is None or review.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This review is not pending")
    comment = (comment or "").strip()
    if not accept and not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment is required to reject a request")

    now = datetime.now(timezone.utc)
    review.status = "accepted" if accept else "rejected"
    review.reviewed_by_user_id = str(admin.id)
    review.reviewed_at = now
    review.review_comment = comment or None
    if accept:
        _apply_acceptance(vuln, review, now)
    vuln.updated_at = now
    await vuln.save()

    await audit_service.record(
        "Finding Review Accepted" if accept else "Finding Review Rejected",
        actor_type="user",
        actor_user_id=str(admin.id),
        project_id=vuln.project_id,
        target_type="vulnerability",
        target_id=str(vuln.id),
        metadata={
            "kind": review.kind,
            "file": review.file_path,
            "comment": comment,
            # Kept visible on purpose: an admin may approve their own request, and the trail says so.
            "self_approved": accept and review.requested_by_user_id == str(admin.id),
        },
    )
    label = "false positive" if review.kind == "false_positive" else "accepted risk"
    verdict = "accepted -- it no longer blocks CI" if accept else "rejected -- it still blocks CI"
    await notification_service.notify(
        "finding.review_decided",
        project_id=vuln.project_id,
        title=f"Your {label} request was {'accepted' if accept else 'rejected'}",
        body=f"{vuln.current_rule_name or vuln.current_rule_id} in {review.file_path}: {verdict}."
        + (f" Admin comment: {comment}" if comment else ""),
        link=f"/projects/{vuln.project_id}/vulnerabilities/{vuln.id}",
        severity="info" if accept else "warning",
        only_user_ids=[review.requested_by_user_id],
    )
    if accept and review.kind == "false_positive":
        from app.services import scan_engine_service

        await scan_engine_service.check_rule_noisy(vuln.current_rule_id)
    return vuln


async def revoke(vuln: Vulnerability, comment: str, admin: User) -> Vulnerability:
    review = vuln.review
    if review is None or review.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an accepted exemption can be revoked")
    comment = (comment or "").strip()
    if not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment is required to revoke an exemption")

    now = datetime.now(timezone.utc)
    review.status = "revoked"
    review.reviewed_by_user_id = str(admin.id)
    review.reviewed_at = now
    review.review_comment = comment
    vuln.status = "open"
    vuln.resolution_reason = None
    vuln.resolution_comment = None
    vuln.resolved_at = None
    vuln.resolved_by_user_id = None
    vuln.reopened_at = now
    vuln.updated_at = now
    await vuln.save()

    await audit_service.record(
        "Finding Review Revoked",
        actor_type="user",
        actor_user_id=str(admin.id),
        project_id=vuln.project_id,
        target_type="vulnerability",
        target_id=str(vuln.id),
        metadata={"kind": review.kind, "file": review.file_path, "comment": comment},
    )
    label = "false positive" if review.kind == "false_positive" else "accepted risk"
    await notification_service.notify(
        "finding.review_decided",
        project_id=vuln.project_id,
        title=f"Your {label} exemption was revoked",
        body=f"{vuln.current_rule_name or vuln.current_rule_id} in {review.file_path} blocks CI again. "
        f"Admin comment: {comment}",
        link=f"/projects/{vuln.project_id}/vulnerabilities/{vuln.id}",
        severity="warning",
        only_user_ids=[review.requested_by_user_id],
    )
    return vuln


async def accepted_exemptions(project_id: str, repo_scope_key: str) -> list[dict[str, str]]:
    """Every accepted (fingerprint, file) in one project's repo scope -- never another project's or
    another repo's. The one query both report ingestion and the scanner create-scan response use."""
    rows = await Vulnerability.get_pymongo_collection().find(
        {"project_id": project_id, "repo_scope_key": repo_scope_key, "review.status": "accepted"},
        {"fingerprint": 1, "review.file_path": 1, "review.kind": 1},
    ).to_list(length=None)
    return [
        {"fingerprint": r["fingerprint"], "file": normalize_path(r["review"]["file_path"]), "kind": r["review"]["kind"]}
        for r in rows
    ]


async def migrate_unreviewed_false_positives() -> int:
    """Startup migration: a false-positive verdict set before admin review existed was never
    reviewed, so it goes back to blocking as a pending request (comment and requester preserved).
    Dependency findings cannot be false positives any more; theirs reopen with no request. Idempotent:
    a migrated row has a review, and only review-less resolved/false_positive rows are touched."""
    coll = Vulnerability.get_pymongo_collection()
    now = datetime.now(timezone.utc)
    rows = await coll.find(
        {"status": "resolved", "resolution_reason": "false_positive", "review": None}
    ).to_list(length=None)
    for r in rows:
        location = (r.get("current_location") or {}).get("file")
        reopen = {
            "status": "open",
            "resolution_reason": None,
            "resolved_at": None,
            "resolved_by_user_id": None,
            "reopened_at": now,
            "updated_at": now,
        }
        if r.get("current_kind") != "sca" and location and r.get("resolved_by_user_id"):
            reopen["review"] = FindingReview(
                kind="false_positive",
                file_path=normalize_path(location),
                requested_by_user_id=r["resolved_by_user_id"],
                requested_at=r.get("resolved_at") or now,
                request_comment=r.get("resolution_comment") or "(marked before admin review existed)",
            ).model_dump()
        else:
            reopen["resolution_comment"] = None
        await coll.update_one({"_id": r["_id"]}, {"$set": reopen})
        await audit_service.record(
            "Finding Review Migrated",
            actor_type="system",
            project_id=r.get("project_id"),
            target_type="vulnerability",
            target_id=str(r["_id"]),
            metadata={"to": "pending review" if "review" in reopen else "open (dependency finding)"},
        )
    return len(rows)


async def migrate_risk_review_toggle() -> bool:
    """Startup migration: seed `risk_acceptance_review_required` from `finding_review_required` when the
    stored settings predate it, so an upgrade never loosens review (the old switch governed accepted risk
    on dependency findings). Reads the raw document because a Beanie load would fill in the default and
    hide that the field was never stored. Idempotent: once stored, the field is never overwritten."""
    coll = WorkspaceSettings.get_pymongo_collection()
    doc = await coll.find_one({"risk_acceptance_review_required": {"$exists": False}})
    if doc is None:
        return False
    await coll.update_one(
        {"_id": doc["_id"]},
        {"$set": {"risk_acceptance_review_required": bool(doc.get("finding_review_required", False))}},
    )
    return True


async def migrate_unreviewed_accepted_risks() -> int:
    """Startup migration: an accepted risk set before it went through review (owner/admin-only
    direct triage) was never reviewed, so it goes back to blocking as a pending request. The requester
    and comment come from the audit trail when it can be found; otherwise the row simply reopens with no
    request. Never auto-accepted. Idempotent: a migrated row is `open`, and only review-less
    accepted_risk rows are touched."""
    coll = Vulnerability.get_pymongo_collection()
    now = datetime.now(timezone.utc)
    rows = await coll.find({"status": "accepted_risk", "review": None}).to_list(length=None)
    for r in rows:
        vid = str(r["_id"])
        trail = await AuditLog.get_pymongo_collection().find_one(
            {
                "target_type": "vulnerability",
                "target_id": vid,
                "action": "Vulnerability Status Updated",
                "metadata.status.after": "accepted_risk",
            },
            sort=[("created_at", -1)],
        )
        location = (r.get("current_location") or {}).get("file")
        reopen = {
            "status": "open",
            "resolution_reason": None,
            "resolution_comment": None,
            "resolved_at": None,
            "resolved_by_user_id": None,
            "reopened_at": now,
            "updated_at": now,
        }
        requester = (trail or {}).get("actor_user_id")
        if requester and location:
            reopen["review"] = FindingReview(
                kind="accepted_risk",
                file_path=normalize_path(location),
                requested_by_user_id=requester,
                requested_at=trail.get("created_at") or now,
                request_comment=r.get("resolution_comment") or "(accepted before risk review existed)",
            ).model_dump()
        await coll.update_one({"_id": r["_id"]}, {"$set": reopen})
        await audit_service.record(
            "Finding Review Migrated",
            actor_type="system",
            project_id=r.get("project_id"),
            target_type="vulnerability",
            target_id=vid,
            metadata={"to": "pending review" if "review" in reopen else "open (requester unknown)"},
        )
    return len(rows)
