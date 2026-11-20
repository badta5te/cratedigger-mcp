"""Compact, human-readable text for Claude.

Every card carries the IDs for the next call and ends with the Discogs attribution.
"""

import re
from typing import Literal

from cratedigger_mcp.discogs import Artist, Format, Release, Track

ResponseFormat = Literal["concise", "detailed"]

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
        *(_track(track) for track in release.tracklist),
    ]
    if response_format == "detailed":
        lines += ["", *_identifiers(release), "", *_notes(release.notes)]
    lines += ["", attribution(release.uri or f"https://www.discogs.com/release/{release.id}")]
    return "\n".join(lines)


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
