"""Report the ways a mod set can go wrong.

The first check is the one that matters, and it changed shape. Two mods clash
when they write the same asset, not when they touch the same hero. A hero has
many costumes, and a library with forty Emma Frost mods covering forty different
costumes is a healthy library; a hero-level check calls every one of them a
problem, and a warning that fires on a healthy setup teaches the user to ignore
warnings.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import components as component_rules
from .model import Component, Mod, State


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

    # Gathered per mod, because a mod that fights six others should say so once.
    # Six separate rows for one problem is the noise the hero-level check used
    # to make, in a different shape.
    rivals: dict[str, list[tuple[Mod, set[str]]]] = {}
    for mod, other, shared, _certain in overlaps(mods):
        rivals.setdefault(mod.slug, []).append((other, shared))

    for slug, found in rivals.items():
        mod = next(item for item in mods if item.slug == slug)
        found.sort(key=lambda pair: -len(pair[1]))
        contested = _describe({asset for _, shared in found for asset in shared})
        if len(found) == 1:
            add(mod, "conflict", f"overwrites {_name(found[0][0], mods)}: {contested}")
        else:
            listed = ", ".join(_name(other, mods) for other, _ in found[:2])
            add(
                mod,
                "conflict",
                f"overwrites {len(found)} other mods ({listed}, …): {contested}",
            )

    # Two mods whose containers are named the same take the same link name, so
    # one silently replaces the other in the game folder. The assets need not
    # overlap at all for this to bite.
    for mod, other, name in name_collisions(mods):
        add(mod, "conflict", f"shares the file name {name} with {other.title}")

    # A newer version of the same mod sits in the library. The download site id
    # identifies the mod across versions, unlike the file name.
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

    # Unreal reads "~mods" in alphabetical order and "_P" marks a patch pak.
    # Without the high number the mod can load before the base game files and
    # lose the override.
    for mod in mods:
        if not mod.has_load_order and mod.state is not State.UNSUPPORTED:
            add(mod, "loadorder", "no _9999999_P suffix — may not override")

    # Nexus holds a newer file than the one on disk.
    for mod in mods:
        if mod.nexus and mod.nexus.has_update:
            newer = mod.nexus.latest_version or f"file {mod.nexus.latest_file_id}"
            add(mod, "outdated", f"Nexus has {newer}")

    # An option that was never resolved. After a normal install this is empty,
    # but a catalog carried over from a version that linked everything arrives
    # with each option switched on.
    for mod in mods:
        if mod.state is not State.INSTALLED:
            continue
        internal = _internal_overlaps(mod.active)
        if internal:
            add(
                mod,
                "conflict",
                f"{internal + 1} of its own options are running at once — pick one",
            )

    return result


def overlaps(mods: list[Mod]) -> list[tuple[Mod, Mod, set[str], bool]]:
    """Every pair of installed mods that write the same asset.

    Reported once for each side, so a table can show the warning on both rows.
    Members of one collection are not exempt: a curator picking two mods that
    overwrite each other is still only getting one of them, and that is worth
    saying. The old exemption existed to mute a hero-level check that fired on
    almost everything, and this one does not.
    """
    # An index from asset to the mods writing it. Comparing every pair of
    # components directly would be quadratic in a library of a few hundred, and
    # almost every pair shares nothing.
    owners: dict[str, list[Mod]] = {}
    for mod in mods:
        if mod.state is not State.INSTALLED:
            continue
        for component in mod.active:
            for asset in component.assets:
                holders = owners.setdefault(asset, [])
                if mod not in holders:
                    holders.append(mod)

    found: dict[tuple[str, str], tuple[Mod, Mod, set[str], bool]] = {}
    for asset, holders in owners.items():
        if len(holders) < 2:
            continue
        for mod in holders:
            for other in holders:
                if other is mod:
                    continue
                key = (mod.slug, other.slug)
                if key in found:
                    found[key][2].add(asset)
                else:
                    found[key] = (mod, other, {asset}, True)
    return list(found.values())


def name_collisions(mods: list[Mod]) -> list[tuple[Mod, Mod, str]]:
    """Pairs of installed mods that claim the same file name in the game folder."""
    owners: dict[str, list[Mod]] = {}
    for mod in mods:
        if mod.state is not State.INSTALLED:
            continue
        for name in mod.files:
            owners.setdefault(name, []).append(mod)

    found: list[tuple[Mod, Mod, str]] = []
    for name, holders in sorted(owners.items()):
        if len(holders) < 2:
            continue
        for mod in holders:
            for other in holders:
                if other is not mod:
                    found.append((mod, other, name))
    return found


def _internal_overlaps(active: list[Component]) -> int:
    """How many enabled components of one mod overwrite an earlier one."""
    count = 0
    for index, component in enumerate(active):
        if any(component_rules.overlap(component, other) for other in active[:index]):
            count += 1
    return count


def _name(mod: Mod, mods: list[Mod]) -> str:
    """A label that tells two mods apart.

    Titles come from the archive name, and two downloads of one mod page often
    produce the same one. "overwrites Adam Warlock — Default · Aroused" printed
    twice on one row leaves the user with no way to tell which file to remove.
    """
    same = [other for other in mods if other.title == mod.title]
    if len(same) < 2:
        return mod.title
    return f"{mod.title} ({mod.version_label})" if mod.version else mod.source.name


def _describe(shared: set[str]) -> str:
    """Name what is contested, in the terms the user thinks in.

    Costume ids are the useful unit: "Emma Frost's Queen of Diamonds" is a thing
    the user recognises, while a list of ".uasset" paths is not.
    """
    from .iostore import CHARACTER_SKIN

    skins: dict[str, None] = {}
    for asset in shared:
        for match in CHARACTER_SKIN.finditer(asset):
            if match.group(1) == match.group(2):
                skins.setdefault(match.group(2) + match.group(3), None)

    if skins:
        listed = ", ".join(sorted(skins)[:3])
        extra = "" if len(skins) <= 3 else f" and {len(skins) - 3} more"
        return f"costume {listed}{extra}"
    count = len(shared)
    return f"{count} asset{'' if count == 1 else 's'}"


SYMBOLS = {"conflict": "⚠", "outdated": "↑", "loadorder": "!"}


def badge(warnings: list[Warning_]) -> str:
    """A compact marker for the table."""
    return "".join(dict.fromkeys(SYMBOLS[w.kind] for w in warnings))
