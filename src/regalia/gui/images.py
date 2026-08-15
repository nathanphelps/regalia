"""Asynchronous, disk-backed Nexus image loading."""

from __future__ import annotations

import hashlib
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage

from ..nexus.client import USER_AGENT
from ..paths import image_cache_dir


class ImageSignals(QObject):
    loaded = Signal(str, QImage, bool, int)
    failed = Signal(str)


class ImageJob(QRunnable):
    def __init__(self, url: str, path: Path) -> None:
        super().__init__()
        self.url = url
        self.path = path
        self.signals = ImageSignals()

    @Slot()
    def run(self) -> None:
        try:
            disk_hit = self.path.is_file()
            if not disk_hit:
                request = urllib.request.Request(
                    self.url, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                partial = self.path.with_suffix(".part")
                partial.write_bytes(data)
                partial.replace(self.path)
            else:
                self.path.touch()
            image = QImage(str(self.path))
            if image.isNull():
                self.path.unlink(missing_ok=True)
                raise ValueError("unsupported image")
            try:
                self.signals.loaded.emit(
                    self.url, image, disk_hit, self.path.stat().st_size
                )
            except RuntimeError:
                pass  # the application closed while the image was decoding
        except Exception:  # noqa: BLE001 - any decoder/network failure is a fallback
            try:
                self.signals.failed.emit(self.url)
            except RuntimeError:
                pass


@dataclass(frozen=True, slots=True)
class CacheStats:
    memory_hits: int
    disk_hits: int
    network_fetches: int
    failures: int
    network_bytes: int
    memory_items: int
    pending: int


class ImageCache(QObject):
    image_ready = Signal(str, QImage)
    image_failed = Signal(str)
    changed = Signal()

    def __init__(self, limit_mb: int = 1024, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.root = image_cache_dir()
        self.limit = limit_mb * 1024 * 1024
        self.memory_limit = min(self.limit // 4, 256 * 1024 * 1024)
        self.pool = QThreadPool.globalInstance()
        self.memory: OrderedDict[str, QImage] = OrderedDict()
        self.pending: set[str] = set()
        self._jobs: dict[str, ImageJob] = {}
        self.memory_hits = 0
        self.disk_hits = 0
        self.network_fetches = 0
        self.failures = 0
        self.network_bytes = 0

    def request(self, url: str, width: int, height: int) -> QImage | None:
        if not url:
            return None
        if url in self.memory:
            self.memory_hits += 1
            self.memory.move_to_end(url)
            return self.memory[url]
        if url in self.pending:
            return None
        digest = hashlib.sha256(url.encode()).hexdigest()
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            suffix = ".img"
        path = self.root / digest[:2] / f"{digest}{suffix}"
        job = ImageJob(url, path)
        self.pending.add(url)
        self._jobs[url] = job
        job.signals.loaded.connect(
            lambda loaded_url, image, disk_hit, size: self._loaded(
                loaded_url, image, disk_hit, size
            )
        )
        job.signals.failed.connect(self._failed)
        self.pool.start(job)
        return None

    def _loaded(self, url: str, image: QImage, disk_hit: bool, size: int) -> None:
        self.pending.discard(url)
        self._jobs.pop(url, None)
        self.memory[url] = image
        if disk_hit:
            self.disk_hits += 1
        else:
            self.network_fetches += 1
            self.network_bytes += size
        self.image_ready.emit(url, image)
        self._trim_memory()
        self._trim()
        self.changed.emit()

    def _failed(self, url: str) -> None:
        self.pending.discard(url)
        self._jobs.pop(url, None)
        self.failures += 1
        self.image_failed.emit(url)
        self.changed.emit()

    @property
    def stats(self) -> CacheStats:
        return CacheStats(
            memory_hits=self.memory_hits,
            disk_hits=self.disk_hits,
            network_fetches=self.network_fetches,
            failures=self.failures,
            network_bytes=self.network_bytes,
            memory_items=len(self.memory),
            pending=len(self.pending),
        )

    def disk_usage(self) -> tuple[int, int]:
        if not self.root.is_dir():
            return 0, 0
        files = [
            path
            for path in self.root.rglob("*")
            if path.is_file() and path.suffix != ".part"
        ]
        return len(files), sum(path.stat().st_size for path in files)

    def set_limit(self, limit_mb: int) -> None:
        self.limit = limit_mb * 1024 * 1024
        self.memory_limit = min(self.limit // 4, 256 * 1024 * 1024)
        self._trim_memory()
        self._trim()
        self.changed.emit()

    def clear(self) -> tuple[int, int]:
        self.memory.clear()
        count = 0
        size = 0
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if not path.is_file() or path.suffix == ".part":
                    continue
                try:
                    file_size = path.stat().st_size
                    path.unlink()
                except OSError:
                    continue
                count += 1
                size += file_size
        self.changed.emit()
        return count, size

    def _trim(self) -> None:
        if not self.root.is_dir():
            return
        files = [
            path
            for path in self.root.rglob("*")
            if path.is_file() and path.suffix != ".part"
        ]
        total = sum(path.stat().st_size for path in files)
        if total <= self.limit:
            return
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            try:
                size = path.stat().st_size
                path.unlink()
                total -= size
            except OSError:
                continue
            if total <= self.limit:
                break

    def _trim_memory(self) -> None:
        total = sum(image.sizeInBytes() for image in self.memory.values())
        while self.memory and total > self.memory_limit:
            _, image = self.memory.popitem(last=False)
            total -= image.sizeInBytes()
