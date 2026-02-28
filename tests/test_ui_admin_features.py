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
    room_id = None
    total_students = sum(int(inst.groups[g].size) for g in act.group_ids if g in inst.groups)
    for rid, room in inst.rooms.items():
        if int(room.capacity) < int(total_students):
            continue
        if act.kind == "LEC" and room.room_type != "LECTURE":
            continue
        if act.kind == "TUT" and room.room_type not in ("LECTURE", "TUTORIAL"):
            continue
        if act.kind == "LAB" and room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
            continue
        tag = getattr(act, "requires_specialization", None)
        if tag and tag not in set(getattr(room, "specialization_tags", []) or []):
            continue
        room_id = int(rid)
        break
    if room_id is None:
        room_id = int(next(iter(inst.rooms.keys())))
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


def _pick_valid_room_id(inst, act) -> int:
    total_students = sum(
        int(inst.groups[g].size) for g in act.group_ids if g in inst.groups
    )
    for rid, room in inst.rooms.items():
        if int(room.capacity) < int(total_students):
            continue
        if act.kind == "LEC" and room.room_type != "LECTURE":
            continue
        if act.kind == "TUT" and room.room_type not in ("LECTURE", "TUTORIAL"):
            continue
        if act.kind == "LAB" and room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
            continue
        tag = getattr(act, "requires_specialization", None)
        if tag and tag not in set(getattr(room, "specialization_tags", []) or []):
            continue
        return int(rid)
    return int(next(iter(inst.rooms.keys())))


def _conflicting_schedule_with_extra(inst):
    act_ids = list(inst.activities.keys())
    a_id = int(act_ids[0])
    b_id = int(act_ids[1])
    c_id = int(act_ids[2]) if len(act_ids) > 2 else int(act_ids[0])
    a = inst.activities[a_id]
    b = inst.activities[b_id]
    c = inst.activities[c_id]
    week = int(a.week)
    room_id = _pick_valid_room_id(inst, a)
    c_room_id = _pick_valid_room_id(inst, c)
    shared_group = int(a.group_ids[0] if a.group_ids else b.group_ids[0])
    shared_staff = int(a.prof_id if a.kind == "LEC" else a.ta_id)
    c_staff = int(c.prof_id if c.kind == "LEC" else c.ta_id)
    schedule = {
        a_id: {
            "week": week,
            "day": "MON",
            "slot": 0,
            "duration": int(a.duration),
            "room_id": room_id,
            "staff_id": shared_staff,
            "course_id": int(a.course_id),
            "group_ids": [shared_group],
            "kind": str(a.kind),
        },
        b_id: {
            "week": week,
            "day": "MON",
            "slot": 0,
            "duration": int(b.duration),
            "room_id": room_id,
            "staff_id": shared_staff,
            "course_id": int(b.course_id),
            "group_ids": [shared_group],
            "kind": str(b.kind),
        },
        c_id: {
            "week": int(c.week),
            "day": "TUE",
            "slot": 2,
            "duration": int(c.duration),
            "room_id": c_room_id,
            "staff_id": c_staff,
            "course_id": int(c.course_id),
            "group_ids": list(c.group_ids),
            "kind": str(c.kind),
        },
    }
    return a_id, b_id, c_id, schedule


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


