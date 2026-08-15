# The shapes real archives take

Measured over one user's 182-archive Nexus library for this game, 181 of which
contain pak files. The numbers matter because they say which cases are worth
code and which are worth a graceful failure.

## Pak sets per archive

| Pak sets | Archives |
|---|---|
| 1 | 176 |
| 12 | 2 |
| 16 | 1 |
| 21 | 1 |
| 24 | 1 |

The single-set case is 97% of the library, which is why "a mod is one pak set"
survives so long as an assumption. It fails on the five archives that matter
most: they are the biggest downloads, they are the ones with real choices in
them, and mishandling them corrupts the deployment for every other mod that
touches the same hero.

Design for the many-set case and let the single-set case fall out of it as the
degenerate form. The reverse — a single-set model with multi-set bolted on —
puts the exception in every call site.

## Folder depth of the pak files

| Depth | Archives |
|---|---|
| 0, files at the archive root | 38 |
| 1, one wrapper folder | 138 |
| 3 or 4, a real tree | 5 |

The 138 single-wrapper archives are why flattening looks safe: strip the wrapper
and everything lands side by side. The five deep archives are where it destroys
information, because there the folders carry the author's choices.

Flattening also risks silent loss. Two branches commonly hold a pak with the
same file name — that is what "the same mod at a different size" looks like on
disk — and a flatten that skips a name already taken drops the second one with
no error. It did not happen in this library, which is luck, not a guarantee.

## The tree is the option tree

```
Thicc Mantis (Flora Maiden)/
├── Default/           L/ M/ XL/ XXL/ XXXL/ zMaX/ _Normal/
├── No Skirt/          L/ M/ XL/ XXL/ XXXL/ zMaX/ _Normal/
├── =Top Heavy/        No Skirt/ L/ M/ XL/ XXL/ XXXL/
├── =Bottom Heavy/     No Skirt/ L/ M/ XL/ XXL/ XXXL/
└── _Physics/
```

Twenty-four pak sets, of which the author expects two to be active: one body and
the physics add-on. `_Physics` is additive, everything else is one long list of
alternatives.

Naming carries no convention. `_Physics`, `_Normal`, `zMaX` and `=Top Heavy`
come from one author's habits: the leading underscore and the `z` are there to
sort the folder to an end of the list, and `=` to the front. Another author uses
`Optional/`, `Choose One/`, or nothing at all. Any parser keyed on these names
works on one mod page and breaks on the next.

Group by asset paths instead. Read each pak set's `.utoc`, take the set of asset
paths, and two sets that share a path are alternatives while two that do not are
additive. On the tree above that yields exactly the author's intent: every body
size writes the same skeletal mesh, the physics container writes physics assets
nobody else touches.

Fall back to the folder tree only when a container cannot be read: siblings
under one parent are probably alternatives. Say in the interface that the
grouping is a guess when it came from folder names, because the user can correct
a guess and cannot correct a fact they were not told was uncertain.

## File naming inside the archive

Pak stems carry the `_9999999_P` load-order suffix in this library. The stem is
whatever the author typed and frequently has nothing in common with the archive
name: `Adam Warlock-3599-….zip` contains `AdamsBigFatCock_9999999_P.pak`.

Two consequences. The link name in the game folder must be the stem, not
anything derived from the archive. And two unrelated archives can ship the same
stem, so a deployment has to detect that collision rather than let one mod's
link quietly overwrite another's.

## Non-pak contents

Archives routinely carry screenshots, comparison GIFs and read-me files, often
in their own folders, sometimes tens of megabytes of them. They are not mod
content and must not be linked into the game folder. They are, however, the best
preview art available offline, and are worth keeping for that.

## The one archive that is not a mod

The UTOC signature bypass ships as an archive of a DLL and an `.asi` plugin with
no pak at all. Detect it by content — a `dsound.dll` plus something ending
`.asi` — and route it to the patch installer. A name check fails because users
rename it.
