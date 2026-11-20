# Research: MCP server for Discogs, record notes and Last.fm (Python, FastMCP)

Research date: **2026-11-20**. This document merges 7 parallel research tracks into a single picture. Where sources contradicted each other, the choice and the reason for it are stated explicitly.

The raw per-track notes (`01-mcp-fastmcp.md` … `07-tooling-packaging.md`) are kept locally and are not part of the repository. They use their own labels and partly contradict this document; where they diverge, **this document is authoritative**: the contradictions were resolved while merging. For example, Discogs facts come from the Discogs track rather than from "403 / from memory" in other notes; the Discogs API has no median price; the MCP spec revision is 2026-07-28.

**Label legend** (one for the whole document):

| Label | Meaning |
|---|---|
| **[DOC]** | verified in a primary source: specification, official documentation, PyPI/GitHub API, ToS |
| **[LIVE]** | verified with a live anonymous API request on 2026-11-20 |
| **[SEC]** | secondary source: blog, community forum, third-party catalog |
| **[ASSUME]** | assumption, inference or opinion not confirmed by a primary source |

**Method caveats (apply to the whole document):**
- Pages were read via WebFetch, which paraphrases the page with a summarizer model. Critical numbers (versions, dates) were re-checked via PyPI JSON / GitHub API. ToS clause numbers should be verified by eye before quoting them in the README.
- `discogs.com` (documentation, API Terms of Use, forum) is behind Cloudflare bot protection (HTTP 403). The documentation and ToS texts were read **via Wayback Machine snapshots**: docs from 2026-11-06, ToS from 2026-05-30. Opening them in a browser was not possible; the Chrome extension was not connected.
- No authenticated API requests were made; there are no real tokens.
- All code snippets in this document are illustrative and **have not been run**.
- If a page has no date of its own, the check date 2026-11-20 is given.

---

## 1. Executive summary

