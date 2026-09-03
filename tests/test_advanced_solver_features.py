from __future__ import annotations

import time
from typing import Dict

from ortools.sat.python import cp_model

from core.solver_cp_sat import TimetableSolver
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


def test_cp_sat_accepts_partial_incumbent_hints_without_changing_correctness():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    report = model.add_solution_hint(
        {1: incumbent[1], 999: {"day": "MON", "slot": 0}}
    )
    solver, status = model.solve(time_limit_seconds=5.0, workers=1, random_seed=11)

    assert report["start_hints"] == 1
    assert 999 in report["skipped_activity_ids"]
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(inst, schedule, strict_rooms=True) == []


def test_locked_rooms_compile_to_singleton_domains_for_exact_repairs():
    inst = _build_instance()
    inst.locked_activities = {1: {"day": "MON", "slot": 0, "room_id": 1}}

    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    assert model.allowed_starts[1] == [0]
    assert model.allowed_rooms[1] == [1]
    assert len([key for key in model.room_sel if key[0] == 1]) == 1


def test_reusable_assumption_neighborhood_changes_without_rebuilding_model():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)
    initial_variables = len(model.m.Proto().variables)
    initial_constraints = len(model.m.Proto().constraints)
    initial_objective = str(model.m.Proto().objective)

    first = model.set_neighborhood_assumptions(
        incumbent,
        unlocked_activity_ids={1},
    )
    solver, status = model.solve(time_limit_seconds=2.0, workers=1, random_seed=3)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    assert first["fixed_activities"] == 1
    assert validate_schedule_against_instance(
        inst, model.extract_solution(solver), strict_rooms=True
    ) == []

    second = model.set_neighborhood_assumptions(
        incumbent,
        unlocked_activity_ids={2},
    )
    second_solver, second_status = model.solve(
        time_limit_seconds=2.0,
        workers=1,
        random_seed=4,
    )
    assert int(second_status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    assert second["fixed_activities"] == 1
    assert len(model.m.Proto().variables) == initial_variables
    assert len(model.m.Proto().constraints) == initial_constraints
    assert str(model.m.Proto().objective) == initial_objective
    assert validate_schedule_against_instance(
        inst, model.extract_solution(second_solver), strict_rooms=True
    ) == []


def test_assumption_core_is_only_read_for_an_infeasibility_proof():
    inst = _build_instance()
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    class UnknownSolver:
        def SufficientAssumptionsForInfeasibility(self):
            raise AssertionError("UNKNOWN has no valid infeasibility core")

    assert model.assumption_core_activity_ids(
        UnknownSolver(),
        raw_status=int(cp_model.UNKNOWN),
    ) == []


def test_reusable_assumptions_require_a_complete_incumbent():
    inst = _build_instance()
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    try:
        model.set_neighborhood_assumptions(
            {1: _schedule(0, 2, room_a=1, room_b=1)[1]},
            unlocked_activity_ids={1},
        )
    except ValueError as exc:
        assert "complete incumbent" in str(exc).lower()
    else:
        raise AssertionError("A partial incumbent must not silently unlock activities")


def test_solve_attempt_budget_includes_model_build_and_setup(monkeypatch):
    observed: dict[str, float] = {}

    class FakeModel:
        decomposition_report = {}

        def add_solution_hint(self, schedule, *, include_rooms=True):
            del schedule, include_rooms
            time.sleep(0.01)

        def solve(self, *, time_limit_seconds, **_kwargs):
            observed["search_budget"] = float(time_limit_seconds)
            return cp_model.CpSolver(), int(cp_model.UNKNOWN)

    def delayed_build(*_args, **_kwargs):
        time.sleep(0.03)
        return FakeModel()

    monkeypatch.setattr(solver_service, "build_timetable_solver", delayed_build)
    _, _, status, attempt = solver_service._run_solve_attempt(
        _build_instance(),
        room_mode="greedy",
        use_objective=False,
        options=SolveOptions(
            room_mode="greedy",
            use_objective=False,
            time_limit_seconds=0.10,
            base_schedule=_schedule(0, 2, room_a=1, room_b=1),
        ),
    )

    assert int(status) == int(cp_model.UNKNOWN)
    assert 0.0 < observed["search_budget"] < 0.075
    assert attempt.model_build_seconds >= 0.025
    assert attempt.setup_seconds >= 0.008
    assert attempt.search_budget_seconds == observed["search_budget"]
    assert attempt.elapsed_seconds >= attempt.model_build_seconds + attempt.setup_seconds


def test_solve_attempt_skips_search_when_build_exhausts_budget(monkeypatch):
    class FakeModel:
        decomposition_report = {}

        def solve(self, **_kwargs):
            raise AssertionError("Search must not start after the total deadline")

    def delayed_build(*_args, **_kwargs):
        time.sleep(0.025)
        return FakeModel()

    monkeypatch.setattr(solver_service, "build_timetable_solver", delayed_build)
    _, _, status, attempt = solver_service._run_solve_attempt(
        _build_instance(),
        room_mode="greedy",
        use_objective=False,
        options=SolveOptions(
            room_mode="greedy",
            use_objective=False,
            time_limit_seconds=0.005,
        ),
    )

    assert int(status) == int(cp_model.UNKNOWN)
    assert attempt.budget_exhausted is True
    assert attempt.search_seconds == 0.0
    assert attempt.proof_status == "no_solution"


def test_research_profile_caps_incumbent_and_adaptive_stages_to_total_budget():
    _, resolved, meta = solver_service._apply_objective_profile(
        _build_instance(),
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=0.10,
            adaptive_lns_seconds=10.0,
        ),
    )

    assert meta["id"] == "research_adaptive"
    assert resolved.time_limit_seconds is not None
    assert resolved.time_limit_seconds >= 0.0
    assert resolved.adaptive_lns_seconds >= 0.0
    assert (
        float(resolved.time_limit_seconds) + float(resolved.adaptive_lns_seconds)
        <= 0.10
    )


