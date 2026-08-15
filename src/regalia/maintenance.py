"""Undo what the tool has done, in pieces or all of it.

Anything that deletes has to answer two questions before it runs: exactly what
goes, and what the user loses that they cannot get back. The scopes here are
separate for that reason. Unlinking is free — the store can relink in a second.
Dropping the store costs an extraction. Dropping the library costs a download,
which for a large collection is the expensive one, so it is never included in a
sweep that the user did not name.

Nothing here touches the game's own files. The tool only ever added symlinks to
"~mods", and a link counts as ours only when it points into our own store.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import archive
from .paths import (
    CACHE_DIR,
    CATALOG_FILE,
    CONFIG_FILE,
    LIBRARY_DIR,
    STORE_DIR,
)

# The order a full sweep runs in. Links go before the store, so a failure part
# way through leaves the game folder clean rather than full of dead links.
SCOPES = ("links", "store", "catalog", "cache", "credentials", "config", "library")

DESTRUCTIVE = frozenset({"library"})

DESCRIPTIONS = {
    "links": "the symlinks in the game's ~mods folder",
    "store": "the extracted mod files",
    "catalog": "the mod list and the hash cache",
    "cache": "downloaded artwork",
    "credentials": "the saved Nexus API key",
    "config": "the settings file",
    "library": "the archives the tool imported (re-downloading is the only way back)",
}


@dataclass(slots=True)
class Item:
    """One thing a reset would remove."""

    scope: str
    path: Path
    bytes: int = 0
    is_link: bool = True


@dataclass(slots=True)
class Plan:
    """What a reset would do, before it does any of it."""

    items: list[Item] = field(default_factory=list)
    scopes: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def bytes(self) -> int:
        return sum(item.bytes for item in self.items)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def by_scope(self) -> dict[str, list[Item]]:
        grouped: dict[str, list[Item]] = {}
        for item in self.items:
            grouped.setdefault(item.scope, []).append(item)
        return grouped

    @property
    def touches_destructive(self) -> bool:
        return bool(set(self.scopes) & DESTRUCTIVE)


def owns_link(path: Path) -> bool:
    """Whether this symlink is one the tool made.

    The target decides it. A link pointing into our own store is ours whether or
    not the catalog still lists it, and that matters: a lost or cleared catalog
    would otherwise leave every link in the game folder unremovable, which is
    the one state a reset exists to get out of. `readlink` still answers for a
    broken link, so a link whose target has been deleted is still recognised.

    Anything else in "~mods" belongs to another tool or to the user, and
    removing it would be a surprise.
    """
    if not path.is_symlink():
        return False
    try:
        target = Path(os.readlink(path))
    except OSError:
        return False
    if not target.is_absolute():
        target = (path.parent / target).resolve(strict=False)
    return STORE_DIR in target.parents


def plan(scopes: list[str], mods_dir: Path | None, claimed: set[str]) -> Plan:
    """Work out what the named scopes would remove.

    `claimed` is every file name the catalog knows about. A link counts as ours
    when the catalog claims it or when it points into our store; the second test
    is what survives a catalog that has been cleared.
    """
    unknown = [scope for scope in scopes if scope not in SCOPES]
    if unknown:
        raise ValueError(f"unknown scope: {', '.join(unknown)}")

    found: list[Item] = []
    ordered = tuple(scope for scope in SCOPES if scope in scopes)

    if "links" in ordered and mods_dir and mods_dir.is_dir():
        for path in sorted(mods_dir.iterdir()):
            if path.is_symlink() and (path.name in claimed or owns_link(path)):
                found.append(Item("links", path, 0, True))

    if "store" in ordered:
        found += _directory_items("store", STORE_DIR)
    if "cache" in ordered:
        found += _directory_items("cache", CACHE_DIR)
    if "library" in ordered:
        for path in archive.find_archives([LIBRARY_DIR]):
            found.append(Item("library", path, _size(path), False))

    if "catalog" in ordered and CATALOG_FILE.is_file():
        found.append(Item("catalog", CATALOG_FILE, _size(CATALOG_FILE), False))
    if "config" in ordered and CONFIG_FILE.is_file():
        found.append(Item("config", CONFIG_FILE, _size(CONFIG_FILE), False))
    if "credentials" in ordered:
        from .credentials import CREDENTIALS_FILE

        if CREDENTIALS_FILE.is_file():
            found.append(Item("credentials", CREDENTIALS_FILE, 0, False))

    return Plan(found, ordered)


def run(plan: Plan) -> list[str]:
    """Carry out a plan. Reports one line per scope, and every failure."""
    log: list[str] = []
    grouped = plan.by_scope()

    for scope in plan.scopes:
        items = grouped.get(scope, [])
        if scope in ("store", "cache") and items:
            # These are whole trees. Removing the root once beats unlinking
            # every file, and leaves nothing behind when a file is unreadable.
            root = STORE_DIR if scope == "store" else CACHE_DIR
            try:
                shutil.rmtree(root)
                log.append(f"removed {scope}: {len(items)} item(s)")
            except OSError as error:
                log.append(f"could not remove {root}: {error}")
            continue

        removed = 0
        for item in items:
            try:
                item.path.unlink()
                removed += 1
            except OSError as error:
                log.append(f"could not remove {item.path}: {error}")
        if removed:
            log.append(f"removed {scope}: {removed} item(s)")

    return log


def _directory_items(scope: str, root: Path) -> list[Item]:
    if not root.is_dir():
        return []
    found: list[Item] = []
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            found.append(Item(scope, path, _size(path), path.is_symlink()))
    return found


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if not path.is_symlink() else 0
    except OSError:
        return 0


def human(count: int) -> str:
    """Bytes in the unit a person reads."""
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GB"
