"""Choosing Copies from the Collection snapshot: by text, by folder and in a sort order.

Discogs has no text filter for the Collection, so all of it happens locally over the snapshot,
and asking again with other choices costs no request.
"""

from cratedigger_mcp.discogs import Collection, CollectionSort, Copy
from cratedigger_mcp.formatting import artist_credit


def matches_query(query: str, copy: Copy) -> bool:
    """Whether every word of `query` occurs in the artist or title of `copy`, ignoring case.

    The artists count both as credited on the Release and under their own Discogs names.
    """
    release = copy.release
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
        if folder_id in (0, copy.folder_id) and matches_query(query, copy)
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


def _artist_and_title(copy: Copy) -> tuple[str, str]:
    return artist_credit(copy.release.artists).casefold(), copy.release.title.casefold()
