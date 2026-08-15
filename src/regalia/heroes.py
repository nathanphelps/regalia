"""Marvel Rivals hero names and the aliases that appear in mod file names.

The built-in table below ships with the tool. A user adds to it through
`heroes.toml` in the configuration directory, which matters because the game
adds a hero every season and an unknown hero loses its conflict warnings.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .paths import CONFIG_DIR

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
