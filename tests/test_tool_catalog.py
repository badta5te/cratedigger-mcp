"""Contract test on the tool catalog Claude sees. Later tickets extend the snapshot."""

import re
from typing import Any

from fastmcp import Client
from inline_snapshot import snapshot

MIN_DESCRIPTION_LENGTH = 150
TOOL_NAME = re.compile(r"\bdiscogs_[a-z_]+")


def mentioned_tools(text: str | None) -> set[str]:
    return set(TOOL_NAME.findall(text or ""))


async def test_tool_catalog_matches_the_contract(client: Client[Any]) -> None:
    tools = await client.list_tools()

    catalog = [
        {
            "name": tool.name,
            "title": tool.title,
            "read_only": tool.annotations.read_only_hint if tool.annotations else None,
            "destructive": tool.annotations.destructive_hint if tool.annotations else None,
            "open_world": tool.annotations.open_world_hint if tool.annotations else None,
            "idempotent": tool.annotations.idempotent_hint if tool.annotations else None,
            "asks_to_confirm": (tool.meta or {}).get("anthropic/requiresUserInteraction"),
            "points_to": sorted(mentioned_tools(tool.description) - {tool.name}),
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
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": ["discogs_get_prices", "discogs_list_collection"],
            },
            {
                "name": "discogs_get_prices",
                "title": "Get Discogs Marketplace Prices",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_list_master_releases",
                    "discogs_search",
                    "discogs_wantlist_prices",
                ],
            },
            {
                "name": "discogs_get_release",
                "title": "Get Discogs Release",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_get_prices",
                    "discogs_list_master_releases",
                    "discogs_search",
                ],
            },
            {
                "name": "discogs_list_collection",
                "title": "List My Discogs Collection",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_collection_summary",
                    "discogs_match_collection",
                    "discogs_search",
                ],
            },
            {
                "name": "discogs_list_master_releases",
                "title": "List Releases of a Discogs Master",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": ["discogs_get_prices", "discogs_get_release", "discogs_search"],
            },
            {
                "name": "discogs_list_wantlist",
                "title": "List My Discogs Wantlist",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_list_collection",
                    "discogs_search",
                    "discogs_wantlist_prices",
                ],
            },
            {
                "name": "discogs_match_collection",
                "title": "Match Albums Against My Discogs Collection",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": ["discogs_list_collection", "discogs_search"],
            },
            {
                "name": "discogs_search",
                "title": "Search Discogs Catalog",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_get_release",
                    "discogs_list_collection",
                    "discogs_list_master_releases",
                    "discogs_list_wantlist",
                    "discogs_match_collection",
                ],
            },
            {
                "name": "discogs_wantlist_add",
                "title": "Add to My Discogs Wantlist",
                "read_only": False,
                "destructive": False,
                "open_world": True,
                "idempotent": True,
                "asks_to_confirm": None,
                "points_to": [
                    "discogs_get_release",
                    "discogs_list_master_releases",
                    "discogs_search",
                ],
            },
            {
                "name": "discogs_wantlist_prices",
                "title": "Get Prices of My Discogs Wantlist",
                "read_only": True,
                "destructive": None,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": None,
                "points_to": ["discogs_get_prices", "discogs_list_wantlist"],
            },
            {
                "name": "discogs_wantlist_remove",
                "title": "Remove from My Discogs Wantlist",
                "read_only": False,
                "destructive": True,
                "open_world": True,
                "idempotent": None,
                "asks_to_confirm": True,
                "points_to": ["discogs_list_wantlist"],
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
    for term in (
        "artist and title text only",
        "discogs_search",
        "discogs_list_collection",
        "discogs_wantlist_prices",
    ):
        assert term in description


async def test_wantlist_prices_description_says_what_it_checks(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["discogs_wantlist_prices"].description or ""
    for term in (
        "at most 30 Wants",
        "max_price",
        "any condition",
        "excluding shipping",
        "Wantlister",
        "discogs_get_prices",
        "discogs_list_wantlist",
    ):
        assert term in description


async def test_wantlist_change_descriptions_say_what_they_touch(client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}

    add = " ".join((tools["discogs_wantlist_add"].description or "").split())
    for term in ("already on the Wantlist", "discogs_search", "never changes the Collection"):
        assert term in add
    remove = " ".join((tools["discogs_wantlist_remove"].description or "").split())
    for term in ("only when the Owner asks", "confirm", "discogs_list_wantlist", "Collection"):
        assert term in remove


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


async def test_instructions_say_which_tool_to_use_for_what(client: Client[Any]) -> None:
    tools = await client.list_tools()

    assert {tool.name for tool in tools} - mentioned_tools(client.instructions) == set()


async def test_every_tool_points_to_another_tool(client: Client[Any]) -> None:
    tools = await client.list_tools()

    alone = [tool.name for tool in tools if not mentioned_tools(tool.description) - {tool.name}]
    assert alone == []


async def test_descriptions_name_only_tools_that_exist(client: Client[Any]) -> None:
    tools = await client.list_tools()
    prompts = await client.list_prompts()
    prompt = await client.get_prompt("identify_release", {"description": "a 7-inch single"})
    known = {tool.name for tool in tools}

    texts = [
        client.instructions,
        *(tool.description for tool in tools),
        *(str(argument) for tool in tools for argument in tool.input_schema.values()),
        *(item.description for item in prompts),
        *(str(message.content) for message in prompt.messages),
    ]
    assert set().union(*(mentioned_tools(text) for text in texts)) - known == set()


async def test_tools_return_text_without_an_output_schema(client: Client[Any]) -> None:
    tools = await client.list_tools()

    assert {tool.name: tool.output_schema for tool in tools if tool.output_schema} == {}


async def test_instructions_describe_the_scope(client: Client[Any]) -> None:
    instructions = client.instructions

    assert instructions is not None
    for term in ("Discogs", "Release", "pressing", "Marketplace", "Collection", "Wantlist"):
        assert term in instructions
