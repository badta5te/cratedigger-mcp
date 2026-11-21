"""Shared test harness: a fake Discogs behind an HTTP mock transport and an in-memory MCP client."""

import asyncio
import copy
import json
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastmcp import Client

from cratedigger_mcp.server import create_server
from cratedigger_mcp.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "discogs"
TEST_TOKEN = "test-token-6f1d2c"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class FakeClock:
    """Controllable time: sleeping advances the clock at once and is recorded."""

    def __init__(self) -> None:
        self.current = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class FakeDiscogs:
    """A fake api.discogs.com that serves fixtures and records every request it receives.

    It enforces a rate limit over a sliding window, reports it in the `X-Discogs-Ratelimit-*`
    headers and answers HTTP 429 when the limit is exceeded, as Discogs documents it.
    """

    RATE_LIMIT = 60
    WINDOW = timedelta(seconds=60)

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.requests: list[httpx2.Request] = []
        self.statuses: list[int] = []
        self._counted_at: list[datetime] = []
        self.releases: dict[int, Any] = {
            249504: load_fixture("release_249504.json"),
            1621435: load_fixture("release_1621435.json"),
        }
        # Search pages by `type`, as captured; the fake fits `pagination` to the requested page.
        self.searches: dict[str, Any] = {
            kind: load_fixture(f"search_{kind}.json")
            for kind in ("release", "master", "artist", "label")
        }
        self.masters: dict[int, Any] = {96559: load_fixture("master_96559.json")}
        # The captured first page of each Master's Releases, sorted by release date.
        self.master_releases: dict[int, Any] = {96559: load_fixture("master_versions_96559.json")}
        self.reject_token = False
        self.failing_status: int | None = None
        self.unreachable = False
        self.transport_error: httpx2.RequestError | None = None  # raised instead of answering
        self.non_json_body: str | None = None  # served with HTTP 200 instead of the fixture
        self.throttled_requests = 0  # how many upcoming requests get HTTP 429
        self.transport = httpx2.MockTransport(self._handle)

    def use_quota(self, requests: int) -> None:
        """Spend part of the rate limit now, as other clients of the same token would."""
        self._counted_at.extend([self.clock.now()] * requests)

    def add_release(self, release_id: int) -> None:
        """Serve one more Release, a copy of a fixture under another release_id."""
        self.releases[release_id] = load_fixture("release_249504.json") | {"id": release_id}

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self._respond(request)
        self.statuses.append(response.status_code)
        return response

    def _count_request(self) -> bool:
        """Count this request in the window; False when it exceeds the limit."""
        now = self.clock.now()
        self._counted_at = [at for at in self._counted_at if at > now - self.WINDOW]
        if len(self._counted_at) >= self.RATE_LIMIT:
            return False
        self._counted_at.append(now)
        return True

    def _rate_limit_headers(self, used: int) -> dict[str, str]:
        return {
            "X-Discogs-Ratelimit": str(self.RATE_LIMIT),
            "X-Discogs-Ratelimit-Used": str(used),
            "X-Discogs-Ratelimit-Remaining": str(self.RATE_LIMIT - used),
        }

    def _respond(self, request: httpx2.Request) -> httpx2.Response:
        if self.unreachable:
            # Echo the headers into the exception to prove they never reach Claude.
            raise httpx2.ConnectError(f"connection refused, headers={dict(request.headers)}")
        if self.transport_error is not None:
            raise self.transport_error
        if self.reject_token:
            return httpx2.Response(401, json=load_fixture("error_401.json"))
        throttled = self.throttled_requests > 0
        self.throttled_requests = max(0, self.throttled_requests - 1)
        if throttled or not self._count_request():
            return httpx2.Response(
                429,
                headers=self._rate_limit_headers(used=self.RATE_LIMIT),
                json={"message": "You are making requests too quickly."},
            )
        headers = self._rate_limit_headers(used=len(self._counted_at))
        if self.failing_status is not None:
            return httpx2.Response(self.failing_status)
        if self.non_json_body is not None:
            return httpx2.Response(200, headers=headers, text=self.non_json_body)
        parts = request.url.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "releases" and parts[1].isdigit():
            release = self.releases.get(int(parts[1]))
            if release is None:
                return httpx2.Response(
                    404, headers=headers, json=load_fixture("error_404_release.json")
                )
            return httpx2.Response(200, headers=headers, json=release)
        if parts == ["database", "search"]:
            return self._search(request, headers)
        if len(parts) >= 2 and parts[0] == "masters" and parts[1].isdigit():
            master_id = int(parts[1])
            if len(parts) == 2:
                master = self.masters.get(master_id)
                if master is None:
                    return httpx2.Response(
                        404, headers=headers, json=load_fixture("error_404_master.json")
                    )
                return httpx2.Response(200, headers=headers, json=master)
            if parts[2:] == ["versions"]:
                return self._master_releases(master_id, request, headers)
        return httpx2.Response(
            404, headers=headers, json={"message": "The requested resource was not found."}
        )

    def _search(self, request: httpx2.Request, headers: dict[str, str]) -> httpx2.Response:
        """Serve the captured page for the `type`, numbered as the requested page.

        Like Discogs, a page past the last one is HTTP 404.
        """
        params = request.url.params
        found = copy.deepcopy(self.searches[params.get("type", "release")])
        pagination = found["pagination"]
        page = int(params.get("page", "1"))
        per_page = int(params.get("per_page", "50"))
        pages = max(1, math.ceil(pagination["items"] / per_page))
        if page > pages:
            return httpx2.Response(
                404,
                headers=headers,
                json={"message": f"Page {page} is outside of valid range [1, {pages}]."},
            )
        pagination.update(page=page, per_page=per_page, pages=pages)
        return httpx2.Response(200, headers=headers, json=found)

    def _master_releases(
        self, master_id: int, request: httpx2.Request, headers: dict[str, str]
    ) -> httpx2.Response:
        """Serve the captured page of a Master's Releases, numbered as the requested page.

        Like Discogs, an unknown Master is not HTTP 404 here: Discogs answers with every
        Release in its database. A page past the last one is HTTP 200 with no Releases.
        """
        found = copy.deepcopy(self.master_releases.get(master_id, self.master_releases[96559]))
        pagination = found["pagination"]
        if master_id not in self.master_releases:
            pagination["items"] = 8_169_703
        params = request.url.params
        page = int(params.get("page", "1"))
        per_page = int(params.get("per_page", "50"))
        pages = max(1, math.ceil(pagination["items"] / per_page))
        if page > pages:
            found["versions"] = []
        pagination.update(page=page, per_page=per_page, pages=pages)
        return httpx2.Response(200, headers=headers, json=found)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def discogs(clock: FakeClock) -> FakeDiscogs:
    return FakeDiscogs(clock)


@pytest.fixture
async def client(discogs: FakeDiscogs, clock: FakeClock) -> AsyncIterator[Client[Any]]:
    server = create_server(
        Settings(discogs_token=TEST_TOKEN), transport=discogs.transport, clock=clock
    )
    async with Client(server) as mcp_client:
        yield mcp_client


async def call_tool_text(
    client: Client[Any], name: str, arguments: dict[str, Any]
) -> tuple[bool, str]:
    """Call a tool as Claude would and return its error flag and its single text block."""
    result = await client.call_tool(name, arguments, raise_on_error=False)
    [content] = result.content
    assert content.type == "text"
    return result.is_error, content.text