def test_adaptive_budget_subtracts_room_dive_and_completion_reserves():
    assert solver_service._budget_after_reserves(8.0, 7.75, 0.50, 0.25) == 7.0


def test_solve_instance_does_not_rebuild_for_retry_after_total_deadline(monkeypatch):
    calls: list[str] = []

    class FakeModel:
        decomposition_report = {}

    def slow_unknown(inst_arg, *, room_mode, use_objective, options):
        del inst_arg, options
        calls.append(str(room_mode))
        time.sleep(0.06)
        return (
            FakeModel(),
            cp_model.CpSolver(),
            int(cp_model.UNKNOWN),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=bool(use_objective),
                time_limit_seconds=0.05,
                raw_status=int(cp_model.UNKNOWN),
                model_build_seconds=0.04,
                elapsed_seconds=0.06,
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", slow_unknown)
    result = solver_service.solve_instance(
        _build_instance(),
        SolveOptions(
            room_mode="cp_rooms",
            use_objective=True,
            retry_without_objective=True,
            objective_profile="balanced",
            time_limit_seconds=0.05,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.status == -1
    assert calls == ["cp_rooms"]
    assert result.meta["timing"]["budget_exhausted"] is True


def test_fairness_first_returns_valid_reserved_incumbent_when_optimization_times_out(
    monkeypatch,
):
    original_run_attempt = solver_service._run_solve_attempt
    observed_hint: Dict[int, Dict[str, object]] = {}

    class TimedOutFairnessModel:
        decomposition_report = {
            "status": "TIME_LIMIT",
            "proof_status": "no_solution",
        }

    def fairness_timeout(inst_arg, *, room_mode, use_objective, options):
        if not use_objective:
            return original_run_attempt(
                inst_arg,
                room_mode=room_mode,
                use_objective=use_objective,
                options=options,
            )
        observed_hint.update(
            {
                int(activity_id): dict(info)
                for activity_id, info in (options.base_schedule or {}).items()
            }
        )
        return (
            TimedOutFairnessModel(),
            cp_model.CpSolver(),
            int(cp_model.UNKNOWN),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=True,
                time_limit_seconds=options.time_limit_seconds,
                raw_status=int(cp_model.UNKNOWN),
                status_name=str(cp_model.CpSolverStatus(cp_model.UNKNOWN)),
                proof_status="no_solution",
                budget_seconds=options.time_limit_seconds,
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fairness_timeout)
    inst = _build_instance()
    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="fairness_first",
            time_limit_seconds=5.0,
            workers=1,
            random_seed=7,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.status == 0
    assert result.raw_status == int(cp_model.FEASIBLE)
    assert len(result.schedule) == len(inst.activities)
    assert validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert len(observed_hint) == len(inst.activities)
    assert [attempt.use_objective for attempt in result.attempts] == [False, True]
    fairness = result.meta["fairness_first"]
    assert fairness["bootstrap_budget_seconds"] == 2.0
    assert fairness["bootstrap_valid"] is True
    assert fairness["fairness_proof_status"] == "no_solution"
    assert fairness["fairness_optimization_complete"] is False
    assert fairness["returned_source"] == "feasibility_incumbent"
    assert fairness["status"] == "FEASIBILITY_INCUMBENT_FAIRNESS_INCOMPLETE"


def test_adaptive_repair_reports_reused_objective_and_neighborhood_proof():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    result_schedule, meta = solver_service._run_adaptive_lns(
        inst,
        incumbent,
        SolveOptions(
            workers=1,
            random_seed=5,
            adaptive_lns_seconds=0.5,
            adaptive_lns_slice_seconds=0.2,
            adaptive_lns_max_rounds=1,
            adaptive_lns_neighborhood_sizes=(1,),
            adaptive_lns_exact_activity_limit=10,
        ),
        fixed_time_room_dive_enabled=True,
        fixed_time_room_dive_budget_seconds=0.2,
        final_deadline=time.perf_counter() + 0.75,
    )

    assert len(result_schedule) == len(inst.activities)
    assert meta["reusable_model"]["objective_reused_across_rounds"] is True
    assert meta["reusable_model"]["objective_fingerprint"]
    assert len(meta["trace"]) == 1
    row = meta["trace"][0]
    assert row["proof_scope"] == "neighborhood"
    assert row["proof_status"] in {"optimal", "feasible_incumbent"}
    assert row["repair_metadata"]["model_structure_unchanged"] is True
    assert row["repair_metadata"]["objective_unchanged"] is True
    assert row["repair_metadata"]["search_budget_seconds"] < row[
        "slice_budget_seconds"
    ]
    room_dive = meta["fixed_time_room_dive"]
    assert room_dive["status"] == "REJECTED_NO_IMPROVEMENT"
    assert room_dive["validation"]["valid"] is True
    assert room_dive["deadline_overrun_seconds"] < 0.05


def test_non_itc_presets_retain_default_adaptive_neighborhood_sizes():
    inst = _build_instance()
    inst.hard_constraints["enable_itc2007_compact_adaptive_arms"] = True

    sizes, policy = solver_service._adaptive_lns_neighborhood_policy(
        inst,
        SolveOptions(),
        activity_count=100,
    )

    assert sizes == (12, 24, 48)
    assert policy["requested_sizes"] == [12, 24, 48]
    assert policy["configured_sizes"] == [12, 24, 48]
    assert policy["effective_sizes"] == [12, 24, 48]
    assert policy["imported_itc2007_eligible"] is False
    assert policy["compact_switch_enabled"] is True
    assert policy["applied"] is False
    assert policy["reason"] == "not_imported_itc2007"


def test_fixed_time_room_assumptions_preserve_generic_locks_and_travel_rules():
    inst = _build_instance()
    inst.locked_activities = {1: {"day": "MON", "slot": 0, "room_id": 1}}
    inst.travel_time_rules = {
        "same_building": 0,
        "cross_building": 1,
        "cross_campus": 2,
    }
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    assumptions = model.set_fixed_time_room_assumptions(incumbent)
    solver, status = model.solve(time_limit_seconds=1.0, workers=1, random_seed=11)

    assert assumptions == {
        "mode": "fixed_time_room_dive",
        "fixed_start_activities": 2,
        "free_room_activities": 2,
        "assumption_literals": 2,
    }
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    candidate = model.extract_solution(solver)
    assert candidate[1]["room_id"] == 1
    assert {
        activity_id: (row["day"], row["slot"])
        for activity_id, row in candidate.items()
    } == {
        activity_id: (row["day"], row["slot"])
        for activity_id, row in incumbent.items()
    }
    assert validate_schedule_against_instance(
        inst,
        candidate,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_fixed_time_room_dive_rejects_no_worse_candidate():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        model,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 0.75,
        workers=1,
        seed=13,
    )

    assert returned is incumbent
    assert meta["status"] == "REJECTED_NO_IMPROVEMENT"
    assert meta["validation"]["valid"] is True
    assert meta["fixed_starts_preserved"] is True
    assert meta["returned_source"] == "incumbent"
    assert meta["pre_score"] == meta["candidate_score"]
    assert meta["post_score"] == meta["pre_score"]
    assert meta["returned_score"] == meta["pre_score"]
    assert meta["improvement"] == 0
    assert meta["candidate_improvement"] == 0
    assert meta["post_room_components"] == meta["pre_room_components"]
    assert meta["returned_room_components"] == meta["pre_room_components"]
    assert meta["candidate_room_components"] is not None


def test_fixed_time_room_dive_rejected_worse_candidate_keeps_returned_telemetry(
    monkeypatch,
):
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    worse_candidate = _schedule(0, 2, room_a=2, room_b=2)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    def acceptance_score(_inst, candidate):
        return (
            (100, "planora_generic")
            if candidate is incumbent
            else (120, "planora_generic")
        )

    monkeypatch.setattr(solver_service, "_adaptive_acceptance_score", acceptance_score)
    monkeypatch.setattr(model, "extract_solution", lambda _solver: worse_candidate)

    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        model,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 0.75,
        workers=1,
        seed=13,
    )

    assert returned is incumbent
    assert meta["status"] == "REJECTED_NO_IMPROVEMENT"
    assert meta["validation"]["valid"] is True
    assert meta["pre_score"] == 100
    assert meta["candidate_score"] == 120
    assert meta["candidate_improvement"] == -20
    assert meta["post_score"] == 100
    assert meta["returned_score"] == 100
    assert meta["improvement"] == 0
    assert meta["post_room_components"]["objective_total"] == 100
    assert meta["returned_room_components"]["objective_total"] == 100
    assert meta["candidate_room_components"]["objective_total"] == 120


def test_fixed_time_room_dive_skips_unsupported_and_expired_budget():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)

    unsupported, unsupported_meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        None,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 0.5,
        workers=1,
        seed=17,
    )
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)
    expired, expired_meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        model,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() - 0.01,
        workers=1,
        seed=17,
    )

    assert unsupported is incumbent
    assert unsupported_meta["status"] == "SKIPPED_UNSUPPORTED"
    assert unsupported_meta["attempted"] is False
    assert expired is incumbent
    assert expired_meta["status"] == "SKIPPED_INSUFFICIENT_BUDGET"
    assert expired_meta["attempted"] is False
    assert expired_meta["deadline_overrun_seconds"] >= 0.0
    assert expired_meta["elapsed_seconds"] < 0.1


