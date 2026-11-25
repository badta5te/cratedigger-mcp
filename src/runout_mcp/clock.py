"""Time as the server sees it: the current moment and waiting.

Everything that depends on time (rate-limit pacing, retry backoff, cache expiry) goes through a
`Clock`, so tests can drive time without real waiting.
"""

import asyncio
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current moment, timezone-aware."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait for `seconds` before returning."""
        ...


class SystemClock:
    """The real clock. Wall-clock UTC keeps advancing while the Mac sleeps, unlike a monotonic
    clock, so cache entries still expire across a sleep."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
