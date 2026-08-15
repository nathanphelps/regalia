"""The archives the tool owns, and how files get into them.

A download folder makes a poor library. The browser renames on collision, so
one re-download becomes "mod (1).zip" and the catalog gains a second record for
a mod it already had. The desktop offers to empty the folder. Other tools write
there too, so every unrelated archive lands in the scan. And because a mod is
keyed by its archive path, moving the file loses the record while the store and
the game links stay behind.

So the tool keeps its own directory and treats a download folder as a place to
import *from*, which is what a download folder actually is.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import archive
from .paths import LIBRARY_DIR


def ensure() -> Path:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return LIBRARY_DIR


def roots(scan_dirs: list[Path]) -> list[Path]:
    """Every directory a scan reads, the library first.

    The library always counts, whatever the configuration says, because a mod
    installed from it must not disappear when the user edits their watch list.
    """
    found = [LIBRARY_DIR]
    for path in scan_dirs:
        if path not in found:
            found.append(path)
    return found


def holds(path: Path) -> bool:
    """True when this archive already lives in the library."""
    try:
        return path.resolve().parent == LIBRARY_DIR.resolve()
    except OSError:
        return False


def destination_for(name: str) -> Path:
    """A free name in the library for an incoming archive.

    A repeat download of the same file keeps the same name, because the caller
    checks `exists` first. This only breaks a genuine clash between two
    different files that were given one name.
    """
    ensure()
    candidate = LIBRARY_DIR / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for number in range(2, 1000):
        candidate = LIBRARY_DIR / f"{stem} ({number}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"no free name in the library for {name}")


def import_archive(path: Path, move: bool = False) -> tuple[Path, str]:
    """Bring one archive into the library. Returns the path and what happened."""
    if holds(path):
        return path, "already in the library"

    existing = LIBRARY_DIR / path.name
    if existing.is_file() and existing.stat().st_size == path.stat().st_size:
        # Same name and same size is the same download. Copying it again would
        # make a second record for one mod.
        if move:
            path.unlink()
            return existing, "already held; removed the duplicate"
        return existing, "already held"

    target = destination_for(path.name)
    if move:
        try:
            path.rename(target)
        except OSError:
            # A move across filesystems is a copy and a delete.
            shutil.copy2(path, target)
            path.unlink()
        return target, "moved"
    shutil.copy2(path, target)
    return target, "copied"


def import_all(sources: list[Path], move: bool = False) -> list[str]:
    """Import every archive found in the given files or directories."""
    log: list[str] = []
    files: list[Path] = []
    for source in sources:
        if source.is_dir():
            files += archive.find_archives([source])
        elif source.is_file() and source.suffix.lower() in archive.ARCHIVE_SUFFIXES:
            files.append(source)
        else:
            log.append(f"skipped {source}: not an archive or a folder")

    for path in files:
        try:
            target, what = import_archive(path, move)
        except OSError as error:
            log.append(f"failed {path.name}: {error}")
            continue
        log.append(f"{what}: {target.name}")
    return log


def forget(path: Path) -> bool:
    """Delete an archive from the library. Returns whether it went.

    Only a file the library owns. An archive the user keeps in a watched folder
    of their own is theirs, and deleting it because they uninstalled a mod would
    be a surprise — uninstalling is about the game folder, not about their
    downloads.
    """
    if not holds(path):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def size() -> tuple[int, int]:
    """How many archives the library holds, and how many bytes."""
    if not LIBRARY_DIR.is_dir():
        return 0, 0
    found = archive.find_archives([LIBRARY_DIR])
    total = 0
    for path in found:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return len(found), total
