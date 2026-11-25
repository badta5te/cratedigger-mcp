# The server is named Runout for Discogs

The project was first named "Cratedigger for Discogs" (`cratedigger-mcp`). Before the first release, reading Discogs' [Application Name and Description Policy](https://support.discogs.com/hc/en-us/articles/360009207054-Application-Name-and-Description-Policy) (effective 2019-12-11, read on 2026-11-25) showed that it lists "Crate Diggers" among the Discogs marks applications may not use, and forbids names that imitate or could be confused with Discogs' marks. We decided to rename the project to **Runout for Discogs**: the distribution and command are `runout-mcp`, the import package is `runout_mcp` and the repository is `badta5te/runout-mcp`.

The runout is the area by the label where the matrix/runout etchings are, which collectors read to tell Releases apart. The name keeps the policy's "<unique name> for Discogs" pattern, which it gives as acceptable, and resembles none of Discogs' marks.

## Considered Options

- **Keep "Cratedigger".** "Crate digging" is common collector slang, but the policy names "Crate Diggers" outright, and a later objection from Discogs would mean renaming a package already on PyPI and the MCP Registry.
- **Other vinyl terms.** "Shelfcheck", "Catno" and "Waxledger" were free on PyPI too; "Deadwax" was already taken as a bare name there. Runout was preferred as short, specific to identifying Releases and free on PyPI both bare and as `runout-mcp`.

## Consequences

- Nothing had been published under the old name, so the rename costs no migration: no PyPI project, MCP Registry entry, tag or trusted publisher existed yet.
- The tool names (`discogs_*`) are unchanged; they describe what each tool reaches, as the policy allows.
- Git history, closed issues and the raw research notes keep the old name.
