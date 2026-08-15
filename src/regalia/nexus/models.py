"""Records returned by the Nexus APIs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    total: int
    offset: int
    count: int

    @property
    def first(self) -> int:
        return self.offset + 1 if self.items else 0

    @property
    def last(self) -> int:
        return self.offset + len(self.items)

    @property
    def has_previous(self) -> bool:
        return self.offset > 0

    @property
    def has_next(self) -> bool:
        return self.last < self.total


@dataclass(frozen=True, slots=True)
class UserInfo:
    user_id: int
    name: str
    is_premium: bool
    is_supporter: bool

    @property
    def badge(self) -> str:
        if self.is_premium:
            return "★premium"
        return "supporter" if self.is_supporter else "free"


@dataclass(frozen=True, slots=True)
class NexusFile:
    file_id: int
    name: str
    version: str | None
    size: int
    category: str
    description: str = ""
    uploaded: int = 0

    @property
    def is_main(self) -> bool:
        return self.category in ("MAIN", "UPDATE")

    @property
    def is_current(self) -> bool:
        return self.category not in ("OLD_VERSION", "ARCHIVED")

    @property
    def size_label(self) -> str:
        mb = self.size / 1_048_576
        return f"{mb:,.0f} MB" if mb >= 1 else f"{self.size / 1024:,.0f} KB"


@dataclass(frozen=True, slots=True)
class NexusMod:
    mod_id: int
    name: str
    author: str
    version: str | None
    summary: str = ""
    adult: bool = False
    downloads: int = 0
    endorsements: int = 0
    updated_at: str = ""
    picture_url: str = ""
    thumbnail_url: str = ""
    category: str = ""

    @property
    def downloads_label(self) -> str:
        if self.downloads >= 1000:
            return f"{self.downloads / 1000:,.1f}k"
        return str(self.downloads)


@dataclass(frozen=True, slots=True)
class NexusImage:
    image_id: str
    url: str
    thumbnail_url: str
    title: str = ""
    caption: str = ""
    site_url: str = ""


@dataclass(frozen=True, slots=True)
class HashMatch:
    """One archive identified by its MD5."""

    md5: str
    file_name: str
    file_size: int
    mod_id: int
    file_id: int
    file_label: str
    file_version: str | None
    mod_name: str
    author: str
    adult: bool


@dataclass(frozen=True, slots=True)
class CollectionMod:
    mod_id: int
    file_id: int
    file_name: str
    file_version: str | None
    size: int
    mod_name: str
    author: str
    optional: bool
    update_policy: str

    @property
    def pinned(self) -> bool:
        """True when the manifest demands this exact file."""
        return self.update_policy == "exact"


@dataclass(slots=True)
class Collection:
    slug: str
    name: str
    summary: str
    author: str
    revision: int
    mod_count: int
    total_size: int
    adult: bool = False
    endorsements: int = 0
    installation_info: str = ""
    updated_at: str = ""
    downloads: int = 0
    unique_downloads: int = 0
    rating: str = ""
    rating_count: int = 0
    tile_url: str = ""
    header_url: str = ""
    mods: list[CollectionMod] = field(default_factory=list)

    @property
    def size_label(self) -> str:
        gb = self.total_size / 2**30
        if gb >= 1:
            return f"{gb:,.2f} GB"
        return f"{self.total_size / 2**20:,.0f} MB"

    @property
    def updated_label(self) -> str:
        """The update date alone. The time of day is noise in a list."""
        return self.updated_at[:10] if self.updated_at else "—"

    @property
    def downloads_label(self) -> str:
        if self.downloads >= 1000:
            return f"{self.downloads / 1000:,.1f}k"
        return str(self.downloads)

    @property
    def rating_label(self) -> str:
        """A percentage with the number of votes behind it.

        A high score from five voters is not the same as one from three
        thousand, so the count travels with the score.
        """
        if not self.rating or not self.rating_count:
            return "—"
        try:
            percent = round(float(self.rating))
        except ValueError:
            return "—"
        votes = (
            f"{self.rating_count / 1000:,.1f}k"
            if self.rating_count >= 1000
            else str(self.rating_count)
        )
        return f"{percent}% ·{votes}"

    @property
    def required(self) -> list[CollectionMod]:
        return [mod for mod in self.mods if not mod.optional]

    @property
    def optional(self) -> list[CollectionMod]:
        return [mod for mod in self.mods if mod.optional]
