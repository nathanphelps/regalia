# regalia — design

Date: 2026-08-14
Status: approved

## Purpose

`regalia` is a terminal wizard that installs Marvel Rivals mods from downloaded
archives. It extracts each archive once, keeps the files in a store directory, and
links them into the game. One person uses it on one machine.

## Scope

In scope:

- Scan folders for mod archives (`.7z`, `.zip`).
- Parse hero, variant, and version out of archive names.
- Install, uninstall, enable, and disable mods.
- Detect conflicts and superseded versions.
- Install the UTOC signature bypass patch.
- Report the Proton DLL override that the patch needs.

Out of scope:

- The Windows dual-boot copy of the game on `/mnt/sda2`.
- Downloads from Nexus or any other site.
- Tests. The owner does not want them.

## Environment

The tool targets one known machine.

| Item | Value |
|---|---|
| Game root | `~/.local/share/Steam/steamapps/common/MarvelRivals` |
| Steam app id | `2767030` |
| Paks directory | `<game root>/MarvelGame/Marvel/Content/Paks` |
| Mods directory | `<paks>/~mods` (the tool creates it) |
| Binaries | `<game root>/MarvelGame/Marvel/Binaries/Win64` |
| Proton prefix | `~/.local/share/Steam/steamapps/compatdata/2767030` |
| Filesystem | ext4 on `/dev/nvme0n1p3` |
| Archive tool | `/usr/bin/7z` |
| Python | 3.14, run through `uv` |

## Archive shapes

All 28 sample archives hold an Unreal IoStore mod. Each mod is a `.pak` file with
an optional `.ucas` and `.utoc` beside it. Three layouts occur:

1. Files at the archive root. Example: `Cyclops Slutty - Just Visor.zip`.
2. Files in one wrapper folder. Example: `SIT-MuscularLoki_.../*.pak`.
3. A `.pak` alone, with no `.ucas` or `.utoc`. Example: `Jarvis_Remove_His_Balls_9999999_P.pak`.

The signature bypass archive is different. It holds `dsound.dll` and
`plugins/*.asi`. The tool recognises it by content and treats it as the patch, not
as a mod.

Most mod files end with `_9999999_P`. Unreal loads `~mods` in alphabetical order,
and the `_P` suffix marks a patch pak. The high number forces the mod to load last,
so it overrides the base game. A mod without this suffix can lose. The tool shows a
warning for those mods.

## Architecture

### State locations

The tool separates disposable state from valuable state.

| Path | Holds |
|---|---|
| `~/.config/regalia/config.toml` | scan directories, game path override, theme |
| `~/.local/share/regalia/store/<slug>/` | extracted mod files |
| `~/.local/share/regalia/catalog.json` | known mods, install state, enable state |
| `<paks>/~mods/` | symlinks only |

The game directory holds no original data. A game update can delete `~mods`. The
tool then relinks the files from the store.

### Modules

`paths.py`
: Reads `~/.local/share/Steam/steamapps/libraryfolders.vdf`. Selects the library
whose `apps` block lists app `2767030`. Derives the Paks, mods, binaries, and
prefix paths. A config value overrides the result. The tool never searches the disk
for a folder named `MarvelRivals`, because that search can find the dual-boot copy.

`heroes.py`
: A table of Marvel Rivals hero names with aliases. Maps `CaptAmerica` to
`Captain America` and `MrFantastic` to `Mister Fantastic`.

`naming.py`
: Turns a file name into a hero, a variant, and a version. The steps are:
1. Remove the Nexus tail. It matches `-\d+(-\d+){2,}-\d{10}$`.
2. Read and remove a version token such as `V1.2.0`.
3. Remove known noise words such as `Muscular`, `SIT-`, and `VLQ`.
4. Match the longest hero alias in the remaining text.
5. Keep the rest as the variant.
If no hero matches, the hero is `Unknown` and the variant is the whole name. The
tool does not guess.

`archive.py`
: Lists and extracts archives through `7z`. Extraction reports progress from the
`-bsp1` output. Extraction moves a single wrapper folder's contents up one level.

`model.py`
: The `Mod` record. Fields: slug, hero, variant, version, nexus id, source archive,
store path, file names, state, and load-order flag.

`catalog.py`
: Scans the configured directories, builds `Mod` records, and saves them to
`catalog.json`. The Nexus id is the identity key, so two versions of the same mod
group together.

`installer.py`
: Extracts an archive to the store, creates the `~mods` symlinks, and records the
result. Uninstall removes the links and the store directory. Disable removes only
the links.

