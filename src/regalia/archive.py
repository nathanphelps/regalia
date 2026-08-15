"""List and extract mod archives.

Two backends do the work. The `7z` command is preferred, because it is faster on
the large packs mod collections produce. A pure-Python backend takes over when
`7z` is absent, so the tool needs no system package at all. That matters on
SteamOS and the immutable distributions, where layering p7zip is awkward and the
users least able to do it are the ones most likely to need the tool.

Set REGALIA_EXTRACTOR to "7z" or "python" to force one of them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

MOD_SUFFIXES = frozenset({".pak", ".ucas", ".utoc"})
ARCHIVE_SUFFIXES = frozenset({".7z", ".zip"})

PROGRESS = re.compile(r"(\d{1,3})%")
ENV_BACKEND = "REGALIA_EXTRACTOR"

Progress = Callable[[int], None]


class NoExtractor(Exception):
    """Nothing on this machine can open an archive."""


# The old name, kept so an out-of-tree caller does not break.
SevenZipMissing = NoExtractor


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    size: int
    is_dir: bool

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


# -- the 7z command ------------------------------------------------------


class SevenZipExtractor:
    """Drive the 7z command."""

    name = "7z"

    def __init__(self, command: str) -> None:
        self.command = command

    @property
    def detail(self) -> str:
        return self.command

    def list_entries(self, archive: Path) -> list[Entry]:
        result = subprocess.run(
            [self.command, "l", "-ba", "-slt", str(archive)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            return []
        return list(_parse_slt(result.stdout))

    def extract(
        self, archive: Path, destination: Path, on_progress: Progress | None
    ) -> None:
        process = subprocess.Popen(
            [self.command, "x", "-y", "-bsp1", f"-o{destination}", str(archive)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        tail: list[str] = []
        for chunk in iter(lambda: process.stdout.readline(), ""):
            tail.append(chunk)
            if on_progress and (match := PROGRESS.search(chunk)):
                on_progress(min(100, int(match.group(1))))
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"7z failed ({code}): {''.join(tail[-8:]).strip()}")


def _parse_slt(text: str) -> Iterator[Entry]:
    """Parse the "-slt" output, which is one key = value block per entry.

    The block format is used instead of the table because mod file names contain
    spaces and the table columns are not reliably aligned.
    """
    name: str | None = None
    size = 0
    is_dir = False
    for line in text.splitlines():
        if line.startswith("Path = "):
            if name is not None:
                yield Entry(name, size, is_dir)
            name, size, is_dir = line[7:], 0, False
        elif line.startswith("Size = ") and line[7:].strip().isdigit():
            size = int(line[7:])
        elif line.startswith("Attributes = "):
            # A zip written by a DOS-era tool carries no attribute bits, so 7z
            # prints the key and nothing else. No bits means no directory flag.
            attributes = line[13:].split()
            is_dir = bool(attributes) and "D" in attributes[0]
    if name is not None:
        yield Entry(name, size, is_dir)


# -- the pure-Python backend ---------------------------------------------


class PythonExtractor:
    """Open archives with py7zr and the standard library.

    Slower than the command on large packs, but it needs nothing installed.
    """

    name = "python"

    @property
    def detail(self) -> str:
        import py7zr

        return f"py7zr {py7zr.__version__}"

    def list_entries(self, archive: Path) -> list[Entry]:
        try:
            if archive.suffix.lower() == ".zip":
                return _zip_entries(archive)
            return _seven_zip_entries(archive)
        except Exception:
            # A damaged archive lists as empty, matching what the command does.
            return []

    def extract(
        self, archive: Path, destination: Path, on_progress: Progress | None
    ) -> None:
        if archive.suffix.lower() == ".zip":
            _extract_zip(archive, destination, on_progress)
        else:
            _extract_seven_zip(archive, destination, on_progress)


def _zip_entries(archive: Path) -> list[Entry]:
    with zipfile.ZipFile(archive) as handle:
        return [
            Entry(info.filename, info.file_size, info.is_dir())
            for info in handle.infolist()
        ]


def _seven_zip_entries(archive: Path) -> list[Entry]:
    import py7zr

    with py7zr.SevenZipFile(archive, "r") as handle:
        return [
            Entry(
                getattr(info, "filename", ""),
                int(getattr(info, "uncompressed", 0) or 0),
                bool(getattr(info, "is_directory", False)),
            )
            for info in handle.list()
        ]


def _extract_zip(
    archive: Path, destination: Path, on_progress: Progress | None
) -> None:
    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        total = max(sum(info.file_size for info in members), 1)
        done = 0
        for info in members:
            handle.extract(info, destination)
            done += info.file_size
            if on_progress:
                on_progress(min(99, int(done * 100 / total)))


def _extract_seven_zip(
    archive: Path, destination: Path, on_progress: Progress | None
) -> None:
    import py7zr
    from py7zr.callbacks import ExtractCallback

    class _Reporter(ExtractCallback):
        """Turn py7zr's per-file reports into one percentage."""

        def __init__(self, total: int) -> None:
            self.total = max(total, 1)
            self.done = 0

        def report_start_preparation(self) -> None:
            pass

        def report_start(self, processing_file_path, processing_bytes) -> None:
            pass

        def report_update(self, decompressed_bytes) -> None:
            pass

        def report_end(self, processing_file_path, wrote_bytes) -> None:
            try:
                self.done += int(wrote_bytes)
            except (TypeError, ValueError):
                return
            if on_progress:
                on_progress(min(99, int(self.done * 100 / self.total)))

        def report_postprocess(self) -> None:
            pass

        def report_warning(self, message) -> None:
            pass

    with py7zr.SevenZipFile(archive, "r") as handle:
        total = sum(
            int(getattr(info, "uncompressed", 0) or 0) for info in handle.list()
        )

    with py7zr.SevenZipFile(archive, "r") as handle:
        if on_progress:
            handle.extractall(path=destination, callback=_Reporter(total))
        else:
            handle.extractall(path=destination)


