from __future__ import annotations

from itertools import product

import pytest
from ortools.sat.python import cp_model

from core.metaheuristics import LocalSearchImprover
from core.room_decomposition import ExactRoomSubproblem
from core.room_proof_checker import check_contextual_hall_derivation
from core.solver_cp_sat import TimetableSolver, assign_rooms_greedily
from utils.domain import (
    Activity,
    Course,
    DistributionConstraint,
    Group,
    Instance,
    Program,
    Room,
    StaffMember,
)
from utils.specs import validate_schedule_against_instance
from utils.generator import generate_instance


def _two_activity_instance(*, rooms: dict[int, Room]) -> Instance:
    return Instance(
        days=["MON", "TUE"],
        slots_per_day=2,
        weeks=[1],
        programs={
            1: Program(id=1, name="P", course_ids=[1, 2], group_ids=[1, 2]),
        },
        groups={
            1: Group(id=1, name="G1", program_id=1, size=40, course_ids=[1]),
            2: Group(id=2, name="G2", program_id=1, size=40, course_ids=[2]),
        },
        courses={
            course_id: Course(
                id=course_id,
                code=f"C{course_id}",
                name=f"Course {course_id}",
                structure_type="LEC_ONLY",
                lecture_count=1,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                prof_id=course_id,
                ta_id=course_id + 2,
            )
            for course_id in (1, 2)
        },
        staff={
            staff_id: StaffMember(
                id=staff_id,
                name=f"S{staff_id}",
                is_prof=staff_id <= 2,
                available_days={"MON", "TUE"},
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses={staff_id if staff_id <= 2 else staff_id - 2},
            )
            for staff_id in (1, 2, 3, 4)
        },
        rooms=rooms,
        activities={
            activity_id: Activity(
                id=activity_id,
                course_id=activity_id,
                week=1,
                kind="LEC",
                duration=1,
                group_ids=[activity_id],
                prof_id=activity_id,
                ta_id=activity_id + 2,
            )
            for activity_id in (1, 2)
        },
    )


def _simultaneous_schedule() -> dict[int, dict[str, object]]:
    return {
        activity_id: {
            "room_id": None,
            "staff_id": activity_id,
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "group_ids": [activity_id],
            "course_id": activity_id,
            "kind": "LEC",
        }
        for activity_id in (1, 2)
    }


def test_exact_subproblem_emits_hall_deficiency_certificate() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="Eligible", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="Too small", capacity=30, room_type="LECTURE"),
        }
    )
    result = ExactRoomSubproblem(inst, _simultaneous_schedule()).solve(workers=1)

    assert not result.feasible
    certificate = result.certificates[0]
    assert certificate.certificate_type == "hall_deficiency"
    assert certificate.representative_activity_ids == (1, 2)
    assert certificate.candidate_room_ids == (1,)
    assert certificate.deficiency == 1


def test_cluster_capacity_uses_union_of_all_student_groups() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="Small", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="Large", capacity=100, room_type="LECTURE"),
        }
    )
    result = ExactRoomSubproblem(
        inst,
        _simultaneous_schedule(),
        clusters_by_week_kind={1: {"LEC": [[1, 2]], "TUT": [], "LAB": []}},
    ).solve(workers=1)

    assert result.feasible
    assert result.assignments == {1: 2, 2: 2}


def test_decomposed_solver_adds_hall_cut_and_returns_valid_schedule() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="Eligible", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="Too small", capacity=30, room_type="LECTURE"),
        }
    )
    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    solver, status = model.solve(time_limit_seconds=10, workers=1, random_seed=7)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert model.decomposition_report["cuts_added"] >= 1
    reported_cuts = [
        cut
        for round_row in model.decomposition_report["rounds"]
        for cut in round_row.get("room_cuts", [])
    ]
    assert len(reported_cuts) == model.decomposition_report["cuts_added"]
    assert model.decomposition_report["cut_kind_counts"]
    assert all("cut_kind" in cut and "term_count" in cut for cut in reported_cuts)
    assert schedule[1]["day"] != schedule[2]["day"] or schedule[1]["slot"] != schedule[2]["slot"]
    assert validate_schedule_against_instance(inst, schedule, strict_rooms=True) == []


