from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QScrollArea, QTableWidget


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
        area = self._external_scroll_area
        if area is None:
            super().wheelEvent(event)
            return
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        horizontal = horizontal or abs(pixel.x()) > abs(pixel.y()) or abs(angle.x()) > abs(angle.y())
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        raw_delta = pixel.x() if horizontal else pixel.y()
        if raw_delta == 0:
            raw_delta = angle.x() if horizontal else angle.y()
            raw_delta = int(raw_delta / 8)
        before = int(bar.value())
        step = max(1, int(bar.singleStep()))
        bar.setValue(before - int(raw_delta or step))
        if int(bar.value()) != before or int(bar.maximum()) > 0:
            event.accept()
            return
        super().wheelEvent(event)

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
