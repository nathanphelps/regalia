"""Report the three ways a mod set can go wrong."""

from __future__ import annotations

from dataclasses import dataclass

from .model import Mod, State


@dataclass(frozen=True, slots=True)
class Warning_:
    slug: str
    kind: str
    text: str


def _version_key(mod: Mod) -> tuple[int, ...]:
    if not mod.version:
        return (0,)
    parts = []
    for chunk in mod.version.split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def check(mods: list[Mod]) -> dict[str, list[Warning_]]:
    """Return warnings for every mod, keyed by slug."""
    result: dict[str, list[Warning_]] = {}

    def add(mod: Mod, kind: str, text: str) -> None:
        result.setdefault(mod.slug, []).append(Warning_(mod.slug, kind, text))

    # 1. Two active mods changing the same hero. Only one of them wins in game,
    #    and which one is not predictable from the file names alone.
    #
    #    Members of one collection are exempt. A curator picks overlapping mods
    #    on purpose, and a 137-mod collection would otherwise mark nearly every
    #    row, which would drain the warning of meaning.
    active = [mod for mod in mods if mod.state is State.INSTALLED]
    by_hero: dict[str, list[Mod]] = {}
    for mod in active:
        if mod.hero != "Unknown":
            by_hero.setdefault(mod.hero, []).append(mod)
    for hero, group in by_hero.items():
        if len(group) < 2:
            continue
        for mod in group:
            others = [
                other
                for other in group
                if other is not mod and not _share_collection(mod, other)
            ]
            if not others:
                continue
            names = [other.variant or other.slug for other in others]
            add(mod, "conflict", f"also modifies {hero}: {', '.join(names)}")

    # 2. A newer version of the same mod sits in the library. The download site
    #    id identifies the mod across versions, unlike the file name.
    by_identity: dict[str, list[Mod]] = {}
    for mod in mods:
        if mod.nexus_id:
            by_identity.setdefault(mod.nexus_id, []).append(mod)
    for group in by_identity.values():
        if len(group) < 2:
            continue
        newest = max(group, key=_version_key)
        for mod in group:
            if mod is newest:
                continue
            add(mod, "outdated", f"superseded by {newest.version_label}")

    # 3. Unreal reads "~mods" in alphabetical order and "_P" marks a patch pak.
    #    Without the high number the mod can load before the base game files and
    #    lose the override.
    for mod in mods:
        if not mod.has_load_order and mod.state is not State.UNSUPPORTED:
            add(mod, "loadorder", "no _9999999_P suffix — may not override")

    # 4. Nexus holds a newer file than the one on disk.
    for mod in mods:
        if mod.nexus and mod.nexus.has_update:
            newer = mod.nexus.latest_version or f"file {mod.nexus.latest_file_id}"
            add(mod, "outdated", f"Nexus has {newer}")

    return result


def _share_collection(one: Mod, other: Mod) -> bool:
    return bool(set(one.collections) & set(other.collections))


SYMBOLS = {"conflict": "⚠", "outdated": "↑", "loadorder": "!"}


def badge(warnings: list[Warning_]) -> str:
    """A compact marker for the table."""
    return "".join(dict.fromkeys(SYMBOLS[w.kind] for w in warnings))
