"""Find out which local mods have a newer file on Nexus."""

from __future__ import annotations

from dataclasses import dataclass

from .client import NexusClient
from .models import NexusFile


@dataclass(frozen=True, slots=True)
class Update:
    mod_id: int
    current_file_id: int | None
    latest_file_id: int
    latest_version: str | None
    latest_name: str
    size: int


def newest_file(files: list[NexusFile]) -> NexusFile | None:
    """Pick the file a user would download today.

    Old and archived files are skipped. Among the rest the newest upload wins,
    because version numbers are free text and cannot be ordered reliably.
    """
    live = [file for file in files if file.is_current]
    if not live:
        return None
    main = [file for file in live if file.is_main] or live
    return max(main, key=lambda file: (file.uploaded, file.file_id))


def check(
    client: NexusClient,
    owned: dict[int, int | None],
    period: str = "1m",
) -> dict[int, Update]:
    """Report the owned mods that have a newer file.

    `owned` maps a mod id to the file id held locally, or None when unknown.

    One request returns every mod in the game that changed in the period. The
    library is then filtered locally, so the cost does not grow with the number
    of mods held.
    """
    if not owned:
        return {}

    changed = client.updated_since(period)
    candidates = [mod_id for mod_id in owned if mod_id in changed]

    updates: dict[int, Update] = {}
    for mod_id in candidates:
        newest = newest_file(client.files(mod_id))
        if newest is None:
            continue
        current = owned[mod_id]
        if current is not None and newest.file_id <= current:
            continue
        updates[mod_id] = Update(
            mod_id=mod_id,
            current_file_id=current,
            latest_file_id=newest.file_id,
            latest_version=newest.version,
            latest_name=newest.name,
            size=newest.size,
        )
    return updates
