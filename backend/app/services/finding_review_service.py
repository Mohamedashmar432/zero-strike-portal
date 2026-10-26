"""Admin-reviewed exemptions: a finding stops blocking CI only after a portal admin accepts it.

A project member asks (`request_review`) -- false positive for code findings, accepted risk for
dependency findings -- with a comment. The finding keeps blocking while the request is pending. A
portal admin accepts or rejects it (`decide`), and can later revoke an acceptance (`revoke`).

An accepted review is an *exemption*: `accepted_exemptions` is the single source both consumers
read -- report ingestion (portal counts) and the scanner create-scan response (the CI gate) -- so
the two can never disagree. An exemption is (fingerprint, file): the fingerprint has no path in it,
so matching it alone would also silence the same snippet in another file of the repo.

See docs/FINDING_REVIEW.md.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.user import User
from app.models.vulnerability import FindingReview, ReviewKind, Vulnerability
from app.services import audit_service, notification_service

_REVIEW_LINK = "/admin/finding-reviews"


def normalize_path(path: str | None) -> str:
    """The comparison form of a scanner-reported path: forward slashes, no leading "./"."""
    p = (path or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def kind_allowed(vuln: Vulnerability) -> ReviewKind:
    """The one review kind a finding may get: dependency findings are almost always real (a
    published advisory against the installed version), so they can be accepted as a risk but never
    called a false positive."""
    return "accepted_risk" if vuln.current_kind == "sca" else "false_positive"


async def request_review(vuln: Vulnerability, kind: ReviewKind, comment: str, user: User) -> Vulnerability:
    comment = (comment or "").strip()
    if not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment explaining why is required")
    allowed = kind_allowed(vuln)
    if kind != allowed:
        if vuln.current_kind == "sca":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Dependency findings cannot be marked as false positive. Request accepted risk instead.",
            )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only dependency findings go through accepted-risk review; mark this one as a false positive.",
        )
    if vuln.review and vuln.review.status == "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "This finding is already exempted by an admin")
    file_path = normalize_path(vuln.current_location.file if vuln.current_location else None)
    if not file_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "This finding has no file location to exempt")

    now = datetime.now(timezone.utc)
    vuln.review = FindingReview(
        kind=kind,
        file_path=file_path,
        requested_by_user_id=str(user.id),
        requested_at=now,
        request_comment=comment,
    )
    vuln.updated_at = now
    await vuln.save()

    label = "false positive" if kind == "false_positive" else "accepted risk"
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
        # The same status/reason a direct triage used to set, so every existing reader (fix_status,
        # the Scan Engine's false-positive stats, reconcile's "dispositional reason" rule) keeps working.
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
