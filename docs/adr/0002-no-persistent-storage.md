# No persistent storage of Discogs data

The server keeps Discogs data only in an in-memory cache (prices for one hour; Collection and Wantlist snapshots checked against Discogs on every call and reused for at most 5 minutes, see ADR-0003) and has no database: no price history, no price watch, no background collector. The Discogs API Terms of Use classify prices, Collection and Wantlist as Restricted Data that may not be stored "longer than necessary" or shown more than six hours old; the server runs locally over stdio with no always-on machine to host a collector; and Discogs' own Wantlister already sends price and condition filtered alerts for Wants.

## Considered Options

- **Price watch with a last-check row in SQLite** (research stage 2A): needs a scheduler and an always-on host, and duplicates Wantlister.
- **Price history** (research stage 2B): conflicts with the storage clause unless Discogs grants permission.
