"""Install, enable, disable, and remove mods.

The store holds the real files. The game folder holds only symlinks, so the game
directory is disposable and a failed operation cannot lose data.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from . import archive
from .model import Mod, State
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
        archive.extract(mod.source, destination, on_progress)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        mod.state = State.AVAILABLE
        raise

    # Trust the extracted names over the archive listing. 7z can rename an entry
    # when two files inside one archive flatten to the same name.
    mod.files = sorted(
        path.name
        for path in destination.iterdir()
        if path.is_file() and path.suffix.lower() in archive.MOD_SUFFIXES
    )
    if not mod.files:
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError("archive held no .pak, .ucas, or .utoc files")


def link(mod: Mod, mods_dir: Path, overwrite: bool = False) -> None:
    """Point the game at the store copy of each mod file."""
    mods_dir.mkdir(parents=True, exist_ok=True)
    source_dir = store_dir(mod)

    for name in mod.files:
        target = mods_dir / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            if not overwrite:
                raise LinkConflict(target)
            target.unlink()
        target.symlink_to(source_dir / name)

    mod.state = State.INSTALLED


def unlink(mod: Mod, mods_dir: Path) -> None:
    """Remove the game's links but keep the store copy."""
    for name in mod.files:
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
    if not store_dir(mod).is_dir() or not mod.files:
        extract_to_store(mod, on_progress)
    elif on_progress:
        on_progress(100)
    link(mod, mods_dir, overwrite)


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
    """Find links in the game folder that no known mod claims."""
    if not mods_dir.is_dir():
        return []
    claimed = {name for mod in mods for name in mod.files}
    return [
        path
        for path in sorted(mods_dir.iterdir())
        if path.name not in claimed and path.suffix.lower() in archive.MOD_SUFFIXES
    ]
