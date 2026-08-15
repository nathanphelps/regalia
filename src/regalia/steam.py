"""Close Steam and edit the launch options for Marvel Rivals.

Steam keeps `localconfig.vdf` in memory and writes it out when it exits. An edit
made while Steam runs is therefore lost, and worse, the rewrite can drop what was
changed. Every write here happens with Steam closed, after a backup, and is read
back before it is called a success.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .environment import SteamInstall, primary_steam
from .paths import (
    APP_ID,
    DATA_DIR,
    _apps_section,
    _launch_options_in,
    account_of,
    escape_vdf,
    local_config_files,
    read_vdf,
)

BACKUP_DIR = DATA_DIR / "backups"
KEEP_BACKUPS = 10

# The client is one process; the interface runs as another. Either one being up
# means Steam owns the file.
PROCESSES = ("steam", "steamwebhelper")

SHUTDOWN_TIMEOUT = 30
POLL = 0.5


class SteamError(Exception):
    """The change could not be made."""


class SteamStillRunning(SteamError):
    """Steam is up and this machine offers no way to close it from here.

    The caller should ask the user to close Steam and then wait, rather than
    give up. Writing while Steam runs would lose the change.
    """


@dataclass(frozen=True, slots=True)
class EditResult:
    changed: bool
    before: str
    after: str
    backup: Path | None
    message: str
    account: str | None = None


# -- the running client --------------------------------------------------


def _resolve(install: SteamInstall | None) -> SteamInstall | None:
    """Fall back to the installation detected for this machine."""
    return install if install is not None else primary_steam()


def _probes(install: SteamInstall | None) -> list[list[str]]:
    resolved = _resolve(install)
    if resolved is not None:
        return resolved.process_probes()
    return [["pgrep", "-x", name] for name in PROCESSES]


def running_pids(install: SteamInstall | None = None) -> list[int]:
    found: set[int] = set()
    for probe in _probes(install):
        try:
            result = subprocess.run(probe, capture_output=True, text=True)
        except FileNotFoundError:
            # pgrep is missing. Report nothing rather than claim Steam is down,
            # because the caller decides whether to write based on this.
            raise SteamError(
                "pgrep is not installed, so regalia cannot tell whether Steam "
                "is running. Install procps, or close Steam and edit by hand."
            ) from None
        found.update(int(line) for line in result.stdout.split() if line.isdigit())
    return sorted(found)


def is_running(install: SteamInstall | None = None) -> bool:
    return bool(running_pids(install))


def wait_until_closed(
    install: SteamInstall | None = None, timeout: int = SHUTDOWN_TIMEOUT
) -> bool:
    """Poll until Steam is gone, without asking it to quit."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(install):
            return True
        time.sleep(POLL)
    return not is_running(install)


def shutdown(
    install: SteamInstall | None = None, timeout: int = SHUTDOWN_TIMEOUT
) -> bool:
    """Ask Steam to quit, then wait for it.

    Returns True once nothing is left running. The caller must not edit anything
    when this returns False; Steam would overwrite the change on its way out.

    Raises SteamStillRunning when this machine has no command that can close
    Steam. The caller should then ask the user to close it and call
    wait_until_closed.
    """
    if not is_running(install):
        return True

    resolved = _resolve(install)
    command = resolved.shutdown_command() if resolved else None
    if command is None:
        flavor = resolved.flavor.value if resolved else "unknown"
        raise SteamStillRunning(
            f"Steam is running, but no command on this machine can close a "
            f"{flavor} Steam. Close Steam yourself, then try again."
        )

    subprocess.run(command, capture_output=True)
    return wait_until_closed(install, timeout)


def start(install: SteamInstall | None = None) -> bool:
    """Launch Steam again, detached from this process."""
    resolved = _resolve(install)
    command = resolved.start_command() if resolved else None
    if command is None:
        return False
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


# -- merging the override ------------------------------------------------

OVERRIDE_KEY = "WINEDLLOVERRIDES"
DSOUND = "dsound=n,b"
COMMAND = "%command%"

EXISTING_OVERRIDE = re.compile(rf'{OVERRIDE_KEY}="([^"]*)"')


def merge_override(existing: str, entry: str = DSOUND) -> str:
    """Add the DLL override without discarding what is already there.

    Launch options often carry other settings. Overwriting them to add one entry
    would silently undo a Proton tweak, so the existing value is kept and the
    override is folded into it.
    """
    existing = (existing or "").strip()
    name = entry.split("=", 1)[0]

    if not existing:
        return f'{OVERRIDE_KEY}="{entry}" {COMMAND}'

    if match := EXISTING_OVERRIDE.search(existing):
        current = match.group(1)
        if any(part.split("=", 1)[0] == name for part in current.split(";") if part):
            return existing  # already covers this DLL
        merged = f"{current};{entry}" if current else entry
        return (
            existing[: match.start()]
            + f'{OVERRIDE_KEY}="{merged}"'
            + existing[match.end() :]
        )

    if COMMAND in existing:
        return existing.replace(COMMAND, f'{OVERRIDE_KEY}="{entry}" {COMMAND}', 1)

    # No %command% placeholder, so Steam would pass the whole string to the game.
    # Put the override first and let the old text become game arguments.
    return f'{OVERRIDE_KEY}="{entry}" {COMMAND} {existing}'


