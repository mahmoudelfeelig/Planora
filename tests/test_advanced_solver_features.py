from __future__ import annotations

from typing import Dict

from ortools.sat.python import cp_model

from services import solver_service
from services.contracts import SolveAttempt, SolveOptions, SolveResult
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.specs import validate_schedule_against_instance


def _build_instance() -> Instance:
    programs = {1: Program(id=1, name="P1", course_ids=[1, 2], group_ids=[1])}
    groups = {1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1, 2])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course-1",
            structure_type="LEC_ONLY",
            lecture_count=1,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1],
            prof_id=1,
            ta_id=2,
        ),
        2: Course(
            id=2,
            code="C2",
            name="Course-2",
            structure_type="LEC_ONLY",
            lecture_count=1,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1],
            prof_id=1,
            ta_id=2,
        ),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
        ),
    }
    rooms = {
        1: Room(
            id=1,
            name="L1",
            capacity=100,
            room_type="LECTURE",
            campus="MAIN",
            building="A",
        ),
        2: Room(
            id=2,
            name="L2",
            capacity=100,
            room_type="LECTURE",
            campus="SATELLITE",
            building="B",
        ),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
        ),
    }
    return Instance(
        days=["MON", "TUE"],
        slots_per_day=3,
        weeks=[1],
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        hard_constraints={
            "week1_lectures_only": False,
            "enforce_precedence_rules": True,
            "enforce_travel_time_buffers": True,
            "enforce_building_closures": True,
            "enforce_calendar_rules": True,
        },
    )


def _schedule(slot_a: int, slot_b: int, *, room_a: int = 1, room_b: int = 2) -> Dict[int, Dict[str, object]]:
    return {
        1: {
            "week": 1,
            "day": "MON",
            "slot": int(slot_a),
            "duration": 1,
            "room_id": int(room_a),
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        },
        2: {
            "week": 1,
            "day": "MON",
            "slot": int(slot_b),
            "duration": 1,
            "room_id": int(room_b),
            "staff_id": 1,
            "course_id": 2,
            "group_ids": [1],
            "kind": "LEC",
        },
    }


def test_calendar_and_building_closure_rules_validate_and_toggle():
    inst = _build_instance()
    inst.calendar_rules = {"blackout_weeks": [1]}
    inst.room_closures = [{"building": "A", "week": 1, "day": "MON", "slot": 0}]
    sched = _schedule(0, 2, room_a=1, room_b=1)

    errors = validate_schedule_against_instance(inst, sched, strict_rooms=True)
    assert any("blocked calendar" in err for err in errors)
    assert any("room 1 unavailable" in err for err in errors)

    inst.hard_constraints["enforce_calendar_rules"] = False
    inst.hard_constraints["enforce_building_closures"] = False
    relaxed_errors = validate_schedule_against_instance(inst, sched, strict_rooms=True)
    assert not any("blocked calendar" in err for err in relaxed_errors)
    assert not any("unavailable room" in err for err in relaxed_errors)


def test_precedence_and_travel_buffer_rules_validate_and_toggle():
    inst = _build_instance()
    inst.precedence_rules = [{"before_activity_id": 1, "after_activity_id": 2, "min_gap_slots": 1}]
    inst.travel_time_rules = {"cross_campus": 2, "cross_building": 1, "same_building": 0}
    sched = _schedule(1, 0, room_a=1, room_b=2)

    errors = validate_schedule_against_instance(inst, sched, strict_rooms=True)
    assert any("precedence" in err for err in errors)
    assert any("travel buffer" in err for err in errors)

    inst.hard_constraints["enforce_precedence_rules"] = False
    inst.hard_constraints["enforce_travel_time_buffers"] = False
    relaxed_errors = validate_schedule_against_instance(inst, sched, strict_rooms=True)
    assert not any("precedence" in err for err in relaxed_errors)
    assert not any("travel buffer" in err for err in relaxed_errors)


def test_incremental_resolve_freezes_only_unaffected_scope(monkeypatch):
    inst = _build_instance()
    inst.groups[2] = Group(id=2, name="G2", program_id=1, size=25, course_ids=[2])
    inst.staff[3] = StaffMember(
        id=3,
        name="Prof-2",
        is_prof=True,
        available_days={"MON", "TUE"},
        max_slots_per_day=None,
        max_slots_per_week=None,
        can_teach_courses={2},
    )
    inst.activities[2] = Activity(
        id=2,
        course_id=2,
        week=1,
        kind="LEC",
        duration=1,
        group_ids=[2],
        prof_id=3,
        ta_id=2,
    )
    base_schedule = _schedule(0, 2, room_a=1, room_b=2)
    base_schedule[2]["group_ids"] = [2]
    base_schedule[2]["staff_id"] = 3
    seen: dict[str, object] = {}

    class FakeModel:
        def extract_solution(self, solver):
            return {a_id: dict(info) for a_id, info in base_schedule.items()}

    def fake_run(inst_arg, *, room_mode, use_objective, options):
        seen["locks"] = dict(getattr(inst_arg, "locked_activities", {}) or {})
        return (
            FakeModel(),
            object(),
            int(cp_model.FEASIBLE),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=bool(use_objective),
                time_limit_seconds=options.time_limit_seconds,
                raw_status=int(cp_model.FEASIBLE),
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fake_run)
    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            time_limit_seconds=5.0,
            workers=1,
            base_schedule=base_schedule,
            affected_activity_ids=[1],
            freeze_unaffected=True,
        ),
    )

    locks = seen.get("locks", {})
    assert isinstance(locks, dict)
    assert 2 in locks
    assert 1 not in locks
    assert result.meta.get("incremental", {}).get("enabled") is True


