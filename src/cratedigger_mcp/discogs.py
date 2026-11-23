"""The Discogs client: the only module that speaks HTTP to Discogs.

It authenticates every request with the Owner's token and the project User-Agent, paces
requests on the rate-limit headers Discogs returns, waits and retries when Discogs answers
HTTP 429, maps HTTP failures and unexpected responses to domain errors and returns typed models
instead of raw JSON.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cratedigger_mcp import __version__
from cratedigger_mcp.clock import Clock

API_URL = "https://api.discogs.com"
REPOSITORY_URL = "https://github.com/badta5te/cratedigger-mcp"
USER_AGENT = f"cratedigger-mcp/{__version__} +{REPOSITORY_URL}"
TIMEOUT_SECONDS = 30.0
# Discogs counts requests over a sliding window of this length. The limit itself is read from
# the X-Discogs-Ratelimit header, never assumed.
RATE_LIMIT_WINDOW_SECONDS = 60.0
# Pacing starts once the remaining quota drops to this share of the limit or below.
LOW_QUOTA_SHARE = 0.1
# Waits before each retry of a request Discogs rejected with HTTP 429. Bounded, so a tool call
# gives up within well under a minute instead of looping.
RETRY_DELAYS_SECONDS = (5.0, 10.0, 20.0)
# The largest page Discogs serves; used when every page of a list is fetched.
FULL_PAGE_SIZE = 100

logger = logging.getLogger(__name__)


class DiscogsError(Exception):
    """A Discogs request failed. The message is safe to show: it never carries the token."""


class NotFoundError(DiscogsError):
    """Discogs has no such resource (HTTP 404)."""


class UnauthorizedError(DiscogsError):
    """Discogs rejected the token (HTTP 401)."""


class RateLimitedError(DiscogsError):
    """Discogs kept answering HTTP 429 after every retry."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Artist(_Model):
    name: str
    anv: str = ""
    join: str = ""


class Label(_Model):
    name: str
    catno: str = ""


class Format(_Model):
    name: str
    qty: str = "1"
    descriptions: list[str] = Field(default_factory=list)
    text: str = ""


class Track(_Model):
    """A tracklist entry: a track, a heading such as "Side One", or an index track that groups
    the parts of a suite or medley in `sub_tracks`."""

    position: str = ""
    title: str = ""
    duration: str = ""
    type_: str = "track"
    sub_tracks: list["Track"] = Field(default_factory=list)


class Identifier(_Model):
    type: str
    value: str = ""
    description: str = ""


class Community(_Model):
    have: int = 0
    want: int = 0


class Release(_Model):
    id: int
    title: str
    artists: list[Artist] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    formats: list[Format] = Field(default_factory=list)
    country: str = ""
    year: int = 0
    master_id: int | None = None
    community: Community = Field(default_factory=Community)
    tracklist: list[Track] = Field(default_factory=list)
    identifiers: list[Identifier] = Field(default_factory=list)
    notes: str | None = None
    uri: str = ""


SearchType = Literal["release", "master", "artist", "label"]
# The orders Discogs can sort a Master's Releases in.
MasterReleaseSort = Literal["released", "title", "format", "label", "catno", "country"]
# The orders Copies of the Collection can be listed in.
CollectionSort = Literal["added", "artist", "title", "year"]
# The currencies Discogs reports Marketplace prices in.
Currency = Literal[
    "USD", "GBP", "EUR", "CAD", "AUD", "JPY", "CHF", "MXN", "BRL", "NZD", "SEK", "ZAR"
]
# Query-string parameters of a Discogs request, such as q, artist, year or page.
QueryParams = Mapping[str, str | int]


class SearchResult(_Model):
    """One catalog search hit. Artists and labels carry only an id and a title."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: int
    title: str = ""
    year: str = ""  # Discogs sends the year as a string
    country: str = ""
    format: list[str] = Field(default_factory=list)
    label: list[str] = Field(default_factory=list)
    catno: str = ""
    master_id: int | None = None


class Pagination(_Model):
    page: int
    pages: int
    per_page: int
    items: int


class SearchPage(_Model):
    pagination: Pagination
    results: list[SearchResult] = Field(default_factory=list)


class Master(_Model):
    id: int
    title: str
    artists: list[Artist] = Field(default_factory=list)
    year: int = 0
    uri: str = ""


class MasterRelease(_Model):
    """One Release in the list of a Master's Releases."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: int
    title: str = ""
    label: str = ""
    catno: str = ""
    country: str = ""
    released: str = ""  # usually the year alone, "0" when unknown
    major_formats: list[str] = Field(default_factory=list)
    format: str = ""  # the Format details, e.g. '7", 45 RPM, Single'