1. **What we're building:** a personal MCP server on FastMCP 4.x: Discogs (search, pressings, prices, collection, wantlist) + record notes + optionally Last.fm.
2. **Urgent:** from **2026-12-01** the anonymous Discogs API returns 401 [DOC], so a personal token is needed from day one.
3. **Main conflict:** under the Discogs ToS, prices are "Restricted Data": they may be stored "no longer than necessary" and shown no older than 6 h [DOC, ToS snapshot 2026-05-30].
4. Hence **long-term price history is in question**: stage 2 forks into a price watch without history, or history after permission from Discogs (open question #1).
5. **Niche:** linking the collection with Last.fm, notes keyed by `release_id`, pressing comparison, price tracking. API wrappers already exist.
6. **No Spotify:** the API is cut down, the Policy forbids "ingest" into AI, and an official Claude connector already exists.
7. **Tooling:** uv (≈ bundler + rbenv), ruff (≈ rubocop), pytest, mypy, pydantic-settings, uv_build, Trusted Publishing, `uvx`.
8. **Remote:** public HTTPS on 443 and OAuth (FastMCP `GitHubProvider` + login allowlist); bearer tokens in claude.ai are a beta not available to everyone.

---

## 2. Findings across 9 tracks

### 2.1 MCP and FastMCP today

**MCP specification**
- Current revision **`2026-07-28`**, previous `2025-11-25` [DOC] ([versioning](https://modelcontextprotocol.io/specification/versioning), [changelog 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).
- This is the biggest change of the year: the protocol became **stateless**. There is no `initialize` handshake and no `Mcp-Session-Id`; server-initiated requests (elicitation, sampling, roots) are replaced by Multi Round-Trip Requests [DOC].
- Deprecated (removal no earlier than the revision after 2027-07-28): **Roots, Sampling, Logging, Dynamic Client Registration (DCR), HTTP+SSE** [DOC] ([deprecated](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)).
- Tasks moved into the `io.modelcontextprotocol/tasks` extension [DOC].
- Timeline for the year: 2025-06-18 added structured output (`outputSchema`), elicitation and OAuth Resource Server; 2025-11-25 added CIMD, experimental tasks, URL-mode elicitation; 2026-07-28 made it stateless [DOC] (changelog of each revision).

**Library versions**
- **FastMCP 4.2.3** (PyPI, 2026-11-20), 4.0.0 released 2026-08-31, Python ≥ 3.11 [DOC] ([PyPI](https://pypi.org/project/fastmcp/), [releases](https://github.com/PrefectHQ/fastmcp/releases)). Repository `PrefectHQ/fastmcp`, Apache-2.0 license.
- Official SDK **`mcp` 2.3.0** (2026-10-02) [DOC]. In SDK v2, `mcp.server.fastmcp.FastMCP` was **removed**; use `from mcp.server import MCPServer` instead ([what's new SDK v2](https://py.sdk.modelcontextprotocol.io/whats-new/)).
- FastMCP 4 is built on SDK v2 and **negotiates the protocol version per connection**: old handshake clients keep working [DOC] ([v4.0.0 release](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0)).
- Beginner trap: there are three different imports floating around the internet. We need `from fastmcp import FastMCP` (the `fastmcp` package). `mcp.server.fastmcp` is SDK v1 and is obsolete.

**Choice: `fastmcp` 4.x.** Analogy: the SDK is Rack, FastMCP is Sinatra/Grape. FastMCP already ships auth providers, HTTP deployment, middleware and an in-memory client for tests [DOC] ([from-mcp-sdk-v2](https://gofastmcp.com/docs/getting-started/upgrading/from-mcp-sdk-v2.md)). The FastMCP docs themselves warn that "breaking changes may occur in minor versions" [DOC] ([installation](https://gofastmcp.com/getting-started/installation)). Hence a narrow pin: `fastmcp>=4.2.3,<4.3` plus `uv.lock`.

**Transports** [DOC] ([transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http.md), [FastMCP running](https://gofastmcp.com/docs/deployment/running-server.md)):
- **stdio** for local runs (`mcp.run()`). **Never write to stdout**: any `print()` breaks JSON-RPC; logs go to stderr only.
- **Streamable HTTP** for remote: `mcp.run(transport="http", host="127.0.0.1", port=8000)`, endpoint `/mcp`.
- SSE is legacy; don't use it.

**Primitives** (Rails analogy):
- **Tools**: roughly controller actions that the model chooses and calls.
- **Resources**: roughly read-only GET routes that the model or the user "attaches" to the context. Templates like `notes://{path}` are the analogue of a route with a parameter.
- **Prompts**: message templates the user triggers; in Claude Code they appear as `/server:prompt` [DOC].

**Tool annotations** (per `schema.ts` of revision 2026-07-28) [DOC] ([schema.ts](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts)):

| Hint | Meaning | Default |
|---|---|---|
| `readOnlyHint` | the tool changes nothing | `false` |
| `destructiveHint` | may delete or overwrite (meaningful only when `readOnlyHint=false`) | `true` |
| `idempotentHint` | a repeated call has no additional effect | `false` |
| `openWorldHint` | reaches the outside world (Discogs: yes, local notes: no) | `true` |

- Annotations are only hints; the client is not required to trust them [DOC].
- **Claude Code** runs tools with `readOnlyHint=true` in parallel and allows retrying them after a dropped connection [DOC] ([Claude Code MCP](https://code.claude.com/docs/en/mcp)). What it does with `destructiveHint` is not documented [ASSUME].
- The Anthropic connector directory requires `title` and `readOnlyHint`/`destructiveHint` on every tool: read-only tools run without confirmation, destructive ones always ask [DOC] ([review criteria](https://claude.com/docs/connectors/building/review-criteria.md)). This is a good rule for our project too.

**Elicitation, sampling and other capabilities in Claude clients** [DOC unless stated otherwise]:
- **Elicitation:** works in Claude Code; unconfirmed in claude.ai/Desktop, the issues are contradictory [SEC].
- **Sampling:** **not supported** in claude.ai/Desktop ([connectors/building](https://www.claude.com/docs/connectors/building)); `ctx.sample()` was removed in FastMCP 4.
- **Progress:** supported, but in Claude Code it does not extend the timeout.
- **Limits:** per-call timeout in claude.ai/Desktop is 240 s.
- **Conclusion:** **we don't build on elicitation or sampling**; write confirmation is done via separate write tools.

**Remote server authorization per the spec** [DOC] ([authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization.md)):
- An MCP server is an OAuth 2.1 resource server. It must serve **Protected Resource Metadata (RFC 9728)** and validate the token audience; the client passes `resource` (RFC 8707).
- Client registration order: pre-registered → **CIMD** → DCR (deprecated).
- stdio needs no authorization; credentials come from env.
- In FastMCP 4: `JWTVerifier`, `OAuthProxy`, `GitHubProvider`, `StaticTokenVerifier` (dev only). The default is `auth=None`, meaning the HTTP endpoint is **open to everyone** [DOC] ([auth](https://gofastmcp.com/docs/servers/auth/authentication.md)).

Snippet (not run; annotations are passed as a dict because the casing of the `ToolAnnotations` model in FastMCP 4 was not verified; the `instructions=` parameter is written from memory [ASSUME], while the Claude Code docs confirm that server instructions matter):
```python
from fastmcp import FastMCP

mcp = FastMCP("vinyl", instructions="Discogs vinyl collection, wantlist, pressings, prices; record notes.")

@mcp.tool(annotations={"title": "Search Discogs", "readOnlyHint": True, "openWorldHint": True})
async def discogs_search(query: str, limit: int = 10) -> str:
    """Search the Discogs database for releases. ..."""
```

### 2.2 Discogs API

Source: [developer docs](https://www.discogs.com/developers) via the Wayback snapshot of 2026-11-06, plus live requests [LIVE].

**Auth** [DOC]:

| Credentials | Limit | Own collection/wantlist | When needed |
|---|---|---|---|
| none | 25/min | no | **stops working from 2026-12-01 (401)** ([forum, ~2026-11-02](https://www.discogs.com/forum/thread/1189875)) |
| consumer key/secret | 60/min | no | public app without login |
| **personal access token** | 60/min | **yes, for the owner** | **our case** |
| OAuth 1.0a | 60/min | yes, for any user | multi-user service |

- Header: `Authorization: Discogs token=...` [DOC].
- **User-Agent is mandatory** and must be unique (`AppName/0.1 +url`). Generic UAs are rate-limited harder [DOC].
- `GET /oauth/identity` returns the token owner's username [DOC].

**Endpoints we need** [DOC; behavior marked LIVE]:

| Path | Auth | What it gives |
|---|---|---|
| `GET /database/search` | token | `q`, `type`, `artist`, `release_title`, `label`, `catno`, `barcode`, `format`, `country`, `year`, `sort`. **Search depth is capped at 10,000 results** [LIVE]; the docs don't say so |
| `GET /releases/{id}` | opt. | formats, labels/catno, identifiers (barcode, matrix), tracklist, `community.have/want`, `lowest_price` (a number without currency), `num_for_sale`, `master_id` |
| `GET /masters/{id}/versions` | opt. | **pressings**; filters `format`, `label`, `released`, `country`, `sort`, pagination [LIVE] |
| `GET /marketplace/stats/{id}?curr_abbr=` | opt. | `lowest_price{value,currency}`, `num_for_sale`, `blocked_from_sale`. **No median** [LIVE] |
| `GET /marketplace/price_suggestions/{id}` | token + **completed seller settings** | price for 8 grades (Mint…Poor) in the selling currency; empty object if there is no data |
| `GET /users/{u}/collection/folders/{id}/releases` | owner (except public folder 0) | collection, pagination, `sort` |
| `GET /users/{u}/collection/value` | owner | min/median/max **as strings** with a currency symbol |
| `GET/PUT/POST/DELETE /users/{u}/wants[/{id}]` | owner for writes | wantlist; PUT adds an entry (201) |

**What the API lacks** [DOC]: sales history, medians, a list of listings per release. "Prices" in the API are limited to `lowest_price`, `num_for_sale` and `price_suggestions`.

**Rate limit** [DOC + LIVE]:
- 60/min with auth; sliding 60 s window.
- Headers `X-Discogs-Ratelimit`, `-Used`, `-Remaining`; 429 when exceeded.
- Unclear whether the limit is per IP or per account. There is a recent forum thread "Authenticated requests limits behavior change" (~2026-10-29, [thread 1188759](https://www.discogs.com/forum/thread/1188759)); it was **not read**.
- The ToS forbids circumventing the limit with additional keys [DOC].

**Pagination** [DOC]:
- `page`/`per_page`, default 50, maximum 100. The response contains `pagination{page,pages,items,urls}`.
- Live, `per_page=500` also worked [LIVE], but it must not be relied on.

**Docs vs live discrepancies** [LIVE]:
- `/releases/{id}/stats` returned `{"is_offensive":false}` instead of have/want, so take have/want from `/releases`.
- Search still works anonymously, although per the docs it has required auth since 2014.
- `curr_abbr` in `/releases` doesn't change `lowest_price`, so use `/marketplace/stats` for prices.

**API Terms of Use** ([ToS](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use), "Last Updated: May 27th, 2025", read **via the Wayback snapshot of 2026-05-30**; later changes are not visible) [DOC]:
- **CC0 Data:** titles, tracklists, identifiers, credits, versions. Free to use; the same data is in the monthly data dumps.
- **Restricted Data:** user data (collection, wantlist) and **Marketplace Data**, i.e. "pricing, pricing suggestions … sales history".
- Quote: "You may not display … the Content if it is more than six (6) hours older than the information on Our online properties … You may not cache or store the Content longer than is necessary to provide a service to Your application's users."
- Restricted Data may not be transferred to third parties or used commercially.
- **Attribution is mandatory:**
  - next to the data: the phrase "Data provided by Discogs." linking (without nofollow) to a discogs.com page;
  - in the README: the disclaimer "This application uses Discogs' API but is not affiliated with, sponsored or endorsed by Discogs. 'Discogs' is a trademark of Zink Media, LLC.".
- Interpretation (not legal advice) [ASSUME]:
  - (a) a long-term `lowest_price` history conflicts with the storage clause;
  - (b) publishing a collected price database is not allowed;
  - (c) passing the collection and prices to an LLM provider may formally count as a "transfer to third party". This is a gray area; there is a forum thread "AI LLMs and Discogs Access - Claude Blocked?" ([thread 1189731](https://www.discogs.com/forum/thread/1189731)), **not read**.
- The application naming policy requires the format "unique name + for Discogs". This is a 2017 snapshot and may be outdated [DOC, [naming policy](https://www.discogs.com/help/doc/naming-your-application)].

**Client library:**
- `python3-discogs-client` is alive: v2.10 released 2026-09-29, BSD license [DOC] ([PyPI](https://pypi.org/project/python3-discogs-client/), [GitHub](https://github.com/joalla/discogs_client)).
- Downsides: it is **synchronous** (requests), and its lazy objects may silently make extra requests [ASSUME].
- **Decision:** our own thin async client (~10 GET endpoints) with its own rate limiter. Analogy: a custom Faraday client instead of a heavy gem.

### 2.3 Last.fm and Spotify

**Last.fm is the primary "what I listen to" source** [DOC] ([API](https://www.last.fm/api)):
- `user.getRecentTracks` (limit up to 200, `from`/`to`, now playing via `nowplaying="true"`), `user.getTopAlbums/Artists/Tracks` (period from `7day` to `overall`, **with playcount**), `user.getWeeklyChartList`, `album.getInfo` with `username` (the user's playcount for the album), `library.getArtists`. (`user.getWeeklyAlbumChart` for weekly ranges also exists, but its page was not opened during this research [ASSUME].)
- Reading needs **only an API key**; a session is needed only for writes (scrobble, love). The **entire scrobble history** is available.
- ToS ([tos](https://www.last.fm/api/tos)): non-commercial only; credit Last.fm; cache per HTTP headers, no more than 100 MB. The ToS says nothing about AI/ML.
- The documentation gives no numeric rate limit ("be reasonable", error 29) [DOC]. The ~5 req/s figure comes only from third-party sources [SEC].
- Library `pylast` 7.3.0 (2026-11-19) is alive but synchronous [DOC]. For 3–4 GETs, plain HTTP is simpler.
- Unconfirmed: whether API key registration is open (the form is behind a login) and whether the "hide recent listening" setting affects `getRecentTracks` [ASSUME].

**Spotify: we don't build our own layer** [DOC]:
- **Dev mode:** since 2026-02-11 (for existing apps since 2026-03-09) the app owner must have Premium, with a limit of 5 users; since 2025-05-15 extended quota is granted only to organizations with 250k MAU ([quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), [blog 2026-02-06](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)).
- **Recently played** returns only the last 50 tracks [SEC, Spotify moderator, 2024]; top items come without playcount and without albums.
- **Developer Policy III.14 / Terms IV.2.1** (v10, effective 2025-05-15): prohibits "train … or otherwise **ingest** Spotify Content into a machine learning or AI model" ([policy](https://developer.spotify.com/policy), [terms](https://developer.spotify.com/terms)). Applicability to MCP has not been officially clarified [ASSUME].
- **Terms IV.3** forbid building your own database of Spotify data.
- **OAuth:** since 2025-11-27 `localhost`, implicit grant and HTTP redirects no longer work; a refresh token lives 6 months ([redirect URI](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)).
- An official **Spotify connector in Claude** has existed since 2026-04-23 ([newsroom](https://newsroom.spotify.com/tag/claude-integration/), [catalog](https://claude.com/connectors/spotify)). It handles now playing, search, the library, and natural-language questions like "what have I listened to recently" (up to 20 entities, no counts). That's enough for conversational questions, but not for a deterministic join with Discogs.

**Bottom line:** "what I listen to" comes from Last.fm, and Spotify is covered by the official connector. Last.fm only works if Spotify and other players scrobble to it (open question #3).

### 2.4 Existing solutions

Checked via the GitHub API and the [MCP Registry API](https://registry.modelcontextprotocol.io/v0.1/servers?search=discogs) on 2026-11-20 [DOC].

| Project | Stack / license | What it does | What it lacks |
|---|---|---|---|
| [cswkim/discogs-mcp-server](https://github.com/cswkim/discogs-mcp-server) | TS, MIT, 135★, commit 2026-10-23 | ~50 tools, 1 tool = 1 endpoint, stdio + HTTP | no annotations, no price suggestions, raw JSON |
| [rianvdm/discogs-mcp](https://github.com/rianvdm/discogs-mcp) | TS/Cloudflare, MIT, 20★, v3.9.0 2026-11-09 | OAuth, KV snapshot of the collection, dedup by master, batched marketplace stats up to 50 | no price history ("doesn't remember earlier checks"), no versions |
| [hlights33/discogs-mcp](https://github.com/hlights33/discogs-mcp) | **Python**, MIT, 0★, 1 commit 2026-10-06 | price suggestions, SQLite cache + read-only `query_collection(sql)`, `dry_run` by default on writes, annotations | no price history; code maturity not checked |
| [WOIII-me/Discogs-MCP](https://github.com/WOIII-me/Discogs-MCP) | TS, MIT, frozen | `find_best_pressing`, `compare_pressings`, `rank_wantlist` | project closed 2026-11-18 |
| [rianvdm/lastfm-mcp](https://github.com/rianvdm/lastfm-mcp) | TS, MIT, 54★, listed in the Registry | full Last.fm read layer | no link to Discogs |
| Official [filesystem](https://github.com/modelcontextprotocol/servers), [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) (Apache-2.0), [StevenStavrakis/obsidian-mcp](https://github.com/StevenStavrakis/obsidian-mcp) (MIT) | — | general markdown handling, targeted edits, frontmatter, `etag` | "record notes" are not tied to a `release_id` |

- **Not covered by anyone:**
  - wantlist price history or tracking;
  - linking the collection with Last.fm ("what in my collection I haven't played in a year", "what I listen to but don't own on vinyl");
  - notes tied to `release_id`/`master_id`;
  - pressing comparison (existed only in the frozen WOIII project).
- **Licenses:**
  - **may borrow from** (with attribution): MIT/Apache — hlights33, rianvdm, WOIII, filesystem, cyanheads;
  - **must not copy code from**: basic-memory (AGPL-3.0), jerome-fosse/discogs-mcp-server (GPL-3.0), repositories without a license.
- **Discogs servers in the Registry** are only closed-source and gateway ones (cotlet, pipeworx, mrfentmen). cswkim, rianvdm and hlights33 are not listed there.

### 2.5 Tool design

Sources: Anthropic "[Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)" (2025-09-11), "[Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)", "[Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)" (2025-11-24), [tools spec](https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md), [Claude Code MCP](https://code.claude.com/docs/en/mcp) [DOC].

1. **Granularity.** "Tools that just wrap existing API endpoints often underperform". Tools are built around scenarios; each has one clear purpose and there are no overlaps. Analogy: not one action per table, but actions built around user scenarios. Target: 10–15 tools.
2. **Naming.** Domain prefix (`discogs_`, `notes_`, `lastfm_`). The spec and the Claude API allow names up to 128 characters (`[A-Za-z0-9_-]`, plus `.` in the spec); the Anthropic connector directory requires ≤ 64, so that's our target. In Claude Code the full name looks like `mcp__<server>__<tool>`, and tool search is on by default: at startup the model sees **only the tool names and the server `instructions`**. So keywords (vinyl, pressing, wantlist) belong in the names and in the instructions.
3. **Response size.**
   - Claude Code's limit is 25,000 tokens (`MAX_MCP_OUTPUT_TOKENS`) and separately 50,000 characters of text. Beyond the limit, the result is spilled to a file.
   - In claude.ai the result is capped at ~150,000 characters.
   - We aim for 2–5k tokens: `limit=10` by default, a hint like "Showing 1–10 of 134, use page=2", `response_format="concise"|"detailed"` (in Anthropic's example, concise took ~⅓ of the tokens).
   - Each result line contains a human-readable name **and** the ID for the next call: `Kind of Blue — Miles Davis (1959, Columbia, LP) [release_id=249504]`.
4. **Errors.**
   - Input validation and business errors are returned as a **tool execution error** (`isError: true`), not as a JSON-RPC error, so the model can correct itself. This was clarified in the 2025-11-25 spec [DOC].
   - In FastMCP: `raise ToolError("Release 123 not found. Use discogs_search to find the release_id.")`. The error should suggest the next action.
   - An empty result is not an error.
   - The `mask_error_details=True` flag hides the details of ordinary exceptions but not the `ToolError` text, so it must not contain secrets.
5. **Descriptions (docstrings)** are "by far the most important factor". At least 3–4 sentences: what the tool does, **when to use it and when not to**, the meaning of each parameter, what it does not return. FastMCP takes the description from the docstring and `Args`, and `Annotated[..., Field(description=...)]` takes precedence over the docstring. In Claude Code the description limit is 4,096 characters when loaded at startup.
6. **Read and write.**
   - Read tools are marked `readOnlyHint=True`.
   - Write tools are separate tools, not `action="delete"` inside a single one: annotations work at the tool level.
   - For dangerous actions there is `_meta["anthropic/requiresUserInteraction"]=true`: Claude Code asks for confirmation on every call [DOC].
7. **No `outputSchema` in the MVP.** Compact text matters more to Claude, and how Claude Code uses `structuredContent` is unconfirmed [ASSUME]. We'll revisit it if a programmatic consumer appears.

### 2.6 Storage and background jobs

- **SQLite in WAL mode:** readers don't block the writer, but there is a single writer; all processes must be on the same host, a network FS won't do; never copy the `.db` without the `-wal` file [DOC] ([sqlite.org/wal](https://www.sqlite.org/wal.html)). This fits the "collector writes, server reads (`mode=ro`)" scheme perfectly.
- **Collector options compared:**

| Option | Assessment |
|---|---|
| **CLI `collect` + systemd timer** (`OnCalendar=daily`, `Persistent=true` catches up on missed runs) [DOC] ([systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)) | **recommended for a Linux server.** Analogue: rake task + whenever, but with catch-up. Logs go to journald |
| launchd (macOS) | the systemd timer analogue if the server runs on a Mac [ASSUME] |
| cron | works, but a missed run is not caught up [ASSUME] |
| APScheduler 3.11.3 in-process | works only with a single process on an always-on machine |
| APScheduler 4.x | **pre-release**, README: "do NOT use in production" [DOC] ([GitHub](https://github.com/agronholm/apscheduler)) |
| Fly scheduled machine | a volume is bound to a single Machine, so a shared SQLite is impossible [DOC] |

- **Rate limit during collection.** The token budget is shared by the collector and the live server. One `/marketplace/stats` request per release; at ~45 req/min, 500 releases take ~11 min [ASSUME, arithmetic]. The collector reads `X-Discogs-Ratelimit-Remaining` and backs off on 429.
- **Data access:** stdlib `sqlite3` with migrations via `PRAGMA user_version`, a simplified `schema_migrations`. SQLAlchemy/Alembic is overkill for 2–3 tables [ASSUME].
- **The ToS restriction** (see 2.2) determines *what* to store: see the stage 2 branches in section 6.

### 2.7 Remote deployment

Sources: Anthropic [connectors/building](https://www.claude.com/docs/connectors/building), [authentication](https://claude.com/docs/connectors/building/authentication.md), [troubleshooting](https://claude.com/docs/connectors/building/troubleshooting.md), [custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) [DOC].

- **The server must be public.** Connectors connect from Anthropic IPs (`160.79.104.0/21`, `153.61.208.0/20`). Requirements:
  - port **443 only**;
  - a public **IPv4 A record**;
  - a hostname resolving to 10/8, 172.16/12, 192.168/16 or **100.64/10 (CGNAT, Tailscale)** is rejected;
  - **no redirects** to another host, otherwise `Authorization` is lost.
- **Tailscale-only does not work with claude.ai** [ASSUME, inferred from the requirements]. It is only suitable for Claude Code inside the tailnet.
- **Auth matrix:**

| Method | claude.ai / Desktop / mobile | Claude Code |
|---|---|---|
| OAuth (CIMD/DCR) | yes, the standard path | yes |
| Static bearer ("Request headers") | **beta, only for some organizations** [DOC]; the help center presents it as a normal step — **a contradiction**, [issue #685](https://github.com/anthropics/claude-ai-mcp/issues/685) unanswered since 2026-07-24 | yes: `claude mcp add --transport http NAME URL --header "Authorization: Bearer …"` |
| No auth | technically yes, but **unacceptable for a personal collection** | yes |

- **Recommendation:** FastMCP `GitHubProvider`, i.e. an OAuth proxy with a CIMD/DCR interface for Claude.
  - GitHubProvider admits **any** GitHub account, so an allowlist on the `login` claim via `AuthMiddleware` is required. The `login` claim was confirmed from the source code, but the check pattern itself was not tested [ASSUME].
  - Enable `host_origin_protection` with the exact hostname: in FastMCP it defaults to `False`, although the spec requires checking `Origin` [DOC].
- **Hosting:**

| Option | Cost (checked 2026-11-20) | Comment |
|---|---|---|
| Pi or mini PC at home + **Cloudflare Tunnel** | hardware + a domain on Cloudflare | no NAT/CGNAT issues; add Anthropic IPs to the WAF allowlist [DOC] |
| VPS (Hetzner etc.) + Caddy | ~€5–6/mo [SEC, prices after 2026-06-15 are contradictory] | public IPv4, systemd |
| Fly.io | shared-cpu-1x 256MB **$2.19/mo** + volume $0.15/GB, no free tier [DOC] ([pricing](https://docs.fly.io/about/pricing)) | one always-on Machine, in-process scheduler |
| Render/Railway Free, Prefect Horizon | — | ephemeral disk or sleeping, unsuitable for SQLite [DOC] |

- **Connecting:**
  1. claude.ai → **Customize → Connectors → Add custom connector**.
  2. Enter the URL `https://host/mcp` and complete the OAuth login.
  3. After that the connector is available on web, desktop and mobile, and appears automatically in Claude Code when logged in with the same account [DOC].
  4. Custom connectors are available on Free (1), Pro, Max, Team and Enterprise [DOC].
  5. Before connecting, check: `curl -i https://host/mcp` (401 is fine) and `/.well-known/oauth-protected-resource` (200 JSON).

### 2.8 Testing and evals

Levels, by analogy with Rails:

| Level | Tool | Analogue |
|---|---|---|
| unit | pytest on pure formatting and error-mapping functions | model specs |
| integration | **in-memory `fastmcp.Client(mcp)`** + a stubbed HTTP transport | request specs (Rack::Test) |
| manual | `fastmcp dev inspector server.py` (UI) or `fastmcp call server.py discogs_search query=...` | Postman / `rails console` |
| schema smoke test in CI | MCP Inspector CLI `--method tools/list --strict` (requires Node) | — |
| tool-selection evals | a custom script on the Anthropic SDK | — |

- **In-memory client** [DOC] ([testing](https://gofastmcp.com/patterns/testing), [client tools](https://gofastmcp.com/clients/tools)): runs in the same process, without stdio. `call_tool` raises `ToolError` by default; with `raise_on_error=False` you can check `result.is_error`. In FastMCP 4 the attributes are snake_case. Config: `pytest-asyncio` and `asyncio_mode = "auto"`.
- **Mocking HTTP.**
  - FastMCP 4 and SDK v2 use **`httpx2`**, a fork of httpx by the Pydantic team, because httpx itself has had no stable release since 2024-12-06 [DOC] ([PyPI httpx2](https://pypi.org/project/httpx2/)).
  - `respx` and `pytest-httpx` are tied to the old `httpx`.
  - **Decision:** the Discogs client accepts an `AsyncClient` via its constructor, and tests pass it `httpx2.MockTransport(handler)`. This is the analogue of a Faraday test adapter. `MockTransport` was confirmed from the httpx2 source [DOC].
  - Fixtures are real JSON responses, saved once and **anonymized**. No VCR cassettes: risk of leaking the token and the personal collection.
- **Contract test on `list_tools`:** names, annotations, description length ≥ ~150 characters. Can be done with `inline-snapshot` [DOC].
- **Evals.**
  - The MCP connector in the Claude API **cannot use local stdio**; it needs public HTTP [DOC] ([mcp-connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)).
  - So evals are a script: `list_tools()` → `messages.create(tools=...)` with `tool_choice: auto`, a single turn, compare the tool name and a subset of the arguments.
  - Set: 15–30 YAML cases, ~20% of them held out.
  - Case types: "collection, wantlist or search" and "release or versions" traps; cases where the tool must not write anything unless asked.
  - Metrics: selection accuracy, extra calls, `input_tokens` of the tool catalog.
  - Run manually after editing descriptions, not in CI (it's paid and non-deterministic).
  - promptfoo is alive and supports MCP, but it's Node; Inspect AI is overkill; mcp-evals is not recommended [DOC/ASSUME].

### 2.9 Packaging and Python tooling

It's true that Python has no single "Rails way". But by the end of 2026 a de facto standard has formed around the Astral tools. In March 2026 Astral joined OpenAI and promised to keep the tools open source ([post 2026-03-19](https://astral.sh/blog/openai)) [DOC]. The formats are standard (`pyproject.toml`, PEP 735), so lock-in is minimal.

| Task | Tool (version, date) | Ruby analogue | Why |
|---|---|---|---|
| Python versions | **uv** 0.13.9 (2026-11-17), `.python-version` | rbenv + `.ruby-version` | uv downloads the required Python itself [DOC] ([docs](https://docs.astral.sh/uv/)) |
| dependencies, venv, running | **uv**: `uv add`, `uv sync`, `uv run` | bundler: `bundle add`, `bundle install`, `bundle exec` | one fast tool; poetry and pdm are alive, but there's no reason to pick them for a new project [ASSUME] |
| lock | `uv.lock` (commit it); `uv sync --locked` in CI | Gemfile.lock, `--frozen` | [DOC]. PEP 751 `pylock.toml` is supported only as an export |
| dev dependencies | `[dependency-groups] dev` (PEP 735) | `group :development, :test` | not included in the published package [DOC] |
| linter and formatter | **ruff** 0.17.6 (2026-11-19) | rubocop | one binary instead of flake8, isort and black [DOC] |
| types | **mypy** 2.4.1 (2026-10-28) or pyright; **ty** is beta 0.0.107 | Sorbet / Steep | ty is still beta, so not the only gate [DOC] |
| tests | **pytest** 9.2.0 + **pytest-asyncio** 1.5.0 | RSpec; `conftest.py` ≈ `spec_helper`, fixtures ≈ `let` | as in the FastMCP docs [DOC] |
| HTTP client | **httpx2** 2.16.2 (2026-11-16) | Faraday | already comes transitively with FastMCP 4; async [DOC] |
| models and validation | **pydantic** 2.x | ActiveModel / dry-struct | FastMCP builds the tools' JSON Schema from annotations, so **type hints are functional here** |
| settings and secrets | **pydantic-settings** (`SecretStr`, `.env`) | `ENV.fetch` / credentials | [DOC] |
| logging | stdlib `logging` → **stderr** | `Rails.logger` | stdout is taken by the protocol [DOC] |
| developer tasks | `justfile` (just 1.59) + `uv run` | rake, `bin/*` | Python has no built-in rake [ASSUME] |
| git hooks | optional: pre-commit or lefthook | overcommit / lefthook | CI is enough for a single developer [ASSUME] |
| CI | GitHub Actions + `astral-sh/setup-uv` (v10.4.0) | `ruby/setup-ruby` | [DOC] |
| build | `uv build`, backend **uv_build** (`>=0.13.9,<0.14`) | `gem build` + gemspec | pure-Python only, which is enough for us [DOC] |
| publishing | `uv publish` + **PyPI Trusted Publishing** (OIDC, no tokens) | `gem push`, rubygems trusted publishing | [DOC] ([trusted publishers](https://docs.pypi.org/trusted-publishers/)) |
| running on the user's machine | **`uvx <package>`** | `npx` / `gem exec` | isolated temporary environment [DOC] |

**Python version:** develop on 3.14, `requires-python = ">=3.12"`, CI matrix 3.12–3.14. FastMCP 4.2 requires ≥ 3.11; 3.10 is already EOL (2026-10-01); 3.15 was released 2026-10-09 and is still too fresh [DOC] ([devguide](https://devguide.python.org/versions/)).

**pyproject.toml** (≈ Gemfile + gemspec + .rubocop.yml in one file, a sketch):
```toml
[project]
name = "<name — open question #8>"
version = "0.1.0"
requires-python = ">=3.12"
readme = "README.md"            # becomes the PyPI page and the mcp-name source for the Registry
license = "MIT"
dependencies = ["fastmcp>=4.2.3,<4.3", "httpx2>=2.16,<3", "pydantic-settings>=2.16,<3"]

[project.scripts]
vinyl-mcp = "vinyl_mcp.server:main"   # ≈ bin/ in a gem; command name = package name → `uvx <pkg>` without --from

[dependency-groups]
dev = ["pytest>=9", "pytest-asyncio>=1.5", "ruff>=0.17", "mypy>=2.4"]

[build-system]
requires = ["uv_build>=0.13.9,<0.14"]
build-backend = "uv_build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```
- `uv.lock` is **not used** by a `uvx` install; dependencies are resolved from the package metadata. So the version bounds in `dependencies` matter [ASSUME, inference].

**Publishing:**
1. `uv build`, then publish to TestPyPI.
2. On PyPI, create a "pending trusted publisher" with the repo, the `release.yml` workflow and the `pypi` environment. A pending publisher **does not reserve the name**.
3. Pushing the `v0.1.0` tag triggers the workflow: `uv build` → `uv publish` with `id-token: write` [DOC] ([uv + GitHub](https://docs.astral.sh/uv/guides/integration/github/)).

**Connecting on the user's side:**
- Claude Code: `claude mcp add --env DISCOGS_TOKEN=... --transport stdio vinyl -- uvx <pkg>` [ASSUME: the command is assembled from documented forms and was not run; per the docs, one more option should sit between `--env` and the name] ([Claude Code MCP](https://code.claude.com/docs/en/mcp)).
- Claude Desktop: `claude_desktop_config.json` → `"command": "uvx"`. On macOS the GUI doesn't see the shell PATH, so specify the **absolute path to `uvx`** [DOC] ([FastMCP + Claude Desktop](https://gofastmcp.com/docs/integrations/claude-desktop.md)).

**MCP Registry:**
- As of 2026-11-20 still in **preview** (a banner on every page; `mcp-publisher` releases are 1.x, but that doesn't mean GA) [DOC] ([registry docs](https://modelcontextprotocol.io/registry/quickstart)).
- Steps:
  1. Publish the package to PyPI.
  2. Add `<!-- mcp-name: io.github.<user>/<name> -->` to the README.
  3. Create `server.json` (`registryType: "pypi"`, `runtimeHint: "uvx"`, description ≤ 100 characters, version is immutable).
  4. `mcp-publisher login github` → `mcp-publisher publish`.
- No `.mcpb` (Desktop Extensions) in the first version: Python bundling is fragile, and the CLI has had no releases since 2025-12-04 [DOC].

**Pitfalls for a Rails developer:**
1. **async.** Calling `foo()` without `await` returns a coroutine, not the result. Blocking code (`sqlite3`, `time.sleep`) inside `async def` freezes the whole server; wrap it in `asyncio.to_thread`.
2. **stdout.** `print()` in a stdio server breaks the protocol.
3. **Imports.** There is no Zeitwerk: everything is imported explicitly, and circular imports fail. The PyPI name `vinyl-mcp` and the module name `vinyl_mcp` differ.
4. **Types.** They are not checked at runtime, except in pydantic. Yet for FastMCP, argument annotations define the tool schema.
5. **Mutable defaults.** `def f(x=[])` is the classic mistake. Truthiness is different too: `0`, `""` and `[]` are falsy.
6. **Old code on the internet.** 2025 tutorials (`mcp.server.fastmcp`, FastMCP 2.x) are outdated.

---

## 3. Recommended architecture

> These are default recommendations. Items that depend on the owner's answers link to an open question (section 7). `vinyl-mcp` / `vinyl_mcp` here and in 2.9 is a placeholder working name until question #8 is decided.

**One server, three domains** (`discogs_*`, `notes_*`, `lastfm_*`) plus "insights" tools that connect them. The project's value is exactly in that connection, so three separate servers would break it.

```
<project>/
  pyproject.toml  uv.lock  .python-version  justfile  README.md  LICENSE  server.json
  src/vinyl_mcp/
    server.py          # mcp = FastMCP(..., instructions=...); tool registration; main()
    settings.py        # pydantic-settings: DISCOGS_TOKEN, DISCOGS_USER_AGENT, NOTES_DIR, LASTFM_*, DB_PATH
    clients/
      discogs.py       # async client on httpx2: auth, User-Agent, rate limiter, 401/404/429 → domain errors
      lastfm.py        # 3–4 GET methods, api_key
    tools/             # ≈ controllers: thin, just parameters → service → formatting
      discogs.py  notes.py  lastfm.py  insights.py
    formatting.py      # concise/detailed rendering, "Data provided by Discogs" attribution
    notes/store.py     # safe paths (NOTES_DIR root), frontmatter, search
    matching.py        # artist/album normalization for the Last.fm ↔ Discogs join
    cache.py           # in-memory TTL cache (minutes, within the ToS)
    db.py              # stage 2: sqlite3 + PRAGMA user_version migrations
    collector.py       # stage 2: CLI `vinyl-mcp collect` (≈ rake task)
  tests/
    conftest.py        # in-memory Client fixture, MockTransport
    fixtures/*.json    # anonymized Discogs/Last.fm responses
  evals/cases.yaml  evals/run.py
```

**Where each kind of data lives:**

| Data | Where | Why |
|---|---|---|
| Tokens (Discogs, Last.fm, GitHub OAuth) | env / `.env` (in `.gitignore`); on the server an `EnvironmentFile` with mode 600 | never in the repository, URLs or tool responses |
| Discogs catalog (CC0) | not stored; call the API with a short in-memory TTL cache | ToS: store no longer than necessary |
| Collection and wantlist | read from the API, kept in an in-memory TTL cache (minutes to hours) for local filtering; not written to disk (revisit per question #9) | Restricted Data |
| Record notes | markdown files in `NOTES_DIR` with `discogs_release_id`, `discogs_master_id` frontmatter (question #2) | user data, works without the server, Obsidian-compatible |
| Price watch targets (release_id, max_price, currency) | SQLite, stage 2A | this is **the owner's** data, not Discogs data |
| Last price check | SQLite: one row per release, overwritten, shown with a timestamp if no older than 6 h | stage 2A |
| Price history | SQLite `price_snapshot`, **only in branch 2B** | see open question #1 |
| FastMCP OAuth state (remote) | encrypted `client_storage` on disk | stage 3 |

**Call flow** (Rails analogy: tool ≈ action, client ≈ service/adapter, formatting ≈ view):
1. The tool validates parameters (pydantic/FastMCP).
2. Calls the Discogs client: limiter, cache, HTTP.
3. Maps errors to a `ToolError` with a hint.
4. Renders compact text with IDs and attribution.

---

## 4. Proposed tool list

Every Discogs response ends with a "Data provided by Discogs" line with a link [DOC, ToS]. Default `limit` values are small. Signatures are schematic.

**Stage 1 — MVP (read Discogs + read and write notes)**

| Tool | Signature | Returns | R/W |
|---|---|---|---|
| `discogs_search` | `(query, type="release", artist?, year?, format?, country?, catno?, barcode?, limit=10, page=1)` | list of `Title — Artist (year, label, format) [release_id, master_id]` and "page X of Y" | R |
| `discogs_get_release` | `(release_id, response_format="concise")` | card: label/catno, formats, tracklist, have/want, `master_id`; in `detailed` also identifiers (matrix, barcode), notes | R |
| `discogs_list_pressings` | `(master_id, format?, country?, year?, sort="released", limit=20, page=1)` | master versions: country, year, label, catno, format, `release_id` | R |
| `discogs_get_prices` | `(release_ids: list[int] ≤ 10, currency="EUR", include_suggestions=False)` | per release `lowest_price`, `num_for_sale`, and per-grade prices when the flag is set; request timestamp. If price suggestions are unavailable (seller settings not completed), this is stated explicitly | R |
| `discogs_list_collection` | `(query?, folder_id=0, sort="added", limit=20, page=1)` | collection items with IDs; `query` filters by artist/title | R |
| `discogs_list_wantlist` | `(query?, limit=20, page=1)` | wantlist items with notes and IDs | R |
| `discogs_collection_summary` | `()` | item count per folder and min/median/max value estimate from `/collection/value` | R |
| `notes_search` | `(query, release_id?, limit=10)` | list of notes: path, title, snippet, linked `release_id` | R |
| `notes_read` | `(path)` | note text (path only inside `NOTES_DIR`) | R |
| `notes_write_release_note` | `(release_id, text, mode="append")` | path of the created or appended note; on creation the frontmatter is filled from Discogs | W (`destructiveHint=False`) |

Plus the `notes://{path}` resource template and the `identify_pressing(description)` prompt ("help me identify my pressing from the matrix/runout").

**Cost in Discogs requests** (all calls share the 60/min budget) [DOC for the endpoints, calculation is ASSUME]:
- The collection and wantlist endpoints have **no server-side text filter**, only `sort`. So `query` in `discogs_list_collection` and `discogs_list_wantlist`, as well as `insights_*`, work like this: the tool fetches all pages once (100 items each; a 1,000-item collection = 10 requests), keeps them in an in-memory TTL cache (minutes to hours) and filters locally.
- `discogs_get_prices` costs 1 `/marketplace/stats` request per release plus 1 for `price_suggestions` if the flag is on. 10 releases with suggestions is 20 requests, a third of the per-minute budget. Hence the ≤ 10 limit.
- If the collection is large or a fast `query` is needed, the next step is a local SQLite cache of the collection with sync, as in hlights33 (question #9). But that is also storing Restricted Data, and its retention is limited by the ToS.

**Stage 1.5 — writing to Discogs (opt-in, question #7)**

| Tool | Signature | Returns | R/W |
|---|---|---|---|
| `discogs_wantlist_add` | `(release_id, notes?)` | confirmation and card | W (`idempotentHint=True`, `destructiveHint=False`) |
| `discogs_wantlist_remove` | `(release_id)` | confirmation | W (`destructiveHint=True`, `requiresUserInteraction`) |

**Stage 2A — price watch (less risky under the ToS [ASSUME: our interpretation of the ToS snapshot])**

| Tool | Signature | Returns | R/W |
|---|---|---|---|
| `watch_set_target` | `(release_id, max_price, currency="EUR")` | confirmation | W (local DB) |
| `watch_list` | `(only_hits=False)` | targets and the last check (price, `num_for_sale`, time); if the check is older than 6 h, the price is not shown and "needs a fresh check" is shown instead (or the tool makes a fresh request itself) | R |
| `watch_remove` | `(release_id)` | confirmation | W (destructive, local) |

The `vinyl-mcp collect` collector checks the targets' current prices every N hours and overwrites the "last check" row. No history.

**Stage 2B — price history (only if open question #1 is decided in its favor)**

| Tool | Signature | Returns | R/W |
|---|---|---|---|
| `discogs_price_history` | `(release_id, since="90d")` | series of `lowest_price`/`num_for_sale` snapshots by date and min/max for the period | R |
| `wantlist_price_changes` | `(since="7d", min_drop_pct=10)` | wantlist releases whose price dropped or that got new listings | R |

**Stage 2 — Last.fm and the link**

| Tool | Signature | Returns | R/W |
|---|---|---|---|
| `lastfm_top_albums` | `(period="1month", limit=20)` | albums with playcount | R |
| `lastfm_recent_tracks` | `(limit=20, since?)` | recent tracks, now playing | R |
| `insights_listening_vs_collection` | `(period="12month", mode="unplayed"\|"not_owned", limit=20)` | `unplayed`: records in the collection with no plays in the period; `not_owned`: frequently played albums not in the collection (marked "in wantlist" where applicable) | R |

That's 10 tools in the MVP and about 20 in the full set, within the recommended range. If the catalog grows, "thin" tools should be merged.

---

## 5. Risks and constraints

| Risk | Level | What to do |
|---|---|---|
| **Anonymous Discogs API shutdown on 2026-12-01** | high, in 11 days | token from day one; mock-based tests don't depend on the network |
| **Discogs ToS: storing prices** (6 h, "no longer than necessary", Restricted Data) | high for price history | branch 2A by default (less risky, but this is our interpretation [ASSUME]); for 2B, a written request to Discogs Support; never publish or commit the price database |
| **Discogs ToS: passing data to an LLM** ("transfer to third party") | medium, unclear | read forum thread 1189731; only the owner's own data, only on request |
| ToS: attribution and project name | medium | "Data provided by Discogs" in responses, disclaimer in the README, a name like "… for Discogs" (question #8) |
| Rate limit change for authenticated requests (forum, 2026-10) | medium | don't hardcode 60, read the headers, back off |
| Spotify Developer Policy (ingest into AI) | high if Spotify is built | we don't build it; use the official connector |
| Last.fm: non-commercial only, limit not published | low | ≤ 1–2 req/s, cache, credit Last.fm |
| **Remote security:** `/mcp` open by default (`auth=None`), GitHubProvider admits any account, Origin check disabled | high on deployment | `login` allowlist, `host_origin_protection`, HTTPS, no redirects, tokens only in env |
| Leaking the token or the personal collection via logs, fixtures, errors | medium | `SecretStr`, anonymized fixtures, `ToolError` text without secrets |
| Path traversal in notes | medium | strict check that the path is inside `NOTES_DIR`, plus FastMCP 4's built-in template protection |
| Fast-moving breaking changes in FastMCP/SDK | medium | narrow pin, `uv.lock`, read the changelog before upgrading |
| Static bearer unavailable in claude.ai | medium | OAuth via GitHubProvider; bearer only for Claude Code |
| Cost | low | 0 locally; VPS ~€5–6/mo or Fly ~$2.5/mo; a domain; evals via the Anthropic API cost cents per run [ASSUME] |
| price suggestions require seller settings | functional | explicit message in the tool (question #4) |

---

## 6. Roadmap

| Stage | Contents | Definition of done |
|---|---|---|
| **0. Skeleton (one evening)** | `uv init` (src layout), ruff, mypy, pytest, justfile, CI on GitHub Actions; `settings.py`; Discogs client with token, User-Agent and limiter | `just check` (ruff + mypy + pytest) is green locally and in CI; the client **always** sends the token, and a test checks it |
| **1. Weekend MVP** | the 10 stage 1 tools from section 4 (9 read + note writing), stdio, connected to Claude Desktop/Code via `uv run` | Claude Code and Desktop see the server; with a real token, "find UK pressings of Kind of Blue", "what jazz is in my wantlist", "how much is release X", "write a note about this record" work; responses ≤ ~5k tokens; Discogs attribution present; the token never reaches the logs; in-memory tests for every tool, for 404/429 and the `list_tools` contract; **the server works after 2026-12-01** (no anonymous calls) |
| **2. Storage and the link** | SQLite (`user_version` migrations), `vinyl-mcp collect` + timer (systemd/launchd, question #5); **branch 2A** (price watch) or **2B** (history, question #1); Last.fm client and `insights_*` | the collector runs on schedule for ≥ 7 days without manual intervention, a `collector_run` table exists, the rate limit is not exceeded (no 429s in the logs); `watch_list` or `price_history` answer from the DB; `insights_listening_vs_collection` gives a plausible result on the owner's collection |
| **3. Remote** | Streamable HTTP, `GitHubProvider` + `login` allowlist, `host_origin_protection`, hosting (question #5), HTTPS 443 without redirects | the connector is added in claude.ai; it works from a phone; a request from another GitHub account is refused; `curl` without a token gets 401; Anthropic's troubleshooting checklist passes |
| **4. Evals** | `evals/cases.yaml` (15–30 cases, 20% held out), selection-only script; description edits based on results | tool selection accuracy ≥ 90% on held-out; no write-tool calls unless asked; the tool catalog's `input_tokens` recorded as a baseline |
| **5. Publishing** | README (installation, Discogs disclaimer, Last.fm credit), LICENSE, TestPyPI → PyPI via Trusted Publishing, `server.json` + MCP Registry | `uvx <pkg>` starts the server on a clean machine; the package is on PyPI; the Registry entry is found via `curl registry.modelcontextprotocol.io/v0.1/servers?search=...`; the repository contains no secrets, no fixtures with personal data and no price data |

---

## 7. Open questions for the owner

1. **Price history and the Discogs ToS.** Options:
   - **(A)** price watch only, with the last check and no history (less risky, but this too should be confirmed with Discogs);
   - **(B)** write to Discogs Support and build history after getting permission;
   - **(C)** build history locally for personal use, accepting the risk, without publishing the data.

   Recommendation: A, with B in parallel.
2. **Notes.** Where do they live (an Obsidian vault? a separate folder?) and in what format (frontmatter, wikilinks)? Are tools for general notes needed, or are "record cards" enough, with general notes left to an existing filesystem or Obsidian server?
3. **Last.fm.** Is there an account, and do Spotify or other players scrobble to it? Without that, the "listening ↔ collection" link is empty.
4. **Discogs seller settings.** Are they completed? Without them `price_suggestions` doesn't work.
5. **Home hardware.** Is it a Mac (then launchd; systemd is Linux-only), a Raspberry Pi or a VPS? Is there an own domain (needed for Cloudflare Tunnel)?
6. **Claude plan**, and whether the "Request headers" section is visible in the Add custom connector dialog. This decides whether a bearer token can replace OAuth.
7. **Write tools.** Should the wantlist and collection be modifiable from Claude, or is read access plus notes enough?
8. **Project name and license.** The Discogs policy requires the "… for Discogs" format (2017 snapshot); `discogs-mcp` is free on PyPI but in a gray zone. MIT or Apache-2.0?
9. **Collection and wantlist size.** It determines the collector's run time, the request cost of `query`, and whether a local SQLite cache of the collection is needed (see section 4, "Cost in Discogs requests").
10. **Default currency** for prices (EUR? RUB is not supported by Discogs: the `curr_abbr` list is USD, GBP, EUR, CAD, AUD, JPY, CHF, MXN, BRL, NZD, SEK, ZAR [DOC]).

---

## 8. Check manually (could not be read automatically)

These pages are behind Cloudflare bot protection. Open them in a browser before stage 2:
1. **Current API Terms of Use**: https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use. We read the 2025-05-27 version via the 2026-05-30 snapshot; there is a recent forum thread "API Terms of Use" ([thread 1190765](https://www.discogs.com/forum/thread/1190765), ~2026-11-13).
2. Thread "AI LLMs and Discogs Access - Claude Blocked?": https://www.discogs.com/forum/thread/1189731.
3. Thread "Storing Discogs API data for a third-party app": https://www.discogs.com/forum/thread/1187739.
4. Thread "Authenticated requests limits behavior change": https://www.discogs.com/forum/thread/1188759.
5. Last.fm API key registration: https://www.last.fm/api/account/create.
6. Behavior of `price_suggestions`, `/oauth/identity`, the collection and the wantlist with a real token. No authenticated requests were made.
