"""The mod record and its states.

Three layers, deliberately named apart. An **archive** is the file the user
downloaded. A **component** is one pak set inside it — a ".pak" with its
".ucas" and ".utoc" — and it is the smallest thing the game can load and the
smallest thing the user can turn on. A `Mod` is the archive plus everything
known about it.

The distinction is not pedantry. One archive in a normal library holds
twenty-four components, of which the author expects two to run. Managers that
call all three layers "mod" end up installing all twenty-four, and the Nexus
Mods app rewrote its core model over exactly this ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .gameconfig import Setting


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
class Component:
    """One pak set: the ".pak", ".ucas" and ".utoc" that share a stem.

    `folder` is where the set sat inside the archive. It carries the author's
    intent — sibling folders are almost always alternatives — and it is the only
    grouping hint available for a container that cannot be read.

    `assets` is the truth. Two components collide when they write the same asset
    path, and nothing else about them decides it.
    """

    stem: str
    folder: str = ""
    names: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    enabled: bool = True
    inspected: bool = False

    @property
    def label(self) -> str:
        """What to call this component in a list the user reads."""
        return f"{self.folder}/{self.stem}" if self.folder else self.stem

    @property
    def sources(self) -> list[str]:
        """Store-relative paths of the real files."""
        return [f"{self.folder}/{name}" if self.folder else name for name in self.names]

    @property
    def is_readable(self) -> bool:
        """True when the container listed its assets.

        An unreadable component still installs. It only loses asset-level
        conflict checking, so the tool falls back to the folder hint and says
        that it is guessing.
        """
        return bool(self.assets)

    def to_json(self) -> dict:
        return {
            "stem": self.stem,
            "folder": self.folder,
            "names": self.names,
            "assets": self.assets,
            "enabled": self.enabled,
            "inspected": self.inspected,
        }

    @classmethod
    def from_json(cls, data: dict) -> Component:
        return cls(
            stem=data["stem"],
            folder=data.get("folder", ""),
            names=list(data.get("names", [])),
            assets=list(data.get("assets", [])),
            enabled=bool(data.get("enabled", True)),
            inspected=bool(data.get("inspected")),
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
    components: list[Component] = field(default_factory=list)
    # A config mod ships no pak. It changes the game by adding a few lines to
    # its settings, so it has settings where other mods have components.
    settings: list[Setting] = field(default_factory=list)
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
    def is_config(self) -> bool:
        """Whether this mod changes settings rather than shipping files."""
        return bool(self.settings) and not self.components

    @property
    def active(self) -> list[Component]:
        """The components the user chose to run."""
        return [component for component in self.components if component.enabled]

    @property
    def files(self) -> list[str]:
        """The names this mod claims in the game folder.

        Only the enabled components appear. A disabled component keeps its files
        in the store and takes no name, which is what lets ten body options live
        in one store directory while one of them is linked.
        """
        return sorted(name for item in self.active for name in item.names)

    @property
    def all_files(self) -> list[str]:
        """Every file the archive holds, enabled or not."""
        return sorted(name for item in self.components for name in item.names)

    @property
    def has_choices(self) -> bool:
        return len(self.components) > 1

    @property
    def files_label(self) -> str:
        """A compact description of what is installed.

        The three Unreal files share one stem, so the stem is printed once with
        the suffixes collected in braces. A mod with several components reports
        how many of them run instead, because listing sixty file names tells the
        reader nothing they can act on.
        """
        if self.is_config:
            count = len(self.settings)
            return f"{count} setting{'' if count == 1 else 's'}"
        if not self.components:
            return "(not inspected)"
        if self.has_choices:
            return f"{len(self.active)} of {len(self.components)} parts"
        names = self.components[0].names
        suffixes = ",".join(sorted(Path(n).suffix.lstrip(".") for n in names))
        return f"{self.components[0].stem}.{{{suffixes}}}"

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
            "components": [item.to_json() for item in self.components],
            "settings": [item.to_json() for item in self.settings],
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
            components=_components_from_json(data),
            settings=[Setting.from_json(item) for item in data.get("settings", [])],
            state=State(data.get("state", "available")),
            has_load_order=data.get("has_load_order", True),
            note=data.get("note", ""),
            nexus=NexusInfo.from_json(data["nexus"]) if data.get("nexus") else None,
            md5=data.get("md5"),
            collections=list(data.get("collections", [])),
            custom_variant=data.get("custom_variant", ""),
            variant_note=data.get("variant_note", ""),
        )


def _components_from_json(data: dict) -> list[Component]:
    """Read components, rebuilding them from a catalog written before they existed.

    A version 2 record held one flat list of file names and linked all of them.
    Grouping that list by stem recovers the components, and every one is marked
    enabled because that is what the old code did on disk. The next scan reads
    the containers and works out which of them actually belong together.
    """
    if "components" in data:
        return [Component.from_json(item) for item in data["components"]]

    grouped: dict[str, list[str]] = {}
    for name in data.get("files", []):
        grouped.setdefault(Path(name).stem, []).append(name)
    return [
        Component(stem=stem, names=sorted(names))
        for stem, names in sorted(grouped.items())
    ]
