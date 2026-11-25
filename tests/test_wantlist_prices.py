"""discogs_wantlist_prices: which Wants are cheap on the Discogs Marketplace right now."""

from datetime import timedelta
from typing import Any

import pytest
from fastmcp import Client

from runout_mcp.settings import Settings
from tests.conftest import TEST_TOKEN, FakeClock, FakeDiscogs, call_tool_text

FIRST_ON_YOUR_BLOCK = 26304263
MAXI_SINGLE = 995860
SINGLE = 221824


def for_sale(discogs: FakeDiscogs, release_id: int, lowest: float, count: int) -> None:
    """Let the fake Marketplace offer `count` listings of the Release, the cheapest at `lowest`."""
    discogs.marketplace_stats[release_id] = {
        "num_for_sale": count,
        "lowest_price": {"value": lowest, "currency": "EUR"},
        "blocked_from_sale": False,
    }


def nothing_for_sale(discogs: FakeDiscogs, release_id: int) -> None:
    discogs.marketplace_stats[release_id] = {
        "num_for_sale": 0,
        "lowest_price": None,
        "blocked_from_sale": False,
    }


def stats_requests(discogs: FakeDiscogs) -> list[str]:
    """The release_ids whose Marketplace stats were requested so far, in order."""
    return [
        r.url.path.rsplit("/", 1)[1]
        for r in discogs.requests
        if r.url.path.startswith("/marketplace/stats/")
    ]


async def wantlist_prices(client: Client[Any], **arguments: Any) -> str:
    is_error, text = await call_tool_text(client, "discogs_wantlist_prices", arguments)
    assert not is_error, text
    return text


async def test_wants_are_sorted_cheapest_first_and_unsold_ones_listed_apart(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 12.5, 3)
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)
    nothing_for_sale(discogs, SINGLE)

    text = await wantlist_prices(client)

    assert text == (
        "Wantlist of example-owner, Lowest prices in EUR, cheapest first: "
        "Wants 1–3 of 3 checked (newest first)\n"
        "Lowest price: the cheapest current listing in any condition, excluding shipping; "
        "not a market value. Checked 2026-11-20 12:00 UTC.\n"
        "1. 4.00 EUR · 10 for sale · Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 12", 45 RPM, Maxi-Single, Stereo · RCA – PT 41 448 [release_id=995860]\n'
        "2. 12.50 EUR · 3 for sale · Rick Astley — First On Your Block · 1993 · "
        "Cassette, Promo · RCA – RDJ-66342-4 [release_id=26304263]\n"
        "\n"
        "Nothing for sale right now:\n"
        '- Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 [release_id=221824]\n"
        "\n"
        "Use discogs_get_release with a release_id for the full card.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )
    assert stats_requests(discogs) == [str(FIRST_ON_YOUR_BLOCK), str(MAXI_SINGLE), str(SINGLE)]
    assert {r.url.params["curr_abbr"] for r in discogs.requests if "curr_abbr" in r.url.params} == {
        "EUR"
    }


async def test_max_price_keeps_wants_at_or_under_it_and_counts_the_rest(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 30.01, 3)
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)
    for_sale(discogs, SINGLE, 30.0, 1)

    text = await wantlist_prices(client, max_price=30)

    assert text.splitlines()[0] == (
        "Wantlist of example-owner, Lowest prices in EUR, at or under 30.00 EUR, cheapest first: "
        "Wants 1–3 of 3 checked (newest first)"
    )
    assert text.splitlines()[2:6] == [
        "1. 4.00 EUR · 10 for sale · Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 12", 45 RPM, Maxi-Single, Stereo · RCA – PT 41 448 [release_id=995860]',
        "2. 30.00 EUR · 1 for sale · Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 12", 45 RPM, Single, Lyntone/Damont · RCA – PT 41448 [release_id=221824]',
        "1 Want costs more than 30.00 EUR.",
        "",
    ]
    assert "First On Your Block" not in text


async def test_a_page_with_nothing_under_max_price_still_says_how_to_continue(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 12.5, 3)
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)

    text = await wantlist_prices(client, max_price=1, limit=2)

    assert text.splitlines()[0].endswith(": Wants 1–2 of 3 checked (newest first)")
    assert text.splitlines()[2:] == [
        "None of these Wants is at or under 1.00 EUR: 2 Wants cost more.",
        "",
        "Use page=2 to check the next 1 Want. "
        "Use discogs_get_release with a release_id for the full card.",
        "",
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner",
    ]
    assert stats_requests(discogs) == [str(FIRST_ON_YOUR_BLOCK), str(MAXI_SINGLE)]


