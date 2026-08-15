"""Config mods: the ones that ship an ".ini" instead of a pak.

Not every mod is a pak. A whole category changes the game by adding a few lines
to its settings — turning off hero outlines, or fog, or the depth of field — and
those arrive as an "Engine.ini" with a couple of keys in it. The tool used to
call these "unsupported: no .pak file inside", which is true and useless: it
names what is absent rather than what the thing is.

They install differently, and the difference matters. A pak mod is a symlink
into a folder the game only reads, so it can be undone by deleting a link. A
config mod has to write into a file the game owns and rewrites, beside settings
the user chose themselves. So:

- only the keys the mod names are touched, never the whole file;
- whatever stood there before is recorded, so uninstalling puts it back rather
  than deleting a line the user wanted;
- the file is copied aside before the first change.

The format is Unreal's, which is INI-shaped but not INI: duplicate keys are
meaningful and `configparser` would collapse them. It is parsed by hand.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .paths import DATA_DIR

BACKUP_DIR = DATA_DIR / "backups"
KEEP_BACKUPS = 10

SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
SETTING = re.compile(r"^\s*(?P<key>[^;#=\[\s][^=]*?)\s*=\s*(?P<value>.*?)\s*$")


@dataclass(slots=True)
class Setting:
    """One key a config mod sets, and what stood there before it did."""

    section: str
    key: str
    value: str
    # None means the key was absent, so uninstalling removes the line rather
    # than writing an empty one.
    previous: str | None = None

    @property
    def label(self) -> str:
        return f"[{self.section}] {self.key} = {self.value}"

    def to_json(self) -> dict:
        return {
            "section": self.section,
            "key": self.key,
            "value": self.value,
            "previous": self.previous,
        }

    @classmethod
    def from_json(cls, data: dict) -> Setting:
        return cls(
            section=str(data["section"]),
            key=str(data["key"]),
            value=str(data.get("value", "")),
            previous=data.get("previous"),
        )


def parse(text: str) -> list[Setting]:
    """Read the settings out of an Unreal config file.

    Comment and blank lines are skipped. A key outside any section is skipped
    too: Unreal ignores it, and guessing a section for it would put a setting
    somewhere the author did not ask for.
    """
    found: list[Setting] = []
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in ";#":
            continue
        if match := SECTION.match(line):
            section = match.group("name").strip()
            continue
        if not section:
            continue
        if match := SETTING.match(line):
            found.append(Setting(section, match.group("key"), match.group("value")))
    return found


def read(path: Path) -> str:
    if not path.is_file():
        return ""
    # The game writes this file; another program's bytes must survive a rewrite.
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def current_value(text: str, section: str, key: str) -> str | None:
    """What the file says for one key, or None when it does not say."""
    in_section = False
    for line in text.splitlines():
        if match := SECTION.match(line):
            in_section = match.group("name").strip().lower() == section.lower()
            continue
        if not in_section:
            continue
        if match := SETTING.match(line):
            if match.group("key").strip().lower() == key.lower():
                return match.group("value")
    return None


def _set(text: str, section: str, key: str, value: str | None) -> str:
    """Return the text with one key set, or removed when the value is None."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    done = False
    section_seen = False

    for line in lines:
        if match := SECTION.match(line):
            if in_section and not done and value is not None:
                # Leaving the section without having found the key: add it at
                # the end of the section rather than at the end of the file,
                # where it would belong to whatever section came last. Above
                # any blank lines, so the gap goes on separating the sections
                # instead of ending up in the middle of one.
                blanks = 0
                while out and not out[-1].strip():
                    out.pop()
                    blanks += 1
                out.append(f"{key}={value}")
                out += [""] * blanks
                done = True
            in_section = match.group("name").strip().lower() == section.lower()
            section_seen = section_seen or in_section
            out.append(line)
            continue

        if in_section and not done:
            if (match := SETTING.match(line)) and match.group(
                "key"
            ).strip().lower() == key.lower():
                done = True
                if value is not None:
                    out.append(f"{key}={value}")
                continue  # dropping the line is how a removal happens
        out.append(line)

    if not done and value is not None:
        if not section_seen:
            if out and out[-1].strip():
                out.append("")
            out.append(f"[{section}]")
        out.append(f"{key}={value}")

    return "\n".join(out).rstrip("\n") + "\n"


def backup(path: Path) -> Path | None:
    """Copy the settings file aside. None when there was nothing to copy."""
    if not path.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}"
    shutil.copy2(path, target)

    kept = sorted(BACKUP_DIR.glob(f"{path.stem}-*{path.suffix}"))
    for stale in kept[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
    return target


def apply(settings: list[Setting], path: Path) -> None:
    """Write the mod's settings, remembering what each one replaced."""
    text = read(path)
    backup(path)
    for setting in settings:
        # Recorded now, from the file as it stands, so an uninstall restores
        # what the user had rather than what the mod assumed they had.
        setting.previous = current_value(text, setting.section, setting.key)
        text = _set(text, setting.section, setting.key, setting.value)
    _write(path, text)


def revoke(settings: list[Setting], path: Path) -> None:
    """Undo the mod's settings, putting back whatever they replaced."""
    if not path.is_file():
        return
    text = read(path)
    backup(path)
    for setting in settings:
        if current_value(text, setting.section, setting.key) != setting.value:
            # Someone changed it since. Theirs to keep — a mod being removed
            # does not entitle it to overwrite a later decision.
            continue
        text = _set(text, setting.section, setting.key, setting.previous)
    _write(path, text)


def is_applied(settings: list[Setting], path: Path) -> bool:
    """True when every one of the mod's settings is in force."""
    if not settings:
        return False
    text = read(path)
    return all(
        current_value(text, item.section, item.key) == item.value for item in settings
    )


def _write(path: Path, text: str) -> None:
    """Replace the file in one step, so a crash cannot leave it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".regalia-new")
    temporary.write_text(text, encoding="utf-8", errors="surrogateescape")
    temporary.replace(path)
