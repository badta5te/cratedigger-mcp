"""How the server talks to Discogs: authentication, User-Agent and failures shown to Claude."""

from importlib.metadata import version
from typing import Any

from fastmcp import Client

from tests.conftest import TEST_TOKEN, FakeDiscogs, call_tool_text


async def call_get_release(client: Client[Any], release_id: int) -> tuple[bool, str]:
    return await call_tool_text(client, "discogs_get_release", {"release_id": release_id})


async def test_every_request_carries_the_token_and_the_project_user_agent(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await call_get_release(client, 249504)
    await call_get_release(client, 1621435)

    assert len(discogs.requests) == 2
    for request in discogs.requests:
        assert request.url.host == "api.discogs.com"
        assert request.headers["Authorization"] == f"Discogs token={TEST_TOKEN}"
        assert request.headers["User-Agent"] == (
            f"cratedigger-mcp/{version('cratedigger-mcp')} "
            "+https://github.com/badta5te/cratedigger-mcp"
        )


async def test_unknown_release_suggests_searching_first(client: Client[Any]) -> None:
    is_error, text = await call_get_release(client, 999999999)

    assert is_error
    assert text == (
        "Release 999999999 not found on Discogs. Use discogs_search to find the release_id."
    )


async def test_rejected_token_says_to_check_discogs_token(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.reject_token = True

    is_error, text = await call_get_release(client, 249504)

    assert is_error
    assert "HTTP 401" in text
    assert "Check DISCOGS_TOKEN" in text
    assert TEST_TOKEN not in text


async def test_discogs_outage_is_reported_as_a_tool_error(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.failing_status = 502

    is_error, text = await call_get_release(client, 249504)

    assert is_error
    assert text == "Discogs answered HTTP 502 for /releases/249504. Try again later."


async def test_network_failure_is_reported_without_secrets(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.unreachable = True

    is_error, text = await call_get_release(client, 249504)

    assert is_error
    assert text == "Could not reach Discogs (ConnectError). Try again in a moment."
    assert TEST_TOKEN not in text
