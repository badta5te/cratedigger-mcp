"""Compact, human-readable text for Claude.

Every card carries the IDs for the next call and ends with the Discogs attribution.
"""

import math
import re
from collections import Counter
from datetime import UTC
from typing import Literal
from urllib.parse import quote, urlencode

from cratedigger_mcp.discogs import (
    Artist,
    Collection,
    CollectionField,
    CollectionRelease,
    CollectionSort,
    CollectionSummary,
    Copy,
    Currency,
    Folder,
    Format,
    MarketplaceCheck,
    Master,
    MasterRelease,
    MasterReleaseSort,
    MasterReleasesPage,
    QueryParams,
    Release,
    SearchPage,
    SearchResult,
    SearchType,
    Track,
    Want,
    Wantlist,
)
from cratedigger_mcp.matching import MATCH_RESULTS, AlbumMatch

ResponseFormat = Literal["concise", "detailed"]

# How each sort order of a Master's Releases reads in the heading.
MASTER_RELEASE_SORTS: dict[MasterReleaseSort, str] = {
    "released": "release date",
    "title": "title",
    "format": "Format",
    "label": "label",
    "catno": "catalog number",
    "country": "country",
}

# How each sort order of the Collection reads in the heading.
COLLECTION_SORTS: dict[CollectionSort, str] = {
    "added": "newest first",
    "artist": "sorted by artist",
    "title": "sorted by title",
    "year": "sorted by year, oldest first",
}

NOTES_LIMIT = 1500
# How many Releases a matched album lists before "and N more".
MATCHED_RELEASES_SHOWN = 3
_DISAMBIGUATION = re.compile(r" \(\d+\)$")
# A grade such as "Very Good Plus (VG+)" reads as its abbreviation.
_GRADE = re.compile(r"\(([^()]+)\)$")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def attribution(url: str) -> str:
    """The attribution the Discogs API Terms of Use require next to Discogs data."""
    return f"Data provided by Discogs: {url}"


def release_card(release: Release, response_format: ResponseFormat = "concise") -> str:
    lines = [
        f"{release.title} — {artist_credit(release.artists)} [release_id={release.id}]",
        f"Label: {_labels(release)}",
        f"Format: {_formats(release.formats)}",
        f"Country: {release.country or 'unknown'} · Year: {release.year or 'unknown'}",
        "Master: "
        + (
            f"master_id={release.master_id}"
            if release.master_id
            else "none (this Release is not grouped under a Master)"
        ),
        f"Discogs community: {release.community.have} have · {release.community.want} want",
        "",
        "Tracklist:",
        *_tracklist(release.tracklist),
    ]
    if response_format == "detailed":
        lines += ["", *_identifiers(release), "", *_notes(release.notes)]
    lines += ["", attribution(release.uri or f"https://www.discogs.com/release/{release.id}")]
    return "\n".join(lines)


def marketplace_prices(checks: list[MarketplaceCheck], currency: Currency) -> str:
    """The Lowest price of each Release, with what it means and when it was checked."""
    sell_url = (
        f"https://www.discogs.com/sell/release/{checks[0].release_id}"
        if len(checks) == 1
        else "https://www.discogs.com/sell/list"
    )
    return "\n".join(
        [
            f"Marketplace prices in {currency}. Lowest price: the cheapest current listing in "
            "any condition, excluding shipping; not a market value.",
            *(_marketplace_line(check) for check in checks),
            "",
            attribution(sell_url),
        ]
    )


def _marketplace_line(check: MarketplaceCheck) -> str:
    stats = check.stats
    if stats.blocked_from_sale:
        status = "blocked from sale on the Discogs Marketplace"
    elif stats.lowest_price is None or not stats.num_for_sale:
        status = "nothing for sale right now"
    else:
        price = stats.lowest_price
        status = f"Lowest price {price.value:.2f} {price.currency} · {stats.num_for_sale} for sale"
    checked = check.checked_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"release_id={check.release_id}: {status} · checked {checked}"


