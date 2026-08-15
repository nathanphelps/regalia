"""Marvel Rivals hero names and the aliases that appear in mod file names.

The built-in table below ships with the tool. A user adds to it through
`heroes.toml` in the configuration directory, which matters because the game
adds a hero every season and an unknown hero loses its conflict warnings.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from .paths import CONFIG_DIR, DATA_DIR

# Canonical name -> extra spellings seen in the wild. Mod authors drop spaces,
# abbreviate, and use MCU names, so one hero needs several aliases.
HEROES: dict[str, tuple[str, ...]] = {
    "Adam Warlock": ("adamwarlock", "warlock"),
    "Angela": (),
    "Beast": (),
    "Black Panther": ("blackpanther", "tchalla"),
    "Black Widow": ("blackwidow", "natasha"),
    "Blade": (),
    "Captain America": ("captainamerica", "captamerica", "capamerica", "cap"),
    "Cloak & Dagger": ("cloakdagger", "cloakanddagger", "cloak", "dagger"),
    "Cyclops": ("scottsummers",),
    "Daredevil": (),
    "Deadpool": (),
    "Doctor Strange": ("doctorstrange", "drstrange", "strange"),
    "Emma Frost": ("emmafrost", "emma"),
    "Gambit": (),
    "Groot": (),
    "Hawkeye": ("clintbarton",),
    "Hela": (),
    "Hulk": ("brucebanner",),
    "Human Torch": ("humantorch", "johnnystorm"),
    "Invisible Woman": ("invisiblewoman", "suestorm"),
    "Iron Fist": ("ironfist",),
    "Iron Man": ("ironman", "tonystark"),
    "Jean Grey": ("jeangrey", "phoenix"),
    "Jeff the Land Shark": ("jeff", "landshark", "jefftheLandshark"),
    "Loki": (),
    "Luna Snow": ("lunasnow", "luna"),
    "Magik": ("illyana",),
    "Magneto": (),
    "Mantis": (),
    "Mister Fantastic": ("mrfantastic", "misterfantastic", "reedrichards"),
    "Moon Knight": ("moonknight",),
    "Namor": (),
    "Nightcrawler": (),
    "Peni Parker": ("peniparker", "peni"),
    "Psylocke": (),
    "Punisher": ("thepunisher", "frankcastle"),
    "Rocket Raccoon": ("rocketraccoon", "rocket"),
    "Scarlet Witch": ("scarletwitch", "wanda"),
    "Silver Surfer": ("silversurfer",),
    "Spider-Man": ("spiderman", "peterparker"),
    "Squirrel Girl": ("squirrelgirl",),
    "Star-Lord": ("starlord", "peterquill"),
    "Storm": ("ororo",),
    "The Thing": ("thething", "bengrimm"),
    "Thor": (),
    "Ultron": (),
    "Venom": ("eddiebrock",),
    "Winter Soldier": ("wintersoldier", "bucky", "buckybarnes"),
    "Wolverine": ("logan",),
}

# Words that describe the mod, not the hero. They are stripped before matching so
# that "MuscularCaptAmerica" resolves cleanly.
NOISE_WORDS: frozenset[str] = frozenset(
    {
        "sit",
        "vlq",
        "muscular",
        "marvel",
        "rivals",
        "mod",
        "skin",
        "mesh",
        "male",
        "nude",
        "lewd",
    }
)


def _key(text: str) -> str:
    """Reduce text to lowercase letters and digits for tolerant matching."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


# -- the user overlay ----------------------------------------------------

OVERLAY_FILE = CONFIG_DIR / "heroes.toml"

_overlay_error: str | None = None
_overlay_count: int = 0
_merged: dict[str, tuple[str, ...]] | None = None
_index: list[tuple[str, str]] | None = None


