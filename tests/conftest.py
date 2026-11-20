"""Shared test harness: a fake Discogs behind an HTTP mock transport and an in-memory MCP client."""

import json
from collections.abc import AsyncIterator
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


class FakeDiscogs:
    """A fake api.discogs.com that serves fixtures and records every request it receives."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.releases: dict[int, Any] = {
            249504: load_fixture("release_249504.json"),
            1621435: load_fixture("release_1621435.json"),
        }
        self.reject_token = False
        self.failing_status: int | None = None
        self.unreachable = False
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.unreachable:
            # Echo the headers into the exception to prove they never reach Claude.
            raise httpx2.ConnectError(f"connection refused, headers={dict(request.headers)}")
        if self.reject_token:
            return httpx2.Response(401, json=load_fixture("error_401.json"))
        if self.failing_status is not None:
            return httpx2.Response(self.failing_status)
        parts = request.url.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "releases" and parts[1].isdigit():
            release = self.releases.get(int(parts[1]))
            if release is None:
                return httpx2.Response(404, json=load_fixture("error_404_release.json"))
            return httpx2.Response(200, json=release)
        return httpx2.Response(404, json={"message": "The requested resource was not found."})


@pytest.fixture
def discogs() -> FakeDiscogs:
    return FakeDiscogs()


@pytest.fixture
async def client(discogs: FakeDiscogs) -> AsyncIterator[Client[Any]]:
    server = create_server(Settings(discogs_token=TEST_TOKEN), transport=discogs.transport)
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
