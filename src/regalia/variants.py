"""Group the archives that are alternative downloads of one Nexus mod page.

This is a different question from the one `components` answers. A component is a
pak set inside one archive. A variant here is a whole archive — one of several
files a mod page offers, where the user picked more than one and wants to switch
between them.

Both exist because both happen. An author can offer five files on a page, or one
file holding five folders, or five files each holding five folders.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import installer
from .model import Mod, State


@dataclass(frozen=True, slots=True)
class VariantGroup:
    identity: str
    title: str
    mods: tuple[Mod, ...]

    @property
    def active(self) -> tuple[Mod, ...]:
        return tuple(mod for mod in self.mods if mod.state is State.INSTALLED)

    @property
    def held(self) -> tuple[Mod, ...]:
        return tuple(mod for mod in self.mods if mod.is_present)

    @property
    def has_choices(self) -> bool:
        return len(self.mods) > 1


def group_mods(mods: list[Mod]) -> list[VariantGroup]:
    grouped: dict[str, list[Mod]] = {}
    for mod in mods:
        # A verified Nexus ID is the only safe proof that differently named
        # archives are choices from one mod page. Unverified guesses stay alone.
        identity = f"nexus:{mod.nexus_id}" if mod.nexus_id else f"local:{mod.slug}"
        grouped.setdefault(identity, []).append(mod)

    result: list[VariantGroup] = []
    for identity, members in grouped.items():
        members.sort(
            key=lambda mod: (
                mod.state is not State.INSTALLED,
                mod.display_variant.lower(),
                mod.version or "",
            )
        )
        first = members[0]
        title = first.nexus.mod_name if first.nexus else first.hero
        result.append(VariantGroup(identity, title, tuple(members)))
    return sorted(result, key=lambda group: group.title.lower())


def activate(target: Mod, siblings: list[Mod], mods_dir: Path) -> None:
    """Enable one variant and restore the former active set if linking fails.

    Files from the same mod page usually rebuild the same costume, so switching
    means turning the others off. Two files from one page that touch nothing in
    common are left alone: `conflicts` reports a real overlap, and nothing here
    should switch off a mod the user is not actually replacing.
    """
    active = [
        mod
        for mod in siblings
        if mod is not target and mod.state is State.INSTALLED and _overlaps(target, mod)
    ]
    for mod in active:
        installer.unlink(mod, mods_dir)
    try:
        if target.is_present:
            installer.link(target, mods_dir)
        else:
            installer.install(target, mods_dir)
    except Exception:
        if target.state is State.INSTALLED:
            installer.unlink(target, mods_dir)
        for mod in active:
            installer.link(mod, mods_dir, overwrite=True)
        raise


def _overlaps(one: Mod, other: Mod) -> bool:
    """Whether two archives would fight over anything.

    Asset paths decide it when both were read. When either could not be read the
    answer is yes, which keeps the old behaviour for a mod the tool cannot
    inspect: switching variants is a deliberate act and leaving the previous one
    running would surprise the user more than turning it off.
    """
    left = {asset for item in one.active for asset in item.assets}
    right = {asset for item in other.active for asset in item.assets}
    if not left or not right:
        return True
    if left & right:
        return True
    # Even with disjoint assets, two archives claiming one file name collide in
    # the game folder, because the second link replaces the first.
    return bool(set(one.files) & set(other.files))