class MasterReleasesPage(_Model):
    pagination: Pagination
    versions: list[MasterRelease] = Field(default_factory=list)


class LowestPrice(_Model):
    value: float
    currency: str


class MarketplaceStats(_Model):
    """A Release's Marketplace summary. A Release blocked from sale has no counts at all."""

    num_for_sale: int | None = None
    lowest_price: LowestPrice | None = None
    blocked_from_sale: bool = False


@dataclass(frozen=True)
class MarketplaceCheck:
    """The Marketplace stats of one Release and when Discogs reported them."""

    release_id: int
    stats: MarketplaceStats
    checked_at: datetime


class Identity(_Model):
    username: str


class Folder(_Model):
    """A Collection folder. Folder 0 holds every Copy; folder 1 is Uncategorized."""

    id: int
    name: str
    count: int = 0


class CollectionFolders(_Model):
    folders: list[Folder] = Field(default_factory=list)


class CollectionField(_Model):
    """A field the Owner fills in for each Copy: by default the dropdowns Media Condition and
    Sleeve Condition; the Owner can add dropdowns and free-text fields of their own."""

    id: int
    name: str
    type: str = ""  # dropdown or textarea


class CollectionFields(_Model):
    fields: list[CollectionField] = Field(default_factory=list)


class CopyNote(_Model):
    """The value of one Collection field for one Copy."""

    field_id: int
    value: str = ""


class CollectionRelease(_Model):
    """The Release a Copy or a Want is of, as the Collection and the Wantlist list it."""

    id: int
    title: str = ""
    year: int = 0
    master_id: int = 0  # 0 when the Release is not grouped under a Master
    artists: list[Artist] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    formats: list[Format] = Field(default_factory=list)


class _Paged(_Model):
    pagination: Pagination


class Copy(_Model):
    instance_id: int
    folder_id: int
    date_added: datetime
    release: CollectionRelease = Field(alias="basic_information")
    notes: list[CopyNote] = Field(default_factory=list)


class CollectionPage(_Paged):
    releases: list[Copy] = Field(default_factory=list)


class Want(_Model):
    id: int  # the release_id
    date_added: datetime
    release: CollectionRelease = Field(alias="basic_information")


class WantlistPage(_Paged):
    wants: list[Want] = Field(default_factory=list)


class CollectionValue(_Model):
    """Discogs' estimate of what the Collection is worth: amounts as text with the currency
    sign, in the currency of the Owner's Discogs settings, e.g. "$1,204.50"."""

    minimum: str
    median: str
    maximum: str


@dataclass(frozen=True)
class Collection:
    """Every Copy in the Owner's Collection, newest first, its folders and its fields."""

    owner: str
    folders: list[Folder]
    fields: list[CollectionField]
    copies: list[Copy]

    def folder(self, folder_id: int) -> Folder | None:
        return next((folder for folder in self.folders if folder.id == folder_id), None)


@dataclass(frozen=True)
class CollectionSummary:
    owner: str
    folders: list[Folder]
    value: CollectionValue


@dataclass(frozen=True)
class Wantlist:
    """Every Want on the Owner's Wantlist, newest first."""

    owner: str
    wants: list[Want]


