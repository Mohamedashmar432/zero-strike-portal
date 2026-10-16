"""Scan Engine ("engine room"): which scanner rules are noisy, retiring rules, custom rules, and the
versioned rule pack that makes those changes take effect. See docs/SCANNER_ENGINE_ROOM_PLAN.md.

Model in one paragraph: `RuleOverride` + `CustomRule` are the admin's *working copy*. Publishing
freezes the working copy as the next immutable `RulePackVersion`; the highest version is *active* and
is the only thing scans read (retired rules suppress findings at ingest, custom rules are written to
the scan workdir and passed to the scanner as `--extra-rules`). Pending changes are simply the
difference between the working copy and the active pack. Nothing here sends code to an LLM, and rule
statistics are counts only - no client code is shown across projects.
"""

import os
import re
import tempfile
from datetime import datetime, timezone

import structlog
import yaml
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.models.project import Project
from app.models.scan_engine import (
    CustomRule,
    NoisyRuleAlert,
    PackCustomRule,
    RuleOverride,
    RulePackVersion,
)
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.schemas.report import GoReportIn
from app.services import audit_service, workspace_settings_service

logger = structlog.get_logger(__name__)

CUSTOM_RULE_ID_RE = re.compile(r"^ZS-CUSTOM-[A-Z0-9-]+$")
_ANY_RULE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_TEXT = 20_000
_VALIDATE_TIMEOUT_S = 60
_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")

# The `language:` value in a rule's YAML -> file extension for the validation samples.
_EXT = {
    "python": "py",
    "javascript": "js",
    "typescript": "ts",
    "java": "java",
    "go": "go",
    "csharp": "cs",
    "php": "php",
    "html": "html",
}


def _bad(message: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, message)


# --- active pack --------------------------------------------------------------------------------


async def active_pack() -> RulePackVersion | None:
    """The highest published version, or None before the first publish."""
    return await RulePackVersion.find_one(sort=[("version", -1)])


async def retired_rule_ids() -> set[str]:
    pack = await active_pack()
    return set(pack.retired_rule_ids) if pack else set()


async def write_pack_custom_rules(dest: str) -> int:
    """Write the active pack's custom rules into `dest` for `--extra-rules`; returns how many.
    0 means the caller must not pass the flag at all."""
    pack = await active_pack()
    rules = [r for r in (pack.custom_rules if pack else []) if CUSTOM_RULE_ID_RE.match(r.rule_id)]
    if not rules:
        return 0
    os.makedirs(dest, exist_ok=True)
    for r in rules:
        with open(os.path.join(dest, f"{r.rule_id}.yaml"), "w", encoding="utf-8") as fh:
            fh.write(r.yaml)
    return len(rules)


# --- rule statistics ----------------------------------------------------------------------------


def _top_severity(values: list[str | None]) -> str | None:
    present = [v for v in values if v in _SEVERITY_ORDER]
    return min(present, key=_SEVERITY_ORDER.index) if present else None


async def _thresholds() -> tuple[int, int]:
    ws = await workspace_settings_service.get_workspace_settings()
    return ws.noisy_rule_min_fp_tags, ws.noisy_rule_min_fp_percent


def _is_noisy(fp: int, total: int, min_tags: int, min_percent: int) -> bool:
    return total > 0 and fp >= min_tags and fp * 100 >= min_percent * total


async def _aggregate_rules(rule_id: str | None = None) -> dict[str, dict]:
    match: dict = {"current_rule_id": {"$ne": None}}
    if rule_id:
        match = {"current_rule_id": rule_id}
    is_fp = {"$and": [{"$eq": ["$status", "resolved"]}, {"$eq": ["$resolution_reason", "false_positive"]}]}
    groups = await Vulnerability.get_pymongo_collection().aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": "$current_rule_id",
                    "total": {"$sum": 1},
                    "fp_tags": {"$sum": {"$cond": [is_fp, 1, 0]}},
                    "projects": {"$addToSet": "$project_id"},
                    "title": {"$last": "$current_rule_name"},
                    "severities": {"$addToSet": "$current_severity"},
                }
            },
        ]
    ).to_list(length=None)
    return {g["_id"]: g for g in groups}


