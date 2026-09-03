from __future__ import annotations

import os
import time

import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QWheelEvent  # noqa: E402

from ui.app import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_mainwindow_constructs_quickly(qt_app):
    start = time.perf_counter()
    win = MainWindow()
    elapsed = time.perf_counter() - start
    try:
        assert elapsed < 1.5
    finally:
        win.close()
        win.deleteLater()


def test_busy_toggle_disables_controls(qt_app):
    win = MainWindow()
    try:
        win.set_busy(True)
        assert not win.solve_button.isEnabled()
        assert not win.improve_button.isEnabled()
        assert not win.export_menu_btn.isEnabled()
        assert not win.project_menu_btn.isEnabled()
        win.set_busy(False)
        assert win.solve_button.isEnabled()
        assert win.improve_button.isEnabled()
        assert win.export_menu_btn.isEnabled()
        assert win.project_menu_btn.isEnabled()
    finally:
        win.close()
        win.deleteLater()


def test_desktop_uses_shared_public_catalog_and_mode_mapping(qt_app):
    win = MainWindow()
    try:
        assert [
            win.scenario_combo.itemData(index)
            for index in range(win.scenario_combo.count())
        ] == [
            "demo",
            "spring_2023",
            "import",
        ]
        assert [
            win.run_mode_combo.itemData(index)
            for index in range(win.run_mode_combo.count())
        ] == [
            "fast",
            "balanced",
            "quality",
        ]

        generated = []
        win.on_generate = lambda: generated.append(win.mode_combo.currentData())
        win.scenario_combo.setCurrentIndex(win.scenario_combo.findData("spring_2023"))
        win._on_public_generate()
        assert generated == ["ss23_uni_like"]

        win.run_mode_combo.setCurrentIndex(win.run_mode_combo.findData("quality"))
        assert win.room_mode_combo.currentData() == "partitioned"
        assert win.objective_profile_combo.currentData() == "university_quality"
        assert win.time_limit_spin.value() == 60
        assert win.objective_cb.isChecked()
    finally:
        win.close()
        win.deleteLater()


def test_generate_shows_empty_calendar_before_solve(qt_app):
    win = MainWindow()
    try:
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        assert win.inst is not None
        assert win.current_schedule == {}
        assert win.table.rowCount() == int(win.inst.slots_per_day)
        assert win.table.columnCount() == len(win.inst.days)
        assert (
            win.table.horizontalScrollBarPolicy()
            == win.table.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert (
            win.schedule_view_scroll.horizontalScrollBarPolicy()
            == win.schedule_view_scroll.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert win.table._external_scroll_area is None
    finally:
        win.close()
        win.deleteLater()


def test_schedule_uses_native_scroll_without_outer_wheel_trap(qt_app):
    win = MainWindow()
    try:
        win.resize(700, 520)
        win._maximize_on_first_show = False
        win._tutorial_checked = True
        win.show()
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        win._apply_table_relayout()
        qt_app.processEvents()

        outer_vertical = win.schedule_view_scroll.verticalScrollBar()
        outer_horizontal = win.schedule_view_scroll.horizontalScrollBar()
        horizontal = win.table.horizontalScrollBar()
        assert horizontal.maximum() > 0
        assert outer_horizontal.maximum() == 0
        assert outer_vertical.maximum() == 0
        assert win.table._external_scroll_area is None

        horizontal.setValue(0)
        event = QWheelEvent(
            QPointF(20, 20),
            QPointF(20, 20),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ShiftModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        win.table.wheelEvent(event)
        assert horizontal.value() > 0
        assert event.isAccepted()
    finally:
        win.close()
        win.deleteLater()


def test_status_toast_is_stateful_and_closeable(qt_app):
    win = MainWindow()
    try:
        win._maximize_on_first_show = False
        win._tutorial_checked = True
        win.resize(1100, 760)
        win.show()
        win.set_status("Building schedule with Balanced mode...")
        qt_app.processEvents()
        assert win.status_toast.isVisible()
        assert win.status_toast.property("level") == "busy"
        assert win.status_toast.progress.isVisible()
        assert win.status_toast.close_button.accessibleName() == "Close notification"

        win.set_status("Draft ready · 182 activities · Balanced")
        qt_app.processEvents()
        assert win.status_toast.property("level") == "success"
        assert not win.status_toast.progress.isVisible()
        win.status_toast.close_button.click()
        deadline = time.perf_counter() + 0.5
        while win.status_toast.isVisible() and time.perf_counter() < deadline:
            qt_app.processEvents()
        assert not win.status_toast.isVisible()

        win.set_status("Solve error: unavailable")
        qt_app.processEvents()
        assert win.status_toast.isVisible()
        assert win.status_toast.property("level") == "error"
    finally:
        win.close()
        win.deleteLater()


def test_desktop_theme_switch_preserves_legible_contrast(qt_app):
    win = MainWindow()
    try:
        win._theme_mode = "light"
        win._apply_theme()
        assert "#eef2f7" in win.styleSheet()
        assert win.theme_button.text() == "Dark"

        win.theme_button.click()
        assert win._theme_mode == "dark"
        assert "#08111f" in win.styleSheet()
        assert "#f3f7fc" in win.styleSheet()
        assert win.theme_button.text() == "Light"
    finally:
        win.close()
        win.deleteLater()
