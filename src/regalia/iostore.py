"""Read the asset paths out of an Unreal IoStore container.

A ".utoc" is the table of contents for the ".ucas" beside it, and it carries a
directory index listing every asset the container holds. That list is the only
honest answer to "what does this mod change". A file name is what the author
felt like typing; two archives called the same thing can touch different
costumes, and one archive can hold twenty-four containers that all claim the
same mesh.

The reader is pure Python on purpose. Every other tool that does this ships a
Rust extension or shells out to `repak`, which puts a build dependency between
the user and a feature that is, in the end, unpacking a struct. The layout is
documented in `.claude/skills/marvel-rivals-modding/references/utoc-format.md`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"-==--==--==--==-"
NONE_INDEX = 0xFFFFFFFF

# EIoContainerFlags. Only these two change how the file is read.
FLAG_ENCRYPTED = 0x02
FLAG_INDEXED = 0x08

# Versions that added an array between the chunk offsets and the blocks. Miss
# either one and the directory index is read from the wrong offset, which
# produces a plausible-looking length and then nonsense.
VERSION_PERFECT_HASH = 4
VERSION_PERFECT_HASH_OVERFLOW = 5

# "/Characters/1053/1053301/" — the character id repeats at the head of the skin
# id, and that repetition is what separates a real match from any other run of
# digits in a path.
CHARACTER_SKIN = re.compile(r"/characters/(\d{4})/(\d{4})(\d{3})(?=[/_.])")


class UnreadableContainer(Exception):
    """The container cannot be listed, with the reason in the message."""


@dataclass(frozen=True, slots=True)
class Container:
    """One IoStore container and the assets it claims."""

    path: Path
    mount: str
    assets: tuple[str, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        """The assets in the one spelling two containers can be compared in."""
        return tuple(normalise(asset, self.mount) for asset in self.assets)

    @property
    def skins(self) -> tuple[str, ...]:
        """Every costume id this container writes to, in first-seen order."""
        found: dict[str, None] = {}
        for asset in self.paths:
            for match in CHARACTER_SKIN.finditer(asset):
                # The two four-digit groups must agree, or the path is not the
                # character-and-costume shape it resembles.
                if match.group(1) == match.group(2):
                    found.setdefault(match.group(2) + match.group(3), None)
        return tuple(found)

    @property
    def characters(self) -> tuple[str, ...]:
        found: dict[str, None] = {}
        for skin in self.skins:
            found.setdefault(skin[:4], None)
        return tuple(found)


def read(path: Path) -> Container:
    """List the assets in one container. Raises `UnreadableContainer`."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise UnreadableContainer(str(error)) from error

    if len(data) < 152 or data[:16] != MAGIC:
        raise UnreadableContainer("not an IoStore container")

    version = data[16]
    (
        header_size,
        entry_count,
        block_count,
        block_entry_size,
        method_count,
        method_length,
        _block_size,
        index_size,
        _partitions,
    ) = struct.unpack_from("<9I", data, 20)
    flags = data[80]

    if flags & FLAG_ENCRYPTED:
        # The game's own containers are encrypted and need its AES key. Mod
        # containers from the community tools are not. Saying so beats guessing:
        # invented paths would flow into conflict detection and come back out as
        # confident nonsense.
        raise UnreadableContainer("directory index is encrypted")
    if not index_size or not flags & FLAG_INDEXED:
        raise UnreadableContainer("container carries no directory index")

    (hash_seed_count,) = struct.unpack_from("<I", data, 84)
    (no_hash_count,) = struct.unpack_from("<I", data, 96)

    # Chunk ids are 12 bytes and the offset-and-length pairs are 10.
    offset = header_size + entry_count * 22
    if version >= VERSION_PERFECT_HASH:
        offset += hash_seed_count * 4
    if version >= VERSION_PERFECT_HASH_OVERFLOW:
        offset += no_hash_count * 4
    offset += block_count * block_entry_size
    offset += method_count * method_length

    if offset + index_size > len(data):
        raise UnreadableContainer("directory index runs past the end of the file")

    mount, assets = _parse_index(data[offset : offset + index_size])
    return Container(path=path, mount=mount, assets=tuple(assets))


def read_or_none(path: Path) -> Container | None:
    """`read`, but a container that cannot be listed is simply absent."""
    try:
        return read(path)
    except UnreadableContainer:
        return None


def _parse_index(buffer: bytes) -> tuple[str, list[str]]:
    """Walk the directory tree and join the names into paths."""
    cursor = 0
    end = len(buffer)

    def take(fmt: str) -> tuple:
        nonlocal cursor
        size = struct.calcsize(fmt)
        if cursor + size > end:
            raise UnreadableContainer("directory index is truncated")
        value = struct.unpack_from(fmt, buffer, cursor)
        cursor += size
        return value

    (mount_length,) = take("<I")
    if cursor + mount_length > end:
        raise UnreadableContainer("directory index is truncated")
    mount = _decode(buffer[cursor : cursor + mount_length])
    cursor += mount_length

    (directory_count,) = take("<I")
    directories = [take("<4I") for _ in range(directory_count)]
    (file_count,) = take("<I")
    files = [take("<3I") for _ in range(file_count)]
    (string_count,) = take("<I")

    strings: list[str] = []
    for _ in range(string_count):
        (length,) = take("<I")
        if cursor + length > end:
            raise UnreadableContainer("directory index is truncated")
        strings.append(_decode(buffer[cursor : cursor + length]))
        cursor += length

    def name(index: int) -> str:
        if index == NONE_INDEX or index >= len(strings):
            raise UnreadableContainer("directory index names a missing string")
        return strings[index]

    paths: list[str] = []
    # An iterative walk with a seen set, so a container whose sibling chain
    # loops back on itself fails instead of hanging.
    seen: set[int] = set()
    stack: list[tuple[int, str]] = [(0, "")] if directories else []
    while stack:
        index, prefix = stack.pop()
        if index == NONE_INDEX or index >= len(directories) or index in seen:
            continue
        seen.add(index)
        name_index, first_child, next_sibling, first_file = directories[index]
        here = prefix if name_index == NONE_INDEX else f"{prefix}{name(name_index)}/"

        file_index = first_file
        visited_files: set[int] = set()
        while file_index != NONE_INDEX and file_index < len(files):
            if file_index in visited_files:
                break
            visited_files.add(file_index)
            file_name_index, next_file, _user_data = files[file_index]
            paths.append(here + name(file_name_index))
            file_index = next_file

        stack.append((next_sibling, prefix))
        stack.append((first_child, here))

    return mount, paths


def _decode(raw: bytes) -> str:
    """Strings are NUL-terminated and the length includes the terminator."""
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def normalise(asset: str, mount: str = "") -> str:
    """One spelling for one asset, so two containers can be compared.

    Containers hold the mount point apart from the paths, and the paths arrive
    with the "../../../" the cook wrote. Authors also disagree about case, and a
    case-sensitive comparison silently misses real conflicts.
    """
    joined = f"{mount}{asset}" if mount else asset
    joined = joined.replace("\\", "/")
    while joined.startswith("../"):
        joined = joined[3:]
    return "/" + joined.lstrip("/").lower()


def asset_set(container: Container) -> frozenset[str]:
    """The comparable asset paths of one container."""
    return frozenset(container.paths)