async def _languages() -> dict[str, str]:
    from app.models.finding import Finding

    groups = await Finding.get_pymongo_collection().aggregate(
        [
            {"$match": {"rule_id": {"$ne": None}, "language": {"$ne": None}}},
            {"$group": {"_id": "$rule_id", "language": {"$first": "$language"}}},
        ]
    ).to_list(length=None)
    return {g["_id"]: g["language"] for g in groups}


async def rule_stats() -> dict:
    """One row per rule that has produced a finding, plus any retired/custom rule without one.
    Sorted by false-positive tags."""
    min_tags, min_percent = await _thresholds()
    agg = await _aggregate_rules()
    langs = await _languages()
    overrides = {o.rule_id: o for o in await RuleOverride.find_all().to_list()}
    customs = {c.rule_id: c for c in await CustomRule.find_all().to_list()}
    pack = await active_pack()
    base_retired = set(pack.retired_rule_ids) if pack else set()
    base_custom = {r.rule_id: r.yaml for r in (pack.custom_rules if pack else [])}

    retired_now = {rid for rid, o in overrides.items() if o.state == "retired"}
    rows = []
    for rid in sorted(set(agg) | retired_now | set(customs)):
        g = agg.get(rid, {})
        total, fp = g.get("total", 0), g.get("fp_tags", 0)
        is_retired = rid in retired_now
        is_custom = rid in customs
        pending = (is_retired != (rid in base_retired)) or (
            is_custom and (rid not in base_custom or base_custom[rid] != customs[rid].yaml)
        )
        rows.append(
            {
                "rule_id": rid,
                "title": g.get("title") or (None),
                "severity": _top_severity(g.get("severities", [])),
                "language": langs.get(rid) or (customs[rid].language if is_custom else None),
                "total_findings": total,
                "fp_tags": fp,
                "fp_rate": round(fp / total, 4) if total else 0.0,
                "projects_affected": len(g.get("projects", [])),
                "state": "retired" if is_retired else ("custom" if is_custom else "active"),
                "noisy": _is_noisy(fp, total, min_tags, min_percent),
                "pending": pending,
                "retire_reason": overrides[rid].reason if is_retired else None,
            }
        )
    rows.sort(key=lambda r: (-r["fp_tags"], r["rule_id"]))
    return {
        "rules": rows,
        "noisy_min_fp_tags": min_tags,
        "noisy_min_fp_percent": min_percent,
        "active_version": pack.version if pack else None,
    }


async def rule_fp_history(rule_id: str, limit: int = 100) -> list[dict]:
    """Who tagged what as a false positive. Names the project, never shows its code."""
    rows = await Vulnerability.find(
        Vulnerability.current_rule_id == rule_id,
        Vulnerability.status == "resolved",
        Vulnerability.resolution_reason == "false_positive",
    ).sort("-resolved_at").limit(limit).to_list()
    names: dict[str, str] = {}
    for pid in {r.project_id for r in rows}:
        project = await workspace_settings_service.load_project(pid)
        names[pid] = project.name if isinstance(project, Project) else "(deleted project)"
    users: dict[str, str] = {}
    for uid in {r.resolved_by_user_id for r in rows if r.resolved_by_user_id}:
        try:
            u = await User.get(uid)
        except Exception:
            u = None
        users[uid] = u.email if u else "(unknown user)"
    return [
        {
            "project_id": r.project_id,
            "project_name": names[r.project_id],
            "tagged_at": r.resolved_at,
            "tagged_by": users.get(r.resolved_by_user_id or "", None),
            "comment": r.resolution_comment,
        }
        for r in rows
    ]


