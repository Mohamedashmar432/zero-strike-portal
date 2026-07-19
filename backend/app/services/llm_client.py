"""Thin wrapper over litellm.acompletion, backed by whichever AIProviderConfig is
currently active (see ai_provider_config_service.get_active_config). litellm itself is
the provider abstraction (its model-string prefixes select anthropic/openai/lmstudio/
kimi/nvidia_nim/openrouter/custom) -- this module deliberately does not build a second
"provider adapter" interface on top of it.
"""

import json

import litellm
import structlog

from app.core.retry import retry_transient
from app.models.ai_provider_config import NO_KEY_REQUIRED_PROVIDERS, AIProvider
from app.services import ai_provider_config_service

logger = structlog.get_logger(__name__)

# litellm infers anthropic/openai from well-known bare model names (e.g. "claude-*"/"gpt-*"),
# but every other provider here needs to be told explicitly which backend to route to --
# either via litellm's own provider-prefix convention (nvidia_nim/openrouter are natively
# recognized) or by routing through litellm's generic OpenAI-compatible path (lmstudio/kimi/
# custom/commandcode all expose an OpenAI-compatible REST API, so litellm treats them as
# "openai" against a custom api_base). Without this, litellm raises "LLM Provider NOT
# provided" for a bare model name like "kimi-k2.6" -- it has no way to guess which backend
# that string belongs to.
_NATIVE_PREFIX_PROVIDERS = {"nvidia_nim", "openrouter", "groq"}
_OPENAI_COMPATIBLE_PROVIDERS = {"lmstudio", "kimi", "custom", "commandcode"}
# Kimi/Moonshot's and Command Code's endpoints are fixed and well-known, so admins don't need
# to type them themselves (mirrors why they aren't in the frontend's SELF_HOSTED_PROVIDERS
# base_url-required list).
_DEFAULT_BASE_URLS = {
    "kimi": "https://api.moonshot.ai/v1",
    "commandcode": "https://api.commandcode.ai/provider/v1",
}
# The openai SDK (which litellm delegates every _OPENAI_COMPATIBLE_PROVIDERS_ call to) raises
# its own AuthenticationError if api_key is None/empty -- even for a self-hosted server (e.g.
# LM Studio) that never checks it. A placeholder gets the call to the actual server so any
# real auth failure comes back as a genuine upstream error instead of this client-side one.
_PLACEHOLDER_API_KEY = "not-needed"

# Only anthropic/openai reliably honor OpenAI's `response_format={"type":"json_object"}`. Local
# and OpenAI-compatible backends often 400 on it (e.g. LM Studio: "'response_format.type' must be
# 'json_schema' or 'text'"). For everyone else we rely on the prompt asking for JSON plus tolerant
# parsing (_extract_json) -- mirrors zero-strike-cli, which uses no response_format at all.
_JSON_OBJECT_PROVIDERS = {"anthropic", "openai"}


def _extract_json(content: str) -> dict:
    """Best-effort JSON out of an LLM reply. Strips ```json / ``` fences, then takes the
    outermost {...} span (skips any prose the model added before/after), then json.loads.
    Raises LLMMalformedResponseError if nothing parseable is found -- the caller records the
    provider call as success regardless (it happened and was billed); only our parse failed."""
    text = content.strip()
    if text.startswith("```"):
        # drop the opening fence line (``` or ```json) and any trailing fence
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= start:
        raise LLMMalformedResponseError(f"LLM response contained no JSON object: {content[:200]!r}")
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        raise LLMMalformedResponseError(f"LLM response was not valid JSON: {exc}") from exc


def _ensure_v1_suffix(base_url: str) -> str:
    """Self-hosted OpenAI-compatible servers (LM Studio, Ollama, vLLM, ...) all serve their
    API under /v1, but admins commonly copy just the host:port shown in their app's UI. litellm
    naively appends /chat/completions to whatever base_url it's given, so a missing /v1 hits
    the wrong path -- the server 404s with a plain-text body litellm can't parse as a normal
    OpenAI error, surfacing as an opaque "Error in response object". Idempotent."""
    trimmed = base_url.rstrip("/")
    return trimmed if trimmed.endswith("/v1") else f"{trimmed}/v1"


def _resolve_model_and_base(
    provider: AIProvider, model_name: str, base_url: str | None
) -> tuple[str, str | None]:
    """Maps (provider, model_name) to the litellm model string and effective api_base.
    Idempotent -- if the admin already typed the expected prefix themselves, it's left as-is."""
    if provider in _NATIVE_PREFIX_PROVIDERS:
        prefix = f"{provider}/"
        model = model_name if model_name.startswith(prefix) else prefix + model_name
        return model, base_url
    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        model = model_name if model_name.startswith("openai/") else f"openai/{model_name}"
        resolved_base = base_url or _DEFAULT_BASE_URLS.get(provider)
        return model, _ensure_v1_suffix(resolved_base) if resolved_base else resolved_base
    return model_name, base_url


def _resolve_api_key(provider: AIProvider, api_key: str | None) -> str | None:
    """Substitutes a placeholder only for providers that genuinely need no key -- a hosted
    provider (kimi/commandcode/anthropic/...) missing its key still gets None, so it fails
    with a real upstream 401 rather than silently pretending to be configured."""
    if api_key:
        return api_key
    if provider in NO_KEY_REQUIRED_PROVIDERS:
        return _PLACEHOLDER_API_KEY
    return api_key


class LLMError(Exception):
    """Base class for all llm_client errors."""


class LLMNotConfiguredError(LLMError):
    """No AI provider is active/ready (see ai_provider_config_service.is_ready) --
    raised before any network call is attempted."""


