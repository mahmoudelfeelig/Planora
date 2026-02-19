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


def test_split_phased_budget_prioritizes_feasibility():
    assert ui_window.MainWindow._split_phased_budget(45.0) == (45.0, 0.0)

    feas_120, improve_120 = ui_window.MainWindow._split_phased_budget(120.0)
    assert feas_120 == pytest.approx(96.0)
    assert improve_120 == pytest.approx(24.0)
    assert feas_120 > improve_120

    feas_300, improve_300 = ui_window.MainWindow._split_phased_budget(300.0)
    assert feas_300 == pytest.approx(240.0)
    assert improve_300 == pytest.approx(60.0)
    assert feas_300 > improve_300
