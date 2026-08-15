"""Install a whole collection.

A collection is a curated list of mod files. The popular ones for this game hold
between 137 and 216 mods, so the run is long, partly redundant with what is
already held, and must survive individual failures.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .client import NexusClient
from .download import Cancelled, download_file
from .models import Collection, CollectionMod

CONCURRENCY = 3
RETRIES = 2


@dataclass(slots=True)
class Plan:
    """What an install run will actually do."""

    collection: Collection
    wanted: list[CollectionMod]
    already_held: list[CollectionMod] = field(default_factory=list)

    @property
    def to_download(self) -> list[CollectionMod]:
        """The members still to fetch, each one only once.

        A manifest can name the same file twice. Downloading it twice at the
        same time would have two workers writing one path.
        """
        held = {(mod.mod_id, mod.file_id) for mod in self.already_held}
        seen: set[tuple[int, int]] = set()
        unique: list[CollectionMod] = []
        for mod in self.wanted:
            key = (mod.mod_id, mod.file_id)
            if key in held or key in seen:
                continue
            seen.add(key)
            unique.append(mod)
        return unique

    @property
    def download_bytes(self) -> int:
        return sum(mod.size for mod in self.to_download)

    @property
    def size_label(self) -> str:
        gb = self.download_bytes / 2**30
        if gb >= 1:
            return f"{gb:,.2f} GB"
        return f"{self.download_bytes / 2**20:,.0f} MB"


@dataclass(slots=True)
class Outcome:
    downloaded: list[Path] = field(default_factory=list)
    skipped: list[CollectionMod] = field(default_factory=list)
    failed: list[tuple[CollectionMod, str]] = field(default_factory=list)
    cancelled: bool = False
    # Filled in by `deploy`, which runs after the caller has rescanned.
    installed: int = 0
    problems: list[str] = field(default_factory=list)


def plan(
    collection: Collection,
    include_optional: set[int] | None = None,
    held: set[tuple[int, int]] | None = None,
) -> Plan:
    """Decide what to fetch.

    Optional members are left out unless chosen. Anything already held is
    counted as done, so a second collection that overlaps the first costs only
    the difference.
    """
    include_optional = include_optional or set()
    held = held or set()

    wanted = [
        mod
        for mod in collection.mods
        if not mod.optional or mod.file_id in include_optional
    ]
    already = [mod for mod in wanted if (mod.mod_id, mod.file_id) in held]
    return Plan(collection=collection, wanted=wanted, already_held=already)


def resolve_file_id(mod: CollectionMod) -> int:
    """Pick the file to fetch for one member: the one the manifest names.

    The update policy is recorded but never used to fetch a different file. One
    mod page usually holds many unrelated files rather than a chain of versions.
    Page 5095, for example, offers eight body variants and two add-ons, and this
    collection picks three of them. Reading "prefer" as "take the newest file on
    the page" turned those three separate choices into three copies of one file,
    which both discards what the curator tested and makes several members race
    for the same download.

    A newer file is still reported, through the update check, where the person
    can see what changed and decide.
    """
    return mod.file_id


def fetch(
    client: NexusClient,
    plan: Plan,
    destination: Path,
    on_item: Callable[[int, int, CollectionMod], None] | None = None,
    on_bytes: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Outcome:
    """Download every member of the plan into the library.

    Members download a few at a time. A failure is retried, then recorded, and
    the run continues; one bad member must not abandon the other hundred.

    Downloading is only half of installing a collection. `deploy` does the rest,
    and the two are separate because the catalog has to see the new archives in
    between.
    """
    outcome = Outcome()
    outcome.skipped = list(plan.already_held)

    targets = plan.to_download
    total = len(targets)
    if not total:
        return outcome

    done_bytes = 0
    counter = 0
    lock = threading.Lock()

    def stop() -> bool:
        return bool(cancelled and cancelled())

    def one(mod: CollectionMod) -> None:
        nonlocal done_bytes, counter
        if stop():
            return
        with lock:
            counter += 1
            index = counter
        if on_item:
            on_item(index, total, mod)

        last_error = ""
        for attempt in range(RETRIES + 1):
            if stop():
                return
            try:
                file_id = resolve_file_id(mod)
                path = download_file(
                    client,
                    mod.mod_id,
                    file_id,
                    destination,
                    file_name=mod.file_name,
                    cancelled=cancelled,
                )
                with lock:
                    outcome.downloaded.append(path)
                    done_bytes += mod.size
                    if on_bytes:
                        on_bytes(done_bytes, plan.download_bytes)
                return
            except Cancelled:
                return
            except Exception as error:  # noqa: BLE001 - one member must not end the run
                # Every failure is caught, not only the ones this package
                # raises. A member that fails in an unforeseen way must not end
                # a run of a hundred others.
                last_error = f"{type(error).__name__}: {error}"
                if attempt == RETRIES:
                    with lock:
                        outcome.failed.append((mod, last_error))

    def guarded(mod: CollectionMod) -> None:
        try:
            one(mod)
        except BaseException as error:  # noqa: BLE001 - the pool must not stop
            with lock:
                outcome.failed.append((mod, f"{type(error).__name__}: {error}"))

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        # map() would re-raise the first failure and abandon the rest, so the
        # results are consumed only after every worker has finished.
        list(pool.map(guarded, targets))

    outcome.cancelled = stop()
    return outcome


def deploy(
    mods: list,
    downloaded: list[Path],
    mods_dir: Path,
    on_item: Callable[[int, int, str], None] | None = None,
) -> tuple[int, list[str]]:
    """Extract and link the mods a collection just brought in.

    Downloading a hundred archives and leaving them switched off is not what a
    user means by installing a collection. The caller rescans first, so the
    catalog holds a record for each new archive; this then installs the records
    whose archive is one of the downloads.

    Returns how many were installed and one line per failure. A member that
    cannot be installed must not abandon the rest, for the same reason a member
    that cannot be downloaded does not.
    """
    from .. import installer
    from ..model import State

    wanted = {path.resolve() for path in downloaded}
    targets = [
        mod
        for mod in mods
        if mod.state is not State.UNSUPPORTED and _resolved(mod.source) in wanted
    ]

    installed = 0
    problems: list[str] = []
    for index, mod in enumerate(targets, start=1):
        if on_item:
            on_item(index, len(targets), mod.title)
        try:
            # A curator picks overlapping mods on purpose, and the later member
            # is meant to win, so a name already taken is overwritten rather
            # than treated as an error.
            installer.install(mod, mods_dir, overwrite=True)
            installed += 1
        except Exception as error:  # noqa: BLE001 - one member must not end the run
            problems.append(f"{mod.title}: {type(error).__name__}: {error}")
    return installed, problems


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path