class _Pacer:
    """Slows requests down when the X-Discogs-Ratelimit-* headers report little quota left.

    With plenty of quota it never waits. Below the low mark it spreads the remaining requests
    over the window, waiting the whole window when none are left, so Discogs does not have to
    answer HTTP 429. Time spent idle counts towards the wait.

    Discogs counts `X-Discogs-Ratelimit-Remaining` before the request it answers, so the quota
    left after that request is one less.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._limit: int | None = None
        self._remaining: int | None = None
        self._last_request_at: datetime | None = None

    async def wait_turn(self) -> None:
        """Wait until the next request may go out, then count it against the quota."""
        async with self._lock:  # parallel tool calls take turns, each seeing the others
            delay = self._delay()
            if delay > 0:
                await self._clock.sleep(delay)
            self._last_request_at = self._clock.now()
            if self._remaining is not None:
                self._remaining = max(0, self._remaining - 1)

    def observe(self, response: httpx2.Response) -> None:
        """Learn the quota from a response."""
        if response.status_code == 429:
            # The retry backoff takes over; pacing on top would stack the waits.
            self._remaining = None
            return
        limit = _int_header(response, "X-Discogs-Ratelimit")
        remaining = _int_header(response, "X-Discogs-Ratelimit-Remaining")
        if limit is not None and remaining is not None:
            self._limit, self._remaining = limit, max(0, remaining - 1)

    def _delay(self) -> float:
        if self._limit is None or self._remaining is None or self._last_request_at is None:
            return 0.0
        if self._remaining > self._limit * LOW_QUOTA_SHARE:
            return 0.0
        interval = RATE_LIMIT_WINDOW_SECONDS / (self._remaining + 1)
        idle = (self._clock.now() - self._last_request_at).total_seconds()
        return max(0.0, interval - idle)


def _int_header(response: httpx2.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


def _full_page(page: int) -> dict[str, str | int]:
    """The query of one page of a list fetched whole, newest added first."""
    return {"per_page": FULL_PAGE_SIZE, "page": page, "sort": "added", "sort_order": "desc"}


def _same_start[E](pagination: Pagination, first_page: list[E], previous: list[E]) -> bool:
    """Whether a list still holds as many entries as `previous` and starts with the same ones."""
    return pagination.items == len(previous) and first_page == previous[: len(first_page)]


def _collection_path(owner: str) -> str:
    return f"/users/{quote(owner, safe='')}/collection"


def _wants_path(owner: str) -> str:
    return f"/users/{quote(owner, safe='')}/wants"


def build_http_client(
    token: str, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """An HTTP client preconfigured for Discogs. Tests pass a mock `transport`."""
    return httpx2.AsyncClient(
        base_url=API_URL,
        headers={
            "Authorization": f"Discogs token={token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        timeout=TIMEOUT_SECONDS,
        transport=transport,
    )


class DiscogsClient:
    """Use-case methods over the Discogs API."""

    def __init__(self, http: httpx2.AsyncClient, clock: Clock) -> None:
        self._http = http
        self._clock = clock
        self._pacer = _Pacer(clock)
        self._username: str | None = None
        self._username_lock = asyncio.Lock()

    async def get_release(self, release_id: int) -> Release:
        return await self._get(f"/releases/{release_id}", Release)

    async def search(
        self, search_type: SearchType, params: QueryParams, per_page: int, page: int
    ) -> SearchPage:
        """One page of catalog search results."""
        paged = {**params, "type": search_type, "per_page": per_page, "page": page}
        return await self._get("/database/search", SearchPage, paged)

    async def check_marketplace(self, release_id: int, currency: Currency) -> MarketplaceCheck:
        """The Lowest price and the number for sale of a Release, in `currency`."""
        stats = await self._get(
            f"/marketplace/stats/{release_id}", MarketplaceStats, {"curr_abbr": currency}
        )
        return MarketplaceCheck(release_id, stats, checked_at=self._clock.now())

    async def get_master(self, master_id: int) -> Master:
        return await self._get(f"/masters/{master_id}", Master)

    async def list_master_releases(
        self, master_id: int, params: QueryParams, per_page: int, page: int
    ) -> MasterReleasesPage:
        """One page of a Master's Releases, filtered and sorted by `params`.

        Discogs answers an unknown master_id here with every Release in its database instead of
        HTTP 404, so look the Master up with `get_master` first.
        """
        paged = {**params, "per_page": per_page, "page": page}
        return await self._get(f"/masters/{master_id}/versions", MasterReleasesPage, paged)

    async def owner_username(self) -> str:
        """The Owner's Discogs username, looked up from the token once per process."""
        async with self._username_lock:  # parallel tool calls share one lookup
            if self._username is None:
                identity = await self._get("/oauth/identity", Identity)
                self._username = identity.username
            return self._username

    async def get_collection(self, previous: Collection | None = None) -> Collection:
        """Every Copy in the Owner's Collection across all pages, newest first.

        When the folders with their counts, the total and the first page are the same as in
        `previous`, `previous` itself is returned and the fields and later pages are not
        fetched. Changes to older Copies that keep every folder's count, such as a new grade,
        go unseen until the snapshot is reloaded.
        """
        owner = await self.owner_username()
        base = _collection_path(owner)
        path = f"{base}/folders/0/releases"
        folders = await self._get(f"{base}/folders", CollectionFolders)
        first = await self._get(path, CollectionPage, _full_page(1))
        if (
            previous is not None
            and folders.folders == previous.folders
            and _same_start(first.pagination, first.releases, previous.copies)
        ):
            return previous
        fields = await self._get(f"{base}/fields", CollectionFields)
        copies = await self._every_page(path, CollectionPage, first, lambda found: found.releases)
        return Collection(owner, folders.folders, fields.fields, copies)

    async def get_wantlist(self, previous: Wantlist | None = None) -> Wantlist:
        """Every Want on the Owner's Wantlist across all pages, newest first.

        When the first page shows the same Wants and the same total as `previous`, nothing was
        added or removed: `previous` itself is returned and the later pages are not fetched.
        """
        owner = await self.owner_username()
        path = _wants_path(owner)
        first = await self._get(path, WantlistPage, _full_page(1))
        if previous is not None and _same_start(first.pagination, first.wants, previous.wants):
            return previous
        wants = await self._every_page(path, WantlistPage, first, lambda found: found.wants)
        return Wantlist(owner, wants)

    async def add_want(self, release_id: int) -> None:
        """Put a Release on the Owner's Wantlist."""
        owner = await self.owner_username()
        await self._call("PUT", f"{_wants_path(owner)}/{release_id}")

    async def remove_want(self, release_id: int) -> None:
        """Take a Want off the Owner's Wantlist. Discogs answers HTTP 404 when it is not there."""
        owner = await self.owner_username()
        await self._call("DELETE", f"{_wants_path(owner)}/{release_id}")

    async def get_collection_summary(self) -> CollectionSummary:
        """The Collection's folders with their counts and Discogs' estimate of its value."""
        owner = await self.owner_username()
        base = _collection_path(owner)
        folders = await self._get(f"{base}/folders", CollectionFolders)
        value = await self._get(f"{base}/value", CollectionValue)
        return CollectionSummary(owner, folders.folders, value)

    async def _every_page[P: _Paged, E](
        self, path: str, model: type[P], first: P, entries: Callable[[P], list[E]]
    ) -> list[E]:
        """The entries of `first` and of every later page of the list at `path`."""
        found = list(entries(first))
        for page in range(2, first.pagination.pages + 1):
            found += entries(await self._get(path, model, _full_page(page)))
        return found

    async def _get[M: BaseModel](
        self, path: str, model: type[M], params: QueryParams | None = None
    ) -> M:
        response = await self._call("GET", path, params)
        try:
            return model.model_validate_json(response.content)
        except ValidationError as error:  # not JSON, or not the shape the model expects
            logger.warning("Unexpected Discogs response for %s: %s", path, error)
            raise DiscogsError(
                f"Discogs sent an unexpected response for {path}. Try again later."
            ) from None

    async def _call(
        self, method: str, path: str, params: QueryParams | None = None
    ) -> httpx2.Response:
        """A successful response to the request, retried while Discogs answers HTTP 429."""
        response = await self._send(method, path, params)
        for delay in RETRY_DELAYS_SECONDS:
            if response.status_code != 429:
                break
            await self._clock.sleep(delay)
            response = await self._send(method, path, params)
        if response.status_code == 429:
            raise RateLimitedError(
                "Discogs is rate-limiting requests (HTTP 429). Try again in a minute."
            )
        if response.status_code == 401:
            raise UnauthorizedError("Discogs rejected the token (HTTP 401).")
        if response.status_code == 404:
            raise NotFoundError(f"Discogs has nothing at {path} (HTTP 404).")
        if response.is_error:
            raise DiscogsError(
                f"Discogs answered HTTP {response.status_code} for {path}. Try again later."
            )
        return response

    async def _send(self, method: str, path: str, params: QueryParams | None) -> httpx2.Response:
        await self._pacer.wait_turn()
        try:
            response = await self._http.request(method, path, params=params)
        except httpx2.RequestError as error:
            raise DiscogsError(
                f"Could not reach Discogs ({type(error).__name__}). Try again in a moment."
            ) from None
        self._pacer.observe(response)
        return response
