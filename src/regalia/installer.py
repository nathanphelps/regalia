"""Install, enable, disable, and remove mods.

The store holds the real files. The game folder holds only symlinks, so the game
directory is disposable and a failed operation cannot lose data.

The store keeps the folder tree the archive used. That tree is how the author
says "these are alternatives, that one is an add-on", and flattening it throws
the distinction away — along with, when two branches hold a file of the same
name, one of the files.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from . import archive, components
from .model import Component, Mod, State
from .paths import STORE_DIR

Progress = Callable[[int], None]


class LinkConflict(Exception):
    """A file that the tool did not create already occupies the target name."""

    def __init__(self, target: Path) -> None:
        super().__init__(f"{target.name} already exists and is not a link")
        self.target = target


def store_dir(mod: Mod) -> Path:
    return STORE_DIR / mod.slug


def extract_to_store(mod: Mod, on_progress: Progress | None = None) -> None:
    """Extract the archive into the store, replacing any partial attempt."""
    destination = store_dir(mod)
    if destination.exists():
        shutil.rmtree(destination)
    try:
        archive.extract_tree(mod.source, destination, on_progress)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        mod.state = State.AVAILABLE
        raise

    # Trust the extracted tree over the archive listing. 7z can rename an entry,
    # and only the files on disk say what the containers actually claim.
    found = components.discover(destination)
    if not found:
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError("archive held no .pak, .ucas, or .utoc files")

    _carry_choices(mod.components, found)
    mod.components = found


def _carry_choices(previous: list[Component], found: list[Component]) -> None:
    """Keep the user's selection across a re-extract, then fill the gaps.

    A component is matched by folder and stem, which survive a re-download of the
    same file. Anything unmatched falls back to the default selection so a
    changed archive never arrives with every option switched on.
    """
    remembered = {(item.folder, item.stem): item.enabled for item in previous}
    if not remembered:
        components.choose_default(found)
        return

    known = [item for item in found if (item.folder, item.stem) in remembered]
    for item in known:
        item.enabled = remembered[(item.folder, item.stem)]

    fresh = [item for item in found if (item.folder, item.stem) not in remembered]
    for item in fresh:
        # A new option arrives switched off unless nothing it collides with is
        # already running. Switching it on could silently replace the choice the
        # user made last time.
        item.enabled = not components.clashes(item, known)

    # The selection being carried in was made before this archive was
    # extracted, so it came from folder names rather than from the containers.
    # Now that the assets are readable it has to be narrowed, or a twelve-part
    # archive installs all twelve.
    components.resolve(found)


def link(mod: Mod, mods_dir: Path, overwrite: bool = False) -> None:
    """Point the game at the store copy of each enabled component."""
    mods_dir.mkdir(parents=True, exist_ok=True)
    source_dir = store_dir(mod)

    for component in mod.active:
        for name in component.names:
            target = mods_dir / name
            source = source_dir / component.folder / name
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                if not overwrite:
                    raise LinkConflict(target)
                target.unlink()
            target.symlink_to(source)

    mod.state = State.INSTALLED


def unlink(mod: Mod, mods_dir: Path) -> None:
    """Remove the game's links but keep the store copy.

    Every component is unlinked, not only the enabled ones, so a name left over
    from an earlier selection cannot outlive the mod that put it there.
    """
    for name in mod.all_files:
        target = mods_dir / name
        if target.is_symlink():
            target.unlink()
    mod.state = State.DISABLED


def install(
    mod: Mod,
    mods_dir: Path,
    on_progress: Progress | None = None,
    overwrite: bool = False,
) -> None:
    if not store_dir(mod).is_dir() or not mod.components:
        extract_to_store(mod, on_progress)
    elif on_progress:
        on_progress(100)
    link(mod, mods_dir, overwrite)


def apply_selection(mod: Mod, mods_dir: Path) -> None:
    """Make the game folder match the mod's current component selection.

    Called after the user turns a component on or off. Disabled components lose
    their links and enabled ones gain them; nothing is extracted again, because
    the store already holds every option.
    """
    if not mod.is_present:
        return
    active = {name for component in mod.active for name in component.names}
    for name in mod.all_files:
        target = mods_dir / name
        if name not in active and target.is_symlink():
            target.unlink()
    link(mod, mods_dir, overwrite=True)


def remove(mod: Mod, mods_dir: Path) -> None:
    """Remove the links and the store copy."""
    unlink(mod, mods_dir)
    shutil.rmtree(store_dir(mod), ignore_errors=True)
    mod.state = State.AVAILABLE


def repair(mods: list[Mod], mods_dir: Path) -> int:
    """Relink every mod whose links went missing, after a game update."""
    fixed = 0
    for mod in mods:
        if mod.state is State.BROKEN:
            link(mod, mods_dir, overwrite=True)
            fixed += 1
    return fixed


def orphan_links(mods_dir: Path, mods: list[Mod]) -> list[Path]:
    """Find links in the game folder that no known mod claims.

    A name a mod holds but has switched off still counts as claimed. Reporting
    it as an orphan would invite the user to delete a link the tool is about to
    remove itself.
    """
    if not mods_dir.is_dir():
        return []
    claimed = {name for mod in mods for name in mod.all_files}
    return [
        path
        for path in sorted(mods_dir.iterdir())
        if path.name not in claimed and path.suffix.lower() in archive.MOD_SUFFIXES
    ]
