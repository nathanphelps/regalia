"""Reusable image-led widgets for the Qt interface."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..nexus.models import Page
from .images import ImageCache


class ImageTile(QWidget):
    clicked = Signal()

    def __init__(
        self,
        cache: ImageCache,
        url: str = "",
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self.url = url
        self.title = title
        self.subtitle = subtitle
        self.image: QImage | None = None
        self.failed = False
        self.crop = True
        self.hovered = False
        self.setMinimumSize(220, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        cache.image_ready.connect(self._image_ready)
        cache.image_failed.connect(self._image_failed)

    def set_content(self, url: str, title: str, subtitle: str = "") -> None:
        self.url, self.title, self.subtitle = url, title, subtitle
        self.image = None
        self.failed = False
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(260, 168)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._request()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.image is None:
            self._request()

    def _request(self) -> None:
        if self.url and self.image is None and not self.failed:
            image = self.cache.request(self.url, self.width(), self.height())
            if image is not None:
                self.image = image
                self.update()

    def _image_ready(self, url: str, image: QImage) -> None:
        if url == self.url:
            self.image = image
            self.failed = False
            self.update()

    def _image_failed(self, url: str) -> None:
        if url == self.url:
            self.failed = True
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor("#252831"))

        if self.image and not self.image.isNull():
            pixmap = QPixmap.fromImage(self.image)
            scaled = pixmap.scaled(
                rect.size(),
                (
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding
                    if self.crop
                    else Qt.AspectRatioMode.KeepAspectRatio
                ),
                Qt.TransformationMode.SmoothTransformation,
            )
            if self.crop:
                source = QRect(
                    max(0, (scaled.width() - rect.width()) // 2),
                    max(0, (scaled.height() - rect.height()) // 2),
                    rect.width(),
                    rect.height(),
                )
                painter.drawPixmap(rect, scaled, source)
            else:
                x = (rect.width() - scaled.width()) // 2
                y = (rect.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(rect, QColor("#292c35"))
            painter.setPen(QColor("#505461"))
            painter.drawLine(0, rect.height(), rect.width(), 0)

        gradient = QColor(10, 11, 14, 205)
        painter.fillRect(
            QRect(0, max(0, self.height() - 65), self.width(), 65), gradient
        )
        painter.setPen(QColor("#f0ede5"))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            QRect(14, self.height() - 57, self.width() - 28, 27),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.title,
        )
        if self.subtitle:
            painter.setPen(QColor("#b4b5bd"))
            small = QFont(self.font())
            small.setPointSize(8)
            painter.setFont(small)
            painter.drawText(
                QRect(14, self.height() - 31, self.width() - 28, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )
        if self.failed:
            painter.setPen(QColor("#e4b363"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "IMAGE UNAVAILABLE")
        if self.hovered:
            pen = painter.pen()
            pen.setColor(QColor("#8f92e8"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "—", accent: str | None = None) -> None:
        super().__init__()
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        self.label = QLabel(label.upper())
        self.label.setObjectName("eyebrow")
        self.value = QLabel(value)
        style = "font-size:26px;font-weight:700"
        self.value.setStyleSheet(f"{style};color:{accent}" if accent else style)
        layout.addWidget(self.label)
        layout.addWidget(self.value)

    def set_value(self, value: str, accent: str | None = None) -> None:
        self.value.setText(value)
        if accent:
            self.value.setStyleSheet(f"color:{accent};font-size:26px;font-weight:700")


class HorizontalRail(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.layout_ = QHBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 0, 6)
        self.layout_.setSpacing(12)
        self.layout_.addStretch()
        self.setWidget(self.body)
        self.setFixedHeight(205)

    def clear(self) -> None:
        while self.layout_.count() > 1:
            item = self.layout_.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

    def add_tile(self, tile: ImageTile) -> None:
        self.layout_.insertWidget(self.layout_.count() - 1, tile)


class GalleryDialog(QDialog):
    def __init__(
        self,
        cache: ImageCache,
        images: list,
        index: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self.images = images
        self.index = index
        self.setWindowTitle("Nexus gallery")
        self.resize(1100, 760)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.viewer = ImageTile(cache)
        self.viewer.crop = False
        self.viewer.setMinimumHeight(620)
        self.viewer.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.viewer, 1)
        controls = QHBoxLayout()
        previous = QPushButton("← Previous")
        previous.clicked.connect(self.previous)
        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        next_ = QPushButton("Next →")
        next_.clicked.connect(self.next)
        original = QPushButton("Open original")
        original.clicked.connect(self.open_original)
        controls.addWidget(previous)
        controls.addWidget(self.caption, 1)
        controls.addWidget(original)
        controls.addWidget(next_)
        layout.addLayout(controls)
        self.show_image()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.previous()
            return
        if event.key() == Qt.Key.Key_Right:
            self.next()
            return
        super().keyPressEvent(event)

    def previous(self) -> None:
        if self.images:
            self.index = (self.index - 1) % len(self.images)
            self.show_image()

    def next(self) -> None:
        if self.images:
            self.index = (self.index + 1) % len(self.images)
            self.show_image()

    def open_original(self) -> None:
        if self.images:
            QDesktopServices.openUrl(QUrl(self.images[self.index].url))

    def show_image(self) -> None:
        if not self.images:
            self.viewer.set_content("", "No images")
            return
        image = self.images[self.index]
        self.viewer.set_content(image.url, image.title or "Nexus image", image.caption)
        self.caption.setText(f"{self.index + 1} / {len(self.images)}")


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


class Paginator(QWidget):
    page_requested = Signal(int, int)  # offset, page size

    def __init__(self, page_size: int = 24, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page: Page | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        self.first_button = QPushButton("|←")
        self.previous_button = QPushButton("← Previous")
        self.label = QLabel("No results")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton("Next →")
        self.last_button = QPushButton("→|")
        self.size = QComboBox()
        for value in (24, 40, 60, 100):
            self.size.addItem(f"{value} / page", value)
        index = self.size.findData(page_size)
        self.size.setCurrentIndex(max(0, index))
        self.first_button.clicked.connect(lambda: self.request(0))
        self.previous_button.clicked.connect(self.previous)
        self.next_button.clicked.connect(self.next)
        self.last_button.clicked.connect(self.last)
        self.size.currentIndexChanged.connect(lambda: self.request(0))
        layout.addWidget(self.first_button)
        layout.addWidget(self.previous_button)
        layout.addStretch()
        layout.addWidget(self.label)
        layout.addStretch()
        layout.addWidget(self.size)
        layout.addWidget(self.next_button)
        layout.addWidget(self.last_button)
        self.set_page(None)

    @property
    def page_size(self) -> int:
        return int(self.size.currentData())

    def set_page(self, page: Page | None) -> None:
        self.page = page
        if page is None or not page.items:
            total = page.total if page else 0
            self.label.setText(f"No results · {total:,} total")
            has_previous = bool(page and page.has_previous)
            self.first_button.setEnabled(has_previous)
            self.previous_button.setEnabled(has_previous)
            self.next_button.setEnabled(False)
            self.last_button.setEnabled(False)
            return
        page_number = page.offset // page.count + 1
        page_count = max(1, (page.total + page.count - 1) // page.count)
        self.label.setText(
            f"{page.first:,}–{page.last:,} of {page.total:,} · page "
            f"{page_number:,} / {page_count:,}"
        )
        self.first_button.setEnabled(page.has_previous)
        self.previous_button.setEnabled(page.has_previous)
        self.next_button.setEnabled(page.has_next)
        self.last_button.setEnabled(page.has_next)

    def request(self, offset: int) -> None:
        self.page_requested.emit(max(0, offset), self.page_size)

    def previous(self) -> None:
        if self.page:
            self.request(max(0, self.page.offset - self.page.count))

    def next(self) -> None:
        if self.page:
            self.request(self.page.offset + self.page.count)

    def last(self) -> None:
        if self.page and self.page.total:
            offset = ((self.page.total - 1) // self.page_size) * self.page_size
            self.request(offset)
