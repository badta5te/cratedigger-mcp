"""discogs_get_release: the Release card the Owner sees."""

from typing import Any

from fastmcp import Client

from tests.conftest import FakeDiscogs, call_tool_text


async def get_release(client: Client[Any], release_id: int, **arguments: Any) -> str:
    is_error, text = await call_tool_text(
        client, "discogs_get_release", {"release_id": release_id, **arguments}
    )
    assert not is_error, text
    return text


async def test_concise_card_shows_what_the_release_is(client: Client[Any]) -> None:
    card = await get_release(client, 249504)

    assert card == (
        "Never Gonna Give You Up — Rick Astley [release_id=249504]\n"
        "Label: RCA – PB 41447\n"
        'Format: Vinyl, 7", 45 RPM, Single, Stereo, CBS Pressing\n'
        "Country: UK · Year: 1987\n"
        "Master: master_id=96559\n"
        "Discogs community: 4190 have · 597 want\n"
        "\n"
        "Tracklist:\n"
        "A  Never Gonna Give You Up (3:32)\n"
        "B  Never Gonna Give You Up (Instrumental) (3:30)\n"
        "\n"
        "Data provided by Discogs: "
        "https://www.discogs.com/release/249504-Rick-Astley-Never-Gonna-Give-You-Up"
    )


async def test_detailed_card_adds_identifiers_and_notes(client: Client[Any]) -> None:
    card = await get_release(client, 249504, response_format="detailed")

    concise = await get_release(client, 249504)
    attribution = concise.rsplit("\n\n", 1)[1]
    assert card.startswith(concise.removesuffix(attribution))
    assert card.endswith("\n\n" + attribution)
    assert (
        "Identifiers:\n"
        "  Barcode: 5012394144777\n"
        "  Label Code: LC 0316\n"
        "  Price Code (D:): AC\n"
        "  Price Code (F:): RC110\n"
        "  Price Code (UK:): AA\n"
        "  Matrix / Runout (A side label): PB 41447 A‡\n"
        "  Matrix / Runout (B side label): PB 41447 B‡\n"
        "  Matrix / Runout (A side runout, variant 1): PB 41447 A2 UTOPIA MS\n"
    ) in card
    assert (
        "Notes:\n"
        'UK Release has a black label with the text "Manufactured In England" printed on it.\n'
        "\n"
        "Sleeve:\n"
    ) in card
    assert "Runouts are etched, except 'B' stamp in variant '3. 'MS' is encircled." in card


async def test_detailed_card_without_identifiers_or_notes(client: Client[Any]) -> None:
    card = await get_release(client, 1621435, response_format="detailed")

    assert card.startswith("Swim — Fishbone [release_id=1621435]\n")
    assert "Identifiers: none listed\n" in card
    assert "Notes: none\n" in card
    assert card.endswith(
        "Data provided by Discogs: https://www.discogs.com/release/1621435-Fishbone-Swim"
    )


async def test_long_notes_are_cut_to_keep_the_card_compact(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.releases[249504]["notes"] = "Pressing detail. " * 400

    card = await get_release(client, 249504, response_format="detailed")

    assert len(card) < 4000
    assert "(notes shortened, full text on Discogs)" in card


async def test_card_for_a_release_without_master_year_or_country(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    release = discogs.releases[1621435]
    del release["master_id"], release["master_url"]
    release["year"] = 0
    del release["country"]

    card = await get_release(client, 1621435)

    assert "Country: unknown · Year: unknown\n" in card
    assert "Master: none (this Release is not grouped under a Master)\n" in card


async def test_artist_credit_follows_discogs_naming(
    client: Client[Any], discogs: FakeDiscogs
) -> None:
    discogs.releases[1621435]["artists"] = [
        {"name": "Fishbone (2)", "anv": "", "join": "&", "id": 1},
        {"name": "The Familyhood Nextperience", "anv": "Familyhood", "join": "", "id": 2},
    ]

    card = await get_release(client, 1621435)

    assert card.startswith("Swim — Fishbone & Familyhood [release_id=1621435]\n")
