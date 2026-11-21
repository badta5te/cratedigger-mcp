"""Compact, human-readable text for Claude.

Every card carries the IDs for the next call and ends with the Discogs attribution.
"""

import re
from typing import Literal
from urllib.parse import urlencode

from cratedigger_mcp.discogs import (
    Artist,
    Format,
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
)

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

NOTES_LIMIT = 1500
_DISAMBIGUATION = re.compile(r" \(\d+\)$")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def attribution(url: str) -> str:
    """The attribution the Discogs API Terms of Use require next to Discogs data."""
    return f"Data provided by Discogs: {url}"


def release_card(release: Release, response_format: ResponseFormat = "concise") -> str:
    lines = [
        f"{release.title} — {_artist_credit(release.artists)} [release_id={release.id}]",
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
    hint = f"Showing {first}–{last} of {pagination.items}."
    if pagination.page < pagination.pages:
        hint += f" Use page={pagination.page + 1} for more."
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
        f"{master.title} — {_artist_credit(master.artists)}"
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
    hint = f"Showing {first}–{last} of {pagination.items}."
    if pagination.page < pagination.pages:
        hint += f" Use page={pagination.page + 1} for more."
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


def _artist_credit(artists: list[Artist]) -> str:
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