`conflicts.py`
: Reports three conditions:
1. Two installed mods claim the same hero.
2. A newer version of an installed mod sits in the library.
3. A mod lacks the `_9999999_P` load-order suffix.

`patch.py`
: Detects, installs, and verifies the UTOC signature bypass. See below.

`app.py` and `app.tcss`
: The Textual interface.

## Interface

Four tabs: LIBRARY, INSTALLED, PATCH, LOG.

```
┌ REGALIA ─────────────────────────── ● patch ok ── 12/28 installed ┐
│  LIBRARY   INSTALLED   PATCH   LOG                                  │
├─────────────────────────────────────────────────────────────────────┤
│  search ▏muscular                                                   │
├───┬──────────────┬────────────────────┬─────────┬────────┬──────────┤
│ ☑ │ Wolverine    │ Default · Aroused  │ v1.0.0  │  16 MB │ INSTALLED│
│ ☐ │ Loki         │ Default · Helmet   │ v1.0.1  │  34 MB │ ⚠ newer  │
│ ☑ │ Moon Knight  │ Blood Moon         │ v1.1.0  │  17 MB │ DISABLED │
├───┴──────────────┴────────────────────┴─────────┴────────┴──────────┤
│  SIT-MuscularWolverine…_9999999_P.{pak,ucas,utoc}                   │
│  ⚠ also modifies Wolverine — conflicts with 1 other selected mod    │
├─────────────────────────────────────────────────────────────────────┤
│  ████████████████░░░░░░░░  extracting Loki  62%                     │
└ space pick · i install · d disable · x remove · r rescan · q quit ──┘
```

Keys: `space` selects, `i` installs, `d` disables, `x` removes, `r` rescans,
`/` focuses search, `q` quits.

Installation runs in a Textual worker thread. The progress bar follows the
percentage that `7z` prints.

### Theme

The palette follows the owner's design taste.

| Role | Light (default) | Dark (`--dark`) |
|---|---|---|
| Ground | `#ece8dc` | `#1a1a1a` |
| Ink | `#1a1a1a` | `#ece8dc` |
| Accent | `#6c6ce0` | `#8f92e8` |
| Muted | `#8a8578` | `#6f6a5e` |

Borders are square and heavy. No rounded corners. Section labels use letter-spaced
capitals. A terminal has one typeface, so hierarchy comes from weight, spacing, and
colour.

## The signature bypass patch

No mod loads without this patch. The PATCH tab does three things.

1. **Detect.** It checks for `dsound.dll` and `plugins/*.asi` in `Binaries/Win64`.
2. **Install.** It finds the bypass archive in the scan directories and extracts
   `dsound.dll` and the `plugins` folder into `Binaries/Win64`.
3. **Verify the Proton override.** Ultimate ASI Loader loads through a fake
   `dsound.dll`. Wine ignores that file unless the launch options set an override.
   The tool reads `~/.local/share/Steam/userdata/*/config/localconfig.vdf`, finds
   the launch options for app `2767030`, and shows the required string:

   ```
   WINEDLLOVERRIDES="dsound=n,b" %command%
   ```

   Reading this file needs care. The app id also appears inside binary licence
   data ahead of the `apps` section, so the search must begin at that section.
   The value escapes its own quotes as `\"`, so a pattern that stops at the
   first quote reads only a fragment of it.

   The tool can also write this value. The rules that make the write safe are in
   the Nexus integration design, under "Steam launch options".

## Error handling

| Case | Behaviour |
|---|---|
| Game not found | The Settings screen opens first and asks for a path |
| `7z` missing | The tool stops at startup and prints the install command |
| Archive holds no `.pak` | The mod shows `UNSUPPORTED`; the reason goes to the LOG tab |
| Link target exists | A modal asks: overwrite, skip, or cancel |
| `~mods` deleted by a game update | The catalog finds the missing links and offers Repair |
| Extraction fails | The tool deletes the partial store folder; the mod stays `AVAILABLE` |

## Decisions and reasons

- **Symlinks, not copies.** Enable and disable cost no time and no disk space. The
  game reads symlinks through Wine, because Wine opens files with normal system
  calls.
- **Shell out to `7z`.** It handles `.7z` and `.zip`, it prints progress, and it is
  already installed. A Python library would add a dependency and give less.
- **The Nexus id is the identity.** File names change between versions, but the id
  in the Nexus tail does not.
- **No tests.** The owner asked for none. Safety comes from the layout instead: the
  game folder holds only links, so the worst failure is a broken link.
