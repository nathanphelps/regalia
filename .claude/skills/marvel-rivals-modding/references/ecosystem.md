# What the other mod managers decided

Worth reading before inventing a data model, because several of these projects
already hit the wall and wrote down what they changed.

## Nexus Mods app — the word "mod" was the bug

They rewrote their core model because "Mod" was ambiguous: it was being used for
a downloaded archive, for a thing the user toggles, for game files, and for
overrides, all at once. The replacement is a small tree:

- `LoadoutItem` — anything in a loadout, with a name
- `LoadoutFile` — a file, a kind of `LoadoutItem`
- `LoadoutItemGroup` — a container that is itself an item, so groups nest
- `LibraryItem` and `LibraryLinkedLoadoutItem` — the archive, and the link from
  the archive to what it put in the loadout

Their worked example is an archive that installs three separate mods: it becomes
one group holding three children, so the user sees the one thing they downloaded
and can still act on the three things inside it. That is the same shape a Rivals
archive with twenty-four pak sets needs.

Their conflict model is file-path based with an explicit priority order the user
can drag to reorder — conflicts are surfaced and resolved, not prevented.

Take from this: separate the archive from the installable unit, let the
installable unit nest, and never name either of them "mod" in code.

## Mod Organizer 2 — separate files of one mod page

Long-standing issue: a Nexus page has a main file plus optional files, users
install them separately, and treating them as one entry means reinstalling
everything to update one piece. Their answer is to track the optional files
independently while naming them after the parent.

Take from this: identity is per file, not per mod page, but presentation groups
by page. Both facts have to be in the model.

## Limo — deployers and target directories

A Linux general-purpose manager. Mods live in a staging directory; a *deployer*
links them into a target directory, and one application can have several target
directories. It defaults to hard links rather than symlinks.

Take from this: the staging-directory-plus-link design is standard and correct,
and the deployment target is worth naming as its own concept rather than
hard-coding one path.

## The Marvel Rivals managers

**RivalNxt** is the most complete. It parses `.pak` and `.utoc` contents, stores
asset paths in SQLite, and computes conflicts as a view over which asset paths
appear in more than one pak. It reads character and skin names out of the game's
own `.locres` files so its tables never go stale, and it renders a file tree so
the user can activate individual paks inside a multi-pak archive. Its costs: a
Rust extension via PyO3 as a hard dependency, and a subprocess wrapper because
that extension panics on malformed files.

**Stwinklein/MarvelRivalsModManager** groups `.pak`/`.ucas`/`.utoc` by stem into
one unit, categorises by hero-name keyword matching with manual tags on top, and
disables a mod by *moving* it to a folder inside `Paks/` rather than renaming or
moving it outside — their note is that this survives game updates better. No
conflict detection.

Take from this: asset-level conflict detection and per-pak activation are the
two features that separate a working Rivals manager from a file mover. Neither
needs a native extension — the `.utoc` directory index parses in Python.

## The common thread

Every project that started with "one archive is one mod" rewrote it. The ones
that ship useful conflict detection all read inside the containers. Filename
heuristics are the fallback layer in every mature design and the primary layer
only in the immature ones.
