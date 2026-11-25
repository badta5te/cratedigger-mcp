"""An in-memory cache with per-entry time to live.

Nothing is persisted: Discogs data lives only as long as the process (ADR-0002). The Owner's
Collection and Wantlist snapshots are checked against Discogs on every call (ADR-0003).
"""

from collections.abc import Awaitable, Callable, Hashable
from datetime import datetime, timedelta
from typing import Any, NamedTuple, cast

from runout_mcp.clock import Clock

CATALOG_TTL = timedelta(hours=1)
PRICE_TTL = timedelta(hours=1)
# The longest a Collection or Wantlist snapshot is reused, however often its first page is
# confirmed unchanged: a backstop for changes that page cannot reveal (ADR-0003).
OWNER_SNAPSHOT_TTL = timedelta(minutes=5)


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
        return self._store(key, ttl, await load())

    async def revalidate[T](
        self, key: Hashable, ttl: timedelta, load: Callable[[T | None], Awaitable[T]]
    ) -> T:
        """The result of `load(previous)`, where `previous` is the live value for `key` or None.

        `load` returns `previous` itself to confirm it is still current: its time to live then
        runs on, so repeated confirmations never postpone a full reload. Any other value is kept
        for `ttl` from when `load()` returned. A failing `load()` leaves the entry as it was.
        """
        entry = self._entries.get(key)
        previous = (
            cast(T, entry.value)
            if entry is not None and self._clock.now() < entry.expires_at
            else None
        )
        value = await load(previous)
        if previous is not None and value is previous:
            return value
        return self._store(key, ttl, value)

    def drop(self, key: Hashable) -> None:
        """Forget the value for `key`, so that the next call loads it afresh."""
        self._entries.pop(key, None)

    def _store[T](self, key: Hashable, ttl: timedelta, value: T) -> T:
        """Keep `value` for `ttl` from now."""
        loaded_at = self._clock.now()
        self._evict_expired(loaded_at)
        self._entries[key] = _Entry(loaded_at + ttl, value)
        return value

    def _evict_expired(self, now: datetime) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
