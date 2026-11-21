"""The identify_release prompt: Claude guides the Owner to the exact Release they hold."""

from typing import Any

from fastmcp import Client


async def test_prompt_is_offered_with_a_description_argument(client: Client[Any]) -> None:
    prompts = {prompt.name: prompt for prompt in await client.list_prompts()}

    prompt = prompts["identify_release"]
    assert prompt.title == "Identify a Discogs Release"
    assert [(argument.name, argument.required) for argument in prompt.arguments or []] == [
        ("description", True)
    ]


async def test_prompt_walks_through_barcode_catalog_number_and_runout(
    client: Client[Any],
) -> None:
    description = "Kind of Blue LP, orange Columbia label, runout CL 1355-1AF"

    result = await client.get_prompt("identify_release", {"description": description})

    [message] = result.messages
    assert message.role == "user"
    assert message.content.type == "text"
    text = message.content.text
    assert description in text
    for step in ("barcode", "catalog number", "matrix/runout"):
        assert step in text
    assert "discogs_search" in text
    assert 'discogs_get_release with response_format="detailed"' in text
