# Cratedigger for Discogs

`cratedigger-mcp` is a small local [MCP](https://modelcontextprotocol.io) server that lets Claude
answer everyday questions about your Discogs world: Releases and pressings in the catalog,
Marketplace prices, and your own Collection and Wantlist.

It runs on your machine over stdio, talks to the Discogs API with your personal access token and
stores nothing on disk.

> **Status:** early development. Available tools so far:
>
> - `discogs_search`: search the catalog for Releases (default), Masters, artists or labels by
>   free text, narrowed by artist, year, Format, country, catalog number or barcode. Results are
>   paged and carry the `release_id`/`master_id` for the next call.
> - `discogs_get_release`: the card of one Release by `release_id`: label, catalog number, Format,
>   country, year, tracklist, have/want counts and Master. Its detailed form adds identifiers
>   (matrix/runout, barcode) and release notes.
> - `discogs_list_master_releases`: the Releases of a Master by `master_id`, to compare the
>   editions of an album by country, year, label, catalog number and Format. It filters by
>   Format, country and year, sorts by release date by default and pages, and every line carries
>   the `release_id`.
> - `discogs_get_prices`: the Lowest price (the cheapest current listing in any condition,
>   excluding shipping), the number of copies for sale and the blocked-from-sale flag of 1 to 10
>   Releases, with the time each was checked. Prices are kept in memory for an hour.
> - `discogs_list_collection`: the Copies in your Collection, newest first by default, filtered
>   by artist or title text, narrowed to one folder, sorted and paged. Each line carries the
>   Release, its Format, its condition (Media and Sleeve grades) and the `release_id`, and marks
>   Releases you have several Copies of.
> - `discogs_list_wantlist`: the Wants on your Wantlist, newest first, filtered by artist or
>   title text and paged. Each line carries the Release, its Format and the `release_id`.
> - `discogs_wantlist_prices`: the Lowest price of up to 30 Wants per call (a page of your
>   Wantlist, newest first), sorted from cheapest, optionally only those at or under
>   `max_price` and filtered by artist or title text. Wants with nothing for sale are listed
>   apart, and the response says which page to check next. It shares the one-hour price cache
>   with `discogs_get_prices`. There is no price watch: Discogs' own Wantlister sends alerts.
> - `discogs_wantlist_add`: adds a Release to your Wantlist by `release_id` and returns a short
>   card of it. Adding a Release that is already wanted succeeds and changes nothing.
> - `discogs_wantlist_remove`: removes a Want by `release_id`. It is marked destructive and
>   asks for your confirmation on every call; a Release that is not on the Wantlist is an
>   error. Both Wantlist tools drop the cached Wantlist, so the next listing is fetched afresh;
>   Discogs' own listing can take about 10 seconds to show the change.
>   No tool changes your Collection.
> - `discogs_collection_summary`: the number of Copies in each folder and Discogs'
>   minimum/median/maximum estimate of the Collection's value.
> - `discogs_match_collection`: checks 1 to 200 artist/album pairs from any other source
>   (Last.fm, Spotify, a pasted list) against your Collection and Wantlist. Each album is in
>   Collection (any Release of its Master, in any Format, with the matching Copies listed), on
>   Wantlist, possible (a longer or shorter title of the same artist under another Master, such
>   as a reissue with an added subtitle or a live album; titles that differ only by a series
>   number such as "III" or "Vol. 2" count as different albums) or absent. Names match ignoring case, diacritics, punctuation, a leading "The", "&" versus "and"
>   and edition qualifiers such as "(Remastered)". It reads only your Collection and Wantlist
>   and never searches the catalog per album.
>
> The server finds your username from the token. It keeps the Collection and the Wantlist in
> memory and checks their first page on every call, so a Want or Copy you add on Discogs shows
> at once while a follow-up question costs one or two Discogs requests.
>
> And one prompt:
>
> - `identify_release`: guides Claude through finding the exact Release you hold from its
>   barcode, catalog number and matrix/runout etchings.

## Requirements

- [uv](https://docs.astral.sh/uv/) (provides `uvx`)
- A Discogs personal access token: open
  [Discogs → Settings → Developers](https://www.discogs.com/settings/developers) and click
  **Generate new token**. The server refuses to start without it.

## Connect to Claude

The package is not on PyPI yet. Until it is, run it from a local checkout with
`uvx --from /absolute/path/to/cratedigger-mcp cratedigger-mcp`. After the first release this
becomes plain `uvx cratedigger-mcp`.

### Claude Desktop

Claude Desktop on macOS does not see your shell `PATH`, so give it the **absolute path to
`uvx`** (find it with `which uvx`). Add this to
`~/Library/Application Support/Claude/claude_desktop_config.json` and restart Claude Desktop:

```json
{
  "mcpServers": {
    "cratedigger": {
      "command": "/absolute/path/to/uvx",
      "args": ["--from", "/absolute/path/to/cratedigger-mcp", "cratedigger-mcp"],
      "env": { "DISCOGS_TOKEN": "your-personal-access-token" }
    }
  }
}
```

### Claude Code

```sh
claude mcp add cratedigger --env DISCOGS_TOKEN=your-personal-access-token \
  -- uvx --from /absolute/path/to/cratedigger-mcp cratedigger-mcp
```

Then ask, for example: "Show me Discogs release 249504 in detail."

### Settings

| Environment variable | Required | Meaning |
|---|---|---|
| `DISCOGS_TOKEN` | yes | Your Discogs personal access token |
| `DISCOGS_CURRENCY` | no | Currency of prices: USD, GBP, EUR (default), CAD, AUD, JPY, CHF, MXN, BRL, NZD, SEK or ZAR. A tool call can still ask for another one. |

## Development

Requires uv 0.13.x and [just](https://just.systems).

```sh
uv sync          # create .venv from uv.lock
just check       # ruff, mypy and pytest: the same command CI runs on Python 3.12–3.15
just fix         # apply ruff fixes and formatting
just serve       # run the server over stdio (needs DISCOGS_TOKEN)
```

Tests build the server through `create_server()` and call its tools through FastMCP's in-memory
client against a fake Discogs (`httpx2.MockTransport`) serving anonymized fixtures. No test touches
the network.

## Discogs

Every response that contains Discogs data ends with "Data provided by Discogs" and a link to the
data on discogs.com.

This application uses Discogs' API but is not affiliated with, sponsored or endorsed by Discogs.
"Discogs" is a trademark of Zink Media, LLC.

## License

MIT