# -- editing the file ----------------------------------------------------


def _block_span(text: str, start: int) -> tuple[int, int]:
    """Find the braces of the app block that begins at `start`.

    Values can contain braces, so the scan tracks whether it sits inside a
    quoted string.
    """
    opening = text.find("{", start)
    if opening < 0:
        raise SteamError("The app block has no opening brace")

    depth = 0
    in_string = False
    index = opening
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return opening, index
        index += 1
    raise SteamError("The app block is not closed")


def _rewrite(text: str, value: str) -> str:
    """Return the file with the launch options for this game set to `value`."""
    start = _apps_section(text)
    match = re.search(rf'^([ \t]*)"{APP_ID}"[ \t]*$', text[start:], re.MULTILINE)
    if not match:
        raise SteamError(
            f"Steam has no settings block for app {APP_ID}. Run the game once first."
        )

    indent = match.group(1)
    opening, closing = _block_span(text, start + match.end())
    block = text[opening : closing + 1]
    escaped = escape_vdf(value)

    existing = re.search(r'([ \t]*)"LaunchOptions"[ \t]+"(?:[^"\\]|\\.)*"', block)
    if existing:
        replacement = f'{existing.group(1)}"LaunchOptions"\t\t"{escaped}"'
        new_block = block[: existing.start()] + replacement + block[existing.end() :]
    else:
        # Insert as the first key of the block, matching the file's indentation.
        inner = f'{indent}\t"LaunchOptions"\t\t"{escaped}"'
        new_block = "{\n" + inner + "\n" + block[1:].lstrip("\n")

    return text[:opening] + new_block + text[closing + 1 :]


def backup(path: Path) -> Path:
    """Copy the settings file aside before touching it."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"localconfig-{account_of(path)}-{stamp}.vdf"
    shutil.copy2(path, target)

    kept = sorted(BACKUP_DIR.glob("localconfig-*.vdf"))
    for stale in kept[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
    return target


def _write_atomically(path: Path, text: str) -> None:
    """Replace the file in one step so a crash cannot leave it half written.

    Read and written with "surrogateescape", which carries any byte the file
    holds that is not valid UTF-8 through unchanged. This file belongs to Steam
    and can name a game or a folder in some other encoding; decoding those with
    "replace" and writing the result back would quietly substitute the bytes and
    corrupt a part of the file that has nothing to do with the launch options.
    The read-back check would not notice, because it only compares the one value
    this module set.
    """
    mode = path.stat().st_mode & 0o777
    temporary = path.with_suffix(".vdf.regalia-new")
    with temporary.open("w", encoding="utf-8", errors="surrogateescape") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def set_launch_options(
    value: str,
    installs: list[SteamInstall] | None = None,
    install: SteamInstall | None = None,
) -> EditResult:
    """Write the launch options for Marvel Rivals.

    Steam must already be closed. The file is backed up, replaced in one step,
    and read back to prove the change landed. The result names the Steam account
    that was edited.
    """
    if is_running(install):
        raise SteamError("Steam is still running. Close it before editing.")

    files = local_config_files(installs)
    if not files:
        raise SteamError("No Steam settings file was found")

    for path in files:
        text = read_vdf(path)
        before = _launch_options_in(text)
        if before is None:
            continue  # this account does not own the game

        account = account_of(path)
        if before == value:
            return EditResult(False, before, before, None, "already set", account)

        saved = backup(path)
        _write_atomically(path, _rewrite(text, value))

        after = _launch_options_in(read_vdf(path))
        if after != value:
            shutil.copy2(saved, path)
            raise SteamError(
                f"The change did not take, so the backup was restored. Got {after!r}."
            )
        return EditResult(True, before, after, saved, "updated", account)

    raise SteamError(
        f"No Steam account on this machine has a settings block for app {APP_ID}."
    )


def read_current(
    installs: list[SteamInstall] | None = None,
) -> str | None:
    """The launch options as they stand, or None when no block exists."""
    for path in local_config_files(installs):
        current = _launch_options_in(read_vdf(path))
        if current is not None:
            return current
    return None


def apply_override(
    entry: str = DSOUND,
    installs: list[SteamInstall] | None = None,
    install: SteamInstall | None = None,
) -> EditResult:
    """Add the DLL override the signature bypass needs, keeping what is there."""
    for path in local_config_files(installs):
        current = _launch_options_in(read_vdf(path))
        if current is not None:
            return set_launch_options(merge_override(current, entry), installs, install)
    raise SteamError(f"No settings block for app {APP_ID} was found")
