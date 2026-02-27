from __future__ import annotations

import os
import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_lock_indicator_renders(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        # build a tiny schedule with one activity
        a_id, act = next(iter(inst.activities.items()))
        win.current_schedule = {
            a_id: {
                "week": act.week,
                "day": inst.days[0],
                "slot": 0,
                "duration": act.duration,
                "room_id": None,
                "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
                "course_id": act.course_id,
                "group_ids": list(act.group_ids),
                "kind": act.kind,
            }
        }
        win.locked_activities = {a_id: {"day": inst.days[0], "slot": 0}}
        win.populate_weeks()
        win.update_entities()

        # Ensure the view targets the relevant group and week
        win.view_type_combo.setCurrentText("Group")
        g_id = act.group_ids[0] if act.group_ids else None
        if g_id is not None:
            idx = win.entity_combo.findData(g_id)
            if idx >= 0:
                win.entity_combo.setCurrentIndex(idx)
        w_idx = win.week_combo.findData(act.week)
        if w_idx >= 0:
            win.week_combo.setCurrentIndex(w_idx)
        win.update_table()

        item = win.table.item(0, 0)
        assert item is not None
        assert "LOCK[" in item.text()
    finally:
        win.close()
        win.deleteLater()
