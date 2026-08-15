"""Pages in the native Qt application."""

from __future__ import annotations

import html
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import (
    components,
    conflicts,
    credentials,
    installer,
    library,
    maintenance,
    nxm,
    patch,
    steam,
    variants,
)
from ..catalog import Catalog
from ..config import Config, suggested_import_dir
from ..model import Mod, State
from ..nexus import NexusClient, NexusFile, NexusImage, NexusMod, Page
from ..nexus import collections as collection_ops
from ..nexus.download import download_file
from ..paths import DATA_DIR, LIBRARY_DIR, GamePaths
from .images import ImageCache
from .state import GuiState
from .tasks import TaskCoordinator
from .widgets import (
    GalleryDialog,
    HorizontalRail,
    ImageTile,
    Paginator,
    StatCard,
    section_title,
)


def plain(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def human_size(size: int) -> str:
    if size >= 2**30:
        return f"{size / 2**30:,.2f} GiB"
    if size >= 2**20:
        return f"{size / 2**20:,.1f} MiB"
    return f"{size / 2**10:,.0f} KiB"


@dataclass(slots=True)
class Context:
    config: Config
    catalog: Catalog
    client: NexusClient
    tasks: TaskCoordinator
    images: ImageCache
    state: GuiState
    game: GamePaths | None
    game_error: str
    notify: Any
    refresh_all: Any
    # Look for Steam and the game again, after the user changes a path.
    rediscover: Any = None


class DashboardPage(QWidget):
    open_nexus_mod = Signal(int)
    open_page = Signal(str)

    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(0)
        body = QWidget()
        outer = QVBoxLayout(body)
        scroll.setWidget(body)
        shell.addWidget(scroll)
        heading = QLabel("COMMAND CENTER")
        heading.setObjectName("pageTitle")
        outer.addWidget(heading)
        outer.addWidget(QLabel("Local health and Nexus discovery at a glance."))

        stats = QHBoxLayout()
        self.installed = StatCard("Installed")
        self.updates = StatCard("Updates", accent="#e4b363")
        self.patch = StatCard("Patch", accent="#65c18c")
        self.game = StatCard("Game")
        for card in (self.installed, self.updates, self.patch, self.game):
            stats.addWidget(card)
        outer.addLayout(stats)

        outer.addWidget(section_title("Favorites"))
        self.favorites = HorizontalRail()
        outer.addWidget(self.favorites)
        outer.addWidget(section_title("Recently viewed"))
        self.viewed = HorizontalRail()
        outer.addWidget(self.viewed)
        outer.addWidget(section_title("Popular on Nexus"))
        self.popular = HorizontalRail()
        outer.addWidget(self.popular)
        outer.addWidget(section_title("Recently updated"))
        self.recent = HorizontalRail()
        outer.addWidget(self.recent)
        outer.addStretch()
        context.state.changed.connect(self.load_personal)
        self.refresh_local()

    def refresh_local(self) -> None:
        catalog = self.context.catalog
        self.installed.set_value(f"{catalog.installed_count} / {len(catalog.mods)}")
        update_count = sum(
            bool(mod.nexus and mod.nexus.has_update) for mod in catalog.mods
        )
        self.updates.set_value(str(update_count), "#e4b363")
        if self.context.game:
            state = patch.status(self.context.game)
            self.patch.set_value(
                "READY" if state.ready else state.summary.upper(),
                "#65c18c" if state.ready else "#e4b363",
            )
            self.game.set_value("FOUND", "#65c18c")
        else:
            self.patch.set_value("UNKNOWN", "#df6666")
            self.game.set_value("MISSING", "#df6666")

    def load_remote(self) -> None:
        self.load_personal()
        if self.popular.layout_.count() > 1:
            return

        def work(progress):
            progress(10, "Loading popular mods")
            popular = self.context.client.browse("downloads", 12)
            progress(60, "Loading recent mods")
            recent = self.context.client.browse("updatedAt", 12)
            return popular, recent

        self.context.tasks.submit(
            "Refresh dashboard",
            work,
            on_result=self._remote_ready,
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _remote_ready(self, result) -> None:
        popular, recent = result
        self._fill(self.popular, popular)
        self._fill(self.recent, recent)

    def load_personal(self) -> None:
        favorites = list(self.context.state.data.favorite_mod_ids)[:12]
        recent = self.context.state.data.recent_mod_ids[:12]

        def work(progress):
            def resolve(ids: list[int]) -> list[NexusMod]:
                return [
                    mod
                    for mod_id in ids
                    if (mod := self.context.client.mod(mod_id)) is not None
                ]

            return resolve(favorites), resolve(recent)

        if not favorites and not recent:
            self._fill_empty(self.favorites, "Star mods to keep them close")
            self._fill_empty(self.viewed, "Opened mods appear here")
            return
        self.context.tasks.submit(
            "Refresh personal Nexus shelves",
            work,
            on_result=lambda result: self._personal_ready(*result),
            on_error=lambda message, trace: None,
        )

    def _personal_ready(
        self, favorites: list[NexusMod], recent: list[NexusMod]
    ) -> None:
        if favorites:
            self._fill(self.favorites, favorites)
        else:
            self._fill_empty(self.favorites, "Star mods to keep them close")
        if recent:
            self._fill(self.viewed, recent)
        else:
            self._fill_empty(self.viewed, "Opened mods appear here")

    def _fill_empty(self, rail: HorizontalRail, message: str) -> None:
        rail.clear()
        tile = ImageTile(self.context.images, title=message, subtitle="NEXUS SHELF")
        tile.setFixedWidth(260)
        rail.add_tile(tile)

    def _fill(self, rail: HorizontalRail, mods: list[NexusMod]) -> None:
        rail.clear()
        for mod in mods:
            tile = ImageTile(
                self.context.images,
                mod.thumbnail_url or mod.picture_url,
                mod.name,
                f"{mod.author} · {mod.downloads_label} downloads",
            )
            tile.setFixedWidth(260)
            tile.clicked.connect(
                lambda mod_id=mod.mod_id: self.open_nexus_mod.emit(mod_id)
            )
            rail.add_tile(tile)


class VariantStudioDialog(QDialog):
    def __init__(self, context: Context, siblings: list[Mod], parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.siblings = siblings
        self.setWindowTitle("Variant studio")
        self.resize(900, 590)
        layout = QVBoxLayout(self)
        title = QLabel("VARIANT STUDIO")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        nexus_name = next(
            (
                mod.nexus.mod_name
                for mod in siblings
                if mod.nexus and mod.nexus.mod_name
            ),
            siblings[0].hero,
        )
        intro = QLabel(
            f"{nexus_name} · {len(siblings)} local choices · one active at a time"
        )
        intro.setObjectName("eyebrow")
        layout.addWidget(intro)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Variant", "Version", "State", "Archive", "Size", "Identity")
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_editor)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.label = QLineEdit()
        self.label.setPlaceholderText("Friendly local name (optional)")
        self.note = QTextEdit()
        self.note.setMaximumHeight(70)
        self.note.setPlaceholderText("Notes about this variant")
        form.addRow("Display name", self.label)
        form.addRow("Notes", self.note)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save = QPushButton("Save metadata")
        save.clicked.connect(self.save_metadata)
        reveal = QPushButton("Reveal archive")
        reveal.clicked.connect(self.reveal)
        activate = QPushButton("Make active")
        activate.clicked.connect(self.activate)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(save)
        buttons.addWidget(reveal)
        buttons.addStretch()
        buttons.addWidget(activate)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.populate()

    def selected(self) -> Mod | None:
        row = self.table.currentRow()
        if not 0 <= row < len(self.siblings):
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        slug = item.data(Qt.ItemDataRole.UserRole)
        return next((mod for mod in self.siblings if mod.slug == slug), None)

    def populate(self) -> None:
        selected_slug = self.selected().slug if self.selected() else ""
        self.siblings.sort(key=lambda mod: mod.display_variant.lower())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.siblings))
        for row, mod in enumerate(self.siblings):
            identity = "VERIFIED" if mod.verified else "UNVERIFIED"
            values = (
                mod.display_variant or "Default",
                mod.version_label,
                "ACTIVE" if mod.state is State.INSTALLED else mod.state.value.upper(),
                mod.source.name,
                mod.size_label,
                identity,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, mod.slug)
                if column == 2 and mod.state is State.INSTALLED:
                    item.setForeground(QColor("#65c18c"))
                self.table.setItem(row, column, item)
            if mod.slug == selected_slug or (not selected_slug and row == 0):
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.load_editor()

    def load_editor(self) -> None:
        mod = self.selected()
        self.label.setText(mod.custom_variant if mod else "")
        self.note.setPlainText(mod.variant_note if mod else "")

    def save_metadata(self) -> None:
        mod = self.selected()
        if mod is None:
            return
        mod.custom_variant = self.label.text().strip()
        mod.variant_note = self.note.toPlainText().strip()
        self.context.catalog.save()
        self.populate()
        self.context.notify(f"Saved metadata for {mod.display_variant or mod.hero}")

    def reveal(self) -> None:
        mod = self.selected()
        if mod:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(mod.source.parent)))

    def activate(self) -> None:
        mod = self.selected()
        if mod is None or mod.state is State.INSTALLED:
            return
        if self.context.game is None:
            self.context.notify(self.context.game_error or "Game not found", True)
            return
        try:
            variants.activate(mod, self.siblings, self.context.game.mods)
            self.context.catalog.save()
        except Exception as error:  # noqa: BLE001 - GUI action boundary
            self.context.notify(str(error), True)
            return
        self.populate()
        self.context.notify(f"Activated {mod.display_variant or mod.title}")
        self.context.refresh_all()