def test_fixed_time_room_dive_does_not_start_after_upstream_overrun_erodes_reserve():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    calls = {"setup": 0, "search": 0}

    class GuardedModel:
        room_mode = "cp_rooms"
        use_objective = True

        @staticmethod
        def set_fixed_time_room_assumptions(_schedule):
            calls["setup"] += 1
            raise AssertionError("Setup must not start without the full reserve")

        @staticmethod
        def solve(**_kwargs):
            calls["search"] += 1
            raise AssertionError("Search must not start without the full reserve")

    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        GuardedModel(),
        budget_seconds=0.08,
        final_deadline=time.perf_counter() + 0.10,
        workers=1,
        seed=23,
        completion_reserve_seconds=0.05,
    )

    assert returned is incumbent
    assert calls == {"setup": 0, "search": 0}
    assert meta["status"] == "SKIPPED_INSUFFICIENT_BUDGET"
    assert (
        meta["skip_reason"]
        == "full_finalization_and_completion_reserve_unavailable"
    )
    assert meta["attempted"] is False
    assert meta["admission_passed"] is False
    assert (
        meta["admission_scope"]
        == "setup_search_validation_and_outer_completion"
    )
    assert 0.08 < meta["shared_deadline_remaining_at_start_seconds"] < 0.13
    assert meta["completion_reserve_seconds"] == 0.05
    assert meta["admission_required_seconds"] == 0.13
    assert meta["admission_shortfall_seconds"] > 0.0
    assert meta["pre_score"] is None
    assert meta["validation"]["attempted"] is False


