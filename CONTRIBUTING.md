# Contributing

Thanks for looking. Bug reports and small, focused pull requests are welcome.

## Before you file an issue

- Run `regalia doctor` and paste the output. It reports every check, the Steam
  flavour it found, your distribution, and a **masked** key.
- Never paste your Nexus API key, a signed download URL, or the contents of
  `credentials.toml`. A signed URL carries a working token.
- Say which interface you used, desktop or terminal, and which Proton version
  runs the game.

## Setting up

```bash
git clone https://github.com/nathanphelps/regalia
cd regalia
uv sync --extra tui
uv run regalia
```

The desktop interface needs the Qt platform libraries that PySide6 pulls in.
The terminal interface is the `tui` extra.

## Before you open a pull request

```bash
uv run --extra tui python -m pytest
uvx ruff check .
uvx ruff format --check .
```

All three must pass. CI runs the same three.

## What the code expects

- **The game folder holds symlinks only.** Anything that copies a mod file into
  the game breaks the guarantee that a game update cannot lose your work.
- **Domain modules stay free of presentation code.** `archive`, `catalog`,
  `installer`, `patch`, `paths`, `environment`, `readiness` and `nexus` know
  nothing about Textual or Qt. Both interfaces are consumers.
- **`environment` owns every fact about the host.** No other module may name a
  Flatpak path or a Snap command.
- **Long work leaves the UI thread.** Downloads, extraction, hashing, and link
  operations run through the worker layer in each interface.
- **The API key is written once, at mode 0600, and never printed.** Log the
  masked form or nothing.

## Adding a Steam flavour

Everything lives in `src/regalia/environment.py`.

1. Add a member to `SteamFlavor`.
2. Add its root to `candidate_roots()`, in priority order.
3. Teach `SteamInstall._launcher()` how to run that client.
4. Teach `flavor_for()` to recognise the path, so a user who types the root by
   hand still gets the right commands.
5. Add the root to `FLAVOUR_ROOTS` in `tests/test_environment.py`. The
   parametrised test then covers it, and add a command test beside the existing
   Flatpak and Snap ones.

Nothing else needs to change. `paths`, `steam` and `readiness` all take a
`SteamInstall` and ask it what to do.

## Tests

There is no blanket test suite, and that is deliberate for a tool this size.
The tests that exist cover what cannot be checked by hand:

| File | Covers |
|---|---|
| `test_environment.py` | Steam detection per flavour, XDG resolution, the localised downloads folder |
| `test_vdf.py` | reading and rewriting `localconfig.vdf`, merging the DLL override |
| `test_migrate.py` | carrying an installation over from the old name |
| `test_heroes.py` | the hero overlay merge rules |
| `test_naming.py` | archive names to hero, variant and version |

If you change parsing, conflict detection, version comparison, or anything in
`environment`, add a test next to the change. Those are the parts where a quiet
mistake is expensive: a wrong value written into someone's Steam configuration,
or a mod that silently loses its conflict warnings.

## Releasing

The version lives in one place: `__version__` in `src/regalia/__init__.py`.
Hatchling reads it, so the package metadata, the `doctor` report and the Nexus
user agent all report the same string. Never write a version into
`pyproject.toml`.

To cut a release:

1. Raise `__version__` in `src/regalia/__init__.py`.
2. Commit that change on `main`.
3. Tag it: `git tag -a v0.2.0 -m "Regalia 0.2.0"`.
4. Push the tag: `git push origin v0.2.0`.

`.github/workflows/release.yml` does the rest. It builds the wheel and the
source archive with `uv build`, stops if the tag and the built version disagree,
installs the wheel and starts it, then opens a GitHub release with both files
and generated notes.

Build the same two files locally with `uv build`. Nothing in `dist/` is
committed.

## Scope

Regalia targets Marvel Rivals on Linux under Proton. Patches that add other
games are out of scope; the hero table, the pak naming rules, and the signature
bypass are all specific to this one.

These are deferred rather than rejected, and a well-scoped patch is welcome:

- a chooser for machines with two Steam accounts that both own the game
- a lock on `catalog.json`, so two running interfaces cannot clobber each other
- Windows support