def search_results(
    found: SearchPage,
    search_type: SearchType,
    query: str,
    filters: QueryParams,
) -> str:
    """One page of catalog search results, numbered across pages, with a next-page hint."""
    pagination = found.pagination
    heading = _search_heading(search_type, query, filters)
    footer = ["", attribution(_search_url(search_type, query))]
    if pagination.items == 0:
        return "\n".join(
            [f"{heading}: nothing found. Try a broader query or fewer filters.", *footer]
        )
    first = (pagination.page - 1) * pagination.per_page + 1
    last = first + len(found.results) - 1
    hint = _showing(first, last, pagination.items, pagination.page, pagination.pages)
    lines = [
        f"{heading}: page {pagination.page} of {pagination.pages} ({pagination.items} results)",
        *(
            f"{number}. {_search_result(result, search_type)}"
            for number, result in enumerate(found.results, start=first)
        ),
        "",
        hint,
        *footer,
    ]
    return "\n".join(lines)


def master_releases(
    master: Master, found: MasterReleasesPage, filters: QueryParams, sort: MasterReleaseSort
) -> str:
    """One page of a Master's Releases, numbered across pages, with a next-page hint."""
    pagination = found.pagination
    footer = ["", attribution(master.uri or f"https://www.discogs.com/master/{master.id}")]
    master_label = (
        f"{master.title} — {artist_credit(master.artists)}"
        + (f" ({master.year})" if master.year else "")
        + f" [master_id={master.id}]"
    )
    filter_text = ", ".join(f"{key}={value}" for key, value in filters.items())
    if pagination.items == 0:
        if not filters:
            return "\n".join([f"Discogs lists no Releases of the Master {master_label}.", *footer])
        return "\n".join(
            [
                f"No Releases of the Master {master_label} match {filter_text}. Filter values "
                "are exact and case-sensitive, as Discogs writes them (Vinyl, CD, UK): check "
                "them or use fewer filters.",
                *footer,
            ]
        )
    if not found.versions:  # Discogs answers a page past the last one with no Releases
        return "\n".join(
            [
                f"No Releases on page {pagination.page}: the list has {pagination.pages} pages "
                f"of {pagination.per_page}. Use a lower page.",
                *footer,
            ]
        )
    heading = ", ".join(
        filter(
            None,
            [
                f"Releases of the Master {master_label}",
                filter_text,
                f"sorted by {MASTER_RELEASE_SORTS[sort]}",
            ],
        )
    )
    first = (pagination.page - 1) * pagination.per_page + 1
    last = first + len(found.versions) - 1
    hint = _showing(first, last, pagination.items, pagination.page, pagination.pages)
    hint += " Use discogs_get_release with a release_id for the full card."
    lines = [
        f"{heading}: page {pagination.page} of {pagination.pages} ({pagination.items} Releases)",
        *(
            f"{number}. {_master_release(release, master)}"
            for number, release in enumerate(found.versions, start=first)
        ),
        "",
        hint,
        *footer,
    ]
    return "\n".join(lines)


def collection_copies(
    collection: Collection,
    chosen: list[Copy],
    query: str,
    folder: Folder | None,
    sort: CollectionSort,
    limit: int,
    page: int,
) -> str:
    """One page of the chosen Copies, numbered across pages, with a next-page hint.

    `folder` is the folder browsed, None for the whole Collection.
    """
    footer = ["", attribution(collection_url(collection.owner))]
    criteria = [
        *([f'match "{query}"'] if query else []),
        *([f"in folder {_folder_label(folder)}"] if folder else []),
    ]
    if not chosen:
        if not criteria:
            return "\n".join([f"The Collection of {collection.owner} holds no Copies.", *footer])
        advice = " Try fewer words or another spelling." if query else ""
        nothing = f"No Copies in the Collection of {collection.owner} {' '.join(criteria)}."
        return "\n".join([nothing + advice, *footer])
    pages = math.ceil(len(chosen) / limit)
    if page > pages:
        return "\n".join(
            [
                f"No Copies on page {page}: the list has {pages} pages of {limit}. "
                "Use a lower page.",
                *footer,
            ]
        )
    heading = ", ".join(
        [
            f"Collection of {collection.owner}",
            *([f'Copies matching "{query}"'] if query else []),
            *([f"folder {_folder_label(folder)}"] if folder else []),
            COLLECTION_SORTS[sort],
        ]
    )
    copies_of = Counter(copy.release.id for copy in collection.copies)
    first = (page - 1) * limit + 1
    shown = chosen[first - 1 : first - 1 + limit]
    last = first + len(shown) - 1
    hint = _showing(first, last, len(chosen), page, pages)
    hint += " Use discogs_get_release with a release_id for the full card."
    lines = [
        f"{heading}: page {page} of {pages} ({_copies(len(chosen))})",
        *(
            f"{number}. "
            + _copy_line(
                copy,
                copies_of[copy.release.id],
                _folder_name(collection, copy.folder_id) if folder is None else None,
                _condition(copy, collection.fields),
            )
            for number, copy in enumerate(shown, start=first)
        ),
        "",
        hint,
        *footer,
    ]
    return "\n".join(lines)


