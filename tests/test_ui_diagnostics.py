from __future__ import annotations

import os

import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import app as ui_app  # noqa: E402
from ui import window as ui_window  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_top_counts_orders_by_count_then_id(qt_app):
    out = ui_window.MainWindow._top_counts({10: 2, 2: 3, 5: 3, 7: 1}, limit=3)
    assert out == [(2, 3), (5, 3), (10, 2)]


def test_app_icon_prefers_root_logo(qt_app):
    assert ui_app._app_icon_path().endswith("Logo.ico")
    assert ui_window._app_icon_path().endswith("Logo.ico")


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


def test_cp_bound_summary_formats_gap_and_unavailable_reason(qt_app):
    win = ui_window.MainWindow()
    try:
        assert (
            "obj=120.00" in win._cp_bound_summary_from_meta(
                {
                    "attempts": [
                        {
                            "room_mode": "cp_rooms",
                            "use_objective": True,
                            "objective_value": 120.0,
                            "best_objective_bound": 90.0,
                            "relative_gap": 0.25,
                        }
                    ]
                }
            )
        )
        assert "gap=25.00%" in win._cp_bound_summary_from_meta(
            {
                "attempts": [
                    {
                        "room_mode": "cp_rooms",
                        "use_objective": True,
                        "objective_value": 120.0,
                        "best_objective_bound": 90.0,
                        "relative_gap": 0.25,
                    }
                ]
            }
        )
        assert "ran without CP objective" in win._cp_bound_summary_from_meta(
            {
                "objective_profile": "university_quality",
                "attempts": [
                    {
                        "room_mode": "greedy",
                        "use_objective": False,
                    }
                ],
            }
        )
    finally:
        win.close()
        win.deleteLater()


def test_improve_status_keeps_scores_visible(qt_app):
    win = ui_window.MainWindow()
    try:
        full = "Improving... 1% (iter 10/1000, original=1545, current=1516, best=1516)"
        win.set_status(full)
        visible = win.status_label.text()
        assert visible == "Improving 1% | 10/1000 | 1545->1516 | best 1516"
        assert "best 1516" in visible
        assert win.status_label.toolTip() == full
    finally:
        win.close()
        win.deleteLater()


def test_focused_improve_instance_boosts_selected_weight(qt_app):
    win = ui_window.MainWindow()
    try:
        win.on_generate()
        idx = win.improve_focus_combo.findData("thin_day")
        assert idx >= 0
        win.improve_focus_combo.setCurrentIndex(idx)
        focused = win._build_focused_improve_instance("thin_day")
        assert focused is not win.inst
        assert focused.soft_weights["thin_day"] == ui_window.SOFT_WEIGHT_DEFAULTS["thin_day"] * 10
        assert getattr(win.inst, "soft_weights", {}).get("thin_day") == ui_window.SOFT_WEIGHT_DEFAULTS["thin_day"]
    finally:
        win.close()
        win.deleteLater()


def test_project_menu_is_grouped_into_task_submenus(qt_app):
    win = ui_window.MainWindow()
    try:
        top_level = [
            action.text()
            for action in win.project_menu.actions()
            if not action.isSeparator()
        ]
        assert top_level == [
            "File",
            "Import",
            "Reports",
            "Analyze",
            "Edit",
            "Repair",
            "Branches",
            "Release",
            "Institution",
            "Settings & Diagnostics",
            f"About {ui_window.APP_SHORT_NAME}",
        ]

        submenus = {
            action.text(): action.menu()
            for action in win.project_menu.actions()
            if action.menu() is not None
        }
        assert "Import Timetable CSV (create scenario)" in [
            action.text() for action in submenus["Import"].actions()
        ]
        assert "Show Conflicts" in [
            action.text() for action in submenus["Analyze"].actions()
        ]
        assert "Score Breakdown" in [
            action.text() for action in submenus["Analyze"].actions()
        ]
        assert "Fix Current Conflicts" in [
            action.text() for action in submenus["Repair"].actions()
        ]
        assert "Focused CP-SAT Polish" in [
            action.text() for action in submenus["Repair"].actions()
        ]
        assert "Sandbox: Start Branch" in [
            action.text() for action in submenus["Branches"].actions()
        ]
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
