# Runout for Discogs

<!-- mcp-name: io.github.badta5te/runout-mcp -->

`runout-mcp` is a small local [MCP](https://modelcontextprotocol.io) server that lets Claude
answer everyday questions about your Discogs world: Releases and pressings in the catalog,
Marketplace prices, and your own Collection and Wantlist.

- "Which pressings of *Kind of Blue* exist, and how do they differ?"
- "What does this Release cost on Discogs right now?"
- "Do I have anything by Can? On vinyl or only on CD?"
- "Which of my 50 most-played albums on Last.fm are not on my shelf yet?"
- "What on my Wantlist is under 20 EUR right now?"

It runs on your machine over stdio, talks to the Discogs API with your own personal access token
and stores nothing on disk.

The name follows the Discogs rule for applications built on its API ("… for Discogs"). The
package and the command are both called `runout-mcp`.

## Tools

| Tool | What it answers |
|---|---|
| `discogs_search` | Find Releases (pressings), Masters, artists or labels in the catalog by free text, narrowed by artist, year, Format, country, catalog number or barcode |
| `discogs_get_release` | The card of one Release: label, catalog number, Format, country, year, tracklist, have/want counts and Master; the detailed form adds matrix/runout, barcode and notes |
| `discogs_list_master_releases` | Every Release of a Master, to compare the Releases of an album by country, year, label, catalog number and Format |
| `discogs_get_prices` | The Lowest price, the number of copies for sale and the blocked-from-sale flag of 1 to 10 Releases |
| `discogs_list_collection` | The Copies in your Collection, newest first, filtered by artist or title, by folder, with Format and condition |
| `discogs_collection_summary` | How many Copies each folder holds, and Discogs' minimum/median/maximum estimate of the Collection's value |
| `discogs_match_collection` | Which of up to 200 albums from another source (Last.fm, Spotify, a pasted list) are in your Collection, on your Wantlist, possible matches or absent |
| `discogs_list_wantlist` | The Wants on your Wantlist, newest first, filtered by artist or title |
| `discogs_wantlist_prices` | The Lowest price of up to 30 Wants per call, cheapest first, optionally under a maximum price |
| `discogs_wantlist_add` | Adds a Release to your Wantlist; adding one that is already wanted changes nothing |
| `discogs_wantlist_remove` | Removes a Want; marked destructive, so Claude asks you to confirm every call |

And one prompt, `identify_release`, that walks Claude through finding the exact Release you hold
from its barcode, catalog number and matrix/runout etchings.

No tool changes your Collection. A Lowest price is the cheapest current listing in any
condition, excluding shipping: not a market value. There is no price watch; Discogs' own
Wantlister sends alerts for your Wants.

## Requirements

- [uv](https://docs.astral.sh/uv/), which provides `uvx`.
- A Discogs personal access token: open
  [Discogs → Settings → Developers](https://www.discogs.com/settings/developers) and click
  **Generate new token**. The server refuses to start without it, and finds your Discogs
  username from it.

## Installation

There is nothing to install by hand: Claude starts the server with

```sh
uvx runout-mcp
```

which downloads the package from PyPI on first use and runs it in an isolated environment. Pin a
version with `uvx runout-mcp@0.1.0`.

### Claude Desktop

Claude Desktop does not see your shell `PATH`, so give it the **absolute path to `uvx`**: find
it with `which uvx` (macOS) or `where uvx` (Windows). Open **Settings → Developer → Edit
Config**, or edit the file directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "runout": {
      "command": "/absolute/path/to/uvx",
      "args": ["runout-mcp"],
      "env": { "DISCOGS_TOKEN": "your-personal-access-token" }
    }
  }
}
```

Restart Claude Desktop.

### Claude Code

```sh
claude mcp add runout --scope user -e DISCOGS_TOKEN=your-personal-access-token \
  -- uvx runout-mcp
```

`--scope user` makes the server available in every project; leave it out to add it to the
current project only. Check the connection with `claude mcp list` or `/mcp` inside Claude Code.

Then ask, for example: "Show me Discogs release 249504 in detail."

## Configuration

The server reads its settings from the environment, which the Claude configuration above sets.

| Environment variable | Required | Meaning |
|---|---|---|
| `DISCOGS_TOKEN` | yes | Your Discogs personal access token |
| `DISCOGS_CURRENCY` | no | Currency of prices: USD, GBP, EUR (default), CAD, AUD, JPY, CHF, MXN, BRL, NZD, SEK or ZAR. A tool call can still ask for another one. |

## How it treats your data

- **Nothing is stored on disk.** Discogs data lives only in memory while the server runs:
  catalog lookups and prices for an hour, the Collection and the Wantlist for at most five
  minutes, and the first page of each is checked again on every call, so a Copy or Want you add
  on Discogs shows at once.
- **The token stays private.** It is sent only to `api.discogs.com` and never appears in logs,
  tool output or error messages.
- **The server paces itself** on the Discogs rate-limit headers and retries briefly when Discogs
  asks it to slow down.
- Your Collection, Wantlist and prices reach Claude as tool results, like anything else you ask
  Claude about.

## Development

Requires uv 0.13.x and [just](https://just.systems).

```sh
uv sync          # create .venv from uv.lock
just check       # ruff, mypy and pytest: the same command CI runs on Python 3.12–3.15
just fix         # apply ruff fixes and formatting
just serve       # run the server over stdio from the checkout (needs DISCOGS_TOKEN)
```

To try a local checkout in Claude, use `uvx --from /absolute/path/to/runout-mcp
runout-mcp` as the command.

Tests build the server through `create_server()` and call its tools through FastMCP's in-memory
client against a fake Discogs (`httpx2.MockTransport`) serving anonymized fixtures. No test touches
the network.

### Releasing

Pushing a version tag publishes the package to PyPI through
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/): GitHub Actions proves its
identity to PyPI with OIDC, so no PyPI token is stored anywhere.

1. Set the new version in `pyproject.toml` and in both `version` fields of `server.json`, then
   run `uv lock` and commit.
2. Tag and push: `git tag -a v0.1.0 -m v0.1.0 && git push origin v0.1.0`. The release workflow
   checks that the tag and both files name the same version, runs the checks, builds and
   publishes.
3. Publish the entry to the [MCP Registry](https://registry.modelcontextprotocol.io) once the
   version is on PyPI: `mcp-publisher login github`, then `mcp-publisher publish`.

One-time setup before the first release: on PyPI, add a pending trusted publisher for the
project `runout-mcp` with owner `badta5te`, repository `runout-mcp`, workflow
`release.yml` and environment `pypi`; on GitHub, create the `pypi` environment under
**Settings → Environments**.

## Discogs

Every response that contains Discogs data ends with "Data provided by Discogs" and a link to the
data on discogs.com.

This application uses Discogs’ API but is not affiliated with, sponsored or endorsed by Discogs.
‘Discogs’ is a trademark of Zink Media, LLC.

## License

Released under the [MIT License](https://github.com/badta5te/runout-mcp/blob/main/LICENSE).
Copyright (c) 2026 Pavel Mikhailov.
