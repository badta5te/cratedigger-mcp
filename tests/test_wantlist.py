"""discogs_list_wantlist: what is on the Owner's Wantlist."""

import copy
from datetime import timedelta
from typing import Any

import pytest
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
        "Funk / Soul, Pop (Ballad, Soul) · added 2026-11-02 [release_id=26304263]\n"
        '2. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Maxi-Single, '
        "Stereo · RCA – PT 41 448 · Electronic, Pop (Dance-pop, Synth-pop, Hi NRG) · "
        "added 2026-10-21 [release_id=995860]\n"
        '3. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 · Electronic, Pop (Synth-pop) · added 2026-09-09 "
        "[release_id=221824]\n"
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


def wants_pages(discogs: FakeDiscogs) -> list[str]:
    """The Wantlist pages requested so far, by number."""
    return [r.url.params["page"] for r in discogs.requests if r.url.path.endswith("/wants")]


async def test_a_want_added_on_discogs_shows_at_once(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await list_wantlist(client)
    added = copy.deepcopy(discogs.wantlist[0])
    added["id"] = added["basic_information"]["id"] = 7_000_001
    added["basic_information"]["title"] = "Just Added"
    added["date_added"] = "2026-11-20T11:59:00+00:00"
    discogs.wantlist.insert(0, added)

    text = await list_wantlist(client)

    assert text.splitlines()[0].endswith(": page 1 of 1 (4 Wants)")
    assert text.splitlines()[1].startswith("1. Rick Astley — Just Added · ")


async def test_a_want_removed_past_the_first_page_disappears_at_once(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(150)
    await list_wantlist(client)
    removed = discogs.wantlist.pop()
    discogs.requests.clear()

    text = await list_wantlist(client, limit=50, page=4)

    assert wants_pages(discogs) == ["1", "2"]
    assert text.splitlines()[0].endswith(": page 4 of 4 (152 Wants)")
    assert removed["basic_information"]["title"] not in text


async def test_an_unchanged_wantlist_costs_one_request(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(200)
    await list_wantlist(client)
    discogs.requests.clear()

    text = await list_wantlist(client, query="filler 199")

    assert [request.url.path for request in discogs.requests] == ["/users/example-owner/wants"]
    assert wants_pages(discogs) == ["1"]
    assert "1. Rick Astley — Filler 199 · " in text


async def test_the_whole_wantlist_is_fetched_again_every_5_minutes_however_often_asked(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    discogs.add_wants(200)
    await list_wantlist(client)
    clock.advance(timedelta(minutes=4))
    await list_wantlist(client)
    discogs.requests.clear()
    clock.advance(timedelta(minutes=2))

    await list_wantlist(client)

    assert wants_pages(discogs) == ["1", "2", "3"]
    assert "/oauth/identity" not in [request.url.path for request in discogs.requests]


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
        "Stereo · RCA – PT 41 448 · Electronic, Pop (Dance-pop, Synth-pop, Hi NRG) · "
        "added 2026-10-21 [release_id=995860]",
        '2. Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Single, '
        "Lyntone/Damont · RCA – PT 41448 · Electronic, Pop (Synth-pop) · added 2026-09-09 "
        "[release_id=221824]",
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


async def test_a_failed_check_keeps_the_snapshot(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.add_wants(200)
    await list_wantlist(client)
    discogs.failing_status = 502
    is_error, _ = await call_tool_text(client, "discogs_list_wantlist", {})
    assert is_error
    discogs.failing_status = None
    discogs.requests.clear()

    await list_wantlist(client)

    assert wants_pages(discogs) == ["1"]


async def test_genre_keeps_wants_with_a_matching_discogs_genre_or_style(
    client: Client[Any],
) -> None:
    by_style = await list_wantlist(client, genre="SYNTH-POP")
    by_genre = await list_wantlist(client, genre="pop")
    pop_as_text = await list_wantlist(client, query="pop")

    assert by_style.splitlines()[0] == (
        'Wantlist of example-owner, genre "SYNTH-POP", newest first: page 1 of 1 (2 Wants)'
    )
    assert "[release_id=995860]" in by_style
    assert "[release_id=221824]" in by_style
    assert "[release_id=26304263]" not in by_style
    assert "(3 Wants)" in by_genre.splitlines()[0]
    assert pop_as_text.startswith('No Wants on the Wantlist of example-owner match "pop".')


@pytest.mark.parametrize(
    "spelling", ["Drum n Bass", "drum and bass", "Drum & Bass", "drum'n'bass", "DnB", "d&b"]
)
async def test_genre_takes_the_usual_spellings_of_a_discogs_style(
    client: Client[Any], discogs: FakeDiscogs, spelling: str
) -> None:
    discogs.wantlist[0]["basic_information"]["styles"] = ["Drum n Bass", "Neurofunk"]

    text = await list_wantlist(client, genre=spelling)

    assert "(1 Want)" in text.splitlines()[0]
    assert "(Drum n Bass, Neurofunk) · added 2026-11-02 [release_id=26304263]" in text


async def test_genre_matches_whole_words_of_a_genre_or_style(client: Client[Any]) -> None:
    text = await list_wantlist(client, genre="electro")

    assert text.startswith('No Wants on the Wantlist of example-owner match genre "electro".')


async def test_a_genre_matching_nothing_lists_the_genres_and_styles_on_the_wantlist(
    client: Client[Any],
) -> None:
    text = await list_wantlist(client, genre="jazz")

    assert text.splitlines()[0] == (
        'No Wants on the Wantlist of example-owner match genre "jazz". '
        "Genres on the Wantlist: Pop (3), Electronic (2), Funk / Soul (1). "
        "Styles: Synth-pop (2), Ballad (1), Dance-pop (1), Hi NRG (1), Soul (1). "
        "Ask again with one of these as the genre."
    )


@pytest.mark.parametrize(("spelling", "wants"), [("synthpop", 2), ("FUNKSOUL", 1)])
async def test_genre_matches_a_style_written_as_one_word(
    client: Client[Any], spelling: str, wants: int
) -> None:
    text = await list_wantlist(client, genre=spelling)

    assert f"({wants} Want" in text.splitlines()[0]


async def test_a_genre_of_punctuation_only_matches_nothing(client: Client[Any]) -> None:
    text = await list_wantlist(client, genre="!!!")

    assert text.startswith('No Wants on the Wantlist of example-owner match genre "!!!". Genres')
