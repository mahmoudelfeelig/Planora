from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QSettings
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services.ui_contract import ui_contract


TUTORIAL_STEPS: tuple[dict[str, str], ...] = tuple(
    {
        "id": str(step["id"]),
        "title": str(step["title"]),
        "description": str(step["body"]),
    }
    for step in ui_contract()["tutorial"]
)


def _normalized_steps(steps: Iterable[Mapping[str, object]] | None) -> Sequence[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(steps or TUTORIAL_STEPS):
        title = str(raw.get("title") or f"Step {index + 1}").strip()
        description = str(raw.get("description") or "").strip()
        if title:
            normalized.append({"title": title, "description": description})
    return normalized or list(TUTORIAL_STEPS)


class TutorialDialog(QDialog):
    SETTINGS_KEY = "tutorial/planora_ui_v1_seen"

    def __init__(self, parent=None, *, icon_path: str = "", steps=None):
        super().__init__(parent)
        self.setObjectName("tutorialDialog")
        self.setWindowTitle("How Planora works")
        self.setModal(True)
        self.setMinimumSize(610, 470)
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 28)
        root.setSpacing(18)

        brand = QHBoxLayout()
        if icon_path:
            logo = QLabel()
            logo.setObjectName("tutorialLogo")
            pixmap = QIcon(icon_path).pixmap(54, 54)
            logo.setPixmap(pixmap)
            logo.setFixedSize(58, 58)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand.addWidget(logo)
        title_box = QVBoxLayout()
        eyebrow = QLabel("PLANORA GUIDED TOUR")
        eyebrow.setObjectName("eyebrowLabel")
        heading = QLabel("A clear path from data to a published timetable")
        heading.setObjectName("tutorialHeading")
        heading.setWordWrap(True)
        title_box.addWidget(eyebrow)
        title_box.addWidget(heading)
        brand.addLayout(title_box, 1)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("quietButton")
        self.close_button.setAccessibleName("Close tutorial")
        brand.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(brand)

        self.stack = QStackedWidget()
        self._steps = _normalized_steps(steps)
        for index, step in enumerate(self._steps):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 12, 0, 12)
            page_layout.setSpacing(16)
            marker = QLabel(f"STEP {index + 1} OF {len(self._steps)}")
            marker.setObjectName("eyebrowLabel")
            page_title = QLabel(step["title"])
            page_title.setObjectName("tutorialStepTitle")
            page_title.setWordWrap(True)
            copy = QLabel(step["description"])
            copy.setObjectName("tutorialCopy")
            copy.setWordWrap(True)
            copy.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            page_layout.addWidget(marker)
            page_layout.addWidget(page_title)
            page_layout.addWidget(copy)
            page_layout.addStretch(1)
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        controls = QHBoxLayout()
        self.skip_button = QPushButton("Skip to schedule")
        self.skip_button.setObjectName("quietButton")
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("secondaryButton")
        self.next_button = QPushButton("Continue")
        controls.addWidget(self.skip_button)
        controls.addStretch(1)
        controls.addWidget(self.back_button)
        controls.addWidget(self.next_button)
        root.addLayout(controls)

        self.skip_button.clicked.connect(self.accept)
        self.close_button.clicked.connect(self.reject)
        self.back_button.clicked.connect(self._go_back)
        self.next_button.clicked.connect(self._go_next)
        self.stack.currentChanged.connect(self._refresh_controls)
        self._refresh_controls(0)

        self.setTabOrder(self.close_button, self.skip_button)
        self.setTabOrder(self.skip_button, self.back_button)
        self.setTabOrder(self.back_button, self.next_button)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._entrance_animation = QPropertyAnimation(effect, b"opacity", self)
        self._entrance_animation.setDuration(180)
        self._entrance_animation.setStartValue(0.15)
        self._entrance_animation.setEndValue(1.0)
        self._entrance_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance_animation.finished.connect(lambda: self.setGraphicsEffect(None))
        self._entrance_animation.start()
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    @classmethod
    def was_seen(cls) -> bool:
        return bool(QSettings("Planora", "Planora").value(cls.SETTINGS_KEY, False, type=bool))

    @classmethod
    def mark_seen(cls) -> None:
        QSettings("Planora", "Planora").setValue(cls.SETTINGS_KEY, True)

    def accept(self) -> None:
        self.mark_seen()
        super().accept()

    def _go_back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))

    def _go_next(self) -> None:
        if self.stack.currentIndex() >= self.stack.count() - 1:
            self.mark_seen()
            self.done(2)
            return
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)

    def _refresh_controls(self, index: int) -> None:
        self.back_button.setEnabled(index > 0)
        self.next_button.setText("Choose timetable data" if index >= self.stack.count() - 1 else "Continue")
