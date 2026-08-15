"""Find the pak sets inside a mod, and work out which of them may run together.

One archive holds one or more components. Most hold exactly one, which is why
the naive "an archive is a pak" model survives so long; the ones that hold
twenty-four are the ones where getting it wrong ruins the deployment.

Two components may not run together when they write the same asset path. That
single rule replaces every heuristic about folder names, hero names and file
names, and it is derived rather than guessed — see `iostore`.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from . import archive, iostore
from .model import Component

# The order the pieces of a set are listed in, so a component always reports its
# files the same way.
SUFFIX_ORDER = {".pak": 0, ".utoc": 1, ".ucas": 2}


def from_entries(entries: Iterable[archive.Entry]) -> list[Component]:
    """Build components from an archive listing, before anything is extracted.

    Only names are known at this point. The assets stay empty until the files
    are on disk and the containers can be read.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for entry in archive.mod_files(list(entries)):
        path = PurePosix(entry.name)
        grouped.setdefault((path.folder, path.stem), []).append(path.name)
    return _build(grouped)


def discover(store: Path) -> list[Component]:
    """Find the pak sets in an extracted mod, and read what each one claims.

    The store keeps the folders the archive used, because those folders are the
    author's option tree. A store directory written by an older version is flat;
    it is found just the same, with every set sitting at the root.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    if not store.is_dir():
        return []
    for path in sorted(store.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in archive.MOD_SUFFIXES:
            continue
        folder = path.parent.relative_to(store).as_posix()
        grouped.setdefault(("" if folder == "." else folder, path.stem), []).append(
            path.name
        )

    components = _build(grouped)
    for component in components:
        _inspect(component, store)
    return components


def _build(grouped: dict[tuple[str, str], list[str]]) -> list[Component]:
    components = [
        Component(
            stem=stem,
            folder=folder,
            names=sorted(names, key=lambda n: SUFFIX_ORDER.get(Path(n).suffix, 9)),
        )
        for (folder, stem), names in grouped.items()
    ]
    return sorted(components, key=lambda item: (item.folder.lower(), item.stem.lower()))


def _inspect(component: Component, store: Path) -> None:
    """Read the component's container and record the assets it writes."""
    component.inspected = True
    for name in component.names:
        if not name.lower().endswith(".utoc"):
            continue
        container = iostore.read_or_none(store / component.folder / name)
        if container:
            component.assets = sorted(set(container.paths))
        return


# -- which components may run together -----------------------------------


def overlap(one: Component, other: Component) -> set[str]:
    """The asset paths both components write.

    Empty means they can run side by side. Two components that could not be read
    fall back to the folder hint, because siblings under one folder are almost
    always the author's alternatives and installing all of them is the failure
    this module exists to prevent. The result is marked a guess in `is_certain`.
    """
    if one is other:
        return set()
    if one.is_readable and other.is_readable:
        return set(one.assets) & set(other.assets)

    # Neither container could be read, so fall back to where they sat. Sharing a
    # folder means alternatives; so does sitting in sibling folders under one
    # parent, which is the shape a size ladder takes — "Default/L", "Default/M".
    # Comparing the folders whole would call those two unrelated and install
    # both, which is the failure this module exists to prevent.
    if one.folder and one.folder == other.folder:
        return {f"folder:{one.folder}"}
    if _parent(one.folder) and _parent(one.folder) == _parent(other.folder):
        return {f"folder:{_parent(one.folder)}"}
    return set()


def _parent(folder: str) -> str:
    head, _, _tail = folder.rpartition("/")
    return head


def is_certain(one: Component, other: Component) -> bool:
    """True when the answer came from the containers rather than a folder name."""
    return one.is_readable and other.is_readable


def clashes(component: Component, others: Iterable[Component]) -> list[Component]:
    """The components already enabled that this one would overwrite."""
    return [other for other in others if other.enabled and overlap(component, other)]


def groups(components: list[Component]) -> list[list[Component]]:
    """Split components into sets of alternatives, for presentation.

    Components are joined when they overlap, and joins are followed through:
    a size option that shares a mesh with the next size ends up in one group with
    all of them. Anything nothing overlaps stands alone, which is what an add-on
    like a physics container looks like.

    Presentation only. Enabling still decides by direct overlap, because a chain
    can link two components that do not actually collide with each other.
    """
    remaining = list(components)
    found: list[list[Component]] = []
    while remaining:
        group = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for candidate in list(remaining):
                if any(overlap(candidate, member) for member in group):
                    group.append(candidate)
                    remaining.remove(candidate)
                    changed = True
        found.append(group)
    return found


def enable(component: Component, components: list[Component]) -> list[Component]:
    """Turn one component on and turn off whatever it would overwrite.

    Returns the components that were switched off, so the caller can tell the
    user what changed rather than letting a choice quietly undo an earlier one.
    """
    displaced = clashes(component, components)
    for other in displaced:
        other.enabled = False
    component.enabled = True
    return displaced


def resolve(components: list[Component]) -> list[Component]:
    """Switch off enabled components that overwrite an earlier enabled one.

    Every path that inherits a selection has to run this. A selection made
    before the containers were readable is a guess from folder names, and a
    selection carried over from a catalog that predates components says
    everything is on. Either can name two components that write one asset, and
    only the assets can settle it.

    Returns what was switched off, so the caller can say so.
    """
    kept: list[Component] = []
    dropped: list[Component] = []
    for component in components:
        if not component.enabled:
            continue
        if clashes(component, kept):
            component.enabled = False
            dropped.append(component)
        else:
            kept.append(component)
    return dropped


def choose_default(components: list[Component]) -> None:
    """Pick a sensible starting selection for a freshly extracted mod.

    One component per group of alternatives plus every add-on. The first member
    of each group wins, which after sorting is the shallowest folder and then the
    first name — as close to "the plain one" as can be had without reading the
    author's mind. A mod with real choices is worth showing the user, and the
    interfaces do that; this only ensures installing never links two options that
    fight each other.
    """
    for group in groups(components):
        for index, component in enumerate(group):
            component.enabled = index == 0


class PurePosix:
    """Split an archive entry name without caring which slash it used."""

    __slots__ = ("folder", "name", "stem")

    def __init__(self, raw: str) -> None:
        cleaned = raw.replace("\\", "/").strip("/")
        head, _, tail = cleaned.rpartition("/")
        self.folder = head
        self.name = tail
        self.stem = tail.rsplit(".", 1)[0]
