# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Regalia is a Marvel Rivals mod manager for Linux. One domain core serves two
interfaces: a Qt desktop application and a Textual terminal application.

## Commands

```bash
uv sync --extra tui              # set up; the tui extra is optional
uv run regalia                   # the desktop application
uv run regalia tui               # the terminal application
uv run regalia doctor            # every environment check, with the fix for each
uv run regalia status            # the current state, one line per fact
uv run regalia import ~/Downloads   # bring existing archives into the library
uv run regalia reset             # list what a reset would remove; --yes does it

# Always `python -m pytest`. A stray pytest on the PATH otherwise wins, and it
# runs against the wrong interpreter.
uv run --extra tui python -m pytest
uv run --extra tui python -m pytest tests/test_naming.py::test_a_version_is_read_and_removed
uvx ruff check .                 # lint
uvx ruff format --check .        # format check
uv build                         # the wheel and the source archive

uv run --extra tui python shot.py --dark --tab=patch --demo   # terminal screenshots
```

`shot.py` boots the terminal application headless and writes an SVG, then calls
Inkscape for a PNG. `--demo` builds a throwaway game tree, so a screenshot never
touches the real installation.

CI runs the lint, the format check, the tests, and the build. All four must pass.

## Architecture

### The layer rule

`archive`, `catalog`, `components`, `conflicts`, `environment`, `heroes`,
`installer`, `iostore`, `library`, `maintenance`, `naming`, `nexus`, `patch`,
`paths`, `readiness`, `steam` and `variants` are the domain. They import no Qt
and no Textual. Both interfaces are consumers of the same objects. Put logic in
the domain, never in a page or a screen, or the two interfaces drift apart.

- `src/regalia/gui/` — the Qt application. `pages.py` holds the pages,
  `tasks.py` runs every slow call on a `QThreadPool` and reports it as an
  `Activity`.
- `src/regalia/app.py` — the Textual application. The same slow calls run under
  `@work(thread=True)`.
- `src/regalia/cli.py` — the entry point for both, plus `doctor`, `status`, the
  `nxm://` handler and the desktop entry commands.

### Archive, component, deployment

Three layers, named apart on purpose. An **archive** is the file the user
downloaded. A **component** is one pak set inside it — a `.pak` with its `.ucas`
and `.utoc` — and it is the smallest thing the game loads and the smallest thing
the user can switch on. A `Mod` is the archive plus what is known about it.

Most archives hold one component. Some hold twenty-four, because the author
offered a body-size ladder and a physics add-on in one download, and expects two
of them to run. An earlier version linked every pak file it found, which handed
Unreal ten claims on one mesh and let it pick one at random.

`components.overlap()` decides what may run together, and it derives the answer
rather than guessing it: two components collide when they write the same asset
path. `iostore` reads those paths out of the `.utoc` directory index in pure
Python — no Rust extension, no `repak` — and refuses an encrypted container
rather than inventing paths for it. When a container cannot be read the rule
falls back to "siblings in one folder are alternatives" and says so.

The same rule powers `conflicts`. Two mods clash when they write the same asset,
never because they touch the same hero: a hero has many costumes, and forty mods
covering forty costumes is a healthy library that a hero-level check would
condemn wholesale.

### The library, and why it is not the downloads folder

`library` owns `~/.local/share/regalia/library`. Downloads land there and it is
always scanned, whatever `scan_dirs` says. A downloads folder was the old default
and it was a bad one: everything the browser saves arrives in the mod list, the
desktop offers to empty it, a repeat download becomes "mod (1).zip", and because
a mod is keyed by its archive path a file that moves takes its record with it.
`catalog` now also keeps an installed mod whose archive has gone, so the store
and the links always have an owner.

### The store, and why the game folder holds only symlinks

`installer` extracts each archive once into `~/.local/share/regalia/store/<slug>`
and links the files into the game `~mods` folder. The game folder therefore holds
no real file. A game update can delete every link and lose nothing, and
`installer.repair()` puts them back.

