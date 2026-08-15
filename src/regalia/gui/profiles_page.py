"""The Profiles page.

A profile is a whole deployment under a name — a light set for competitive play,
a full set otherwise. It started as a row of buttons above the library, which
was the wrong home for it twice over: it acts on every mod rather than on the
selection, and it had nowhere to say what a switch would actually do.

That last part is the reason this is a page. Switching moves the whole library
at once, and a name and a count give the user no way to picture it. This screen
names what would go off before anything happens, because turning a mod on is
visible in game and turning one off is what surprises people.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import profiles
from ..model import State
from .widgets import section_title

HEADERS = ("Profile", "Mods", "Parts", "Saved")


class ProfilesPage(QWidget):
    """Save the running set of mods under a name, and switch between them."""

    def __init__(self, context) -> None:
        super().__init__()
        self.context = context
        self.store = profiles.ProfileStore.load()

        layout = QVBoxLayout(self)
        title = QLabel("PROFILES")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setObjectName("eyebrow")
        layout.addWidget(self.intro)

        bar = QHBoxLayout()
        save_current = QPushButton("Save what is running as…")
        save_current.clicked.connect(self.save_current)
        bar.addWidget(save_current)
        bar.addStretch()
        layout.addLayout(bar)

        splitter = QSplitter()
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.refresh_detail)
        self.table.doubleClicked.connect(self.apply_selected)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Select a profile")
        self.detail_title.setObjectName("detailTitle")
        detail_layout.addWidget(self.detail_title)

        detail_layout.addWidget(section_title("What switching would do"))
        self.change_summary = QLabel()
        self.change_summary.setWordWrap(True)
        detail_layout.addWidget(self.change_summary)
        self.change_detail = QLabel()
        self.change_detail.setWordWrap(True)
        self.change_detail.setObjectName("eyebrow")
        detail_layout.addWidget(self.change_detail)

        self.apply_button = QPushButton("Switch to this profile")
        self.apply_button.clicked.connect(self.apply_selected)
        detail_layout.addWidget(self.apply_button)

        actions = QHBoxLayout()
        # Held together so they can be switched off as a set. Every one of them
        # acts on the selected profile, and a live button that does nothing when
        # pressed reads as a broken one.
        self.selection_buttons = []
        for label, slot in (
            ("Replace with what is running", self.replace_selected),
            ("Rename…", self.rename_selected),
            ("Duplicate", self.duplicate_selected),
            ("Delete", self.delete_selected),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
            self.selection_buttons.append(button)
        detail_layout.addLayout(actions)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([640, 520])
        layout.addWidget(splitter, 1)

        self.refresh()

    # -- reading ---------------------------------------------------------

    def current(self) -> profiles.Profile | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.store.profiles):
            return self.store.profiles[row]
        return None

    def refresh(self) -> None:
        self.store = profiles.ProfileStore.load()
        running = sum(
            1 for mod in self.context.catalog.mods if mod.state is State.INSTALLED
        )
        self.intro.setText(
            f"{running} mod(s) running now. A profile remembers which mods ran "
            "and which parts of each, so a body size chosen out of a twenty-four "
            "part archive comes back the way you left it."
        )

        keep = self.table.currentRow()
        self.table.setRowCount(len(self.store.profiles))
        for row, item in enumerate(self.store.profiles):
            for column, text in enumerate(
                (item.name, str(item.size), str(item.part_count), item.saved_label)
            ):
                cell = QTableWidgetItem(text)
                if column:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, cell)
        if self.store.profiles:
            self.table.selectRow(min(max(keep, 0), len(self.store.profiles) - 1))
        self.refresh_detail()

    def refresh_detail(self) -> None:
        profile = self.current()
        has = profile is not None
        self.apply_button.setEnabled(has)
        for button in self.selection_buttons:
            button.setEnabled(has)
        if profile is None:
            self.detail_title.setText(
                "No profiles yet" if not self.store.profiles else "Select a profile"
            )
            self.change_summary.setText(
                "Set the library up the way you want it, then save it as a profile."
                if not self.store.profiles
                else ""
            )
            self.change_detail.setText("")
            return

        self.detail_title.setText(profile.name)
        change = profiles.preview(profile, self.context.catalog.mods)
        if not change.linked and not change.unlinked:
            self.change_summary.setText("Nothing. This is what is running now.")
        else:
            self.change_summary.setText(
                f"{len(change.linked)} mod(s) switched on, "
                f"{len(change.unlinked)} switched off, "
                f"{len(change.unchanged)} left alone."
            )

        notes: list[str] = []
        if change.unlinked:
            notes.append("Would go off: " + self._names(change.unlinked))
        if change.linked:
            notes.append("Would come on: " + self._names(change.linked))
        if change.missing:
            # Named rather than dropped: the user chose these once, and a
            # profile quietly getting smaller is worse than one that complains.
            notes.append(
                f"{len(change.missing)} mod(s) in this profile are no longer in "
                "the library and will be skipped."
            )
        self.change_detail.setText("\n\n".join(notes))

    def _names(self, slugs: list[str], limit: int = 6) -> str:
        by_slug = {mod.slug: mod for mod in self.context.catalog.mods}
        titles = [by_slug[slug].title for slug in slugs if slug in by_slug]
        shown = ", ".join(titles[:limit])
        extra = "" if len(titles) <= limit else f" and {len(titles) - limit} more"
        return f"{shown}{extra}"

    # -- writing ---------------------------------------------------------

    def save_current(self) -> None:
        name, agreed = QInputDialog.getText(
            self, "Save profile", "Name for the set of mods running now"
        )
        if not agreed:
            return
        self._store(name)

    def replace_selected(self) -> None:
        profile = self.current()
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "Replace profile",
            f"Replace {profile.name} with the {self._running()} mod(s) running "
            "now? The saved set is lost.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store(profile.name)

    def duplicate_selected(self) -> None:
        profile = self.current()
        if profile is None:
            return
        name, agreed = QInputDialog.getText(
            self, "Duplicate profile", "Name for the copy", text=f"{profile.name} copy"
        )
        if not agreed:
            return
        try:
            copy = profiles.Profile(
                name=profiles.clean_name(name),
                parts=dict(profile.parts),
                saved=profile.saved,
            )
        except profiles.ProfileError as error:
            self.context.notify(str(error), True)
            return
        self.store.put(copy)
        self.store.save()
        self.refresh()
        self.context.notify(f"Copied to {copy.name}")

    def rename_selected(self) -> None:
        profile = self.current()
        if profile is None:
            return
        name, agreed = QInputDialog.getText(
            self, "Rename profile", "New name", text=profile.name
        )
        if not agreed:
            return
        try:
            renamed = profiles.clean_name(name)
        except profiles.ProfileError as error:
            self.context.notify(str(error), True)
            return
        self.store.remove(profile.name)
        profile.rename(renamed)
        self.store.put(profile)
        self.store.save()
        self.refresh()

    def delete_selected(self) -> None:
        profile = self.current()
        if profile is None:
            return
        answer = QMessageBox.question(
            self, "Delete profile", f"Delete the profile {profile.name}?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.remove(profile.name)
        self.store.save()
        self.refresh()
        self.context.notify(f"Deleted {profile.name}")

    def apply_selected(self) -> None:
        profile = self.current()
        game = self.context.game
        if profile is None:
            return
        if game is None:
            self.context.notify(self.context.game_error or "Game not found", True)
            return

        change = profiles.preview(profile, self.context.catalog.mods)
        if change.unlinked or change.linked:
            answer = QMessageBox.question(
                self,
                f"Switch to {profile.name}",
                f"{len(change.linked)} mod(s) on, {len(change.unlinked)} off. "
                "Nothing is deleted — the files stay and switching back is quick.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        def work(progress):
            progress(10, profile.name)
            outcome = profiles.apply(profile, self.context.catalog.mods, game.mods)
            self.context.catalog.verify(game.mods)
            self.context.catalog.save()
            return outcome

        self.context.tasks.submit(
            f"Switch to {profile.name}",
            work,
            on_result=self._applied,
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _applied(self, outcome) -> None:
        self.context.notify(outcome.summary, bool(outcome.problems))
        for line in outcome.problems[:3]:
            self.context.notify(line, True)
        self.context.refresh_all()
        self.refresh()

    def _running(self) -> int:
        return sum(
            1 for mod in self.context.catalog.mods if mod.state is State.INSTALLED
        )

    def _store(self, name: str) -> None:
        try:
            saved = profiles.capture(name, self.context.catalog.mods)
        except profiles.ProfileError as error:
            self.context.notify(str(error), True)
            return
        self.store.put(saved)
        self.store.save()
        self.refresh()
        self.context.notify(f"Saved {saved.name}: {saved.size} mod(s)")
