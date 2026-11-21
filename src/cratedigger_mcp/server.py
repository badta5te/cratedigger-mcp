"""The FastMCP server: a factory for tests and the stdio entry point."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated, Any

import httpx2
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from cratedigger_mcp.cache import CATALOG_TTL, PRICE_TTL, TtlCache
from cratedigger_mcp.clock import Clock, SystemClock
from cratedigger_mcp.discogs import (
    Currency,
    DiscogsClient,
    DiscogsError,
    MasterReleaseSort,
    NotFoundError,
    SearchType,
    UnauthorizedError,
    build_http_client,
)
from cratedigger_mcp.formatting import (
    ResponseFormat,
    marketplace_prices,
    master_releases,
    release_card,
    search_results,
)
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

IDENTIFY_RELEASE = """\
Help me identify exactly which Discogs Release I am holding, so that I can add the \
right one to Discogs. Here is what I can see on it:

{description}

Work through the strongest identifiers first, using discogs_search with type="release":
1. If there is a barcode, search with the barcode filter. Discogs matches it against every \
identifier of a Release, so matrix/runout text works in that filter too.
2. Otherwise search with the catalog number (catno filter) together with the artist, and \
narrow with year, format and country when the results are too many.
3. If neither is known, search by artist and title and narrow with the filters.

When a few candidates remain, open each with discogs_get_release with \
response_format="detailed" and compare its matrix/runout etchings, barcode, label, country \
and notes with what I described. Ask me to read specific details off the record (for example \
the runout etching on side A, or the text around the label rim) whenever that would tell the \
candidates apart. Don't guess: if two Releases still fit, say so and name what would separate \
them.

