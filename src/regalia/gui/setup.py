"""The first-run setup page.

A new user lands here when no settings have ever been saved, or when a check
blocks work. It asks for the three things the tool cannot guess — where the game
is, where downloads land, and the Nexus key — and then shows every check with
the fix beside it.

The checks come from `readiness`, so this page and the `doctor` command can
never disagree about what is wrong.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import credentials, library, nxm
from ..config import suggested_import_dir
from ..environment import steam_installs
from ..paths import LIBRARY_DIR, GameNotFound, discover_game
from ..readiness import Check, Level, run_checks

MARK_COLOURS = {
    Level.OK: "#7bbf8f",
    Level.WARN: "#d8b678",
    Level.BLOCKED: "#e08585",
}


class SetupPage(QWidget):
    """Walk a new user from nothing to a working installation."""

    finished = Signal()
    open_patch = Signal()

    def __init__(self, context) -> None:
        super().__init__()
        self.context = context

        layout = QVBoxLayout(self)
        title = QLabel("SETUP")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        intro = QLabel(
            "Two things cannot be guessed: where the game is, and your Nexus "
            "key. Everything else is checked below, with the fix beside it. "
            "Come back here any time something breaks — Settings is for "
            "changing what already works."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(self._form())
        layout.addWidget(self._checks_panel(), 1)
        layout.addLayout(self._actions())

        self.refresh()

    # -- the three questions ---------------------------------------------

    def _form(self) -> QWidget:
        box = QFrame()
        box.setObjectName("statCard")
        form = QFormLayout(box)

        self.game_root = QLineEdit()
        self.game_root.setPlaceholderText("Found automatically when Steam knows it")
        detect = QPushButton("Detect")
        detect.clicked.connect(self.detect_game)
        browse_game = QPushButton("Browse…")
        browse_game.clicked.connect(self.pick_game)
        form.addRow("Game folder", _row(self.game_root, detect, browse_game))

        # Not a question. The tool owns this folder, and asking the user to
        # nominate one only ever produced a bad answer: a download folder holds
        # everything the browser saves, the desktop offers to empty it, and a
        # mod is keyed by its archive path, so a file that moves loses its
        # record. What is worth offering is a way to bring existing mods in.
        self.library = QLabel()
        self.library.setObjectName("eyebrow")
        self.library.setWordWrap(True)
        bring = QPushButton("Import mods you already have…")
        bring.clicked.connect(self.import_archives)
        form.addRow("Mod library", _row(self.library, bring))

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(credentials.mask(credentials.load_key()))
        save_key = QPushButton("Save key")
        save_key.clicked.connect(self.save_key)
        form.addRow("Nexus API key", _row(self.key, save_key))

        hint = QLabel(
            f'Search works without a key. Downloads need one: <a href="'
            f'{credentials.API_KEY_URL}">{credentials.API_KEY_URL}</a>'
        )
        hint.setOpenExternalLinks(True)
        hint.setObjectName("eyebrow")
        form.addRow("", hint)

        save = QPushButton("Save and re-check")
        save.clicked.connect(self.save)
        form.addRow("", save)
        return box

    # -- the checks ------------------------------------------------------

    def _checks_panel(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        self.checks_host = QWidget()
        self.checks_layout = QVBoxLayout(self.checks_host)
        self.checks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        area.setWidget(self.checks_host)
        return area

    def _actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        handler = QPushButton("Register nxm:// links")
        handler.clicked.connect(self.register_nxm)
        menu = QPushButton("Add to applications menu")
        menu.clicked.connect(self.install_entry)
        patch = QPushButton("Open the patch screen")
        patch.clicked.connect(self.open_patch.emit)
        done = QPushButton("Continue")
        done.clicked.connect(self.finished.emit)
        for button in (handler, menu, patch):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(done)
        return row

    # -- actions ---------------------------------------------------------

    def detect_game(self) -> None:
        config = self.context.config
        try:
            found = discover_game(None, steam_installs(config.steam_root, refresh=True))
        except GameNotFound as error:
            self.context.notify(str(error), True)
            return
        self.game_root.setText(str(found.root))
        self.context.notify(f"Found the game at {found.root}")

    def pick_game(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Marvel Rivals folder")
        if path:
            self.game_root.setText(path)

    def import_archives(self) -> None:
        """Copy archives the user already downloaded into the library.

        Copying rather than moving, because the folder chosen is usually the
        user's own downloads and emptying it without being asked would be a
        surprise. The originals can go once they are satisfied.
        """
        start = str(suggested_import_dir())
        path = QFileDialog.getExistingDirectory(self, "Folder holding mods", start)
        if not path:
            return

        def work(progress):
            return library.import_all([Path(path)], move=False)

        self.context.tasks.submit(
            "Import mods",
            work,
            on_result=self._imported,
            on_error=lambda message, trace: self.context.notify(message, True),
        )

    def _imported(self, log: list[str]) -> None:
        added = sum(1 for line in log if line.startswith(("copied", "moved")))
        held = sum(1 for line in log if line.startswith("already"))
        failed = sum(1 for line in log if line.startswith("failed"))
        message = f"Imported {added} archive(s)"
        if held:
            message += f", {held} already held"
        if failed:
            message += f", {failed} failed"
        self.context.notify(message, bool(failed))
        self.context.refresh_all()
        self.refresh()

    def save_key(self) -> None:
        value = self.key.text().strip()
        if not value:
            return
        credentials.save_key(value)
        self.key.clear()
        self.key.setPlaceholderText(credentials.mask(credentials.load_key()))
        self.context.notify("Nexus key saved")
        self.refresh()

    def save(self) -> None:
        config = self.context.config
        root = self.game_root.text().strip()
        config.game_root = Path(root).expanduser() if root else None
        config.save()
        self.context.rediscover()
        self.context.notify("Settings saved")
        self.refresh()

    def register_nxm(self) -> None:
        for step in nxm.register():
            self.context.notify(step)
        self.refresh()

    def install_entry(self) -> None:
        self.context.notify(f"Wrote {nxm.install_app_entry()}")
        self.refresh()

    # -- redraw ----------------------------------------------------------

    def refresh(self) -> None:
        config = self.context.config
        if not self.game_root.text().strip():
            known = config.game_root or (
                self.context.game.root if self.context.game else None
            )
            self.game_root.setText(str(known) if known else "")
        count, size = library.size()
        watched = (
            f"  ·  also watching {len(config.scan_dirs)} folder(s)"
            if config.scan_dirs
            else ""
        )
        self.library.setText(f"{LIBRARY_DIR}  ·  {count} archive(s){watched}")

        while self.checks_layout.count():
            item = self.checks_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

        report = run_checks(config)
        for check in report.checks:
            self.checks_layout.addWidget(_check_row(check))


def _row(*widgets: QWidget) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widgets[0], 1)
    for widget in widgets[1:]:
        layout.addWidget(widget)
    return box


def _check_row(check: Check) -> QWidget:
    box = QFrame()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 3, 0, 3)

    head = QLabel(f"{check.level.mark}  {check.name} — {check.detail}")
    head.setStyleSheet(f"color:{MARK_COLOURS[check.level]}; font-weight:600;")
    head.setWordWrap(True)
    layout.addWidget(head)

    if check.remedy:
        remedy = QLabel(check.remedy)
        remedy.setWordWrap(True)
        remedy.setObjectName("eyebrow")
        layout.addWidget(remedy)
    return box
