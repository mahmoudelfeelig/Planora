from __future__ import annotations

import os
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from core.solver_cp_sat import TimetableSolver
from services import solver_service
from services.contracts import SolveOptions
from services.institution_template_service import (
    load_institution_template,
    save_institution_template,
)
from ui import window as ui_window
from ui.backend_client import LocalBackendClient
from ui.dialogs import ImportScheduleWizardDialog
from utils.domain import Activity, Course, GenericResource, Group, Instance, Program, Room, StaffMember
from utils.generator import generate_custom_instance
from utils.specs import validate_schedule_against_instance

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QTableView  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_custom_generation_supports_term_blocks_and_room_floors():
    inst = generate_custom_instance(
        num_programs=1,
        groups_per_program=1,
        courses_per_program=2,
        num_professors=1,
        num_tas=1,
        term_blocks=[
            {"label": "Teaching A", "length_weeks": 4, "teaching": True},
            {"label": "Exams", "length_weeks": 2, "teaching": False},
            {"label": "Teaching B", "length_weeks": 3, "teaching": True},
        ],
        room_specs=[
            {
                "name": "Lecture-1",
                "room_type": "LECTURE",
                "capacity": 120,
                "campus": "MAIN",
                "building": "ENG",
                "floor": "3",
            },
            {
                "name": "Tutorial-1",
                "room_type": "TUTORIAL",
                "capacity": 60,
                "campus": "MAIN",
                "building": "ENG",
                "floor": "2",
            },
        ],
        calendar_days=["MON", "TUE", "WED", "THU", "FRI"],
        slots_per_day=4,
        seed=7,
    )

    assert inst.weeks == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert len(inst.term_blocks) == 3
    assert inst.term_blocks[1]["teaching"] is False
    assert inst.rooms[1].floor == "3"


def test_generic_resources_validate_and_solver_respects_capacity():
    inst = Instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        programs={1: Program(id=1, name="P1", course_ids=[1, 2], group_ids=[1, 2])},
        groups={
            1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1]),
            2: Group(id=2, name="G2", program_id=1, size=20, course_ids=[2]),
        },
        courses={
            1: Course(id=1, code="C1", name="Course 1", structure_type="LEC_ONLY", lecture_count=1, tutorial_count=0, lab_weeks=0, lab_duration=0, share_lecture_group_ids=[], prof_id=1, ta_id=2),
            2: Course(id=2, code="C2", name="Course 2", structure_type="LEC_ONLY", lecture_count=1, tutorial_count=0, lab_weeks=0, lab_duration=0, share_lecture_group_ids=[], prof_id=1, ta_id=2),
        },
        staff={
            1: StaffMember(id=1, name="Prof-1", is_prof=True, available_days={"MON"}, max_slots_per_day=None, max_slots_per_week=None, can_teach_courses={1, 2}),
            2: StaffMember(id=2, name="TA-1", is_prof=False, available_days={"MON"}, max_slots_per_day=None, max_slots_per_week=None, can_teach_courses={1, 2}),
        },
        rooms={
            1: Room(id=1, name="L1", capacity=80, room_type="LECTURE"),
            2: Room(id=2, name="L2", capacity=80, room_type="LECTURE"),
        },
        activities={
            1: Activity(id=1, course_id=1, week=1, kind="LEC", duration=1, group_ids=[1], prof_id=1, ta_id=2, resource_ids=[1]),
            2: Activity(id=2, course_id=2, week=1, kind="LEC", duration=1, group_ids=[2], prof_id=1, ta_id=2, resource_ids=[1]),
        },
        generic_resources={
            1: GenericResource(id=1, name="Projector Rig", resource_type="EQUIPMENT", capacity=1),
        },
        hard_constraints={"week1_lectures_only": False},
    )

    bad_schedule = {
        1: {"week": 1, "day": "MON", "slot": 0, "duration": 1, "room_id": 1, "staff_id": 1, "course_id": 1, "group_ids": [1], "kind": "LEC"},
        2: {"week": 1, "day": "MON", "slot": 0, "duration": 1, "room_id": 2, "staff_id": 1, "course_id": 2, "group_ids": [2], "kind": "LEC"},
    }
    errors = validate_schedule_against_instance(inst, bad_schedule, strict_rooms=True)
    assert any("Generic resource overlap" in err for err in errors)

    solver = TimetableSolver(inst, room_mode="greedy", use_objective=False)
    sat_solver, status = solver.solve(workers=1, time_limit_seconds=10.0)
    assert int(status) in (int(cp_model.FEASIBLE), int(cp_model.OPTIMAL))
    schedule = solver.extract_solution(sat_solver)
    assert int(schedule[1]["slot"]) != int(schedule[2]["slot"])


def test_institution_template_roundtrip(tmp_path: Path):
    payload = {
        "name": "Engineering Faculty",
        "objective_profile": "quality_first",
        "constraints": {"hard": {"week1_lectures_only": True}, "soft": {"stud_gaps": 9}},
        "generator_defaults": {"calendar_days": ["MON", "TUE", "WED"]},
        "import_defaults": {"mapping": {"activity_id": "Activity ID"}, "group_separator": "|"},
    }
    path = tmp_path / "institution_template.json"
    save_institution_template(path, payload)
    restored = load_institution_template(path)
    assert restored["name"] == "Engineering Faculty"
    assert restored["objective_profile"] == "quality_first"
    assert restored["import_defaults"]["group_separator"] == "|"