Finish with the release_id you are confident about, a one-line summary of the Release, and \
why it matches."""


def given_filters(**filters: str | int | None) -> dict[str, str | int]:
    """The filters the caller actually gave: neither left out nor empty."""
    return {name: value for name, value in filters.items() if value is not None and value != ""}


def tool_error(error: DiscogsError) -> ToolError:
    """The tool error Claude sees for a Discogs failure, with the next step to take."""
    if isinstance(error, UnauthorizedError):
        return ToolError(TOKEN_HINT)
    return ToolError(str(error))


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
        Do not use it to find a Release by name (use discogs_search) or for prices
        (use discogs_get_prices).
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
        except DiscogsError as error:
            raise tool_error(error) from None
        return release_card(release, response_format)

    @mcp.tool(title="Search Discogs Catalog", annotations=READ_ONLY, output_schema=None)
    async def discogs_search(
        ctx: Context,
        query: Annotated[
            str,
            Field(description="Free text: artist, title, label or any mix, e.g. 'Kind of Blue'."),
        ] = "",
        type: Annotated[
            SearchType,
            Field(
                description="What to find: release (default, a specific pressing), master "
                "(the album as a whole), artist or label. The filters apply to release and "
                "master searches only."
            ),
        ] = "release",
        artist: Annotated[str | None, Field(description="Only this artist.")] = None,
        year: Annotated[int | None, Field(description="Only this release year.", gt=0)] = None,
        format: Annotated[
            str | None, Field(description="Only this Format, e.g. Vinyl, CD, Cassette, LP.")
        ] = None,
        country: Annotated[
            str | None, Field(description="Only Releases from this country, e.g. UK, Japan.")
        ] = None,
        catno: Annotated[
            str | None, Field(description="Catalog number as printed, e.g. PB 41447.")
        ] = None,
        barcode: Annotated[
            str | None,
            Field(
                description="Barcode digits, or other identifier text such as a matrix/runout "
                "etching: Discogs matches it against every identifier of a Release."
            ),
        ] = None,
        limit: Annotated[int, Field(description="Results per page.", ge=1, le=50)] = 10,
        page: Annotated[int, Field(description="Page of results, from 1.", ge=1)] = 1,
    ) -> str:
        """Search the Discogs catalog for Releases (pressings), Masters, artists or labels.

        Use it to find a release_id or master_id by name, or to find the exact pressing the
        Owner is holding by narrowing with artist, year, Format, country, catalog number or
        barcode. Each result carries the release_id/master_id for discogs_get_release and the
        other tools. Results are paged: the response states the page and the total.
        Do not use it to check what the Owner has or wants: use discogs_list_collection or
        discogs_list_wantlist, and discogs_match_collection for a list of albums.
        """
        filters = given_filters(
            artist=artist, year=year, format=format, country=country, catno=catno, barcode=barcode
        )
        query = query.strip()
        if not query and not filters:
            raise ToolError(
                "Give a query or at least one filter (artist, year, format, country, catno, "
                "barcode) to search Discogs."
            )
        if filters and type in ("artist", "label"):
            raise ToolError(
                "The filters artist, year, format, country, catno and barcode apply to release "
                f"and master searches only. Search {type}s by query alone."
            )
        params = {"q": query, **filters} if query else filters
        try:
            found = await discogs_client(ctx).search(type, params, per_page=limit, page=page)
        except NotFoundError as error:
            if page == 1:
                raise tool_error(error) from None
            # Discogs answers 404 for a page past the last one or past its 10,000-result depth.
            return (
                f"No results on page {page}: it is past the last page of this search, or beyond "
                "the first 10,000 results Discogs serves. Use a lower page or narrow the search."
            )
        except DiscogsError as error:
            raise tool_error(error) from None
        return search_results(found, type, query, filters)

    @mcp.tool(title="List Releases of a Discogs Master", annotations=READ_ONLY, output_schema=None)
    async def discogs_list_master_releases(
        ctx: Context,
        master_id: Annotated[int, Field(description="Discogs master_id, e.g. 96559.", gt=0)],
        format: Annotated[
            str | None,
            Field(description='Only this Format, exactly as Discogs writes it: Vinyl, CD, 7".'),
        ] = None,
        country: Annotated[
            str | None,
            Field(description="Only Releases from this country, exactly as Discogs writes it: UK."),
        ] = None,
        year: Annotated[int | None, Field(description="Only this release year.", gt=0)] = None,
        sort: Annotated[
            MasterReleaseSort,
            Field(
                description="Order of the list: released (default, oldest first), title, "
                "format, label, catno or country."
            ),
        ] = "released",
        limit: Annotated[int, Field(description="Releases per page.", ge=1, le=50)] = 20,
        page: Annotated[int, Field(description="Page of Releases, from 1.", ge=1)] = 1,
    ) -> str:
        """List the Releases of a Discogs Master: all pressings, versions and editions of an album.

        Use it to compare the available editions of an album by country, year, label, catalog
        number and Format, narrowed to one Format, country or year. Each line carries the
        release_id for discogs_get_release. Results are sorted by release date unless another
        sort is asked for, and paged.
        Find the master_id with discogs_search (type="master") or on a Release card.
        """
        filters = given_filters(format=format, country=country, year=year)
        params = {
            **{("released" if name == "year" else name): value for name, value in filters.items()},
            "sort": sort,
            "sort_order": "asc",
        }
        client = discogs_client(ctx)
        try:
            # Looked up first: Discogs does not answer an unknown Master's versions with 404.
            master = await cache.get_or_load(
                ("master", master_id), CATALOG_TTL, lambda: client.get_master(master_id)
            )
            found = await cache.get_or_load(
                ("master_releases", master_id, tuple(params.items()), limit, page),
                CATALOG_TTL,
                lambda: client.list_master_releases(master_id, params, per_page=limit, page=page),
            )
        except NotFoundError:
            raise ToolError(
                f"Master {master_id} not found on Discogs. "
                'Use discogs_search with type="master" to find the master_id.'
            ) from None
        except DiscogsError as error:
            raise tool_error(error) from None
        return master_releases(master, found, filters, sort)

    @mcp.tool(title="Get Discogs Marketplace Prices", annotations=READ_ONLY, output_schema=None)
    async def discogs_get_prices(
        ctx: Context,
        release_ids: Annotated[
            list[Annotated[int, Field(gt=0)]],
            Field(
                description="1 to 10 Discogs release_ids, e.g. [249504].",
                min_length=1,
                max_length=10,
            ),
        ],
        currency: Annotated[
            Currency | None,
            Field(description=f"Currency of the prices; {settings.discogs_currency} by default."),
        ] = None,
    ) -> str:
        """Show what Releases (pressings) cost on the Discogs Marketplace right now.

        For each of 1 to 10 release_ids: the Lowest price, how many copies are for sale and
        whether the Release is blocked from sale, with the time Discogs reported it. The Lowest
        price is the cheapest current listing in any condition, excluding shipping: not a
        market value. Use it to compare editions by price, for example after
        discogs_list_master_releases. For the prices of the Owner's Wantlist use
        discogs_wantlist_prices.
        """
        chosen = currency or settings.discogs_currency
        client = discogs_client(ctx)
        checks, unknown = [], []
        # One after another: a failure leaves no requests running, and the checks that
        # succeeded are cached for the next call.
        for release_id in dict.fromkeys(release_ids):  # asked twice, shown once
            try:
                checks.append(
                    await cache.get_or_load(
                        ("price", release_id, chosen),
                        PRICE_TTL,
                        partial(client.check_marketplace, release_id, chosen),
                    )
                )
            except NotFoundError:
                unknown.append(release_id)
            except DiscogsError as error:
                raise tool_error(error) from None
        if unknown:
            raise ToolError(
                ("Releases " if len(unknown) > 1 else "Release ")
                + ", ".join(map(str, unknown))
                + " not found on Discogs. Use discogs_search to find the release_id, then ask "
                "again."
            )
        return marketplace_prices(checks, chosen)

    @mcp.prompt(title="Identify a Discogs Release")
    def identify_release(
        description: Annotated[
            str,
            Field(
                description="What the Owner sees on the record: artist, title, label, "
                "catalog number, barcode, matrix/runout etchings, sleeve details."
            ),
        ],
    ) -> str:
        """Find out which Discogs Release (pressing) the Owner is holding."""
        return IDENTIFY_RELEASE.format(description=description)

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