def test_objective_profiles_adjust_solve_behavior(monkeypatch):
    inst = _build_instance()
    base_schedule = _schedule(0, 2, room_a=1, room_b=1)
    attempts: list[tuple[str, bool, float | None]] = []
    improve_calls: list[tuple[int, float | None]] = []

    class FakeModel:
        def extract_solution(self, solver):
            return {a_id: dict(info) for a_id, info in base_schedule.items()}

    class FakeImprover:
        def __init__(self, inst):
            pass

        def compute_soft_penalty(self, schedule):
            return 10 if int(schedule[2]["slot"]) == 2 else 5

        def improve(self, schedule, *, iterations=0, max_seconds=None, **kwargs):
            improve_calls.append((int(iterations), max_seconds))
            out = {a_id: dict(info) for a_id, info in schedule.items()}
            out[2]["slot"] = 1
            return out

    def fake_run(inst_arg, *, room_mode, use_objective, options):
        attempts.append((str(room_mode), bool(use_objective), options.time_limit_seconds))
        return (
            FakeModel(),
            object(),
            int(cp_model.FEASIBLE),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=bool(use_objective),
                time_limit_seconds=options.time_limit_seconds,
                raw_status=int(cp_model.FEASIBLE),
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fake_run)
    monkeypatch.setattr(solver_service, "LocalSearchImprover", FakeImprover)

    fast = solver_service.solve_instance(
        inst,
        SolveOptions(
            room_mode="cp_rooms",
            use_objective=True,
            time_limit_seconds=60.0,
            objective_profile="fast feasible",
        ),
    )
    assert fast.meta.get("objective_profile", {}).get("id") == "fast_feasible"
    assert attempts[0][1] is False

    attempts.clear()
    quality = solver_service.solve_instance(
        inst,
        SolveOptions(
            room_mode="cp_rooms",
            use_objective=True,
            time_limit_seconds=90.0,
            objective_profile="quality-first",
        ),
    )
    assert quality.meta.get("objective_profile", {}).get("id") == "quality_first"
    assert attempts[0][1] is False  # phased feasibility-first
    assert quality.meta.get("improvement", {}).get("enabled") is True
    assert improve_calls


def test_portfolio_solve_ranks_candidates_and_explains():
    inst = _build_instance()
    original = solver_service.solve_instance

    def fake_solve(_inst, options, *, progress_hook=None):
        profile = str(options.objective_profile)
        penalties = {
            "fast_feasible": 22,
            "balanced": 14,
            "quality_first": 9,
        }
        schedule = _schedule(0, 2 if profile != "quality_first" else 1, room_a=1, room_b=1)
        return SolveResult(
            status=0,
            raw_status=int(cp_model.FEASIBLE),
            schedule=schedule,
            attempts=[],
            meta={
                "quality": {
                    "soft_penalty": penalties[profile],
                    "breakdown": {"total": penalties[profile]},
                }
            },
        )

    solver_service.solve_instance = fake_solve
    try:
        portfolio = solver_service.solve_portfolio(
            inst,
            SolveOptions(room_mode="cp_rooms", use_objective=True, time_limit_seconds=30.0),
        )
    finally:
        solver_service.solve_instance = original

    assert portfolio.best_index == 2
    assert portfolio.best is not None
    assert portfolio.best.name == "quality_first"
    assert "ranked first" in str(portfolio.best.rank_explanation).lower()
    assert "total" in str(portfolio.candidates[1].rank_explanation).lower()


def test_quality_meta_includes_breakdown_and_sla(monkeypatch):
    inst = _build_instance()
    inst.sla_targets = {"max_soft_penalty": 8, "max_hard_conflicts": 0}
    schedule = _schedule(0, 2, room_a=1, room_b=1)

    class FakeModel:
        def extract_solution(self, solver):
            return {a_id: dict(info) for a_id, info in schedule.items()}

    def fake_run(inst_arg, *, room_mode, use_objective, options):
        return (
            FakeModel(),
            object(),
            int(cp_model.FEASIBLE),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=bool(use_objective),
                time_limit_seconds=options.time_limit_seconds,
                raw_status=int(cp_model.FEASIBLE),
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fake_run)
    result = solver_service.solve_instance(
        inst,
        SolveOptions(room_mode="greedy", use_objective=False, retry_without_objective=False),
    )

    quality = result.meta.get("quality", {})
    assert int(quality.get("soft_penalty", 0)) >= 0
    assert "breakdown" in quality
    assert "sla" in quality
    assert quality["sla"]["passed"] is False
