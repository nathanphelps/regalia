"""The IoStore reader.

The containers are built here rather than committed as fixtures. A binary blob
in the repository proves the parser still does what it did; a builder proves it
reads the format, and it can be bent into the malformed shapes a real library
eventually produces.
"""

from __future__ import annotations

import struct

import pytest

from regalia import iostore

NONE = 0xFFFFFFFF


def build_index(mount: str, tree: dict[str, list[str]]) -> bytes:
    """Lay out a directory index for one level of folders under the root."""
    strings: list[str] = []

    def intern(value: str) -> int:
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    # Root, then one directory per folder, chained as siblings.
    directories: list[tuple[int, int, int, int]] = []
    files: list[tuple[int, int, int]] = []

    folders = list(tree)
    root_child = 1 if folders else NONE
    directories.append((NONE, root_child, NONE, NONE))

    for position, folder in enumerate(folders):
        first_file = len(files)
        names = tree[folder]
        for offset, name in enumerate(names):
            following = first_file + offset + 1
            files.append(
                (intern(name), following if offset + 1 < len(names) else NONE, 0)
            )
        sibling = position + 2 if position + 2 <= len(folders) else NONE
        directories.append(
            (intern(folder), NONE, sibling, first_file if names else NONE)
        )

    out = bytearray()
    encoded = mount.encode() + b"\0"
    out += struct.pack("<I", len(encoded)) + encoded
    out += struct.pack("<I", len(directories))
    for entry in directories:
        out += struct.pack("<4I", *entry)
    out += struct.pack("<I", len(files))
    for entry in files:
        out += struct.pack("<3I", *entry)
    out += struct.pack("<I", len(strings))
    for value in strings:
        raw = value.encode() + b"\0"
        out += struct.pack("<I", len(raw)) + raw
    return bytes(out)


def build_container(
    index: bytes,
    *,
    version: int = 5,
    entry_count: int = 2,
    flags: int = iostore.FLAG_INDEXED,
    hash_seeds: int = 0,
    without_hash: int = 0,
) -> bytes:
    header = bytearray(144)
    header[0:16] = iostore.MAGIC
    header[16] = version
    struct.pack_into(
        "<9I",
        header,
        20,
        144,  # header size
        entry_count,
        0,  # compressed block count
        12,  # compressed block entry size
        0,  # compression method count
        32,  # compression method length
        0x10000,
        len(index),
        1,
    )
    header[80] = flags
    struct.pack_into("<I", header, 84, hash_seeds)
    struct.pack_into("<I", header, 96, without_hash)

    body = bytearray()
    body += b"\0" * (entry_count * 12)  # chunk ids
    body += b"\0" * (entry_count * 10)  # offsets and lengths
    body += b"\0" * (hash_seeds * 4)
    body += b"\0" * (without_hash * 4)
    body += index
    body += b"\0" * (entry_count * 33)  # chunk metas
    # The sections follow the header directly. Real containers put nothing
    # between them, which is why the reader measures from the header size.
    return bytes(header) + bytes(body)


def write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_asset_paths_are_read_from_the_directory_index(tmp_path):
    index = build_index(
        "../../../",
        {
            "Marvel/Content/Marvel/Characters/1053/1053301/Meshes": [
                "SK_1053_1053301.uasset"
            ]
        },
    )
    container = iostore.read(write(tmp_path, "a.utoc", build_container(index)))

    assert container.mount == "../../../"
    assert container.assets == (
        "Marvel/Content/Marvel/Characters/1053/1053301/Meshes/SK_1053_1053301.uasset",
    )


def test_a_path_is_normalised_so_two_containers_compare(tmp_path):
    # The prefix the cook wrote and the author's casing must not make two
    # spellings of one asset, or a real conflict goes unreported.
    assert iostore.normalise("Marvel/Content/A.uasset", "../../../") == (
        "/marvel/content/a.uasset"
    )
    assert iostore.normalise("\\Marvel\\B.uasset") == "/marvel/b.uasset"


def test_the_costume_is_read_out_of_the_path(tmp_path):
    index = build_index(
        "../../../",
        {
            "Marvel/Content/Marvel/Characters/1046/1046001/Textures": ["T_a.uasset"],
            "Marvel/Content/Marvel/Characters/1046/1046300/Meshes": ["SK_b.uasset"],
        },
    )
    container = iostore.read(write(tmp_path, "b.utoc", build_container(index)))

    assert sorted(container.skins) == ["1046001", "1046300"]
    assert container.characters == ("1046",)


def test_a_run_of_digits_that_is_not_a_costume_is_ignored(tmp_path):
    # The two four-digit groups have to agree. "1046/2222333" is not this
    # character's costume, whatever it looks like.
    index = build_index("", {"Marvel/Characters/1046/2222333/Meshes": ["SK_c.uasset"]})
    container = iostore.read(write(tmp_path, "c.utoc", build_container(index)))

    assert container.skins == ()


def test_versions_before_the_hash_arrays_skip_them(tmp_path):
    # A version 3 container has no perfect-hash arrays, so the counts in the
    # header must not move the directory index.
    index = build_index("", {"Content": ["one.uasset"]})
    data = build_container(index, version=3, hash_seeds=7, without_hash=9)
    # Rebuild without the arrays the older version does not carry.
    header, rest = data[:144], data[144:]
    rest = rest[: 2 * 12 + 2 * 10] + rest[2 * 12 + 2 * 10 + 7 * 4 + 9 * 4 :]

    container = iostore.read(write(tmp_path, "d.utoc", header + rest))
    assert container.assets == ("Content/one.uasset",)


def test_an_encrypted_index_is_refused_rather_than_guessed(tmp_path):
    index = build_index("", {"Content": ["one.uasset"]})
    data = build_container(index, flags=iostore.FLAG_INDEXED | iostore.FLAG_ENCRYPTED)

    with pytest.raises(iostore.UnreadableContainer, match="encrypted"):
        iostore.read(write(tmp_path, "e.utoc", data))


def test_a_file_that_is_not_a_container_is_refused(tmp_path):
    with pytest.raises(iostore.UnreadableContainer, match="not an IoStore"):
        iostore.read(write(tmp_path, "f.utoc", b"nonsense" * 40))


def test_a_truncated_index_fails_instead_of_reading_past_the_end(tmp_path):
    index = build_index("", {"Content": ["one.uasset"]})
    data = bytearray(build_container(index))
    # Claim an index far larger than the file holds.
    struct.pack_into("<I", data, 20 + 7 * 4, 1_000_000)

    with pytest.raises(iostore.UnreadableContainer, match="past the end"):
        iostore.read(write(tmp_path, "g.utoc", bytes(data)))


def test_read_or_none_turns_a_refusal_into_an_absence(tmp_path):
    assert iostore.read_or_none(write(tmp_path, "h.utoc", b"nope")) is None