def collection_summary(summary: CollectionSummary) -> str:
    """The number of Copies in each folder and Discogs' estimate of the Collection's value."""
    folders = [folder for folder in summary.folders if folder.id != 0]
    total = next(
        (folder.count for folder in summary.folders if folder.id == 0),
        sum(folder.count for folder in folders),
    )
    value = summary.value
    return "\n".join(
        [
            f"Collection of {summary.owner}: {_copies(total)}",
            "Folders:",
            *(
                f"  {folder.name}: {_copies(folder.count)} [folder_id={folder.id}]"
                for folder in folders
            ),
            f"Value estimated by Discogs: minimum {value.minimum} · median {value.median} · "
            f"maximum {value.maximum}",
            "",
            attribution(collection_url(summary.owner)),
        ]
    )


def wantlist_wants(
    wantlist: Wantlist, chosen: list[Want], query: str, limit: int, page: int
) -> str:
    """One page of the chosen Wants, numbered across pages, with a next-page hint."""
    footer = ["", attribution(wantlist_url(wantlist.owner))]
    if not chosen:
        if not query:
            return "\n".join([f"The Wantlist of {wantlist.owner} holds no Wants.", *footer])
        nothing = f'No Wants on the Wantlist of {wantlist.owner} match "{query}".'
        return "\n".join([nothing + " Try fewer words or another spelling.", *footer])
    pages = math.ceil(len(chosen) / limit)
    if page > pages:
        return "\n".join(
            [
                f"No Wants on page {page}: the list has {pages} pages of {limit}. "
                "Use a lower page.",
                *footer,
            ]
        )
    heading = ", ".join(
        [
            f"Wantlist of {wantlist.owner}",
            *([f'Wants matching "{query}"'] if query else []),
            "newest first",
        ]
    )
    first = (page - 1) * limit + 1
    shown = chosen[first - 1 : first - 1 + limit]
    last = first + len(shown) - 1
    hint = _showing(first, last, len(chosen), page, pages)
    hint += " Use discogs_get_release with a release_id for the full card."
    lines = [
        f"{heading}: page {page} of {pages} ({_wants(len(chosen))})",
        *(f"{number}. {_want_line(want)}" for number, want in enumerate(shown, start=first)),
        "",
        hint,
        *footer,
    ]
    return "\n".join(lines)


def album_matches(matches: list[AlbumMatch], collection: Collection, wantlist: Wantlist) -> str:
    """One line per album with its result and the Releases behind it."""
    results = Counter(found.result for found in matches)
    counts = ", ".join(f"{results[result]} {result}" for result in MATCH_RESULTS if results[result])
    albums = f"{len(matches)} album{'' if len(matches) == 1 else 's'}"
    lines = [
        f"Matched {albums} against the Collection of {collection.owner} "
        f"({_copies(len(collection.copies))}) and its Wantlist ({_wants(len(wantlist.wants))}): "
        f"{counts}.",
        *(f"{number}. {_album_match(found)}" for number, found in enumerate(matches, start=1)),
        "",
        "Use discogs_get_release with a release_id for the full card."
        + (
            " A possible match is a Release of the same artist with a longer or shorter title "
            "under another Master, such as an anniversary or expanded edition: ask the Owner "
            "or compare the cards."
            if results["possible"]
            else ""
        ),
        "",
        attribution(collection_url(collection.owner)),
    ]
    return "\n".join(lines)