def read_overlay(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Read the user's extra heroes and aliases.

    The game adds a hero every season. Waiting for a release would leave the new
    hero parsing as "Unknown", which also loses its conflict warnings, so the
    user can name it themselves.
    """
    file = path if path is not None else OVERLAY_FILE
    if not file.is_file():
        return {}

    data = tomllib.loads(file.read_text())
    # Accept both a [heroes] table and a bare top-level table.
    section = data.get("heroes", data)
    if not isinstance(section, dict):
        raise ValueError("the overlay must be a table of hero names")

    found: dict[str, tuple[str, ...]] = {}
    for name, aliases in section.items():
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            raise ValueError(f'"{name}" must hold a list of aliases')
        found[str(name)] = tuple(str(alias) for alias in aliases)
    return found


def merge_heroes(
    base: dict[str, tuple[str, ...]],
    overlay: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Fold the overlay into the built-in table.

    A new key adds a hero. An existing key adds aliases rather than replacing
    them, so a user who names one nickname does not lose the rest.
    """
    merged = {name: tuple(aliases) for name, aliases in base.items()}
    for name, aliases in overlay.items():
        existing = merged.get(name, ())
        merged[name] = tuple(dict.fromkeys((*existing, *aliases)))
    return merged


def heroes() -> dict[str, tuple[str, ...]]:
    """The hero table this run will use, built once and remembered."""
    global _merged, _overlay_error, _overlay_count
    if _merged is None:
        try:
            overlay = read_overlay()
            _overlay_error = None
        except Exception as error:  # a bad overlay must not stop the tool
            overlay = {}
            _overlay_error = str(error)
        _overlay_count = len(overlay)
        _merged = merge_heroes(HEROES, overlay)
    return _merged


def reload_heroes() -> None:
    """Forget the merged table. Used after the user edits the overlay."""
    global _merged, _index
    _merged = None
    _index = None


def overlay_error() -> str | None:
    """Why the overlay was ignored, if it was."""
    heroes()
    return _overlay_error


def overlay_count() -> int:
    """How many heroes the overlay names."""
    heroes()
    return _overlay_count


def alias_index() -> list[tuple[str, str]]:
    """Every alias, longest first.

    Longest-first matching stops "Iron Man" from swallowing a name that should
    have matched "Iron Fist", and stops the bare alias "cap" from beating
    "captainamerica".
    """
    global _index
    if _index is None:
        _index = sorted(
            (
                (_key(alias), canonical)
                for canonical, aliases in heroes().items()
                for alias in (canonical, *aliases)
            ),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
    return _index


def find_hero(text: str) -> tuple[str, str] | None:
    """Find a hero in `text`.

    Returns the canonical hero name and the alias that matched, or None.
    """
    haystack = _key(text)
    for alias_key, canonical in alias_index():
        if alias_key and alias_key in haystack:
            return canonical, alias_key
    return None


# -- character ids, learned from the library -----------------------------
#
# A container states which character it changes: the asset paths carry a
# four-digit id. Nothing ships that maps those ids to names, and a shipped table
# would go stale every season, so the tool works it out from mods it has already
# named and remembers the answer. A file whose name says nothing then still
# reports the right hero, because the pak inside it does.

UNKNOWN = "Unknown"

CHARACTERS_FILE = DATA_DIR / "characters.json"

_learned: dict[str, str] | None = None


def learned_characters() -> dict[str, str]:
    """The character id to hero name map worked out so far."""
    global _learned
    if _learned is None:
        try:
            _learned = {
                str(key): str(value)
                for key, value in json.loads(CHARACTERS_FILE.read_text()).items()
            }
        except (OSError, ValueError, AttributeError):
            _learned = {}
    return dict(_learned)


def learn_characters(pairs: dict[str, str]) -> int:
    """Record character ids seen alongside a known hero. Returns what is new.

    An id already known is left alone. The first confident answer wins, because
    a later disagreement is far more likely to be a mis-parsed file name than a
    character changing identity.
    """
    global _learned
    known = learned_characters()
    fresh = {
        character: hero
        for character, hero in pairs.items()
        if character not in known and hero and hero != UNKNOWN
    }
    if not fresh:
        return 0

    known.update(fresh)
    _learned = known
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CHARACTERS_FILE.write_text(json.dumps(known, indent=2, sort_keys=True) + "\n")
    except OSError:
        # Losing the file costs a re-learn on the next scan, which is cheap.
        # Failing the scan over it is not.
        pass
    return len(fresh)


def hero_for_character(character: str) -> str:
    """The hero a character id belongs to, or "Unknown"."""
    return learned_characters().get(character, UNKNOWN)


def forget_characters() -> None:
    """Drop the cache so the next read comes from disk. Used by the tests."""
    global _learned
    _learned = None


# -- costume names -------------------------------------------------------
#
# The game knows these, in ".locres" files inside its own paks. Those cannot be
# read: the pak index is AES encrypted and the entries are Oodle compressed, so
# reaching them needs the publisher's key and a proprietary decompressor. Both
# are outside what this project can ship.
#
# What can be read is the library itself. Mod authors lead a file name with the
# costume far more often than not — three separate Blade mods all begin
# "BladeKnight" — so the first word of the parsed variant, agreed on by several
# mods for one costume, is a good name for it. A costume the tool works out this
# way is a guess from names, which is why it takes a vote and why the user can
# overrule it in costumes.toml.

COSTUMES_FILE = DATA_DIR / "costumes.json"
COSTUME_OVERLAY_FILE = CONFIG_DIR / "costumes.toml"

# The default costume is the one the game ships the character in. Its id always
# ends "001", so it needs no guessing and no vote.
DEFAULT_SUFFIX = "001"

# Words that describe what a mod does to a costume rather than naming one.
COSTUME_NOISE: frozenset[str] = frozenset(
    {
        "addon",
        "addin",
        "retexture",
        "remove",
        "nude",
        "thicc",
        "skimpy",
        "sexy",
        "muscular",
        "body",
        "bodyhair",
        "oily",
        "thong",
        "jockstrap",
        "briefs",
        "beard",
        "hair",
        "aroused",
        "erect",
        "flaccid",
        "physics",
        "fix",
        "main",
        "version",
        "new",
        "old",
        "updated",
        "no",
        "the",
    }
)

_costumes: dict[str, str] | None = None


def _costume_overlay() -> dict[str, str]:
    if not COSTUME_OVERLAY_FILE.is_file():
        return {}
    try:
        data = tomllib.loads(COSTUME_OVERLAY_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section = data.get("costumes", data)
    if not isinstance(section, dict):
        return {}
    return {str(key): str(value) for key, value in section.items()}


def learned_costumes() -> dict[str, str]:
    """Costume id to name, with anything the user wrote taking priority."""
    global _costumes
    if _costumes is None:
        try:
            found = {
                str(key): str(value)
                for key, value in json.loads(COSTUMES_FILE.read_text()).items()
            }
        except (OSError, ValueError, AttributeError):
            found = {}
        found.update(_costume_overlay())
        _costumes = found
    return dict(_costumes)


def is_costume_name(word: str) -> bool:
    """Whether a word could be naming a costume rather than describing a change."""
    cleaned = word.strip()
    return (
        len(cleaned) > 2
        and not cleaned.isdigit()
        and cleaned.lower() not in COSTUME_NOISE
        and cleaned.lower() not in NOISE_WORDS
    )


def learn_costumes(votes: dict[str, list[str]], agree: int = 2) -> int:
    """Record costume names that several mods agree on. Returns what is new.

    A vote rather than a first answer, because this reads a file name and file
    names are wrong often enough to matter. One mod calling a costume "Skimpy
    outfit" should not name it for every other mod that shares it.
    """
    global _costumes
    known = learned_costumes()
    fresh: dict[str, str] = {}

    for costume, names in votes.items():
        if costume in known:
            continue
        if costume.endswith(DEFAULT_SUFFIX):
            fresh[costume] = "Default"
            continue
        tally: dict[str, int] = {}
        for name in names:
            if is_costume_name(name):
                tally[name] = tally.get(name, 0) + 1
        if not tally:
            continue
        best, count = max(tally.items(), key=lambda pair: pair[1])
        if count >= agree:
            fresh[costume] = best

    if not fresh:
        return 0

    known.update(fresh)
    _costumes = known
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Only what was worked out. Anything the user wrote stays in their file,
        # so a rewrite here can never quietly bake their wording into ours.
        overlay = _costume_overlay()
        COSTUMES_FILE.write_text(
            json.dumps(
                {key: value for key, value in known.items() if key not in overlay},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError:
        pass
    return len(fresh)


def costume_name(costume: str) -> str:
    """The costume's name, or its id when nothing has named it yet."""
    return learned_costumes().get(costume, costume)


def forget_costumes() -> None:
    """Drop the cache so the next read comes from disk. Used by the tests."""
    global _costumes
    _costumes = None
