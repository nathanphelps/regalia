# Regalia

**A Marvel Rivals mod manager for Linux.** Install cosmetic mods from a folder
or straight from Nexus Mods, with a native desktop application and a terminal
one.

Regalia extracts each archive once into a store directory, then links the files
into the game. The game folder holds only symlinks, so a game update cannot lose
anything, and enabling or disabling a mod costs no disk space.

One archive is not always one mod. A single download can hold two dozen pak
sets — a body-size ladder, a physics add-on, an outfit with and without a cape —
and the author expects you to run one or two of them. Regalia reads the asset
paths inside each container and works out which of them overwrite each other, so
it installs the choice rather than all of it.

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
| `regalia import DIR` | copy archives into the library (`--move` to move) |
| `regalia profile` | `list`, `save NAME`, `apply NAME`, `delete NAME` |
| `regalia reset` | list what a reset would remove (`--yes` to do it) |

Options that apply to any of them: `--dark` / `--light`, `--game-root DIR`,
`--steam-root DIR`, `--scan DIR` (repeatable), and `--save` to write the current
options to the config file.

## First run

Regalia opens a **Setup** page when it cannot work yet. It asks for the two
things it cannot guess — where the game is, and your Nexus key — and then lists
every check with the fix beside it.

Downloads land in a library Regalia owns, at
`~/.local/share/regalia/library`. If you already have a folder of archives,
bring them in:

```bash
regalia import ~/Downloads/Rivals          # copy them
regalia import ~/Downloads/Rivals --move   # or move them
```

Setup has a button for the same thing. A download folder makes a poor library:
everything the browser saves lands there, the desktop offers to empty it, and a
mod is remembered by its archive path, so a file that moves takes its record
with it.

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
| `p` | choose which parts of a mod run |
| `f` | profiles — save or switch a whole set of mods |
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

The game adds a hero every season, and mod authors name files freely —
`PANTS-4245-1-0.7z` says nothing about who it is for.

Regalia reads the character id out of the pak and learns which hero it belongs
to from mods it managed to name some other way, so most nameless archives sort
themselves out. A character it has never seen shows as `Character 1037`, which
still groups those mods together and warns about them properly.

To give that character a name, or to add a hero ahead of a release, use
`~/.config/regalia/heroes.toml`:

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
| `~/.config/regalia/config.toml` | game path, extra watch folders, theme |
| `~/.config/regalia/credentials.toml` | the Nexus key, mode 0600 |
| `~/.config/regalia/heroes.toml` | your extra heroes and aliases |
| `~/.local/share/regalia/library/` | the archives Regalia owns; downloads land here |
| `~/.local/share/regalia/store/` | extracted mod files, in the archive's own folders |
| `~/.local/share/regalia/catalog.json` | known mods and their state |
| `~/.local/share/regalia/profiles.json` | saved sets of mods |
| `~/.local/share/regalia/characters.json` | character ids the tool has learned |
| `~/.local/share/regalia/backups/` | Steam config backups |
| `~/.cache/regalia/images/` | Nexus artwork |
| `<game>/…/Content/Paks/~mods/` | symlinks only |

All three follow the XDG base directory variables when you set them.

| Variable | Effect |
|---|---|
| `NEXUS_API_KEY` | use this key instead of the file |
| `REGALIA_EXTRACTOR` | force `7z` or `python` |
| `REGALIA_SHOT_DIR` | where `shot.py` writes screenshots |

## Parts of a mod

Most archives hold one pak set and behave like a single mod. Some hold many,
because the author offered choices in one download — five body sizes, an outfit
with and without a cape, a physics add-on meant to run alongside.

Regalia reads each container's asset list and groups the parts that write the
same asset. Parts in one group overwrite each other, so only one of them can
run; anything in a group of its own runs alongside the rest. Installing picks
one part per group.

Press `p` in the terminal, or use the **Parts of this mod** list in the desktop
detail pane, to change the choice. Switching a part on switches off whatever it
would have overwritten, and says so.

When a container cannot be read — an encrypted one, or a format the reader does
not know — Regalia falls back to the folder layout, treats neighbours as
alternatives, and marks the guess as a guess.

## Profiles

A profile is a named set of mods, switched in one step: a light set for
competitive play, a full set otherwise.

```bash
regalia profile save "raid night"
regalia profile list
regalia profile apply "raid night"
```

It records which parts of each mod ran, not only which mods, so a body size
chosen out of a twenty-four part archive comes back the way you left it.
Switching is a diff — mods in both sets keep their links, and mods the profile
drops are unlinked but keep their extracted files, so switching back needs no
extraction.

There is a profile bar above the desktop library, and `f` in the terminal.

## Starting over

`regalia reset` lists exactly what it would remove and does nothing else until
you add `--yes`:

| Scope | Removes |
|---|---|
| `links` | the symlinks in the game's `~mods` folder |
| `store` | the extracted mod files |
| `catalog` | the mod list and the hash cache |
| `cache` | downloaded artwork |
| `credentials` | the saved Nexus API key |
| `config` | the settings file |
| `library` | the archives Regalia imported |
| `all` | everything above **except** the library |

`all` leaves the library alone on purpose: re-downloading a large collection is
the one cost that cannot be undone cheaply. Name `library` explicitly if you
mean it.

The desktop has the same thing under **Start over** in Settings, and each button
lists what it would remove before it removes anything.

## Warnings in the table

| Mark | Meaning |
|---|---|
| `⚠` | another installed mod writes the same asset — only one of them wins |
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
