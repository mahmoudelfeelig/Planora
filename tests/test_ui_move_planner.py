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


def _build_single_activity_schedule(inst):
    a_id, act = next(iter(inst.activities.items()))
    return {
        int(a_id): {
            "week": int(act.week),
            "day": inst.days[0],
            "slot": 0,
            "duration": int(act.duration),
            "room_id": next(iter(inst.rooms.keys())),
            "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
            "course_id": int(act.course_id),
            "group_ids": list(act.group_ids),
            "kind": str(act.kind),
        }
    }


def test_collect_held_target_map_uses_check_move(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        win.current_schedule = _build_single_activity_schedule(inst)
        held_id = next(iter(win.current_schedule.keys()))
        win.held_activity_id = held_id

        def fake_check_move(
            a_id,
            day,
            slot,
            room_id,
            staff_id,
            week=None,
            schedule_override=None,
        ):
            return (day == "MON" and int(slot) == 0), "blocked"

        win.check_move = fake_check_move  # type: ignore[assignment]
        mapping = win._collect_held_target_map(win.current_schedule[held_id]["week"])
        assert mapping[("MON", 0)] is True
        # At least one other slot should be invalid.
        assert any(not ok for (d, s), ok in mapping.items() if (d, s) != ("MON", 0))
    finally:
        win.close()
        win.deleteLater()


def test_find_move_conflicts_detects_overlap_reasons(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        act_ids = list(inst.activities.keys())
        a_id = int(act_ids[0])
        b_id = int(act_ids[1])
        a = inst.activities[a_id]
        b = inst.activities[b_id]

        shared_group = a.group_ids[0] if a.group_ids else b.group_ids[0]
        room_id = next(iter(inst.rooms.keys()))
        staff_id = int(a.prof_id if a.kind == "LEC" else a.ta_id)
        week = int(a.week)
        win.current_schedule = {
            a_id: {
                "week": week,
                "day": "MON",
                "slot": 1,
                "duration": max(1, int(a.duration)),
                "room_id": room_id,
                "staff_id": staff_id,
                "course_id": int(a.course_id),
                "group_ids": [int(shared_group)],
                "kind": str(a.kind),
            },
            b_id: {
                "week": week,
                "day": "MON",
                "slot": 1,
                "duration": max(1, int(b.duration)),
                "room_id": room_id,
                "staff_id": staff_id,
                "course_id": int(b.course_id),
                "group_ids": [int(shared_group)],
                "kind": str(b.kind),
            },
        }

        conflicts = win._find_move_conflicts(
            a_id=a_id,
            new_day="MON",
            new_slot=1,
            new_room_id=room_id,
            new_staff_id=staff_id,
        )
        assert conflicts
        assert conflicts[0]["activity_id"] == b_id
        reasons = set(conflicts[0]["reasons"])
        assert {"staff", "room", "group"}.issubset(reasons)
    finally:
        win.close()
        win.deleteLater()
