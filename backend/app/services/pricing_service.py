"""What an LLM call cost (design: docs/AI_PRICING_AND_BUDGETS.md).

Precedence: the provider config's own per-million override, then litellm's price map, then
"unknown" -- never a silent $0. litellm only downloads its map once at import and falls back to a
bundled copy on failure, so refresh_loop() re-downloads it daily and an admin can force it.
"""

import asyncio
from datetime import datetime, timezone

import litellm
import structlog
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info

logger = structlog.get_logger(__name__)

_REFRESH_SECONDS = 24 * 60 * 60

# litellm downloads the map once when it is imported, which is process start -- so that is when the
# current map was loaded until the first refresh replaces it.
_state: dict = {"refreshed_at": datetime.now(timezone.utc), "source": None, "fallback_reason": None}


def status() -> dict:
    info = get_model_cost_map_source_info()
    return {
        "models": len(litellm.model_cost),
        "source": _state["source"] or info.get("source"),
        "url": litellm.model_cost_map_url,
        "refreshed_at": _state["refreshed_at"],
        "fallback_reason": _state["fallback_reason"] or info.get("fallback_reason"),
    }


async def refresh() -> dict:
    """Re-download the price map and merge it into litellm's. Never raises: a failed refresh keeps
    the map we already have, which is strictly better than an empty one."""
    try:
        fresh = await asyncio.to_thread(litellm.get_model_cost_map, litellm.model_cost_map_url)
        info = get_model_cost_map_source_info()
        # On a failed download litellm returns its bundled copy; merging that would overwrite newer
        # prices with older ones, so only a live download replaces what we have.
        if fresh and info.get("source") == "remote":
            litellm.model_cost.update(fresh)
            _state.update(refreshed_at=datetime.now(timezone.utc), source="remote", fallback_reason=None)
        else:
            _state["fallback_reason"] = info.get("fallback_reason") or "live price list unavailable"
    except Exception as exc:
        logger.warning("price map refresh failed", error=str(exc))
        _state["fallback_reason"] = f"refresh failed: {type(exc).__name__}"
    return status()


async def refresh_loop() -> None:
    # Sleep first, like the other poll loops: the import-time download already covered startup.
    while True:
        await asyncio.sleep(_REFRESH_SECONDS)
        await refresh()


def cost_of(config, response, prompt_tokens: int, completion_tokens: int) -> float | None:
    """USD for one successful call, or None when nothing can price it."""
    inp = getattr(config, "input_cost_per_million", None)
    out = getattr(config, "output_cost_per_million", None)
    if inp is not None or out is not None:
        return (prompt_tokens * (inp or 0) + completion_tokens * (out or 0)) / 1_000_000
    try:
        return float(litellm.completion_cost(completion_response=response))
    except Exception:
        logger.warning("no price for model", provider=config.provider, model=config.model_name)
        return None
