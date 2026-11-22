"""discogs_wantlist_add and discogs_wantlist_remove: the Owner changes the Wantlist from Claude."""

from typing import Any

from fastmcp import Client

from tests.conftest import FakeDiscogs, call_tool_text

RELEASE_URL = "https://www.discogs.com/release/249504-Rick-Astley-Never-Gonna-Give-You-Up"


async def add_want(client: Client[Any], release_id: int) -> str:
    is_error, text = await call_tool_text(
        client, "discogs_wantlist_add", {"release_id": release_id}
    )
    assert not is_error, text
    return text


def writes(discogs: FakeDiscogs) -> list[tuple[str, str]]:
    """The requests that changed something on Discogs, as method and path."""
    return [(r.method, r.url.path) for r in discogs.requests if r.method != "GET"]


async def remove_want(client: Client[Any], release_id: int) -> tuple[bool, str]:
    return await call_tool_text(client, "discogs_wantlist_remove", {"release_id": release_id})


async def list_wantlist(client: Client[Any]) -> str:
    is_error, text = await call_tool_text(client, "discogs_list_wantlist", {"limit": 50})
    assert not is_error, text
    return text


def wants_pages(discogs: FakeDiscogs) -> list[str]:
    return [r.url.params["page"] for r in discogs.requests if r.url.path.endswith("/wants")]


async def test_a_release_is_added_as_a_want_with_a_short_card(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    text = await add_want(client, 249504)

    assert text == (
        "Added to the Wantlist of example-owner:\n"
        "Never Gonna Give You Up — Rick Astley [release_id=249504]\n"
        "Label: RCA – PB 41447\n"
        'Format: Vinyl, 7", 45 RPM, Single, Stereo, CBS Pressing\n'
        "Country: UK · Year: 1987\n"
        "\n"
        f"Data provided by Discogs: {RELEASE_URL}"
    )
    assert writes(discogs) == [("PUT", "/users/example-owner/wants/249504")]
    assert [want["id"] for want in discogs.wantlist] == [249504, 26304263, 995860, 221824]


async def test_adding_a_release_already_wanted_succeeds_and_changes_nothing(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    await add_want(client, 249504)

    text = await add_want(client, 249504)

    assert text.splitlines()[:2] == [
        "Already on the Wantlist of example-owner since 2026-11-20; nothing changed:",
        "Never Gonna Give You Up — Rick Astley [release_id=249504]",
    ]
    assert writes(discogs) == [("PUT", "/users/example-owner/wants/249504")]
    assert [want["id"] for want in discogs.wantlist].count(249504) == 1


async def test_a_want_is_removed(client: Client[Any], discogs: FakeDiscogs) -> None:
    is_error, text = await remove_want(client, 995860)

    assert not is_error, text
    assert text == (
        "Removed from the Wantlist of example-owner:\n"
        'Rick Astley — Never Gonna Give You Up · 1987 · Vinyl, 12", 45 RPM, Maxi-Single, '
        "Stereo · RCA – PT 41 448 · added 2026-10-21 [release_id=995860]\n"
        "\n"
        "Data provided by Discogs: https://www.discogs.com/wantlist?user=example-owner"
    )
    assert writes(discogs) == [("DELETE", "/users/example-owner/wants/995860")]
    assert [want["id"] for want in discogs.wantlist] == [26304263, 221824]


async def test_removing_a_release_not_on_the_wantlist_is_a_tool_error(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await remove_want(client, 249504)

    assert is_error
    assert text == (
        "Release 249504 is not on the Wantlist of example-owner. "
        "Use discogs_list_wantlist to find the release_id of the Want."
    )
    assert writes(discogs) == []


async def test_adding_an_unknown_release_is_a_tool_error(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    is_error, text = await call_tool_text(client, "discogs_wantlist_add", {"release_id": 404404})

    assert is_error
    assert text == (
        "Release 404404 not found on Discogs. Use discogs_search to find the release_id."
    )
    assert writes(discogs) == []


async def test_the_wantlist_is_fetched_whole_again_after_an_add(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(200)
    await list_wantlist(client)
    await add_want(client, 249504)
    discogs.requests.clear()

    text = await list_wantlist(client)

    assert wants_pages(discogs) == ["1", "2", "3"]
    assert text.splitlines()[0].endswith(": page 1 of 5 (204 Wants)")
    assert text.splitlines()[1].startswith("1. Rick Astley — Never Gonna Give You Up · ")
    assert text.splitlines()[1].endswith("[release_id=249504]")


async def test_the_wantlist_is_fetched_whole_again_after_a_remove(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.add_wants(200)
    await list_wantlist(client)
    is_error, _ = await remove_want(client, 6_000_150)
    assert not is_error
    discogs.requests.clear()

    text = await list_wantlist(client)

    assert wants_pages(discogs) == ["1", "2", "3"]
    assert text.splitlines()[0].endswith(": page 1 of 5 (202 Wants)")


async def test_no_tool_writes_anything_but_the_wantlist(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    tools = await client.list_tools()
    await add_want(client, 249504)
    await remove_want(client, 995860)

    changing = sorted(
        tool.name for tool in tools if not (tool.annotations and tool.annotations.read_only_hint)
    )
    assert changing == ["discogs_wantlist_add", "discogs_wantlist_remove"]
    assert writes(discogs) == [
        ("PUT", "/users/example-owner/wants/249504"),
        ("DELETE", "/users/example-owner/wants/995860"),
    ]


async def test_a_want_already_gone_from_discogs_is_a_tool_error_and_refreshes_the_wantlist(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    # Past the first page and with the total kept, the snapshot cannot see the Want go.
    discogs.add_wants(200)
    await list_wantlist(client)
    gone = next(want for want in discogs.wantlist if want["id"] == 6_000_150)
    discogs.wantlist.remove(gone)
    discogs.add_wants(1)
    discogs.wantlist[-1]["id"] = discogs.wantlist[-1]["basic_information"]["id"] = 6_100_000

    is_error, text = await remove_want(client, 6_000_150)

    assert is_error
    assert text.startswith("Release 6000150 is not on the Wantlist of example-owner.")
    assert writes(discogs) == [("DELETE", "/users/example-owner/wants/6000150")]
    discogs.requests.clear()
    await list_wantlist(client)
    assert wants_pages(discogs) == ["1", "2", "3"]