def test_local_backend_client_uses_portfolio_service(monkeypatch):
    called = {}

    def fake_portfolio(inst, options):
        called["profile"] = str(options.objective_profile)
        return "ok"

    monkeypatch.setattr("ui.backend_client.solve_portfolio", fake_portfolio)
    client = LocalBackendClient()
    result = client.solve_portfolio(object(), SolveOptions(objective_profile="balanced"))
    assert result == "ok"
    assert called["profile"] == "balanced"


def test_search_bar_and_virtualized_fairness_views(qt_app):
    win = ui_window.MainWindow()
    try:
        assert isinstance(win.fairness_group_table, QTableView)
        assert isinstance(win.fairness_staff_table, QTableView)
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        win.search_scope_combo.setCurrentText("Activities")
        win.search_edit.setText("A1")
        rows = win._search_result_rows("Activities", "A1")
        assert rows
    finally:
        win.close()
        win.deleteLater()


def test_import_wizard_uses_default_mapping(qt_app):
    dlg = ImportScheduleWizardDialog(
        None,
        ["Activity ID", "Week", "Day", "Slot", "Duration", "Course ID", "Kind"],
        [{"Activity ID": "1", "Week": "1"}],
        default_mapping={"activity_id": "Activity ID", "week": "Week"},
        default_group_separator="|",
    )
    try:
        assert dlg.selected_mapping()["activity_id"] == "Activity ID"
        assert dlg.selected_mapping()["week"] == "Week"
        assert dlg.group_separator() == "|"
    finally:
        dlg.close()
        dlg.deleteLater()


def test_command_palette_actions_registered(qt_app):
    win = ui_window.MainWindow()
    try:
        shortcuts = {action.shortcut().toString() for action in win._command_actions}
        assert "Ctrl+Shift+P" in shortcuts
        assert "Ctrl+F" in shortcuts
    finally:
        win.close()
        win.deleteLater()


def test_drag_drop_helpers_move_activity(qt_app):
    win = ui_window.MainWindow()
    try:
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        # Build a trivial one-activity schedule.
        lecture_pair = next(
            (item for item in win.inst.activities.items() if item[1].kind == "LEC"),
            next(iter(win.inst.activities.items())),
        )
        a_id, act = lecture_pair
        room_id = next(
            (
                int(r_id)
                for r_id, room in win.inst.rooms.items()
                if room.room_type == "LECTURE"
            ),
            int(next(iter(win.inst.rooms.keys()))),
        )
        win.current_schedule = {
            int(a_id): {
                "week": int(act.week),
                "day": win.inst.days[0],
                "slot": 0,
                "duration": int(act.duration),
                "room_id": int(room_id),
                "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                "course_id": int(act.course_id),
                "group_ids": list(act.group_ids),
                "kind": str(act.kind),
            }
        }
        win.base_schedule = {k: dict(v) for k, v in win.current_schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()
        win._on_schedule_drag_requested(0, 0)
        win._on_schedule_drop_requested(0, 1)
        assert int(win.current_schedule[int(a_id)]["slot"]) == 1
    finally:
        win.close()
        win.deleteLater()


def test_non_blocking_edit_analysis_requests_background_work(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        win.mode_combo.setCurrentText("small_demo")
        win.on_generate()
        a_id, act = next(iter(win.inst.activities.items()))
        room_id = next(iter(win.inst.rooms.keys()))
        win.current_schedule = {
            int(a_id): {
                "week": int(act.week),
                "day": win.inst.days[0],
                "slot": 0,
                "duration": int(act.duration),
                "room_id": int(room_id),
                "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                "course_id": int(act.course_id),
                "group_ids": list(act.group_ids),
                "kind": str(act.kind),
            }
        }
        win.base_schedule = {k: dict(v) for k, v in win.current_schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win._set_held_activity(int(a_id))
        monkeypatch.setattr(win._thread_pool, "start", lambda worker: None)
        win.update_table()
        assert win._held_analysis_async_key is not None
    finally:
        win.close()
        win.deleteLater()


def test_term_blocks_appear_in_week_labels(qt_app):
    win = ui_window.MainWindow()
    try:
        win.mode_combo.setCurrentText("custom")
        win._apply_custom_generation_config(
            {
                "num_programs": 1,
                "groups_per_program": 1,
                "courses_per_program": 2,
                "num_professors": 1,
                "num_tas": 1,
                "calendar_days": ["MON", "TUE", "WED"],
                "term_blocks": [
                    {"label": "Block A", "length_weeks": 3, "teaching": True},
                    {"label": "Exams", "length_weeks": 2, "teaching": False},
                ],
            }
        )
        win.on_generate()
        labels = [win.week_combo.itemText(i) for i in range(win.week_combo.count())]
        assert any("Block A" in label for label in labels)
        assert any("Exams" in label for label in labels)
    finally:
        win.close()
        win.deleteLater()