async def test_at_most_30_wants_are_checked_per_call_and_the_next_page_is_named(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(40)
    for number, want in enumerate(discogs.wantlist):
        for_sale(discogs, want["id"], 100.0 - number, 1)

    first = await wantlist_prices(client)
    second = await wantlist_prices(client, page=2)

    assert first.splitlines()[0].endswith(": Wants 1–30 of 43 checked (newest first)")
    assert first.splitlines()[2].startswith("1. 71.00 EUR · 1 for sale · Rick Astley — Filler 27 ")
    assert "\nUse page=2 to check the next 13 Wants. Use discogs_get_release" in first
    assert second.splitlines()[0].endswith(": Wants 31–43 of 43 checked (newest first)")
    assert second.splitlines()[2].startswith("1. 58.00 EUR · 1 for sale · Rick Astley — Filler 40 ")
    assert "Use page=" not in second
    assert len(stats_requests(discogs)) == 43


async def test_a_limit_above_30_is_rejected_with_the_limit_stated(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(client, "discogs_wantlist_prices", {"limit": 31})

    assert is_error
    assert "less than or equal to 30" in text
    assert discogs.requests == []


async def test_query_checks_only_the_matching_wants(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)
    for_sale(discogs, SINGLE, 6.0, 2)

    text = await wantlist_prices(client, query=" GIVE astley ")

    assert text.splitlines()[0] == (
        'Wantlist of example-owner, Wants matching "GIVE astley", Lowest prices in EUR, '
        "cheapest first: Wants 1–2 of 2 checked (newest first)"
    )
    assert stats_requests(discogs) == [str(MAXI_SINGLE), str(SINGLE)]


@pytest.mark.parametrize("settings", [Settings(discogs_token=TEST_TOKEN, discogs_currency="GBP")])
async def test_currency_comes_from_settings_or_the_call(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 4.0, 10)

    by_default = await wantlist_prices(client, query="block")
    chosen = await wantlist_prices(client, query="block", currency="USD", max_price=5)

    assert "Lowest prices in GBP" in by_default
    assert "1. 4.00 GBP · 10 for sale · " in by_default
    assert "Lowest prices in USD, at or under 5.00 USD" in chosen
    assert "1. 4.00 USD · 10 for sale · " in chosen
    params = [r.url.params["curr_abbr"] for r in discogs.requests if "curr_abbr" in r.url.params]
    assert params == ["GBP", "USD"]


async def test_blocked_and_unknown_releases_are_listed_with_the_unsold_ones(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.marketplace_stats[SINGLE] = {
        "num_for_sale": None,
        "lowest_price": None,
        "blocked_from_sale": True,
    }
    nothing_for_sale(discogs, MAXI_SINGLE)  # FIRST_ON_YOUR_BLOCK has no stats: HTTP 404

    text = await wantlist_prices(client)

    assert text.splitlines()[1:7] == [
        "Lowest price: the cheapest current listing in any condition, excluding shipping; "
        "not a market value. Checked 2026-11-20 12:00 UTC.",
        "",
        "Nothing for sale right now:",
        "- Rick Astley — First On Your Block · 1993 · Cassette, Promo · RCA – RDJ-66342-4 "
        "[release_id=26304263] · no Marketplace stats on Discogs",
        '- Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Maxi-Single, '
        "Stereo · RCA – PT 41 448 [release_id=995860]",
        '- Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 [release_id=221824] · blocked from sale on the "
        "Discogs Marketplace",
    ]


@pytest.mark.parametrize(
    ("arguments", "answer"),
    [
        ({"query": "zappa"}, 'No Wants on the Wantlist of example-owner match "zappa". Try fewer'),
        ({"page": 2}, "No Wants on page 2: the list has 1 pages of 30. Use a lower page."),
    ],
    ids=["no match", "past the last page"],
)
async def test_nothing_to_check_is_an_answer_without_price_requests(
    client: Client[Any], discogs: FakeDiscogs, arguments: dict[str, Any], answer: str
) -> None:
    text = await wantlist_prices(client, **arguments)

    assert text.startswith(answer)
    assert stats_requests(discogs) == []


async def test_an_empty_wantlist_is_an_answer(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.wantlist = []

    text = await wantlist_prices(client, max_price=30)

    assert text == (
        "The Wantlist of example-owner holds no Wants.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )
    assert stats_requests(discogs) == []


async def test_prices_are_shared_with_discogs_get_prices_for_an_hour(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 12.5, 3)
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)
    nothing_for_sale(discogs, SINGLE)
    await call_tool_text(client, "discogs_get_prices", {"release_ids": [MAXI_SINGLE]})
    clock.advance(timedelta(minutes=30))

    text = await wantlist_prices(client)
    _, prices = await call_tool_text(client, "discogs_get_prices", {"release_ids": [SINGLE]})

    assert stats_requests(discogs) == [str(MAXI_SINGLE), str(FIRST_ON_YOUR_BLOCK), str(SINGLE)]
    assert "Checked 2026-11-20 12:00–12:30 UTC." in text
    assert "release_id=221824: nothing for sale right now · checked 2026-11-20 12:30 UTC" in prices

    clock.advance(timedelta(minutes=31))
    await wantlist_prices(client)

    assert stats_requests(discogs)[3:] == [str(MAXI_SINGLE)]  # the one checked at 12:00


async def test_a_failed_check_is_an_error_and_keeps_the_prices_checked_before_it(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for_sale(discogs, FIRST_ON_YOUR_BLOCK, 12.5, 3)
    for_sale(discogs, MAXI_SINGLE, 4.0, 10)
    discogs.marketplace_stats[SINGLE] = {"num_for_sale": "many", "lowest_price": None}

    is_error, text = await call_tool_text(client, "discogs_wantlist_prices", {})

    assert is_error
    assert text == (
        f"Discogs sent an unexpected response for /marketplace/stats/{SINGLE}. Try again later."
    )
    nothing_for_sale(discogs, SINGLE)
    await wantlist_prices(client)
    assert stats_requests(discogs) == [
        str(FIRST_ON_YOUR_BLOCK),
        str(MAXI_SINGLE),
        str(SINGLE),
        str(SINGLE),
    ]


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_wantlist_prices", {})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text
    assert TEST_TOKEN not in text


async def test_two_full_pages_in_a_row_stay_within_the_rate_limit(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.add_wants(60)
    for want in discogs.wantlist:
        nothing_for_sale(discogs, want["id"])

    await wantlist_prices(client)
    await wantlist_prices(client, page=2)

    assert len(stats_requests(discogs)) == 60
    assert 429 not in discogs.statuses
    assert sum(clock.sleeps) < 240
