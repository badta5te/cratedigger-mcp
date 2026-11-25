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

from runout_mcp.server import create_server
from runout_mcp.settings import Settings

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
    headers and answers HTTP 429 when the limit is exceeded, as Discogs documents it. Like
    Discogs (captured on issue #3), `Used` counts the requests made before the one being
    answered, so the first request of a window answers `Used: 0`, `Remaining: 60`.
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
        # Marketplace stats by release_id, as captured in EUR; the fake answers in the currency
        # asked for, keeping the captured value.
        self.marketplace_stats: dict[int, Any] = {
            249504: load_fixture("marketplace_stats_249504.json"),
            23: load_fixture("marketplace_stats_nothing_for_sale.json"),
            3341754: load_fixture("marketplace_stats_blocked.json"),
        }
        # The Owner the token belongs to; the Owner's endpoints answer 404 for any other name.
        self.identity: Any = load_fixture("identity.json")
        # Every Copy in the Collection, newest first as captured; the fake pages through them
        # and reports `pagination` for what it holds.
        self.collection: list[Any] = load_fixture("collection_folder_0_releases.json")["releases"]
        self.collection_folders: Any = load_fixture("collection_folders.json")
        self.collection_fields: Any = load_fixture("collection_fields.json")
        self.collection_value: Any = load_fixture("collection_value.json")
        # Every Want on the Wantlist, newest first as captured; served like the Collection.
        self.wantlist: list[Any] = load_fixture("wantlist.json")["wants"]
        # What the Wantlist listing serves while it lags behind the writes, as Discogs' does for
        # several seconds; None when it is current.
        self.listed_wantlist: list[Any] | None = None
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

    def _count_request(self) -> int | None:
        """Count this request in the window and return how many were counted before it; None
        when it exceeds the limit."""
        now = self.clock.now()
        self._counted_at = [at for at in self._counted_at if at > now - self.WINDOW]
        used = len(self._counted_at)
        if used >= self.RATE_LIMIT:
            return None
        self._counted_at.append(now)
        return used

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
        used = None if throttled else self._count_request()
        if used is None:
            return httpx2.Response(
                429,
                headers=self._rate_limit_headers(used=self.RATE_LIMIT),
                json={"message": "You are making requests too quickly."},
            )
        headers = self._rate_limit_headers(used=used)
        if self.failing_status is not None:
            return httpx2.Response(self.failing_status)
        if self.non_json_body is not None:
            return httpx2.Response(200, headers=headers, text=self.non_json_body)
        parts = request.url.path.strip("/").split("/")
        owner = self.identity["username"]
        if request.method != "GET":
            # Discogs takes writes to the Owner's Wantlist only from this server's tools.
            if (
                request.method in ("PUT", "DELETE")
                and len(parts) == 4
                and parts[:3] == ["users", owner, "wants"]
                and parts[3].isdigit()
            ):
                return self._write_want(request.method, int(parts[3]), headers)
            return httpx2.Response(405, headers=headers, json={"message": "Method not allowed."})
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
        if len(parts) == 3 and parts[:2] == ["marketplace", "stats"] and parts[2].isdigit():
            return self._marketplace_stats(int(parts[2]), request, headers)
        if parts == ["oauth", "identity"]:
            return httpx2.Response(200, headers=headers, json=self.identity)
        if len(parts) >= 3 and parts[0] == "users" and parts[1] == owner:
            owned = self._owner_resource(parts[2:], request, headers)
            if owned is not None:
                return owned
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

    def add_copies(self, count: int) -> None:
        """Add `count` older Copies to the Collection, copies of a captured one, so that the
        Collection spans several pages."""
        template = self.collection[-1]
        for number in range(1, count + 1):
            copy_ = copy.deepcopy(template)
            copy_["instance_id"] = 1_400_000_000 + number
            copy_["id"] = copy_["basic_information"]["id"] = 5_000_000 + number
            copy_["basic_information"]["title"] = f"Filler {number}"
            copy_["date_added"] = f"2025-01-01T00:00:{number % 60:02d}-08:00"
            self.collection.append(copy_)

    def add_wants(self, count: int) -> None:
        """Add `count` older Wants to the Wantlist, each older than the one before, copies of a
        captured one, so that the Wantlist spans several pages."""
        template = self.wantlist[-1]
        for number in range(1, count + 1):
            want = copy.deepcopy(template)
            want["id"] = want["basic_information"]["id"] = 6_000_000 + number
            want["basic_information"]["title"] = f"Filler {number}"
            added = datetime(2025, 1, 1, tzinfo=UTC) - timedelta(minutes=number)
            want["date_added"] = added.isoformat()
            self.wantlist.append(want)

    def _owner_resource(
        self, parts: list[str], request: httpx2.Request, headers: dict[str, str]
    ) -> httpx2.Response | None:
        if parts == ["collection", "folders"]:
            return httpx2.Response(200, headers=headers, json=self.collection_folders)
        if parts == ["collection", "fields"]:
            return httpx2.Response(200, headers=headers, json=self.collection_fields)
        if parts == ["collection", "value"]:
            return httpx2.Response(200, headers=headers, json=self.collection_value)
        if parts == ["collection", "folders", "0", "releases"]:
            return self._page(self.collection, "releases", request, headers)
        if parts == ["wants"]:
            listed = self.wantlist if self.listed_wantlist is None else self.listed_wantlist
            return self._page(listed, "wants", request, headers)
        return None

    def freeze_wantlist_listing(self) -> None:
        """Keep serving the Wantlist listing as it is now while writes go on changing it."""
        self.listed_wantlist = copy.deepcopy(self.wantlist)

    def _write_want(self, method: str, release_id: int, headers: dict[str, str]) -> httpx2.Response:
        """Add (PUT) or remove (DELETE) a Want, answering as Discogs did in a live check on
        2026-11-22: 201 with the Want for every PUT, 204 for a DELETE, and the same 404 for a
        DELETE of a Release not wanted and a PUT of an unknown release_id."""
        not_wanted = httpx2.Response(
            404,
            headers=headers,
            json={"message": "That release does not exist in the user's wantlist."},
        )
        wanted = next((want for want in self.wantlist if want["id"] == release_id), None)
        if method == "DELETE":
            if wanted is None:
                return not_wanted
            self.wantlist.remove(wanted)
            return httpx2.Response(204, headers=headers)
        release = self.releases.get(release_id)
        if release is None:
            return not_wanted
        if wanted is None:
            wanted = {
                "id": release_id,
                "rating": 0,
                "notes": "",
                "date_added": self.clock.now().isoformat(),
                "basic_information": {
                    "id": release_id,
                    "master_id": release.get("master_id") or 0,
                    "title": release["title"],
                    "year": release.get("year", 0),
                    "artists": release.get("artists", []),
                    "labels": release.get("labels", []),
                    "formats": release.get("formats", []),
                },
            }
            self.wantlist.insert(0, wanted)
        return httpx2.Response(201, headers=headers, json=wanted)

    def _page(
        self, entries: list[Any], key: str, request: httpx2.Request, headers: dict[str, str]
    ) -> httpx2.Response:
        """Serve one page of `entries` under `key`. Like Discogs, a page past the last one is
        HTTP 404."""
        params = request.url.params
        page = int(params.get("page", "1"))
        per_page = int(params.get("per_page", "50"))
        items = len(entries)
        pages = max(1, math.ceil(items / per_page))
        if page > pages:
            return httpx2.Response(
                404,
                headers=headers,
                json={"message": f"Page {page} is outside of valid range [1, {pages}]."},
            )
        start = (page - 1) * per_page
        return httpx2.Response(
            200,
            headers=headers,
            json={
                "pagination": {"page": page, "pages": pages, "per_page": per_page, "items": items},
                key: entries[start : start + per_page],
            },
        )

    def _marketplace_stats(
        self, release_id: int, request: httpx2.Request, headers: dict[str, str]
    ) -> httpx2.Response:
        stats = copy.deepcopy(self.marketplace_stats.get(release_id))
        if stats is None:
            return httpx2.Response(
                404, headers=headers, json=load_fixture("error_404_marketplace_stats.json")
            )
        if stats["lowest_price"] is not None:
            stats["lowest_price"]["currency"] = request.url.params.get("curr_abbr", "USD")
        return httpx2.Response(200, headers=headers, json=stats)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def discogs(clock: FakeClock) -> FakeDiscogs:
    return FakeDiscogs(clock)


@pytest.fixture
def settings() -> Settings:
    # Every value is explicit, so the developer's environment cannot leak into a test.
    return Settings(discogs_token=TEST_TOKEN, discogs_currency="EUR")


@pytest.fixture
async def client(
    settings: Settings, discogs: FakeDiscogs, clock: FakeClock
) -> AsyncIterator[Client[Any]]:
    server = create_server(settings, transport=discogs.transport, clock=clock)
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
