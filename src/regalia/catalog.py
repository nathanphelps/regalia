"""Build and persist the list of known mods."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import archive, naming
from .model import Mod, NexusInfo, State
from .paths import CATALOG_FILE, DATA_DIR, STORE_DIR

CATALOG_VERSION = 2


class Catalog:
    def __init__(self, mods: list[Mod] | None = None) -> None:
        self.mods: list[Mod] = mods or []
        self.patch_archive: Path | None = None
        # Maps "<size>:<mtime>" to a digest, so an unchanged archive is hashed
        # once and never again.
        self.md5_cache: dict[str, str] = {}

    # -- persistence ----------------------------------------------------

    @classmethod
    def load(cls) -> Catalog:
        if not CATALOG_FILE.is_file():
            return cls()
        data = json.loads(CATALOG_FILE.read_text())
        # A version 1 file simply lacks the Nexus fields. It loads as it is and
        # gains them on the next scan.
        catalog = cls([Mod.from_json(item) for item in data.get("mods", [])])
        catalog.md5_cache = dict(data.get("md5_cache", {}))
        return catalog

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CATALOG_VERSION,
            "mods": [mod.to_json() for mod in self.mods],
            "md5_cache": self.md5_cache,
        }
        CATALOG_FILE.write_text(json.dumps(payload, indent=2))

    # -- scanning -------------------------------------------------------

    def rescan(self, scan_dirs: list[Path], mods_dir: Path) -> list[str]:
        """Rebuild the mod list from the scan directories.

        Install state is kept for mods that are already known, then checked
        against the game folder. Returns log lines for the LOG tab.
        """
        previous = {mod.source: mod for mod in self.mods}
        claimed: dict[str, Path] = {}
        log: list[str] = []
        found: list[Mod] = []
        self.patch_archive = None

        for path in archive.find_archives(scan_dirs):
            entries = archive.list_entries(path)
            if not entries:
                log.append(f"unreadable: {path.name}")
                continue

            if archive.looks_like_patch(entries):
                self.patch_archive = path
                log.append(f"patch archive: {path.name}")
                continue

            parsed = naming.parse(path.name)
            slug = self._unique_slug(parsed, path, claimed)
            files = archive.mod_files(entries)

            # An archive is identified by its path, not by its slug. Two files
            # can describe the same hero, variant and version, and keying the
            # carried-over state by slug then handed one record to both, which
            # put the same object in the list twice.
            mod = previous.get(path) or Mod(
                slug=slug,
                hero=parsed.hero,
                variant=parsed.variant,
                version=parsed.version,
                nexus_id=parsed.nexus_id,
                source=path,
                size=0,
            )
            mod.slug = slug
            mod.source = path
            mod.hero = parsed.hero
            mod.variant = parsed.variant
            mod.version = parsed.version
            mod.nexus_id = parsed.nexus_id
            mod.size = sum(entry.size for entry in files)

            if not files:
                mod.state = State.UNSUPPORTED
                mod.note = "no .pak file inside"
                log.append(f"unsupported: {path.name} — no .pak inside")
            else:
                mod.files = [Path(entry.name).name for entry in files]
                # The inner pak name decides load order, not the archive name.
                mod.has_load_order = any(
                    naming.LOAD_ORDER_SUFFIX.search(name) for name in mod.files
                )
                if mod.state is State.UNSUPPORTED:
                    mod.state = State.AVAILABLE

            found.append(mod)

        self.mods = sorted(found, key=lambda m: (m.hero, m.variant))
        log += self.verify(mods_dir)
        return log

    @staticmethod
    def _unique_slug(
        parsed: naming.ParsedName, path: Path, claimed: dict[str, Path]
    ) -> str:
        """A stable directory name that no other archive shares.

        The readable form is kept while it is free, so store directories made by
        earlier runs still match. When two archives describe the same hero,
        variant and version, the later one gains a short digest of its file name.
        A repeated slug would give two mods one store directory and one row key.
        """
        base = naming.slugify(f"{parsed.hero}-{parsed.variant}-{parsed.version or ''}")
        if claimed.get(base) in (None, path):
            claimed[base] = path
            return base

        digest = hashlib.sha1(path.name.encode()).hexdigest()[:6]
        slug = f"{base}-{digest}"
        claimed[slug] = path
        return slug

    # -- state checks ---------------------------------------------------

    def verify(self, mods_dir: Path) -> list[str]:
        """Reconcile recorded state with what is actually on disk.

        A game update can delete the "~mods" folder. The store still holds the
        files, so the tool reports the mods as broken and offers a repair.
        """
        log: list[str] = []
        for mod in self.mods:
            if mod.state is State.UNSUPPORTED:
                continue
            store = STORE_DIR / mod.slug
            extracted = store.is_dir() and any(store.iterdir())
            linked = extracted and all(
                (mods_dir / name).is_symlink() for name in mod.files
            )

            if not extracted:
                mod.state = State.AVAILABLE
            elif linked:
                mod.state = State.INSTALLED
            elif mod.state in (State.INSTALLED, State.BROKEN):
                # The links vanished under a mod that was linked. A game update
                # deleted them.
                mod.state = State.BROKEN
                log.append(f"broken links: {mod.title}")
            else:
                # Extracted but never linked into this game folder, which also
                # covers a switch to a different game directory.
                mod.state = State.DISABLED
        return log

    # -- nexus ----------------------------------------------------------

    def apply_nexus(self, matches: dict[Path, object], digests: dict[Path, str]) -> int:
        """Merge hash results into the catalog.

        Nexus wins where Nexus knows better: version, ids, and author are facts
        it owns. The hero stays with the local parser because Nexus has no such
        field, but the parser is re-run on the Nexus names, which are cleaner
        than a file name a browser may have renamed.
        """
        from .nexus.identify import cache_key

        applied = 0
        by_source = {mod.source: mod for mod in self.mods}

        for path, digest in digests.items():
            if mod := by_source.get(path):
                mod.md5 = digest
            # Remember the digest against the file's size and time so that an
            # unchanged archive is never read again. Without this every scan
            # would re-hash the whole library.
            try:
                self.md5_cache[cache_key(path)] = digest
            except OSError:
                pass

        for path, match in matches.items():
            mod = by_source.get(path)
            if mod is None:
                continue

            existing = mod.nexus
            mod.nexus = NexusInfo(
                mod_id=match.mod_id,
                file_id=match.file_id,
                mod_name=match.mod_name,
                file_name=match.file_label,
                author=match.author,
                version=match.file_version,
                adult=match.adult,
                verified=True,
                latest_file_id=existing.latest_file_id if existing else None,
                latest_version=existing.latest_version if existing else None,
            )
            mod.nexus_id = str(match.mod_id)
            if match.file_version:
                mod.version = match.file_version

            # Re-parse the hero from the Nexus mod name and the variant from the
            # Nexus file name. Both are more reliable than the archive name.
            from_mod = naming.parse(match.mod_name)
            if from_mod.hero != "Unknown":
                mod.hero = from_mod.hero
                from_file = naming.parse(match.file_label)
                if from_file.hero == from_mod.hero and from_file.variant:
                    mod.variant = from_file.variant
                elif from_mod.variant:
                    mod.variant = from_mod.variant
            applied += 1

        self.mods.sort(key=lambda m: (m.hero, m.variant))
        return applied

    def apply_updates(self, updates: dict[int, object]) -> int:
        """Record which mods have a newer file on Nexus."""
        marked = 0
        for mod in self.mods:
            if not mod.nexus:
                continue
            if update := updates.get(mod.nexus.mod_id):
                mod.nexus.latest_file_id = update.latest_file_id
                mod.nexus.latest_version = update.latest_version
                marked += 1
        return marked

    def owned_mod_ids(self) -> dict[int, int | None]:
        """Every known Nexus mod id, mapped to the file id held."""
        owned: dict[int, int | None] = {}
        for mod in self.mods:
            if mod.nexus:
                owned[mod.nexus.mod_id] = mod.nexus.file_id
            elif mod.nexus_id and mod.nexus_id.isdigit():
                owned.setdefault(int(mod.nexus_id), None)
        return owned

    def held_files(self) -> set[tuple[int, int]]:
        """The mod and file pairs already present, for collection planning."""
        return {
            (mod.nexus.mod_id, mod.nexus.file_id)
            for mod in self.mods
            if mod.nexus and mod.nexus.file_id
        }

    def tag_collection(
        self, slug: str, paths: set[Path], pairs: set[tuple[int, int]] | None = None
    ) -> None:
        """Record that these mods arrived with a collection.

        Archives are matched by path, which is known the moment they are
        downloaded. Matching on Nexus ids would tag nothing, because a fresh
        archive has no Nexus record until it is identified, and the conflict
        rule that exempts members of one collection would then never fire.
        """
        pairs = pairs or set()
        for mod in self.mods:
            member = mod.source in paths
            if not member and mod.nexus and mod.nexus.file_id:
                member = (mod.nexus.mod_id, mod.nexus.file_id) in pairs
            if member and slug not in mod.collections:
                mod.collections.append(slug)

    def in_collection(self, slug: str) -> list[Mod]:
        return [mod for mod in self.mods if slug in mod.collections]

    # -- queries --------------------------------------------------------

    def by_slug(self, slug: str) -> Mod | None:
        return next((mod for mod in self.mods if mod.slug == slug), None)

    def search(self, query: str) -> list[Mod]:
        if not query.strip():
            return self.mods
        needle = query.lower()
        return [
            mod
            for mod in self.mods
            if needle in mod.hero.lower()
            or needle in mod.variant.lower()
            or needle in mod.source.name.lower()
        ]

    @property
    def installed_count(self) -> int:
        return sum(1 for mod in self.mods if mod.state is State.INSTALLED)
