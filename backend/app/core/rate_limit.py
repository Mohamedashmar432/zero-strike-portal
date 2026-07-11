"""In-memory sliding-window rate limiter.

In-memory, per-process — won't coordinate across multiple replicas; move to a
Mongo-backed or Redis-backed limiter if the deployment scales horizontally
beyond one backend process. This project currently deploys as a single-VM
Docker Compose stack (see `app/core/config.py` and the project's CLAUDE.md),
so that ceiling is an accepted, documented tradeoff rather than a gap.
"""

import time
from collections.abc import Callable

from fastapi import HTTPException, status


class RateLimiter:
    """Tracks hit timestamps per key and allows up to `max_attempts` within a sliding window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        """Records a hit for `key` and returns whether it was allowed under the limit.

        Every call — allowed or not — counts as a hit, so repeatedly calling past the
        limit doesn't reset or extend the window.
        """
        now = self._clock()
        bucket = [t for t in self._hits.get(key, []) if now - t < window_seconds]
        allowed = len(bucket) < max_attempts
        bucket.append(now)
        self._hits[key] = bucket
        return allowed


limiter = RateLimiter()


def enforce(key: str, max_attempts: int, window_seconds: int) -> None:
    """Raises HTTP 429 if `key` has exceeded `max_attempts` within `window_seconds`."""
    if not limiter.check(key, max_attempts, window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