def _album_match(found: AlbumMatch) -> str:
    album = f"{found.album.artist} — {found.album.title}: {found.result}"
    match found.result:
        case "in Collection":
            return f"{album}: {_matched_releases([copy.release for copy in found.copies])}"
        case "on Wantlist":
            return f"{album}: {_matched_releases([want.release for want in found.wants])}"
        case "possible":
            candidates = [
                *(_matched_release(copy.release, 1, "in Collection") for copy in found.copies),
                *(_matched_release(want.release, 1, "on Wantlist") for want in found.wants),
            ]
            return f"{album}: " + _first_few(list(dict.fromkeys(candidates)))
        case "absent":
            return album


def _matched_releases(releases: list[CollectionRelease]) -> str:
    """Each Release once, with the number of entries of it when there are several."""
    entries = Counter(release.id for release in releases)
    unique = {release.id: release for release in releases}.values()
    return _first_few([_matched_release(release, entries[release.id]) for release in unique])


def _matched_release(release: CollectionRelease, copies: int, where: str = "") -> str:
    details = [
        release.title,
        str(release.year) if release.year else "",
        _medium_names(release.formats),
        f"{copies} Copies" if copies > 1 else "",
        where,
    ]
    return " · ".join(filter(None, details)) + f" [release_id={release.id}]"


def _first_few(items: list[str]) -> str:
    shown = "; ".join(items[:MATCHED_RELEASES_SHOWN])
    more = len(items) - MATCHED_RELEASES_SHOWN
    return shown + (f"; and {more} more Release{'s' if more > 1 else ''}" if more > 0 else "")


def _medium_names(formats: list[Format]) -> str:
    """The Formats without their details, e.g. "2 × Vinyl + CD"."""
    names = [
        (f"{medium.qty} × " if medium.qty not in ("", "1") else "") + medium.name
        for medium in formats
    ]
    return " + ".join(names) or "unknown Format"


def wantlist_url(owner: str) -> str:
    return "https://www.discogs.com/wantlist?" + urlencode({"user": owner})


def collection_url(owner: str) -> str:
    return f"https://www.discogs.com/user/{quote(owner, safe='')}/collection"


def _copy_line(copy: Copy, copies_of_release: int, folder_name: str | None, condition: str) -> str:
    line = _listed_release_line(
        copy.release,
        f"added {copy.date_added:%Y-%m-%d}",
        f"folder {folder_name}" if folder_name else "",
        condition,
    )
    if copies_of_release > 1:
        line += f" · one of {copies_of_release} Copies of this Release"
    return line


def _want_line(want: Want) -> str:
    return _listed_release_line(want.release, f"added {want.date_added:%Y-%m-%d}")


def _listed_release_line(release: CollectionRelease, *extra: str) -> str:
    """Artist — title, year, Format, the first label and catalog number, then `extra`."""
    label = release.labels[0] if release.labels else None
    details = [
        f"{artist_credit(release.artists)} — {release.title}",
        str(release.year) if release.year else "",
        _formats(release.formats),
        " – ".join(filter(None, [label.name, label.catno])) if label else "",
        *extra,
    ]
    return " · ".join(filter(None, details)) + f" [release_id={release.id}]"


def _condition(copy: Copy, fields: list[CollectionField]) -> str:
    """The Copy's dropdown fields, such as its Media and Sleeve grades, in the Owner's order.

    Free-text fields are left out to keep the line short.
    """
    values = {note.field_id: note.value.strip() for note in copy.notes}
    shown = []
    for field in fields:
        value = values.get(field.id)
        if field.type == "dropdown" and value:
            grade = _GRADE.search(value)
            shown.append(f"{field.name} {grade.group(1) if grade else value}")
    return ", ".join(shown)


def _folder_name(collection: Collection, folder_id: int) -> str:
    found = collection.folder(folder_id)
    return found.name if found else f"folder_id={folder_id}"


def _folder_label(folder: Folder) -> str:
    return f"{folder.name} [folder_id={folder.id}]"


def _copies(count: int) -> str:
    return f"{count} Cop{'y' if count == 1 else 'ies'}"


