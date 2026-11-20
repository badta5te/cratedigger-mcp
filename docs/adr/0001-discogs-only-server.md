# The server covers Discogs only

The research (`docs/research.md`) proposed one server with three domains: Discogs, record notes and Last.fm, joined by "insights" tools. We decided the server covers Discogs only. Notes are out of scope entirely, and listening data comes from other connectors (an existing Last.fm MCP server, the official Spotify connector). Claude composes connectors; the server's contribution to cross-source questions is a source-agnostic tool that takes a list of artist/album pairs and reports which are in the Owner's Collection or Wantlist.

## Considered Options

- **Built-in Last.fm client and insights tools.** Deterministic joins over full datasets in one process, but it duplicates an existing Last.fm server and ties the project to one listening source.
- **Built-in notes store.** The Owner keeps notes in Craft, which is already a Claude connector, and does not take notes about records.

## Consequences

"What in my Collection haven't I played in a year" is only approximate: Claude must pass the whole listening list to the matching tool instead of the server joining it internally.
