"""discogs_match_collection: which albums from another source the Owner has or wants."""

import copy
from typing import Any

import pytest
from fastmcp import Client

from tests.conftest import FakeDiscogs, call_tool_text


async def match(client: Client[Any], *albums: tuple[str, str]) -> str:
    arguments = {"albums": [{"artist": artist, "title": title} for artist, title in albums]}
    is_error, text = await call_tool_text(client, "discogs_match_collection", arguments)
    assert not is_error, text
    return text


async def test_an_album_counts_as_in_collection_through_any_release_of_its_master(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await match(client, ("Rick Astley", "Never Gonna Give You Up"))

    assert text == (
        "Matched 1 album against the Collection of example-owner (5 Copies) and its Wantlist "
        "(3 Wants): 1 in Collection.\n"
        "1. Rick Astley — Never Gonna Give You Up: in Collection: Never Gonna Give You Up · "
        '1987 · Vinyl, 7", Single · 2 Copies [release_id=249504]; Original Hit Singles · 1989 · '
        "CD, Single [release_id=1570630]\n"
        "\n"
        "Use discogs_get_release with a release_id for the full card.\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/user/example-owner/collection"
    )


def add_copy(
    discogs: FakeDiscogs,
    release_id: int,
    artist: str,
    title: str,
    master_id: int = 0,
    medium: str = "Vinyl",
    year: int = 2000,
) -> None:
    """Add an older Copy of a Release by `artist`, a copy of a captured one."""
    added = copy.deepcopy(discogs.collection[-1])
    added["instance_id"] = 1_600_000_000 + release_id
    added["id"] = release_id
    release = added["basic_information"]
    release.update(id=release_id, title=title, master_id=master_id, year=year)
    release["artists"] = [{"name": artist, "anv": "", "join": "", "id": 1}]
    descriptions = ["LP", "Album"] if medium == "Vinyl" else ["Album"]
    release["formats"] = [{"name": medium, "qty": "1", "descriptions": descriptions}]
    discogs.collection.append(added)


def album_line(text: str) -> str:
    """The line of the only album matched."""
    [line] = [line for line in text.splitlines() if line.startswith("1. ")]
    return line


@pytest.mark.parametrize(
    ("artist", "title"),
    [
        ("The Beatles", "Abbey Road"),
        ("Beatles", "abbey road"),
        ("The Beatles", "Abbey Road (Remastered)"),
        ("The Beatles", "Abbey Road - Remastered 2009"),
        ("THE BEATLES", "Abbey Road [50th Anniversary Super Deluxe Edition]"),
        ("the beatles", "Abbey Road: Deluxe Edition"),
    ],
)
async def test_case_a_leading_the_and_edition_qualifiers_are_ignored(
    client: Client[Any], discogs: FakeDiscogs, artist: str, title: str
) -> None:
    add_copy(discogs, 101, "The Beatles", "Abbey Road", master_id=24047, year=1969)
    add_copy(discogs, 102, "The Beatles", "Abbey Road (Remastered)", 24047, "CD", 2009)

    text = await match(client, (artist, title))

    assert album_line(text) == (
        f"1. {artist} — {title}: in Collection: Abbey Road · 1969 · Vinyl, LP [release_id=101]; "
        "Abbey Road (Remastered) · 2009 · CD [release_id=102]"
    )


@pytest.mark.parametrize(
    ("artist", "title"),
    [
        ("Björk", "Homogenic"),
        ("bjork", "HOMOGENIC"),
        ("Sigur Ros", "Agaetis Byrjun"),
        ("Simon and Garfunkel", "Bridge over Troubled Water"),
        ("R.E.M.", "Automatic for the People"),
        ("ACDC", "Back In Black"),
    ],
)
async def test_diacritics_punctuation_and_ampersands_are_ignored(
    client: Client[Any], discogs: FakeDiscogs, artist: str, title: str
) -> None:
    add_copy(discogs, 201, "Björk", "Homogenic")
    add_copy(discogs, 202, "Sigur Rós", "Ágætis Byrjun")
    add_copy(discogs, 203, "Simon & Garfunkel", "Bridge Over Troubled Water")
    add_copy(discogs, 204, "R.E.M.", "Automatic For The People")
    add_copy(discogs, 205, "AC/DC", "Back In Black")

    text = await match(client, (artist, title))

    assert ": in Collection: " in album_line(text)


async def test_a_similar_title_under_another_master_is_possible(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    add_copy(discogs, 301, "Radiohead", "OK Computer OKNOTOK 1997 2017", 1234567, year=2017)

    text = await match(client, ("Radiohead", "OK Computer"))

    assert album_line(text) == (
        "1. Radiohead — OK Computer: possible: OK Computer OKNOTOK 1997 2017 · 2017 · Vinyl, LP · "
        "in Collection [release_id=301]"
    )
    assert text.splitlines()[0].endswith(": 1 possible.")
    assert "A possible match is a Release of the same artist" in text


async def test_a_different_album_with_a_close_title_is_absent(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    add_copy(discogs, 401, "Led Zeppelin", "Led Zeppelin III", 2001)

    text = await match(client, ("Led Zeppelin", "Led Zeppelin II"))

    assert album_line(text) == "1. Led Zeppelin — Led Zeppelin II: absent"


async def test_a_release_without_a_master_matches_on_artist_and_title_alone(
    client: Client[Any],
) -> None:
    text = await match(client, ("Rick Astley", "Wonderful You"))

    # The Want "First On Your Block" has no Master either and stays out.
    assert album_line(text) == (
        "1. Rick Astley — Wonderful You: in Collection: Wonderful You · 1991 · CD, Single "
        "[release_id=3499619]"
    )


async def test_an_album_only_on_the_wantlist_is_reported_as_wanted(
    client: Client[Any],
) -> None:
    text = await match(client, ("Rick Astley", "First On Your Block"))

    assert album_line(text) == (
        "1. Rick Astley — First On Your Block: on Wantlist: First On Your Block · 1993 · "
        "Cassette [release_id=26304263]"
    )


async def test_albums_are_reported_one_line_each_in_the_order_given(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    add_copy(discogs, 301, "Radiohead", "OK Computer OKNOTOK 1997 2017", 1234567, year=2017)

    text = await match(
        client,
        ("Fishbone", "Swim"),
        ("Rick Astley", "First On Your Block"),
        ("Radiohead", "OK Computer"),
        ("Rick Astley", "Whenever You Need Somebody"),
        ("Unknown Band", "Swim"),
    )

    lines = text.splitlines()
    assert lines[0] == (
        "Matched 5 albums against the Collection of example-owner (6 Copies) and its Wantlist "
        "(3 Wants): 1 in Collection, 1 on Wantlist, 1 possible, 2 absent."
    )
    assert [line.split(": ")[1] for line in lines[1:6]] == [
        "in Collection",
        "on Wantlist",
        "possible",
        "absent",
        "absent",
    ]
    assert lines[6] == ""


async def test_matching_100_albums_reads_only_the_collection_and_wantlist(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    albums = [("Rick Astley", "Never Gonna Give You Up")] + [
        (f"Artist {number}", f"Album {number}") for number in range(1, 100)
    ]

    text = await match(client, *albums)

    assert text.splitlines()[0].endswith(": 1 in Collection, 99 absent.")
    assert [request.url.path for request in discogs.requests] == [
        "/oauth/identity",
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/folders/0/releases",
        "/users/example-owner/collection/fields",
        "/users/example-owner/wants",
    ]
    discogs.requests.clear()

    await match(client, *albums)

    assert [request.url.path for request in discogs.requests] == [
        "/users/example-owner/collection/folders",
        "/users/example-owner/collection/folders/0/releases",
        "/users/example-owner/wants",
    ]


@pytest.mark.parametrize(
    ("albums", "explanation"),
    [
        ([{"artist": "A", "title": "B"}] * 201, "List should have at most 200 items"),
        ([], "List should have at least 1 item"),
        ([{"artist": "A", "title": ""}], "String should have at least 1 character"),
    ],
)
async def test_invalid_album_lists_are_rejected_with_the_valid_range(
    client: Client[Any], discogs: FakeDiscogs, albums: list[dict[str, str]], explanation: str
) -> None:
    is_error, text = await call_tool_text(client, "discogs_match_collection", {"albums": albums})

    assert is_error
    assert explanation in text
    assert discogs.requests == []


async def test_a_long_list_of_matching_releases_is_cut_short(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    for number in range(1, 6):
        add_copy(discogs, 500 + number, "Miles Davis", "Kind Of Blue", 5460, year=1958 + number)

    text = await match(client, ("Miles Davis", "Kind of Blue (Legacy Edition)"))

    assert album_line(text) == (
        "1. Miles Davis — Kind of Blue (Legacy Edition): in Collection: Kind Of Blue · 1959 · "
        "Vinyl, LP [release_id=501]; Kind Of Blue · 1960 · Vinyl, LP [release_id=502]; "
        "Kind Of Blue · 1961 · Vinyl, LP [release_id=503]; and 2 more Releases"
    )


async def test_a_reissue_under_the_same_master_counts_whatever_its_title(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    add_copy(discogs, 601, "Fleetwood Mac", "Rumours (Expanded Edition)", 12345, "CD", 2004)
    add_copy(discogs, 602, "Fleetwood Mac", "Rumours / The Alternate Album", 12345, year=2013)

    text = await match(client, ("Fleetwood Mac", "Rumours (Super Deluxe)"))

    assert album_line(text) == (
        "1. Fleetwood Mac — Rumours (Super Deluxe): in Collection: Rumours (Expanded Edition) · "
        "2004 · CD [release_id=601]; Rumours / The Alternate Album · 2013 · Vinyl, LP "
        "[release_id=602]"
    )


@pytest.mark.parametrize(
    "title", ["Pet Sounds (Mono)", "Pet Sounds [Stereo]", "Pet Sounds (Bonus Track Version)"]
)
async def test_mono_stereo_and_bonus_track_editions_are_the_same_album(
    client: Client[Any], discogs: FakeDiscogs, title: str
) -> None:
    add_copy(discogs, 701, "The Beach Boys", "Pet Sounds", 33333, year=1966)

    text = await match(client, ("The Beach Boys", title))

    assert ": in Collection: Pet Sounds · 1966 · Vinyl, LP [release_id=701]" in album_line(text)


async def test_a_shorter_title_under_another_master_is_possible_too(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    add_copy(discogs, 801, "Radiohead", "OK Computer", 21491, year=1997)

    text = await match(client, ("Radiohead", "OK Computer OKNOTOK 1997 2017"))

    assert album_line(text) == (
        "1. Radiohead — OK Computer OKNOTOK 1997 2017: possible: OK Computer · 1997 · Vinyl, LP · "
        "in Collection [release_id=801]"
    )


@pytest.mark.parametrize(
    ("owned", "asked", "result"),
    [
        (("Ed Sheeran", "+"), ("Ed Sheeran", "+"), "in Collection"),
        (("!!!", "Myth Takes"), ("!!!", "Myth Takes"), "in Collection"),
        (("Ed Sheeran", "+"), ("Ed Sheeran", "÷"), "absent"),
        (("Nirvana", "ネヴァーマインド"), ("Nirvana", "ネウァーマイント"), "absent"),
        (("Nirvana", "ネヴァーマインド"), ("nirvana", "ネヴァーマインド"), "in Collection"),
        (("Harmonia", "Deluxe"), ("Harmonia", "Deluxe"), "in Collection"),
        (("Someone", "Stereo Mono"), ("Someone", "Mono"), "possible"),
        (
            ("Someone", "Greatest Hits Vol. 2"),
            ("Someone", "Greatest Hits Vol. 2 Deluxe"),
            "in Collection",
        ),
        (("Someone", "Greatest Hits Vol. 2"), ("Someone", "Greatest Hits Vol. 3"), "absent"),
        (("Prince", "1999"), ("Prince", "1999 - Remastered"), "in Collection"),
        (("Chicago", "Chicago"), ("Chicago", "Chicago 17 - Remastered"), "absent"),
        (("Chicago", "Chicago 17"), ("Chicago", "Chicago 17 (2011 Remaster)"), "in Collection"),
        (("Various", "Nuggets"), ("Various Artists", "Nuggets"), "in Collection"),
    ],
)
async def test_names_made_of_symbols_scripts_or_qualifiers_keep_their_meaning(
    client: Client[Any],
    discogs: FakeDiscogs,
    owned: tuple[str, str],
    asked: tuple[str, str],
    result: str,
) -> None:
    add_copy(discogs, 901, *owned)

    text = await match(client, asked)

    assert album_line(text).split(": ")[1] == result


async def test_a_blank_artist_or_title_is_rejected(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(
        client, "discogs_match_collection", {"albums": [{"artist": "  ", "title": "Swim"}]}
    )

    assert is_error
    assert "String should have at least 1 character" in text
    assert discogs.requests == []


@pytest.mark.parametrize(
    ("owned", "asked", "result"),
    [
        ("Led Zeppelin III", "Led Zeppelin", "absent"),
        ("Greatest Hits II", "Greatest Hits", "absent"),
        ("Greatest Hits Vol. 2", "Greatest Hits", "absent"),
        ("Chicago 17", "Chicago", "absent"),
        ("Chicago", "Chicago XVII", "absent"),
        ("OK Computer OKNOTOK 1997 2017", "OK Computer", "possible"),
        ("Kind of Blue 1959", "Kind of Blue", "possible"),
        ("Rumours Live", "Rumours", "possible"),
        ("Peter Gabriel 1: Car", "Peter Gabriel", "possible"),
        ("Live at Leeds", "Live", "possible"),
    ],
)
async def test_a_title_that_differs_only_by_a_series_number_is_another_album(
    client: Client[Any], discogs: FakeDiscogs, owned: str, asked: str, result: str
) -> None:
    add_copy(discogs, 1001, "Someone", owned, 424242)

    text = await match(client, ("Someone", asked))

    assert album_line(text).split(": ")[1] == result
