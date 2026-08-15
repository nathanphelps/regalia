"""Entry point for the native Qt desktop application."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import migrate
from ..archive import NoExtractor, require_extractor
from ..config import Config
from .main_window import MainWindow

# Inter is the intended face. Most systems do not ship it, so the list falls
# through to whatever the desktop uses for its own interface.
FONT_STACK = ("Inter", "Cantarell", "Noto Sans", "DejaVu Sans")

DARK = """
QWidget { background:#15171b; color:#efede7; font-size:13px; }
QLabel { background:transparent; }
QMainWindow { background:#15171b; }
#navigationRail { background:#101216; border-right:1px solid #2a2d34; }
#wordmark { color:#f3f0e8; font-size:27px; font-weight:800; letter-spacing:2px; }
#eyebrow, #sectionTitle { color:#969aa5; font-size:10px; font-weight:700; letter-spacing:2px; }
#pageTitle { font-size:27px; font-weight:800; letter-spacing:2px; }
#detailTitle { font-size:21px; font-weight:700; }
#accountBadge { background:#20232b; color:#b7a9ff; padding:12px; border-left:3px solid #8f92e8; }
#statCard { background:#20232b; border:1px solid #2d3039; padding:4px; }
#collectionCard { background:#20232b; border:1px solid #2d3039; }
#navigation { background:transparent; outline:none; }
#navigation::item { color:#999da8; padding:11px 10px; border-left:2px solid transparent; }
#navigation::item:selected { background:#242731; color:#f3f0e8; border-left:2px solid #8f92e8; }
QLineEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QListWidget, QTableWidget {
  background:#20232a; border:1px solid #343842; padding:7px; selection-background-color:#6157b8;
}
QLineEdit:focus, QComboBox:focus, QTableWidget:focus { border:1px solid #8f92e8; }
QHeaderView::section { background:#1b1e24; color:#989ca6; border:0; border-bottom:1px solid #343842; padding:8px; font-size:10px; font-weight:700; }
QTableWidget { gridline-color:#2a2d34; alternate-background-color:#191b20; }
QPushButton { background:#2a2d35; border:1px solid #3b3f49; padding:8px 14px; font-weight:600; }
QPushButton:hover { background:#373b46; border-color:#8f92e8; }
QPushButton:pressed { background:#56508b; }
QScrollBar:vertical { background:#15171b; width:10px; }
QScrollBar::handle:vertical { background:#3b3f48; min-height:30px; }
QScrollBar:horizontal { background:#15171b; height:10px; }
QScrollBar::handle:horizontal { background:#3b3f48; min-width:30px; }
QStatusBar { background:#101216; border-top:1px solid #2a2d34; }
QTabBar::tab { background:#20232a; padding:9px 15px; }
QTabBar::tab:selected { color:#b7a9ff; border-bottom:2px solid #8f92e8; }
"""

LIGHT = """
QWidget { background:#ece8dc; color:#1a1a1a; font-size:13px; }
QLabel { background:transparent; }
#navigationRail { background:#ded8c8; border-right:1px solid #c5beaa; }
#wordmark { font-size:27px; font-weight:800; letter-spacing:2px; }
#eyebrow, #sectionTitle { color:#746f64; font-size:10px; font-weight:700; letter-spacing:2px; }
#pageTitle { font-size:27px; font-weight:800; letter-spacing:2px; }
#detailTitle { font-size:21px; font-weight:700; }
#accountBadge, #statCard { background:#d9d3c0; padding:10px; border:1px solid #c1baa6; }
#collectionCard { background:#d9d3c0; border:1px solid #c1baa6; }
#navigation { background:transparent; outline:none; }
#navigation::item { padding:11px 10px; }
#navigation::item:selected { background:#cec7b4; border-left:2px solid #6c6ce0; }
QLineEdit, QTextEdit, QTextBrowser, QComboBox, QListWidget, QTableWidget { background:#f4f0e7; border:1px solid #bdb5a2; padding:7px; }
QHeaderView::section { background:#d9d3c0; border:0; border-bottom:1px solid #bdb5a2; padding:8px; font-weight:700; }
QPushButton { background:#d9d3c0; border:1px solid #aaa18d; padding:8px 14px; font-weight:600; }
QPushButton:hover { border-color:#6c6ce0; }
QStatusBar { background:#ded8c8; border-top:1px solid #c5beaa; }
"""


def interface_font() -> QFont:
    """The first font in the stack this system actually has."""
    families = set(QFontDatabase.families())
    for name in FONT_STACK:
        if name in families:
            return QFont(name, 10)
    return QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))


def main(config: Config | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("regalia")
    app.setOrganizationName("regalia")
    app.setDesktopFileName("regalia")
    app.setStyle("Fusion")
    app.setFont(interface_font())
    migrate.run()
    config = config or Config.load()
    app.setStyleSheet(DARK if config.gui_theme == "dark" else LIGHT)
    try:
        require_extractor()
    except NoExtractor as error:
        QMessageBox.critical(None, "No archive extractor", str(error))
        return 1
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