def test_solve_instance_fixed_time_room_dive_retains_deadline_after_adaptive_overrun(
    monkeypatch,
):
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    calls = {"setup": 0, "search": 0}

    class InitialModel:
        decomposition_report = {}

        @staticmethod
        def extract_solution(_solver):
            return {activity_id: dict(row) for activity_id, row in incumbent.items()}

    class GuardedRoomModel:
        room_mode = "cp_rooms"
        use_objective = True

        @staticmethod
        def set_fixed_time_room_assumptions(_schedule):
            calls["setup"] += 1
            raise AssertionError("Room finalization must not consume an eroded reserve")

        @staticmethod
        def solve(**_kwargs):
            calls["search"] += 1
            raise AssertionError("Room search must not consume an eroded reserve")

    def feasible_initial(_inst, *, room_mode, use_objective, options):
        return (
            InitialModel(),
            cp_model.CpSolver(),
            int(cp_model.FEASIBLE),
            SolveAttempt(
                room_mode=str(room_mode),
                use_objective=bool(use_objective),
                time_limit_seconds=options.time_limit_seconds,
                raw_status=int(cp_model.FEASIBLE),
                status_name=str(cp_model.CpSolverStatus(cp_model.FEASIBLE)),
                proof_status="feasible_incumbent",
                budget_seconds=options.time_limit_seconds,
            ),
        )

    def adaptive_overrun(
        inst_arg,
        schedule,
        options,
        *,
        fixed_time_room_dive_budget_seconds,
        fixed_time_room_dive_completion_reserve_seconds,
        final_deadline,
        **_kwargs,
    ):
        started = time.perf_counter()
        assert final_deadline is not None
        target_remaining = float(fixed_time_room_dive_budget_seconds) + (
            float(fixed_time_room_dive_completion_reserve_seconds) * 0.50
        )
        time.sleep(
            max(
                0.0,
                float(final_deadline) - time.perf_counter() - target_remaining,
            )
        )
        returned, dive_meta = solver_service._run_fixed_time_room_dive(
            inst_arg,
            schedule,
            GuardedRoomModel(),
            budget_seconds=float(fixed_time_room_dive_budget_seconds),
            final_deadline=float(final_deadline),
            workers=1,
            seed=29,
            completion_reserve_seconds=float(
                fixed_time_room_dive_completion_reserve_seconds
            ),
        )
        elapsed = time.perf_counter() - started
        return returned, {
            "status": "TIME_LIMIT",
            "budget_seconds": float(options.adaptive_lns_seconds),
            "elapsed_seconds": float(elapsed),
            "deadline_overrun_seconds": max(
                0.0,
                float(elapsed) - float(options.adaptive_lns_seconds),
            ),
            "fixed_time_room_dive": dive_meta,
        }

    monkeypatch.setattr(solver_service, "_run_solve_attempt", feasible_initial)
    monkeypatch.setattr(solver_service, "_run_adaptive_lns", adaptive_overrun)

    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=0.20,
            workers=1,
            random_seed=29,
            fixed_time_room_dive=True,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    dive = result.meta["adaptive_lns"]["fixed_time_room_dive"]
    assert result.is_feasible
    assert calls == {"setup": 0, "search": 0}
    assert dive["status"] == "SKIPPED_INSUFFICIENT_BUDGET"
    assert (
        dive["skip_reason"]
        == "full_finalization_and_completion_reserve_unavailable"
    )
    assert dive["admission_passed"] is False
    assert dive["completion_reserve_seconds"] == 0.05
    assert result.meta["timing"]["deadline_overrun_seconds"] == 0.0