class LibraryPage(QWidget):
    open_nexus_mod = Signal(int)

    HEADERS = ("Hero", "Variant", "Version", "Size", "State", "Warnings")

    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        self.warnings: dict[str, list[conflicts.Warning_]] = {}
        self._nexus_covers: dict[int, NexusMod] = {}
        self._cover_slug = ""
        self._cover_timer = QTimer(self)
        self._cover_timer.setSingleShot(True)
        self._cover_timer.setInterval(180)
        self._cover_timer.timeout.connect(self._load_detail_cover)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        title = QLabel("LIBRARY")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search heroes, variants, and archives")
        self.search.setClearButtonEnabled(True)
        self.hero_filter = QComboBox()
        self.hero_filter.addItem("All heroes", "")
        self.state_filter = QComboBox()
        self.state_filter.addItems(
            ["All states", *[state.value.title() for state in State]]
        )
        self.issue_filter = QComboBox()
        self.issue_filter.addItem("Everything", "")
        self.issue_filter.addItem("Updates", "updates")
        self.issue_filter.addItem("Conflicts", "conflicts")
        self.issue_filter.addItem("Verified", "verified")
        self.issue_filter.addItem("Unverified", "unverified")
        self.issue_filter.addItem("Held", "held")
        self.issue_filter.addItem("Active", "active")
        self.grouped = QCheckBox("Group variants")
        self.grouped.setChecked(True)
        rescan = QPushButton("Rescan")
        identify = QPushButton("Identify with Nexus")
        updates = QPushButton("Check updates")
        rescan.clicked.connect(self.rescan)
        identify.clicked.connect(self.identify)
        updates.clicked.connect(self.check_updates)
        bar.addWidget(title)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.hero_filter)
        bar.addWidget(self.state_filter)
        bar.addWidget(self.issue_filter)
        bar.addWidget(self.grouped)
        bar.addWidget(rescan)
        bar.addWidget(identify)
        bar.addWidget(updates)
        layout.addLayout(bar)
        self.result_summary = QLabel()
        self.result_summary.setObjectName("eyebrow")
        layout.addWidget(self.result_summary)

        splitter = QSplitter()
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.refresh_detail)
        self.table.doubleClicked.connect(self.open_selected_nexus)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.cover = ImageTile(self.context.images, title="Select a mod")
        self.cover.setMinimumHeight(230)
        detail_layout.addWidget(self.cover)
        self.detail_title = QLabel("Select a mod")
        self.detail_title.setObjectName("detailTitle")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail)
        # The parts of one archive. Most mods have exactly one and the section
        # stays hidden; the ones that hold twenty-four are why it exists.
        self.parts_title = section_title("Parts of this mod")
        detail_layout.addWidget(self.parts_title)
        self.parts_hint = QLabel()
        self.parts_hint.setWordWrap(True)
        self.parts_hint.setObjectName("partsHint")
        detail_layout.addWidget(self.parts_hint)
        self.parts_list = QListWidget()
        self.parts_list.setMaximumHeight(210)
        self.parts_list.itemChanged.connect(self._part_toggled)
        detail_layout.addWidget(self.parts_list)

        detail_layout.addWidget(section_title("Variants and versions"))
        self.variant_list = QListWidget()
        self.variant_list.setMaximumHeight(190)
        detail_layout.addWidget(self.variant_list)
        activate_variant = QPushButton("Activate selected variant")
        activate_variant.clicked.connect(self.activate_variant)
        detail_layout.addWidget(activate_variant)
        manage_variants = QPushButton("Open variant studio…")
        manage_variants.clicked.connect(self.open_variant_studio)
        detail_layout.addWidget(manage_variants)
        actions = QGridLayout()
        for index, (label, slot) in enumerate(
            (
                ("Install", self.install),
                ("Enable", self.enable),
                ("Disable", self.disable),
                ("Uninstall", self.remove),
                ("Repair", self.repair),
                ("Open Nexus", self.open_selected_nexus),
            )
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button, index // 2, index % 2)
        detail_layout.addLayout(actions)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([850, 330])
        layout.addWidget(splitter, 1)
        self.search.textChanged.connect(self.refresh)
        self.hero_filter.currentIndexChanged.connect(self.refresh)
        self.state_filter.currentTextChanged.connect(self.refresh)
        self.issue_filter.currentIndexChanged.connect(self.refresh)
        self.grouped.toggled.connect(self.refresh)
        self.variant_list.itemDoubleClicked.connect(
            lambda item: self.activate_variant()
        )
        self._refresh_hero_filter()
        self.refresh()

    def selected_mods(self) -> list[Mod]:
        slugs: set[str] = set()
        for index in self.table.selectionModel().selectedRows():
            value = self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            slugs.update(value if isinstance(value, list) else [str(value)])
        return [mod for mod in self.context.catalog.mods if mod.slug in slugs]

    def current_mod(self) -> Mod | None:
        selected = self.selected_mods()
        return selected[0] if selected else None

    def refresh(self) -> None:
        self.warnings = conflicts.check(self.context.catalog.mods)
        query = self.search.text().lower().strip()
        hero = str(self.hero_filter.currentData() or "")
        state_text = self.state_filter.currentText()
        issue = str(self.issue_filter.currentData() or "")
        mods = self.context.catalog.mods
        if query:
            mods = [
                mod
                for mod in mods
                if query in mod.hero.lower()
                or query in mod.variant.lower()
                or query in mod.custom_variant.lower()
                or query in mod.variant_note.lower()
                or query in mod.source.name.lower()
                or query in mod.version_label.lower()
                or query in mod.state.value
                or query in (mod.nexus_id or "")
                or query in mod.author.lower()
                or query in (mod.nexus.mod_name if mod.nexus else "").lower()
                or query in (mod.nexus.file_name if mod.nexus else "").lower()
                or any(query in name.lower() for name in mod.collections)
                or any(
                    query in warning.text.lower()
                    for warning in self.warnings.get(mod.slug, [])
                )
            ]
        if hero:
            mods = [mod for mod in mods if mod.hero == hero]
        if state_text != "All states":
            mods = [mod for mod in mods if mod.state.value == state_text.lower()]
        if issue == "updates":
            mods = [
                mod
                for mod in mods
                if any(
                    warning.kind == "outdated"
                    for warning in self.warnings.get(mod.slug, [])
                )
            ]
        elif issue == "conflicts":
            mods = [
                mod
                for mod in mods
                if any(
                    warning.kind == "conflict"
                    for warning in self.warnings.get(mod.slug, [])
                )
            ]
        elif issue == "verified":
            mods = [mod for mod in mods if mod.verified]
        elif issue == "unverified":
            mods = [mod for mod in mods if not mod.verified]
        elif issue == "held":
            mods = [mod for mod in mods if mod.is_present]
        elif issue == "active":
            mods = [mod for mod in mods if mod.state is State.INSTALLED]

        groups = variants.group_mods(mods) if self.grouped.isChecked() else []
        rows = (
            [(group.mods[0], group) for group in groups]
            if self.grouped.isChecked()
            else [(mod, None) for mod in mods]
        )
        self.table.setRowCount(len(rows))
        row_height = 44 if self.context.config.library_density == "comfortable" else 30
        for row, (mod, group) in enumerate(rows):
            warning_rows = self.warnings.get(mod.slug, [])
            variant_label = mod.display_variant or "—"
            if group and group.has_choices:
                active = (
                    group.active[0].display_variant if group.active else "none active"
                )
                variant_label = f"{len(group.mods)} variants · {active}"
            values = (
                mod.hero + ("  ✓" if mod.verified else ""),
                variant_label,
                mod.version_label,
                mod.size_label,
                mod.state.value.upper(),
                conflicts.badge(warning_rows),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    represented = (
                        [member.slug for member in group.mods] if group else [mod.slug]
                    )
                    item.setData(Qt.ItemDataRole.UserRole, represented)
                if column == 4:
                    color = {
                        State.INSTALLED: "#65c18c",
                        State.BROKEN: "#df6666",
                        State.UNSUPPORTED: "#df6666",
                        State.DISABLED: "#9ea1aa",
                    }.get(mod.state)
                    if color:
                        item.setForeground(QColor(color))
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, row_height)
        self.refresh_detail()
        active_filters = sum(bool(value) for value in (query, hero, issue))
        active_filters += state_text != "All states"
        mode = "variant groups" if self.grouped.isChecked() else "archives"
        self.result_summary.setText(
            f"{len(rows):,} {mode} · {len(mods):,} matching archives"
            + (f" · {active_filters} active filters" if active_filters else "")
        )

    def refresh_detail(self) -> None:
        mod = self.current_mod()
        if not mod:
            self._cover_slug = ""
            self._cover_timer.stop()
            self.detail_title.setText("Select a mod")
            self.detail.setText("")
            self.cover.set_content("", "Select a mod")
            self.variant_list.clear()
            self._show_parts(None)
            return
        self.detail_title.setText(mod.title)
        self._cover_slug = mod.slug
        image = ""
        nexus_mod_id = mod.nexus.mod_id if mod.nexus else None
        if nexus_mod_id and nexus_mod_id in self._nexus_covers:
            remote = self._nexus_covers[nexus_mod_id]
            image = remote.thumbnail_url or remote.picture_url
        elif nexus_mod_id:
            self._cover_timer.start()
        notes = [mod.files_label, mod.source.name]
        if mod.nexus:
            notes.append(
                f"{mod.nexus.mod_name} · {mod.nexus.author} · Nexus {mod.nexus.mod_id}"
            )
        notes.extend(warning.text for warning in self.warnings.get(mod.slug, []))
        if mod.variant_note:
            notes.append(f"NOTE · {mod.variant_note}")
        self.detail.setText("\n\n".join(filter(None, notes)))
        self.cover.set_content(image, mod.title, mod.state.value.upper())
        self._show_parts(mod)
        self.variant_list.clear()
        siblings = self.variant_siblings(mod)
        for sibling in siblings:
            state = (
                "ACTIVE"
                if sibling.state is State.INSTALLED
                else sibling.state.value.upper()
            )
            label = (
                f"{sibling.display_variant or sibling.title}  ·  "
                f"{sibling.version_label}  ·  {state}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sibling.slug)
            if sibling.state is State.INSTALLED:
                item.setForeground(QColor("#65c18c"))
            self.variant_list.addItem(item)
            if sibling is mod:
                self.variant_list.setCurrentItem(item)

    def _show_parts(self, mod: Mod | None) -> None:
        """List the archive's pak sets, grouped into the choices the author made.

        A mod with one part hides the whole section: showing a single tickbox
        that must stay ticked teaches the user nothing and takes the space the
        artwork wants.
        """
        # Repopulating fires itemChanged for every row. Without the guard each
        # rebuild would be read back as the user unticking things.
        self._loading_parts = True
        try:
            self.parts_list.clear()
            visible = bool(mod and mod.has_choices)
            self.parts_title.setVisible(visible)
            self.parts_hint.setVisible(visible)
            self.parts_list.setVisible(visible)
            if not visible or mod is None:
                return

            grouped = components.groups(mod.components)
            alternatives = sum(1 for group in grouped if len(group) > 1)
            self.parts_hint.setText(
                f"{len(mod.components)} parts in {len(grouped)} group(s). "
                f"Parts in one group overwrite each other, so only one can run."
                if alternatives
                else f"{len(mod.components)} parts, none of which overlap."
            )

            for number, group in enumerate(grouped, start=1):
                exclusive = len(group) > 1
                for component in group:
                    mark = f"[{number}] " if exclusive else "[+] "
                    label = f"{mark}{component.label}"
                    if not component.is_readable:
                        label += "  (contents unreadable)"
                    item = QListWidgetItem(label)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if component.enabled
                        else Qt.CheckState.Unchecked
                    )
                    item.setData(
                        Qt.ItemDataRole.UserRole, (component.folder, component.stem)
                    )
                    self.parts_list.addItem(item)
        finally:
            self._loading_parts = False

    def _part_toggled(self, item: QListWidgetItem) -> None:
        """Turn a part on or off, and switch off whatever it would overwrite."""
        if getattr(self, "_loading_parts", False):
            return
        mod = self.current_mod()
        if mod is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        component = next(
            (item_ for item_ in mod.components if (item_.folder, item_.stem) == key),
            None,
        )
        if component is None:
            return

        if item.checkState() == Qt.CheckState.Checked:
            displaced = components.enable(component, mod.components)
            if displaced:
                names = ", ".join(other.label for other in displaced[:3])
                self.context.notify(f"Switched off {len(displaced)} part(s): {names}")
        else:
            component.enabled = False

        try:
            installer.apply_selection(mod, self.context.game.mods)
        except Exception as error:  # the game folder can refuse a link
            self.context.notify(str(error), True)
        self.context.catalog.save()
        self.refresh()

    def _load_detail_cover(self) -> None:
        mod = self.context.catalog.by_slug(self._cover_slug)
        if mod is None or mod.nexus is None:
            return
        mod_id = mod.nexus.mod_id
        slug = mod.slug
        self.context.tasks.submit(
            "Load library artwork",
            lambda progress: (slug, self.context.client.mod(mod_id)),
            on_result=self._cover_loaded,
            on_error=lambda message, trace: None,
        )

    def _cover_loaded(self, result) -> None:
        slug, remote = result
        if remote is None:
            return
        self._nexus_covers[remote.mod_id] = remote
        if slug != self._cover_slug:
            return
        mod = self.context.catalog.by_slug(slug)
        if mod is None:
            return
        self.cover.set_content(
            remote.thumbnail_url or remote.picture_url,
            mod.title,
            mod.state.value.upper(),
        )

    def _refresh_hero_filter(self) -> None:
        current = self.hero_filter.currentData()
        heroes = sorted(
            {mod.hero for mod in self.context.catalog.mods if mod.hero != "Unknown"}
        )
        self.hero_filter.blockSignals(True)
        self.hero_filter.clear()
        self.hero_filter.addItem("All heroes", "")
        for hero in heroes:
            self.hero_filter.addItem(hero, hero)
        index = self.hero_filter.findData(current)
        self.hero_filter.setCurrentIndex(max(0, index))
        self.hero_filter.blockSignals(False)

    def variant_siblings(self, mod: Mod) -> list[Mod]:
        if not mod.nexus_id:
            return [mod]
        return [
            sibling
            for sibling in self.context.catalog.mods
            if sibling.nexus_id == mod.nexus_id
        ]

    def activate_variant(self) -> None:
        item = self.variant_list.currentItem()
        game = self._require_game()
        if item is None or game is None:
            return
        target = self.context.catalog.by_slug(str(item.data(Qt.ItemDataRole.UserRole)))
        if target is None:
            return
        siblings = self.variant_siblings(target)
        if target.state is State.INSTALLED:
            self.context.notify(f"{target.variant or target.title} is already active")
            return

        def work(progress):
            progress(20, f"Switching to {target.variant or target.title}")
            variants.activate(target, siblings, game.mods)
            self.context.catalog.save()
            return target

        self.context.tasks.submit(
            "Switch variant",
            work,
            on_result=lambda chosen: self._action_done(
                f"Activated {chosen.variant or chosen.title}"
            ),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def open_variant_studio(self) -> None:
        mod = self.current_mod()
        if mod is None:
            return
        VariantStudioDialog(self.context, self.variant_siblings(mod), self).exec()
        self.refresh()

    def _require_game(self) -> GamePaths | None:
        if not self.context.game:
            self.context.notify(self.context.game_error or "Game not found", True)
            return None
        return self.context.game

    def _run_mod_action(
        self, label: str, function, mods: list[Mod] | None = None
    ) -> None:
        mods = self.selected_mods() if mods is None else mods
        game = self._require_game()
        if not mods or not game:
            return

        def work(progress):
            for index, mod in enumerate(mods, 1):
                progress(int((index - 1) / len(mods) * 100), mod.title)
                function(mod, game)
            self.context.catalog.save()
            return len(mods)

        self.context.tasks.submit(
            label,
            work,
            on_result=lambda count: self._action_done(f"{label}: {count} mod(s)"),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _action_done(self, message: str) -> None:
        self.context.notify(message)
        self._refresh_hero_filter()
        self.context.refresh_all()

    def install(self) -> None:
        self._run_mod_action(
            "Install",
            lambda mod, game: installer.install(mod, game.mods),
        )

    def enable(self) -> None:
        self._run_mod_action("Enable", lambda mod, game: installer.link(mod, game.mods))

    def disable(self) -> None:
        self._run_mod_action(
            "Disable", lambda mod, game: installer.unlink(mod, game.mods)
        )

    def remove(self) -> None:
        mods = [mod for mod in self.selected_mods() if mod.is_present]
        if not mods:
            self.context.notify(
                "Nothing selected is installed; source archives are kept in the library"
            )
            return
        answer = QMessageBox.question(
            self,
            "Uninstall mods",
            f"Uninstall {len(mods)} selected variant(s)?\n\n"
            "Game links and extracted store files will be removed. "
            "The original archives stay in your library.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_mod_action(
                "Uninstall",
                lambda mod, game: installer.remove(mod, game.mods),
                mods,
            )

    def repair(self) -> None:
        game = self._require_game()
        if not game:
            return
        fixed = installer.repair(self.context.catalog.mods, game.mods)
        self.context.catalog.save()
        self._action_done(f"Repaired {fixed} mod(s)")

    def rescan(self) -> None:
        game = self._require_game()
        mods_dir = game.mods if game else Path("/nonexistent")

        def work(progress):
            progress(15, "Inspecting archives")
            log = self.context.catalog.rescan(self.context.config.scan_dirs, mods_dir)
            self.context.catalog.save()
            return log

        self.context.tasks.submit(
            "Scan library",
            work,
            on_result=lambda log: self._action_done(
                f"Library refreshed · {len(self.context.catalog.mods)} mods"
            ),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def identify(self) -> None:
        from ..nexus.identify import identify_paths

        paths = [mod.source for mod in self.context.catalog.mods]
        if not paths:
            return

        def work(progress):
            matches, digests = identify_paths(
                self.context.client, paths, self.context.catalog.md5_cache
            )
            applied = self.context.catalog.apply_nexus(matches, digests)
            self.context.catalog.save()
            return applied

        self.context.tasks.submit(
            "Identify library",
            work,
            on_result=lambda count: self._action_done(f"Identified {count} mod(s)"),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def check_updates(self) -> None:
        from ..nexus.updates import check

        def work(progress):
            updates = check(self.context.client, self.context.catalog.owned_mod_ids())
            count = self.context.catalog.apply_updates(updates)
            self.context.catalog.save()
            return count

        self.context.tasks.submit(
            "Check Nexus updates",
            work,
            on_result=lambda count: self._action_done(f"Found {count} update(s)"),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def open_selected_nexus(self) -> None:
        mod = self.current_mod()
        if mod and mod.nexus:
            self.open_nexus_mod.emit(mod.nexus.mod_id)
        elif mod:
            self.context.notify("Identify this archive with Nexus first", True)


class ModDetailDialog(QDialog):
    def __init__(
        self,
        context: Context,
        mod: NexusMod,
        files: list[NexusFile],
        images: list[NexusImage],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.context, self.mod, self.files, self.images = context, mod, files, images
        self.setWindowTitle(mod.name)
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.cover = ImageTile(
            context.images,
            (images[0].url if images else mod.picture_url),
            mod.name,
            f"{mod.author} · {mod.downloads_label} downloads",
        )
        self.cover.setMinimumSize(440, 270)
        self.cover.clicked.connect(lambda: self.open_gallery(0))
        top.addWidget(self.cover, 1)
        meta = QVBoxLayout()
        title = QLabel(mod.name)
        title.setObjectName("detailTitle")
        title.setWordWrap(True)
        meta.addWidget(title)
        meta.addWidget(
            QLabel(
                f"by {mod.author}\nVersion {mod.version or '—'}\n"
                f"{mod.downloads_label} downloads · {mod.endorsements} endorsements"
            )
        )
        browse = QPushButton("Open on Nexus")
        browse.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(f"https://www.nexusmods.com/marvelrivals/mods/{mod.mod_id}")
            )
        )
        gallery = QPushButton(f"View gallery ({len(images)})")
        gallery.clicked.connect(lambda: self.open_gallery(0))
        self.favorite = QPushButton()
        self.refresh_favorite()
        self.favorite.clicked.connect(self.toggle_favorite)
        meta.addWidget(browse)
        meta.addWidget(gallery)
        meta.addWidget(self.favorite)
        meta.addStretch()
        top.addLayout(meta)
        layout.addLayout(top)

        tabs = QTabWidget()
        description = QTextBrowser()
        description.setPlainText(plain(mod.summary) or "No description available.")
        tabs.addTab(description, "Overview")
        self.file_table = QTableWidget(len(files), 5)
        self.file_table.setHorizontalHeaderLabels(
            ("File", "Version", "Size", "Category", "Held")
        )
        self.file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.file_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, file in enumerate(files):
            local = self.local_for_file(file.file_id)
            status = ""
            if local and local.state is State.INSTALLED:
                status = "ACTIVE"
            elif local and local.is_present:
                status = "HELD"
            elif file.category in ("OLD_VERSION", "ARCHIVED"):
                status = file.category.replace("_", " ")
            values = (
                file.name,
                file.version or "—",
                file.size_label,
                file.category,
                status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, file.file_id)
                if column == 4 and status == "ACTIVE":
                    item.setForeground(QColor("#65c18c"))
                elif column == 4 and status == "HELD":
                    item.setForeground(QColor("#b7a9ff"))
                self.file_table.setItem(row, column, item)
        tabs.addTab(self.file_table, "Files")
        gallery_page = QWidget()
        gallery_grid = QGridLayout(gallery_page)
        for index, image in enumerate(images):
            tile = ImageTile(
                context.images,
                image.thumbnail_url or image.url,
                image.title or mod.name,
                image.caption,
            )
            tile.clicked.connect(lambda i=index: self.open_gallery(i))
            gallery_grid.addWidget(tile, index // 3, index % 3)
        gallery_scroll = QScrollArea()
        gallery_scroll.setWidgetResizable(True)
        gallery_scroll.setWidget(gallery_page)
        tabs.addTab(gallery_scroll, f"Gallery ({len(images)})")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        download = QPushButton("Download selected")
        activate = QPushButton("Activate held variant")
        install = QPushButton("Download and install")
        buttons.addButton(download, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(activate, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(install, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        download.clicked.connect(lambda: self.download_selected(False))
        activate.clicked.connect(self.activate_selected)
        install.clicked.connect(lambda: self.download_selected(True))
        layout.addWidget(buttons)

    def refresh_favorite(self) -> None:
        self.favorite.setText(
            "★ Remove from favorites"
            if self.context.state.is_favorite(self.mod.mod_id)
            else "☆ Add to favorites"
        )

    def toggle_favorite(self) -> None:
        favorite = self.context.state.toggle_favorite(self.mod.mod_id)
        self.refresh_favorite()
        self.context.notify(
            f"{'Added' if favorite else 'Removed'} {self.mod.name} "
            f"{'to' if favorite else 'from'} favorites"
        )

    def selected_file(self) -> NexusFile | None:
        row = self.file_table.currentRow()
        if row < 0 and self.files:
            row = 0
        return self.files[row] if 0 <= row < len(self.files) else None

    def local_for_file(self, file_id: int) -> Mod | None:
        return next(
            (
                local
                for local in self.context.catalog.mods
                if local.nexus
                and local.nexus.mod_id == self.mod.mod_id
                and local.nexus.file_id == file_id
            ),
            None,
        )

    def local_siblings(self) -> list[Mod]:
        return [
            local
            for local in self.context.catalog.mods
            if (local.nexus and local.nexus.mod_id == self.mod.mod_id)
            or local.nexus_id == str(self.mod.mod_id)
        ]

    def activate_selected(self) -> None:
        file = self.selected_file()
        game = self.context.game
        if not file or not game:
            return
        local = self.local_for_file(file.file_id)
        if local is None or not local.is_present:
            self.context.notify("Download this variant before activating it", True)
            return
        if local.state is State.INSTALLED:
            self.context.notify("That variant is already active")
            return
        siblings = self.local_siblings()

        def work(progress):
            progress(25, f"Activating {file.name}")
            variants.activate(local, siblings, game.mods)
            self.context.catalog.save()
            return local

        self.context.tasks.submit(
            "Switch variant",
            work,
            on_result=lambda target: self._activated(target),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _activated(self, target: Mod) -> None:
        self.context.notify(f"Activated {target.variant or target.title}")
        self.context.refresh_all()
        self.accept()

    def open_gallery(self, index: int) -> None:
        if self.images:
            GalleryDialog(self.context.images, self.images, index, self).exec()

    def download_selected(self, install_after: bool) -> None:
        file = self.selected_file()
        if not file:
            self.context.notify("Select a file first", True)
            return
        if not self.context.client.api_key:
            self.context.notify("Add a Nexus API key in Settings to download", True)
            return
        active = [
            local
            for local in self.local_siblings()
            if local.state is State.INSTALLED
            and (not local.nexus or local.nexus.file_id != file.file_id)
        ]
        if install_after and active:
            names = ", ".join(local.variant or local.title for local in active)
            answer = QMessageBox.question(
                self,
                "Switch active variant",
                f"Download and activate {file.name}?\n\n"
                f"Currently active: {names}\n\n"
                "The current variant will stay extracted but become disabled.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        def work(progress):
            def bytes_progress(done, total):
                percent = int(done / total * 100) if total else 0
                progress(percent, file.name)

            path = download_file(
                self.context.client,
                self.mod.mod_id,
                file.file_id,
                library.ensure(),
                file_name=file.name,
                on_progress=bytes_progress,
            )
            if install_after and self.context.game:
                self.context.catalog.rescan(
                    self.context.config.scan_dirs, self.context.game.mods
                )
                local = next(
                    (
                        item
                        for item in self.context.catalog.mods
                        if item.source == path
                        or (item.nexus and item.nexus.file_id == file.file_id)
                    ),
                    None,
                )
                if local:
                    variants.activate(
                        local, self.local_siblings(), self.context.game.mods
                    )
            self.context.catalog.save()
            return path

        self.context.tasks.submit(
            f"Download {self.mod.name}",
            work,
            on_result=lambda path: self._downloaded(path, install_after),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _downloaded(self, path: Path, installed: bool) -> None:
        self.context.notify(f"{'Installed' if installed else 'Downloaded'} {path.name}")
        self.context.refresh_all()


class NexusPage(QWidget):
    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        self.mods: list[NexusMod] = []
        self.offset = 0
        self._generation = 0
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        title = QLabel("NEXUS")
        title.setObjectName("pageTitle")
        self.search = QComboBox()
        self.search.setEditable(True)
        self.search.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.search.setMinimumWidth(360)
        self.search.lineEdit().setPlaceholderText(
            "Search Nexus · author:name  category:name  id:1234"
        )
        self.search.lineEdit().setClearButtonEnabled(True)
        self.search.lineEdit().returnPressed.connect(lambda: self.load(reset=True))
        self.sort = QComboBox()
        self.sort.addItem("Most downloaded", "downloads")
        self.sort.addItem("Recently updated", "updatedAt")
        self.sort.addItem("Newest", "createdAt")
        self.sort.currentIndexChanged.connect(lambda: self.load(reset=True))
        go = QPushButton("Search")
        go.clicked.connect(lambda: self.load(reset=True))
        save = QPushButton("Save search")
        save.clicked.connect(self.save_search)
        favorites = QPushButton("★ Favorites")
        favorites.clicked.connect(self.load_favorites)
        self.saved = QComboBox()
        self.saved.addItem("Saved searches…", "")
        for query in context.state.data.saved_searches:
            self.saved.addItem(query, query)
        self.saved.currentIndexChanged.connect(self.apply_saved_search)
        bar.addWidget(title)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.sort)
        bar.addWidget(go)
        bar.addWidget(save)
        bar.addWidget(favorites)
        bar.addWidget(self.saved)
        layout.addLayout(bar)
        self.status = QLabel("Search or browse the Nexus catalog.")
        layout.addWidget(self.status)
        self.grid_body = QWidget()
        self.grid = QGridLayout(self.grid_body)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_body)
        layout.addWidget(scroll, 1)
        self.paginator = Paginator(24)
        self.paginator.page_requested.connect(self.load_page)
        layout.addWidget(self.paginator)
        QTimer.singleShot(0, lambda: self.load(reset=True))

    def clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

    @property
    def query_text(self) -> str:
        return self.search.currentText().strip()

    def set_query(self, text: str) -> None:
        self.search.setEditText(text)

    def save_search(self) -> None:
        query = self.query_text
        if not self.context.state.save_search(query):
            self.context.notify("Enter a search before saving it", True)
            return
        index = self.saved.findData(query)
        if index >= 0:
            self.saved.removeItem(index)
        self.saved.insertItem(1, query, query)
        self.saved.setCurrentIndex(0)
        self.context.notify(f"Saved search: {query}")

    def apply_saved_search(self, index: int) -> None:
        query = str(self.saved.itemData(index) or "")
        if query:
            self.set_query(query)
            self.load(reset=True)
            self.saved.setCurrentIndex(0)

    def load_favorites(self) -> None:
        ids = sorted(self.context.state.data.favorite_mod_ids)
        self._generation += 1
        generation = self._generation
        self.status.setText("Loading favorites…")

        def work(progress):
            items = [
                mod
                for mod_id in ids
                if (mod := self.context.client.mod(mod_id)) is not None
            ]
            return generation, Page(items, len(items), 0, max(len(items), 1))

        self.context.tasks.submit(
            "Load favorites",
            work,
            on_result=self._loaded,
            on_error=lambda message, trace: self._failed(message),
        )

    @staticmethod
    def parse_query(query: str) -> tuple[str, str, str, int | None]:
        free: list[str] = []
        author = ""
        category = ""
        mod_id: int | None = None
        try:
            tokens = shlex.split(query)
        except ValueError:
            tokens = query.split()
        for token in tokens:
            key, separator, value = token.partition(":")
            if separator and value:
                if key.lower() == "author":
                    author = value
                    continue
                if key.lower() in ("category", "cat"):
                    category = value
                    continue
                if key.lower() in ("id", "mod") and value.isdigit():
                    mod_id = int(value)
                    continue
            free.append(token)
        if len(free) == 1 and free[0].isdigit():
            mod_id = int(free.pop())
        return " ".join(free), author, category, mod_id

    def load(self, checked: bool = False, *, reset: bool = False) -> None:
        if reset:
            self.offset = 0
        self.load_page(self.offset, self.paginator.page_size)

    def load_page(self, offset: int, count: int) -> None:
        query = self.query_text
        text, author, category, mod_id = self.parse_query(query)
        if mod_id is not None:
            self._remember_search(query)
            self.open_mod(mod_id)
            return
        sort = self.sort.currentData()
        self.offset = offset
        self._generation += 1
        generation = self._generation
        self.status.setText("Loading Nexus…")

        def work(progress):
            progress(20, "Searching Nexus")
            page = (
                self.context.client.search_page(
                    text,
                    author=author,
                    category=category,
                    count=count,
                    offset=offset,
                )
                if (text or author or category)
                else self.context.client.browse_page(sort, count, offset)
            )
            return generation, page

        self.context.tasks.submit(
            "Search Nexus" if (text or author or category) else "Browse Nexus",
            work,
            on_result=self._loaded,
            on_error=lambda message, trace: self._failed(message),
        )

    def _remember_search(self, query: str) -> None:
        if not query:
            return
        existing = [self.search.itemText(i) for i in range(self.search.count())]
        if query in existing:
            self.search.removeItem(existing.index(query))
        self.search.insertItem(0, query)
        while self.search.count() > 12:
            self.search.removeItem(self.search.count() - 1)
        self.search.setEditText(query)

    def _loaded(self, result) -> None:
        generation, page = result
        if generation != self._generation:
            return
        self.mods = page.items
        self.offset = page.offset
        self._remember_search(self.query_text)
        self.status.setText(
            f"Showing {page.first:,}–{page.last:,} of {page.total:,} Nexus mods"
        )
        self.paginator.set_page(page)
        self.clear()
        for index, mod in enumerate(page.items):
            tile = ImageTile(
                self.context.images,
                mod.thumbnail_url or mod.picture_url,
                mod.name,
                f"{mod.author} · {mod.downloads_label} downloads",
            )
            tile.clicked.connect(lambda mod_id=mod.mod_id: self.open_mod(mod_id))
            self.grid.addWidget(tile, index // 4, index % 4)

    def _failed(self, message: str) -> None:
        self.status.setText(message)
        self.context.notify(message, True)

    def open_mod(self, mod_id: int) -> None:
        known = next((mod for mod in self.mods if mod.mod_id == mod_id), None)
        self.status.setText("Loading mod details and gallery…")

        def work(progress):
            mod = known or self.context.client.mod(mod_id)
            if mod is None:
                raise RuntimeError(f"Nexus mod {mod_id} was not found")
            progress(30, "Loading files")
            files = self.context.client.files(mod_id)
            progress(60, "Loading gallery")
            images = self.context.client.images(mod)
            return mod, files, images

        self.context.tasks.submit(
            "Load mod details",
            work,
            on_result=self._show_mod,
            on_error=lambda message, trace: self._failed(message),
        )

    def _show_mod(self, result) -> None:
        self.status.setText("")
        mod, files, images = result
        self.context.state.remember_mod(mod.mod_id)
        ModDetailDialog(self.context, mod, files, images, self).exec()


class CollectionDialog(QDialog):
    def __init__(self, context: Context, collection, parent=None) -> None:
        super().__init__(parent)
        self.context, self.collection = context, collection
        self.setWindowTitle(collection.name)
        self.resize(980, 720)
        layout = QVBoxLayout(self)
        if collection.header_url or collection.tile_url:
            hero = ImageTile(
                context.images,
                collection.header_url or collection.tile_url,
                collection.name,
                f"CURATED BY {collection.author.upper()}",
            )
            hero.setMinimumHeight(190)
            hero.setCursor(Qt.CursorShape.ArrowCursor)
            layout.addWidget(hero)
        title = QLabel(collection.name)
        title.setObjectName("detailTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                f"by {collection.author} · revision {collection.revision} · "
                f"{collection.mod_count} mods · {collection.size_label}\n"
                f"{plain(collection.summary)}"
            )
        )
        tools = QHBoxLayout()
        self.member_search = QLineEdit()
        self.member_search.setPlaceholderText("Filter collection members")
        self.member_search.setClearButtonEnabled(True)
        self.member_filter = QComboBox()
        self.member_filter.addItem("All members", "")
        self.member_filter.addItem("Required", "required")
        self.member_filter.addItem("Optional", "optional")
        self.member_filter.addItem("Missing", "missing")
        self.member_filter.addItem("Already held", "held")
        select_optional = QPushButton("Select all optional")
        clear_optional = QPushButton("Clear optional")
        invert_optional = QPushButton("Invert optional")
        select_optional.clicked.connect(lambda: self.set_optional("all"))
        clear_optional.clicked.connect(lambda: self.set_optional("none"))
        invert_optional.clicked.connect(lambda: self.set_optional("invert"))
        tools.addWidget(self.member_search, 1)
        tools.addWidget(self.member_filter)
        tools.addWidget(select_optional)
        tools.addWidget(clear_optional)
        tools.addWidget(invert_optional)
        layout.addLayout(tools)
        self.table = QTableWidget(len(collection.mods), 6)
        self.table.setHorizontalHeaderLabels(
            ("Include", "Mod", "File", "Version", "Size", "Status")
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        held = context.catalog.held_files()
        for row, mod in enumerate(collection.mods):
            include = QTableWidgetItem()
            include.setFlags(include.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            include.setCheckState(
                Qt.CheckState.Unchecked if mod.optional else Qt.CheckState.Checked
            )
            if not mod.optional:
                include.setFlags(include.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            include.setData(Qt.ItemDataRole.UserRole, mod.file_id)
            self.table.setItem(row, 0, include)
            values = (
                mod.mod_name,
                mod.file_name,
                mod.file_version or "—",
                f"{mod.size / 2**20:,.0f} MB",
                "HELD"
                if (mod.mod_id, mod.file_id) in held
                else ("OPTIONAL" if mod.optional else ""),
            )
            for column, value in enumerate(values, 1):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.itemChanged.connect(lambda item: self.refresh_summary())
        self.member_search.textChanged.connect(self.apply_filter)
        self.member_filter.currentIndexChanged.connect(self.apply_filter)
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        install = QPushButton("Download collection")
        buttons.addButton(install, QDialogButtonBox.ButtonRole.AcceptRole)
        install.clicked.connect(self.install)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_summary()

    def set_optional(self, mode: str) -> None:
        self.table.blockSignals(True)
        try:
            for row, mod in enumerate(self.collection.mods):
                if not mod.optional or self.table.isRowHidden(row):
                    continue
                item = self.table.item(row, 0)
                if mode == "all":
                    item.setCheckState(Qt.CheckState.Checked)
                elif mode == "none":
                    item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item.setCheckState(
                        Qt.CheckState.Unchecked
                        if item.checkState() == Qt.CheckState.Checked
                        else Qt.CheckState.Checked
                    )
        finally:
            self.table.blockSignals(False)
        self.refresh_summary()

    def apply_filter(self) -> None:
        query = self.member_search.text().lower().strip()
        kind = str(self.member_filter.currentData() or "")
        held = self.context.catalog.held_files()
        visible = 0
        for row, mod in enumerate(self.collection.mods):
            matches_text = not query or any(
                query in value.lower()
                for value in (mod.mod_name, mod.file_name, mod.file_version or "")
            )
            is_held = (mod.mod_id, mod.file_id) in held
            matches_kind = (
                not kind
                or (kind == "required" and not mod.optional)
                or (kind == "optional" and mod.optional)
                or (kind == "missing" and not is_held)
                or (kind == "held" and is_held)
            )
            hidden = not (matches_text and matches_kind)
            self.table.setRowHidden(row, hidden)
            visible += not hidden
        self.refresh_summary(visible)

    def optional_ids(self) -> set[int]:
        return {
            int(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).flags() & Qt.ItemFlag.ItemIsEnabled
            and self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        }

    def plan(self):
        return collection_ops.plan(
            self.collection,
            self.optional_ids(),
            self.context.catalog.held_files(),
        )

    def refresh_summary(self, visible: int | None = None) -> None:
        plan = self.plan()
        visible_text = f" · {visible} visible" if visible is not None else ""
        self.summary.setText(
            f"{len(plan.wanted)} selected · {len(plan.already_held)} already held · "
            f"{len(plan.to_download)} to download · {plan.size_label}{visible_text}"
        )

    def install(self) -> None:
        if not self.context.client.api_key:
            self.context.notify("Add a Nexus API key in Settings to download", True)
            return
        plan = self.plan()

        def work(progress):
            def item(index, total, mod):
                progress(int((index - 1) / max(total, 1) * 100), mod.mod_name)

            outcome = collection_ops.fetch(
                self.context.client,
                plan,
                library.ensure(),
                on_item=item,
            )
            if self.context.game:
                # The rescan has to come between the download and the install,
                # so the catalog holds a record for each archive that arrived.
                self.context.catalog.rescan(
                    self.context.config.scan_dirs, self.context.game.mods
                )
                progress(99, "installing")
                outcome.installed, outcome.problems = collection_ops.deploy(
                    self.context.catalog.mods,
                    outcome.downloaded,
                    self.context.game.mods,
                )
            pairs = {(mod.mod_id, mod.file_id) for mod in plan.wanted}
            self.context.catalog.tag_collection(self.collection.slug, pairs)
            self.context.catalog.save()
            return outcome

        self.context.tasks.submit(
            f"Download {self.collection.name}",
            work,
            on_result=self._done,
            on_error=lambda message, trace: self.context.notify(message, True),
        )
        self.accept()

    def _done(self, outcome) -> None:
        message = (
            f"Downloaded {len(outcome.downloaded)} file(s), "
            f"installed {outcome.installed}"
        )
        if outcome.failed:
            message += f" · {len(outcome.failed)} download(s) failed"
        if outcome.problems:
            message += f" · {len(outcome.problems)} install(s) failed"
        self.context.notify(message, bool(outcome.failed or outcome.problems))
        self.context.refresh_all()


class CollectionCard(QFrame):
    opened = Signal(str)

    def __init__(self, context: Context, collection) -> None:
        super().__init__()
        self.collection = collection
        self.setObjectName("collectionCard")
        self.setMinimumWidth(235)
        self.setMaximumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        image = ImageTile(
            context.images,
            collection.tile_url or collection.header_url,
            collection.name,
            f"{collection.author}  ·  {collection.mod_count} mods",
        )
        image.setMinimumSize(220, 155)
        image.clicked.connect(lambda: self.opened.emit(collection.slug))
        layout.addWidget(image)
        metrics = QLabel(
            f"{collection.downloads_label} downloads   "
            f"{collection.rating_label}   {collection.size_label}"
        )
        metrics.setObjectName("eyebrow")
        metrics.setContentsMargins(12, 0, 12, 0)
        layout.addWidget(metrics)
        summary = QLabel(plain(collection.summary) or "No description provided.")
        summary.setWordWrap(True)
        summary.setMaximumHeight(42)
        summary.setContentsMargins(12, 0, 12, 0)
        layout.addWidget(summary)


class CollectionsPage(QWidget):
    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        self.collections = []
        self.offset = 0
        self._generation = 0
        self._columns = 0
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        title = QLabel("COLLECTIONS")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search collections…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(lambda: self.load(reset=True))
        search_button = QPushButton("Search")
        search_button.clicked.connect(lambda: self.load(reset=True))
        self.sort = QComboBox()
        self.sort.addItem("Most endorsed", "endorsements")
        self.sort.addItem("Most downloaded", "totalDownloads")
        self.sort.addItem("Recently updated", "updatedAt")
        self.sort.currentIndexChanged.connect(lambda: self.load(reset=True))
        load = QPushButton("Refresh")
        load.clicked.connect(lambda: self.load(reset=True))
        bar.addWidget(title)
        bar.addWidget(self.search, 1)
        bar.addWidget(search_button)
        bar.addStretch()
        bar.addWidget(self.sort)
        bar.addWidget(load)
        layout.addLayout(bar)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_body = QWidget()
        self.grid = QGridLayout(self.grid_body)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(14)
        self.scroll.setWidget(self.grid_body)
        layout.addWidget(self.scroll, 1)
        self.paginator = Paginator(40)
        self.paginator.page_requested.connect(self.load_page)
        layout.addWidget(self.paginator)

    def load(self, checked: bool = False, *, reset: bool = False) -> None:
        if reset:
            self.offset = 0
        self.load_page(self.offset, self.paginator.page_size)

    def load_page(self, offset: int, count: int) -> None:
        sort = self.sort.currentData()
        search = self.search.text().strip()
        self.offset = offset
        self._generation += 1
        generation = self._generation
        self.context.tasks.submit(
            "Load collections",
            lambda progress: (
                generation,
                self.context.client.collections_page(sort, count, offset, search),
            ),
            on_result=self._loaded,
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _loaded(self, result) -> None:
        generation, page = result
        if generation != self._generation:
            return
        self.collections = page.items
        self.offset = page.offset
        self.paginator.set_page(page)
        self.status.setText(
            f"Showing {page.first:,}–{page.last:,} of {page.total:,} collections"
        )
        self._render_cards()
        self.scroll.verticalScrollBar().setValue(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.collections:
            QTimer.singleShot(0, self._render_cards)

    def _render_cards(self) -> None:
        width = self.scroll.viewport().width() if self.scroll else self.width()
        columns = max(1, min(4, (width + 14) // 264))
        if columns == self._columns and self.grid.count() == len(self.collections):
            return
        self._columns = columns
        while self.grid.count():
            item = self.grid.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        for index, collection in enumerate(self.collections):
            card = CollectionCard(self.context, collection)
            card.opened.connect(self.open_collection)
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

    def open_collection(self, slug: str) -> None:
        self.context.tasks.submit(
            "Load collection manifest",
            lambda progress: self.context.client.collection(slug),
            on_result=lambda collection: CollectionDialog(
                self.context, collection, self
            ).exec(),
            on_error=lambda message, trace: self.context.notify(message, True),
        )


class PatchPage(QWidget):
    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        title = QLabel("PATCH")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Marvel Rivals rejects unsigned pak files. All three checks must pass."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.loader = StatCard("Loader")
        self.plugin = StatCard("Signature bypass")
        self.override = StatCard("Proton override")
        checks = QHBoxLayout()
        checks.addWidget(self.loader)
        checks.addWidget(self.plugin)
        checks.addWidget(self.override)
        layout.addLayout(checks)
        layout.addWidget(section_title("Steam launch options"))
        self.options = QTextEdit()
        self.options.setReadOnly(True)
        self.options.setMaximumHeight(100)
        layout.addWidget(self.options)
        actions = QHBoxLayout()
        install = QPushButton("Install patch")
        remove = QPushButton("Remove patch")
        set_options = QPushButton("Close Steam and set override")
        refresh = QPushButton("Re-check")
        install.clicked.connect(self.install)
        remove.clicked.connect(self.remove)
        set_options.clicked.connect(self.set_override)
        refresh.clicked.connect(self.refresh)
        for button in (install, remove, set_options, refresh):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.guidance = QLabel()
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        if not self.context.game:
            for card in (self.loader, self.plugin, self.override):
                card.set_value("UNKNOWN", "#df6666")
            self.guidance.setText(self.context.game_error)
            return
        state = patch.status(self.context.game)
        self.loader.set_value(
            "READY" if state.loader_installed else "MISSING",
            "#65c18c" if state.loader_installed else "#df6666",
        )
        self.plugin.set_value(
            "READY" if state.plugin_installed else "MISSING",
            "#65c18c" if state.plugin_installed else "#df6666",
        )
        self.override.set_value(
            "READY" if state.override_set else "MISSING",
            "#65c18c" if state.override_set else "#e4b363",
        )
        self.options.setPlainText(state.launch_options or "(none set)")
        self.guidance.setText(
            "Required: " + steam.merge_override(state.launch_options or "")
            if not state.override_set
            else "The signature bypass is ready."
        )

    def install(self) -> None:
        if not self.context.game or not self.context.catalog.patch_archive:
            self.context.notify("No patch archive was found in the scan folders", True)
            return
        game, archive = self.context.game, self.context.catalog.patch_archive
        self.context.tasks.submit(
            "Install signature bypass",
            lambda progress: patch.install(game, archive, DATA_DIR / "staging"),
            on_result=lambda placed: self._done(f"Installed {', '.join(placed)}"),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def remove(self) -> None:
        if self.context.game:
            removed = patch.uninstall(self.context.game)
            self._done(f"Removed {', '.join(removed) or 'nothing'}")

    def set_override(self) -> None:
        if not self.context.game:
            return
        answer = QMessageBox.question(
            self,
            "Edit Steam launch options",
            "Steam must close before its settings are edited. Close Steam, set the "
            "override, verify it, and restart Steam?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def work(progress):
            progress(10, "Closing Steam")
            if not steam.shutdown():
                raise RuntimeError("Steam did not close in time")
            current = patch.status(self.context.game).launch_options or ""
            progress(55, "Backing up and editing settings")
            result = steam.set_launch_options(steam.merge_override(current))
            steam.start()
            return result

        self.context.tasks.submit(
            "Set Proton override",
            work,
            on_result=lambda result: self._done(result.message),
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _done(self, message: str) -> None:
        self.context.notify(message)
        self.refresh()


class ActivityPage(QWidget):
    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        title = QLabel("ACTIVITY")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel("Downloads, scans, installs, and errors from this session.")
        )
        tools = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("eyebrow")
        cancel = QPushButton("Cancel selected")
        cancel.clicked.connect(self.cancel_selected)
        clear = QPushButton("Clear finished")
        clear.clicked.connect(self.context.tasks.clear_finished)
        tools.addWidget(self.summary)
        tools.addStretch()
        tools.addWidget(cancel)
        tools.addWidget(clear)
        layout.addLayout(tools)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("Time", "Operation", "State", "Progress", "Detail")
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        context.tasks.activity_changed.connect(self.refresh)

    def refresh(self) -> None:
        activities = self.context.tasks.activities
        self.table.setRowCount(len(activities))
        for row, activity in enumerate(activities):
            values = (
                activity.started,
                activity.label,
                activity.state.upper(),
                f"{activity.progress}%" if activity.progress is not None else "—",
                activity.detail,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, activity.task_id)
                if column == 2:
                    color = {
                        "failed": "#df6666",
                        "complete": "#65c18c",
                        "cancelled": "#e4b363",
                        "running": "#8f92e8",
                    }.get(activity.state, "#9ea1aa")
                    item.setForeground(QColor(color))
                self.table.setItem(row, column, item)
        running = sum(activity.state == "running" for activity in activities)
        failed = sum(activity.state == "failed" for activity in activities)
        self.summary.setText(
            f"{running} running · {len(activities) - running} finished"
            + (f" · {failed} failed" if failed else "")
        )

    def cancel_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        task_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if self.context.tasks.cancel(str(task_id)):
            self.context.notify(
                "Task cancelled; an in-flight operation may finish safely"
            )


class SettingsPage(QWidget):
    def __init__(self, context: Context) -> None:
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        title = QLabel("SETTINGS")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(credentials.mask(credentials.load_key()))
        self.game_root = QLineEdit(
            str(context.config.game_root or (context.game.root if context.game else ""))
        )
        game_pick = QPushButton("Browse…")
        game_pick.clicked.connect(self.pick_game)
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_root, 1)
        game_row.addWidget(game_pick)
        game_box = QWidget()
        game_box.setLayout(game_row)
        self.scan = QListWidget()
        self.scan.setMaximumHeight(130)
        for path in context.config.scan_dirs:
            self.scan.addItem(str(path))
        scan_buttons = QHBoxLayout()
        add_scan = QPushButton("Add folder")
        remove_scan = QPushButton("Remove selected")
        add_scan.clicked.connect(self.add_scan)
        remove_scan.clicked.connect(self.remove_scan)
        scan_buttons.addWidget(add_scan)
        scan_buttons.addWidget(remove_scan)
        scan_box = QWidget()
        scan_layout = QVBoxLayout(scan_box)
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.addWidget(self.scan)
        scan_layout.addLayout(scan_buttons)
        self.theme = QComboBox()
        self.theme.addItems(("Dark command center", "Parchment light"))
        self.theme.setCurrentIndex(0 if context.config.gui_theme == "dark" else 1)
        self.density = QComboBox()
        self.density.addItems(("Comfortable", "Compact"))
        self.density.setCurrentText(context.config.library_density.title())
        self.cache = QComboBox()
        for size in (256, 512, 1024, 2048, 5120, 10240):
            self.cache.addItem(
                f"{size // 1024} GiB" if size >= 1024 else f"{size} MiB", size
            )
        index = self.cache.findData(context.config.image_cache_mb)
        self.cache.setCurrentIndex(index if index >= 0 else 2)
        # Grouped, and named the same as the Setup page. The two screens used
        # different words for one thing — "Game root" against "Game folder",
        # "Scan folders" against "Downloads folder" — which read as four
        # settings instead of two.
        self.library_line = QLabel()
        self.library_line.setWordWrap(True)
        self.library_line.setObjectName("eyebrow")
        import_button = QPushButton("Import…")
        import_button.clicked.connect(self.import_archives)
        open_library = QPushButton("Open folder")
        open_library.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LIBRARY_DIR)))
        )
        library_row = QHBoxLayout()
        library_row.addWidget(self.library_line, 1)
        library_row.addWidget(import_button)
        library_row.addWidget(open_library)
        library_box = QWidget()
        library_box.setLayout(library_row)

        watch_hint = QLabel(
            "Optional. The library above is always read; add a folder here only "
            "to watch archives you keep somewhere else."
        )
        watch_hint.setWordWrap(True)
        watch_hint.setObjectName("eyebrow")

        form.addRow(section_title("Game"), QWidget())
        form.addRow("Game folder", game_box)
        form.addRow(section_title("Mods"), QWidget())
        form.addRow("Mod library", library_box)
        form.addRow("Extra folders to watch", scan_box)
        form.addRow("", watch_hint)
        form.addRow(section_title("Nexus"), QWidget())
        form.addRow("API key", self.key)
        form.addRow(section_title("Appearance"), QWidget())
        form.addRow("Theme", self.theme)
        form.addRow("Library density", self.density)
        form.addRow("Image cache", self.cache)
        layout.addLayout(form)
        cache_panel = QFrame()
        cache_panel.setObjectName("statCard")
        cache_layout = QHBoxLayout(cache_panel)
        self.cache_status = QLabel()
        self.cache_status.setWordWrap(True)
        inspect_cache = QPushButton("Measure cache")
        inspect_cache.clicked.connect(lambda: self.refresh_cache(True))
        clear_cache = QPushButton("Clear cache")
        clear_cache.clicked.connect(self.clear_cache)
        cache_layout.addWidget(self.cache_status, 1)
        cache_layout.addWidget(inspect_cache)
        cache_layout.addWidget(clear_cache)
        layout.addWidget(cache_panel)

        # Save sits with the form it saves. Everything below it is an action
        # that takes effect the moment it is pressed, and the destructive ones
        # go last so nothing lands under the pointer on the way to Save.
        save = QPushButton("Save settings")
        save.clicked.connect(self.save)
        layout.addWidget(save)

        layout.addWidget(section_title("Nexus browser links"))
        self.handler = QLabel()
        self.handler.setWordWrap(True)
        layout.addWidget(self.handler)
        handlers = QHBoxLayout()
        register = QPushButton("Register nxm:// handler")
        unregister = QPushButton("Unregister")
        register.clicked.connect(self.register_nxm)
        unregister.clicked.connect(self.unregister_nxm)
        handlers.addWidget(register)
        handlers.addWidget(unregister)
        handlers.addStretch()
        layout.addLayout(handlers)

        layout.addWidget(section_title("Start over"))
        reset_hint = QLabel(
            "Each of these lists exactly what it would remove before it removes "
            "anything. Your archives are never touched."
        )
        reset_hint.setWordWrap(True)
        reset_hint.setObjectName("eyebrow")
        layout.addWidget(reset_hint)
        resets = QHBoxLayout()
        for label, scopes, title in (
            ("Unlink every mod", ["links"], "Remove the game's links"),
            (
                "Delete extracted files",
                ["links", "store"],
                "Remove the links and the extracted files",
            ),
            (
                "Forget everything",
                ["links", "store", "catalog", "cache"],
                "Remove links, extracted files, the mod list and artwork",
            ),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, s=scopes, t=title: self.reset(s, t))
            resets.addWidget(button)
        resets.addStretch()
        layout.addLayout(resets)

        layout.addStretch()
        self._cache_disk: tuple[int, int] | None = None
        context.images.changed.connect(self.refresh_cache)
        self.refresh_cache()
        self.refresh_handler()
        self.refresh_library()

    def refresh_cache(self, measure: bool = False) -> None:
        if measure:
            self._cache_disk = self.context.images.disk_usage()
        stats = self.context.images.stats
        disk = (
            f"{self._cache_disk[0]:,} files · {human_size(self._cache_disk[1])} on disk"
            if self._cache_disk is not None
            else "Disk usage not measured"
        )
        self.cache_status.setText(
            f"{disk}\n{stats.memory_items} decoded · {stats.pending} loading · "
            f"{stats.memory_hits:,} memory hits · {stats.disk_hits:,} disk hits · "
            f"{stats.network_fetches:,} fetched · {stats.failures:,} failed"
        )

    def clear_cache(self) -> None:
        count, size = self.context.images.clear()
        self._cache_disk = (0, 0)
        self.refresh_cache()
        self.context.notify(f"Cleared {count:,} cached images · {human_size(size)}")

    def import_archives(self) -> None:
        """Bring archives from anywhere into the library the tool manages."""
        start = str(suggested_import_dir())
        path = QFileDialog.getExistingDirectory(self, "Folder holding mods", start)
        if not path:
            return
        self.context.tasks.submit(
            "Import mods",
            lambda progress: library.import_all([Path(path)], move=False),
            on_result=self._imported,
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _imported(self, log: list[str]) -> None:
        added = sum(1 for line in log if line.startswith(("copied", "moved")))
        self.context.notify(f"Imported {added} archive(s)")
        self.refresh_library()
        self.context.refresh_all()

    def refresh_library(self) -> None:
        count, total = library.size()
        self.library_line.setText(
            f"{LIBRARY_DIR}  ·  {count} archive(s), {maintenance.human(total)}"
        )

    def reset(self, scopes: list[str], title: str) -> None:
        """Show exactly what would go, then remove it only if the user agrees.

        The list is the point. "Reset" means different things to different
        people, and the only way to be sure is to name every file first.
        """
        game = self.context.game
        claimed = {name for mod in self.context.catalog.mods for name in mod.all_files}
        todo = maintenance.plan(scopes, game.mods if game else None, claimed)
        if todo.is_empty:
            self.context.notify("Nothing to remove")
            return

        lines = [
            f"{scope}: {len(items)} item(s) — {maintenance.DESCRIPTIONS[scope]}"
            for scope, items in todo.by_scope().items()
        ]
        answer = QMessageBox.warning(
            self,
            title,
            f"This removes {todo.count} item(s), {maintenance.human(todo.bytes)}:\n\n"
            + "\n".join(lines)
            + "\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        for line in maintenance.run(todo):
            self.context.notify(line)
        self.context.refresh_all()
        self.refresh_library()

    def pick_game(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Marvel Rivals folder")
        if path:
            self.game_root.setText(path)

    def add_scan(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add archive folder")
        if path and not self.scan.findItems(path, Qt.MatchFlag.MatchExactly):
            self.scan.addItem(path)

    def remove_scan(self) -> None:
        for item in self.scan.selectedItems():
            self.scan.takeItem(self.scan.row(item))

    def save(self) -> None:
        config = self.context.config
        scan_dirs = [Path(self.scan.item(i).text()) for i in range(self.scan.count())]
        if not scan_dirs:
            self.context.notify("At least one scan folder is required", True)
            return
        config.scan_dirs = scan_dirs
        root = self.game_root.text().strip()
        config.game_root = Path(root) if root else None
        config.gui_theme = "dark" if self.theme.currentIndex() == 0 else "light"
        config.library_density = self.density.currentText().lower()
        config.image_cache_mb = int(self.cache.currentData())
        config.save()
        if key := self.key.text().strip():
            credentials.save_key(key)
            self.context.client.api_key = key
            self.key.clear()
            self.key.setPlaceholderText(credentials.mask(key))
        self.context.images.set_limit(config.image_cache_mb)
        from .application import DARK, LIGHT

        QApplication.instance().setStyleSheet(
            DARK if config.gui_theme == "dark" else LIGHT
        )
        self.context.refresh_all()
        self.context.notify("Settings saved · restart only if the game path changed")

    def register_nxm(self) -> None:
        try:
            result = nxm.register()
        except Exception as error:  # noqa: BLE001 - desktop integration varies by host
            self.context.notify(str(error), True)
        else:
            self.context.notify(" · ".join(result))
            self.refresh_handler()

    def unregister_nxm(self) -> None:
        try:
            result = nxm.unregister()
        except Exception as error:  # noqa: BLE001 - desktop integration varies by host
            self.context.notify(str(error), True)
        else:
            self.context.notify(" · ".join(result))
            self.refresh_handler()

    def refresh_handler(self) -> None:
        handler = nxm.registered_handler()
        self.handler.setText(
            f"Current handler: {handler or 'none'}"
            + (" · regalia owns it" if nxm.is_registered() else "")
        )
