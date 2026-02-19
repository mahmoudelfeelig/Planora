from __future__ import annotations

import os

import pytest

PyQt6 = pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import window as ui_window  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_top_counts_orders_by_count_then_id(qt_app):
    out = ui_window.MainWindow._top_counts({10: 2, 2: 3, 5: 3, 7: 1}, limit=3)
    assert out == [(2, 3), (5, 3), (10, 2)]


def test_build_no_feasible_message_includes_attempts(qt_app):
    win = ui_window.MainWindow()
    try:
        res = {
            "status": -1,
            "schedule": {},
            "meta": {
                "attempts": [
                    {"room_mode": "cp_rooms", "use_objective": True, "time_limit_seconds": 30.0, "status": 0},
                    {"room_mode": "cp_rooms", "use_objective": False, "time_limit_seconds": 120.0, "status": 0},
                ]
            },
        }
        msg = win._build_no_feasible_message(res, -1)
        assert "Attempt details:" in msg
        assert "mode=cp_rooms" in msg
        assert "objective=off" in msg
    finally:
        win.close()
        win.deleteLater()
