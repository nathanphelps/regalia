"""Turn a mod archive file name into a hero, a variant, and a version.

Mod authors use several naming conventions. The parser removes the parts that the
download site adds, then looks for a hero name in what remains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .heroes import NOISE_WORDS, _key, alias_index

# Nexus appends the mod id, the version parts, and a Unix timestamp.
# Example: "-2519-1-1-0-1751818210"
NEXUS_TAIL = re.compile(r"-(\d+)(?:-\d+){2,}-(\d{10})$")

# The current Nexus download name appends the mod id, the version, an upload
# time, and a random token. The version may carry dots.
# Examples: " 12021 1 2026-08-13T22-53Z sMEtcBCrC"
#           " 9652 1.2 2026-06-21T15-40Z KVc4D2Ocs"
ALT_TAIL = re.compile(
    r"\s+(\d{2,7})\s+(\d+(?:\.\d+)*)\s+\d{4}-\d{2}-\d{2}T\d{2}-\d{2}Z\s+\S+$"
)

# The boundaries are spelled out rather than written as \b, because "_" counts
# as a word character. With \b, "Loki_V1.2.0" matched at the "2" and reported
# the version as "2.0".
VERSION = re.compile(
    r"(?<![0-9A-Za-z])v?(\d+\.\d+(?:\.\d+)*)(?![0-9A-Za-z])", re.IGNORECASE
)

# Unreal loads "~mods" alphabetically. "_P" marks a patch pak and the large number
# forces it to sort last, so the mod overrides the base game.
LOAD_ORDER_SUFFIX = re.compile(r"_9{4,}_P\b", re.IGNORECASE)

SEPARATORS = re.compile(r"[\s_\-.]+")
SUBTOKENS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")


@dataclass(frozen=True, slots=True)
class ParsedName:
    hero: str
    variant: str
    version: str | None
    nexus_id: str | None
    has_load_order: bool

    @property
    def title(self) -> str:
        return f"{self.hero} — {self.variant}" if self.variant else self.hero


def _is_random_token(group: str) -> bool:
    """True for upload ids such as "sMEtcBCrC" or "HT9vBGmku".

    Those strings mix case more often than real words do. A compound word such as
    "BloodMoon" also mixes case, so a plain case-change count is not enough. An
    upload id either buries a digit inside mixed-case letters, or changes case
    more times than any compound word does.
    """
    if len(group) < 6 or not group.isalnum():
        return False
    has_upper = any(ch.isupper() for ch in group)
    has_lower = any(ch.islower() for ch in group)
    if not (has_upper and has_lower):
        return False
    if any(ch.isdigit() for ch in group):
        return True
    transitions = sum(
        1
        for a, b in zip(group, group[1:], strict=False)
        if a.isalpha() and b.isalpha() and a.isupper() != b.isupper()
    )
    return transitions >= 5


def _strip_tails(stem: str) -> tuple[str, str | None, str | None]:
    """Remove the download-site suffix. Return the name, the mod id, the version."""
    nexus_id: str | None = None
    version: str | None = None

    if match := NEXUS_TAIL.search(stem):
        nexus_id = match.group(1)
        stem = stem[: match.start()]
    elif match := ALT_TAIL.search(stem):
        nexus_id = match.group(1)
        version = match.group(2)
        stem = stem[: match.start()]

    if match := VERSION.search(stem):
        version = match.group(1)
        stem = stem[: match.start()] + stem[match.end() :]

    return stem.strip(" -_"), nexus_id, version


def parse(filename: str) -> ParsedName:
    """Parse an archive file name."""
    stem = re.sub(r"\.(7z|zip|rar)$", "", filename, flags=re.IGNORECASE)
    stem, nexus_id, version = _strip_tails(stem)

    has_load_order = bool(LOAD_ORDER_SUFFIX.search(stem))
    stem = LOAD_ORDER_SUFFIX.sub("", stem)

    # Split into groups on separators, then into subtokens on case changes.
    # Groups are kept so that "BloodMoon" survives as one word after the hero
    # name is removed from a neighbouring group.
    groups = [g for g in SEPARATORS.split(stem) if g]
    tokens: list[tuple[int, str]] = [
        (index, sub)
        for index, group in enumerate(groups)
        for sub in SUBTOKENS.findall(group)
    ]

    hero, consumed = _match_hero(tokens)

    kept: dict[int, list[str]] = {}
    for position, (group_index, token) in enumerate(tokens):
        if position in consumed or token.lower() in NOISE_WORDS:
            continue
        kept.setdefault(group_index, []).append(token)

    parts = ["".join(subs) for _, subs in sorted(kept.items())]
    parts = [
        part
        for part in parts
        if not part.isdigit() and not _is_random_token(part) and len(part) > 1
    ]

    if hero is None:
        # No hero matched. Keep the whole name rather than guess at a variant.
        return ParsedName(
            "Unknown", " ".join(groups), version, nexus_id, has_load_order
        )

    return ParsedName(hero, " · ".join(parts), version, nexus_id, has_load_order)


def _match_hero(tokens: list[tuple[int, str]]) -> tuple[str | None, set[int]]:
    """Find the longest hero alias spanning consecutive tokens.

    Returns the hero and the token positions it used.
    """
    keys = [_key(token) for _, token in tokens]
    best: tuple[int, str, set[int]] | None = None
    index = alias_index()

    for start in range(len(tokens)):
        joined = ""
        for end in range(start, min(start + 4, len(tokens))):
            joined += keys[end]
            for alias_key, canonical in index:
                if alias_key != joined:
                    continue
                span = set(range(start, end + 1))
                if best is None or len(alias_key) > best[0]:
                    best = (len(alias_key), canonical, span)
                break

    if best is None:
        return None, set()
    return best[1], best[2]


def slugify(text: str) -> str:
    """Make a stable directory name."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "mod"
