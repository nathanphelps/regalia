---
name: marvel-rivals-modding
description: The domain model for Marvel Rivals mods on PC and Linux — pak/ucas/utoc containers, the ~mods folder, the _9999999_P load-order suffix, the UTOC signature bypass, character and skin IDs inside asset paths, and the rule that decides whether two pak sets can be active together. Use this skill whenever the work touches Marvel Rivals mods, a Marvel Rivals mod manager, the Regalia codebase, Unreal Engine 5 IoStore containers, ~mods, .utoc or .ucas files, mod conflict detection, or archive layouts from Nexus Mods for this game — even when the request names none of those directly and only asks to "install a skin", "group the variants", or "work out which mods clash".
---

# Marvel Rivals modding

Marvel Rivals is Unreal Engine 5 with IoStore packaging. Almost every wrong
assumption in a Rivals mod manager comes from one of four mistakes. Read this
section before you design anything; the details live in the reference files.

The four mistakes:

1. **"A mod is one pak."** A mod is an archive. An archive holds one or more
   independent pak sets, and the author expects you to install some of them.
2. **"One mod per hero."** A hero has many costume slots. Two mods that dress
   different costumes of one hero both load, and both work.
3. **"Two mods for one hero conflict."** They conflict only when they write the
   same asset path. Hero identity says nothing about that.
4. **"The file name tells you what the mod does."** It tells you what the author
   felt like typing. The asset paths inside the container tell you the truth.

## The vocabulary

Use these words consistently. The ambiguity of the bare word "mod" is what the
Nexus Mods app blamed for its own data-model rewrite, so name the layer you mean.

| Term | Means |
|---|---|
| **Archive** | The `.zip` or `.7z` the user downloaded. One Nexus file. |
| **Pak set** | One `.pak` + `.ucas` + `.utoc` sharing a stem. The smallest unit the game loads. |
| **Component** | A pak set the user can turn on independently. |
| **Option group** | Components that overwrite each other, so at most one may be active. |
| **Costume** / **skin** | One of a hero's outfits, identified by a 7-digit ID. |
| **Deployment** | The set of pak sets currently linked into the game folder. |

An archive contains components. Components fall into option groups. A
deployment holds at most one component per option group, plus every additive
component the user enabled.

## The layout rule

An archive's folder tree is the author's option tree. Real examples from a
182-archive library:

```
Thicc Mantis (Flora Maiden)/
├── Default/        L/  M/  XL/  XXL/  XXXL/  zMaX/   ← pick one
├── No Skirt/       L/  M/  XL/  XXL/  XXXL/  zMaX/   ← pick one
├── =Top Heavy/     No Skirt/ L/ M/ XL/ XXL/ XXXL/    ← pick one
└── _Physics/                                          ← add alongside
```

Twenty-four pak sets. The author intends the user to run **two** of them: one
body shape and the physics add-on. Linking all twenty-four is not "installing
the mod" — it is handing Unreal twenty-four claims on the same asset and letting
it pick one at random.

Do not try to read intent from folder names. `_Physics`, `zMaX` and `=Top Heavy`
are one author's punctuation habits, not a convention. Derive the grouping from
the asset paths instead, which is the next section.

## The conflict rule

Two pak sets conflict when they write at least one identical asset path. That is
the whole rule, and it holds at every level:

- Inside one archive it separates the option groups from the add-ons.
- Across archives it finds the real clashes between separately installed mods.
- Against the base game it tells you which costume a mod replaces.

Derive it, don't guess it. A `.utoc` carries a plain directory index listing
every asset path in the container, and it parses in pure Python with no external
tool — see `references/utoc-format.md` for the byte layout and
`references/asset-paths.md` for what the paths mean.

Hero-level conflict checks are the trap. A user with forty Emma Frost mods
covering forty different costumes has zero conflicts and would get forty
warnings. Warnings that fire on healthy setups train the user to ignore them.

## Deployment mechanics

The game reads mods from:

```
<game root>/MarvelGame/Marvel/Content/Paks/~mods/
```

Every file in a pak set must land there together. The stem must survive intact —
`.ucas` and `.utoc` are found by the `.pak`'s name, so renaming one of the three
breaks the set.

Unreal reads `~mods` in alphabetical order, and `_P` marks a patch container.
The community convention `_9999999_P` puts a mod last so it wins against the
base game. A pak set without it may load before the game's own files and lose
its override, which looks to the user like "the mod does nothing".

Nothing loads at all without the signature bypass. Marvel Rivals rejects
unsigned containers, and the bypass is an ASI plugin that Ultimate ASI Loader
loads under the name `dsound.dll`. Under Proton, Wine only loads it when the
Steam launch options carry `WINEDLLOVERRIDES="dsound=n,b" %command%`. Treat a
missing override as blocking, never as a warning: every other diagnostic the
tool prints is noise while it is absent.

## Identity

A file name is a hint. An MD5 matched against the Nexus API is proof. Keep the
two apart in any data model — a mod id scraped from a file name should never be
presented with the same confidence as a verified one, because the scraped one is
routinely wrong and the user cannot tell which they are looking at.

Heroes and costumes are better read from asset paths than from names. The path
`.../Characters/1029/1029303/...` states the character and the costume as fact.
`heroes` alias tables are a fallback for archives you cannot open, not the
primary source.

## Reference files

Read the one you need; none of them is required for general discussion.

- `references/asset-paths.md` — character and skin ID scheme, asset categories,
  how to classify a pak set as costume, audio, UI or VFX.
- `references/utoc-format.md` — the `.utoc` binary layout, enough to write a
  directory-index parser, plus the encryption caveat.
- `references/archive-layouts.md` — the shapes real Nexus archives take, with
  frequencies measured over a 182-archive library.
- `references/ecosystem.md` — how Mod Organizer 2, Limo, the Nexus Mods app and
  the existing Rivals managers model this, and which of their decisions to copy.
