"""Download mod archives into the scan folder."""

from __future__ import annotations

import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .client import USER_AGENT, NexusClient, NexusError, NexusOffline

CHUNK = 1 << 16
UNSAFE = re.compile(r"[^A-Za-z0-9._\- ]+")
DISPOSITION = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)

Progress = Callable[[int, int], None]


class Cancelled(NexusError):
    """The caller asked to stop."""


def safe_name(name: str, fallback: str) -> str:
    """Make a file name that cannot escape the target folder."""
    cleaned = UNSAFE.sub("_", Path(name).name).strip(" .")
    return cleaned or fallback


def encode_url(url: str) -> str:
    """Escape a URL that Nexus returned with raw spaces in the path.

    Nexus serves from several CDNs. One uses an opaque identifier for the path,
    another puts the archive name there and does not escape it, so the path can
    hold spaces. Python refuses to send those. The percent sign stays safe so an
    already escaped path is not escaped twice.
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~-._")
    return urllib.parse.urlunsplit(parts._replace(path=path))


def _name_from_response(url: str, headers, fallback: str) -> str:
    """Work out what to call the file that is arriving.

    Content-Disposition is the best source, because the name it gives carries
    the mod id and version that the name parser reads. The URL path is next,
    but only when it ends in a real extension: one CDN uses a bare identifier
    there, which would name every download after a UUID.
    """
    disposition = headers.get("Content-Disposition") or ""
    if match := DISPOSITION.search(disposition):
        return safe_name(urllib.parse.unquote(match.group(1)), fallback)

    from_path = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    if Path(from_path).suffix.lower() in (".7z", ".zip", ".rar"):
        return safe_name(from_path, fallback)
    return fallback


def fetch(
    url: str,
    destination: Path,
    fallback_name: str,
    on_progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Stream a URL into `destination` and return the file written.

    The download writes to a .part file and renames on success, so an
    interrupted run never leaves a half archive that the scanner would treat as
    a real mod.
    """
    destination.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(encode_url(url))
    request.add_header("User-Agent", USER_AGENT)

    partial: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            name = _name_from_response(url, response.headers, fallback_name)
            target = destination / name
            if target.exists():
                return target

            # The scratch name carries the worker's id. Several members of one
            # collection can resolve to the same archive, and a shared scratch
            # path would have one worker rename the file out from under another.
            partial = target.with_suffix(
                f"{target.suffix}.{os.getpid()}-{threading.get_ident()}.part"
            )
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with partial.open("wb") as handle:
                while block := response.read(CHUNK):
                    if cancelled and cancelled():
                        raise Cancelled("cancelled")
                    handle.write(block)
                    done += len(block)
                    if on_progress:
                        on_progress(done, total)
    except Cancelled:
        if partial:
            partial.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        if partial:
            partial.unlink(missing_ok=True)
        raise NexusOffline(f"Download failed: {error}") from error

    # A dropped connection does not always raise. The server can close cleanly
    # part way through, `read` returns nothing, and the loop ends as though the
    # file were complete. Promoting that hands the user a truncated archive that
    # fails to extract much later, with an error that says nothing about the
    # download. Checked here rather than inside the loop so the scratch file is
    # cleaned up on the way out.
    if total and done != total:
        partial.unlink(missing_ok=True)
        raise NexusOffline(
            f"Download stopped early: got {done:,} of {total:,} bytes. Try again."
        )

    if target.exists():
        # Another worker finished the same archive first. Its copy is complete,
        # so this one is discarded rather than overwriting a file in use.
        partial.unlink(missing_ok=True)
        return target

    partial.replace(target)
    return target


def download_file(
    client: NexusClient,
    mod_id: int,
    file_id: int,
    destination: Path,
    file_name: str | None = None,
    key: str | None = None,
    expires: str | None = None,
    on_progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Resolve a download link and fetch the archive."""
    url = client.download_link(mod_id, file_id, key, expires)
    fallback = safe_name(file_name or "", f"{mod_id}-{file_id}.7z")
    if not Path(fallback).suffix:
        fallback += ".7z"
    return fetch(url, destination, fallback, on_progress, cancelled)
