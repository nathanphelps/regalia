"""What this machine is ready to do, and what to fix when it is not.

One model, three presentations: the `doctor` command prints it, the desktop
application walks a new user through it, and the terminal application shows it
on a first run. Keeping the checks here stops the three from drifting apart.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import archive, credentials, nxm, patch
from .config import Config
from .environment import SteamInstall, steam_installs
from .heroes import OVERLAY_FILE, overlay_count, overlay_error
from .paths import (
    CONFIG_FILE,
    GameNotFound,
    GamePaths,
    account_of,
    discover_game,
    launch_options_with_source,
)


class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    BLOCKED = "blocked"

    @property
    def mark(self) -> str:
        return {"ok": "✓", "warn": "!", "blocked": "✗"}[self.value]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    level: Level
    detail: str
    remedy: str | None = None
    # An essential check has to pass before the tool can install a mod. The rest
    # are conveniences, and a warning on one of them must not open a setup flow
    # on a machine where everything already works.
    essential: bool = True

    @property
    def ok(self) -> bool:
        return self.level is Level.OK


@dataclass(frozen=True, slots=True)
class Report:
    checks: list[Check]
    game: GamePaths | None
    installs: list[SteamInstall]

    @property
    def blocked(self) -> list[Check]:
        return [check for check in self.checks if check.level is Level.BLOCKED]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if check.level is Level.WARN]

    @property
    def ready(self) -> bool:
        return not self.blocked

    @property
    def needs_setup(self) -> bool:
        """True when a first run should open the setup flow.

        A blocked check always opens it. A first run opens it only when
        something essential is not already working: a machine where detection
        found everything needs no introduction.
        """
        if self.blocked:
            return True
        unsettled = [check for check in self.checks if check.essential and not check.ok]
        return not Config.exists() and bool(unsettled)


# -- the individual checks -----------------------------------------------


def _extractor_check() -> Check:
    try:
        extractor = archive.require_extractor()
    except archive.NoExtractor as error:
        return Check(
            "Extractor",
            Level.BLOCKED,
            "none available",
            f"{error} Set {archive.ENV_BACKEND} to choose one explicitly.",
        )
    note = "" if extractor.name == "7z" else " — install p7zip for faster extraction"
    return Check("Extractor", Level.OK, f"{extractor.name} ({extractor.detail}){note}")


def _steam_check(installs: list[SteamInstall]) -> Check:
    if not installs:
        return Check(
            "Steam",
            Level.BLOCKED,
            "not found",
            "Install Steam, or set steam_root in " + str(CONFIG_FILE),
        )
    detail = ", ".join(install.label for install in installs)
    first = installs[0]
    if first.shutdown_command() is None:
        return Check(
            "Steam",
            Level.WARN,
            detail,
            f"No command can close a {first.flavor.value} Steam from here. "
            "You will be asked to close it by hand before a launch-option edit.",
        )
    return Check("Steam", Level.OK, detail)


def _game_check(game: GamePaths | None, error: str, installs) -> Check:
    if game is None:
        return Check(
            "Game",
            Level.BLOCKED,
            error or "not found",
            "Run Marvel Rivals once so Steam registers it, or set game_root in "
            + str(CONFIG_FILE),
        )
    if not game.mods.is_dir():
        return Check(
            "Game",
            Level.WARN,
            f"{game.root} — no ~mods folder yet",
            "The folder is created the first time you install a mod.",
        )
    return Check("Game", Level.OK, str(game.root))


def _scan_check(config: Config) -> Check:
    missing = [path for path in config.scan_dirs if not path.is_dir()]
    unwritable = [
        path
        for path in config.scan_dirs
        if path.is_dir() and not os.access(path, os.W_OK)
    ]
    listed = ", ".join(str(path) for path in config.scan_dirs) or "none set"

    if unwritable:
        names = ", ".join(str(path) for path in unwritable)
        return Check(
            "Downloads",
            Level.BLOCKED,
            listed,
            f"Cannot write to {names}. Downloads land there, so choose another "
            "folder in Settings.",
        )
    if missing:
        names = ", ".join(str(path) for path in missing)
        return Check(
            "Downloads",
            Level.WARN,
            listed,
            f"{names} does not exist yet. Setup can create it.",
        )
    return Check("Downloads", Level.OK, listed)


def _key_check() -> Check:
    key = credentials.load_key()
    if not key:
        return Check(
            "Nexus key",
            Level.WARN,
            "not set",
            "Search works without one. Downloads and collections need a key from "
            f"{credentials.API_KEY_URL}",
            essential=False,
        )
    if warning := credentials.file_mode_warning():
        return Check(
            "Nexus key",
            Level.WARN,
            credentials.mask(key),
            f"{warning}. Run: chmod 600 {credentials.CREDENTIALS_FILE}",
        )
    source = "environment" if os.environ.get(credentials.ENV_VAR) else "config file"
    return Check("Nexus key", Level.OK, f"{credentials.mask(key)} (from the {source})")


def _patch_checks(game: GamePaths | None) -> list[Check]:
    if game is None:
        return []
    state = patch.status(game)
    installed = state.loader_installed and state.plugin_installed

    files = Check(
        "Signature bypass",
        Level.OK if installed else Level.BLOCKED,
        f"loader {'yes' if state.loader_installed else 'no'}, "
        f"plugin {'yes' if state.plugin_installed else 'no'}",
        None
        if installed
        else "No mod loads without it. Install the bypass archive from the "
        "PATCH screen.",
    )

    if not state.steam_known:
        override = Check(
            "Launch options",
            Level.BLOCKED,
            "no Steam account owns this game",
            "Run the game once from Steam so it writes a settings block.",
        )
    elif state.override_set:
        where = f" (account {state.steam_account})" if state.steam_account else ""
        override = Check("Launch options", Level.OK, f"override set{where}")
    else:
        where = f" (account {state.steam_account})" if state.steam_account else ""
        override = Check(
            "Launch options",
            Level.BLOCKED,
            f"override missing{where}",
            f"Wine ignores the loader without it. Set: {patch.REQUIRED_OVERRIDE}",
        )
    return [files, override]


def _handler_check() -> Check:
    current = nxm.registered_handler()
    if nxm.is_registered():
        return Check("nxm:// handler", Level.OK, "regalia", essential=False)
    if current:
        return Check(
            "nxm:// handler",
            Level.WARN,
            current,
            "Another program owns it. Run: regalia register-nxm",
            essential=False,
        )
    return Check(
        "nxm:// handler",
        Level.WARN,
        "not registered",
        'Run "regalia register-nxm" to use Mod Manager Download links.',
        essential=False,
    )


def _overlay_check() -> Check:
    if error := overlay_error():
        return Check(
            "Hero overlay",
            Level.WARN,
            f"{OVERLAY_FILE} could not be read",
            f"{error}. The built-in table is being used instead.",
            essential=False,
        )
    count = overlay_count()
    if not count:
        return Check(
            "Hero overlay",
            Level.OK,
            "built-in table only",
            f"Add a hero the tool does not know in {OVERLAY_FILE}",
            essential=False,
        )
    return Check(
        "Hero overlay",
        Level.OK,
        f"{count} entries from {OVERLAY_FILE}",
        essential=False,
    )


def _menu_check() -> Check:
    if nxm.app_entry_installed():
        return Check(
            "Applications menu",
            Level.OK,
            str(nxm.APP_DESKTOP_FILE),
            essential=False,
        )
    return Check(
        "Applications menu",
        Level.WARN,
        "no entry",
        'Run "regalia install-desktop-entry" to add regalia to the menu.',
        essential=False,
    )


# -- the report ----------------------------------------------------------


def run_checks(config: Config | None = None) -> Report:
    """Run every check. Never raises: a failure is a check result."""
    config = config or Config.load()
    installs = steam_installs(config.steam_root)

    game: GamePaths | None = None
    game_error = ""
    try:
        game = discover_game(config.game_root, installs)
    except GameNotFound as error:
        game_error = str(error)

    checks = [
        _extractor_check(),
        _steam_check(installs),
        _game_check(game, game_error, installs),
        _scan_check(config),
        _key_check(),
        *_patch_checks(game),
        _handler_check(),
        _overlay_check(),
        _menu_check(),
    ]
    return Report(checks, game, installs)


def environment_summary() -> list[tuple[str, str]]:
    """Facts worth pasting into a bug report."""
    rows = [
        ("regalia", _version()),
        ("python", sys.version.split()[0]),
        ("platform", platform.platform()),
        ("distribution", _distribution()),
        ("session", os.environ.get("XDG_SESSION_TYPE", "unknown")),
        ("config file", str(CONFIG_FILE)),
    ]
    options, source = launch_options_with_source()
    if source is not None:
        rows.append(("steam account", account_of(source)))
        rows.append(("launch options", options or "(empty)"))
    rows.append(("7z command", archive.seven_zip_command() or "not installed"))
    rows.append(("notify-send", shutil.which("notify-send") or "not installed"))
    return rows


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("regalia")
    except PackageNotFoundError:
        return "unknown"


def _distribution() -> str:
    """The distribution name, from the file every modern distribution ships."""
    try:
        text = Path("/etc/os-release").read_text(errors="replace")
    except OSError:
        return "unknown"
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"
