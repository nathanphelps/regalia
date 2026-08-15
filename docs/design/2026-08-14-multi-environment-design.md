# Multi-environment readiness — design

**Date:** 2026-08-14
**Status:** approved

## Purpose

regalia works on one machine: the author's. This design makes it work for a
stranger on any Linux Steam installation.

Two problems drive the work.

1. The tool hardcodes paths, commands, and defaults that only the author has.
2. A new user gets no help when discovery fails. The first screen is empty and
   the error names a configuration file that does not exist yet.

## Scope

In scope:

- Every Linux Steam flavour: native, Debian package, Flatpak, Snap, SteamOS.
- XDG base directory compliance.
- Defaults that suit a user who is not the author.
- A guided first run, and a `doctor` command.
- A user-editable hero overlay.
- A pure-Python extraction fallback, so no system package is required.
- The desktop application becomes the default install. The terminal application
  becomes an extra.
- Tests for environment detection and VDF parsing.

Out of scope, deliberately:

| Deferred | Reason |
|---|---|
| Windows support | No Proton, no XDG, no `xdg-mime`. A second platform layer. |
| A multi-Steam-account chooser | Rare. The tool will report which account it used instead. |
| Locking `catalog.json` between instances | Needs a design of its own. |
| Sharing one store between OS users | Symlink ownership in a shared game folder is unsolved. |
| Learning heroes from Nexus categories | The mapping is a guess. Wrong guesses corrupt conflict detection. |

## What breaks today

| Area | Fault |
|---|---|
| Steam root | Only `~/.local/share/Steam` and `~/.steam/steam`. Flatpak, Snap and the Debian package are all missed. |
| Steam command | `shutil.which("steam")` finds nothing under Flatpak or Snap, so the launch-option flow stops. |
| XDG | `CONFIG_DIR`, `DATA_DIR` and the desktop directory ignore `XDG_CONFIG_HOME` and `XDG_DATA_HOME`. |
| Image cache | Cache data sits in the data directory. |
| Scan folder | The default is `~/Downloads/Rivals`, a folder only the author has. |
| Steam account | `set_launch_options` edits the first account that owns the game, without saying which. |
| Hero table | Hardcoded. A hero added next season parses as `Unknown` and loses conflict detection. |
| Extraction | `7z` is required. SteamOS and the immutable distributions cannot install it easily. |
| Packaging | PySide6 is required even for a terminal-only user. |
| Font | Qt asks for `Inter`, which most systems do not ship. |

## Architecture

### The environment layer

A new module, `environment.py`, holds every fact about the host. It is the only
module that knows a Flatpak path, and it is also the only module that knows how
to stop a Flatpak Steam. Splitting those two facts apart is what makes the
current code hard to extend.

```python
class SteamFlavor(StrEnum):
    NATIVE = "native"
    DEB = "deb"
    FLATPAK = "flatpak"
    SNAP = "snap"


@dataclass(frozen=True, slots=True)
class SteamInstall:
    root: Path
    flavor: SteamFlavor

    def shutdown_command(self) -> list[str] | None: ...
    def start_command(self) -> list[str] | None: ...
```

Candidate roots, probed in order. A root counts when
`steamapps/libraryfolders.vdf` exists. Results are deduplicated by resolved
path, because `~/.steam/steam` is usually a symbolic link to the native root.

| Flavour | Root |
|---|---|
| native | `$XDG_DATA_HOME/Steam` |
| native | `~/.steam/steam` |
| native | `~/.steam/root` |
| deb | `~/.steam/debian-installation` |
| flatpak | `~/.var/app/com.valvesoftware.Steam/data/Steam` |
| snap | `~/snap/steam/common/.local/share/Steam` |

Commands per flavour:

| Flavour | Stop | Start |
|---|---|---|
| native, deb | `steam -shutdown` | `steam` |
| flatpak | `flatpak run com.valvesoftware.Steam -shutdown` | `flatpak run com.valvesoftware.Steam` |
| snap | `snap run steam -shutdown` | `snap run steam` |

A command is offered only when its launcher is on the path. When no command is
available, the caller asks the user to close Steam and then polls. The tool
still refuses to write while Steam runs.

The module also resolves the base directories: `xdg_config_home()`,
`xdg_data_home()`, `xdg_cache_home()`, and `download_dir()`. The last reads
`XDG_DOWNLOAD_DIR`, then `~/.config/user-dirs.dirs`, then falls back to
`~/Downloads`. A localised desktop names that folder in the user's language, so
the fallback alone is not enough.

**Every function takes an optional `home` and `env`.** They default to the real
ones. This single seam lets the tests build a fake home for each flavour without
touching the real environment.

### Application directories

`paths.py` keeps the constant names, so call sites do not change, but computes
them from XDG. A new `CACHE_DIR` joins them. The image cache moves from
`DATA_DIR/images` to `CACHE_DIR/images`, with a best-effort move on first run.
A failed move costs re-downloads and nothing else, so failures are ignored.

### Steam integration

`discover_game()` and `local_config_files()` accept the detected installs.
`steam.shutdown()` and `steam.start()` accept a `SteamInstall`.

