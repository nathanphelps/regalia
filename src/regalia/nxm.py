"""Desktop integration: the nxm:// handler and the application entry.

Clicking "Mod Manager Download" on the Nexus site opens an nxm:// link. This
module parses that link and registers regalia as the program that handles it.
It also writes the menu entry for the desktop application itself.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .environment import xdg_data_home
from .nexus.client import GAME_DOMAIN
from .paths import CACHE_DIR, CONFIG_DIR

DESKTOP_DIR = xdg_data_home() / "applications"
DESKTOP_FILE = DESKTOP_DIR / "regalia-nxm.desktop"
APP_DESKTOP_FILE = DESKTOP_DIR / "regalia.desktop"
SCHEME = "x-scheme-handler/nxm"

# The handler runs with no terminal. When the desktop cannot show a notice, the
# reason has to land somewhere the user can find it afterwards.
LOG_FILE = CACHE_DIR / "nxm.log"

# Another mod manager usually owns nxm:// already. The name of that program is
# kept so that unregistering gives the association back instead of leaving the
# scheme with no handler at all.
PREVIOUS_HANDLER = CONFIG_DIR / "previous-nxm-handler"

LINK = re.compile(r"^/mods/(\d+)/files/(\d+)/?$")


class NxmError(Exception):
    """The link could not be used."""


@dataclass(frozen=True, slots=True)
class NxmLink:
    game: str
    mod_id: int
    file_id: int
    key: str | None
    expires: str | None


def parse_link(url: str) -> NxmLink:
    """Read an nxm:// link.

    The key and expires pair appears when the site issues the link to a free
    account. Passing them through also works for a Premium account, so they are
    kept whenever present.
    """
    parts = urlparse(url)
    if parts.scheme != "nxm":
        raise NxmError(f"Not an nxm link: {url[:60]}")

    game = parts.netloc.lower()
    match = LINK.match(parts.path)
    if not match:
        raise NxmError(f"Could not read the mod and file from {url[:60]}")

    query = parse_qs(parts.query)
    return NxmLink(
        game=game,
        mod_id=int(match.group(1)),
        file_id=int(match.group(2)),
        key=(query.get("key") or [None])[0],
        expires=(query.get("expires") or [None])[0],
    )


def check_game(link: NxmLink) -> None:
    if link.game != GAME_DOMAIN:
        raise NxmError(
            f"This link is for {link.game}. regalia only handles {GAME_DOMAIN}."
        )


def log(message: str) -> None:
    """Append one line to the handler's log, ignoring any failure."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a") as handle:
            handle.write(f"{stamp}  {message}\n")
    except OSError:
        pass


def notify(title: str, body: str, urgency: str = "normal") -> None:
    """Report to the desktop. The handler has no terminal to print to.

    Every message is logged as well. A desktop without notify-send would
    otherwise swallow the only report a failed download ever makes.
    """
    log(f"{urgency}: {body}")
    if not shutil.which("notify-send"):
        return
    _run(["notify-send", "-u", urgency, "-a", "regalia", title, body])


DESKTOP_TIMEOUT = 10


def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run a desktop helper, bounded.

    These talk to the session bus and the desktop's own services. A notification
    daemon that has stopped answering, or an xdg-mime waiting on a portal, would
    otherwise hold the calling thread for as long as it takes — and one of these
    runs on the path a browser download takes, where there is no window to show
    that anything is wrong.

    A timeout is reported as a failed command rather than raised, because none
    of these is worth abandoning the work for.
    """
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=DESKTOP_TIMEOUT
        )
    except (subprocess.TimeoutExpired, OSError):
        return subprocess.CompletedProcess(
            command, 1, "", f"{command[0]} did not answer"
        )


# -- desktop registration ------------------------------------------------


def _executable() -> str:
    """The command that should receive the link.

    sys.argv[0] points at the console script inside the virtual environment,
    which is what the desktop entry needs.
    """
    candidate = Path(sys.argv[0]).resolve()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return f"{sys.executable} -m regalia"


def desktop_entry() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=regalia\n"
        "GenericName=Marvel Rivals mod installer\n"
        f"Exec={_executable()} nxm %u\n"
        f"MimeType={SCHEME};\n"
        "NoDisplay=true\n"
        "Terminal=false\n"
        "Categories=Game;\n"
    )


def app_desktop_entry() -> str:
    """The menu entry for the desktop application itself."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=regalia\n"
        "GenericName=Marvel Rivals mod manager\n"
        "Comment=Install and manage Marvel Rivals mods\n"
        f"Exec={_executable()}\n"
        "Icon=applications-games\n"
        "Terminal=false\n"
        "Categories=Game;Utility;\n"
        "Keywords=marvel;rivals;mods;nexus;\n"
    )


