import pytest
from fastapi import HTTPException

import app.core.rate_limit as rate_limit_module
from app.core.rate_limit import RateLimiter, enforce


class _FakeClock:
    """Controllable stand-in for time.monotonic — advance() moves it forward without sleeping."""

    def __init__(self, start: float = 0.0):
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_allows_up_to_max_attempts_within_window():
    limiter = RateLimiter(clock=_FakeClock())

    for _ in range(3):
        assert limiter.check("key", max_attempts=3, window_seconds=60) is True


def test_denies_attempt_beyond_max_within_window():
    limiter = RateLimiter(clock=_FakeClock())

    for _ in range(3):
        limiter.check("key", max_attempts=3, window_seconds=60)

    assert limiter.check("key", max_attempts=3, window_seconds=60) is False


def test_window_expiry_allows_attempts_again():
    clock = _FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(3):
        limiter.check("key", max_attempts=3, window_seconds=60)
    assert limiter.check("key", max_attempts=3, window_seconds=60) is False

    clock.advance(61)  # old hits fall outside the sliding window

    assert limiter.check("key", max_attempts=3, window_seconds=60) is True


def test_keys_are_tracked_independently():
    limiter = RateLimiter(clock=_FakeClock())

    for _ in range(3):
        limiter.check("key-a", max_attempts=3, window_seconds=60)

    assert limiter.check("key-a", max_attempts=3, window_seconds=60) is False
    assert limiter.check("key-b", max_attempts=3, window_seconds=60) is True


def test_enforce_raises_429_when_limit_exceeded(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "limiter", RateLimiter(clock=_FakeClock()))

    for _ in range(2):
        enforce("login:1.2.3.4", max_attempts=2, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        enforce("login:1.2.3.4", max_attempts=2, window_seconds=60)

    assert exc_info.value.status_code == 429


def test_enforce_allows_within_limit(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "limiter", RateLimiter(clock=_FakeClock()))

    for _ in range(2):
        enforce("register:5.6.7.8", max_attempts=2, window_seconds=60)  # should not raise
