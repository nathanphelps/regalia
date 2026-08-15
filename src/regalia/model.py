"""The mod record and its states."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class State(StrEnum):
    AVAILABLE = "available"
    INSTALLED = "installed"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    BROKEN = "broken"


@dataclass(slots=True)
class NexusInfo:
    """What Nexus says about a mod.

    `verified` is True only when an MD5 match proved the identity. A mod id
    parsed out of a file name is a hint, not proof.
    """

    mod_id: int
    file_id: int | None = None
    mod_name: str = ""
    file_name: str = ""
    author: str = ""
    version: str | None = None
    adult: bool = False
    verified: bool = False
    latest_file_id: int | None = None
    latest_version: str | None = None

    @property
    def has_update(self) -> bool:
        return (
            self.latest_file_id is not None
            and self.file_id is not None
            and self.latest_file_id > self.file_id
        )

    def to_json(self) -> dict:
        return {
            "mod_id": self.mod_id,
            "file_id": self.file_id,
            "mod_name": self.mod_name,
            "file_name": self.file_name,
            "author": self.author,
            "version": self.version,
            "adult": self.adult,
            "verified": self.verified,
            "latest_file_id": self.latest_file_id,
            "latest_version": self.latest_version,
        }

    @classmethod
    def from_json(cls, data: dict) -> NexusInfo:
        return cls(
            mod_id=int(data["mod_id"]),
            file_id=data.get("file_id"),
            mod_name=data.get("mod_name", ""),
            file_name=data.get("file_name", ""),
            author=data.get("author", ""),
            version=data.get("version"),
            adult=bool(data.get("adult")),
            verified=bool(data.get("verified")),
            latest_file_id=data.get("latest_file_id"),
            latest_version=data.get("latest_version"),
        )


@dataclass(slots=True)
class Mod:
    slug: str
    hero: str
    variant: str
    version: str | None
    nexus_id: str | None
    source: Path
    size: int
    files: list[str] = field(default_factory=list)
    state: State = State.AVAILABLE
    has_load_order: bool = True
    note: str = ""
    nexus: NexusInfo | None = None
    md5: str | None = None
    # The collections this archive arrived with. This is a local fact, recorded
    # when the pack is installed, so it does not wait on a Nexus lookup.
    collections: list[str] = field(default_factory=list)
    custom_variant: str = ""
    variant_note: str = ""

    @property
    def title(self) -> str:
        variant = self.display_variant
        return f"{self.hero} — {variant}" if variant else self.hero

    @property
    def display_variant(self) -> str:
        return self.custom_variant or self.variant

    @property
    def verified(self) -> bool:
        return bool(self.nexus and self.nexus.verified)

    @property
    def author(self) -> str:
        return self.nexus.author if self.nexus else ""

    @property
    def version_label(self) -> str:
        return f"v{self.version}" if self.version else "—"

    @property
    def size_label(self) -> str:
        mb = self.size / 1_048_576
        return f"{mb:,.0f} MB" if mb >= 1 else f"{self.size / 1024:,.0f} KB"

    @property
    def files_label(self) -> str:
        """A compact description of the mod files.

        The three Unreal files share one stem, so the stem is printed once with
        the suffixes collected in braces.
        """
        if not self.files:
            return "(not inspected)"
        stems = {Path(name).stem for name in self.files}
        if len(stems) == 1:
            suffixes = ",".join(sorted(Path(n).suffix.lstrip(".") for n in self.files))
            return f"{stems.pop()}.{{{suffixes}}}"
        return ", ".join(self.files)

    @property
    def is_present(self) -> bool:
        """True once the files sit in the store, whether linked or not."""
        return self.state in (State.INSTALLED, State.DISABLED, State.BROKEN)

    @property
    def identity(self) -> str:
        """The key that groups different versions of one mod together."""
        return self.nexus_id or self.slug

    def to_json(self) -> dict:
        return {
            "slug": self.slug,
            "hero": self.hero,
            "variant": self.variant,
            "version": self.version,
            "nexus_id": self.nexus_id,
            "source": str(self.source),
            "size": self.size,
            "files": self.files,
            "state": str(self.state),
            "has_load_order": self.has_load_order,
            "note": self.note,
            "nexus": self.nexus.to_json() if self.nexus else None,
            "md5": self.md5,
            "collections": self.collections,
            "custom_variant": self.custom_variant,
            "variant_note": self.variant_note,
        }

    @classmethod
    def from_json(cls, data: dict) -> Mod:
        return cls(
            slug=data["slug"],
            hero=data["hero"],
            variant=data["variant"],
            version=data.get("version"),
            nexus_id=data.get("nexus_id"),
            source=Path(data["source"]),
            size=data.get("size", 0),
            files=list(data.get("files", [])),
            state=State(data.get("state", "available")),
            has_load_order=data.get("has_load_order", True),
            note=data.get("note", ""),
            nexus=NexusInfo.from_json(data["nexus"]) if data.get("nexus") else None,
            md5=data.get("md5"),
            collections=list(data.get("collections", [])),
            custom_variant=data.get("custom_variant", ""),
            variant_note=data.get("variant_note", ""),
        )
