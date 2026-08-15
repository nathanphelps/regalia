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

from .. import credentials, nxm
from ..environment import download_dir, steam_installs
from ..paths import GameNotFound, discover_game
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
            "Three things cannot be guessed. Fill them in, then work through "
            "anything still marked below."
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

        self.downloads = QLineEdit()
        create = QPushButton("Create")
        create.clicked.connect(self.create_downloads)
        browse_downloads = QPushButton("Browse…")
        browse_downloads.clicked.connect(self.pick_downloads)
        form.addRow("Downloads folder", _row(self.downloads, create, browse_downloads))

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

    def pick_downloads(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Where downloads land")
        if path:
            self.downloads.setText(path)

    def create_downloads(self) -> None:
        path = Path(self.downloads.text().strip()).expanduser()
        if not path.name:
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.context.notify(f"Could not create {path}: {error}", True)
            return
        self.context.notify(f"Created {path}")
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
        downloads = self.downloads.text().strip()
        if downloads:
            config.scan_dirs = [Path(downloads).expanduser()]
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
        if not self.downloads.text().strip():
            first = config.scan_dirs[0] if config.scan_dirs else download_dir()
            self.downloads.setText(str(first))

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