class LLMTransientError(LLMError):
    """A retryable upstream failure (rate limit, connection, timeout, 5xx) that exhausted
    all retry attempts."""


class LLMPermanentError(LLMError):
    """A non-retryable upstream failure (auth, bad request, not found, permission denied) --
    raised immediately, without retrying."""


class LLMMalformedResponseError(LLMError):
    """The call succeeded but the response content was not valid JSON."""


# litellm exceptions worth retrying: transient upstream conditions that may clear on their own.
_TRANSIENT_EXCEPTIONS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)
# litellm exceptions that are deterministic -- retrying just wastes the caller's timeout budget.
_PERMANENT_EXCEPTIONS = (
    litellm.AuthenticationError,
    litellm.BadRequestError,
    litellm.NotFoundError,
    litellm.PermissionDeniedError,
)


@retry_transient(_TRANSIENT_EXCEPTIONS, max_attempts=3, base_delay=5.0)
async def _call_acompletion(**kwargs):
    return await litellm.acompletion(**kwargs)


async def _record_usage_safe(
    config_id,
    *,
    success: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    provider: str | None = None,
    model_name: str | None = None,
    project_id: str | None = None,
    scan_id: str | None = None,
) -> None:
    """Never lets a usage-write hiccup surface as an error -- by the time this is called the
    provider call itself has already succeeded or definitively failed, so a bookkeeping
    failure here must not change the outcome the caller sees."""
    try:
        await ai_provider_config_service.record_usage(
            str(config_id),
            success=success,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            provider=provider,
            model_name=model_name,
            project_id=project_id,
            scan_id=scan_id,
        )
    except Exception:
        logger.exception("failed to record llm usage", config_id=str(config_id), success=success)


async def get_completion(
    messages: list[dict],
    *,
    response_format_json: bool = True,
    max_tokens: int | None = None,
    project_id: str | None = None,
    scan_id: str | None = None,
) -> dict:
    """Resolves the active provider and returns the parsed-JSON response body.

    Fails fast with LLMNotConfiguredError (no network call) if no provider is active/ready.
    Transient upstream failures are retried (3 attempts, exponential backoff starting at 5s --
    see app.core.retry.retry_transient); auth/bad-request/not-found/permission failures are
    classified permanent and raised immediately without retrying. A response that isn't valid
    JSON raises LLMMalformedResponseError (not retried -- the call itself already succeeded,
    and is recorded as such before the parse is attempted).
    """
    config = await ai_provider_config_service.get_active_config()
    if config is None or not await ai_provider_config_service.is_ready(config):
        raise LLMNotConfiguredError("No AI provider is configured and active")

    model, api_base = _resolve_model_and_base(config.provider, config.model_name, config.base_url)
    api_key = _resolve_api_key(config.provider, ai_provider_config_service.decrypt_api_key(config))
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": config.temperature,
        "api_key": api_key,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format_json and config.provider in _JSON_OBJECT_PROVIDERS:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await _call_acompletion(**kwargs)
    except _PERMANENT_EXCEPTIONS as exc:
        logger.warning("llm call failed permanently", error=str(exc))
        await _record_usage_safe(config.id, success=False)
        raise LLMPermanentError(str(exc)) from exc
    except _TRANSIENT_EXCEPTIONS as exc:
        logger.error("llm call exhausted retries", error=str(exc))
        await _record_usage_safe(config.id, success=False)
        raise LLMTransientError(str(exc)) from exc
    except litellm.APIError as exc:
        # litellm raises the bare base APIError for statuses it doesn't map to a specific
        # subclass (e.g. a provider's 403 "upgrade_required"). Treat as permanent so the real
        # upstream message surfaces instead of escaping as an opaque 500 -- none of the mapped
        # exceptions above subclass APIError, so this never shadows them.
        logger.warning("llm call failed with unmapped api error", error=str(exc))
        await _record_usage_safe(config.id, success=False)
        raise LLMPermanentError(str(exc)) from exc

    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    try:
        cost_usd = litellm.completion_cost(completion_response=response)
    except Exception:
        logger.warning("failed to compute llm completion cost", exc_info=True)
        cost_usd = 0.0

    # The provider call succeeded and was billed regardless of what we do with the content
    # below -- record success now, before attempting to parse it.
    await _record_usage_safe(
        config.id,
        success=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        provider=config.provider,
        model_name=config.model_name,
        project_id=project_id,
        scan_id=scan_id,
    )

    content = response.choices[0].message.content or ""
    return _extract_json(content)


async def test_connection(
    *,
    provider: AIProvider,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    temperature: float = 0.0,
) -> None:
    """Pings the given provider/model/key directly, bypassing get_active_config/is_ready/
    record_usage entirely -- a test ping (whether for a draft, never-saved config or an
    existing stored one) must never count toward that provider's usage totals.
    """
    model, api_base = _resolve_model_and_base(provider, model_name, base_url)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "temperature": temperature,
        "api_key": _resolve_api_key(provider, api_key),
        "max_tokens": 5,
    }
    if api_base:
        kwargs["api_base"] = api_base

    try:
        await _call_acompletion(**kwargs)
    except _PERMANENT_EXCEPTIONS as exc:
        raise LLMPermanentError(str(exc)) from exc
    except _TRANSIENT_EXCEPTIONS as exc:
        raise LLMTransientError(str(exc)) from exc
    except litellm.APIError as exc:
        # See get_completion: unmapped base APIError (e.g. a 403 "upgrade_required") -> permanent,
        # so the test surfaces the real reason rather than a raw 500.
        raise LLMPermanentError(str(exc)) from exc
