"""Where this machine keeps its directories and its Steam installation.

This is the only module that knows a Flatpak path, and it is also the only
module that knows how to stop a Flatpak Steam. Keeping both facts together is
what lets a new packaging flavour be added in one place.

Every function accepts an optional home directory and environment mapping. They
default to the real ones. The tests use that seam to build a fake machine for
each flavour without touching the real environment.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

FLATPAK_ID = "com.valvesoftware.Steam"
SNAP_NAME = "steam"

LIBRARIES_VDF = "steamapps/libraryfolders.vdf"


class SteamFlavor(StrEnum):
    NATIVE = "native"
    DEB = "deb"
    FLATPAK = "flatpak"
    SNAP = "snap"


# -- base directories ----------------------------------------------------


def _home(home: Path | None) -> Path:
    return home if home is not None else Path.home()


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _base_dir(
    variable: str,
    fallback: str,
    home: Path | None,
    env: Mapping[str, str] | None,
) -> Path:
    """Resolve one XDG base directory.

    The specification says a relative value must be ignored, so only an absolute
    path is honoured.
    """
    value = _env(env).get(variable, "").strip()
    if value.startswith("/"):
        return Path(value)
    return _home(home) / fallback


def xdg_config_home(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    return _base_dir("XDG_CONFIG_HOME", ".config", home, env)


def xdg_data_home(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    return _base_dir("XDG_DATA_HOME", ".local/share", home, env)


def xdg_cache_home(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    return _base_dir("XDG_CACHE_HOME", ".cache", home, env)


USER_DIRS_LINE = re.compile(r'^\s*XDG_DOWNLOAD_DIR\s*=\s*"(.*)"\s*$', re.MULTILINE)


def _expand_user_dir(value: str, home: Path) -> str:
    """Expand the one form user-dirs.dirs writes.

    The file stores "$HOME/Downloads". Nothing expands that for us, and a plain
    Path would treat the dollar sign as part of the folder name.
    """
    value = value.strip()
    if value.startswith("$HOME"):
        return f"{home}{value[len('$HOME') :]}"
    if value.startswith("~"):
        return f"{home}{value[1:]}"
    return value


def download_dir(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    """The user's downloads folder.

    A localised desktop names this folder in the user's own language, so
    "~/Downloads" is a last resort rather than the answer.
    """
    direct = _env(env).get("XDG_DOWNLOAD_DIR", "").strip()
    if direct:
        return Path(_expand_user_dir(direct, _home(home)))

    user_dirs = xdg_config_home(home, env) / "user-dirs.dirs"
    if user_dirs.is_file():
        try:
            text = user_dirs.read_text(errors="replace")
        except OSError:
            text = ""
        if match := USER_DIRS_LINE.search(text):
            expanded = _expand_user_dir(match.group(1), _home(home))
            if expanded:
                return Path(expanded)

    return _home(home) / "Downloads"


# -- the Steam installation ----------------------------------------------


def flavor_for(path: Path) -> SteamFlavor:
    """Guess the packaging flavour from a root the user typed in themselves."""
    text = str(path)
    if f".var/app/{FLATPAK_ID}" in text:
        return SteamFlavor.FLATPAK
    if "/snap/steam/" in text:
        return SteamFlavor.SNAP
    if "debian-installation" in text:
        return SteamFlavor.DEB
    return SteamFlavor.NATIVE


@dataclass(frozen=True, slots=True)
class SteamInstall:
    root: Path
    flavor: SteamFlavor

    @property
    def userdata(self) -> Path:
        return self.root / "userdata"

    @property
    def libraries_file(self) -> Path:
        return self.root / LIBRARIES_VDF

    @property
    def label(self) -> str:
        return f"{self.flavor.value} at {self.root}"

    def _launcher(self) -> list[str] | None:
        """The command that runs the client, or None when it is not installed."""
        if self.flavor is SteamFlavor.FLATPAK:
            return ["flatpak", "run", FLATPAK_ID] if shutil.which("flatpak") else None
        if self.flavor is SteamFlavor.SNAP:
            return ["snap", "run", SNAP_NAME] if shutil.which("snap") else None
        return ["steam"] if shutil.which("steam") else None

    def start_command(self) -> list[str] | None:
        return self._launcher()

    def shutdown_command(self) -> list[str] | None:
        launcher = self._launcher()
        return [*launcher, "-shutdown"] if launcher else None

    def process_probes(self) -> list[list[str]]:
        """The commands that answer whether this Steam is running.

        A Flatpak Steam normally keeps the process name, so the exact-name probe
        usually finds it. The command-line probe is there because that is the
        one fact this project cannot verify on the author's machine.
        """
        probes = [["pgrep", "-x", name] for name in ("steam", "steamwebhelper")]
        if self.flavor is SteamFlavor.FLATPAK:
            probes.append(["pgrep", "-f", FLATPAK_ID])
        if self.flavor is SteamFlavor.SNAP:
            probes.append(["pgrep", "-f", "snap/steam"])
        return probes


def candidate_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[tuple[Path, SteamFlavor]]:
    """Every place a Steam installation is known to live, in priority order."""
    base = _home(home)
    return [
        (xdg_data_home(home, env) / "Steam", SteamFlavor.NATIVE),
        (base / ".steam/steam", SteamFlavor.NATIVE),
        (base / ".steam/root", SteamFlavor.NATIVE),
        (base / ".steam/debian-installation", SteamFlavor.DEB),
        (base / ".var/app" / FLATPAK_ID / "data/Steam", SteamFlavor.FLATPAK),
        (base / "snap/steam/common/.local/share/Steam", SteamFlavor.SNAP),
    ]


def find_steam_installs(
    override: str | Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[SteamInstall]:
    """Find every Steam installation on this machine.

    An override is tried first and its flavour is guessed from the path.
    Duplicates are dropped by resolved path, because "~/.steam/steam" is usually
    a symbolic link to the native root.
    """
    candidates: list[tuple[Path, SteamFlavor]] = []
    if override:
        chosen = Path(override).expanduser()
        candidates.append((chosen, flavor_for(chosen)))
    candidates += candidate_roots(home, env)

    found: list[SteamInstall] = []
    seen: set[Path] = set()
    for path, flavor in candidates:
        if not (path / LIBRARIES_VDF).is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(SteamInstall(resolved, flavor))
    return found


# -- the machine this process is running on ------------------------------

_cached: list[SteamInstall] | None = None


def steam_installs(
    override: str | Path | None = None, refresh: bool = False
) -> list[SteamInstall]:
    """The installations on this machine, found once and remembered.

    Detection touches the disk, and both interfaces ask for it repeatedly while
    they redraw. The cache keeps that cheap. Pass refresh after the user changes
    the configured root.
    """
    global _cached
    if refresh or _cached is None:
        _cached = find_steam_installs(override)
    return _cached


def primary_steam(override: str | Path | None = None) -> SteamInstall | None:
    """The installation to drive when nothing more specific is known."""
    installs = steam_installs(override)
    return installs[0] if installs else None
