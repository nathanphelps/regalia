"""The native regalia window and navigation shell."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import credentials
from ..catalog import Catalog
from ..config import Config
from ..environment import steam_installs
from ..nexus import NexusClient
from ..paths import GameNotFound, discover_game
from .images import ImageCache
from .pages import (
    ActivityPage,
    CollectionsPage,
    Context,
    DashboardPage,
    LibraryPage,
    NexusPage,
    PatchPage,
    SettingsPage,
)
from .setup import SetupPage
from .state import GuiState
from .tasks import TaskCoordinator


class CommandPalette(QDialog):
    def __init__(self, commands: list[tuple[str, object]], parent=None) -> None:
        super().__init__(parent)
        self.commands = commands
        self.setWindowTitle("Command palette")
        self.setModal(True)
        self.resize(560, 430)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command…")
        self.list = QListWidget()
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.run_current)
        self.list.itemActivated.connect(lambda item: self.run_current())
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.search.setFocus()

    def refresh(self) -> None:
        query = self.search.text().lower().strip()
        self.list.clear()
        for index, (label, _callback) in enumerate(self.commands):
            if query and query not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        callback = self.commands[int(item.data(Qt.ItemDataRole.UserRole))][1]
        self.accept()
        callback()


def _needs_setup(config: Config) -> bool:
    """True when the first screen should be Setup rather than the dashboard."""
    from ..readiness import run_checks

    return run_checks(config).needs_setup


class MainWindow(QMainWindow):
    PAGE_NAMES = (
        "Dashboard",
        "Library",
        "Nexus",
        "Collections",
        "Patch",
        "Activity",
        "Settings",
        "Setup",
    )
    SETUP_ROW = 7

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.setWindowTitle("regalia")
        self.resize(1440, 900)
        self.setMinimumSize(980, 680)
        self.config = config
        self._history = [0]
        self._history_index = 0
        self._navigating_history = False
        self.catalog = Catalog.load()
        self.client = NexusClient(credentials.load_key())
        self.tasks = TaskCoordinator(self)
        self.images = ImageCache(config.image_cache_mb, self)
        self.gui_state = GuiState(self)
        self._locate_game()

        self.context = Context(
            config=config,
            catalog=self.catalog,
            client=self.client,
            tasks=self.tasks,
            images=self.images,
            state=self.gui_state,
            game=self.game,
            game_error=self.game_error,
            notify=self.notify_user,
            refresh_all=self.refresh_all,
            rediscover=self.rediscover,
        )
        self._scan_stamp = 0.0
        self._build()
        self._wire()
        self.refresh_all()
        if _needs_setup(config):
            # A first run, or something the tool cannot work around. Opening the
            # dashboard would show empty tables and explain nothing.
            self.navigation.setCurrentRow(self.SETUP_ROW)
        QTimer.singleShot(10, self._finish_migration)
        QTimer.singleShot(50, self.library.rescan)
        QTimer.singleShot(250, self.dashboard.load_remote)
        if self.client.api_key:
            QTimer.singleShot(400, self.validate_account)
        self.poller = QTimer(self)
        self.poller.timeout.connect(self.poll_scan_dirs)
        self.poller.start(5000)

    def _build(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("navigationRail")
        rail.setFixedWidth(208)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(18, 22, 18, 18)
        wordmark = QLabel("REGALIA")
        wordmark.setObjectName("wordmark")
        rail_layout.addWidget(wordmark)
        subtitle = QLabel("MARVEL RIVALS\nMOD MANAGER")
        subtitle.setObjectName("eyebrow")
        rail_layout.addWidget(subtitle)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFrameShape(QFrame.Shape.NoFrame)
        self.navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.navigation.setSpacing(4)
        for name in self.PAGE_NAMES:
            item = QListWidgetItem(name.upper())
            item.setSizeHint(QSize(160, 43))
            self.navigation.addItem(item)
        rail_layout.addWidget(self.navigation, 1)
        self.account = QLabel("NEXUS\n" + credentials.mask(self.client.api_key))
        self.account.setObjectName("accountBadge")
        rail_layout.addWidget(self.account)
        root_layout.addWidget(rail)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(26, 18, 26, 18)
        top = QHBoxLayout()
        self.back_button = QPushButton("←")
        self.back_button.setToolTip("Back · Alt+Left")
        self.back_button.setFixedWidth(38)
        self.forward_button = QPushButton("→")
        self.forward_button.setToolTip("Forward · Alt+Right")
        self.forward_button.setFixedWidth(38)
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Search Nexus Mods…")
        self.global_search.setClearButtonEnabled(True)
        self.global_search.setMaximumWidth(520)
        self.activity_label = QLabel("IDLE")
        self.activity_label.setObjectName("eyebrow")
        self.activity_progress = QProgressBar()
        self.activity_progress.setRange(0, 0)
        self.activity_progress.setFixedWidth(100)
        self.activity_progress.hide()
        top.addWidget(self.back_button)
        top.addWidget(self.forward_button)
        top.addWidget(self.global_search)
        top.addStretch()
        top.addWidget(self.activity_label)
        top.addWidget(self.activity_progress)
        workspace_layout.addLayout(top)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.context)
        self.library = LibraryPage(self.context)
        self.nexus = NexusPage(self.context)
        self.collections = CollectionsPage(self.context)
        self.patch = PatchPage(self.context)
        self.activity = ActivityPage(self.context)
        self.settings = SettingsPage(self.context)
        self.setup = SetupPage(self.context)
        for page in (
            self.dashboard,
            self.library,
            self.nexus,
            self.collections,
            self.patch,
            self.activity,
            self.settings,
            self.setup,
        ):
            self.stack.addWidget(page)
        workspace_layout.addWidget(self.stack, 1)
        root_layout.addWidget(workspace, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.navigation.setCurrentRow(0)

    def _wire(self) -> None:
        self.navigation.currentRowChanged.connect(self.navigate)
        self.back_button.clicked.connect(self.go_back)
        self.forward_button.clicked.connect(self.go_forward)
        self.global_search.returnPressed.connect(self.global_nexus_search)
        self.tasks.busy_changed.connect(self.set_busy)
        self.tasks.activity_changed.connect(self.activity_summary)
        self.dashboard.open_nexus_mod.connect(self.open_nexus_mod)
        self.library.open_nexus_mod.connect(self.open_nexus_mod)
        self.setup.finished.connect(lambda: self.navigation.setCurrentRow(0))
        self.setup.open_patch.connect(lambda: self.navigation.setCurrentRow(4))

        shortcuts = (
            ("Ctrl+1", 0),
            ("Ctrl+2", 1),
            ("Ctrl+3", 2),
            ("Ctrl+4", 3),
            ("Ctrl+5", 4),
            ("Ctrl+6", 5),
            ("Ctrl+,", 6),
        )
        for sequence, index in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(
                lambda checked=False, i=index: self.navigation.setCurrentRow(i)
            )
            self.addAction(action)
        focus = QAction(self)
        focus.setShortcut(QKeySequence("Ctrl+L"))
        focus.triggered.connect(self.global_search.setFocus)
        self.addAction(focus)
        palette = QAction(self)
        palette.setShortcut(QKeySequence("Ctrl+K"))
        palette.triggered.connect(self.open_command_palette)
        self.addAction(palette)
        back = QAction(self)
        back.setShortcut(QKeySequence("Alt+Left"))
        back.triggered.connect(self.go_back)
        self.addAction(back)
        forward = QAction(self)
        forward.setShortcut(QKeySequence("Alt+Right"))
        forward.triggered.connect(self.go_forward)
        self.addAction(forward)
        self._refresh_history_buttons()

    def navigate(self, index: int) -> None:
        if index < 0:
            return
        if not self._navigating_history:
            current = self._history[self._history_index]
            if index != current:
                self._history = self._history[: self._history_index + 1]
                self._history.append(index)
                self._history_index += 1
        self._refresh_history_buttons()
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.dashboard.refresh_local()
            self.dashboard.load_remote()
        elif index == 3 and not self.collections.collections:
            self.collections.load()
        elif index == 4:
            self.patch.refresh()
        elif index == 5:
            self.activity.refresh()
        elif index == 6:
            self.settings.refresh_handler()

    def _refresh_history_buttons(self) -> None:
        self.back_button.setEnabled(self._history_index > 0)
        self.forward_button.setEnabled(self._history_index < len(self._history) - 1)

    def _go_history(self, delta: int) -> None:
        target = self._history_index + delta
        if not 0 <= target < len(self._history):
            return
        self._history_index = target
        self._navigating_history = True
        try:
            self.navigation.setCurrentRow(self._history[target])
        finally:
            self._navigating_history = False
        self._refresh_history_buttons()

    def go_back(self) -> None:
        self._go_history(-1)

    def go_forward(self) -> None:
        self._go_history(1)

    def open_command_palette(self) -> None:
        commands: list[tuple[str, object]] = [
            (f"Go to {name}", lambda i=index: self.navigation.setCurrentRow(i))
            for index, name in enumerate(self.PAGE_NAMES)
        ]
        commands += [
            ("Search Nexus", self._focus_nexus_search),
            ("Filter local library", self._focus_library_search),
            ("Rescan local library", self.library.rescan),
            ("Identify archives with Nexus", self.library.identify),
            ("Check for mod updates", self.library.check_updates),
            ("Open favorite Nexus mods", self._open_favorites),
            ("Back", self.go_back),
            ("Forward", self.go_forward),
        ]
        CommandPalette(commands, self).exec()

    def _focus_nexus_search(self) -> None:
        self.navigation.setCurrentRow(2)
        self.nexus.search.setFocus()

    def _focus_library_search(self) -> None:
        self.navigation.setCurrentRow(1)
        self.library.search.setFocus()

    def _open_favorites(self) -> None:
        self.navigation.setCurrentRow(2)
        self.nexus.load_favorites()

    def global_nexus_search(self) -> None:
        self.nexus.set_query(self.global_search.text())
        self.navigation.setCurrentRow(2)
        self.nexus.load(reset=True)

    def open_nexus_mod(self, mod_id: int) -> None:
        self.navigation.setCurrentRow(2)
        self.nexus.open_mod(mod_id)

    def notify_user(self, message: str, error: bool = False) -> None:
        self.statusBar().setStyleSheet("color:#df6666" if error else "color:#65c18c")
        self.statusBar().showMessage(message, 9000 if error else 5000)

    def set_busy(self, busy: bool) -> None:
        self.activity_progress.setVisible(busy)
        if not busy:
            self.activity_label.setText("IDLE")

    def activity_summary(self) -> None:
        running = [a for a in self.tasks.activities if a.state == "running"]
        if running:
            activity = running[0]
            self.activity_label.setText(
                f"{activity.label.upper()}"
                + (f"  {activity.progress}%" if activity.progress is not None else "")
            )

    def _locate_game(self) -> None:
        try:
            self.game = discover_game(
                self.config.game_root, steam_installs(self.config.steam_root)
            )
            self.game_error = ""
        except GameNotFound as error:
            self.game = None
            self.game_error = str(error)

    def _finish_migration(self) -> None:
        """Repoint the game's symlinks after a carry-over from the old name."""
        from .. import migrate

        if not migrate.pending() or self.game is None:
            return
        for step in migrate.run(self.game.mods):
            self.notify_user(step)
        self.catalog = Catalog.load()
        self.context.catalog = self.catalog
        self.refresh_all()

    def rediscover(self) -> None:
        """Look for Steam and the game again, after the user changed a path."""
        steam_installs(self.config.steam_root, refresh=True)
        self._locate_game()
        self.context.game = self.game
        self.context.game_error = self.game_error
        self.refresh_all()

    def refresh_all(self) -> None:
        self.library.refresh()
        self.dashboard.refresh_local()
        self.patch.refresh()
        self.activity.refresh()

    def validate_account(self) -> None:
        self.tasks.submit(
            "Validate Nexus account",
            lambda progress: self.client.validate(),
            on_result=lambda account: self.account.setText(
                f"NEXUS\n{account.name}\n{account.badge}"
            ),
            on_error=lambda message, trace: self.notify_user(message, True),
        )

    def poll_scan_dirs(self) -> None:
        stamp = 0.0
        for directory in self.config.scan_dirs:
            if directory.is_dir():
                stamp = max(stamp, directory.stat().st_mtime)
        if self._scan_stamp and stamp > self._scan_stamp:
            self.library.rescan()
        self._scan_stamp = stamp