def install_app_entry() -> Path:
    """Put regalia in the applications menu."""
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    APP_DESKTOP_FILE.write_text(app_desktop_entry())
    refresh_desktop_database()
    return APP_DESKTOP_FILE


def remove_app_entry() -> bool:
    """Take regalia out of the applications menu."""
    if not APP_DESKTOP_FILE.exists():
        return False
    APP_DESKTOP_FILE.unlink()
    refresh_desktop_database()
    return True


def app_entry_installed() -> bool:
    return APP_DESKTOP_FILE.is_file()


def refresh_desktop_database() -> bool:
    if not shutil.which("update-desktop-database"):
        return False
    _run(["update-desktop-database", str(DESKTOP_DIR)])
    return True


def _desktop_file_exists(name: str) -> bool:
    """True when a desktop entry of this name is still installed.

    An entry can name a program that was removed. xdg-mime keeps reporting it,
    so the name alone does not prove that anything can open the link.
    """
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots = [DESKTOP_DIR]
    roots += [Path(part) / "applications" for part in data_dirs.split(":") if part]
    return any((root / name).is_file() for root in roots)


def register() -> list[str]:
    """Make regalia the handler for nxm:// links."""
    steps: list[str] = []

    # Only remember a handler that still exists. The rename left the old entry
    # registered but deleted, and giving the scheme back to a missing program
    # is worse than leaving it with regalia.
    current = registered_handler()
    if current and current != DESKTOP_FILE.name and _desktop_file_exists(current):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PREVIOUS_HANDLER.write_text(current + "\n")
        steps.append(f"remembered the previous handler: {current}")

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(desktop_entry())
    steps.append(f"wrote {DESKTOP_FILE}")

    for command in (
        ["xdg-mime", "default", DESKTOP_FILE.name, SCHEME],
        ["update-desktop-database", str(DESKTOP_DIR)],
    ):
        if not shutil.which(command[0]):
            steps.append(f"skipped {command[0]}: not installed")
            continue
        result = _run(command)
        steps.append(
            f"ran {command[0]}"
            if result.returncode == 0
            else f"{command[0]} failed: {result.stderr.strip()[:80]}"
        )
    return steps


def unregister() -> list[str]:
    """Stop handling nxm:// links and give the scheme back to its old owner."""
    steps = []
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()
        steps.append(f"removed {DESKTOP_FILE}")

    if PREVIOUS_HANDLER.is_file():
        previous = PREVIOUS_HANDLER.read_text().strip()
        if previous and not _desktop_file_exists(previous):
            steps.append(f"the previous handler {previous} is gone; left it alone")
            previous = ""
        if previous and shutil.which("xdg-mime"):
            result = _run(["xdg-mime", "default", previous, SCHEME])
            steps.append(
                f"gave nxm:// back to {previous}"
                if result.returncode == 0
                else f"could not restore {previous}: {result.stderr.strip()[:80]}"
            )
        PREVIOUS_HANDLER.unlink()

    if shutil.which("update-desktop-database"):
        _run(["update-desktop-database", str(DESKTOP_DIR)])
        steps.append("refreshed the desktop database")
    return steps or ["nothing was registered"]


def previous_handler() -> str | None:
    """The program that owned nxm:// before regalia took it."""
    if PREVIOUS_HANDLER.is_file():
        return PREVIOUS_HANDLER.read_text().strip() or None
    return None


def registered_handler() -> str | None:
    """Which program currently handles nxm:// links."""
    if not shutil.which("xdg-mime"):
        return None
    return _run(["xdg-mime", "query", "default", SCHEME]).stdout.strip() or None


def is_registered() -> bool:
    return registered_handler() == DESKTOP_FILE.name
