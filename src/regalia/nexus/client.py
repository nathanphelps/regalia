"""HTTP access to the two Nexus APIs.

The v2 GraphQL endpoint answers reads without a key and accepts batches. The v1
REST endpoint needs the key and mints download links. One class covers both so
that rate limiting and error handling stay in one place.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .. import __version__
from . import queries
from .models import (
    Collection,
    CollectionMod,
    HashMatch,
    NexusFile,
    NexusImage,
    NexusMod,
    Page,
    UserInfo,
)

GAME_DOMAIN = "marvelrivals"
GAME_ID = "7106"

V1_BASE = "https://api.nexusmods.com/v1"
V2_GRAPHQL = "https://api.nexusmods.com/v2/graphql"

USER_AGENT = f"regalia/{__version__} (Linux; x86_64)"
TIMEOUT = 30

# The official client uses these numbers. A burst of 500 is allowed and the
# allowance recovers one request per second.
BURST = 500
RECOVER_PER_SECOND = 1.0

HASH_CHUNK = 100


class NexusError(Exception):
    """Any Nexus failure."""


class NexusAuthError(NexusError):
    """The key is missing or rejected."""


class NexusPremiumRequired(NexusError):
    """A download link needs a Premium account."""


class NexusRateLimited(NexusError):
    def __init__(self, message: str, reset: str = "") -> None:
        super().__init__(message)
        self.reset = reset


class NexusOffline(NexusError):
    """The service could not be reached."""


@dataclass(slots=True)
class RateLimit:
    hourly_remaining: int | None = None
    hourly_limit: int | None = None
    daily_remaining: int | None = None
    daily_limit: int | None = None
    hourly_reset: str = ""

    @property
    def label(self) -> str:
        if self.hourly_remaining is None:
            return ""
        return f"{self.hourly_remaining}/{self.hourly_limit}"

    @property
    def exhausted(self) -> bool:
        return self.hourly_remaining is not None and self.hourly_remaining <= 0


class _Bucket:
    """A token bucket that limits bursts and recovers over time."""

    def __init__(self, capacity: int = BURST, rate: float = RECOVER_PER_SECOND) -> None:
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._rate = rate
        self._stamp = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity, self._tokens + (now - self._stamp) * self._rate
            )
            self._stamp = now
            if self._tokens < 1.0:
                delay = (1.0 - self._tokens) / self._rate
                time.sleep(delay)
                self._tokens = 0.0
                self._stamp = time.monotonic()
            else:
                self._tokens -= 1.0


class NexusClient:
    """Talks to both Nexus APIs.

    The key is optional. Without it every GraphQL read still works and only the
    v1 calls raise NexusAuthError.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self.rate = RateLimit()
        self._bucket = _Bucket()

    # -- transport ------------------------------------------------------

    def _open(self, request: urllib.request.Request) -> tuple[bytes, dict[str, str]]:
        self._bucket.take()
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:400]
            self._read_rate_limit(dict(error.headers))
            if error.code == 401:
                raise NexusAuthError("Nexus rejected the API key") from error
            if error.code == 403:
                raise NexusPremiumRequired(
                    "Nexus refused the download link. This needs Premium."
                ) from error
            if error.code == 429:
                raise NexusRateLimited(
                    "Nexus rate limit reached", self.rate.hourly_reset
                ) from error
            raise NexusError(f"Nexus returned {error.code}: {body}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise NexusOffline(f"Could not reach Nexus: {error}") from error

    def _read_rate_limit(self, headers: dict[str, str]) -> None:
        lowered = {key.lower(): value for key, value in headers.items()}

        def number(name: str) -> int | None:
            value = lowered.get(name)
            return int(value) if value and value.lstrip("-").isdigit() else None

        if (hourly := number("x-rl-hourly-remaining")) is not None:
            self.rate.hourly_remaining = hourly
        if (limit := number("x-rl-hourly-limit")) is not None:
            self.rate.hourly_limit = limit
        if (daily := number("x-rl-daily-remaining")) is not None:
            self.rate.daily_remaining = daily
        if (daily_limit := number("x-rl-daily-limit")) is not None:
            self.rate.daily_limit = daily_limit
        self.rate.hourly_reset = lowered.get(
            "x-rl-hourly-reset", self.rate.hourly_reset
        )

    # -- the two APIs ---------------------------------------------------

    @staticmethod
    def _decode(body: bytes) -> Any:
        """Read a JSON reply, or say what arrived instead.

        A 200 does not promise JSON. A hotel network, a corporate proxy or a
        Cloudflare interstitial all answer with an HTML page and a success code.
        Letting `json` raise there would escape every caller, because they guard
        against `NexusError` and a decode failure is not one — the interface
        would show a traceback instead of "could not reach Nexus".
        """
        try:
            return json.loads(body)
        except ValueError as error:
            head = body[:120].decode("utf-8", "replace").strip().replace("\n", " ")
            raise NexusError(
                f"Nexus did not answer with JSON. Something on the network may "
                f"be intercepting the connection. Got: {head!r}"
            ) from error

    def rest(self, path: str) -> Any:
        """Call the v1 REST API. This always needs the key."""
        if not self.api_key:
            raise NexusAuthError("No Nexus API key is set")
        request = urllib.request.Request(f"{V1_BASE}{path}")
        request.add_header("apikey", self.api_key)
        body, headers = self._open(request)
        self._read_rate_limit(headers)
        return self._decode(body)

    def graphql(self, document: str, variables: dict[str, Any] | None = None) -> Any:
        """Call the v2 GraphQL API. The key is sent when present but optional."""
        payload = json.dumps({"query": document, "variables": variables or {}}).encode()
        request = urllib.request.Request(V2_GRAPHQL, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("apikey", self.api_key)
        body, headers = self._open(request)
        # The v2 endpoint reports the same allowance as v1, and discarding these
        # meant a run that only searched showed a stale count.
        self._read_rate_limit(headers)
        data = self._decode(body)
        if errors := data.get("errors"):
            raise NexusError(errors[0].get("message", "GraphQL error"))
        return data.get("data") or {}

    # -- account --------------------------------------------------------

    def validate(self) -> UserInfo:
        data = self.rest("/users/validate.json")
        return UserInfo(
            user_id=int(data.get("user_id", 0)),
            name=data.get("name", "?"),
            is_premium=bool(data.get("is_premium")),
            is_supporter=bool(data.get("is_supporter")),
        )

    # -- identification -------------------------------------------------

    def identify(self, md5s: list[str]) -> dict[str, list[HashMatch]]:
        """Look up many hashes at once.

        One hash can belong to many mods. A helper file redistributed across
        dozens of mod pages is byte identical everywhere, so every page that
        carries it answers. The signature bypass patch returns 53 candidates.
        Every candidate is kept and `best_match` decides which one is meant.
        """
        found: dict[str, list[HashMatch]] = {}
        for start in range(0, len(md5s), HASH_CHUNK):
            chunk = md5s[start : start + HASH_CHUNK]
            data = self.graphql(queries.FILE_HASHES, {"md5s": chunk})
            for row in data.get("fileHashes") or []:
                mod_file = row.get("modFile") or {}
                mod = mod_file.get("mod") or {}
                if not mod_file.get("modId"):
                    continue
                found.setdefault(row["md5"], []).append(
                    HashMatch(
                        md5=row["md5"],
                        file_name=row.get("fileName") or "",
                        file_size=int(row.get("fileSize") or 0),
                        mod_id=int(mod_file["modId"]),
                        file_id=int(mod_file.get("fileId") or 0),
                        file_label=mod_file.get("name") or "",
                        file_version=mod_file.get("version"),
                        mod_name=mod.get("name") or "",
                        author=mod.get("author") or "",
                        adult=bool(mod.get("adultContent")),
                    )
                )
        return found

    # -- browsing -------------------------------------------------------

    def search(self, text: str, count: int = 40, offset: int = 0) -> list[NexusMod]:
        return self.search_page(text=text, count=count, offset=offset).items

    def search_page(
        self,
        text: str = "",
        *,
        author: str = "",
        category: str = "",
        count: int = 40,
        offset: int = 0,
    ) -> Page[NexusMod]:
        filters: list[str] = []
        declarations: list[str] = []
        variables: dict[str, Any] = {
            "game": GAME_DOMAIN,
            "count": count,
            "offset": offset,
        }
        if text:
            filters.append("nameStemmed: [{ value: $q, op: WILDCARD }]")
            declarations.append("$q: String!")
            variables["q"] = text
        if author:
            filters.append("author: [{ value: $author, op: WILDCARD }]")
            declarations.append("$author: String!")
            variables["author"] = author
        if category:
            filters.append("categoryName: [{ value: $category, op: WILDCARD }]")
            declarations.append("$category: String!")
            variables["category"] = category
        document = queries.SEARCH_MODS_ADVANCED % {
            "filters": "\n      ".join(filters),
            "sort": "relevance" if text else "downloads",
            "variables": (", " + ", ".join(declarations)) if declarations else "",
        }
        data = self.graphql(document, variables)
        page = data.get("mods") or {}
        return Page(
            items=[_mod(node) for node in page.get("nodes") or []],
            total=int(page.get("totalCount") or 0),
            offset=offset,
            count=count,
        )

    def browse(
        self, sort: str = "downloads", count: int = 40, offset: int = 0
    ) -> list[NexusMod]:
        """List mods by a sort field, such as downloads or createdAt."""
        return self.browse_page(sort, count, offset).items

    def browse_page(
        self, sort: str = "downloads", count: int = 40, offset: int = 0
    ) -> Page[NexusMod]:
        document = queries.BROWSE_MODS % {"sort": sort}
        data = self.graphql(
            document, {"game": GAME_DOMAIN, "count": count, "offset": offset}
        )
        page = data.get("mods") or {}
        return Page(
            items=[_mod(node) for node in page.get("nodes") or []],
            total=int(page.get("totalCount") or 0),
            offset=offset,
            count=count,
        )

    def mod(self, mod_id: int) -> NexusMod | None:
        """Fetch one mod by its id, for a detail view opened from the library."""
        data = self.graphql(
            queries.MOD_BY_ID, {"modId": str(mod_id), "gameId": GAME_ID}
        )
        node = data.get("mod")
        return _mod(node) if node else None

    def files(self, mod_id: int) -> list[NexusFile]:
        data = self.graphql(
            queries.MOD_FILES, {"modId": str(mod_id), "gameId": GAME_ID}
        )
        return [
            NexusFile(
                file_id=int(row["fileId"]),
                name=row.get("name") or "",
                version=row.get("version"),
                size=int(row.get("size") or 0) * 1024,  # the API reports kilobytes
                category=row.get("category") or "",
                description=row.get("description") or "",
                uploaded=int(row.get("date") or 0),
            )
            for row in data.get("modFiles") or []
        ]

    def images(self, mod: NexusMod, count: int = 24) -> list[NexusImage]:
        """Return the mod cover followed by relevant Nexus-hosted media."""
        images: list[NexusImage] = []
        if mod.picture_url:
            images.append(
                NexusImage(
                    image_id=f"mod-{mod.mod_id}",
                    url=mod.picture_url,
                    thumbnail_url=mod.thumbnail_url or mod.picture_url,
                    title=mod.name,
                )
            )
        data = self.graphql(
            queries.MOD_MEDIA,
            {"game": GAME_ID, "query": mod.name, "count": count},
        )
        seen = {image.url for image in images}
        for row in (data.get("media") or {}).get("nodes") or []:
            if row.get("__typename") not in ("Image", "SupporterImage"):
                continue
            url = row.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            images.append(
                NexusImage(
                    image_id=str(row.get("id") or url),
                    url=url,
                    thumbnail_url=row.get("thumbnailUrl") or url,
                    title=row.get("title") or "",
                    caption=row.get("caption") or "",
                    site_url=row.get("siteUrl") or "",
                )
            )
        return images

    def tracked(self) -> list[int]:
        """The mod ids you track, for this game only."""
        rows = self.rest("/user/tracked_mods.json")
        return [
            int(row["mod_id"])
            for row in rows
            if row.get("domain_name") == GAME_DOMAIN and row.get("mod_id")
        ]

    # -- updates --------------------------------------------------------

    def updated_since(self, period: str = "1m") -> dict[int, int]:
        """Every mod in the game that changed. Returns mod id to timestamp.

        One request covers the whole game, so the library is filtered locally
        rather than by asking about each mod in turn.
        """
        rows = self.rest(f"/games/{GAME_DOMAIN}/mods/updated.json?period={period}")
        return {
            int(row["mod_id"]): int(row.get("latest_file_update") or 0) for row in rows
        }

    # -- downloads ------------------------------------------------------

    def download_link(
        self,
        mod_id: int,
        file_id: int,
        key: str | None = None,
        expires: str | None = None,
    ) -> str:
        """Ask for a download URL.

        The key and expires pair comes from an nxm:// link. Sending them also
        works for a free account, so that path keeps working without Premium.
        """
        path = f"/games/{GAME_DOMAIN}/mods/{mod_id}/files/{file_id}/download_link.json"
        if key and expires:
            query = urllib.parse.urlencode({"key": key, "expires": expires})
            path = f"{path}?{query}"
        rows = self.rest(path)
        if not isinstance(rows, list) or not rows:
            raise NexusError("Nexus returned no download URL")
        return rows[0]["URI"]

    # -- collections ----------------------------------------------------

    def collections(
        self, sort: str = "endorsements", count: int = 40, offset: int = 0
    ) -> list[Collection]:
        return self.collections_page(sort, count, offset).items

    def collections_page(
        self,
        sort: str = "endorsements",
        count: int = 40,
        offset: int = 0,
        search: str = "",
    ) -> Page[Collection]:
        document = queries.LIST_COLLECTIONS % {
            "sort": sort,
            "variables": ", $q: String!" if search else "",
            "filters": (
                "generalSearch: [{ value: $q, op: WILDCARD }]" if search else ""
            ),
        }
        variables: dict[str, Any] = {
            "game": GAME_DOMAIN,
            "count": count,
            "offset": offset,
        }
        if search:
            variables["q"] = search
        data = self.graphql(document, variables)
        page = data.get("collectionsV2") or {}
        result: list[Collection] = []
        for node in page.get("nodes") or []:
            revision = node.get("currentRevision") or {}
            result.append(
                Collection(
                    slug=node["slug"],
                    name=node.get("name") or node["slug"],
                    summary=node.get("summary") or "",
                    author=(node.get("user") or {}).get("name") or "",
                    revision=int(revision.get("revisionNumber") or 0),
                    mod_count=int(revision.get("modCount") or 0),
                    total_size=int(revision.get("totalSize") or 0),
                    adult=bool(revision.get("adultContent")),
                    endorsements=int(node.get("endorsements") or 0),
                    updated_at=node.get("updatedAt") or "",
                    downloads=int(node.get("totalDownloads") or 0),
                    unique_downloads=int(node.get("uniqueDownloads") or 0),
                    rating=node.get("overallRating") or "",
                    rating_count=int(node.get("overallRatingCount") or 0),
                    tile_url=_collection_image(node.get("tileImage")),
                    header_url=_collection_image(node.get("headerImage")),
                )
            )
        return Page(result, int(page.get("totalCount") or 0), offset, count)

    def collection(self, slug: str) -> Collection:
        """Fetch a whole manifest. One request, however many mods it holds."""
        data = self.graphql(
            queries.COLLECTION_REVISION, {"slug": slug, "game": GAME_DOMAIN}
        )
        revision = data.get("collectionRevision")
        if not revision:
            raise NexusError(f"No collection named {slug}")

        parent = revision.get("collection") or {}
        mods: list[CollectionMod] = []
        for entry in revision.get("modFiles") or []:
            file = entry.get("file") or {}
            mod = file.get("mod") or {}
            if not file.get("modId"):
                continue
            mods.append(
                CollectionMod(
                    mod_id=int(file["modId"]),
                    file_id=int(file.get("fileId") or entry.get("fileId") or 0),
                    file_name=file.get("name") or "",
                    file_version=file.get("version"),
                    size=int(file.get("size") or 0) * 1024,
                    mod_name=mod.get("name") or "",
                    author=mod.get("author") or "",
                    optional=bool(entry.get("optional")),
                    update_policy=entry.get("updatePolicy") or "prefer",
                )
            )

        return Collection(
            slug=slug,
            name=parent.get("name") or slug,
            summary=parent.get("summary") or "",
            author=(parent.get("user") or {}).get("name") or "",
            revision=int(revision.get("revisionNumber") or 0),
            mod_count=int(revision.get("modCount") or len(mods)),
            total_size=int(revision.get("totalSize") or 0),
            adult=bool(revision.get("adultContent")),
            endorsements=int(parent.get("endorsements") or 0),
            installation_info=revision.get("installationInfo") or "",
            updated_at=parent.get("updatedAt") or "",
            downloads=int(parent.get("totalDownloads") or 0),
            unique_downloads=int(parent.get("uniqueDownloads") or 0),
            rating=parent.get("overallRating") or "",
            rating_count=int(parent.get("overallRatingCount") or 0),
            tile_url=_collection_image(parent.get("tileImage")),
            header_url=_collection_image(parent.get("headerImage")),
            mods=mods,
        )


def _collection_image(image: dict[str, Any] | None) -> str:
    image = image or {}
    return image.get("thumbnailUrl") or image.get("url") or ""


def _mod(node: dict[str, Any]) -> NexusMod:
    return NexusMod(
        mod_id=int(node["modId"]),
        name=node.get("name") or "",
        author=node.get("author") or "",
        version=node.get("version"),
        summary=node.get("summary") or "",
        adult=bool(node.get("adultContent")),
        downloads=int(node.get("downloads") or 0),
        endorsements=int(node.get("endorsements") or 0),
        updated_at=node.get("updatedAt") or "",
        picture_url=node.get("pictureUrl") or "",
        thumbnail_url=(node.get("thumbnailLargeUrl") or node.get("thumbnailUrl") or ""),
        category=node.get("category") or "",
    )
