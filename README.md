# Cratedigger for Discogs

`cratedigger-mcp` is a small local [MCP](https://modelcontextprotocol.io) server that lets Claude
answer everyday questions about your Discogs world: Releases and pressings in the catalog,
Marketplace prices, and your own Collection and Wantlist.

It runs on your machine over stdio, talks to the Discogs API with your personal access token and
stores nothing on disk.

> **Status:** early development. Available tools so far:
>
> - `discogs_get_release`: the card of one Release by `release_id`: label, catalog number, Format,
>   country, year, tracklist, have/want counts and Master. Its detailed form adds identifiers
>   (matrix/runout, barcode) and release notes.

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

## Development

Requires uv 0.13.x and [just](https://just.systems).

```sh
uv sync          # create .venv from uv.lock
just check       # ruff, mypy and pytest: the same command CI runs on Python 3.12–3.14
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
