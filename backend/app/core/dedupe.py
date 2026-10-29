"""In-memory "alert at most once per window" gate.

ponytail: per-process dict. Exact on the single replica we run; with several replicas each would
alert once per window, and a restart forgets everything. Move to a Mongo TTL collection (atomic
upsert as the claim, like the digest slot) if that ever matters.
"""

import time

_MAX_KEYS = 5000


class TTLDedupe:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._group: dict[str, list[float]] = {}

    def first(self, key: str, ttl: float, *, group: str | None = None, group_cap: int | None = None) -> bool:
        """True the first time `key` is seen within `ttl` seconds (and records it). With `group`
        and `group_cap`, also refuses once `group_cap` keys have passed in that group within `ttl`:
        a public endpoint must not be able to mint unlimited distinct keys."""
        now = time.monotonic()
        if len(self._seen) > _MAX_KEYS:
            self._seen = {k: t for k, t in self._seen.items() if now - t < ttl}
        last = self._seen.get(key)
        if last is not None and now - last < ttl:
            return False
        if group is not None and group_cap is not None:
            recent = [t for t in self._group.get(group, []) if now - t < ttl]
            if len(recent) >= group_cap:
                self._group[group] = recent
                return False
            recent.append(now)
            self._group[group] = recent
        self._seen[key] = now
        return True

    def clear(self) -> None:
        self._seen.clear()
        self._group.clear()


# One shared gate for every alert kind; keys are prefixed with the event.
alerts = TTLDedupe()
