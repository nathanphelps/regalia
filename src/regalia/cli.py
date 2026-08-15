"""Command line entry point.

The bare command opens the desktop application, because that is what most
people install. Everything else is a subcommand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import maintenance
from .archive import NoExtractor, require_extractor
from .config import Config
from .maintenance import SCOPES

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

    importer = sub.add_parser(
        "import", help="copy archives into the library the tool manages"
    )
    importer.add_argument("paths", nargs="+", type=Path, help="files or folders")
    importer.add_argument(
        "--move",
        action="store_true",
        help="move instead of copying, leaving the source folder empty",
    )

    resetter = sub.add_parser(
        "reset", help="remove what the tool made; lists it first and asks"
    )
    resetter.add_argument(
        "scopes",
        nargs="*",
        help=f"any of: {', '.join(SCOPES)}, or 'all' for everything but the library",
    )
    resetter.add_argument(
        "--yes", action="store_true", help="do it, rather than only listing it"
    )

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
    from . import credentials, library, nxm
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

    # Into the library, never the browser's download folder. A file there gets
    # renamed on a repeat download and swept up by the desktop cleaner, and the
    # catalog keys a mod by its archive path.
    destination = library.ensure()
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


def _import(paths: list[Path], move: bool, config: Config) -> int:
    """Bring archives into the library so the catalog stops depending on them."""
    from . import library

    log = library.import_all([path.expanduser() for path in paths], move)
    for line in log:
        print(line)
    count, size = library.size()
    print(f"library: {count} archive(s), {maintenance.human(size)}")
    return 0


def _reset(scopes: list[str], confirmed: bool, config: Config) -> int:
    """List what a reset would remove, and remove it only when told to.

    The listing is the default because the scopes differ in cost. Unlinking is
    reversible in a second; dropping the library means downloading a collection
    again, so "all" leaves it alone and the user has to name it.
    """
    from .catalog import Catalog
    from .paths import GameNotFound, discover_game

    if not scopes:
        print("Say what to reset. Scopes:\n")
        for scope in SCOPES:
            mark = "  (not in 'all')" if scope in maintenance.DESTRUCTIVE else ""
            print(f"  {scope:<12} {maintenance.DESCRIPTIONS[scope]}{mark}")
        print("\n  all          everything above except the library")
        print("\nAdd --yes to carry it out. Example: regalia reset links store --yes")
        return 0

    if "all" in scopes:
        scopes = [scope for scope in SCOPES if scope not in maintenance.DESTRUCTIVE]

    mods_dir = None
    try:
        mods_dir = discover_game(config.game_root).mods
    except GameNotFound:
        pass

    catalog = Catalog.load()
    claimed = {name for mod in catalog.mods for name in mod.all_files}

    try:
        todo = maintenance.plan(scopes, mods_dir, claimed)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    if todo.is_empty:
        print("Nothing to remove.")
        return 0

    for scope, items in todo.by_scope().items():
        size = maintenance.human(sum(item.bytes for item in items))
        print(f"{scope:<12} {len(items):>5} item(s)  {size:>10}")
        print(f"             {maintenance.DESCRIPTIONS[scope]}")
    print(f"\ntotal: {todo.count} item(s), {maintenance.human(todo.bytes)}")

    if not confirmed:
        print("\nNothing was removed. Add --yes to carry this out.")
        return 0

    for line in maintenance.run(todo):
        print(line)
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
    if args.command not in ("doctor", "status", "reset"):
        try:
            require_extractor()
        except NoExtractor as error:
            print(error, file=sys.stderr)
            return 1

    if args.command == "nxm":
        return _handle_nxm(args.url, config)
    if args.command == "import":
        return _import(args.paths, args.move, config)
    if args.command == "reset":
        return _reset(args.scopes, args.yes, config)
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
