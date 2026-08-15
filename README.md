# Regalia

**A Marvel Rivals mod manager for Linux.** Install cosmetic mods from a folder
or straight from Nexus Mods, with a native desktop application and a terminal
one.

Regalia extracts each archive once into a store directory, then links the files
into the game. The game folder holds only symlinks, so a game update cannot lose
anything, and enabling or disabling a mod costs no disk space.

> **Read this first.** Marvel Rivals is an online game with anti-cheat. NetEase
> does not support mods, and using them may break the game or put your account
> at risk. This project is not affiliated with NetEase, Marvel, Valve, or Nexus
> Mods. You take on that risk yourself.

## Requirements

- Linux, with the game installed through Steam and Proton
- Python 3.12 or newer
- A Nexus Mods account, only if you want search, downloads, or collections

Nothing else. Regalia extracts archives with `7z` when it is on the path, and
falls back to a pure-Python reader when it is not, so a Steam Deck or an
immutable distribution needs no extra package.

### Supported environments

Regalia finds Steam wherever this machine keeps it.

| Steam | Where it looks |
|---|---|
| native | `$XDG_DATA_HOME/Steam`, `~/.steam/steam`, `~/.steam/root` |
| Debian package | `~/.steam/debian-installation` |
| Flatpak | `~/.var/app/com.valvesoftware.Steam/data/Steam` |
| Snap | `~/snap/steam/common/.local/share/Steam` |

It also uses the right command for each: `steam -shutdown` for a native
install, `flatpak run com.valvesoftware.Steam -shutdown` for a Flatpak, and so
on. Where no such command exists, Regalia asks you to close Steam instead of
writing while it runs.

Run `regalia doctor` to see what your machine reports.

## Install

```bash
uv tool install git+https://github.com/nathanphelps/regalia
```

The desktop application is the default install. Add the terminal one if you
want it:

```bash
uv tool install 'regalia[tui] @ git+https://github.com/nathanphelps/regalia'
```

