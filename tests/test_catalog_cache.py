"""Catalog lookups are cached in memory, so repeated questions cost no Discogs requests."""

from datetime import timedelta
from typing import Any

from fastmcp import Client

from tests.conftest import FakeClock, FakeDiscogs, call_tool_text


async def get_release(client: Client[Any], release_id: int, **arguments: Any) -> str:
    is_error, text = await call_tool_text(
        client, "discogs_get_release", {"release_id": release_id, **arguments}
    )
    assert not is_error, text
    return text


async def test_same_release_within_an_hour_makes_no_request(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    first = await get_release(client, 249504)
    clock.advance(timedelta(minutes=59))
    second = await get_release(client, 249504)

    assert second == first
    assert len(discogs.requests) == 1


async def test_same_release_after_an_hour_is_fetched_again(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await get_release(client, 249504)
    clock.advance(timedelta(minutes=61))
    await get_release(client, 249504)

    assert len(discogs.requests) == 2


async def test_detailed_card_after_concise_reuses_the_lookup(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await get_release(client, 249504)
    detailed = await get_release(client, 249504, response_format="detailed")

    assert "Identifiers:" in detailed
    assert len(discogs.requests) == 1


async def test_different_releases_are_fetched_separately(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await get_release(client, 249504)
    await get_release(client, 1621435)

    assert len(discogs.requests) == 2


async def test_failed_lookup_is_not_cached(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.failing_status = 502
    is_error, _ = await call_tool_text(client, "discogs_get_release", {"release_id": 249504})
    assert is_error
    discogs.failing_status = None

    await get_release(client, 249504)

    assert len(discogs.requests) == 2


async def test_the_hour_counts_from_when_discogs_answered(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.throttled_requests = 1  # the first lookup waits before its retry succeeds
    await get_release(client, 249504)
    answered_at = clock.now()
    assert len(discogs.requests) == 2

    clock.advance(timedelta(minutes=59, seconds=58))
    await get_release(client, 249504)

    assert clock.now() - answered_at < timedelta(hours=1)
    assert len(discogs.requests) == 2
