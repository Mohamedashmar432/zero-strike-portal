"""Shared retry/backoff policy for external calls that fail transiently far more often
than the rest of this codebase's calls (git network errors today; LLM provider calls
once AI analysis lands). Retries only exceptions explicitly marked as transient by the
caller -- this is not a blanket retry-on-any-failure policy, since re-attempting a
deterministic failure (bad auth, bad URL) just wastes the caller's timeout budget.
"""

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def retry_transient(exception_types, max_attempts: int = 3, base_delay: float = 2.0):
    """Retry on `exception_types` with exponential backoff (base_delay, base_delay*2, ...).
    Works on both sync and async callables. Re-raises the last exception once attempts
    are exhausted; anything not in `exception_types` propagates immediately."""
    return retry(
        retry=retry_if_exception_type(exception_types),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=base_delay, min=base_delay),
        reraise=True,
    )
