"""discogs_list_master_releases: comparing the Releases of a Master."""

from datetime import timedelta
from typing import Any

from fastmcp import Client

from tests.conftest import TEST_TOKEN, FakeClock, FakeDiscogs, call_tool_text


async def list_releases(client: Client[Any], master_id: int = 96559, **arguments: Any) -> str:
    is_error, text = await call_tool_text(
        client, "discogs_list_master_releases", {"master_id": master_id, **arguments}
    )
    assert not is_error, text
    return text


async def test_releases_of_a_master_carry_the_release_ids(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await list_releases(client)

    assert text == (
        "Releases of the Master Never Gonna Give You Up — Rick Astley (1987) [master_id=96559], "
        "sorted by release date: page 1 of 4 (67 Releases)\n"
        '1. 1987 · UK · RCA – PB 41447 · Vinyl, 7", 45 RPM, Single [release_id=12442839]\n'
        '2. 1987 · US · RCA Victor – 6784-1-RD · Vinyl, 12", 33 ⅓ RPM, Maxi-Single '
        "[release_id=182213]\n"
        '3. 1987 · Greece · RCA – RCA 4101 · Vinyl, 12" [release_id=2733429]\n'
        "\n"
        "Showing 1–3 of 67. Use page=2 for more. "
        "Use discogs_get_release with a release_id for the full card.\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/master/96559-Rick-Astley-Never-Gonna-Give-You-Up"
    )
    versions = discogs.requests[-1]
    assert versions.url.path == "/masters/96559/versions"
    assert dict(versions.url.params) == {
        "sort": "released",
        "sort_order": "asc",
        "per_page": "20",
        "page": "1",
    }


async def test_filters_and_sort_narrow_the_list_on_discogs(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await list_releases(client, format="Vinyl", country="UK", year=1987, sort="catno")

    versions = discogs.requests[-1]
    assert dict(versions.url.params) == {
        "format": "Vinyl",
        "country": "UK",
        "released": "1987",
        "sort": "catno",
        "sort_order": "asc",
        "per_page": "20",
        "page": "1",
    }
    assert text.startswith(
        "Releases of the Master Never Gonna Give You Up — Rick Astley (1987) [master_id=96559], "
        "format=Vinyl, country=UK, year=1987, sorted by catalog number: page 1 of 4"
    )


async def test_later_pages_continue_the_numbering(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await list_releases(client, limit=3, page=2)

    params = discogs.requests[-1].url.params
    assert (params["per_page"], params["page"]) == ("3", "2")
    assert "page 2 of 23 (67 Releases)\n4. 1987 · UK · RCA" in text
    assert "\nShowing 4–6 of 67. Use page=3 for more. " in text


async def test_last_page_has_no_next_page_hint(client: Client[Any], discogs: FakeDiscogs) -> None:
    captured = discogs.master_releases[96559]
    captured["versions"] = captured["versions"][:1]

    text = await list_releases(client, limit=3, page=23)

    assert "page 23 of 23 (67 Releases)" in text
    assert "\nShowing 67–67 of 67. Use discogs_get_release" in text
    assert "Use page=" not in text


async def test_unknown_master_suggests_searching_for_it(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    # Discogs lists every Release in its database for an unknown Master's versions.
    is_error, text = await call_tool_text(
        client, "discogs_list_master_releases", {"master_id": 999999999}
    )

    assert is_error
    assert text == (
        "Master 999999999 not found on Discogs. "
        'Use discogs_search with type="master" to find the master_id.'
    )


async def test_rejected_token_says_what_to_fix(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(
        client, "discogs_list_master_releases", {"master_id": 96559}
    )

    assert is_error
    assert "Check DISCOGS_TOKEN" in text
    assert TEST_TOKEN not in text


async def test_no_matching_releases_is_a_normal_answer(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    captured = discogs.master_releases[96559]
    captured["pagination"]["items"] = 0
    captured["versions"] = []

    text = await list_releases(client, format="Cassette", country="Peru")

    assert text == (
        "No Releases of the Master Never Gonna Give You Up — Rick Astley (1987) "
        "[master_id=96559] match format=Cassette, country=Peru. Filter values are exact and "
        "case-sensitive, as Discogs writes them (Vinyl, CD, UK): check them or use fewer "
        "filters.\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/master/96559-Rick-Astley-Never-Gonna-Give-You-Up"
    )


async def test_page_past_the_end_is_an_answer_not_an_error(client: Client[Any]) -> None:
    # Discogs answers HTTP 200 with no Releases for a page past the last one.
    text = await list_releases(client, limit=3, page=99)

    assert text == (
        "No Releases on page 99: the list has 23 pages of 3. Use a lower page.\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/master/96559-Rick-Astley-Never-Gonna-Give-You-Up"
    )


async def test_release_titled_apart_from_its_master_shows_its_title(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.master_releases[96559]["versions"] = [
        {
            "id": 1570630,
            "title": "Original Hit Singles",
            "label": "RCA",
            "catno": "PD 42639",
            "country": "UK & Europe",
            "released": "1989",
            "major_formats": ["CD"],
            "format": "Mini, Single",
        },
        {"id": 7, "title": "Never Gonna Give You Up", "released": "0", "major_formats": []},
    ]

    text = await list_releases(client)

    assert (
        "\n1. Original Hit Singles · 1989 · UK & Europe · RCA – PD 42639 · CD, Mini, Single "
        "[release_id=1570630]\n2. [release_id=7]\n"
    ) in text


async def test_same_list_within_an_hour_makes_no_request(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    first = await list_releases(client, format="Vinyl", page=2)
    assert [request.url.path for request in discogs.requests] == [
        "/masters/96559",
        "/masters/96559/versions",
    ]
    clock.advance(timedelta(minutes=59))

    second = await list_releases(client, format="Vinyl", page=2)

    assert second == first
    assert len(discogs.requests) == 2


async def test_another_page_or_filter_reuses_the_master_lookup(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await list_releases(client)
    await list_releases(client, page=2)
    await list_releases(client, country="UK")

    assert [request.url.path for request in discogs.requests] == [
        "/masters/96559",
        "/masters/96559/versions",
        "/masters/96559/versions",
        "/masters/96559/versions",
    ]


async def test_same_list_after_an_hour_is_fetched_again(
    client: Client[Any], discogs: FakeDiscogs, clock: FakeClock
) -> None:
    await list_releases(client)
    clock.advance(timedelta(minutes=61))
    await list_releases(client)

    assert len(discogs.requests) == 4
