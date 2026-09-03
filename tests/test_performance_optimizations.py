from __future__ import annotations

import services.schedule_ops_service as schedule_ops
from core.partitioned_solver import (
    PartitionedTimetableSolver,
    week_partitioning_blockers,
)
from scripts.benchmark_end_to_end_performance import run_embedded_workflow
from services.contracts import ImproveOptions
from utils.generator import generate_instance, instance_to_json


def test_partition_views_are_isolated_and_hardest_models_are_queued_first() -> None:
    inst = generate_instance("small_demo")
    first_activity = min(inst.activities)
    inst.locked_activities[first_activity] = {"day": "MON", "slot": 0}
    inst.activity_unavailability[first_activity] = {("FRI", 4)}
    original = instance_to_json(inst)

    model = PartitionedTimetableSolver(inst, use_objective=False)

    assert instance_to_json(inst) == original
    for _, week, partition in model._partitions:
        assert partition.inst is not inst
        assert partition.inst.programs is inst.programs
        assert partition.inst.groups is inst.groups
        assert partition.inst.courses is inst.courses
        assert partition.inst.staff is inst.staff
        assert partition.inst.rooms is inst.rooms
        assert {
            int(activity.week) for activity in partition.inst.activities.values()
        } == {int(week)}
        assert partition.inst.hard_constraints is not inst.hard_constraints

    execution = model._execution_partitions()
    hardness = [int(row[3]["constraints"]) for row in execution]
    assert hardness == sorted(hardness, reverse=True)


def test_partition_admission_normalizes_optional_boolean_flags() -> None:
    inst = generate_instance("small_demo")

    inst.hard_constraints["force_repeat_weekly_pattern"] = None
    assert week_partitioning_blockers(inst) == []

    inst.hard_constraints["force_repeat_weekly_pattern"] = "yes"
    assert any(
        "force_repeat_weekly_pattern" in reason
        for reason in week_partitioning_blockers(inst)
    )


def test_empty_focus_improvement_reuses_the_validated_after_score(monkeypatch) -> None:
    score_calls: list[dict[int, dict[str, object]]] = []

    def fake_score(_inst, schedule):
        score_calls.append(schedule)
        return {
            "soft_penalty": len(score_calls),
            "hard_conflicts": [],
            "hard_conflict_count": 0,
        }

    monkeypatch.setattr(schedule_ops, "score_schedule", fake_score)
    monkeypatch.setattr(
        schedule_ops,
        "improve_schedule",
        lambda _inst, schedule, _options, **_kwargs: schedule,
    )

    result = schedule_ops.improve_schedule_shared(
        object(),
        {1: {"week": 1, "day": "MON", "slot": 0, "group_ids": []}},
        ImproveOptions(iterations=0, max_seconds=0.05),
    )

    assert len(score_calls) == 2
    assert result["global_after"] is result["after"]
    assert result["after"]["hard_conflict_count"] == 0


def test_score_reuses_penalty_breakdown_for_driver_ranking(monkeypatch) -> None:
    breakdown_calls = 0

    monkeypatch.setattr(schedule_ops, "normalize_schedule", lambda schedule: schedule)
    monkeypatch.setattr(
        schedule_ops,
        "validate_schedule_against_instance",
        lambda *_args, **_kwargs: [],
    )

    def fake_breakdown(_inst, _schedule):
        nonlocal breakdown_calls
        breakdown_calls += 1
        return {"total": 11, "stud_gaps": 7, "stability": 4}

    monkeypatch.setattr(schedule_ops, "compute_penalty_breakdown", fake_breakdown)

    scored = schedule_ops.score_schedule(object(), {1: {}})

    assert breakdown_calls == 1
    assert scored["soft_penalty"] == 11
    assert scored["drivers"] == [
        {"term": "stud_gaps", "penalty": 7, "share": 7 / 11},
        {"term": "stability", "penalty": 4, "share": 4 / 11},
    ]


def test_embedded_end_to_end_runner_covers_solve_validation_score_and_improve() -> None:
    report = run_embedded_workflow(
        mode="small_demo",
        seed=1,
        room_mode="partitioned",
        objective_profile="university_fast",
        solve_seconds=8.0,
        workers=1,
        improve_iterations=20,
        improve_seconds=0.05,
    )

    assert report["valid"] is True
    assert report["solve"]["schedule_rows"] == report["instance"]["activities"]
    assert report["validation_error_count"] == 0
    assert report["final_score"]["hard_conflict_count"] == 0
    assert report["solve"]["engine_meta"]["engine_backend"]["backend_id"] == (
        "planora-solver-service-v1"
    )
    assert {
        "source_generate_or_import",
        "session_create",
        "solve_action",
        "independent_solve_validation",
        "solve_score_action",
        "improve_action",
        "independent_improve_validation",
        "improve_score_action",
    } <= set(report["stage_seconds"])
