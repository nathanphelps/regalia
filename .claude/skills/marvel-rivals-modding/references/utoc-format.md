# Reading a .utoc directory index

A `.utoc` is the table of contents for a `.ucas` blob. It carries a directory
index that lists every asset path in the container. That index is plain data, so
a pure-Python reader is about a hundred lines and needs no external tool — which
matters, because the alternative is shipping a Rust extension or shelling out to
`repak`, and both put a build dependency between the user and a feature that is
just parsing a struct.

All values are little-endian.

## Header, 144 bytes

| Offset | Size | Field |
|---|---|---|
| 0 | 16 | Magic, `-==--==--==--==-` |
| 16 | 1 | Version |
| 17 | 3 | Padding |
| 20 | 4 | Header size, 144 |
| 24 | 4 | Entry count |
| 28 | 4 | Compressed block count |
| 32 | 4 | Compressed block entry size, 12 |
| 36 | 4 | Compression method name count |
| 40 | 4 | Compression method name length, 32 |
| 44 | 4 | Compression block size, 0x10000 |
| 48 | 4 | **Directory index size** |
| 52 | 4 | Partition count |
| 56 | 8 | Container ID |
| 64 | 16 | Encryption key GUID |
| 80 | 1 | **Container flags** |
| 81 | 3 | Padding |
| 84 | 60 | Padding |

Byte 144 begins an `int64` TOC file size.

## Sections, in order from offset 152

1. Chunk IDs — 12 bytes each, entry count of them
2. Offsets and lengths — 10 bytes each, entry count of them
3. Compression blocks — 12 bytes each, compressed block count of them
4. Compression method names — 32 bytes each
5. **Directory index** — directory index size bytes
6. Chunk metas — 33 bytes each

Only section 5 matters for listing paths. Compute its start by summing the four
sections before it; do not scan for it.

## Directory index

```
uint32   mount point length, including the NUL
bytes    mount point, UTF-8, NUL-terminated
uint32   directory entry count
         directory entries, 16 bytes each:
             uint32 name index
             uint32 first child index
             uint32 next sibling index
             uint32 first file index
uint32   file entry count
         file entries, 12 bytes each:
             uint32 name index
             uint32 next file index
             uint32 user data
uint32   string count
         strings, each: uint32 length including NUL, then the bytes
```

`0xFFFFFFFF` is the null index. Walk from directory 0, following `first child`
and `next sibling`, and at each directory follow `first file` and `next file`.
Join the names from the string table. Prepend the mount point to get the path
the game sees.

Recursion depth follows the archive's folder nesting, which is shallow in
practice, but an iterative walk with a visited set costs nothing and makes a
corrupt file fail instead of hang.

## The encryption caveat

Bit 2 of the container flags marks an encrypted directory index. The base game's
own containers are encrypted and need the game's AES key. Mod containers built
with the usual community tools are not encrypted, so a reader that handles the
unencrypted case covers every mod a user installs and correctly declines the
game's own paks.

Detect it and return "unknown" rather than guessing. A parser that returns
garbage paths for an encrypted container is worse than one that admits it cannot
read it, because the garbage flows into conflict detection and produces
confident nonsense.

## Sanity checks worth keeping

A malformed or truncated file should fail fast, not allocate wildly:

- Magic must match.
- Directory index size must fit inside the file.
- String count, directory count and file count must each fit in the remaining
  bytes of the index.
- Every name index must be inside the string table.

## The classic .pak sibling

For UE5 IoStore mods the `.pak` beside the `.utoc` is usually an almost empty
container that exists so the game notices the set. The asset list lives in the
`.utoc`. If a mod ships only a `.pak`, it is a legacy-format mod and its own
index holds the paths; that is a different parser and is worth adding only if
such mods actually appear in the library.
