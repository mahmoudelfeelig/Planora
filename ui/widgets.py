from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
)


class ScheduleItemDelegate(QStyledItemDelegate):
    """Paint selection as an outline without washing out pastel class cards."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        clean_option = QStyleOptionViewItem(option)
        if selected:
            clean_option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, clean_option, index)
        if not selected:
            return
        painter.save()
        pen = QPen(option.palette.highlight().color(), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


class StatusToast(QFrame):
    """Closeable, stateful desktop notification with restrained motion."""

    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusToast")
        self.setProperty("level", "info")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 9, 10, 9)
        root.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("toastIcon")
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(5)
        self.message_label = QLabel()
        self.message_label.setObjectName("toastMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.progress = QProgressBar()
        self.progress.setObjectName("toastProgress")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        copy.addWidget(self.message_label)
        copy.addWidget(self.progress)
        root.addLayout(copy, 1)

        self.close_button = QToolButton()
        self.close_button.setObjectName("toastCloseButton")
        self.close_button.setAccessibleName("Close notification")
        self.close_button.setAutoRaise(True)
        self.close_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        self.close_button.clicked.connect(self.dismiss)
        root.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.timeout.connect(self.dismiss)
        self._animation: QPropertyAnimation | None = None
        self.setMaximumHeight(0)
        self.hide()

    def _state_icon(self, level: str):
        standard = {
            "busy": QStyle.StandardPixmap.SP_BrowserReload,
            "success": QStyle.StandardPixmap.SP_DialogApplyButton,
            "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
            "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
        }.get(level, QStyle.StandardPixmap.SP_MessageBoxInformation)
        return self.style().standardIcon(standard)

    def show_message(
        self,
        message: str,
        *,
        level: str = "info",
        auto_close_ms: int = 0,
    ) -> None:
        normalized = level if level in {"info", "busy", "success", "warning", "error"} else "info"
        self._auto_close.stop()
        self.setProperty("level", normalized)
        self.message_label.setText(str(message))
        self.icon_label.setPixmap(self._state_icon(normalized).pixmap(18, 18))
        self.progress.setVisible(normalized == "busy")
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        self.raise_()

        target = max(46, int(self.sizeHint().height()))
        self._animate_height(max(0, int(self.maximumHeight())), target)
        if auto_close_ms > 0:
            self._auto_close.start(int(auto_close_ms))

    def dismiss(self) -> None:
        self._auto_close.stop()
        if not self.isVisible():
            return
        self._animate_height(max(0, int(self.height())), 0, hide_when_done=True)

    def _animate_height(self, start: int, end: int, *, hide_when_done: bool = False) -> None:
        if self._animation is not None:
            self._animation.stop()
        animation = QPropertyAnimation(self, b"maximumHeight", self)
        animation.setDuration(150)
        animation.setStartValue(int(start))
        animation.setEndValue(int(end))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if hide_when_done:
            animation.finished.connect(self._finish_dismiss)
        self._animation = animation
        animation.start()

    def _finish_dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()


class ScheduleTableWidget(QTableWidget):
    dragRequested = pyqtSignal(int, int)
    dropRequested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos: QPoint | None = None
        self._external_scroll_area: QScrollArea | None = None
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def setExternalScrollArea(self, area: QScrollArea | None) -> None:
        self._external_scroll_area = area

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        horizontal = horizontal or abs(pixel.x()) > abs(pixel.y()) or abs(angle.x()) > abs(angle.y())
        own_bar = self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        own_before = int(own_bar.value())
        raw_delta = pixel.x() if horizontal else pixel.y()
        if horizontal and raw_delta == 0:
            raw_delta = pixel.y()
        if raw_delta == 0:
            raw_delta = angle.x() if horizontal else angle.y()
            if horizontal and raw_delta == 0:
                raw_delta = angle.y()
            raw_delta = int(raw_delta / 8)
        if horizontal:
            own_bar.setValue(own_before - int(raw_delta or own_bar.singleStep()))
        else:
            super().wheelEvent(event)
        if int(own_bar.value()) != own_before:
            event.accept()
            return

        area = self._external_scroll_area
        if area is None:
            event.ignore()
            return
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        before = int(bar.value())
        step = max(1, int(bar.singleStep()))
        bar.setValue(before - int(raw_delta or step))
        if int(bar.value()) != before or int(bar.maximum()) > 0:
            event.accept()
            return
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if (
            self._drag_start_pos is None
            or not (event.buttons() & Qt.MouseButton.LeftButton)
            or (event.pos() - self._drag_start_pos).manhattanLength()
            < self.startDragDistance()
        ):
            super().mouseMoveEvent(event)
            return
        item = self.itemAt(self._drag_start_pos)
        if item is None:
            super().mouseMoveEvent(event)
            return
        self.dragRequested.emit(int(item.row()), int(item.column()))
        drag = QDrag(self)
        pixmap = QPixmap(max(80, item.sizeHint().width()), max(32, item.sizeHint().height()))
        pixmap.fill(Qt.GlobalColor.transparent)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.MoveAction)
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            self.dropRequested.emit(int(item.row()), int(item.column()))
            event.acceptProposedAction()
            return
        super().dropEvent(event)
