from __future__ import annotations

from ortools.sat.python import cp_model

from core.solver_cp_sat import TimetableSolver
from services.contracts import SolveOptions
from services.solver_service import solve_instance
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


def _repeat_instance() -> Instance:
    programs = {1: Program(id=1, name="P1", course_ids=[1], group_ids=[1])}
    groups = {1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_ONLY",
            lecture_count=3,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[],
            prof_id=1,
            ta_id=2,
        )
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
        ),
        2: StaffMember(
            id=2,
            name="TA",
            is_prof=False,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
        ),
    }
    rooms = {
        1: Room(id=1, name="R1", capacity=40, room_type="LECTURE"),
        2: Room(id=2, name="R2", capacity=40, room_type="LECTURE"),
    }
    activities = {
        week: Activity(
            id=week,
            course_id=1,
            week=week,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
        )
        for week in (1, 2, 3)
    }
    return Instance(
        days=["MON", "TUE"],
        slots_per_day=2,
        weeks=[1, 2, 3],
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        hard_constraints={
            "week1_lectures_only": True,
            "force_repeat_weekly_pattern": True,
        },
    )


def test_repeat_week_pattern_ties_time_and_room_after_first_week():
    inst = _repeat_instance()
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)
    solver, status = model.solve(time_limit_seconds=5, workers=1, random_seed=7)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert schedule[2]["day"] == schedule[3]["day"]
    assert schedule[2]["slot"] == schedule[3]["slot"]
    assert schedule[2]["room_id"] == schedule[3]["room_id"]


def test_repeat_week_greedy_request_reports_exact_mode_promotion_within_budget():
    inst = _repeat_instance()

    result = solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            time_limit_seconds=5.0,
            workers=1,
            random_seed=7,
        ),
    )

    assert result.is_feasible is True
    assert result.attempts[0].room_mode == "decomposed"
    resolution = result.meta["decomposition"]["room_mode_resolution"]
    assert resolution == {
        "requested": "greedy",
        "effective": "decomposed",
        "promoted": True,
        "reason": "force_repeat_weekly_pattern_requires_joint_time_room_search",
    }
    assert result.meta["timing"]["deadline_overrun_seconds"] == 0.0
    assert result.schedule[2]["day"] == result.schedule[3]["day"]
    assert result.schedule[2]["slot"] == result.schedule[3]["slot"]
    assert result.schedule[2]["room_id"] == result.schedule[3]["room_id"]


def test_repeat_week_pattern_solves_small_demo_with_one_off_clusters():
    inst = generate_instance("small_demo")
    inst.hard_constraints = dict(getattr(inst, "hard_constraints", {}) or {})
    inst.hard_constraints["force_repeat_weekly_pattern"] = True

    model = TimetableSolver(inst, room_mode="greedy", use_objective=False)
    assert model.requested_room_mode == "greedy"
    assert model.room_mode == "decomposed"
    assert model.room_mode_resolution == {
        "requested": "greedy",
        "effective": "decomposed",
        "promoted": True,
        "reason": "force_repeat_weekly_pattern_requires_joint_time_room_search",
    }
    solver, status = model.solve(time_limit_seconds=20, workers=1, random_seed=7)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert len(schedule) == len(inst.activities)
    report = model.decomposition_report
    assert report["room_mode_resolution"] == model.room_mode_resolution
    assert report["budget_seconds"] == 20.0
    assert report["deadline_overrun_seconds"] == 0.0
    assert validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    repeat_pairs = model._repeat_week_pattern_pairs()
    assert repeat_pairs
    for leader, follower in repeat_pairs:
        assert schedule[leader]["day"] == schedule[follower]["day"]
        assert schedule[leader]["slot"] == schedule[follower]["slot"]
        assert schedule[leader]["room_id"] == schedule[follower]["room_id"]
