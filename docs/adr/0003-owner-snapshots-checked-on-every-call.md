# The Collection and Wantlist snapshots are checked on every call

Discogs has no text filter for the Collection or the Wantlist, so the listing tools fetch every page and filter locally. ADR-0002 first kept these snapshots for 15 minutes without asking Discogs again. That made a Want or Copy added on the Discogs site or app invisible for up to 15 minutes: the Owner adds a Want and asks again, and sees the old list. A tool call is expected to show the current state.

We decided every call fetches the first page again, newest added first. If the total and that page are the same as in the snapshot, the later pages come from the snapshot. Otherwise the whole list is fetched again. For the Collection the folders and their counts are fetched and compared too. A snapshot is reused for at most 5 minutes from its full fetch, however often it is confirmed.

## Considered Options

- **A fixed time to live (15 minutes, or a shorter one).** No request on a repeated question, but a change on Discogs stays hidden until the time runs out.
- **No cache.** Always current, but every call costs one request per 100 entries, and Claude often calls a listing tool several times for one answer.
- **A `refresh` argument.** It depends on Claude guessing that the Owner changed something on Discogs.

## Consequences

- A repeated question costs one request for the Wantlist and two for the Collection, whatever their size. A Wantlist of up to 100 Wants is always fully current, and so are the Copies of a Collection of up to 100 Copies.
- An addition changes the first page and a removal changes the total, so both show at once. Wants added or removed through `discogs_wantlist_add` and `discogs_wantlist_remove` show the same way, and those tools also drop the Wantlist snapshot, so the next listing fetches the whole Wantlist again.
- Discogs' own Wantlist listing lags behind its writes. In a live check on 2026-11-22 a new Want appeared after about 8 seconds, and a removed one disappeared, reappeared and was gone for good after about 8 seconds. A listing right after a change can therefore still show the old Wantlist; the next call picks the change up. For the same reason the write tools never decide from the snapshot: they send the write and let Discogs answer, and a DELETE of a Release that is not wanted gets HTTP 404 at once.
- In a Collection of more than 100 Copies, a change to an older Copy that keeps every folder's count, such as a new grade or two Copies swapping folders, shows only after the 5-minute reload. The Collection fields themselves (a renamed or new custom field) are fetched only on a full reload, in a Collection of any size.
- `discogs_collection_summary` is not cached: it costs two requests and is always current.