async def check_rule_noisy(rule_id: str | None) -> None:
    """After a false-positive tag: if the rule crossed the Noisy threshold, tell admins - once per
    rule. Never raises; the tag that triggered it must succeed regardless."""
    if not rule_id:
        return
    try:
        min_tags, min_percent = await _thresholds()
        g = (await _aggregate_rules(rule_id)).get(rule_id)
        if not g or not _is_noisy(g["fp_tags"], g["total"], min_tags, min_percent):
            return
        try:
            await NoisyRuleAlert(rule_id=rule_id).insert()
        except DuplicateKeyError:
            return  # already notified for this rule
        from app.services import notification_service

        await notification_service.notify(
            "scan_engine.rule_noisy",
            title=f"Rule {rule_id} is noisy",
            body=(
                f"{g['fp_tags']} of {g['total']} findings ({round(100 * g['fp_tags'] / g['total'])}%) "
                f"across {len(g['projects'])} project(s) were tagged false positive."
            ),
            link="/admin/scan-engine",
            severity="warning",
        )
    except Exception:
        logger.exception("noisy-rule check failed", rule_id=rule_id)


# --- working copy: retire / restore -------------------------------------------------------------


def _check_rule_id(rule_id: str) -> None:
    if not _ANY_RULE_ID_RE.match(rule_id):
        raise _bad("Invalid rule id")


async def _set_override(rule_id: str, state: str, reason: str, user: User) -> RuleOverride:
    _check_rule_id(rule_id)
    row = await RuleOverride.find_one(RuleOverride.rule_id == rule_id)
    if row is None:
        row = RuleOverride(rule_id=rule_id, state=state, reason=reason, updated_by=str(user.id))
        await row.insert()
    else:
        row.state, row.reason, row.updated_by = state, reason, str(user.id)
        row.updated_at = datetime.now(timezone.utc)
        await row.save()
    return row


async def retire_rule(rule_id: str, reason: str, user: User) -> None:
    if not reason.strip():
        raise _bad("A reason is required to retire a rule")
    await _set_override(rule_id, "retired", reason.strip(), user)
    await audit_service.record(
        "Scan Engine Rule Retired",
        actor_user_id=str(user.id),
        target_type="scanner_rule",
        target_id=rule_id,
        metadata={"reason": reason.strip(), "draft": True},
    )


async def restore_rule(rule_id: str, user: User) -> None:
    row = await RuleOverride.find_one(RuleOverride.rule_id == rule_id)
    if row is None or row.state != "retired":
        raise _bad("Rule is not retired", status.HTTP_409_CONFLICT)
    await _set_override(rule_id, "active", "restored", user)
    await audit_service.record(
        "Scan Engine Rule Restored",
        actor_user_id=str(user.id),
        target_type="scanner_rule",
        target_id=rule_id,
        metadata={"draft": True},
    )


# --- custom rules -------------------------------------------------------------------------------


