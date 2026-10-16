"""Admin "Scan Engine" API: rule statistics, retire/restore, custom rules, rule pack versions."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import require_admin
from app.models.scan_engine import CustomRule, RulePackVersion
from app.models.user import User
from app.services import scan_engine_service

router = APIRouter(prefix="/admin/scan-engine", tags=["scan-engine"], dependencies=[Depends(require_admin)])


class RetireRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CustomRuleRequest(BaseModel):
    yaml: str
    vulnerable_sample: str
    safe_sample: str


class PublishRequest(BaseModel):
    changelog: str = Field(min_length=1, max_length=500)


class RollbackRequest(BaseModel):
    changelog: str | None = Field(default=None, max_length=500)


class ThresholdsRequest(BaseModel):
    min_fp_tags: int = Field(ge=1, le=10_000)
    min_fp_percent: int = Field(ge=1, le=100)


def _custom_out(c: CustomRule) -> dict:
    return {
        "rule_id": c.rule_id,
        "language": c.language,
        "yaml": c.yaml,
        "vulnerable_sample": c.vulnerable_sample,
        "safe_sample": c.safe_sample,
        "last_validated_at": c.last_validated_at,
        "created_by": c.created_by,
    }


def _version_out(p: RulePackVersion, *, detail: bool = False) -> dict:
    out = {
        "version": p.version,
        "changelog": p.changelog,
        "published_by": p.published_by,
        "published_at": p.published_at,
        "rolled_back_from": p.rolled_back_from,
        "retired_count": len(p.retired_rule_ids),
        "custom_count": len(p.custom_rules),
    }
    if detail:
        out["retired_rule_ids"] = p.retired_rule_ids
        out["custom_rules"] = [{"rule_id": r.rule_id, "yaml": r.yaml} for r in p.custom_rules]
    return out


@router.get("/rules")
async def list_rules() -> dict:
    return await scan_engine_service.rule_stats()


@router.get("/rules/{rule_id}/history")
async def rule_history(rule_id: str) -> dict:
    return {"rule_id": rule_id, "fp_tags": await scan_engine_service.rule_fp_history(rule_id)}


@router.post("/rules/{rule_id}/retire")
async def retire_rule(rule_id: str, payload: RetireRequest, user: User = Depends(require_admin)) -> dict:
    await scan_engine_service.retire_rule(rule_id, payload.reason, user)
    return {"rule_id": rule_id, "state": "retired"}


@router.post("/rules/{rule_id}/restore")
async def restore_rule(rule_id: str, user: User = Depends(require_admin)) -> dict:
    await scan_engine_service.restore_rule(rule_id, user)
    return {"rule_id": rule_id, "state": "active"}


@router.put("/thresholds")
async def set_thresholds(payload: ThresholdsRequest, user: User = Depends(require_admin)) -> dict:
    await scan_engine_service.update_thresholds(payload.min_fp_tags, payload.min_fp_percent, user)
    return {"noisy_min_fp_tags": payload.min_fp_tags, "noisy_min_fp_percent": payload.min_fp_percent}


@router.get("/custom-rules")
async def list_custom_rules() -> list[dict]:
    rows = await CustomRule.find_all().sort("rule_id").to_list()
    return [_custom_out(c) for c in rows]


@router.post("/custom-rules")
async def save_custom_rule(payload: CustomRuleRequest, user: User = Depends(require_admin)) -> dict:
    row = await scan_engine_service.save_custom_rule(
        payload.yaml, payload.vulnerable_sample, payload.safe_sample, user
    )
    return _custom_out(row)


@router.delete("/custom-rules/{rule_id}")
async def delete_custom_rule(rule_id: str, user: User = Depends(require_admin)) -> dict:
    await scan_engine_service.delete_custom_rule(rule_id, user)
    return {"rule_id": rule_id, "deleted": True}


@router.get("/pending")
async def pending() -> dict:
    return await scan_engine_service.pending_changes()


@router.get("/versions")
async def list_versions() -> list[dict]:
    rows = await RulePackVersion.find_all().sort("-version").to_list()
    return [_version_out(p) for p in rows]


@router.get("/versions/{version}")
async def get_version(version: int) -> dict:
    return _version_out(await scan_engine_service.get_version(version), detail=True)


@router.post("/versions", status_code=201)
async def publish(payload: PublishRequest, user: User = Depends(require_admin)) -> dict:
    return _version_out(await scan_engine_service.publish(payload.changelog, user))


@router.post("/versions/{version}/rollback", status_code=201)
async def roll_back(version: int, payload: RollbackRequest, user: User = Depends(require_admin)) -> dict:
    return _version_out(await scan_engine_service.roll_back(version, payload.changelog, user))
