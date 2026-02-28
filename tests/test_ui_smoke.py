from __future__ import annotations

import os
import time

import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

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


def test_generate_shows_empty_calendar_before_solve(qt_app):
    win = MainWindow()
    try:
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        assert win.inst is not None
        assert win.current_schedule == {}
        assert win.table.rowCount() == len(win.inst.days)
        assert win.table.columnCount() == int(win.inst.slots_per_day)
        assert (
            win.table.horizontalScrollBarPolicy()
            == win.table.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert (
            win.schedule_view_scroll.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
    finally:
        win.close()
        win.deleteLater()