# -- choosing a backend --------------------------------------------------

_chosen: SevenZipExtractor | PythonExtractor | None = None


def seven_zip_command() -> str | None:
    return shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")


def _build_extractor() -> SevenZipExtractor | PythonExtractor:
    forced = os.environ.get(ENV_BACKEND, "").strip().lower()
    command = seven_zip_command()

    if forced == "python":
        return PythonExtractor()
    if forced == "7z":
        if not command:
            raise NoExtractor(f"{ENV_BACKEND}=7z, but no 7z command is on the path")
        return SevenZipExtractor(command)

    if command:
        return SevenZipExtractor(command)
    try:
        import py7zr  # noqa: F401
    except ImportError as error:
        raise NoExtractor(
            "No 7z command and no py7zr. Reinstall regalia, or install p7zip "
            "through your package manager."
        ) from error
    return PythonExtractor()


def require_extractor() -> SevenZipExtractor | PythonExtractor:
    """The backend this machine will use. Chosen once and remembered."""
    global _chosen
    if _chosen is None:
        _chosen = _build_extractor()
    return _chosen


def reset_extractor() -> None:
    """Forget the chosen backend. Used by the tests and after a settings change."""
    global _chosen
    _chosen = None


# -- the public surface --------------------------------------------------


def list_entries(archive: Path) -> list[Entry]:
    """List the files inside an archive."""
    return require_extractor().list_entries(archive)


def mod_files(entries: list[Entry]) -> list[Entry]:
    """Return only the Unreal mod files."""
    return [e for e in entries if not e.is_dir and e.suffix in MOD_SUFFIXES]


def looks_like_patch(entries: list[Entry]) -> bool:
    """True for the UTOC signature bypass archive.

    That archive carries a DLL and an ASI plugin instead of mod paks.
    """
    names = {Path(e.name).name.lower() for e in entries if not e.is_dir}
    return "dsound.dll" in names and any(n.endswith(".asi") for n in names)


def extract_tree(
    archive: Path,
    destination: Path,
    on_progress: Progress | None = None,
) -> None:
    """Extract into `destination`, keeping the folders the archive holds.

    The signature bypass needs this: its loader sits at the root and its plugins
    sit in a "plugins" folder, and flattening would put them side by side.
    """
    destination.mkdir(parents=True, exist_ok=True)
    require_extractor().extract(archive, destination, on_progress)
    if on_progress:
        on_progress(100)


def extract(
    archive: Path,
    destination: Path,
    on_progress: Progress | None = None,
) -> None:
    """Extract every file into `destination`, discarding any wrapper folder.

    Mod archives either put the files at the root or inside one folder named
    after the mod. Flattening removes that difference so the installer always
    sees the same layout.
    """
    destination.mkdir(parents=True, exist_ok=True)
    require_extractor().extract(archive, destination, on_progress)
    _flatten(destination)
    if on_progress:
        on_progress(100)


def _flatten(destination: Path) -> None:
    """Move files out of a single wrapper folder, then remove empty folders."""
    for path in list(destination.rglob("*")):
        if path.is_file() and path.parent != destination:
            target = destination / path.name
            if not target.exists():
                path.rename(target)
    for path in sorted(destination.rglob("*"), key=lambda p: -len(p.parts)):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass  # Not empty: an unexpected layout. Leave it in place.


def find_partials(directories: list[Path]) -> list[Path]:
    """Find abandoned downloads.

    A download in flight writes to a ".part" file and renames it on success, so
    anything still carrying that suffix is the remains of a run that stopped.
    The scanner ignores them, but they take real disk space.
    """
    found: list[Path] = []
    for directory in directories:
        if directory.is_dir():
            found += sorted(directory.glob("*.part"))
    return found


def clean_partials(directories: list[Path]) -> tuple[int, int]:
    """Delete abandoned downloads. Returns the count and the bytes recovered."""
    freed = 0
    removed = 0
    for path in find_partials(directories):
        try:
            freed += path.stat().st_size
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed, freed


def find_archives(directories: list[Path]) -> list[Path]:
    """Collect archive files from the configured scan directories."""
    found: list[Path] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in ARCHIVE_SUFFIXES:
                found.append(path)
    return found
