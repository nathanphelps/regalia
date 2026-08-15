"""Find the Marvel Rivals installation and the directories the tool writes to."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .environment import (
    SteamInstall,
    steam_installs,
    xdg_cache_home,
    xdg_config_home,
    xdg_data_home,
)

APP_ID = "2767030"

CONFIG_DIR = xdg_config_home() / "regalia"
DATA_DIR = xdg_data_home() / "regalia"
CACHE_DIR = xdg_cache_home() / "regalia"
STORE_DIR = DATA_DIR / "store"
# Archives the tool owns. A download folder is a terrible library: the browser
# renames on collision, the desktop offers to empty it, and the catalog keys a
# mod by its archive path, so a file that moves takes its record with it and
# leaves an installed mod with no entry.
LIBRARY_DIR = DATA_DIR / "library"
CATALOG_FILE = DATA_DIR / "catalog.json"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def image_cache_dir() -> Path:
    """Where downloaded artwork lives.

    Artwork is cache: a cleaner may delete it and the tool fetches it again. It
    used to sit beside the catalog, which meant a backup of the data directory
    carried hundreds of megabytes of thumbnails. The old folder is moved once.
    """
    target = CACHE_DIR / "images"
    legacy = DATA_DIR / "images"
    if legacy.is_dir() and not target.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(target)
        except OSError:
            return legacy  # a cross-device move failed; keep what works
    return target


class GameNotFound(Exception):
    """The tool could not locate a registered Marvel Rivals installation."""


@dataclass(frozen=True, slots=True)
class GamePaths:
    root: Path
    install: SteamInstall | None = None

    @property
    def paks(self) -> Path:
        return self.root / "MarvelGame/Marvel/Content/Paks"

    @property
    def mods(self) -> Path:
        return self.paks / "~mods"

    @property
    def binaries(self) -> Path:
        return self.root / "MarvelGame/Marvel/Binaries/Win64"

    @property
    def prefix(self) -> Path:
        return self.root.parent.parent / "compatdata" / APP_ID

    def is_valid(self) -> bool:
        return self.paks.is_dir()


def _library_paths(install: SteamInstall) -> list[Path]:
    """Read the library folders that this Steam knows about, in file order."""
    vdf = install.libraries_file
    if not vdf.is_file():
        return []

    text = read_vdf(vdf)
    libraries: list[Path] = []
    # Each block holds one "path" line and one "apps" section. The app id only
    # appears in the block for the library that actually holds the game, so a
    # block-by-block walk selects the right library without touching the disk.
    for block in re.split(r'^\s*"\d+"\s*$', text, flags=re.MULTILINE)[1:]:
        path_match = re.search(r'"path"\s+"([^"]+)"', block)
        if not path_match:
            continue
        if not re.search(rf'"{APP_ID}"\s+"\d+"', block):
            continue
        libraries.append(Path(path_match.group(1)))
    return libraries


def discover_game(
    override: str | Path | None = None,
    installs: list[SteamInstall] | None = None,
) -> GamePaths:
    """Locate the game.

    An explicit override wins. Otherwise every Steam installation on the machine
    is asked which library holds app 2767030. The tool never searches the
    filesystem for a folder named MarvelRivals, because that search can find a
    Windows dual-boot copy that Steam does not manage.
    """
    if override:
        paths = GamePaths(Path(override).expanduser())
        if not paths.is_valid():
            raise GameNotFound(f"No Paks directory under {paths.root}")
        return paths

    if installs is None:
        installs = steam_installs()

    if not installs:
        raise GameNotFound(
            "No Steam installation was found. Set steam_root or game_root in "
            f"{CONFIG_FILE}."
        )

    for install in installs:
        for library in _library_paths(install):
            candidate = GamePaths(library / "steamapps/common/MarvelRivals", install)
            if candidate.is_valid():
                return candidate

    searched = ", ".join(install.label for install in installs)
    raise GameNotFound(
        f"Steam does not report Marvel Rivals (app {APP_ID}) in any library. "
        f"Searched: {searched}. Set game_root in {CONFIG_FILE}."
    )


def local_config_files(
    installs: list[SteamInstall] | None = None,
) -> list[Path]:
    """Every Steam account's local settings file on this machine."""
    if installs is None:
        installs = steam_installs()

    found: list[Path] = []
    for install in installs:
        if not install.userdata.is_dir():
            continue
        for config in sorted(install.userdata.glob("*/config/localconfig.vdf")):
            if config not in found:
                found.append(config)
    return found


def read_vdf(path: Path) -> str:
    """Read a Steam settings file so it can be written back unchanged.

    "surrogateescape" carries any byte that is not valid UTF-8 through as it is.
    These files belong to Steam and can name a game or a folder in some other
    encoding; decoding those with "replace" and writing the result back would
    substitute the bytes and corrupt a part of the file that has nothing to do
    with what this tool came to change.
    """
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def account_of(config: Path) -> str:
    """The Steam account id that owns a localconfig.vdf."""
    return config.parent.parent.name


def launch_options_with_source(
    installs: list[SteamInstall] | None = None,
) -> tuple[str | None, Path | None]:
    """Read the launch options and say which account file they came from.

    The tool reads the first account that has a settings block for the game. A
    machine with two accounts that both own it has no way to say which one the
    user means, so the source is reported rather than guessed at silently.
    """
    for config in local_config_files(installs):
        options = _launch_options_in(read_vdf(config))
        if options is not None:
            return options, config
    return None, None


def steam_launch_options(
    installs: list[SteamInstall] | None = None,
) -> str | None:
    """Read the Steam launch options for Marvel Rivals.

    Returns None when no settings file was found, and an empty string when the
    game has no launch options set.

    The app id must be looked up inside the "apps" section. It also appears
    inside binary licence data earlier in the file, and a plain text search
    finds that copy first and reports nothing. The value itself stores quotes
    escaped as \\", so the closing quote is the first one not preceded by a
    backslash.
    """
    options, _ = launch_options_with_source(installs)
    return options


def _apps_section(text: str) -> int:
    """Where the per-game settings begin."""
    for marker in ('"apps"', '"Apps"'):
        index = text.find(marker)
        if index >= 0:
            return index
    return 0


def _launch_options_in(text: str) -> str | None:
    start = _apps_section(text)
    match = re.search(rf'^\s*"{APP_ID}"\s*$', text[start:], re.MULTILINE)
    if not match:
        return None
    window = text[start + match.end() : start + match.end() + 2000]
    found = re.search(r'"LaunchOptions"\s+"((?:[^"\\]|\\.)*)"', window)
    if not found:
        return ""
    return unescape_vdf(found.group(1))


def unescape_vdf(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def escape_vdf(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
