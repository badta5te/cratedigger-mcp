"""Living within the Discogs rate limit: pacing on the headers and retrying HTTP 429."""

from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastmcp import Client

from tests.conftest import TEST_TOKEN, FakeClock, FakeDiscogs, call_tool_text


async def call_get_release(client: Client[Any], release_id: int) -> tuple[bool, str]:
    return await call_tool_text(client, "discogs_get_release", {"release_id": release_id})


async def test_rate_limited_request_is_retried_after_a_wait(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.throttled_requests = 1

    is_error, text = await call_get_release(client, 249504)

    assert not is_error, text
    assert text.startswith("Never Gonna Give You Up — Rick Astley [release_id=249504]\n")
    assert len(discogs.requests) == 2
    assert sum(clock.sleeps) > 0


async def test_persistent_rate_limiting_ends_in_a_try_again_message(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.throttled_requests = 1000

    is_error, text = await call_get_release(client, 249504)

    assert is_error
    assert text == "Discogs is rate-limiting requests (HTTP 429). Try again in a minute."
    assert TEST_TOKEN not in text
    assert 2 <= len(discogs.requests) <= 5
    assert sum(clock.sleeps) <= 60


async def test_low_remaining_quota_slows_requests_down_before_discogs_says_429(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.use_quota(55)  # other clients of the token left 5 requests in this minute
    release_ids = range(1, 11)
    for release_id in release_ids:
        discogs.add_release(release_id)

    for release_id in release_ids:
        is_error, text = await call_get_release(client, release_id)
        assert not is_error, text

    assert 429 not in discogs.statuses
    assert sum(clock.sleeps) > 0


@pytest.mark.parametrize(
    "used_by_others", [0, FakeDiscogs.RATE_LIMIT - 2, FakeDiscogs.RATE_LIMIT - 1]
)
async def test_running_out_of_the_window_waits_instead_of_drawing_a_429(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock, used_by_others: int
) -> None:
    discogs.use_quota(used_by_others)  # other clients of the token spent part of this minute
    release_ids = range(1, FakeDiscogs.RATE_LIMIT - used_by_others + 3)  # past the window's end
    for release_id in release_ids:
        discogs.add_release(release_id)

    for release_id in release_ids:
        is_error, text = await call_get_release(client, release_id)
        assert not is_error, text

    assert 429 not in discogs.statuses
    assert sum(clock.sleeps) > 0


async def test_ample_quota_means_no_waiting(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    release_ids = range(1, 21)
    for release_id in release_ids:
        discogs.add_release(release_id)

    for release_id in release_ids:
        is_error, text = await call_get_release(client, release_id)
        assert not is_error, text

    assert clock.sleeps == []


async def test_quota_recovered_while_idle_means_no_waiting(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.use_quota(58)
    await call_get_release(client, 249504)  # Discogs reports Remaining 2: 1 request left
    clock.advance(timedelta(minutes=2))

    is_error, text = await call_get_release(client, 1621435)

    assert not is_error, text
    assert clock.sleeps == []


async def test_fake_discogs_counts_the_requests_before_the_current_one(
    discogs: FakeDiscogs,
) -> None:
    # As Discogs answered in the capture recorded on issue #3.
    async with httpx2.AsyncClient(
        transport=discogs.transport, base_url="https://api.discogs.com"
    ) as http:
        responses = [await http.get("/releases/249504") for _ in range(61)]

    def quota(number: int) -> tuple[str, str]:
        headers = responses[number - 1].headers
        return headers["X-Discogs-Ratelimit-Used"], headers["X-Discogs-Ratelimit-Remaining"]

    assert quota(1) == ("0", "60")
    assert quota(10) == ("9", "51")
    assert quota(60) == ("59", "1")
    assert responses[59].status_code == 200
    assert responses[60].status_code == 429
