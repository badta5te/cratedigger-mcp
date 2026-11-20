"""The Discogs client: the only module that speaks HTTP to Discogs.

It authenticates every request with the Owner's token and the project User-Agent, paces
requests on the rate-limit headers Discogs returns, waits and retries when Discogs answers
HTTP 429, maps HTTP failures to domain errors and returns typed models instead of raw JSON.
"""

import asyncio
from datetime import datetime
from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from cratedigger_mcp import __version__
from cratedigger_mcp.clock import Clock

API_URL = "https://api.discogs.com"
REPOSITORY_URL = "https://github.com/badta5te/cratedigger-mcp"
USER_AGENT = f"cratedigger-mcp/{__version__} +{REPOSITORY_URL}"
TIMEOUT_SECONDS = 30.0
# Discogs counts requests over a sliding window of this length. The limit itself is read from
# the X-Discogs-Ratelimit header, never assumed.
RATE_LIMIT_WINDOW_SECONDS = 60.0
# Pacing starts once the remaining quota drops to this share of the limit or below.
LOW_QUOTA_SHARE = 0.1
# Waits before each retry of a request Discogs rejected with HTTP 429. Bounded, so a tool call
# gives up within well under a minute instead of looping.
RETRY_DELAYS_SECONDS = (5.0, 10.0, 20.0)


class DiscogsError(Exception):
    """A Discogs request failed. The message is safe to show: it never carries the token."""


class NotFoundError(DiscogsError):
    """Discogs has no such resource (HTTP 404)."""


class UnauthorizedError(DiscogsError):
    """Discogs rejected the token (HTTP 401)."""


class RateLimitedError(DiscogsError):
    """Discogs kept answering HTTP 429 after every retry."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Artist(_Model):
    name: str
    anv: str = ""
    join: str = ""


class Label(_Model):
    name: str
    catno: str = ""


class Format(_Model):
    name: str
    qty: str = "1"
    descriptions: list[str] = Field(default_factory=list)
    text: str = ""


class Track(_Model):
    position: str = ""
    title: str = ""
    duration: str = ""


class Identifier(_Model):
    type: str
    value: str = ""
    description: str = ""


class Community(_Model):
    have: int = 0
    want: int = 0


class Release(_Model):
    id: int
    title: str
    artists: list[Artist] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    formats: list[Format] = Field(default_factory=list)
    country: str = ""
    year: int = 0
    master_id: int | None = None
    community: Community = Field(default_factory=Community)
    tracklist: list[Track] = Field(default_factory=list)
    identifiers: list[Identifier] = Field(default_factory=list)
    notes: str | None = None
    uri: str = ""


class _Pacer:
    """Slows requests down when the X-Discogs-Ratelimit-* headers report little quota left.

    With plenty of quota it never waits. Below the low mark it spreads the remaining requests
    over the window, waiting the whole window when none are left, so Discogs does not have to
    answer HTTP 429. Time spent idle counts towards the wait.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._limit: int | None = None
        self._remaining: int | None = None
        self._last_request_at: datetime | None = None

    async def wait_turn(self) -> None:
        """Wait until the next request may go out, then count it against the quota."""
        async with self._lock:  # parallel tool calls take turns, each seeing the others
            delay = self._delay()
            if delay > 0:
                await self._clock.sleep(delay)
            self._last_request_at = self._clock.now()
            if self._remaining is not None:
                self._remaining = max(0, self._remaining - 1)

    def observe(self, response: httpx2.Response) -> None:
        """Learn the quota from a response."""
        if response.status_code == 429:
            # The retry backoff takes over; pacing on top would stack the waits.
            self._remaining = None
            return
        limit = _int_header(response, "X-Discogs-Ratelimit")
        remaining = _int_header(response, "X-Discogs-Ratelimit-Remaining")
        if limit is not None and remaining is not None:
            self._limit, self._remaining = limit, remaining

    def _delay(self) -> float:
        if self._limit is None or self._remaining is None or self._last_request_at is None:
            return 0.0
        if self._remaining > self._limit * LOW_QUOTA_SHARE:
            return 0.0
        interval = RATE_LIMIT_WINDOW_SECONDS / (self._remaining + 1)
        idle = (self._clock.now() - self._last_request_at).total_seconds()
        return max(0.0, interval - idle)


def _int_header(response: httpx2.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


def build_http_client(
    token: str, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """An HTTP client preconfigured for Discogs. Tests pass a mock `transport`."""
    return httpx2.AsyncClient(
        base_url=API_URL,
        headers={
            "Authorization": f"Discogs token={token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        timeout=TIMEOUT_SECONDS,
        transport=transport,
    )


class DiscogsClient:
    """Use-case methods over the Discogs API."""

    def __init__(self, http: httpx2.AsyncClient, clock: Clock) -> None:
        self._http = http
        self._clock = clock
        self._pacer = _Pacer(clock)

    async def get_release(self, release_id: int) -> Release:
        return Release.model_validate(await self._get(f"/releases/{release_id}"))

    async def _get(self, path: str) -> Any:
        response = await self._send(path)
        for delay in RETRY_DELAYS_SECONDS:
            if response.status_code != 429:
                break
            await self._clock.sleep(delay)
            response = await self._send(path)
        if response.status_code == 429:
            raise RateLimitedError(
                "Discogs is rate-limiting requests (HTTP 429). Try again in a minute."
            )
        if response.status_code == 401:
            raise UnauthorizedError("Discogs rejected the token (HTTP 401).")
        if response.status_code == 404:
            raise NotFoundError(f"Discogs has nothing at {path} (HTTP 404).")
        if response.is_error:
            raise DiscogsError(
                f"Discogs answered HTTP {response.status_code} for {path}. Try again later."
            )
        return response.json()

    async def _send(self, path: str) -> httpx2.Response:
        await self._pacer.wait_turn()
        try:
            response = await self._http.get(path)
        except httpx2.TransportError as error:
            raise DiscogsError(
                f"Could not reach Discogs ({type(error).__name__}). Try again in a moment."
            ) from None
        self._pacer.observe(response)
        return response
