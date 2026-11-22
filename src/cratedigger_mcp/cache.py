"""An in-memory cache with per-entry time to live.

Nothing is persisted: Discogs data lives only as long as the process (ADR-0002).
"""

from collections.abc import Awaitable, Callable, Hashable
from datetime import datetime, timedelta
from typing import Any, NamedTuple, cast

from cratedigger_mcp.clock import Clock

CATALOG_TTL = timedelta(hours=1)
PRICE_TTL = timedelta(hours=1)
COLLECTION_TTL = timedelta(minutes=15)


class _Entry(NamedTuple):
    expires_at: datetime
    value: Any


class TtlCache:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: dict[Hashable, _Entry] = {}

    async def get_or_load[T](
        self, key: Hashable, ttl: timedelta, load: Callable[[], Awaitable[T]]
    ) -> T:
        """The cached value for `key`, or the result of `load()` kept for `ttl`.

        The time to live counts from when `load()` returned, however long it waited. A failing
        `load()` caches nothing, so the next call tries again.
        """
        entry = self._entries.get(key)
        if entry is not None and self._clock.now() < entry.expires_at:
            return cast(T, entry.value)
        value = await load()
        loaded_at = self._clock.now()
        self._evict_expired(loaded_at)
        self._entries[key] = _Entry(loaded_at + ttl, value)
        return value

    def _evict_expired(self, now: datetime) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
