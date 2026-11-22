"""discogs_collection_summary: the size of the Owner's Collection and what it is worth."""

from datetime import timedelta
from typing import Any

from fastmcp import Client

from tests.conftest import FakeClock, FakeDiscogs, call_tool_text


async def summary(client: Client[Any]) -> str:
    is_error, text = await call_tool_text(client, "discogs_collection_summary", {})
    assert not is_error, text
    return text


async def test_copies_per_folder_and_the_value_as_discogs_reports_it(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await summary(client)

    assert text == (
        "Collection of example-owner: 12 Copies\n"
        "Folders:\n"
        "  CD: 4 Copies [folder_id=2000001]\n"
        "  Records: 7 Copies [folder_id=2000002]\n"
        "  Uncategorized: 1 Copy [folder_id=1]\n"
        "Value estimated by Discogs: minimum $212.30 · median $486.75 · maximum $1,204.50\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/user/example-owner/collection"
    )
    assert [request.url.path for request in discogs.requests] == [
        "/oauth/identity",
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/value",
    ]


async def test_summary_is_cached_for_15_minutes(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await summary(client)
    clock.advance(timedelta(minutes=14))
    await summary(client)
    assert len(discogs.requests) == 3

    clock.advance(timedelta(minutes=2))
    await summary(client)

    assert [request.url.path for request in discogs.requests[3:]] == [
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/value",
    ]


async def test_the_username_is_looked_up_once_for_every_tool(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await summary(client)
    is_error, _ = await call_tool_text(client, "discogs_list_collection", {})
    assert not is_error

    assert [request.url.path for request in discogs.requests].count("/oauth/identity") == 1


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_collection_summary", {})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text
