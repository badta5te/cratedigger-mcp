"""Matching albums from another source (Last.fm, Spotify, a pasted list) against the Owner's
Collection and Wantlist snapshots (ADR-0001).

Artists and titles are compared in a normalized form that ignores case, diacritics,
punctuation, a leading "The", "&" versus "and" and edition qualifiers such as "(Remastered)" or
"Deluxe Edition". An album is in the Collection when a Copy's Release has its normalized artist
and title, and then every Copy of that Release's Master counts as the same album, in any
Format. Releases without a Master match on artist and title alone. A Release of the same artist
whose title contains the album's title, or is contained in it, without being equal is only a
possible match: an anniversary or expanded edition under a Master of its own, for example.

Nothing here asks Discogs: matching works on the snapshots alone.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from cratedigger_mcp.discogs import Collection, CollectionRelease, Copy, Want, Wantlist

# Words that mark an edition rather than a different album. "remaster" counts as a stem.
_QUALIFIERS = frozenset(
    {"deluxe", "expanded", "anniversary", "legacy", "edition", "mono", "stereo"}
)
# Words that go with a qualifier, as in "2011 Remaster" or "50th Anniversary Super Deluxe".
_FILLERS = frozenset(
    {"super", "special", "collector", "collectors", "limited", "version", "bonus", "track"}
    | {"tracks", "digital", "original", "mix", "the", "and", "remix"}
)
_ORDINAL = re.compile(r"\d+(st|nd|rd|th)?")
_BRACKETED = re.compile(r"[(\[{]([^()\[\]{}]*)[)\]}]")
_DISAMBIGUATION = re.compile(r" \(\d+\)$")
# Letters that Unicode does not decompose into a base letter and a mark.
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d"})
# Marks dropped without a space, so that "R.E.M." reads as "rem" and "Don't" as "dont".
_JOINING = str.maketrans("", "", ".'\u2019\u02bc`")

MatchResult = Literal["in Collection", "on Wantlist", "possible", "absent"]
# The results from the strongest to the weakest.
MATCH_RESULTS: tuple[MatchResult, ...] = ("in Collection", "on Wantlist", "possible", "absent")


class Album(BaseModel):
    """An album as another source names it."""

    artist: Annotated[str, Field(description="The artist, e.g. 'The Beatles'.", min_length=1)]
    title: Annotated[str, Field(description="The album title, e.g. 'Abbey Road'.", min_length=1)]


@dataclass(frozen=True)
class AlbumMatch:
    """What the Owner has of one album: the matching Copies when it is in the Collection, the
    matching Wants when it is on the Wantlist, the similar Copies and Wants when it is
    possible."""

    album: Album
    result: MatchResult
    copies: list[Copy] = field(default_factory=list)
    wants: list[Want] = field(default_factory=list)


def match_albums(
    albums: Sequence[Album], collection: Collection, wantlist: Wantlist
) -> list[AlbumMatch]:
    """The result for each album, in the order given."""
    copies = _Index(collection.copies, lambda copy: copy.release)
    wants = _Index(wantlist.wants, lambda want: want.release)
    return [_match(album, copies, wants) for album in albums]


def _match(album: Album, copies: "_Index[Copy]", wants: "_Index[Want]") -> AlbumMatch:
    artist = _key(_words(album.artist))
    title = _title_words(album.title)
    if not artist or not title:
        return AlbumMatch(album, "absent")
    seeds = [*copies.same_album(artist, title), *wants.same_album(artist, title)]
    masters = {release.master_id for release in seeds if release.master_id}
    seed_ids = {release.id for release in seeds}
    owned = copies.of(seed_ids, masters)
    if owned:
        return AlbumMatch(album, "in Collection", copies=owned)
    wanted = wants.of(seed_ids, masters)
    if wanted:
        return AlbumMatch(album, "on Wantlist", wants=wanted)
    similar_copies = copies.similar(artist, title)
    similar_wants = wants.similar(artist, title)
    if similar_copies or similar_wants:
        return AlbumMatch(album, "possible", copies=similar_copies, wants=similar_wants)
    return AlbumMatch(album, "absent")


@dataclass(frozen=True)
class _Indexed[E]:
    entry: E
    release: CollectionRelease
    title: tuple[str, ...]


class _Index[E]:
    """The entries of a snapshot by normalized artist and by Master, in snapshot order."""

    def __init__(self, entries: Iterable[E], release_of: Callable[[E], CollectionRelease]) -> None:
        self._all: list[_Indexed[E]] = []
        self._by_artist: dict[str, list[_Indexed[E]]] = defaultdict(list)
        for entry in entries:
            release = release_of(entry)
            indexed = _Indexed(entry, release, _title_words(release.title))
            self._all.append(indexed)
            for artist in _artist_keys(release):
                self._by_artist[artist].append(indexed)

    def same_album(self, artist: str, title: tuple[str, ...]) -> list[CollectionRelease]:
        """The Releases with this normalized artist and title."""
        return [
            found.release
            for found in self._by_artist.get(artist, [])
            if _key(found.title) == _key(title)
        ]

    def of(self, release_ids: set[int], masters: set[int]) -> list[E]:
        """The entries of these Releases or of any Release of these Masters."""
        return [
            found.entry
            for found in self._all
            if found.release.id in release_ids or found.release.master_id in masters
        ]

    def similar(self, artist: str, title: tuple[str, ...]) -> list[E]:
        """The entries of this artist whose title contains `title` or is contained in it."""
        return [
            found.entry
            for found in self._by_artist.get(artist, [])
            if _contains(found.title, title) or _contains(title, found.title)
        ]


def _artist_keys(release: CollectionRelease) -> set[str]:
    """The normalized names a Release's artists go by: the whole credit, and each artist under
    their Discogs name and as credited."""
    credit = "".join(
        f"{artist.anv or _DISAMBIGUATION.sub('', artist.name)} {artist.join} "
        for artist in release.artists
    )
    names = [credit]
    for artist in release.artists:
        names += [_DISAMBIGUATION.sub("", artist.name), artist.anv]
    return {key for name in names if (key := _key(_words(name)))}


def _title_words(title: str) -> tuple[str, ...]:
    """The words of a title without its edition qualifiers or a leading "The"."""
    unbracketed = _BRACKETED.sub(
        lambda inner: " " if _qualifies(_words(inner.group(1))) else inner.group(0), title
    )
    words = _words(unbracketed) or _words(title)
    return _without_the(_without_trailing_qualifiers(words))


def _without_trailing_qualifiers(words: tuple[str, ...]) -> tuple[str, ...]:
    """`words` without trailing qualifiers such as "Remastered 2009" or "Deluxe Edition", unless
    nothing would be left."""
    end = len(words)
    while end > 1 and _qualifier_or_filler(words[end - 1]):
        end -= 1
    return words[:end] if _qualifies(words[end:]) else words


def _qualifies(words: Iterable[str]) -> bool:
    return any(word in _QUALIFIERS or word.startswith("remaster") for word in words)


def _qualifier_or_filler(word: str) -> bool:
    return (
        word in _QUALIFIERS
        or word in _FILLERS
        or word.startswith("remaster")
        or _ORDINAL.fullmatch(word) is not None
    )


def _without_the(words: tuple[str, ...]) -> tuple[str, ...]:
    return words[1:] if len(words) > 1 and words[0] == "the" else words


def _words(text: str) -> tuple[str, ...]:
    """The words of `text` in lower case, without diacritics or punctuation, "&" as "and"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().translate(_LETTERS))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    spaced = "".join(
        char if char.isalnum() else " " for char in plain.replace("&", " and ").translate(_JOINING)
    )
    return tuple(spaced.split())


def _key(words: tuple[str, ...]) -> str:
    """The form names are compared in: the words run together, so that "AC/DC" and "ACDC" or
    "Jay-Z" and "Jay Z" are the same."""
    return "".join(_without_the(words))


def _contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    """Whether `shorter` occurs as consecutive whole words in `longer` without being equal."""
    if not shorter or len(shorter) >= len(longer):
        return False
    return any(
        longer[start : start + len(shorter)] == shorter
        for start in range(len(longer) - len(shorter) + 1)
    )