@pytest.mark.timing_sensitive
def test_bounded_decomposed_optimization_reserves_exact_room_time() -> None:
    inst = generate_instance("small_demo")
    model = TimetableSolver(inst, room_mode="decomposed", use_objective=True)
    solver, status = model.solve(
        time_limit_seconds=15.0,
        workers=1,
        random_seed=1,
    )

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    report = model.decomposition_report
    assert report["status"] == "FEASIBLE"
    assert report["proof_status"] in {"feasible_incumbent", "optimal"}
    assert report["budget_seconds"] == 15.0
    assert report["objective_value"] is not None
    successful_round = report["rounds"][-1]
    assert 0.0 < successful_round["master_budget_seconds"] < 15.0
    room_timing = successful_round["room_subproblem"]["timing"]
    assert room_timing["search_budget_seconds"] > 0.0


def test_hall_cut_preserves_feasible_alternative_with_time_varying_room_domains() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(
                id=1,
                name="Always available",
                capacity=50,
                room_type="LECTURE",
                availability={("MON", 0), ("MON", 1), ("MON", 2)},
            ),
            2: Room(
                id=2,
                name="Late room",
                capacity=50,
                room_type="LECTURE",
                availability={("MON", 1), ("MON", 2)},
            ),
        }
    )
    inst.days = ["MON"]
    inst.slots_per_day = 3
    for staff in inst.staff.values():
        staff.available_days = {"MON"}
    for course in inst.courses.values():
        course.lecture_count = 2
    for activity in inst.activities.values():
        activity.duration = 2

    incumbent = _simultaneous_schedule()
    for info in incumbent.values():
        info["duration"] = 2

    room_subproblem = ExactRoomSubproblem(inst, incumbent, optimize=False)
    certificate = next(
        item for item in room_subproblem._hall_certificates() if item.slot == 1
    )
    assert certificate.candidate_room_ids == (1,)

    feasible_alternative = {
        1: dict(incumbent[1]),
        2: {**incumbent[2], "slot": 1},
    }
    alternative_result = ExactRoomSubproblem(
        inst,
        feasible_alternative,
        optimize=False,
    ).solve(workers=1)
    assert alternative_result.feasible is True
    assert alternative_result.assignments == {1: 1, 2: 2}

    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    assert model._add_room_certificate_cut(certificate, incumbent) is True
    assert model._last_room_cut_metadata["cut_kind"] == "exact_incumbent_nogood"
    assert model._last_room_cut_metadata["strengthened"] is False
    assert (
        model._last_room_cut_metadata["fallback_reason"]
        == "no_additional_domain_monotone_start"
    )
    model.m.Add(model.start[1] == 0)
    model.m.Add(model.start[2] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model.m)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}


def test_contextual_hall_cut_strengthens_invariant_candidate_domains() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="Eligible", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="Too small", capacity=30, room_type="LECTURE"),
        }
    )
    inst.days = ["MON"]
    inst.slots_per_day = 3
    for staff in inst.staff.values():
        staff.available_days = {"MON"}
    for course in inst.courses.values():
        course.lecture_count = 2
    for activity in inst.activities.values():
        activity.duration = 2

    incumbent = _simultaneous_schedule()
    for info in incumbent.values():
        info["duration"] = 2
    certificate = next(
        item
        for item in ExactRoomSubproblem(inst, incumbent, optimize=False)._hall_certificates()
        if item.slot == 1
    )

    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    assert model._add_room_certificate_cut(certificate, incumbent) is True
    metadata = model._last_room_cut_metadata
    assert metadata["cut_kind"] == "contextual_hall"
    assert metadata["strengthened"] is True
    assert metadata["term_count"] == 4
    assert metadata["rhs"] == 1

    # The exact incumbent nogood alone permits (0, 1). The contextual Hall cut
    # also excludes it because both duration-two jobs still overlap at slot 1
    # and every covering start has the invariant domain {room 1}.
    model.m.Add(model.start[1] == 0)
    model.m.Add(model.start[2] == 1)
    status = cp_model.CpSolver().Solve(model.m)
    assert int(status) == int(cp_model.INFEASIBLE)


