"""discogs_search: finding Releases, Masters, artists and labels in the Discogs catalog."""

from typing import Any

from fastmcp import Client

from tests.conftest import TEST_TOKEN, FakeDiscogs, call_tool_text, load_fixture


async def search(client: Client[Any], **arguments: Any) -> str:
    is_error, text = await call_tool_text(client, "discogs_search", arguments)
    assert not is_error, text
    return text


async def test_release_results_carry_the_ids_for_the_next_call(client: Client[Any]) -> None:
    text = await search(client, query="Never Gonna Give You Up")

    assert text == (
        'Discogs search, releases matching "Never Gonna Give You Up": '
        "page 1 of 910 (9096 results)\n"
        "1. Rick Astley - Never Gonna Give You Up · 1987 · Europe · RCA – PT 41 448 · "
        'Vinyl, 12", 45 RPM, Maxi-Single, Stereo [release_id=995860, master_id=96559]\n'
        "2. Rick Astley - Never Gonna Give You Up · 1987 · UK · RCA – PB 41447 · "
        'Vinyl, 7", 45 RPM, Single, Stereo [release_id=249504, master_id=96559]\n'
        "3. Rick Astley - Never Gonna Give You Up · 1987 · UK · RCA – PT 41448 · "
        'Vinyl, 12", 45 RPM, Single [release_id=221824, master_id=96559]\n'
        "\n"
        "Showing 1–3 of 9096. Use page=2 for more.\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/search/?q=Never+Gonna+Give+You+Up&type=release"
    )


