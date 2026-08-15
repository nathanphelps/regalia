# Asset paths, character IDs and skin IDs

Every claim here is checkable against a container you already have. Open a mod's
`.utoc`, list the paths, and the structure is visible in the first ten lines.

## The path shape

A mounted asset path looks like this:

```
../../../Marvel/Content/Marvel/Characters/1029/1029303/Meshes/SK_1029_1029303.uasset
                                          ^^^^ ^^^^^^^
                                          hero costume
```

Normalise before you compare. Containers store the mount point separately and
paths arrive with a `../../../` prefix; strip it and force a leading `/`, so the
example becomes `/Marvel/Content/Marvel/Characters/1029/1029303/...`. Compare
case-insensitively — the same asset appears with different casing across
authors, and a case-sensitive comparison silently misses real conflicts.

## The ID scheme

- **Character ID** — four digits. `1011` is Hulk, `1015` is Storm, `1034` is
  Iron Man, `1036` is Spider-Man, `1049` is Wolverine.
- **Skin ID** — seven digits: the character ID followed by three more. So skin
  `1011300` belongs to character `1011`.
- The suffix `001` is the default costume. `000` is an internal entry and is not
  a costume a player can equip.
- Suffixes cluster in the 100s, 300s, 500s and 800s, which track release waves
  rather than anything a tool should reason about.

Extract with a pattern anchored on the repetition, because the character ID
repeats at the head of the skin ID and that repetition is what tells you the
match is real rather than a coincidental run of digits:

```python
CHARACTER_SKIN = re.compile(r"/Characters/(\d{4})/(\d{4})(\d{3})(?=[/_.])")
# group(1) must equal group(2); the skin id is group(2) + group(3)
```

Ten-digit IDs also appear (`1017300206`). Those are colour sub-variants; the
first seven digits are the skin.

## Turning IDs into names

The game ships the names. They live in `.locres` files inside
`pakchunkLocres-Windows.pak` and the `Patch*Windows*.pak` files, and later paks
override earlier ones, so read them in order.

- Character names: namespace `123_Customize_<charID>_ST`, key
  `MarvelItemTable_<charID>_ItemName`.
- Costume names, best first:
  1. `MarvelItemTable_ps<skinID>_ItemName` in namespace `123_Customize_ST` —
     the retail names.
  2. `UISkinTable_<skinID>0_..._SkinName` in `601_HeroUIAsset_*`.
  3. `UISkinTable_<skinID>0_SkinBasic_SkinName` in `123_Customize_*`.
  4. `MarvelItemTable_<skinID>_ItemName` — often an internal name.

Reject internal names rather than showing them: anything starting with `[`,
containing `recolor`, starting with `placeholder`, or ending in `**`. Those are
developer placeholders and look like corruption to a user.

Reading locres needs a locres parser and the ability to unpack a base game pak,
which is a much heavier dependency than reading a mod's own `.utoc` directory
index. A static ID-to-hero table is a reasonable substitute; a static
ID-to-costume table is not, because costumes ship every season.

## Classifying a pak set

Bucket by where the paths land. A pak set can fall in several buckets, which is
exactly why "one mod, one category" is the wrong model.

| Bucket | Path or name markers |
|---|---|
| Costume mesh and textures | `/Characters/<id>/<skin>/Meshes/`, `/Materials/`, `/Textures/` |
| Physics and cloth | asset names carrying `Physics`, `_PA`, cloth or chain assets |
| VFX | `/Effects/`, `/Particles/`, Niagara assets |
| Audio | `.bnk`, `.wem`, `/WwiseAudio/` |
| UI and icons | `/UI/`, `/Textures/UI/`, portrait and icon assets |
| Maps and lobby | `/Maps/`, `/Levels/` |

The practical payoff: a costume component and an audio component for the same
hero touch disjoint paths, so they are additive and both should install. Two
costume components for one skin touch the same mesh, so they are exclusive. You
get that answer from the paths without knowing what any folder was named.

## Texture naming

Inside a costume the textures follow `T_<charID><skinID>_<part>_<type>` with
`_D` diffuse, `_N` normal, `_ORM` occlusion-roughness-metallic and `_S`
specular. Meshes are `SK_<charID>_<skinID>`. Useful when you want to say *what*
a mod changed rather than only *that* it changed something.