def _wants(count: int) -> str:
    return f"{count} Want{'' if count == 1 else 's'}"


def _showing(first: int, last: int, total: int, page: int, pages: int) -> str:
    """Which numbers of how many the page shows, and how to get the next page."""
    hint = f"Showing {first}–{last} of {total}."
    return hint + (f" Use page={page + 1} for more." if page < pages else "")


def _master_release(release: MasterRelease, master: Master) -> str:
    title = release.title if release.title != master.title else ""
    year = release.released if release.released not in ("", "0") else ""
    label_catno = " – ".join(filter(None, [release.label, release.catno]))
    formats = ", ".join(filter(None, [*release.major_formats, release.format]))
    details = [title, year, release.country, label_catno, formats]
    return " ".join(filter(None, [" · ".join(filter(None, details)), f"[release_id={release.id}]"]))


def _search_heading(search_type: SearchType, query: str, filters: QueryParams) -> str:
    parts = [f'{search_type}s matching "{query}"' if query else f"{search_type}s"]
    parts += [f"{name}={value}" for name, value in filters.items()]
    return "Discogs search, " + ", ".join(parts)


def _search_result(result: SearchResult, search_type: SearchType) -> str:
    if search_type in ("artist", "label"):
        return f"{result.title} [{search_type}_id={result.id}]"
    formats = ", ".join(dict.fromkeys(result.format))
    # The first label is the Release's own; the rest are companies (distributors, plants).
    label = result.label[0] if result.label else ""
    if search_type == "master":
        details = [result.year, label, formats]
        ids = f"master_id={result.id}"
    else:
        label_catno = " – ".join(filter(None, [label, result.catno]))
        details = [result.year, result.country, label_catno, formats]
        ids = f"release_id={result.id}" + (
            f", master_id={result.master_id}" if result.master_id else ""
        )
    return " · ".join([result.title, *filter(None, details)]) + f" [{ids}]"


def _search_url(search_type: SearchType, query: str) -> str:
    return "https://www.discogs.com/search/?" + urlencode({"q": query, "type": search_type})


def artist_credit(artists: list[Artist]) -> str:
    credit = ""
    for artist in artists:
        credit += artist.anv or _DISAMBIGUATION.sub("", artist.name)
        if artist.join == ",":
            credit += ", "
        elif artist.join:
            credit += f" {artist.join} "
    return credit.strip() or "Unknown Artist"


def _labels(release: Release) -> str:
    labels = dict.fromkeys(f"{label.name} – {label.catno}" for label in release.labels)
    return "; ".join(labels) or "unknown"


def _formats(formats: list[Format]) -> str:
    rendered = []
    for medium in formats:
        parts = [medium.name, *medium.descriptions, *([medium.text] if medium.text else [])]
        quantity = f"{medium.qty} × " if medium.qty not in ("", "1") else ""
        rendered.append(quantity + ", ".join(parts))
    return " + ".join(rendered) or "unknown"


def _tracklist(tracks: list[Track]) -> list[str]:
    lines = []
    for track in tracks:
        if track.type_ == "heading":
            lines.append(f"{track.title}:")
            continue
        lines.append(_track(track))
        lines += [f"  {_track(part)}" for part in track.sub_tracks]
    return lines


def _track(track: Track) -> str:
    line = f"{track.position}  {track.title}" if track.position else track.title
    return f"{line} ({track.duration})" if track.duration else line


def _identifiers(release: Release) -> list[str]:
    if not release.identifiers:
        return ["Identifiers: none listed"]
    return [
        "Identifiers:",
        *(
            f"  {identifier.type}"
            f"{f' ({identifier.description})' if identifier.description else ''}"
            f": {identifier.value}"
            for identifier in release.identifiers
        ),
    ]


def _notes(notes: str | None) -> list[str]:
    text = _EXTRA_BLANK_LINES.sub("\n\n", (notes or "").strip())
    if not text:
        return ["Notes: none"]
    if len(text) > NOTES_LIMIT:
        text = text[:NOTES_LIMIT].rsplit(" ", 1)[0] + "… (notes shortened, full text on Discogs)"
    return ["Notes:", text]
