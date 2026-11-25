"""Choosing Copies from the Collection snapshot (by text, genre, folder and in a sort order)
and Wants from the Wantlist snapshot (by text and genre).

Discogs has no text filter for the Collection or the Wantlist, so all of it happens locally over
the snapshots, and asking again with other choices costs no request.
"""

import re

from runout_mcp.discogs import (
    Collection,
    CollectionRelease,
    CollectionSort,
    Copy,
    Want,
    Wantlist,
)
from runout_mcp.formatting import artist_credit

# Short names people use for a genre or style, as genre keys, with the key of the Discogs name.
GENRE_ALIASES = {"dnb": "drum and bass", "d and b": "drum and bass"}


def matches_query(query: str, release: CollectionRelease) -> bool:
    """Whether every word of `query` occurs in the artist or title of `release`, ignoring case.

    The artists count both as credited on the Release and under their own Discogs names.
    """
    names = [artist.name for artist in release.artists]
    haystack = " ".join([artist_credit(release.artists), *names, release.title]).casefold()
    return all(word in haystack for word in query.casefold().split())


def select_copies(
    collection: Collection, query: str, genre: str, folder_id: int, sort: CollectionSort
) -> list[Copy]:
    """The Copies whose artist or title match `query` and whose genres or styles match
    `genre`, in `folder_id` (0 for all), sorted."""
    chosen = [
        copy
        for copy in collection.copies
        if folder_id in (0, copy.folder_id)
        and matches_query(query, copy.release)
        and matches_genre(genre, copy.release)
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


def genre_key(name: str) -> str:
    """`name` as lower-case words, "&" and a lone "n" read as "and", so that "Drum n Bass",
    "drum & bass" and "Drum'n'Bass" agree; short names such as "dnb" stand for the Discogs
    name."""
    words = re.findall(r"[^\W_]+|&", name.casefold())
    key = " ".join("and" if word in ("&", "n") else word for word in words)
    return GENRE_ALIASES.get(key, key)


def matches_genre(genre: str, release: CollectionRelease) -> bool:
    """Whether `genre` names one of the genres or styles of `release`, or a part of one in
    whole words: "techno" matches "Hard Techno", "electro" does not match "Electronic".
    Written as one word, it matches the whole name: "synthpop" matches "Synth-pop". An empty
    `genre` matches every Release, one without letters or digits none."""
    if not genre.strip():
        return True
    key = genre_key(genre)
    names = [genre_key(name) for name in [*release.genres, *release.styles]]
    return bool(key) and any(
        f" {key} " in f" {name} " or key.replace(" ", "") == name.replace(" ", "") for name in names
    )


def select_wants(wantlist: Wantlist, query: str, genre: str) -> list[Want]:
    """The Wants whose artist or title match `query` and whose genres or styles match `genre`,
    newest first."""
    chosen = [
        want
        for want in wantlist.wants
        if matches_query(query, want.release) and matches_genre(genre, want.release)
    ]
    return sorted(chosen, key=lambda want: want.date_added, reverse=True)


def _artist_and_title(copy: Copy) -> tuple[str, str]:
    return artist_credit(copy.release.artists).casefold(), copy.release.title.casefold()