Never copy a mod file into the game folder. That one change breaks the guarantee
the whole design exists for.

### State on disk

| Path | Holds |
|---|---|
| `~/.config/regalia/config.toml` | the game root, the Steam root, the scan folders, the theme |
| `~/.config/regalia/credentials.toml` | the Nexus API key, mode 0600 |
| `~/.local/share/regalia/catalog.json` | every known mod, its state, and the MD5 cache |
| `~/.local/share/regalia/library/` | the archives the tool owns; downloads land here |
| `~/.local/share/regalia/store/` | the extracted mod files, in the archive's own folder tree |
| `~/.cache/regalia/images/` | Nexus artwork; a cleaner may delete it |

`catalog.Catalog.rescan()` rebuilds the list from the library and the scan
folders on every run.
It keys carried-over records by archive path, not by slug, because two archives
can produce the same slug. `verify()` then compares the record against the game
folder and marks a mod `BROKEN` when its links are gone.

### The signature bypass

Marvel Rivals rejects unsigned pak files. No mod loads without the ASI plugin,
which Ultimate ASI Loader loads under the name `dsound.dll`. Wine only loads it
when the Steam launch options carry `WINEDLLOVERRIDES="dsound=n,b" %command%`.
`patch` installs the files and `steam` writes that option into `localconfig.vdf`,
which means Steam has to be closed first. Treat a missing override as a blocking
problem, not a warning.

### Readiness: one model, three presentations

`readiness.run_checks()` returns the whole picture. The `doctor` command prints
it, the desktop application walks a new user through it, and the terminal
application shows it on a first run. A `Check` is `essential` when the tool
cannot install a mod without it. `Report.needs_setup` opens the setup flow only
when a first run finds an essential check unsettled, so a machine where detection
already found everything sees no introduction.

### The host, in one module

`environment` owns every fact about the machine: the XDG directories, the four
Steam flavours (native, Debian, Flatpak, Snap), and the command that starts or
stops each one. No other module may name a Flatpak path or a Snap command.
`paths`, `steam` and `readiness` take a `SteamInstall` and ask it what to do.
CONTRIBUTING.md holds the five steps for adding a flavour.

### Nexus

Two APIs divide the work. The v2 GraphQL endpoint answers searches, MD5 lookups
and collection manifests, needs no key, and batches. The v1 REST endpoint needs
the key and is the only place that mints a download link. A mod id read out of a
file name is a hint; `NexusInfo.verified` is true only after an MD5 match proved
the identity.

### Names

`naming.parse()` turns an archive file name into a hero, a variant and a version,
and `heroes` holds the alias table that makes it work. Mod authors name files
freely, so both modules carry rules that look arbitrary and are not. Change
either one with a test beside the change.

## Versions and releases

`__version__` in `src/regalia/__init__.py` is the only version. Hatchling reads
it through `[tool.hatch.version]`, so the package metadata, the `doctor` report
and the Nexus user agent all report the same string. Never write a `version`
field into `pyproject.toml`.

A tag makes a release. Raise `__version__`, commit, then push `vX.Y.Z`.
`.github/workflows/release.yml` builds the two files, stops if the tag and the
built version disagree, installs the wheel and starts it, then publishes the
GitHub release.

## Conventions

- **Comments say why, not what.** The code in this repository explains the
  decision behind a line, especially where the obvious approach fails. Match
  that. Delete a comment that only restates the code.
- **Tests cover what a person cannot check by hand.** There is no blanket suite,
  and that is deliberate. Add a test when you change parsing, conflict
  detection, version comparison, or anything in `environment`. Do not scaffold
  tests for wiring.
- **The API key is written once, at mode 0600, and never printed.** Log the
  masked form or nothing.
- **`migrate` runs once and then stops.** It carries an installation over from
  the old name, `rivalmods`. It repoints the game symlinks, which hold an
  absolute path into the old store. Do not remove it before the next release
  after the rename ships.
- **Scope is Marvel Rivals on Linux under Proton.** The hero table, the pak
  naming rules and the signature bypass are all specific to this one game.
