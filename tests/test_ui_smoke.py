from __future__ import annotations

import os
import time

import pytest

PyQt6 = pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

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
        assert not win.export_button.isEnabled()
        win.set_busy(False)
        assert win.solve_button.isEnabled()
        assert win.improve_button.isEnabled()
        assert win.export_button.isEnabled()
    finally:
        win.close()
        win.deleteLater()