The command above tracks the main branch. To pin a published version instead,
take the wheel from a
[release](https://github.com/nathanphelps/regalia/releases):

```bash
uv tool install https://github.com/nathanphelps/regalia/releases/download/v0.2.0/regalia-0.2.0-py3-none-any.whl
```

Or work on it in place:

```bash
git clone https://github.com/nathanphelps/regalia
cd regalia
uv sync --extra tui
uv run regalia
```

## Run it

```bash
regalia                    # the desktop application
regalia tui                # the terminal application
regalia doctor             # check this machine and report what to fix
regalia status             # print the current state
```

Both interfaces drive the same store, catalog, and game folder. Use whichever
one suits the moment.

| Command | Does |
|---|---|
| `regalia` | open the desktop application |
| `regalia tui` | open the terminal application |
| `regalia doctor` | report every check and how to fix what fails |
| `regalia status` | print the game path, scan folders, and handler |
| `regalia register-nxm` | handle `nxm://` links from the browser |
| `regalia unregister-nxm` | stop, and give the scheme back |
| `regalia install-desktop-entry` | add Regalia to the applications menu |
| `regalia clean` | list unfinished downloads (`-y` to delete) |

Options that apply to any of them: `--dark` / `--light`, `--game-root DIR`,
`--steam-root DIR`, `--scan DIR` (repeatable), and `--save` to write the current
options to the config file.

## First run

Regalia opens a **Setup** page when it cannot work yet. It asks for the three
things it cannot guess — where the game is, where downloads land, and your Nexus
key — and then lists every check with the fix beside it.

`regalia doctor` prints the same checks in the terminal, with version and
distribution details. That is the output to paste into a bug report.

## Install the patch first

Marvel Rivals refuses unsigned pak files. No mod loads until a signature bypass
is in place. Regalia does not ship one — it installs the archive you supply, and
checks the three conditions the bypass needs.

Open the PATCH screen and follow all three checks. The third one is easy to miss
under Proton: Wine ignores the bypass loader unless the Steam launch options say

```
WINEDLLOVERRIDES="dsound=n,b" %command%
```

Regalia reads the Steam config to check this, and can set it for you. See
[Steam launch options](#steam-launch-options).

## Keys in the terminal interface

| Key | Action |
|---|---|
| `space` | pick a mod (actions apply to all picked mods) |
| `i` | install |
| `d` | disable — remove the links, keep the files |
| `e` | enable |
| `x` | remove — delete the extracted files as well |
| `r` | rescan the folders |
| `c` | delete downloads that never finished |
| `n` | ask Nexus what every archive is |
| `u` | check Nexus for newer versions |
| `/` | search |
| `q` | quit |

With nothing picked, an action applies to the row under the cursor.

## Nexus Mods

Get a personal key at <https://next.nexusmods.com/settings/api-keys> and paste
it into the setup page or the NEXUS tab. It is stored at
`~/.config/regalia/credentials.toml`, mode 0600, and never printed. Set
`NEXUS_API_KEY` instead if you would rather keep it out of a file; the
environment wins over the file.

Search and identification work without a key. Downloads need one, and a direct
download needs Premium.

`n` hashes every archive and asks Nexus what it is. The answer replaces guessed
names with the real mod name, version, author, and id, and marks the row `✓`.
`u` then reports which of those mods have a newer file.

### Collections

The COLLECTIONS tab lists curated packs. Select one, press **Load manifest** to
see what it holds, then **Install**. Anything already in the store is skipped,
so overlapping collections only cost the difference. Members install and switch
on by themselves once the downloads finish, because a pack is meant to be played
as a whole.

Conflict warnings are suppressed between members of the same collection, since a
curator picks overlapping mods on purpose. A mod outside the pack that touches
the same hero still raises one.

Regalia fetches exactly the files the manifest names. It does not substitute a
newer file, because one mod page usually holds many unrelated files rather than
a chain of versions, and swapping would discard what the curator tested. Newer
files still show up in the update check.

### Detail screens

Press `enter` on any row.

- On a library or Nexus row it opens the mod: author, counts, and every file it
  offers. Variants live at the file level, so this is where you pick one. The
  file you already hold is marked `✓`; choosing another swaps them, because both
  claim the same hero slot.
- On a collection it opens the full member list: every mod, file, version and
  size, and whether you already hold it. `space` picks an optional member. `i`
  installs the selection.

`esc` goes back. Keys the library uses do nothing on these screens.

### One-click downloads from the browser

Run `regalia register-nxm`. After that, "Mod Manager Download" on the Nexus site
sends the file straight into your scan folder, and a running interface notices
and rescans. `regalia unregister-nxm` gives the scheme back to whichever program
held it before.

### Steam launch options

The PATCH screen can set the DLL override for you. It closes Steam first,
because Steam rewrites its settings on exit and would undo the change. Your
existing launch options are kept: the override is folded into what is already
there. The file is backed up to `~/.local/share/regalia/backups/` and the change
is read back before it counts as done. If Steam will not close, nothing is
written.

Regalia edits the first Steam account that owns the game, and reports which one
it used. A machine with two accounts that both own it has no way to know which
you mean, so check the account id the PATCH screen shows.

## Heroes the tool does not know yet

The game adds a hero every season. An unknown hero parses as `Unknown`, which
also loses its conflict warnings. Rather than wait for a release, name it
yourself in `~/.config/regalia/heroes.toml`:

```toml
[heroes]
Ultron = ["ultron", "vision"]
Hulk = ["banner"]              # adds to the built-in aliases, does not replace
```

A new key adds a hero. An existing key unions its aliases with the built-in
ones. `regalia doctor` reports how many the overlay adds.

## Where things live

| Path | Holds |
|---|---|
| `~/.config/regalia/config.toml` | scan folders, game path, theme |
| `~/.config/regalia/credentials.toml` | the Nexus key, mode 0600 |
| `~/.config/regalia/heroes.toml` | your extra heroes and aliases |
| `~/.local/share/regalia/store/` | extracted mod files |
| `~/.local/share/regalia/catalog.json` | known mods and their state |
| `~/.local/share/regalia/backups/` | Steam config backups |
| `~/.cache/regalia/images/` | Nexus artwork |
| `<game>/…/Content/Paks/~mods/` | symlinks only |

All three follow the XDG base directory variables when you set them.

| Variable | Effect |
|---|---|
| `NEXUS_API_KEY` | use this key instead of the file |
| `REGALIA_EXTRACTOR` | force `7z` or `python` |
| `REGALIA_SHOT_DIR` | where `shot.py` writes screenshots |

## Warnings in the table

| Mark | Meaning |
|---|---|
| `⚠` | another installed mod changes the same hero |
| `↑` | a newer version of this mod sits in the library |
| `!` | the mod lacks the `_9999999_P` suffix and may not override the base game |

## Upgrading from rivalmods

This project was called rivalmods. The first run under the new name moves
`~/.config/rivalmods`, `~/.local/share/rivalmods` and `~/.cache/rivalmods` to
their new places, repoints every symlink in the game folder at the renamed
store, and rewrites the desktop entries. Nothing is lost and nothing needs
reinstalling.

## Development

```bash
uv sync --extra tui
uv run --extra tui python -m pytest
uvx ruff check .
uvx ruff format --check .
```

`shot.py` boots the terminal app without a terminal and writes a screenshot.
Pass `--demo` to build a throwaway game tree, so that install states can be
pictured without touching the real one.

```bash
REGALIA_SHOT_DIR=shots uv run --extra tui python shot.py --demo --tab=patch --dark
```

The design notes are in [`docs/design/`](docs/design/). Read
[CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request.

## License

MIT — see [LICENSE](LICENSE).
