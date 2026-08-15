"""Reading the "-slt" listing 7z prints.

Every field in a block is optional in practice. Archives written by DOS-era
tools carry no attribute bits, so 7z prints "Attributes = " and stops, and a
parser that assumes a value crashes before a single mod is read.
"""

from __future__ import annotations

from regalia.archive import _parse_slt

# 7z writes the key, the separator and then nothing. The trailing space is the
# whole point of these tests, so it is spelled out instead of left in a literal
# block where an editor would strip it.
NO_ATTRIBUTES = "Attributes = "

FAT_LISTING = "\n".join(
    [
        "Path = 341-0728",
        "Folder = -",
        "Size = 131072",
        NO_ATTRIBUTES,
        "CRC = 8D410067",
        "",
        "Path = 344s0047.bin",
        "Folder = -",
        "Size = 4096",
        NO_ATTRIBUTES,
        "CRC = 1A2B3C4D",
    ]
)

MIXED_LISTING = "\n".join(
    [
        "Path = skins",
        "Folder = +",
        "Size = 0",
        "Attributes = D_ drwxr-xr-x",
        "",
        "Path = skins/Magik_P.pak",
        "Folder = -",
        "Size = 4096",
        "Attributes = A_ -rw-r--r--",
    ]
)


def test_an_entry_without_attributes_is_read_as_a_file():
    entries = list(_parse_slt(FAT_LISTING))
    assert [entry.name for entry in entries] == ["341-0728", "344s0047.bin"]
    assert [entry.is_dir for entry in entries] == [False, False]
    assert entries[0].size == 131072


def test_the_directory_flag_still_comes_from_the_attributes():
    entries = list(_parse_slt(MIXED_LISTING))
    assert [entry.is_dir for entry in entries] == [True, False]
