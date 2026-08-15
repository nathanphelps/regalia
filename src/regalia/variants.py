"""Group and safely switch variants of one Nexus mod."""

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
    """Enable one variant and restore the former active set if linking fails."""
    active = [
        mod for mod in siblings if mod is not target and mod.state is State.INSTALLED
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