async def _run_scanner_on(sample_dir: str, rules_dir: str) -> set[str]:
    from app.services import cloud_scan_service

    cmd = [settings.scanner_binary_path, "scan", sample_dir, "--format", "json", "--extra-rules", rules_dir]
    try:
        rc, out, err = await cloud_scan_service._run(cmd, _VALIDATE_TIMEOUT_S)
    except cloud_scan_service.CloudScanError as exc:
        raise _bad(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    if rc not in (0, 1):
        detail = err.decode(errors="replace").strip()[-600:] or f"scanner exited {rc}"
        raise _bad(f"The scanner rejected this rule: {detail}")
    report = GoReportIn.model_validate_json(out)
    return {f.rule_id for f in report.findings if f.rule_id}


async def validate_custom_rule(yaml_text: str, vulnerable: str, safe: str) -> tuple[str, str]:
    """Return (rule_id, language) once the rule passes the scanner's own validator, fires on the
    vulnerable sample and stays silent on the safe one. Raises 422 with the reason otherwise."""
    for label, text in (("Rule YAML", yaml_text), ("Vulnerable sample", vulnerable), ("Safe sample", safe)):
        if not text.strip():
            raise _bad(f"{label} is required")
        if len(text) > _MAX_TEXT:
            raise _bad(f"{label} is too long (max {_MAX_TEXT} characters)")
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise _bad(f"Rule YAML is not valid: {exc}") from exc
    if not isinstance(doc, dict):
        raise _bad("Rule YAML must be a mapping")
    rule_id, language = str(doc.get("id", "")), str(doc.get("language", ""))
    if not CUSTOM_RULE_ID_RE.match(rule_id):
        raise _bad("Rule id must match ZS-CUSTOM-[A-Z0-9-]+")
    ext = _EXT.get(language)
    if ext is None:
        raise _bad(f"Unsupported rule language {language!r}; use one of {', '.join(sorted(_EXT))}")

    with tempfile.TemporaryDirectory(prefix="zs-rule-check-") as tmp:
        rules_dir = os.path.join(tmp, "rules")
        os.makedirs(rules_dir)
        with open(os.path.join(rules_dir, f"{rule_id}.yaml"), "w", encoding="utf-8") as fh:
            fh.write(yaml_text)
        fired: dict[str, set[str]] = {}
        for name, code in (("vulnerable", vulnerable), ("safe", safe)):
            sample_dir = os.path.join(tmp, name)
            os.makedirs(sample_dir)
            with open(os.path.join(sample_dir, f"sample.{ext}"), "w", encoding="utf-8") as fh:
                fh.write(code)
            fired[name] = await _run_scanner_on(sample_dir, rules_dir)
    if rule_id not in fired["vulnerable"]:
        raise _bad("The rule did not fire on the vulnerable sample")
    if rule_id in fired["safe"]:
        raise _bad("The rule fired on the safe sample (false positive)")
    return rule_id, language


async def save_custom_rule(yaml_text: str, vulnerable: str, safe: str, user: User) -> CustomRule:
    rule_id, language = await validate_custom_rule(yaml_text, vulnerable, safe)
    now = datetime.now(timezone.utc)
    row = await CustomRule.find_one(CustomRule.rule_id == rule_id)
    edited = row is not None
    if row is None:
        row = CustomRule(
            rule_id=rule_id, yaml=yaml_text, vulnerable_sample=vulnerable, safe_sample=safe,
            language=language, last_validated_at=now, created_by=str(user.id),
        )
        await row.insert()
    else:
        row.yaml, row.vulnerable_sample, row.safe_sample = yaml_text, vulnerable, safe
        row.language, row.last_validated_at = language, now
        await row.save()
    await audit_service.record(
        "Scan Engine Custom Rule Saved",
        actor_user_id=str(user.id),
        target_type="scanner_rule",
        target_id=rule_id,
        metadata={"edited": edited, "language": language, "draft": True},
    )
    return row


async def delete_custom_rule(rule_id: str, user: User) -> None:
    row = await CustomRule.find_one(CustomRule.rule_id == rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom rule not found")
    await row.delete()
    await audit_service.record(
        "Scan Engine Custom Rule Deleted",
        actor_user_id=str(user.id),
        target_type="scanner_rule",
        target_id=rule_id,
        metadata={"draft": True},
    )


# --- draft, publish, roll back ------------------------------------------------------------------


async def _working_copy() -> tuple[list[str], list[PackCustomRule]]:
    retired = sorted(o.rule_id for o in await RuleOverride.find(RuleOverride.state == "retired").to_list())
    customs = [
        PackCustomRule(
            rule_id=c.rule_id, yaml=c.yaml, language=c.language,
            vulnerable_sample=c.vulnerable_sample, safe_sample=c.safe_sample,
        )
        for c in sorted(await CustomRule.find_all().to_list(), key=lambda c: c.rule_id)
    ]
    return retired, customs


async def pending_changes() -> dict:
    """The draft: working copy vs the active pack."""
    retired, customs = await _working_copy()
    pack = await active_pack()
    base_retired = set(pack.retired_rule_ids) if pack else set()
    base_custom = {r.rule_id: r.yaml for r in (pack.custom_rules if pack else [])}
    now_custom = {c.rule_id: c.yaml for c in customs}
    return {
        "retired": sorted(set(retired) - base_retired),
        "restored": sorted(base_retired - set(retired)),
        "custom_added": sorted(set(now_custom) - set(base_custom)),
        "custom_edited": sorted(r for r in now_custom if r in base_custom and now_custom[r] != base_custom[r]),
        "custom_removed": sorted(set(base_custom) - set(now_custom)),
    }


def has_changes(changes: dict) -> bool:
    return any(changes.values())


async def _insert_next_version(
    retired: list[str], customs: list[PackCustomRule], changelog: str, user: User, rolled_back_from: int | None
) -> RulePackVersion:
    current = await active_pack()
    pack = RulePackVersion(
        version=(current.version if current else 0) + 1,
        retired_rule_ids=retired,
        custom_rules=customs,
        changelog=changelog,
        published_by=str(user.id),
        rolled_back_from=rolled_back_from,
    )
    try:
        await pack.insert()
    except DuplicateKeyError as exc:
        # Another admin published the same number first: the unique index decides, we do not retry.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another version was published at the same time. Refresh and try again."
        ) from exc
    return pack


async def publish(changelog: str, user: User) -> RulePackVersion:
    if not changelog.strip():
        raise _bad("A changelog line is required to publish")
    changes = await pending_changes()
    if not has_changes(changes):
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no pending changes to publish")
    retired, customs = await _working_copy()
    pack = await _insert_next_version(retired, customs, changelog.strip(), user, None)
    await audit_service.record(
        "Scan Engine Rule Pack Published",
        actor_user_id=str(user.id),
        target_type="rule_pack",
        target_id=str(pack.version),
        metadata={"version": pack.version, "changelog": pack.changelog, "changes": changes},
    )
    return pack


async def get_version(version: int) -> RulePackVersion:
    pack = await RulePackVersion.find_one(RulePackVersion.version == version)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule pack version not found")
    return pack


async def roll_back(version: int, changelog: str | None, user: User) -> RulePackVersion:
    """Re-publish an older version's contents as a new version; history is never rewritten. The
    working copy is reset to match, so the draft starts clean."""
    target = await get_version(version)
    # Insert first: a lost publish race (409) must not leave the working copy already reset.
    pack = await _insert_next_version(
        list(target.retired_rule_ids),
        list(target.custom_rules),
        (changelog or "").strip() or f"Rolled back to version {version}",
        user,
        version,
    )
    await RuleOverride.find_all().delete()
    await CustomRule.find_all().delete()
    now = datetime.now(timezone.utc)
    for rid in target.retired_rule_ids:
        await RuleOverride(
            rule_id=rid, state="retired", reason=f"rolled back to version {version}", updated_by=str(user.id)
        ).insert()
    for r in target.custom_rules:
        await CustomRule(
            rule_id=r.rule_id, yaml=r.yaml, vulnerable_sample=r.vulnerable_sample, safe_sample=r.safe_sample,
            language=r.language, last_validated_at=now, created_by=str(user.id),
        ).insert()
    await audit_service.record(
        "Scan Engine Rule Pack Rolled Back",
        actor_user_id=str(user.id),
        target_type="rule_pack",
        target_id=str(pack.version),
        metadata={"version": pack.version, "rolled_back_from": version},
    )
    return pack


async def update_thresholds(min_fp_tags: int, min_fp_percent: int, user: User) -> None:
    await workspace_settings_service.update_workspace_settings(
        updated_by=str(user.id), noisy_rule_min_fp_tags=min_fp_tags, noisy_rule_min_fp_percent=min_fp_percent
    )
    await audit_service.record(
        "Scan Engine Thresholds Updated",
        actor_user_id=str(user.id),
        metadata={"min_fp_tags": min_fp_tags, "min_fp_percent": min_fp_percent},
    )
