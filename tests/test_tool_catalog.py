"""Contract test on the tool catalog Claude sees. Later tickets extend the snapshot."""

from typing import Any

from fastmcp import Client
from inline_snapshot import snapshot

MIN_DESCRIPTION_LENGTH = 150


async def test_tool_catalog_matches_the_contract(client: Client[Any]) -> None:
    tools = await client.list_tools()

    catalog = [
        {
            "name": tool.name,
            "title": tool.title,
            "read_only": tool.annotations.read_only_hint if tool.annotations else None,
            "destructive": tool.annotations.destructive_hint if tool.annotations else None,
            "open_world": tool.annotations.open_world_hint if tool.annotations else None,
        }
        for tool in sorted(tools, key=lambda tool: tool.name)
    ]

    assert catalog == snapshot(
        [
            {
                "name": "discogs_get_release",
                "title": "Get Discogs Release",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            }
        ]
    )


async def test_every_tool_explains_itself(client: Client[Any]) -> None:
    tools = await client.list_tools()

    short = {
        tool.name: len(tool.description or "")
        for tool in tools
        if len(tool.description or "") < MIN_DESCRIPTION_LENGTH
    }
    assert short == {}


async def test_tools_return_text_without_an_output_schema(client: Client[Any]) -> None:
    tools = await client.list_tools()

    assert {tool.name: tool.output_schema for tool in tools if tool.output_schema} == {}


async def test_instructions_describe_the_scope(client: Client[Any]) -> None:
    instructions = client.instructions

    assert instructions is not None
    for term in ("Discogs", "Release", "pressing", "Marketplace", "Collection", "Wantlist"):
        assert term in instructions
