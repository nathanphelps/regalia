"""Identify local archives by their MD5.

Hashing happens once per file and the result is cached. One batched query then
asks Nexus what every unknown hash is.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from .client import NexusClient
from .models import HashMatch

CHUNK = 1 << 20


def file_md5(path: Path, on_bytes: Callable[[int], None] | None = None) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
            if on_bytes:
                on_bytes(len(block))
    return digest.hexdigest()


def cache_key(path: Path) -> str:
    """A stamp that changes when the file changes."""
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def best_match(
    candidates: list[HashMatch],
    archive_name: str = "",
    hint_mod_id: int | None = None,
) -> HashMatch | None:
    """Choose which mod a hash really belongs to.

    A file redistributed across many mod pages answers once per page, so the
    order Nexus returns is not a decision. Three signals are used, in order:

    1. The mod id parsed out of the archive name. Nexus writes its own mod id
       into the file name it serves, so this is a strong and cheap signal.
    2. An exact match on the file name Nexus recorded.
    3. The lowest file id, which is the original upload. A redistribution is
       always uploaded later and therefore carries a higher id.

    Without this the signature bypass patch, which 53 mod pages carry, resolves
    to whichever page happened to come last.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    if hint_mod_id is not None:
        for candidate in candidates:
            if candidate.mod_id == hint_mod_id:
                return candidate

    if archive_name:
        stem = Path(archive_name).stem.lower()
        for candidate in candidates:
            if Path(candidate.file_name).stem.lower() == stem:
                return candidate

    return min(candidates, key=lambda candidate: candidate.file_id)


def identify_paths(
    client: NexusClient,
    paths: list[Path],
    cached: dict[str, str] | None = None,
    hints: dict[Path, int | None] | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[Path, HashMatch], dict[Path, str]]:
    """Hash the given archives and ask Nexus what they are.

    `cached` maps a cache key to a known digest, so unchanged files are not read
    again. Returns the matches and the digest of every file.
    """
    cached = cached or {}
    hints = hints or {}
    digests: dict[Path, str] = {}

    for index, path in enumerate(paths, start=1):
        if on_progress:
            on_progress(index, len(paths), path.name)
        try:
            key = cache_key(path)
        except OSError:
            continue
        digests[path] = cached.get(key) or file_md5(path)

    unique = sorted({digest for digest in digests.values()})
    if not unique:
        return {}, digests

    candidates = client.identify(unique)

    matches: dict[Path, HashMatch] = {}
    for path, digest in digests.items():
        chosen = best_match(candidates.get(digest, []), path.name, hints.get(path))
        if chosen:
            matches[path] = chosen
    return matches, digests