def test_contextual_hall_cut_recomputes_the_aggregate_cluster_domain() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="R1", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="R2", capacity=70, room_type="LECTURE"),
        }
    )
    inst.days = ["MON"]
    inst.slots_per_day = 3
    for staff in inst.staff.values():
        staff.available_days = {"MON"}
    for course in inst.courses.values():
        course.lecture_count = 2
    for activity in inst.activities.values():
        activity.duration = 2
        setattr(activity, "cluster_key", "SHARED")

    incumbent = _simultaneous_schedule()
    for info in incumbent.values():
        info["duration"] = 2

    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    room_subproblem = ExactRoomSubproblem(
        inst,
        incumbent,
        clusters_by_week_kind=model.clusters_by_week_kind,
        optimize=False,
    )
    certificate = next(
        item for item in room_subproblem._hall_certificates() if item.slot == 1
    )

    # Each 40-seat member fits alone, but the co-located cluster needs 80 seats.
    # The cut proof must therefore use the cluster's empty aggregate domain.
    assert certificate.representative_activity_ids == (1,)
    assert certificate.candidate_room_ids == ()
    assert model._add_room_certificate_cut(certificate, incumbent) is True
    assert model._last_room_cut_metadata["cut_kind"] == "contextual_hall"
    assert model._last_room_cut_metadata["term_count"] == 2
    assert model._last_room_cut_metadata["rhs"] == 0

    status = cp_model.CpSolver().Solve(model.m)
    assert int(status) == int(cp_model.INFEASIBLE)


def test_contextual_hall_cuts_preserve_every_exactly_room_feasible_tiny_pattern() -> None:
    # For a duration-two job on three slots, these are all four distinct
    # start-availability domains: neither start, start 0 only, start 1 only,
    # or both starts. Exhausting two rooms covers all 4 x 4 domain combinations.
    availability_domains = (
        set(),
        {("MON", 0), ("MON", 1)},
        {("MON", 1), ("MON", 2)},
        {("MON", 0), ("MON", 1), ("MON", 2)},
    )
    time_patterns = tuple(product((0, 1), repeat=2))
    cuts_checked = 0
    feasible_patterns_checked = 0
    strengthened_cuts = 0
    exact_fallback_cuts = 0

    class StartCollector(cp_model.CpSolverSolutionCallback):
        def __init__(self, model: TimetableSolver) -> None:
            super().__init__()
            self.model = model
            self.patterns: set[tuple[int, int]] = set()

        def on_solution_callback(self) -> None:
            self.patterns.add(
                (
                    int(self.Value(self.model.start[1])),
                    int(self.Value(self.model.start[2])),
                )
            )

    for left_availability, right_availability in product(
        availability_domains,
        repeat=2,
    ):
        inst = _two_activity_instance(
            rooms={
                1: Room(
                    id=1,
                    name="R1",
                    capacity=50,
                    room_type="LECTURE",
                    availability=set(left_availability),
                ),
                2: Room(
                    id=2,
                    name="R2",
                    capacity=50,
                    room_type="LECTURE",
                    availability=set(right_availability),
                ),
            }
        )
        inst.days = ["MON"]
        inst.slots_per_day = 3
        for staff in inst.staff.values():
            staff.available_days = {"MON"}
        for course in inst.courses.values():
            course.lecture_count = 2
        for activity in inst.activities.values():
            activity.duration = 2

        schedules: dict[tuple[int, int], dict[int, dict[str, object]]] = {}
        room_results = {}
        for pattern in time_patterns:
            schedule = _simultaneous_schedule()
            schedule[1]["slot"] = int(pattern[0])
            schedule[2]["slot"] = int(pattern[1])
            for info in schedule.values():
                info["duration"] = 2
            schedules[pattern] = schedule
            room_results[pattern] = ExactRoomSubproblem(
                inst,
                schedule,
                optimize=False,
            ).solve(workers=1)

        feasible_patterns = {
            pattern for pattern, result in room_results.items() if result.feasible
        }
        for incumbent_pattern, room_result in room_results.items():
            for certificate in room_result.certificates:
                if certificate.certificate_type != "hall_deficiency":
                    continue
                model = TimetableSolver(
                    inst,
                    room_mode="decomposed",
                    use_objective=False,
                )
                assert model._add_room_certificate_cut(
                    certificate,
                    schedules[incumbent_pattern],
                ) is True
                assert model._last_room_cut_metadata["cut_kind"] in {
                    "contextual_hall",
                    "exact_incumbent_nogood",
                }
                strengthened_cuts += int(
                    bool(model._last_room_cut_metadata["strengthened"])
                )
                exact_fallback_cuts += int(
                    model._last_room_cut_metadata["cut_kind"]
                    == "exact_incumbent_nogood"
                )
                if model._last_room_cut_metadata["cut_kind"] == "contextual_hall":
                    assert model._last_room_cut_metadata["rhs"] == len(
                        model._last_room_cut_metadata["derived_gamma_room_ids"]
                    )
                    assert set(
                        model._last_room_cut_metadata["derived_gamma_room_ids"]
                    ).issubset(model._last_room_cut_metadata["witness_room_ids"])
                    assert check_contextual_hall_derivation(
                        inst,
                        certificate.to_dict(),
                        model._last_room_cut_metadata,
                    ).valid

                collector = StartCollector(model)
                solver = cp_model.CpSolver()
                solver.parameters.enumerate_all_solutions = True
                solver.Solve(model.m, collector)

                cuts_checked += 1
                for feasible_pattern in feasible_patterns:
                    feasible_patterns_checked += 1
                    assert feasible_pattern in collector.patterns

    assert cuts_checked > 0
    assert feasible_patterns_checked > 0
    assert strengthened_cuts > 0
    assert exact_fallback_cuts > 0


