"""discogs_list_wantlist: what is on the Owner's Wantlist."""

from datetime import timedelta
from typing import Any

from fastmcp import Client

from tests.conftest import FakeClock, FakeDiscogs, call_tool_text


async def list_wantlist(client: Client[Any], **arguments: Any) -> str:
    is_error, text = await call_tool_text(client, "discogs_list_wantlist", arguments)
    assert not is_error, text
    return text


async def test_wants_are_listed_newest_first_with_their_release_ids(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await list_wantlist(client)

    assert text == (
        "Wantlist of example-owner, newest first: page 1 of 1 (3 Wants)\n"
        "1. Rick Astley — First On Your Block · 1993 · Cassette, Promo · RCA – RDJ-66342-4 · "
        "added 2026-11-02 [release_id=26304263]\n"
        '2. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Maxi-Single, '
        "Stereo · RCA – PT 41 448 · added 2026-10-21 [release_id=995860]\n"
        '3. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 · added 2026-09-09 [release_id=221824]\n"
        "\n"
        "Showing 1–3 of 3. Use discogs_get_release with a release_id for the full card.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )
    assert [request.url.path for request in discogs.requests] == [
        "/oauth/identity",
        "/users/example-owner/wants",
    ]
    assert dict(discogs.requests[-1].url.params) == {
        "per_page": "100",
        "page": "1",
        "sort": "added",
        "sort_order": "desc",
    }


async def test_the_whole_wantlist_is_fetched_in_pages_of_100(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(200)

    text = await list_wantlist(client, limit=1, page=203)

    pages = [request for request in discogs.requests if request.url.path.endswith("/wants")]
    assert [(r.url.params["per_page"], r.url.params["page"]) for r in pages] == [
        ("100", "1"),
        ("100", "2"),
        ("100", "3"),
    ]
    assert "page 203 of 203 (203 Wants)\n203. Rick Astley — Filler 200 · " in text


async def test_a_second_question_within_15_minutes_makes_no_request(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await list_wantlist(client)
    requests = len(discogs.requests)
    clock.advance(timedelta(minutes=14))

    await list_wantlist(client, query="astley", limit=1, page=2)

    assert len(discogs.requests) == requests


async def test_after_15_minutes_the_wantlist_is_fetched_again_but_not_the_username(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await list_wantlist(client)
    discogs.requests.clear()
    clock.advance(timedelta(minutes=16))

    await list_wantlist(client)

    assert [request.url.path for request in discogs.requests] == ["/users/example-owner/wants"]


async def test_query_matches_artist_or_title_words_ignoring_case(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.wantlist[0]["basic_information"]["artists"][0]["anv"] = "Rick A."

    text = await list_wantlist(client, query="  GIVE astley ")
    by_credited_name = await list_wantlist(client, query="rick a. block")

    assert text.splitlines()[:3] == [
        'Wantlist of example-owner, Wants matching "GIVE astley", newest first: '
        "page 1 of 1 (2 Wants)",
        '1. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Maxi-Single, '
        "Stereo · RCA – PT 41 448 · added 2026-10-21 [release_id=995860]",
        '2. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 · added 2026-09-09 [release_id=221824]",
    ]
    assert by_credited_name.splitlines()[1].startswith("1. Rick A. — First On Your Block · ")


async def test_later_pages_continue_the_numbering(client: Client[Any]) -> None:
    text = await list_wantlist(client, limit=2, page=2)

    assert text.splitlines()[0].endswith(": page 2 of 2 (3 Wants)")
    assert "\n3. Rick Astley — Never Gonna Give You Up · " in text
    assert "\nShowing 3–3 of 3. Use discogs_get_release" in text


async def test_limit_defaults_to_20(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.add_wants(22)

    text = await list_wantlist(client)

    assert text.splitlines()[0].endswith(": page 1 of 2 (25 Wants)")
    assert "\nShowing 1–20 of 25. Use page=2 for more." in text


async def test_a_page_past_the_end_says_how_many_there_are(client: Client[Any]) -> None:
    text = await list_wantlist(client, limit=2, page=3)

    assert text.splitlines()[0] == (
        "No Wants on page 3: the list has 2 pages of 2. Use a lower page."
    )


async def test_no_matches_is_an_answer(client: Client[Any]) -> None:
    text = await list_wantlist(client, query="zappa")

    assert text == (
        'No Wants on the Wantlist of example-owner match "zappa". '
        "Try fewer words or another spelling.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )


async def test_an_empty_wantlist_is_an_answer(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.wantlist = []

    text = await list_wantlist(client)

    assert text == (
        "The Wantlist of example-owner holds no Wants.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_list_wantlist", {})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text


async def test_newest_first_compares_moments_not_text(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    # 23:30 at UTC-08:00 is later than 02:00 the next day at UTC+02:00.
    discogs.wantlist[0]["date_added"] = "2026-11-01T02:00:00+02:00"
    discogs.wantlist[1]["date_added"] = "2026-10-31T23:30:00-08:00"

    text = await list_wantlist(client, limit=2)

    assert "1. Rick Astley — Never Gonna Give You Up" in text
    assert "2. Rick Astley — First On Your Block" in text
