"""Named sets of mods, switched in one step.

A profile records what was deployed: which mods ran, and which parts of each.
That second half is what makes it worth having. Recording only "these mods were
installed" would lose the body size chosen out of a twenty-four part archive,
so switching to a profile and back would quietly change the result.

Applying a profile is a diff against what is running now, not a teardown and a
rebuild. A mod in both the old and the new set keeps its links, so switching
between two profiles that share a hundred mods costs almost nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import components, installer
from .model import Mod, State
from .paths import DATA_DIR

PROFILES_FILE = DATA_DIR / "profiles.json"

# A profile name is shown, searched and used as a key. Anything that would make
# two names look identical in a list is trimmed away.
NAME = re.compile(r"\s+")
MAX_NAME = 60


class ProfileError(Exception):
    """The profile cannot be saved or applied, with the reason in the message."""


@dataclass(slots=True)
class Profile:
    """One saved deployment.

    `parts` maps a mod slug to the labels of the components that were enabled.
    A slug present with an empty list means the mod ran with nothing switched
    on, which is different from the mod being absent, and the two must not be
    confused: absent means unlink it.
    """

    name: str
    parts: dict[str, list[str]] = field(default_factory=dict)
    saved: str = ""

    @property
    def size(self) -> int:
        return len(self.parts)

    def to_json(self) -> dict:
        return {"name": self.name, "parts": self.parts, "saved": self.saved}

    @classmethod
    def from_json(cls, data: dict) -> Profile:
        return cls(
            name=str(data["name"]),
            parts={
                str(slug): [str(label) for label in labels]
                for slug, labels in dict(data.get("parts", {})).items()
            },
            saved=str(data.get("saved", "")),
        )


@dataclass(slots=True)
class Applied:
    """What changed when a profile was applied."""

    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.linked)} on", f"{len(self.unlinked)} off"]
        if self.unchanged:
            parts.append(f"{len(self.unchanged)} unchanged")
        if self.missing:
            parts.append(f"{len(self.missing)} missing")
        if self.problems:
            parts.append(f"{len(self.problems)} failed")
        return ", ".join(parts)


def clean_name(raw: str) -> str:
    name = NAME.sub(" ", raw).strip()[:MAX_NAME]
    if not name:
        raise ProfileError("a profile needs a name")
    return name


def capture(name: str, mods: list[Mod]) -> Profile:
    """Record what is deployed right now."""
    parts = {
        mod.slug: [component.label for component in mod.active]
        for mod in mods
        if mod.state is State.INSTALLED
    }
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    return Profile(name=clean_name(name), parts=parts, saved=stamp)


def apply(profile: Profile, mods: list[Mod], mods_dir: Path) -> Applied:
    """Make the game folder match the profile.

    Mods the profile does not name are unlinked but keep their extracted files,
    so switching back costs no extraction. A mod the profile names that is no
    longer in the library is reported rather than silently dropped — the user
    chose it once and deserves to know it has gone.
    """
    result = Applied()
    by_slug = {mod.slug: mod for mod in mods}

    for slug in profile.parts:
        if slug not in by_slug:
            result.missing.append(slug)

    for mod in mods:
        wanted = profile.parts.get(mod.slug)

        if wanted is None:
            if mod.state is State.INSTALLED:
                try:
                    installer.unlink(mod, mods_dir)
                    result.unlinked.append(mod.slug)
                except OSError as error:
                    result.problems.append(f"{mod.title}: {error}")
            continue

        chosen = set(wanted)
        # Both sides sorted, because component order is a display concern and
        # comparing it unsorted would relink a mod that has not changed.
        already = mod.state is State.INSTALLED and sorted(
            item.label for item in mod.active
        ) == sorted(chosen)
        for component in mod.components:
            component.enabled = component.label in chosen
        # A profile is a file, and a file can be edited or can predate a mod
        # being re-downloaded with different parts. Narrowing here means a
        # stored selection that names two parts writing one asset cannot put
        # both of them in the game folder.
        dropped = components.resolve(mod.components)
        for component in dropped:
            result.problems.append(
                f"{mod.title}: {component.label} left off, it overwrites another part"
            )

        if already:
            result.unchanged.append(mod.slug)
            continue

        try:
            # Overwrite, because a profile is a deliberate statement about what
            # should be running; a name held by a mod this profile drops is
            # about to be released anyway.
            installer.install(mod, mods_dir, overwrite=True)
            result.linked.append(mod.slug)
        except Exception as error:  # noqa: BLE001 - one mod must not end the switch
            result.problems.append(f"{mod.title}: {type(error).__name__}: {error}")

    return result


class ProfileStore:
    """The saved profiles, on disk."""

    def __init__(self, profiles: list[Profile] | None = None) -> None:
        self.profiles: list[Profile] = profiles or []

    @classmethod
    def load(cls) -> ProfileStore:
        if not PROFILES_FILE.is_file():
            return cls()
        try:
            data = json.loads(PROFILES_FILE.read_text())
        except (OSError, ValueError):
            # A broken file must not stop the tool from starting. Losing the
            # profiles is recoverable; refusing to open is not.
            return cls()
        return cls([Profile.from_json(item) for item in data.get("profiles", [])])

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"profiles": [item.to_json() for item in self.profiles]}
        temporary = PROFILES_FILE.with_suffix(".json.new")
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(PROFILES_FILE)

    def get(self, name: str) -> Profile | None:
        wanted = clean_name(name).lower()
        return next(
            (item for item in self.profiles if item.name.lower() == wanted), None
        )

    def put(self, profile: Profile) -> None:
        """Add or replace by name, keeping the list sorted for display."""
        self.profiles = [
            item for item in self.profiles if item.name.lower() != profile.name.lower()
        ]
        self.profiles.append(profile)
        self.profiles.sort(key=lambda item: item.name.lower())

    def remove(self, name: str) -> bool:
        wanted = clean_name(name).lower()
        before = len(self.profiles)
        self.profiles = [item for item in self.profiles if item.name.lower() != wanted]
        return len(self.profiles) != before

    @property
    def names(self) -> list[str]:
        return [item.name for item in self.profiles]
