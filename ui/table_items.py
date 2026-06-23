from __future__ import annotations

import re
from typing import Any, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractSpinBox, QSpinBox, QTableWidgetItem, QToolButton, QWidget


class StepSpinBox(QSpinBox):
    """Spinbox with explicit +/- buttons so controls are visible across styles/themes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("stepBox", True)
        self._btn_plus = QToolButton(self)
        self._btn_minus = QToolButton(self)
        self._configure_button(self._btn_minus, "-", "left", self.stepDown)
        self._configure_button(self._btn_plus, "+", "right", self.stepUp)

    def _configure_button(
        self,
        button: QToolButton,
        text: str,
        direction: str,
        callback,
    ) -> None:
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAutoRaise(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRepeat(True)
        button.setProperty("spinStep", True)
        button.setProperty("spinDir", direction)
        button.clicked.connect(callback)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Keep inner step buttons away from the outer frame so the global outline stays visible.
        inset = 3
        hinted_w = max(
            int(self._btn_plus.minimumSizeHint().width()),
            int(self._btn_minus.minimumSizeHint().width()),
            14,
        )
        w = min(hinted_w, max(14, self.width() - (2 * inset) - 2))
        h = max(14, self.height() - (2 * inset))
        right_x = max(inset, self.width() - w - inset)
        self._btn_minus.setGeometry(inset, inset, w, h)
        self._btn_plus.setGeometry(right_x, inset, w, h)
        self._btn_plus.raise_()
        self._btn_minus.raise_()


class NumericTableItem(QTableWidgetItem):
    """Table item that sorts numeric text by numeric value."""

    @staticmethod
    def _to_number(value: str) -> float | int | None:
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
                return int(text)
            return float(text)
        except Exception:
            return None

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, QTableWidgetItem):
            a_num = self._to_number(self.text())
            b_num = self._to_number(other.text())
            if a_num is not None and b_num is not None:
                return a_num < b_num
            if a_num is not None and b_num is None:
                return True
            if a_num is None and b_num is not None:
                return False
            return self.text().lower() < other.text().lower()
        return super().__lt__(other)


class NaturalSortTableItem(QTableWidgetItem):
    """Table item that sorts mixed text/number tokens naturally."""

    @staticmethod
    def _key(value: str) -> tuple:
        parts = re.split(r"(\d+)", str(value).strip().lower())
        key: List[Any] = []
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return tuple(key)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, QTableWidgetItem):
            return self._key(self.text()) < self._key(other.text())
        return super().__lt__(other)
