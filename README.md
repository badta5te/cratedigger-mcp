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
