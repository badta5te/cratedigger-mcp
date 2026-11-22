"""Matching albums from another source (Last.fm, Spotify, a pasted list) against the Owner's
Collection and Wantlist snapshots (ADR-0001).

Artists and titles are compared in a normalized form that ignores case, diacritics,
punctuation, a leading "The", "&" versus "and" and edition qualifiers such as "(Remastered)" or
"Deluxe Edition". An album is in the Collection when a Copy's Release has its normalized artist
and title, and then every Copy of that Release's Master counts as the same album, in any
Format. Releases without a Master match on artist and title alone. A Release of the same artist
whose title contains the album's title, or is contained in it, without being equal is only a
possible match: a reissue under a Master of its own, such as "OK Computer OKNOTOK 1997 2017",
or a live album. Titles that differ only by a series number, such as "Led Zeppelin" and
"Led Zeppelin III", are two albums.

Nothing here asks Discogs: matching works on the snapshots alone.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from cratedigger_mcp.discogs import Collection, CollectionRelease, Copy, Want, Wantlist

# Words that mark an edition rather than a different album. "remaster" counts as a stem.
_QUALIFIERS = frozenset(
    {"deluxe", "expanded", "anniversary", "legacy", "edition", "mono", "stereo", "bonus"}
)
# Words that go with a qualifier, as in "2011 Remaster" or "50th Anniversary Super Deluxe".
_FILLERS = frozenset(
    {"super", "special", "collector", "collectors", "limited", "version", "track", "tracks"}
    | {"digital", "original", "mix", "the", "and", "remix"}
)
# A year or an ordinal goes with a qualifier, as in "2011 Remaster" or "50th Anniversary";
# another number belongs to the title, as in "Chicago 17" or "Vol. 2 Deluxe".
_YEAR_OR_ORDINAL = re.compile(r"(19|20)\d\d|\d+(st|nd|rd|th)")
# Words that go with the number of an album in a series, as in "Vol. 2" or "Part III".
_SERIES = frozenset({"vol", "volume", "part", "pt"})
# Roman numerals up to XX.
_ROMAN = re.compile(r"x{0,2}(ix|iv|v?i{0,3})")
# How other sources credit a compilation that Discogs credits to "Various".
_VARIOUS = frozenset({"variousartists", "va"})
_BRACKETED = re.compile(r"[(\[{]([^()\[\]{}]*)[)\]}]")
_DISAMBIGUATION = re.compile(r" \(\d+\)$")
# Letters that Unicode does not decompose into a base letter and a mark.
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d"})
# The combining accents of the Latin, Greek and Cyrillic letters.
_COMBINING_ACCENT = re.compile("[\u0300-\u036f]")
# Marks dropped without a space, so that "R.E.M." reads as "rem" and "Don't" as "dont".
_JOINING = str.maketrans("", "", ".'\u2019\u02bc`")

MatchResult = Literal["in Collection", "on Wantlist", "possible", "absent"]
# The results from the strongest to the weakest.
MATCH_RESULTS: tuple[MatchResult, ...] = ("in Collection", "on Wantlist", "possible", "absent")


class Album(BaseModel):
    """An album as another source names it."""

    artist: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(description="The artist, e.g. 'The Beatles'."),
    ]
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(description="The album title, e.g. 'Abbey Road'."),
    ]


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
    artist = _artist_key(album.artist)
    title = _title_words(album.title)
    if not artist or not title:
        return AlbumMatch(album, "absent")
    same_titled = [*copies.same_album(artist, title), *wants.same_album(artist, title)]
    masters = {release.master_id for release in same_titled if release.master_id}
    release_ids = {release.id for release in same_titled}
    owned = copies.of_releases_or_masters(release_ids, masters)
    if owned:
        return AlbumMatch(album, "in Collection", copies=owned)
    wanted = wants.of_releases_or_masters(release_ids, masters)
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

    def of_releases_or_masters(self, release_ids: set[int], masters: set[int]) -> list[E]:
        """The entries of these Releases or of any Release of these Masters."""
        return [
            found.entry
            for found in self._all
            if found.release.id in release_ids or found.release.master_id in masters
        ]

    def similar(self, artist: str, title: tuple[str, ...]) -> list[E]:
        """The entries of this artist whose title contains `title` or is contained in it, unless
        the titles differ only by a series number."""
        return [
            found.entry for found in self._by_artist.get(artist, []) if _similar(found.title, title)
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
    return {key for name in names if (key := _artist_key(name))}


def _artist_key(name: str) -> str:
    key = _key(_words(name))
    return "various" if key in _VARIOUS else key


def _title_words(title: str) -> tuple[str, ...]:
    """The words of a title without its edition qualifiers or a leading "The"."""
    unbracketed = _BRACKETED.sub(
        lambda inner: " " if _qualifies(_words(inner.group(1))) else inner.group(0), title
    )
    words = _words(unbracketed) or _words(title)
    return _without_the(_without_trailing_qualifiers(words))


def _without_trailing_qualifiers(words: tuple[str, ...]) -> tuple[str, ...]:
    """`words` without trailing qualifiers such as "Remastered 2009" or "Deluxe Edition", unless
    only qualifiers would be left, as in an album called "Mono" or "Deluxe"."""
    end = len(words)
    while end > 1 and _qualifier_or_filler(words[end - 1]):
        end -= 1
    only_qualifiers = end == 1 and _qualifier_or_filler(words[0]) and not words[0].isdigit()
    if only_qualifiers or not _qualifies(words[end:]):
        return words
    return words[:end]


def _qualifies(words: Iterable[str]) -> bool:
    return any(word in _QUALIFIERS or word.startswith("remaster") for word in words)


def _qualifier_or_filler(word: str) -> bool:
    return (
        word in _QUALIFIERS
        or word in _FILLERS
        or word.startswith("remaster")
        or _YEAR_OR_ORDINAL.fullmatch(word) is not None
    )


def _without_the(words: tuple[str, ...]) -> tuple[str, ...]:
    return words[1:] if len(words) > 1 and words[0] == "the" else words


def _words(text: str) -> tuple[str, ...]:
    """The words of `text` in lower case, without diacritics or punctuation, "&" as "and".

    Only the Latin, Greek and Cyrillic accents go, so that kana keep their voicing marks. A
    name of symbols alone, such as "+" or "!!!", is one word of its symbols.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold().translate(_LETTERS))
    plain = unicodedata.normalize(
        "NFC", "".join(char for char in decomposed if not _COMBINING_ACCENT.match(char))
    )
    spaced = "".join(
        char if char.isalnum() else " " for char in plain.replace("&", " and ").translate(_JOINING)
    )
    symbols = "".join(text.casefold().split())
    return tuple(spaced.split()) or ((symbols,) if symbols else ())


