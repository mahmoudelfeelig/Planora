from __future__ import annotations

import copy

import pytest
from ortools.sat.python import cp_model

import core.solver_cp_sat as solver_cp_sat
from core.partitioned_solver import PartitionedTimetableSolver
from core.solver_cp_sat import GreedyRoomingError
from utils.domain import DistributionConstraint
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


def test_partitioned_solver_returns_complete_valid_schedule() -> None:
    inst = generate_instance("small_demo")
    model = PartitionedTimetableSolver(inst, use_objective=False)

    solver, status = model.solve(
        time_limit_seconds=20.0,
        workers=4,
        random_seed=7,
    )

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert len(schedule) == len(inst.activities)
    assert validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert model.decomposition_report["partition_dimension"] == "week"
    assert model.decomposition_report["model"]["partition_count"] == len(inst.weeks)
    assert all(
        row["inner_room_mode"] in {"greedy", "decomposed"}
        for row in model.decomposition_report["partitions"]
    )
    assert all(
        not row["exact_room_fallback_used"]
        or row["room_decomposition"]["status"] == "FEASIBLE"
        for row in model.decomposition_report["partitions"]
    )


def test_partitioned_solver_rejects_required_cross_week_decision_coupling() -> None:
    inst = generate_instance("small_demo")
    by_week: dict[int, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        by_week.setdefault(int(activity.week), []).append(int(activity_id))
    weeks = sorted(by_week)
    assert len(weeks) >= 2
    inst.distribution_constraints.append(
        DistributionConstraint(
            id="cross-week-same-start",
            constraint_type="same_start",
            activity_ids=[by_week[weeks[0]][0], by_week[weeks[1]][0]],
            required=True,
        )
    )

    with pytest.raises(ValueError, match="required cross-week"):
        PartitionedTimetableSolver(inst, use_objective=False)


def test_partitioned_solver_reports_soft_cross_week_constraints() -> None:
    inst = generate_instance("small_demo")
    by_week: dict[int, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        by_week.setdefault(int(activity.week), []).append(int(activity_id))
    weeks = sorted(by_week)
    inst.distribution_constraints.append(
        DistributionConstraint(
            id="soft-cross-week-day",
            constraint_type="same_days",
            activity_ids=[by_week[weeks[0]][0], by_week[weeks[1]][0]],
            required=False,
            penalty=3,
        )
    )
    model = PartitionedTimetableSolver(inst, use_objective=False)
    _, status = model.solve(time_limit_seconds=20.0, workers=2, random_seed=3)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    assert model.decomposition_report[
        "soft_cross_week_constraints_scored_post_solve"
    ] == ["soft-cross-week-day"]


def test_partitioned_solver_splits_safe_cross_week_hard_constraints() -> None:
    inst = generate_instance("small_demo")
    by_week: dict[int, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        by_week.setdefault(int(activity.week), []).append(int(activity_id))
    weeks = sorted(by_week)
    inst.distribution_constraints.append(
        DistributionConstraint(
            id="cross-week-not-overlap",
            constraint_type="not_overlap",
            activity_ids=[
                by_week[weeks[0]][0],
                by_week[weeks[1]][0],
                by_week[weeks[1]][1],
            ],
            required=True,
        )
    )
    model = PartitionedTimetableSolver(inst, use_objective=False)
    solver, status = model.solve(time_limit_seconds=20.0, workers=2, random_seed=5)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert model.decomposition_report[
        "required_cross_week_constraints_resolved_without_coupling"
    ] == ["cross-week-not-overlap"]


def test_partitioned_solver_rejects_global_objective_and_repeat_pattern() -> None:
    inst = generate_instance("small_demo")
    with pytest.raises(ValueError, match="globally valid objective bound"):
        PartitionedTimetableSolver(inst, use_objective=True)

    repeated = copy.deepcopy(inst)
    repeated.hard_constraints["force_repeat_weekly_pattern"] = True
    with pytest.raises(ValueError, match="force_repeat_weekly_pattern"):
        PartitionedTimetableSolver(repeated, use_objective=False)


def test_partitioned_solver_activates_exact_room_fallback(monkeypatch) -> None:
    inst = generate_instance("small_demo")

    def reject_fast_rooming(*args, **kwargs):
        raise GreedyRoomingError("forced test fallback", reason="test")

    monkeypatch.setattr(solver_cp_sat, "assign_rooms_greedily", reject_fast_rooming)
    model = PartitionedTimetableSolver(inst, use_objective=False)
    solver, status = model.solve(time_limit_seconds=30.0, workers=4, random_seed=11)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert all(
        row["exact_room_fallback_used"]
        and row["inner_room_mode"] == "decomposed"
        for row in model.decomposition_report["partitions"]
    )
