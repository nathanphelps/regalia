"""Command line entry point.

The bare command opens the desktop application, because that is what most
people install. Everything else is a subcommand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .archive import NoExtractor, require_extractor
from .config import Config

TUI_MISSING = (
    "The terminal interface is not installed. Add it with:\n"
    "  uv tool install 'regalia[tui]'\n"
    "  pip install 'regalia[tui]'"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regalia",
        description="Install and manage Marvel Rivals mods.",
    )
    parser.add_argument("--dark", action="store_true", help="use the dark theme")
    parser.add_argument("--light", action="store_true", help="use the light theme")
    parser.add_argument("--game-root", type=Path, help="override the game directory")
    parser.add_argument("--steam-root", type=Path, help="override the Steam directory")
    parser.add_argument(
        "--scan", type=Path, action="append", help="a folder to scan (repeatable)"
    )
    parser.add_argument("--save", action="store_true", help="save these options")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="open the desktop application (the default)")
    sub.add_parser("tui", help="open the terminal application")
    sub.add_parser("doctor", help="check this machine and report what to fix")
    handler = sub.add_parser("nxm", help="handle an nxm:// link from the browser")
    handler.add_argument("url")
    sub.add_parser("register-nxm", help="handle nxm:// links from now on")
    sub.add_parser("unregister-nxm", help="stop handling nxm:// links")
    sub.add_parser("install-desktop-entry", help="add regalia to the menu")
    sub.add_parser("remove-desktop-entry", help="take regalia out of the menu")
    sub.add_parser("status", help="print the current state and exit")
    cleaner = sub.add_parser(
        "clean", help="list downloads that never finished; -y deletes them"
    )
    # Listing is the default. The screen asks before it deletes, and a command
    # that deletes the moment it is typed does not match that.
    cleaner.add_argument(
        "-y", "--yes", action="store_true", help="delete them, do not just list"
    )
    return parser


def _config_from(args: argparse.Namespace) -> Config:
    config = Config.load()
    # The two interfaces keep their theme in different fields. A theme flag has
    # to set both, or it does nothing to whichever one the user opens.
    if args.dark:
        config.dark = True
        config.gui_theme = "dark"
    if args.light:
        config.dark = False
        config.gui_theme = "light"
    if args.game_root:
        config.game_root = args.game_root.expanduser()
    if args.steam_root:
        config.steam_root = args.steam_root.expanduser()
    if args.scan:
        config.scan_dirs = [path.expanduser() for path in args.scan]
    if args.save:
        config.save()
    return config


def _handle_nxm(url: str, config: Config) -> int:
    """Download one file for a link the browser handed over.

    This runs without a terminal, so every result goes to the desktop.
    """
    from . import credentials, nxm
    from .nexus import NexusClient, NexusError
    from .nexus.download import download_file

    try:
        link = nxm.parse_link(url)
        nxm.check_game(link)
    except nxm.NxmError as error:
        nxm.notify("regalia", str(error), "critical")
        print(error, file=sys.stderr)
        return 2

    key = credentials.load_key()
    if not key:
        message = "No Nexus API key. Open regalia and add one."
        nxm.notify("regalia", message, "critical")
        print(message, file=sys.stderr)
        return 3

    destination = config.scan_dirs[0]
    nxm.notify("regalia", f"Downloading mod {link.mod_id}…")
    try:
        path = download_file(
            NexusClient(key),
            link.mod_id,
            link.file_id,
            destination,
            key=link.key,
            expires=link.expires,
        )
    except NexusError as error:
        nxm.notify("regalia", f"Download failed: {error}", "critical")
        print(error, file=sys.stderr)
        return 1

    nxm.notify("regalia", f"Saved {path.name}")
    print(path)
    return 0


def _status(config: Config) -> int:
    from . import credentials, nxm
    from .environment import steam_installs
    from .nexus.client import GAME_DOMAIN
    from .paths import GameNotFound, discover_game

    installs = steam_installs(config.steam_root)
    print(f"steam       : {', '.join(i.label for i in installs) or 'not found'}")

    try:
        game = discover_game(config.game_root, installs)
        print(f"game        : {game.root}")
        present = "present" if game.mods.is_dir() else "absent"
        print(f"mods folder : {game.mods}  ({present})")
    except GameNotFound as error:
        print(f"game        : not found — {error}")

    print(f"scan folders: {', '.join(str(p) for p in config.scan_dirs)}")
    print(f"nexus key   : {credentials.mask(credentials.load_key())}")
    if warning := credentials.file_mode_warning():
        print(f"  warning   : {warning}")
    handler = nxm.registered_handler()
    owner = "ours" if nxm.is_registered() else "not ours"
    print(f"nxm handler : {handler or 'none'}  ({owner})")
    print(f"game domain : {GAME_DOMAIN}")
    return 0


def _doctor(config: Config) -> int:
    """Report every check and how to fix what fails."""
    from .readiness import environment_summary, run_checks

    for name, value in environment_summary():
        print(f"{name:<16}{value}")
    print()

    report = run_checks(config)
    for check in report.checks:
        print(f"{check.level.mark} {check.name:<20}{check.detail}")
        if check.remedy:
            for line in check.remedy.splitlines():
                print(f"    → {line}")

    print()
    if report.blocked:
        print(f"{len(report.blocked)} blocking problem(s). Fix those first.")
        return 1
    if report.warnings:
        print(f"Ready, with {len(report.warnings)} note(s).")
        return 0
    print("Everything checks out.")
    return 0


def _run_gui(config: Config) -> int:
    from .gui.application import main as gui_main

    return gui_main(config)


def _run_tui(config: Config) -> int:
    try:
        from .app import run
    except ImportError:
        print(TUI_MISSING, file=sys.stderr)
        return 1
    run(config)
    return 0


def main() -> int:
    args = _build_parser().parse_args()

    # Carry an installation over from the old name before anything reads a
    # directory. The interfaces finish the job once they know the game path.
    from . import migrate

    for step in migrate.run():
        print(step, file=sys.stderr)

    config = _config_from(args)

    # Everything except the reports needs to be able to open an archive.
    if args.command not in ("doctor", "status"):
        try:
            require_extractor()
        except NoExtractor as error:
            print(error, file=sys.stderr)
            return 1

    if args.command == "nxm":
        return _handle_nxm(args.url, config)
    if args.command == "register-nxm":
        from . import nxm

        for step in nxm.register():
            print(step)
        return 0
    if args.command == "unregister-nxm":
        from . import nxm

        for step in nxm.unregister():
            print(step)
        return 0
    if args.command == "install-desktop-entry":
        from . import nxm

        print(f"wrote {nxm.install_app_entry()}")
        return 0
    if args.command == "remove-desktop-entry":
        from . import nxm

        print("removed" if nxm.remove_app_entry() else "nothing was installed")
        return 0
    if args.command == "status":
        return _status(config)
    if args.command == "doctor":
        return _doctor(config)
    if args.command == "clean":
        from .archive import clean_partials, find_partials

        partials = find_partials(config.scan_dirs)
        if not partials:
            print("no unfinished downloads")
            return 0
        total = sum(path.stat().st_size for path in partials)
        for path in partials:
            print(f"  {path.name}  ({path.stat().st_size / 2**20:,.0f} MB)")
        if not args.yes:
            print(
                f"\n{len(partials)} file(s), {total / 2**20:,.0f} MB. "
                "Run again with -y to delete them."
            )
            return 0
        removed, freed = clean_partials(config.scan_dirs)
        print(f"removed {removed} file(s), freed {freed / 2**20:,.0f} MB")
        return 0
    if args.command == "tui":
        return _run_tui(config)

    return _run_gui(config)


if __name__ == "__main__":
    raise SystemExit(main())