def test_revert_to_base_blocked_when_base_has_hard_conflicts(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        act_ids = list(inst.activities.keys())
        a_id = int(act_ids[0])
        b_id = int(act_ids[1])
        a = inst.activities[a_id]
        b = inst.activities[b_id]
        shared_group = int(a.group_ids[0] if a.group_ids else b.group_ids[0])
        room_id = next(iter(inst.rooms.keys()))
        week = int(a.week)

        # Current schedule is non-conflicting baseline.
        current = {
            a_id: {
                "week": week,
                "day": "MON",
                "slot": 0,
                "duration": int(a.duration),
                "room_id": int(room_id),
                "staff_id": int(a.prof_id if a.kind == "LEC" else a.ta_id),
                "course_id": int(a.course_id),
                "group_ids": list(a.group_ids),
                "kind": str(a.kind),
            },
            b_id: {
                "week": week,
                "day": "TUE",
                "slot": 2,
                "duration": int(b.duration),
                "room_id": int(room_id),
                "staff_id": int(b.prof_id if b.kind == "LEC" else b.ta_id),
                "course_id": int(b.course_id),
                "group_ids": list(b.group_ids),
                "kind": str(b.kind),
            },
        }
        # Base has an intentional overlap conflict.
        base = {
            a_id: {
                "week": week,
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
                "week": week,
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
        win.current_schedule = {k: v.copy() for k, v in current.items()}
        win.base_schedule = {k: v.copy() for k, v in base.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        warned = {"called": False}

        def fake_warning(*args, **kwargs):
            warned["called"] = True

        monkeypatch.setattr(ui_window.QMessageBox, "warning", fake_warning)
        win.on_revert_to_base()
        assert warned["called"] is True
        assert win.current_schedule == current
    finally:
        win.close()
        win.deleteLater()


def test_sandbox_apply_blocked_when_conflicts_exist(monkeypatch, qt_app):
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
        week = int(a.week)
        shared_group = int(a.group_ids[0] if a.group_ids else b.group_ids[0])

        valid = {
            a_id: {
                "week": week,
                "day": "MON",
                "slot": 0,
                "duration": int(a.duration),
                "room_id": int(room_id),
                "staff_id": int(a.prof_id if a.kind == "LEC" else a.ta_id),
                "course_id": int(a.course_id),
                "group_ids": list(a.group_ids),
                "kind": str(a.kind),
            },
            b_id: {
                "week": week,
                "day": "TUE",
                "slot": 2,
                "duration": int(b.duration),
                "room_id": int(room_id),
                "staff_id": int(b.prof_id if b.kind == "LEC" else b.ta_id),
                "course_id": int(b.course_id),
                "group_ids": list(b.group_ids),
                "kind": str(b.kind),
            },
        }
        win.current_schedule = {k: v.copy() for k, v in valid.items()}
        win.base_schedule = {k: v.copy() for k, v in valid.items()}
        win.on_sandbox_start()

        # Introduce overlap conflict in sandbox state.
        win.current_schedule[b_id]["day"] = "MON"
        win.current_schedule[b_id]["slot"] = 0
        win.current_schedule[b_id]["group_ids"] = [shared_group]

        warned = {"called": False}

        def fake_warning(*args, **kwargs):
            warned["called"] = True

        monkeypatch.setattr(ui_window.QMessageBox, "warning", fake_warning)
        win.on_sandbox_apply()
        assert warned["called"] is True
        # Base should remain the original valid one.
        assert win.base_schedule == valid
    finally:
        win.close()
        win.deleteLater()


def test_history_snapshot_save_and_load(monkeypatch, tmp_path, qt_app):
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

        snapshot_path = tmp_path / "history_snapshot.json"
        monkeypatch.setattr(
            ui_window.QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: (str(snapshot_path), "JSON files (*.json)"),
        )
        win.on_save_history_snapshot()
        assert snapshot_path.exists()

        moved = {k: v.copy() for k, v in win.current_schedule.items()}
        moved[a_id]["slot"] = 1
        win._commit_schedule(moved, "changed")
        assert int(win.current_schedule[a_id]["slot"]) == 1

        win._load_history_snapshot_path(str(snapshot_path))
        assert int(win.current_schedule[a_id]["slot"]) == 0
    finally:
        win.close()
        win.deleteLater()


def test_apply_constraint_template_updates_once(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, schedule = _single_activity_schedule(inst)
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()
        win._load_templates()

        idx = win.constraint_template_combo.findData("Balanced")
        if idx >= 0:
            win.constraint_template_combo.setCurrentIndex(idx)

        calls = {"table": 0}
        orig_update_table = win.update_table

        def counted_update_table():
            calls["table"] += 1
            return orig_update_table()

        monkeypatch.setattr(win, "update_table", counted_update_table)
        win.on_apply_constraint_template()
        assert int(calls["table"]) <= 1
    finally:
        win.close()
        win.deleteLater()


def test_conflict_inspector_jump_selects_activity(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, b_id, _c_id, schedule = _conflicting_schedule_with_extra(inst)
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        captured = {}

        class _FakeConflictDialog:
            def __init__(self, _parent, errors):
                captured["errors"] = list(errors)

            def exec(self):
                return ui_window.QDialog.DialogCode.Accepted

            def solve_conflicts_requested(self):
                return False

            def selected_activity_id(self):
                return int(b_id)

        monkeypatch.setattr(ui_window, "ConflictInspectorDialog", _FakeConflictDialog)
        win.on_show_conflicts()

        assert win.selected_activity_id == int(b_id)
        assert win.held_activity_id is None
        assert win.selected_cell_row == int(inst.days.index("MON"))
        assert win.selected_cell_col == 0
        assert win.view_type_combo.currentText() == "All"
        errors = captured.get("errors", [])
        assert errors
        assert any("slot S1" in str(line) for line in errors)
        assert any("groups=" in str(line) for line in errors)
        assert any("room=" in str(line) for line in errors)
        assert any("staff=" in str(line) for line in errors)
    finally:
        win.close()
        win.deleteLater()


def test_conflict_inspector_solve_conflicts_starts_repair(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, b_id, c_id, schedule = _conflicting_schedule_with_extra(inst)
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.locked_activities = {int(a_id): {"day": "MON", "slot": 0}}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        prior_locks = {
            int(k): dict(v) for k, v in win.locked_activities.items()
        }
        called = {}

        def _fake_start_solver(*, keep_locks: bool):
            called["keep_locks"] = bool(keep_locks)

        class _FakeConflictDialog:
            def __init__(self, _parent, _errors):
                pass

            def exec(self):
                return ui_window.QDialog.DialogCode.Accepted

            def solve_conflicts_requested(self):
                return True

            def selected_activity_id(self):
                return None

        monkeypatch.setattr(ui_window, "ConflictInspectorDialog", _FakeConflictDialog)
        monkeypatch.setattr(win, "_start_solver_process", _fake_start_solver)
        win.on_show_conflicts()

        assert called.get("keep_locks") is True
        assert win._restore_locks_after_solve == prior_locks
        assert int(c_id) in win.locked_activities
        assert int(a_id) not in win.locked_activities or int(b_id) not in win.locked_activities
    finally:
        win.close()
        win.deleteLater()


def test_improve_blocked_when_hard_conflicts_exist(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        _a_id, _b_id, _c_id, schedule = _conflicting_schedule_with_extra(inst)
        win.current_schedule = {k: v.copy() for k, v in schedule.items()}
        win.base_schedule = {k: v.copy() for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()

        warned = {"called": False}

        def _fake_warning(*args, **kwargs):
            warned["called"] = True

        monkeypatch.setattr(ui_window.QMessageBox, "warning", _fake_warning)
        win.on_improve()
        assert warned["called"] is True
        assert "Improve blocked" in str(win._status_full_text)
    finally:
        win.close()
        win.deleteLater()


def test_solver_access_violation_retries_once_in_safe_mode(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        win.proc = None
        win._solver_output_log = "native crash"
        win._last_solver_keep_locks = True
        win._solver_safe_retry_used = False
        win.tmp_inst_path = None
        win.tmp_res_path = None

        called = {}

        def _fake_start_solver_process(*, keep_locks: bool, retry_safe: bool = False):
            called["keep_locks"] = bool(keep_locks)
            called["retry_safe"] = bool(retry_safe)

        monkeypatch.setattr(win, "_start_solver_process", _fake_start_solver_process)
        monkeypatch.setattr(ui_window.sys, "frozen", True, raising=False)
        monkeypatch.setattr(ui_window.QMessageBox, "critical", lambda *args, **kwargs: None)

        win.on_solver_finished(-1073741819, None)
        assert called.get("keep_locks") is True
        assert called.get("retry_safe") is True
        assert win._solver_safe_retry_used is True
    finally:
        win.close()
        win.deleteLater()


def test_solver_error_crash_retries_once_in_safe_mode(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        class _Buf:
            def __init__(self, payload: bytes):
                self._payload = payload

            def data(self):
                return self._payload

        class _DummyProc:
            def __init__(self):
                self.deleted = False

            def readAll(self):
                return _Buf(b"native crash")

            def deleteLater(self):
                self.deleted = True

        proc = _DummyProc()
        win.proc = proc
        win._solver_output_log = ""
        win._last_solver_keep_locks = True
        win._solver_safe_retry_used = False
        win.tmp_inst_path = None
        win.tmp_res_path = None

        called = {}

        def _fake_start_solver_process(*, keep_locks: bool, retry_safe: bool = False):
            called["keep_locks"] = bool(keep_locks)
            called["retry_safe"] = bool(retry_safe)

        monkeypatch.setattr(win, "_start_solver_process", _fake_start_solver_process)
        monkeypatch.setattr(ui_window.sys, "frozen", True, raising=False)
        monkeypatch.setattr(ui_window.QMessageBox, "critical", lambda *args, **kwargs: None)

        win.on_solver_error(ui_window.QProcess.ProcessError.Crashed)
        assert called.get("keep_locks") is True
        assert called.get("retry_safe") is True
        assert win._solver_safe_retry_used is True
        assert proc.deleted is True
    finally:
        win.close()
        win.deleteLater()