def test_fixed_time_room_dive_caps_search_to_the_admitted_reserve():
    inst = _build_instance()
    incumbent = _schedule(0, 2, room_a=1, room_b=1)
    observed: dict[str, float] = {}

    class DeadlineModel:
        room_mode = "cp_rooms"
        use_objective = True

        @staticmethod
        def set_fixed_time_room_assumptions(_schedule):
            time.sleep(0.005)
            return {
                "mode": "fixed_time_room_dive",
                "fixed_start_activities": 2,
                "free_room_activities": 2,
                "assumption_literals": 2,
            }

        @staticmethod
        def solve(*, time_limit_seconds, **_kwargs):
            observed["search_budget_seconds"] = float(time_limit_seconds)
            return cp_model.CpSolver(), int(cp_model.UNKNOWN)

    deadline = time.perf_counter() + 0.20
    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        DeadlineModel(),
        budget_seconds=0.08,
        final_deadline=deadline,
        workers=1,
        seed=23,
    )

    assert returned is incumbent
    assert meta["status"] == "NO_FEASIBLE_CANDIDATE"
    assert 0.0 < observed["search_budget_seconds"] < 0.08
    assert observed["search_budget_seconds"] == meta["search_budget_seconds"]
    assert meta["admission_passed"] is True
    assert meta["deadline_safety_margin_seconds"] > 0.0
    assert meta["elapsed_seconds"] < 0.08


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
    university_fast = solver_service.solve_instance(
        inst,
        SolveOptions(
            room_mode="cp_rooms",
            use_objective=True,
            time_limit_seconds=60.0,
            objective_profile="university fast",
        ),
    )
    assert university_fast.meta.get("objective_profile", {}).get("id") == "university_fast"
    assert attempts[0][:2] == ("partitioned", False)

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
