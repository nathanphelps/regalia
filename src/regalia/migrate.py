"""Carry an installation over from the old name, once.

The project was called rivalmods. A rename that changed only the code would
leave the catalog, the key and the extracted mods behind under the old
directories, and every symlink in the game folder would point into a store that
nothing writes to any more.

This runs on every start and does nothing after the first time.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import nxm
from .environment import xdg_cache_home, xdg_config_home, xdg_data_home
from .paths import CACHE_DIR, CONFIG_DIR, DATA_DIR, STORE_DIR

LEGACY_NAME = "rivalmods"
MARKER = DATA_DIR / ".migrated-from-rivalmods"

LEGACY_DESKTOP_FILES = ("rivalmods-nxm.desktop", "rivalmods.desktop")


def legacy_config() -> Path:
    return xdg_config_home() / LEGACY_NAME


def legacy_data() -> Path:
    return xdg_data_home() / LEGACY_NAME


def legacy_cache() -> Path:
    return xdg_cache_home() / LEGACY_NAME


def pending() -> bool:
    """True when an old installation is still waiting to be carried over."""
    if MARKER.is_file():
        return False
    return any(path.is_dir() for path in (legacy_config(), legacy_data()))


def move_directories() -> list[str]:
    """Rename the three base directories. Never merges into an existing one."""
    steps: list[str] = []
    pairs = (
        (legacy_config(), CONFIG_DIR),
        (legacy_data(), DATA_DIR),
        (legacy_cache(), CACHE_DIR),
    )
    for legacy, current in pairs:
        if not legacy.is_dir() or current.exists():
            continue
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(current)
        except OSError as error:
            steps.append(f"could not move {legacy}: {error}")
            continue
        steps.append(f"moved {legacy} to {current}")
    return steps


def relink_store(mods_dir: Path) -> list[str]:
    """Point the game's symlinks at the renamed store.

    The links hold an absolute path into the old store. Left alone they would
    all read as broken, and the user would have to repair every mod by hand.
    """
    steps: list[str] = []
    if not mods_dir.is_dir():
        return steps

    old_store = legacy_data() / "store"
    moved = 0
    failed = 0
    for link in sorted(mods_dir.iterdir()):
        if not link.is_symlink():
            continue
        target = Path(os.readlink(link))
        try:
            relative = target.relative_to(old_store)
        except ValueError:
            continue  # not one of ours, or already repointed
        try:
            link.unlink()
            link.symlink_to(STORE_DIR / relative)
            moved += 1
        except OSError:
            failed += 1

    if moved:
        steps.append(f"repointed {moved} symlink(s) at {STORE_DIR}")
    if failed:
        steps.append(f"{failed} symlink(s) could not be repointed; run Repair links")
    return steps


def clear_desktop_files() -> list[str]:
    """Remove the entries written under the old name, and re-register if ours."""
    steps: list[str] = []
    was_ours = nxm.registered_handler() in LEGACY_DESKTOP_FILES

    for name in LEGACY_DESKTOP_FILES:
        stale = nxm.DESKTOP_DIR / name
        if stale.is_file():
            stale.unlink()
            steps.append(f"removed {stale}")

    if was_ours:
        steps += nxm.register()
    return steps


def run(mods_dir: Path | None = None) -> list[str]:
    """Carry the installation over. Returns what changed, for the log."""
    if MARKER.is_file():
        return []
    if not pending():
        _mark()
        return []

    steps = move_directories()
    steps += clear_desktop_files()
    if mods_dir is not None:
        steps += relink_store(mods_dir)
        _mark()
    return steps


def _mark() -> None:
    try:
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text("Carried over from rivalmods.\n")
    except OSError:
        pass
