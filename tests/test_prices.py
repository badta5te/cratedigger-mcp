"""discogs_get_prices: what Releases cost on the Discogs Marketplace right now."""

from datetime import timedelta
from typing import Any

import pytest
from fastmcp import Client

from cratedigger_mcp.settings import Settings
from tests.conftest import TEST_TOKEN, FakeClock, FakeDiscogs, call_tool_text


async def get_prices(client: Client[Any], *release_ids: int, **arguments: Any) -> str:
    is_error, text = await call_tool_text(
        client, "discogs_get_prices", {"release_ids": list(release_ids), **arguments}
    )
    assert not is_error, text
    return text


async def test_lowest_price_and_copies_for_sale_of_a_release(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await get_prices(client, 249504)

    assert text == (
        "Marketplace prices in EUR. Lowest price: the cheapest current listing in any "
        "condition, excluding shipping; not a market value.\n"
        "release_id=249504: Lowest price 12.50 EUR · 7 for sale · checked 2026-11-20 12:00 UTC\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/sell/release/249504"
    )
    [request] = discogs.requests
    assert request.url.path == "/marketplace/stats/249504"
    assert dict(request.url.params) == {"curr_abbr": "EUR"}


async def test_nothing_for_sale_and_blocked_from_sale_are_answers(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await get_prices(client, 249504, 23, 3341754, 249504)

    assert text.splitlines()[1:] == [
        "release_id=249504: Lowest price 12.50 EUR · 7 for sale · checked 2026-11-20 12:00 UTC",
        "release_id=23: nothing for sale right now · checked 2026-11-20 12:00 UTC",
        "release_id=3341754: blocked from sale on the Discogs Marketplace · "
        "checked 2026-11-20 12:00 UTC",
        "",
        "Data provided by Discogs: https://www.discogs.com/sell/list",
    ]
    assert [request.url.path for request in discogs.requests] == [
        "/marketplace/stats/249504",
        "/marketplace/stats/23",
        "/marketplace/stats/3341754",
    ]


@pytest.mark.parametrize("settings", [Settings(discogs_token=TEST_TOKEN, discogs_currency="GBP")])
async def test_default_currency_comes_from_settings(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await get_prices(client, 249504)

    assert discogs.requests[0].url.params["curr_abbr"] == "GBP"
    assert text.startswith("Marketplace prices in GBP.")
    assert "Lowest price 12.50 GBP" in text


@pytest.mark.parametrize("settings", [Settings(discogs_token=TEST_TOKEN, discogs_currency="GBP")])
async def test_currency_can_be_chosen_per_call(client: Client[Any], discogs: FakeDiscogs) -> None:
    text = await get_prices(client, 249504, currency="JPY")

    assert discogs.requests[0].url.params["curr_abbr"] == "JPY"
    assert text.startswith("Marketplace prices in JPY.")


@pytest.mark.parametrize(
    ("arguments", "explanation"),
    [
        ({"release_ids": list(range(1, 12))}, "List should have at most 10 items"),
        ({"release_ids": []}, "List should have at least 1 item"),
        (
            {"release_ids": [249504], "currency": "XYZ"},
            "Input should be 'USD', 'GBP', 'EUR', 'CAD', 'AUD', 'JPY', 'CHF', 'MXN', 'BRL', "
            "'NZD', 'SEK' or 'ZAR'",
        ),
    ],
)
async def test_invalid_arguments_are_rejected_with_the_valid_range(
    client: Client[Any], discogs: FakeDiscogs, arguments: dict[str, Any], explanation: str
) -> None:
    is_error, text = await call_tool_text(client, "discogs_get_prices", arguments)

    assert is_error
    assert explanation in text
    assert discogs.requests == []


async def test_unknown_releases_suggest_searching_for_them(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(
        client, "discogs_get_prices", {"release_ids": [999, 249504, 998]}
    )

    assert is_error
    assert text == (
        "Releases 999, 998 not found on Discogs. Use discogs_search to find the release_id, "
        "then ask again."
    )


async def test_one_unknown_release(client: Client[Any]) -> None:
    is_error, text = await call_tool_text(client, "discogs_get_prices", {"release_ids": [999]})

    assert is_error
    assert text.startswith("Release 999 not found on Discogs. Use discogs_search")


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_get_prices", {"release_ids": [249504]})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text
    assert TEST_TOKEN not in text


async def test_cached_price_keeps_the_time_it_was_checked(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await get_prices(client, 249504)
    clock.advance(timedelta(minutes=30))

    text = await get_prices(client, 249504, 23)

    assert [request.url.path for request in discogs.requests] == [
        "/marketplace/stats/249504",
        "/marketplace/stats/23",
    ]
    assert (
        "release_id=249504: Lowest price 12.50 EUR · 7 for sale · checked 2026-11-20 12:00" in text
    )
    assert "release_id=23: nothing for sale right now · checked 2026-11-20 12:30 UTC" in text


async def test_another_currency_is_checked_separately(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await get_prices(client, 249504)
    await get_prices(client, 249504, currency="USD")
    await get_prices(client, 249504, currency="EUR")

    assert [request.url.params["curr_abbr"] for request in discogs.requests] == ["EUR", "USD"]


async def test_price_after_an_hour_is_checked_again(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await get_prices(client, 249504)
    clock.advance(timedelta(minutes=61))

    text = await get_prices(client, 249504)

    assert len(discogs.requests) == 2
    assert "checked 2026-11-20 13:01 UTC" in text


async def test_asking_again_without_the_unknown_release_reuses_the_found_prices(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, _ = await call_tool_text(client, "discogs_get_prices", {"release_ids": [249504, 999]})
    assert is_error

    await get_prices(client, 249504)

    assert len(discogs.requests) == 2
