"""The readiness panel that sits at the top of Settings.

This was a page of its own, called Setup, and it asked for the game folder and
the Nexus key — both of which Settings also asked for, under different names. A
user with a problem had two screens to choose between and no way to tell which
one owned the answer.

There is one screen now. This panel is the part that says what is wrong and
offers the fix; the settings below it are the values to change. The checks come
from `readiness`, so the window and the `doctor` command can never disagree.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import nxm
from ..readiness import Check, Level, run_checks

# About four checks before it scrolls. Enough to see there is a problem and
# what the first one is, without swallowing the screen.
CHECKS_MAX_HEIGHT = 190

MARK_COLOURS = {
    Level.OK: "#7bbf8f",
    Level.WARN: "#d8b678",
    Level.BLOCKED: "#e08585",
}


class ReadinessPanel(QWidget):
    """What is stopping the tool working, and the button that fixes it."""

    open_patch = Signal()

    def __init__(self, context) -> None:
        super().__init__()
        self.context = context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.headline = QLabel()
        self.headline.setObjectName("detailTitle")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        # Bounded, and scrolling when it has more to say than fits. A first run
        # can raise half a dozen checks; letting the panel grow to hold them all
        # takes the room the settings below it need, which is what pushed the
        # fields down to a sliver each.
        self.checks_host = QWidget()
        self.checks_layout = QVBoxLayout(self.checks_host)
        self.checks_layout.setContentsMargins(0, 0, 0, 0)
        self.checks_area = QScrollArea()
        self.checks_area.setWidgetResizable(True)
        self.checks_area.setFrameShape(QFrame.Shape.NoFrame)
        self.checks_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.checks_area.setMaximumHeight(CHECKS_MAX_HEIGHT)
        self.checks_area.setWidget(self.checks_host)
        layout.addWidget(self.checks_area)

        actions = QHBoxLayout()
        self.patch_button = QPushButton("Open the patch screen")
        self.patch_button.clicked.connect(self.open_patch.emit)
        self.handler_button = QPushButton("Register nxm:// links")
        self.handler_button.clicked.connect(self.register_nxm)
        self.menu_button = QPushButton("Add to applications menu")
        self.menu_button.clicked.connect(self.install_entry)
        for button in (self.patch_button, self.handler_button, self.menu_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.refresh()

    # -- actions ---------------------------------------------------------

    def register_nxm(self) -> None:
        try:
            steps = nxm.register()
        except Exception as error:  # noqa: BLE001 - desktop integration varies by host
            self.context.notify(str(error), True)
            return
        self.context.notify(" · ".join(steps))
        self.refresh()

    def install_entry(self) -> None:
        self.context.notify(f"Wrote {nxm.install_app_entry()}")
        self.refresh()

    # -- redraw ----------------------------------------------------------

    def refresh(self) -> None:
        while self.checks_layout.count():
            item = self.checks_layout.takeAt(0)
            if widget := item.widget():
                # Detached now, not only scheduled. `deleteLater` waits for the
                # event loop, so two refreshes in one turn left the first set
                # still parented — visible in the window and counted twice by
                # anything walking the children.
                widget.setParent(None)
                widget.deleteLater()

        report = run_checks(self.context.config)
        # Only what is not yet right. A list of ticks is what the `doctor`
        # command is for; a settings screen showing nine green lines every time
        # buries the one line that matters on the day something breaks.
        outstanding = [check for check in report.checks if check.level is not Level.OK]

        if not outstanding:
            self.headline.setText("Everything is ready.")
            self.checks_layout.addWidget(
                _note("Run `regalia doctor` for the full report.")
            )
        else:
            blocked = sum(1 for c in outstanding if c.level is Level.BLOCKED)
            self.headline.setText(
                f"{len(outstanding)} thing(s) to sort out"
                + (f", {blocked} of them blocking" if blocked else "")
            )
            for check in outstanding:
                self.checks_layout.addWidget(_check_row(check))

        # A button for something already done is noise, and a button that is
        # about to say "already registered" is worse than an absent one.
        names = {check.name for check in outstanding}
        self.patch_button.setVisible("Signature bypass" in names)
        self.handler_button.setVisible("nxm:// handler" in names)
        self.menu_button.setVisible("Applications menu" in names)


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("eyebrow")
    label.setWordWrap(True)
    return label


def _check_row(check: Check) -> QWidget:
    box = QFrame()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 3, 0, 3)

    head = QLabel(f"{check.level.mark}  {check.name} — {check.detail}")
    head.setStyleSheet(f"color:{MARK_COLOURS[check.level]}; font-weight:600;")
    head.setWordWrap(True)
    layout.addWidget(head)

    if check.remedy:
        layout.addWidget(_note(check.remedy))
    return box
