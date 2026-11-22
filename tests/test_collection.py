"""discogs_list_collection: what is in the Owner's Collection."""

from datetime import timedelta
from typing import Any

from fastmcp import Client

from tests.conftest import FakeClock, FakeDiscogs, call_tool_text


async def list_collection(client: Client[Any], **arguments: Any) -> str:
    is_error, text = await call_tool_text(client, "discogs_list_collection", arguments)
    assert not is_error, text
    return text


async def test_copies_are_listed_newest_first_with_their_release_ids(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await list_collection(client)

    assert text == (
        "Collection of example-owner, newest first: page 1 of 1 (5 Copies)\n"
        "1. Rick Astley — Wonderful You · 1991 · CD, Single, Promo · RCA – RDJ62068-2 · "
        "added 2026-10-28 · folder CD [release_id=3499619]\n"
        "2. Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 7", 45 RPM, Single, Stereo, CBS Pressing · RCA – PB 41447 · added 2026-10-12 · '
        "folder Uncategorized [release_id=249504] · one of 2 Copies of this Release\n"
        "3. Rick Astley — Original Hit Singles · 1989 · CD, Mini, Single · RCA – PD 42639 · "
        "added 2026-09-30 · folder CD [release_id=1570630]\n"
        '4. Fishbone — Swim · 1993 · Vinyl, 12", Promo · Columbia – XPR 1948 · '
        "added 2026-09-14 · folder Records [release_id=1621435]\n"
        "5. Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 7", 45 RPM, Single, Stereo, CBS Pressing · RCA – PB 41447 · added 2026-08-02 · '
        "folder Records [release_id=249504] · one of 2 Copies of this Release\n"
        "\n"
        "Showing 1–5 of 5. Use discogs_get_release with a release_id for the full card.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/user/example-owner/collection"
    )
    assert [request.url.path for request in discogs.requests] == [
        "/oauth/identity",
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/folders/0/releases",
    ]
    assert dict(discogs.requests[-1].url.params) == {
        "per_page": "100",
        "page": "1",
        "sort": "added",
        "sort_order": "desc",
    }


async def test_the_whole_collection_is_fetched_in_pages_of_100(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_copies(200)

    text = await list_collection(client, sort="title", limit=1)

    pages = [request for request in discogs.requests if request.url.path.endswith("/releases")]
    assert [(r.url.params["per_page"], r.url.params["page"]) for r in pages] == [
        ("100", "1"),
        ("100", "2"),
        ("100", "3"),
    ]
    assert "page 1 of 205 (205 Copies)\n1. Rick Astley — Filler 1 · " in text


async def test_a_second_question_within_15_minutes_makes_no_request(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await list_collection(client)
    requests = len(discogs.requests)
    clock.advance(timedelta(minutes=14))

    await list_collection(client, query="fishbone", sort="year", limit=1, page=1)

    assert len(discogs.requests) == requests


async def test_after_15_minutes_the_collection_is_fetched_again_but_not_the_username(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await list_collection(client)
    discogs.requests.clear()
    clock.advance(timedelta(minutes=16))

    await list_collection(client)

    assert [request.url.path for request in discogs.requests] == [
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/folders/0/releases",
    ]


async def test_query_matches_artist_or_title_words_ignoring_case(client: Client[Any]) -> None:
    text = await list_collection(client, query="  NEVER astley ")

    assert text.splitlines()[0] == (
        'Collection of example-owner, Copies matching "NEVER astley", newest first: '
        "page 1 of 1 (2 Copies)"
    )
    assert text.splitlines()[1].startswith("1. Rick Astley — Never Gonna Give You Up · ")
    assert text.splitlines()[2].startswith("2. Rick Astley — Never Gonna Give You Up · ")
    assert "fishbone" not in (await list_collection(client, query="astley")).casefold()
    assert "1. Fishbone — Swim" in await list_collection(client, query="fishbone")


async def test_a_folder_keeps_marking_copies_held_elsewhere(client: Client[Any]) -> None:
    text = await list_collection(client, folder_id=1)

    assert text.splitlines()[:2] == [
        "Collection of example-owner, folder Uncategorized [folder_id=1], newest first: "
        "page 1 of 1 (1 Copy)",
        "1. Rick Astley — Never Gonna Give You Up · 1987 · "
        'Vinyl, 7", 45 RPM, Single, Stereo, CBS Pressing · RCA – PB 41447 · added 2026-10-12 '
        "[release_id=249504] · one of 2 Copies of this Release",
    ]


async def test_copies_sort_by_artist_title_or_year(client: Client[Any]) -> None:
    async def titles(sort: str) -> list[str]:
        text = await list_collection(client, sort=sort)
        return [line.split(" · ")[0].split(". ", 1)[1] for line in text.splitlines()[1:6]]

    assert await titles("artist") == [
        "Fishbone — Swim",
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Original Hit Singles",
        "Rick Astley — Wonderful You",
    ]
    assert await titles("title") == [
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Original Hit Singles",
        "Fishbone — Swim",
        "Rick Astley — Wonderful You",
    ]
    assert await titles("year") == [
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Never Gonna Give You Up",
        "Rick Astley — Original Hit Singles",
        "Rick Astley — Wonderful You",
        "Fishbone — Swim",
    ]
    assert (await list_collection(client, sort="year")).startswith(
        "Collection of example-owner, sorted by year, oldest first: "
    )


async def test_year_sort_puts_unknown_years_last(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.collection[0]["basic_information"]["year"] = 0

    text = await list_collection(client, sort="year")

    assert text.splitlines()[5].startswith("5. Rick Astley — Wonderful You · CD, ")


async def test_query_finds_artists_credited_under_another_name(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.collection[3]["basic_information"]["artists"][0]["anv"] = "Fish Bone"

    text = await list_collection(client, query="fishbone")

    assert "1. Fish Bone — Swim" in text


async def test_newest_first_compares_moments_not_text(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    # 23:30 at UTC-08:00 is later than 02:00 the next day at UTC+02:00.
    discogs.collection[0]["date_added"] = "2026-11-01T02:00:00+02:00"
    discogs.collection[1]["date_added"] = "2026-10-31T23:30:00-08:00"

    text = await list_collection(client, limit=2)

    assert "1. Rick Astley — Never Gonna Give You Up" in text
    assert "2. Rick Astley — Wonderful You" in text


async def test_later_pages_continue_the_numbering(client: Client[Any]) -> None:
    text = await list_collection(client, limit=2, page=2)

    assert text.splitlines()[0].endswith(": page 2 of 3 (5 Copies)")
    assert "\n3. Rick Astley — Original Hit Singles" in text
    assert "\n4. Fishbone — Swim" in text
    assert "\nShowing 3–4 of 5. Use page=3 for more. Use discogs_get_release" in text


async def test_limit_defaults_to_20(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.add_copies(25)

    text = await list_collection(client)

    assert text.splitlines()[0].endswith(": page 1 of 2 (30 Copies)")
    assert "\nShowing 1–20 of 30. Use page=2 for more." in text


async def test_a_page_past_the_end_says_how_many_there_are(client: Client[Any]) -> None:
    text = await list_collection(client, limit=2, page=4)

    assert text.splitlines()[0] == (
        "No Copies on page 4: the list has 3 pages of 2. Use a lower page."
    )


async def test_no_matches_is_an_answer(client: Client[Any]) -> None:
    text = await list_collection(client, query="zappa", folder_id=2000001)

    assert text == (
        'No Copies in the Collection of example-owner match "zappa" in folder CD '
        "[folder_id=2000001]. Try fewer words or another spelling.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/user/example-owner/collection"
    )


async def test_an_empty_collection_is_an_answer(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.collection = []

    text = await list_collection(client)

    assert text.splitlines()[0] == "The Collection of example-owner holds no Copies."


async def test_an_unknown_folder_lists_the_folders(client: Client[Any]) -> None:
    is_error, text = await call_tool_text(client, "discogs_list_collection", {"folder_id": 42})

    assert is_error
    assert text == (
        "Folder 42 not found in the Collection of example-owner. Its folders: All "
        "[folder_id=0], CD [folder_id=2000001], Records [folder_id=2000002], "
        "Uncategorized [folder_id=1]."
    )


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_list_collection", {})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text


async def test_a_failed_username_lookup_is_tried_again(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.failing_status = 502
    is_error, _ = await call_tool_text(client, "discogs_list_collection", {})
    assert is_error
    discogs.failing_status = None

    await list_collection(client)

    assert [request.url.path for request in discogs.requests].count("/oauth/identity") == 2