def test_time_move_delta_includes_affected_soft_distribution_penalty() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="R1", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="R2", capacity=50, room_type="LECTURE"),
        }
    )
    inst.distribution_constraints = [
        DistributionConstraint(
            id="soft-same-day",
            constraint_type="SameDays",
            activity_ids=[1, 2],
            required=False,
            penalty=1000,
        )
    ]
    schedule = _simultaneous_schedule()
    schedule[1]["room_id"] = 1
    schedule[2]["room_id"] = 2

    improver = LocalSearchImprover(inst, random_seed=1)
    improver._build_state(schedule)
    incremental_delta = improver._time_move_delta(schedule, [1], "TUE", 0)

    trial = {activity_id: dict(info) for activity_id, info in schedule.items()}
    trial[1]["day"] = "TUE"
    full_delta = improver.compute_soft_penalty(trial) - improver.compute_soft_penalty(
        schedule
    )

    assert full_delta == 1000
    assert incremental_delta == full_delta
    assert schedule[1]["day"] == "MON"


def test_soft_room_capacity_has_greedy_and_exact_decomposition_parity() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="More overflow", capacity=30, room_type="LECTURE"),
            2: Room(id=2, name="Less overflow", capacity=35, room_type="LECTURE"),
        }
    )
    inst.hard_constraints["enforce_room_capacity"] = False
    fixed_times = _simultaneous_schedule()
    fixed_times[2]["slot"] = 1

    greedy_schedule = {
        activity_id: dict(info) for activity_id, info in fixed_times.items()
    }
    assign_rooms_greedily(inst, greedy_schedule)
    exact_result = ExactRoomSubproblem(inst, fixed_times, optimize=True).solve(workers=1)

    assert exact_result.feasible is True
    assert exact_result.assignments == {1: 2, 2: 2}
    assert {
        activity_id: int(info["room_id"])
        for activity_id, info in greedy_schedule.items()
    } == exact_result.assignments


def test_cp_rooms_uses_all_eligible_rooms_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TT_CP_ROOM_CANDIDATE_LIMIT", raising=False)
    rooms = {
        room_id: Room(id=room_id, name=f"R{room_id}", capacity=50, room_type="LECTURE")
        for room_id in range(1, 31)
    }
    inst = _two_activity_instance(rooms=rooms)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)

    assert model.room_candidate_limit == 0
    assert len(model.allowed_rooms[1]) == 30


def test_cp_rooms_enforces_combined_cluster_capacity() -> None:
    inst = _two_activity_instance(
        rooms={
            1: Room(id=1, name="Small", capacity=50, room_type="LECTURE"),
            2: Room(id=2, name="Large", capacity=100, room_type="LECTURE"),
        }
    )
    setattr(inst.activities[1], "cluster_key", "SHARED")
    setattr(inst.activities[2], "cluster_key", "SHARED")
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)
    solver, status = model.solve(time_limit_seconds=5, workers=1, random_seed=3)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert schedule[1]["room_id"] == 2
    assert schedule[2]["room_id"] == 2
