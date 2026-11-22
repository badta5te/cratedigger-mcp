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
                "name": "discogs_collection_summary",
                "title": "Summarize My Discogs Collection",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_get_prices",
                "title": "Get Discogs Marketplace Prices",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_get_release",
                "title": "Get Discogs Release",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_list_collection",
                "title": "List My Discogs Collection",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_list_master_releases",
                "title": "List Releases of a Discogs Master",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_list_wantlist",
                "title": "List My Discogs Wantlist",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_match_collection",
                "title": "Match Albums Against My Discogs Collection",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
            {
                "name": "discogs_search",
                "title": "Search Discogs Catalog",
                "read_only": True,
                "destructive": None,
                "open_world": True,
            },
        ]
    )


async def test_prompt_catalog_matches_the_contract(client: Client[Any]) -> None:
    prompts = await client.list_prompts()

    assert [(prompt.name, prompt.title) for prompt in prompts] == snapshot(
        [("identify_release", "Identify a Discogs Release")]
    )


async def test_search_description_points_to_the_owner_tools(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_search"].description or ""
    for other in ("discogs_list_collection", "discogs_list_wantlist", "discogs_match_collection"):
        assert other in description


async def test_master_releases_description_names_the_search_keywords(
    client: Client[Any],
) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_list_master_releases"].description or ""
    for term in ("pressings", "versions", "discogs_get_release", "discogs_search"):
        assert term in description


async def test_prices_description_says_what_lowest_price_means(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_get_prices"].description or ""
    for term in ("any condition", "excluding shipping", "discogs_wantlist_prices"):
        assert term in description


async def test_collection_tools_point_to_the_other_tools(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    listing = tools["discogs_list_collection"].description or ""
    for other in ("discogs_search", "discogs_match_collection"):
        assert other in listing
    summary = tools["discogs_collection_summary"].description or ""
    for term in ("folder_id", "discogs_list_collection", "minimum, median and maximum"):
        assert term in summary


async def test_wantlist_listing_points_to_the_other_tools(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_list_wantlist"].description or ""
    for term in ("artist and title text only", "discogs_search", "discogs_list_collection"):
        assert term in description


async def test_match_description_says_how_albums_match(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_match_collection"].description or ""
    for term in ("up to 200", "any Release of its Master", "possible", "discogs_search"):
        assert term in description


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
