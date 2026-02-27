from __future__ import annotations

import os

import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import window as ui_window  # noqa: E402
from ui.dialogs import MoveConflictDialog  # noqa: E402
from utils.generator import generate_instance  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _single_activity_schedule(inst):
    a_id, act = next(iter(inst.activities.items()))
    room_id = next(iter(inst.rooms.keys()))
    return int(a_id), {
        int(a_id): {
            "week": int(act.week),
            "day": inst.days[0],
            "slot": 0,
            "duration": int(act.duration),
            "room_id": int(room_id),
            "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
            "course_id": int(act.course_id),
            "group_ids": list(act.group_ids),
            "kind": str(act.kind),
        }
    }


def test_undo_redo_and_revert_base(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, schedule = _single_activity_schedule(inst)
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        moved = {k: v.copy() for k, v in win.current_schedule.items()}
        moved[a_id]["slot"] = 1
        win._push_undo_state()
        win._commit_schedule(moved, "moved")
        assert int(win.current_schedule[a_id]["slot"]) == 1

        win.on_undo()
        assert int(win.current_schedule[a_id]["slot"]) == 0

        win.on_redo()
        assert int(win.current_schedule[a_id]["slot"]) == 1

        win.on_revert_to_base()
        assert int(win.current_schedule[a_id]["slot"]) == int(win.base_schedule[a_id]["slot"])
    finally:
        win.close()
        win.deleteLater()


def test_toggle_lock_and_hold_activity(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, schedule = _single_activity_schedule(inst)
        win.current_schedule = schedule
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        win._toggle_activity_lock(a_id, time_lock=True)
        assert a_id in win.locked_activities
        assert "day" in win.locked_activities[a_id]
        assert "slot" in win.locked_activities[a_id]

        win.on_undo()
        assert a_id not in win.locked_activities

        win._set_held_activity(a_id)
        assert win.held_activity_id == a_id
    finally:
        win.close()
        win.deleteLater()


def test_collect_conflict_errors_reports_overlaps(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        act_ids = list(inst.activities.keys())
        a_id = int(act_ids[0])
        b_id = int(act_ids[1])
        a = inst.activities[a_id]
        b = inst.activities[b_id]
        room_id = next(iter(inst.rooms.keys()))
        shared_group = int(a.group_ids[0] if a.group_ids else b.group_ids[0])

        win.current_schedule = {
            a_id: {
                "week": int(a.week),
                "day": "MON",
                "slot": 0,
                "duration": int(a.duration),
                "room_id": int(room_id),
                "staff_id": int(a.prof_id if a.kind == "LEC" else a.ta_id),
                "course_id": int(a.course_id),
                "group_ids": [shared_group],
                "kind": str(a.kind),
            },
            b_id: {
                "week": int(a.week),
                "day": "MON",
                "slot": 0,
                "duration": int(b.duration),
                "room_id": int(room_id),
                "staff_id": int(b.prof_id if b.kind == "LEC" else b.ta_id),
                "course_id": int(b.course_id),
                "group_ids": [shared_group],
                "kind": str(b.kind),
            },
        }

        errors = win._collect_conflict_errors()
        assert errors
        assert any("overlap" in e.lower() for e in errors)
    finally:
        win.close()
        win.deleteLater()


def test_move_conflict_dialog_force_and_refresh(qt_app):
    inst = generate_instance("small_demo")
    a_id, schedule = _single_activity_schedule(inst)
    conflict = {"activity_id": int(a_id), "reasons": ["room"]}
    options = {int(a_id): [("TUE", 1)]}
    dlg = MoveConflictDialog(
        None,
        inst,
        schedule,
        int(a_id),
        "MON",
        0,
        [conflict],
        options,
    )
    try:
        assert dlg.force_btn.isEnabled()
        assert dlg.conflict_table.rowCount() == 1
        assert dlg.relocate_combo.count() == 1
        dlg._on_force()
        assert dlg.get_decision() == ("force",)

        dlg.update_state([], {}, message="done")
        assert dlg.conflict_table.rowCount() == 0
        assert not dlg.swap_btn.isEnabled()
        assert not dlg.move_btn.isEnabled()
    finally:
        dlg.close()
        dlg.deleteLater()


def test_sandbox_discard_restores_branch_baseline(qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, schedule = _single_activity_schedule(inst)
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        win.on_sandbox_start()
        changed = {k: v.copy() for k, v in win.current_schedule.items()}
        changed[a_id]["slot"] = 1
        win._commit_schedule(changed, "sandbox edit")
        assert int(win.current_schedule[a_id]["slot"]) == 1
        win.on_sandbox_discard()
        assert int(win.current_schedule[a_id]["slot"]) == 0
    finally:
        win.close()
        win.deleteLater()


def test_auto_repair_disruption_freezes_unaffected_and_starts_solver(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        act_ids = list(inst.activities.keys())[:2]
        schedule = {}
        for idx, a_id in enumerate(act_ids):
            act = inst.activities[a_id]
            schedule[int(a_id)] = {
                "week": int(act.week),
                "day": inst.days[0],
                "slot": idx,
                "duration": int(act.duration),
                "room_id": next(iter(inst.rooms.keys())),
                "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                "course_id": int(act.course_id),
                "group_ids": list(act.group_ids),
                "kind": str(act.kind),
            }
        win.current_schedule = schedule
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}

        answers = iter(
            [
                ("Staff outage (week)", True),
                (f"W{inst.weeks[0]}", True),
                ("1: Prof-1", True),
            ]
        )
        monkeypatch.setattr(
            ui_window.QInputDialog,
            "getItem",
            lambda *args, **kwargs: next(answers),
        )

        changed = {k: v.copy() for k, v in schedule.items()}
        first_aid = int(act_ids[0])
        changed[first_aid]["staff_id"] = int(changed[first_aid]["staff_id"])
        monkeypatch.setattr(
            ui_window,
            "apply_staff_outage_week",
            lambda inst_arg, sched_arg, **kwargs: (changed, {first_aid}, set()),
        )

        called = {}

        def fake_start_solver(*, keep_locks: bool):
            called["keep_locks"] = bool(keep_locks)

        monkeypatch.setattr(win, "_start_solver_process", fake_start_solver)
        win.on_auto_repair_disruption()
        assert called["keep_locks"] is True
        # Unaffected activity should be frozen.
        assert len(win.locked_activities) >= 1
    finally:
        win.close()
        win.deleteLater()
