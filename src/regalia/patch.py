"""The UTOC signature bypass patch.

Marvel Rivals checks pak signatures and refuses unsigned files. The bypass is an
ASI plugin loaded by Ultimate ASI Loader, which disguises itself as dsound.dll.
No mod loads without it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import archive
from .paths import GamePaths, account_of, launch_options_with_source

# Wine will not load a native dsound.dll unless the launch options say so.
# "n,b" means: try the native file first, then fall back to the built-in one.
REQUIRED_OVERRIDE = 'WINEDLLOVERRIDES="dsound=n,b" %command%'
OVERRIDE_MARKER = "dsound=n"

LOADER_NAME = "dsound.dll"
PLUGIN_DIR = "plugins"


@dataclass(frozen=True, slots=True)
class PatchStatus:
    loader_installed: bool
    plugin_installed: bool
    launch_options: str | None
    # Which Steam account the options came from. A machine with two accounts
    # that both own the game gives no way to know which one the user means, so
    # the answer is shown rather than assumed.
    steam_account: str | None = None

    @property
    def override_set(self) -> bool:
        return bool(self.launch_options and OVERRIDE_MARKER in self.launch_options)

    @property
    def steam_known(self) -> bool:
        """False when no Steam account on this machine lists the game."""
        return self.launch_options is not None

    @property
    def ready(self) -> bool:
        return self.loader_installed and self.plugin_installed and self.override_set

    @property
    def summary(self) -> str:
        if self.ready:
            return "patch ok"
        if not (self.loader_installed and self.plugin_installed):
            return "patch missing"
        return "override missing"


def status(game: GamePaths) -> PatchStatus:
    plugins = game.binaries / PLUGIN_DIR
    options, source = launch_options_with_source()
    return PatchStatus(
        loader_installed=(game.binaries / LOADER_NAME).is_file(),
        plugin_installed=plugins.is_dir() and any(plugins.glob("*.asi")),
        launch_options=options,
        steam_account=account_of(source) if source else None,
    )


def install(game: GamePaths, patch_archive: Path, staging: Path) -> list[str]:
    """Extract the bypass archive and copy the loader and plugins into the game.

    Returns the file names that were placed.
    """
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    # The archive keeps its "plugins" folder, so extraction must not flatten.
    try:
        archive.extract_tree(patch_archive, staging)
    except Exception as error:
        raise RuntimeError(f"could not extract the patch: {error}") from error

    game.binaries.mkdir(parents=True, exist_ok=True)
    placed: list[str] = []

    for dll in staging.rglob(LOADER_NAME):
        shutil.copy2(dll, game.binaries / LOADER_NAME)
        placed.append(LOADER_NAME)
        break

    target_plugins = game.binaries / PLUGIN_DIR
    for asi in staging.rglob("*.asi"):
        target_plugins.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asi, target_plugins / asi.name)
        placed.append(f"{PLUGIN_DIR}/{asi.name}")

    shutil.rmtree(staging, ignore_errors=True)
    if not placed:
        raise RuntimeError("the archive held no dsound.dll or .asi plugin")
    return placed


def uninstall(game: GamePaths) -> list[str]:
    """Remove the loader and the plugins."""
    removed: list[str] = []
    loader = game.binaries / LOADER_NAME
    if loader.is_file():
        loader.unlink()
        removed.append(LOADER_NAME)
    plugins = game.binaries / PLUGIN_DIR
    for asi in plugins.glob("*.asi") if plugins.is_dir() else []:
        asi.unlink()
        removed.append(f"{PLUGIN_DIR}/{asi.name}")
    return removed
