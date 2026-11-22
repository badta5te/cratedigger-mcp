"""Choosing Copies from the Collection snapshot (by text, by folder and in a sort order) and
Wants from the Wantlist snapshot (by text).

Discogs has no text filter for the Collection or the Wantlist, so all of it happens locally over
the snapshots, and asking again with other choices costs no request.
"""

from cratedigger_mcp.discogs import (
    Collection,
    CollectionRelease,
    CollectionSort,
    Copy,
    Want,
    Wantlist,
)
from cratedigger_mcp.formatting import artist_credit


def matches_query(query: str, release: CollectionRelease) -> bool:
    """Whether every word of `query` occurs in the artist or title of `release`, ignoring case.

    The artists count both as credited on the Release and under their own Discogs names.
    """
    names = [artist.name for artist in release.artists]
    haystack = " ".join([artist_credit(release.artists), *names, release.title]).casefold()
    return all(word in haystack for word in query.casefold().split())


def select_copies(
    collection: Collection, query: str, folder_id: int, sort: CollectionSort
) -> list[Copy]:
    """The Copies whose artist or title match `query`, in `folder_id` (0 for all), sorted."""
    chosen = [
        copy
        for copy in collection.copies
        if folder_id in (0, copy.folder_id) and matches_query(query, copy.release)
    ]
    match sort:
        case "added":
            return sorted(chosen, key=lambda copy: copy.date_added, reverse=True)
        case "year":  # oldest first, unknown years last
            return sorted(chosen, key=lambda copy: (copy.release.year == 0, copy.release.year))
        case "artist":
            return sorted(chosen, key=_artist_and_title)
        case "title":
            return sorted(chosen, key=lambda copy: _artist_and_title(copy)[::-1])


def select_wants(wantlist: Wantlist, query: str) -> list[Want]:
    """The Wants whose artist or title match `query`, newest first."""
    chosen = [want for want in wantlist.wants if matches_query(query, want.release)]
    return sorted(chosen, key=lambda want: want.date_added, reverse=True)


def _artist_and_title(copy: Copy) -> tuple[str, str]:
    return artist_credit(copy.release.artists).casefold(), copy.release.title.casefold()