async def test_filters_narrow_the_search_on_discogs(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await search(
        client,
        query="Never Gonna Give You Up",
        artist="Rick Astley",
        year=1987,
        format="Vinyl",
        country="UK",
        catno="PB 41447",
        barcode="5012394144777",
    )

    [request] = discogs.requests
    assert request.url.path == "/database/search"
    assert dict(request.url.params) == {
        "q": "Never Gonna Give You Up",
        "artist": "Rick Astley",
        "year": "1987",
        "format": "Vinyl",
        "country": "UK",
        "catno": "PB 41447",
        "barcode": "5012394144777",
        "type": "release",
        "per_page": "10",
        "page": "1",
    }
    assert text.startswith(
        'Discogs search, releases matching "Never Gonna Give You Up", artist=Rick Astley, '
        "year=1987, format=Vinyl, country=UK, catno=PB 41447, barcode=5012394144777: page 1"
    )


async def test_barcode_alone_is_enough_to_search(client: Client[Any], discogs: FakeDiscogs) -> None:
    text = await search(client, barcode="5012394144777")

    assert dict(discogs.requests[0].url.params) == {
        "barcode": "5012394144777",
        "type": "release",
        "per_page": "10",
        "page": "1",
    }
    assert text.startswith("Discogs search, releases, barcode=5012394144777: page 1 of 910")


async def test_search_without_query_or_filters_is_rejected(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(client, "discogs_search", {"query": "  "})

    assert is_error
    assert text == (
        "Give a query or at least one filter (artist, year, format, country, catno, barcode) "
        "to search Discogs."
    )
    assert discogs.requests == []


async def test_later_pages_continue_the_numbering(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await search(client, query="Never Gonna Give You Up", limit=3, page=2)

    params = discogs.requests[0].url.params
    assert (params["per_page"], params["page"]) == ("3", "2")
    assert "page 2 of 3032 (9096 results)\n4. Rick Astley" in text
    assert "\nShowing 4–6 of 9096. Use page=3 for more.\n" in text


async def test_last_page_has_no_next_page_hint(client: Client[Any]) -> None:
    text = await search(client, query="Never Gonna Give You Up", type="artist")

    assert "page 1 of 1 (8 results)" in text
    assert "\nShowing 1–3 of 8.\n" in text
    assert "Use page=" not in text


async def test_page_past_the_end_is_an_answer_not_an_error(client: Client[Any]) -> None:
    text = await search(client, query="Never Gonna Give You Up", type="artist", page=2)

    assert text == (
        "No results on page 2: it is past the last page of this search, or beyond the first "
        "10,000 results Discogs serves. Use a lower page or narrow the search."
    )


async def test_no_results_is_a_normal_answer(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.searches["label"] = load_fixture("search_empty.json")

    text = await search(client, query="Never Gonna Give You Up", type="label")

    assert text == (
        'Discogs search, labels matching "Never Gonna Give You Up": nothing found. '
        "Try a broader query or fewer filters.\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/search/?q=Never+Gonna+Give+You+Up&type=label"
    )


async def test_master_results_carry_the_master_id(client: Client[Any]) -> None:
    text = await search(client, query="Never Gonna Give You Up", type="master")

    lines = text.splitlines()
    assert lines[0] == (
        'Discogs search, masters matching "Never Gonna Give You Up": page 1 of 115 (1149 results)'
    )
    assert lines[1] == (
        "1. Rick Astley - Never Gonna Give You Up · 1987 · RCA · "
        'Vinyl, 12", 45 RPM, Single [master_id=96559]'
    )
    assert lines[2] == (
        "2. Lisa Stansfield - Never, Never Gonna Give You Up · 1997 · Arista · "
        'Vinyl, 12" [master_id=106651]'
    )


async def test_artist_and_label_results_carry_their_ids(client: Client[Any]) -> None:
    artists = await search(client, query="Never Gonna Give You Up", type="artist")
    labels = await search(client, query="RCA", type="label")

    assert artists.splitlines()[1:4] == [
        "1. Rick Astley [artist_id=72872]",
        "2. FKW (2) [artist_id=1146552]",
        "3. The Festivals [artist_id=1034987]",
    ]
    assert labels.splitlines()[1:4] == [
        "1. RCA [label_id=895]",
        "2. RCA Victor [label_id=11358]",
        "3. RCA Records [label_id=29656]",
    ]
    assert labels.endswith("https://www.discogs.com/search/?q=RCA&type=label")


async def test_release_without_master_or_details(client: Client[Any], discogs: FakeDiscogs) -> None:
    discogs.searches["release"]["results"] = [
        {"id": 7, "type": "release", "title": "Unknown Artist - Demo", "master_id": 0}
    ]

    text = await search(client, query="Demo")

    assert "\n1. Unknown Artist - Demo [release_id=7]\n" in text


async def test_repeated_formats_are_listed_once(client: Client[Any], discogs: FakeDiscogs) -> None:
    result = discogs.searches["release"]["results"][0]
    result["format"] = ["Vinyl", "LP", "Album", "Vinyl", "LP", "CD"]

    text = await search(client, query="Never Gonna Give You Up")

    assert "· Vinyl, LP, Album, CD [release_id=995860" in text


async def test_rejected_token_during_search_says_what_to_fix(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.reject_token = True

    is_error, text = await call_tool_text(client, "discogs_search", {"query": "x"})

    assert is_error
    assert "Check DISCOGS_TOKEN" in text
    assert TEST_TOKEN not in text


async def test_discogs_failure_during_search_is_a_tool_error(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.failing_status = 502

    is_error, text = await call_tool_text(client, "discogs_search", {"query": "x"})

    assert is_error
    assert text == "Discogs answered HTTP 502 for /database/search. Try again later."


async def test_not_found_on_the_first_page_is_a_tool_error(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.failing_status = 404

    is_error, text = await call_tool_text(client, "discogs_search", {"query": "x"})

    assert is_error
    assert "past the last page" not in text


async def test_release_filters_are_rejected_for_artist_and_label_searches(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(
        client, "discogs_search", {"query": "RCA", "type": "label", "year": 1987}
    )

    assert is_error
    assert text == (
        "The filters artist, year, format, country, catno and barcode apply to release and "
        "master searches only. Search labels by query alone."
    )
    assert discogs.requests == []
