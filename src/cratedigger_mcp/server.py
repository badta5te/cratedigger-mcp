"""The FastMCP server: a factory for tests and the stdio entry point."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx2
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from cratedigger_mcp.cache import CATALOG_TTL, TtlCache
from cratedigger_mcp.clock import Clock, SystemClock
from cratedigger_mcp.discogs import (
    DiscogsClient,
    DiscogsError,
    NotFoundError,
    UnauthorizedError,
    build_http_client,
)
from cratedigger_mcp.formatting import ResponseFormat, release_card
from cratedigger_mcp.settings import Settings

INSTRUCTIONS = """\
Cratedigger for Discogs: the Owner's window onto Discogs, the vinyl and music database and \
Marketplace. Use these tools for the Discogs catalog (Masters, Releases and pressings: label, \
catalog number, Format, country, year, matrix/runout and barcode identifiers), Marketplace \
prices of Releases, and the Owner's own Collection and Wantlist on Discogs. \
Every response carries the release_id or master_id needed for the next call. \
To check a list of albums from another source (listening history, playlists) against the \
Owner's shelf, use discogs_match_collection rather than searching album by album."""

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}

TOKEN_HINT = (
    "Discogs rejected the access token (HTTP 401). Check DISCOGS_TOKEN in the MCP server "
    "configuration: it must be a valid personal access token from "
    "https://www.discogs.com/settings/developers."
)


def create_server(
    settings: Settings,
    transport: httpx2.AsyncBaseTransport | None = None,
    clock: Clock | None = None,
) -> FastMCP[dict[str, Any]]:
    """Build the server.

    Tests pass a mock `transport` that plays the part of Discogs and a `clock` they control.
    """
    clock = clock or SystemClock()
    cache = TtlCache(clock)

    @asynccontextmanager
    async def lifespan(_: FastMCP[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        token = settings.discogs_token.get_secret_value()
        async with build_http_client(token, transport) as http:
            yield {"discogs": DiscogsClient(http, clock)}

    mcp: FastMCP[dict[str, Any]] = FastMCP(
        "cratedigger-mcp", instructions=INSTRUCTIONS, lifespan=lifespan, mask_error_details=True
    )

    def discogs_client(ctx: Context) -> DiscogsClient:
        client: DiscogsClient = ctx.lifespan_context["discogs"]
        return client

    @mcp.tool(title="Get Discogs Release", annotations=READ_ONLY, output_schema=None)
    async def discogs_get_release(
        ctx: Context,
        release_id: Annotated[int, Field(description="Discogs release_id, e.g. 249504.", gt=0)],
        response_format: Annotated[
            ResponseFormat,
            Field(
                description="concise (default): label, catalog number, Format, country, year, "
                "tracklist, have/want and Master. detailed: adds identifiers "
                "(matrix/runout, barcode) and release notes."
            ),
        ] = "concise",
    ) -> str:
        """Show the card of one Discogs Release (a specific pressing or edition) by its release_id.

        Use it when the release_id is known, for example from discogs_search results, to see
        what exactly a pressing is: label, catalog number, Format, country, year, tracklist,
        how many Discogs users have or want it, and its Master. Ask for the detailed form to
        tell near-identical pressings apart by matrix/runout etchings, barcode and notes.
        Do not use it to find a Release by name (use discogs_search) or for prices.
        """
        try:
            client = discogs_client(ctx)
            release = await cache.get_or_load(
                ("release", release_id), CATALOG_TTL, lambda: client.get_release(release_id)
            )
        except NotFoundError:
            raise ToolError(
                f"Release {release_id} not found on Discogs. "
                "Use discogs_search to find the release_id."
            ) from None
        except UnauthorizedError:
            raise ToolError(TOKEN_HINT) from None
        except DiscogsError as error:
            raise ToolError(str(error)) from None
        return release_card(release, response_format)

    return mcp


MISSING_TOKEN = (
    "cratedigger-mcp: DISCOGS_TOKEN is not set. Create a personal access token at "
    "https://www.discogs.com/settings/developers and pass it to the server in the "
    "DISCOGS_TOKEN environment variable."
)


def main() -> None:
    """Console entry point: run over stdio. stdout belongs to the protocol, logs go to stderr."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings()  # values come from the environment
    except ValidationError as error:
        if any(problem["loc"] == ("discogs_token",) for problem in error.errors()):
            sys.exit(MISSING_TOKEN)
        problems = "; ".join(
            f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}" for problem in error.errors()
        )
        sys.exit(f"cratedigger-mcp: invalid configuration: {problems}")
    create_server(settings).run(transport="stdio", show_banner=False)
