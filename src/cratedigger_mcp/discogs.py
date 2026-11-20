"""The Discogs client: the only module that speaks HTTP to Discogs.

It authenticates every request with the Owner's token and the project User-Agent, maps HTTP
failures to domain errors and returns typed models instead of raw JSON.
"""

from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from cratedigger_mcp import __version__

API_URL = "https://api.discogs.com"
REPOSITORY_URL = "https://github.com/badta5te/cratedigger-mcp"
USER_AGENT = f"cratedigger-mcp/{__version__} +{REPOSITORY_URL}"
TIMEOUT_SECONDS = 30.0


class DiscogsError(Exception):
    """A Discogs request failed. The message is safe to show: it never carries the token."""


class NotFoundError(DiscogsError):
    """Discogs has no such resource (HTTP 404)."""


class UnauthorizedError(DiscogsError):
    """Discogs rejected the token (HTTP 401)."""


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

    def __init__(self, http: httpx2.AsyncClient) -> None:
        self._http = http

    async def get_release(self, release_id: int) -> Release:
        return Release.model_validate(await self._get(f"/releases/{release_id}"))

    async def _get(self, path: str) -> Any:
        try:
            response = await self._http.get(path)
        except httpx2.TransportError as error:
            raise DiscogsError(
                f"Could not reach Discogs ({type(error).__name__}). Try again in a moment."
            ) from None
        if response.status_code == 401:
            raise UnauthorizedError("Discogs rejected the token (HTTP 401).")
        if response.status_code == 404:
            raise NotFoundError(f"Discogs has nothing at {path} (HTTP 404).")
        if response.is_error:
            raise DiscogsError(
                f"Discogs answered HTTP {response.status_code} for {path}. Try again later."
            )
        return response.json()