Process detection keeps `pgrep -x steam` and `pgrep -x steamwebhelper`, and adds
`pgrep -f com.valvesoftware.Steam`. Flatpak normally preserves the process name,
but this is the one fact that cannot be checked from the author's machine, so
`doctor` prints what it matched rather than asserting.

`read_current()` and `set_launch_options()` return the account directory they
used. The user interface and `doctor` show it. This does not build the deferred
account chooser, but it does let a user on a shared machine see that the tool
picked the wrong profile.

### Extraction

`archive.py` gains two backends behind its existing functions.

| Backend | Used for | Progress from |
|---|---|---|
| `7z` subprocess | everything, when `7z` is on the path | the `NN%` the command prints |
| pure Python | otherwise | entries extracted over total entries |

The Python backend uses `py7zr` for `.7z` and the standard library `zipfile` for
`.zip`. `REGALIA_EXTRACTOR` forces `7z` or `python` for debugging.

The progress callback signature does not change, so `installer.py` and both
interfaces are untouched. The fallback is invisible above `archive.py`.

### Packaging and entry points

```toml
dependencies = ["pyside6>=6.8", "py7zr>=0.21"]

[project.optional-dependencies]
tui = ["textual>=0.85"]
```

| Command | Before | After |
|---|---|---|
| `regalia` | terminal application | desktop application |
| `regalia tui` | — | terminal application |
| `regalia-gui` | desktop application | kept as an alias |
| `regalia doctor` | — | environment report |

`regalia tui` prints an instruction to install the extra when `textual` is
absent. No Textual module may be imported before that check, so `cli.py` imports
the terminal application lazily.

A desktop entry for the application itself joins the one for the `nxm` handler,
so regalia appears in the applications menu.

The Qt font falls back through `Inter`, then the platform sans-serif, instead of
naming one font that most systems lack.

### Onboarding

A new module, `readiness.py`, holds one model that three interfaces present.

```python
class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    level: Level
    detail: str
    remedy: str | None


def run_checks(config) -> list[Check]: ...
```

The checks: the extractor, the Steam install and its flavour, the game location,
the scan folders and whether they are writable, the Nexus key, the patch loader,
the patch plugin, the launch override, and the `nxm` handler.

Three consumers:

1. `regalia doctor` prints every check and its remedy, with versions and
   flavours. It exits 1 when any check is blocked. This is the output to request
   in a bug report.
2. The desktop application shows a Setup page when no configuration file exists,
   or when any check is blocked. It walks the user through the game location,
   the downloads folder, the key, and the patch, then saves the configuration.
   The page stays available in the navigation rail.
3. The terminal application shows the same checks on a first-run screen.

### Hero overlay

`heroes.py` gains `load_heroes()`, which merges
`$XDG_CONFIG_HOME/regalia/heroes.toml` over the built-in table.

```toml
[heroes]
Ultron = ["ultron"]
Hulk = ["banner"]
```

A new key adds a hero. An existing key unions its aliases with the built-in
ones; it does not replace them. `naming.py` reads the table through a cached
call rather than at import, so the overlay applies and the tests can reload it.
`doctor` reports the overlay and how many heroes it adds.

## Testing

The project has no test suite by choice. This layer earns an exception, because
its correctness cannot be checked by hand on distributions the author does not
run, and because a mistake writes a wrong value into a user's Steam
configuration.

| File | Covers |
|---|---|
| `test_environment.py` | detection per flavour over fixture homes, priority, deduplication, XDG overrides, a localised download directory |
| `test_vdf.py` | `_apps_section`, `_launch_options_in` including the licence-data decoy and escaped quotes, `_rewrite` with the key present and absent, escape round-trip |
| `test_steam_options.py` | `merge_override`: empty, another DLL present, `dsound` already present, `%command%` present and absent, trailing arguments |
| `test_heroes.py` | overlay merge rules |
| `test_naming.py` | real archive names to hero, variant and version |

Continuous integration gains a `pytest` job.

## Error handling

| Condition | Behaviour |
|---|---|
| No Steam install found | Blocked check. The remedy names the config key and the flavours searched. |
| Steam found, game absent | Blocked check. The remedy says to run the game once, or set `game_root`. |
| Steam running, no stop command | The user is asked to close Steam. The tool polls and never writes while Steam runs. |
| Scan folder missing | Warning check. Setup offers to create it. |
| Scan folder not writable | Blocked check, because downloads land there. |
| No extractor | Blocked check. This can only happen when `py7zr` is missing from a broken install. |
| Overlay file malformed | Warning check. The built-in table is used and the parse error is shown. |

## Risks

- Flatpak process naming cannot be verified from the author's machine. `doctor`
  exposes what it matched.
- `py7zr` is slower than `7z` on large archives, so the `7z` path stays
  preferred when available.
- The entry-point change breaks the habit of anyone who used the tool before it.

## Documentation

The README gains a supported-environment table, the split install instructions,
and sections for `heroes.toml`, `doctor`, `REGALIA_EXTRACTOR` and
`NEXUS_API_KEY`. CONTRIBUTING gains instructions to add a Steam flavour and to
run the tests.