def _key(words: tuple[str, ...]) -> str:
    """The form names are compared in: the words run together, so that "AC/DC" and "ACDC" or
    "Jay-Z" and "Jay Z" are the same."""
    return "".join(_without_the(words))


def _similar(one: tuple[str, ...], other: tuple[str, ...]) -> bool:
    """Whether one title occurs in the other as consecutive whole words, and the words left
    over are more than a series number: "OK Computer" and "OK Computer OKNOTOK 1997 2017" are
    similar, "Led Zeppelin" and "Led Zeppelin III" are two albums."""
    shorter, longer = sorted((one, other), key=len)
    if not shorter or len(shorter) == len(longer):
        return False
    for start in range(len(longer) - len(shorter) + 1):
        if longer[start : start + len(shorter)] == shorter:
            rest = longer[:start] + longer[start + len(shorter) :]
            return not _series_number(rest)
    return False


def _series_number(words: tuple[str, ...]) -> bool:
    """Whether `words` only number an album in a series, as in "III", "17" or "Vol. 2". A year
    is not a series number: it marks a reissue more often."""
    numbers = [word for word in words if word not in _SERIES]
    return bool(numbers) and all(
        _ROMAN.fullmatch(word) or (word.isdigit() and int(word) < 1900) for word in numbers
    )
