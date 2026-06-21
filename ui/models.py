from __future__ import annotations

from typing import Any, List, Sequence

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class SimpleTableModel(QAbstractTableModel):
    def __init__(
        self,
        headers: Sequence[str] | None = None,
        rows: Sequence[Sequence[Any]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._headers = [str(h) for h in (headers or [])]
        self._rows = [list(row) for row in (rows or [])]

    def set_table(self, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        self.beginResetModel()
        self._headers = [str(h) for h in (headers or [])]
        self._rows = [list(row) for row in (rows or [])]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return int(len(self._rows))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return int(len(self._headers))

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = int(index.row())
        col = int(index.column())
        if not (0 <= row < len(self._rows) and 0 <= col < len(self._headers)):
            return None
        value = self._rows[row][col]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.UserRole:
            return value
        return None

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= int(section) < len(self._headers):
                return self._headers[int(section)]
            return None
        return int(section) + 1

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # type: ignore[override]
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=lambda row: _natural_sort_key(row[column] if 0 <= int(column) < len(row) else ""), reverse=reverse)
        self.layoutChanged.emit()


def _natural_sort_key(value: Any) -> tuple[int, Any]:
    try:
        if value is None:
            return (2, "")
        text = str(value).strip()
        if text == "":
            return (2, "")
        try:
            number = float(text)
            return (0, number)
        except Exception:
            pass
        import re

        parts = re.split(r"(\d+)", text.lower())
        key: List[Any] = []
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return (1, tuple(key))
    except Exception:
        return (3, str(value))
