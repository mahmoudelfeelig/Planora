from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from collections import Counter

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_constructive import construct_itc2007_schedule
from core.projected_time_search import (
    _ITCProjectedState,
    _ProjectedTrajectoryResult,
    _anneal_fixed_time_rooms,
    _course_room_ejection_descent,
    _polish_large_fixed_time_rooms,
    _projected_trajectory_iteration_checkpoint,
    _run_projected_trajectory,
    optimize_itc2007_fixed_time_rooms_cp,
    optimize_projected_times,
)
from services import solver_service
from services.contracts import SolveOptions
from utils.specs import validate_schedule_against_instance


def _instance(
    *,
    name: str,
    days: int,
    periods_per_day: int,
    courses: tuple[ITC2007Course, ...],
    room_capacities: tuple[int, ...],
    curricula: dict[str, tuple[str, ...]] | None = None,
    unavailability: tuple[tuple[str, int, int], ...] = (),
):
    problem = ITC2007Problem(
        name=name,
        days=int(days),
        periods_per_day=int(periods_per_day),
        courses=courses,
        rooms=tuple(
            ITC2007Room(f"R{index}", int(capacity))
            for index, capacity in enumerate(room_capacities)
        ),
        curricula=curricula or {},
        unavailability=unavailability,
    )
    return convert_itc2007_to_instance(problem)


def _multistart_fixture():
    return _instance(
        name="multistart-separation",
        days=3,
        periods_per_day=3,
        courses=(
            ITC2007Course("C0", "T1", 1, 2, 10),
            ITC2007Course("C1", "T0", 3, 2, 29),
            ITC2007Course("C2", "T0", 2, 2, 16),
            ITC2007Course("C3", "T1", 1, 2, 50),
            ITC2007Course("C4", "T0", 2, 2, 24),
            ITC2007Course("C5", "T1", 3, 1, 41),
            ITC2007Course("C6", "T1", 3, 1, 42),
        ),
        room_capacities=(20, 45, 60),
        curricula={
            "Q0": ("C4", "C5"),
            "Q1": ("C3", "C5"),
            "Q2": ("C2", "C3"),
        },
    )


def _construct(inst, *, seed: int = 13):
    result = construct_itc2007_schedule(
        inst,
        deadline=time.perf_counter() + 1.0,
        seed=int(seed),
        beam_width=4,
        bundle_limit=2,
    )
    assert result.schedule is not None, result.to_dict()
    return result


def test_fixed_time_room_annealing_crosses_a_stability_swap_barrier() -> None:
    inst = _instance(
        name="stability-swap",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "TA", 2, 1, 10),
            ITC2007Course("B", "TB", 2, 1, 10),
        ),
        room_capacities=(20, 20),
    )
    schedule = {
        1: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 1},
        2: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 2},
        3: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 2},
        4: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 1},
    }
    for activity_id, row in schedule.items():
        activity = inst.activities[int(activity_id)]
        row.update(
            {
                "staff_id": int(activity.prof_id),
                "course_id": int(activity.course_id),
                "group_ids": list(activity.group_ids),
                "kind": str(activity.kind),
            }
        )
    initial = score_itc2007_instance_schedule(inst, schedule)

    improved, status, telemetry = _anneal_fixed_time_rooms(
        inst,
        schedule,
        deadline=time.perf_counter() + 0.20,
        seed=17,
        max_iterations=5_000,
    )

    final = score_itc2007_instance_schedule(inst, improved)
    assert status == "improved"
    assert initial.room_stability == 2
    assert final.room_stability == 0
    assert final.total == initial.total - 2
    assert telemetry["best_room_objective"] == 0
    assert all(
        len(
            {
                row["room_id"]
                for row in improved.values()
                if row["day"] == day and row["slot"] == slot
            }
        )
        == 2
        for day in inst.days
        for slot in range(inst.slots_per_day)
    )


def test_course_room_ejection_chain_crosses_the_same_barrier_deterministically() -> None:
    inst = _instance(
        name="course-room-ejection",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "TA", 2, 1, 10),
            ITC2007Course("B", "TB", 2, 1, 10),
        ),
        room_capacities=(20, 20),
    )
    schedule = {
        1: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 1},
        2: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 2},
        3: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 2},
        4: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 1},
    }
    for activity_id, row in schedule.items():
        activity = inst.activities[int(activity_id)]
        row.update(
            {
                "staff_id": int(activity.prof_id),
                "course_id": int(activity.course_id),
                "group_ids": list(activity.group_ids),
                "kind": str(activity.kind),
            }
        )

    improved, status, telemetry = _course_room_ejection_descent(
        inst,
        schedule,
        deadline=time.perf_counter() + 0.20,
        max_sweeps=4,
    )
    expired, expired_status, expired_telemetry = _course_room_ejection_descent(
        inst,
        schedule,
        deadline=time.perf_counter() - 0.001,
        max_sweeps=4,
    )

    initial = score_itc2007_instance_schedule(inst, schedule)
    final = score_itc2007_instance_schedule(inst, improved)
    assert status == "improved"
    assert final.total == initial.total - 2
    assert final.room_stability == 0
    assert telemetry["accepted_chains"] == 1
    assert telemetry["improvement"] == 2
    assert telemetry["final_room_objective"] == 0
    assert telemetry["deadline_exhausted"] is False
    assert validate_schedule_against_instance(
        inst,
        improved,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert {
        activity_id: (row["day"], row["slot"])
        for activity_id, row in improved.items()
    } == {
        activity_id: (row["day"], row["slot"])
        for activity_id, row in schedule.items()
    }
    assert expired_status == "deadline_exhausted"
    assert expired == schedule
    assert expired_telemetry["accepted_chains"] == 0


def test_large_room_polish_keeps_best_complete_checkpoint(monkeypatch) -> None:
    inst = _instance(
        name="room-polish-checkpoints",
        days=1,
        periods_per_day=1,
        courses=(ITC2007Course("A", "TA", 1, 1, 10),),
        room_capacities=(5, 7, 20),
    )
    activity = inst.activities[1]
    schedule = {
        1: {
            "week": 1,
            "day": "D0",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    }
    sequence = iter((2, 3, 2, 1, 1, 1))

    def candidate(_inst, incumbent, *_args, **_kwargs):
        output = {activity_id: dict(row) for activity_id, row in incumbent.items()}
        output[1]["room_id"] = next(sequence)
        return output, "test", {"deadline_exhausted": False}

    monkeypatch.setattr(
        "core.projected_time_search._course_room_ejection_descent",
        candidate,
    )
    monkeypatch.setattr(
        "core.projected_time_search._anneal_fixed_time_rooms",
        candidate,
    )

    polished, telemetry = _polish_large_fixed_time_rooms(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        validator=lambda _inst, _schedule: [],
        max_cycles=3,
    )

    assert polished[1]["room_id"] == 3
    assert telemetry["cycles_completed"] == 3
    assert [row["accepted"] for row in telemetry["trace"]] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_fixed_time_room_cp_public_boundary_improves_without_moving_times() -> None:
    inst = _instance(
        name="exact-room-tail",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "TA", 2, 1, 10),
            ITC2007Course("B", "TB", 2, 1, 10),
        ),
        room_capacities=(20, 20),
    )
    schedule = {
        1: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 1},
        2: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 2},
        3: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 2},
        4: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 1},
    }
    for activity_id, row in schedule.items():
        activity = inst.activities[int(activity_id)]
        row.update(
            {
                "staff_id": int(activity.prof_id),
                "course_id": int(activity.course_id),
                "group_ids": list(activity.group_ids),
                "kind": str(activity.kind),
            }
        )

    result = optimize_itc2007_fixed_time_rooms_cp(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert result.status == "improved"
    assert result.improved is True
    assert result.fixed_starts_preserved is True
    assert result.initial_score is not None
    assert result.final_score is not None
    assert result.initial_score.total - result.final_score.total == 2
    assert result.final_score.room_stability == 0
    assert result.deadline_overrun_seconds == 0.0
    assert {
        activity_id: (
            row["week"],
            row["day"],
            row["slot"],
            row["duration"],
        )
        for activity_id, row in result.schedule.items()
    } == {
        activity_id: (
            row["week"],
            row["day"],
            row["slot"],
            row["duration"],
        )
        for activity_id, row in schedule.items()
    }
    assert validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_fixed_time_room_cp_expired_deadline_returns_exact_incumbent() -> None:
    inst = _instance(
        name="expired-room-tail",
        days=1,
        periods_per_day=1,
        courses=(ITC2007Course("A", "TA", 1, 1, 10),),
        room_capacities=(20,),
    )
    schedule = {
        1: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 1}
    }

    result = optimize_itc2007_fixed_time_rooms_cp(
        inst,
        schedule,
        deadline=time.perf_counter() - 0.001,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert result.improved is False
    assert result.schedule == schedule
    assert result.deadline_exhausted is True


def test_fixed_time_room_cp_rejects_non_lossless_room_capacity_semantics() -> None:
    inst = _instance(
        name="non-lossless-room-capacity",
        days=1,
        periods_per_day=1,
        courses=(ITC2007Course("A", "TA", 1, 1, 10),),
        room_capacities=(20,),
    )
    inst.hard_constraints["enforce_room_capacity"] = True
    activity = inst.activities[1]
    schedule = {
        1: {
            "week": 1,
            "day": "D0",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    }

    result = optimize_itc2007_fixed_time_rooms_cp(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert result.status == "ineligible"
    assert result.improved is False
    assert result.schedule == schedule
    assert "requires_soft_itc2007_room_capacity" in result.eligibility_reasons


def test_constructive_matches_tiny_feasibility_and_fails_closed() -> None:
    feasible = _instance(
        name="tiny-feasible",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "T", 1, 1, 10),
            ITC2007Course("B", "T", 1, 1, 10),
        ),
        room_capacities=(20,),
        unavailability=(("A", 0, 0),),
    )
    result = _construct(feasible, seed=3)

    assert result.feasible is True
    assert validate_schedule_against_instance(
        feasible,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    # The only brute-force feasible shape is one lecture in each of the two
    # periods because both lectures share the same teacher and there is one room.
    assert {row["slot"] for row in result.schedule.values()} == {0, 1}
    assert result.schedule[1]["slot"] == 1

    infeasible = _instance(
        name="tiny-infeasible",
        days=1,
        periods_per_day=2,
        courses=(ITC2007Course("A", "T", 3, 1, 10),),
        room_capacities=(20,),
    )
    failed = construct_itc2007_schedule(
        infeasible,
        deadline=time.perf_counter() + 1.0,
        seed=3,
    )

    assert failed.schedule is None
    assert failed.status == "infeasible"
    assert failed.deadline_exhausted is False


def test_constructive_is_reproducible_on_a_crowded_conflict_fixture() -> None:
    inst = _multistart_fixture()

    first = _construct(inst, seed=13)
    second = _construct(inst, seed=13)

    assert first.schedule == second.schedule
    assert first.nodes == second.nodes
    assert first.backtracks == second.backtracks
    assert len(first.schedule) == 15
    assert max(
        sum(
            int(row["day"] == day and int(row["slot"]) == slot)
            for row in first.schedule.values()
        )
        for day in inst.days
        for slot in range(inst.slots_per_day)
    ) <= len(inst.rooms)
    assert validate_schedule_against_instance(
        inst,
        first.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_structural_multistart_is_nonworsening_and_explores_distinct_trajectories() -> None:
    inst = _multistart_fixture()
    incumbent = _construct(inst, seed=13).schedule
    assert incumbent is not None

    single = optimize_projected_times(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
        candidate_batch_size=8,
        room_reserve_seconds=0.10,
        multi_start_count=1,
        enable_constructive_start=False,
    )
    multiple = optimize_projected_times(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
        candidate_batch_size=8,
        room_reserve_seconds=0.10,
        multi_start_count=3,
        enable_constructive_start=False,
    )

    assert multiple.final_score <= single.final_score
    assert multiple.starts_generated > single.starts_generated
    assert multiple.final_projected_score <= single.final_projected_score
    assert multiple.starts_generated == multiple.starts_completed == 3
    assert {row["trajectory_mode"] for row in multiple.start_telemetry} == {
        "late_acceptance",
        "long_horizon",
        "steepest_descent",
    }
    assert any(
        row["activity_distance_from_incumbent"] > 0
        for row in multiple.start_telemetry
        if row["start_index"] != 0
    )
    assert validate_schedule_against_instance(
        inst,
        multiple.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_multistart_repeats_the_same_finished_search() -> None:
    inst = _multistart_fixture()
    incumbent = _construct(inst, seed=13).schedule
    assert incumbent is not None

    results = [
        optimize_projected_times(
            inst,
            incumbent,
            deadline=time.perf_counter() + 0.5,
            seed=17,
            candidate_batch_size=8,
            room_reserve_seconds=0.10,
            multi_start_count=3,
            enable_constructive_start=False,
        )
        for _ in range(2)
    ]

    assert results[0].schedule == results[1].schedule
    assert results[0].final_score == results[1].final_score
    assert [
        (
            row["start_kind"],
            row["start_projected_score"],
            row["final_projected_score"],
            row["accepted_moves"],
        )
        for row in results[0].start_telemetry
    ] == [
        (
            row["start_kind"],
            row["start_projected_score"],
            row["final_projected_score"],
            row["accepted_moves"],
        )
        for row in results[1].start_telemetry
    ]


def test_candidate_generation_and_fixed_trajectory_are_hash_seed_invariant() -> None:
    probe = textwrap.dedent(
        """
        import json
        import time

        from benchmarks.itc2007 import (
            ITC2007Course,
            ITC2007Problem,
            ITC2007Room,
            convert_itc2007_to_instance,
        )
        from core.itc2007_constructive import construct_itc2007_schedule
        from core.projected_time_search import (
            _ITCProjectedState,
            _run_projected_trajectory,
        )

        problem = ITC2007Problem(
            name="hash-seed-invariance",
            days=3,
            periods_per_day=3,
            courses=(
                ITC2007Course("C0", "T1", 1, 2, 10),
                ITC2007Course("C1", "T0", 3, 2, 29),
                ITC2007Course("C2", "T0", 2, 2, 16),
                ITC2007Course("C3", "T1", 1, 2, 50),
                ITC2007Course("C4", "T0", 2, 2, 24),
                ITC2007Course("C5", "T1", 3, 1, 41),
                ITC2007Course("C6", "T1", 3, 1, 42),
            ),
            rooms=(
                ITC2007Room("R0", 20),
                ITC2007Room("R1", 45),
                ITC2007Room("R2", 60),
            ),
            curricula={
                "Q0": ("C4", "C5"),
                "Q1": ("C3", "C5"),
                "Q2": ("C2", "C3"),
            },
            unavailability=(),
        )
        inst = convert_itc2007_to_instance(problem)
        constructed = construct_itc2007_schedule(
            inst,
            deadline=time.perf_counter() + 2.0,
            seed=13,
            beam_width=4,
            bundle_limit=2,
        )
        assert constructed.schedule is not None
        state = _ITCProjectedState(inst, constructed.schedule, seed=17)
        candidate_trace = []
        for _index in range(4):
            candidates = state.candidate_moves(limit=16)
            candidate_trace.append(
                [
                    [
                        str(family),
                        sorted(
                            [int(activity_id), int(period)]
                            for activity_id, period in move.items()
                        ),
                    ]
                    for move, family in candidates
                ]
            )
            if candidates:
                state.apply(candidates[0][0])
        trajectory = _run_projected_trajectory(
            inst,
            constructed.schedule,
            deadline=time.perf_counter() + 5.0,
            seed=17,
            candidate_batch_size=16,
            start_index=0,
            start_kind="incumbent",
            trajectory_mode="late_acceptance",
            global_started=time.perf_counter(),
            iteration_limit=24,
        )
        print(
            "HASH_PROBE="
            + json.dumps(
                {
                    "candidate_trace": candidate_trace,
                    "best_score": trajectory.best_score,
                    "best_assignment": sorted(trajectory.best_assignment.items()),
                    "iterations": trajectory.iterations,
                    "accepted_moves": trajectory.accepted_moves,
                    "accepted_by_family": sorted(
                        trajectory.accepted_by_family.items()
                    ),
                    "termination_reason": trajectory.termination_reason,
                    "iteration_limit": trajectory.iteration_limit,
                },
                sort_keys=True,
            )
        )
        """
    )

    outputs = []
    for hash_seed in ("0", "91"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hash_seed
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=os.getcwd(),
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        marker = next(
            line
            for line in completed.stdout.splitlines()
            if line.startswith("HASH_PROBE=")
        )
        outputs.append(json.loads(marker.removeprefix("HASH_PROBE=")))

    assert outputs[0] == outputs[1]
    assert outputs[0]["iteration_limit"] == 24
    assert outputs[0]["iterations"] <= 24


def test_fixed_iteration_checkpoint_and_expired_deadline_are_fail_safe() -> None:
    inst = _multistart_fixture()
    incumbent = _construct(inst, seed=13).schedule
    assert incumbent is not None

    bounded = _run_projected_trajectory(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        candidate_batch_size=8,
        start_index=0,
        start_kind="incumbent",
        trajectory_mode="late_acceptance",
        global_started=time.perf_counter(),
        iteration_limit=3,
    )
    expired = _run_projected_trajectory(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
        seed=17,
        candidate_batch_size=8,
        start_index=0,
        start_kind="incumbent",
        trajectory_mode="late_acceptance",
        global_started=time.perf_counter(),
        iteration_limit=3,
    )

    assert bounded.iterations <= 3
    assert bounded.iteration_limit == 3
    assert bounded.completed is True
    assert expired.iterations == 0
    assert expired.termination_reason == "deadline"
    assert expired.best_assignment == _ITCProjectedState(
        inst, incumbent, seed=17
    ).assignment
    assert expired.completed is False
    assert not (
        expired.iteration_limit is not None
        and expired.iterations >= expired.iteration_limit
    )
    assert _projected_trajectory_iteration_checkpoint(
        activity_count=256,
        trajectory_mode="long_horizon",
    ) is None
    assert _projected_trajectory_iteration_checkpoint(
        activity_count=257,
        trajectory_mode="long_horizon",
    ) == 600
    assert _projected_trajectory_iteration_checkpoint(
        activity_count=10_000,
        trajectory_mode="long_horizon",
    ) == 600
    assert _projected_trajectory_iteration_checkpoint(
        activity_count=257,
        trajectory_mode="late_acceptance",
    ) == 64
    assert _projected_trajectory_iteration_checkpoint(
        activity_count=257,
        trajectory_mode="late_acceptance",
        lossless_itc2007=False,
    ) is None


def test_dense_lossless_policy_adapts_only_the_service_default_batch(
    monkeypatch,
) -> None:
    inst = _instance(
        name="dense-lossless-search-policy",
        days=5,
        periods_per_day=5,
        courses=(ITC2007Course("A", "TA", 257, 5, 10),),
        room_capacities=tuple(20 for _index in range(11)),
    )
    activity = inst.activities[1]
    schedule = {
        activity_id: {
            "week": 1,
            "day": inst.days[
                ((activity_id - 1) // inst.slots_per_day) % len(inst.days)
            ],
            "slot": (activity_id - 1) % inst.slots_per_day,
            "duration": 1,
            "room_id": 1,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
        for activity_id in inst.activities
    }
    monkeypatch.setattr(
        "core.projected_time_search._default_validator",
        lambda _inst, _schedule: [],
    )
    observed: list[int] = []

    def trajectory(_inst, _schedule, **kwargs):
        observed.append(int(kwargs["candidate_batch_size"]))
        state = _ITCProjectedState(_inst, _schedule, seed=kwargs["seed"])
        return _ProjectedTrajectoryResult(
            start_index=kwargs["start_index"],
            start_kind=kwargs["start_kind"],
            trajectory_mode=kwargs["trajectory_mode"],
            seed=kwargs["seed"],
            start_score=state.score,
            start_stability_proxy=state.stability_proxy,
            best_score=state.score,
            best_stability_proxy=state.stability_proxy,
            best_assignment=dict(state.assignment),
            elite_assignments={
                tuple(sorted(state.assignment.items())): (
                    state.score,
                    dict(state.assignment),
                )
            },
            iterations=0,
            candidates_evaluated=0,
            accepted_moves=0,
            accepted_by_family=Counter(),
            trace=[],
            elapsed_seconds=0.0,
            termination_reason="test",
            completed=True,
            iteration_limit=kwargs["iteration_limit"],
        )

    monkeypatch.setattr(
        "core.projected_time_search._run_projected_trajectory",
        trajectory,
    )
    monkeypatch.setattr(
        "core.projected_time_search.score_itc2007_instance_schedule",
        lambda _inst, _schedule: type("Score", (), {"total": 0})(),
    )

    defaulted = optimize_projected_times(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        candidate_batch_size=32,
        adapt_dense_default_batch=True,
        multi_start_count=1,
        enable_constructive_start=False,
    )
    explicit = optimize_projected_times(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        candidate_batch_size=40,
        multi_start_count=1,
        enable_constructive_start=False,
    )
    inst.sla_targets["translation"] = "Enriched local model"
    nonlossless = optimize_projected_times(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        candidate_batch_size=32,
        multi_start_count=1,
        enable_constructive_start=False,
    )

    assert observed[:2] == [24, 40]
    assert defaulted.room_screening["search_policy"] == {
        "requested_candidate_batch_size": 32,
        "effective_candidate_batch_size": 24,
        "dense_lossless_policy": True,
        "adapt_dense_default_batch": True,
        "trajectory_iteration_checkpoints": {"late_acceptance": 64},
    }
    assert explicit.room_screening["search_policy"][
        "effective_candidate_batch_size"
    ] == 40
    assert explicit.room_screening["search_policy"][
        "adapt_dense_default_batch"
    ] is False
    assert nonlossless.status == "no_improvement"
    assert observed == [24, 40, 32]
    assert nonlossless.start_telemetry[0]["iteration_limit"] is None
    assert nonlossless.room_screening["search_policy"][
        "dense_lossless_policy"
    ] is False


def test_expired_deadlines_preserve_the_incumbent_and_return_no_partial() -> None:
    inst = _multistart_fixture()
    incumbent = _construct(inst, seed=13).schedule
    assert incumbent is not None
    incumbent_score = score_itc2007_instance_schedule(inst, incumbent).total
    expired = time.perf_counter() - 0.001

    projected = optimize_projected_times(
        inst,
        incumbent,
        deadline=expired,
        seed=17,
        multi_start_count=3,
    )
    constructed = construct_itc2007_schedule(
        inst,
        deadline=expired,
        seed=17,
    )

    assert projected.status == "deadline_exhausted"
    assert projected.schedule == incumbent
    assert projected.final_score == incumbent_score
    assert projected.starts_completed == 0
    assert projected.deadline_exhausted is True
    assert constructed.status == "deadline_exhausted"
    assert constructed.schedule is None
    assert constructed.assigned_activities == 0


def test_research_profile_uses_validated_constructor_before_cp(monkeypatch) -> None:
    inst = _multistart_fixture()
    captured: dict[str, tuple[str, ...]] = {}
    real_constructor = solver_service.construct_itc2007_schedule

    def observed_constructor(*args, **kwargs):
        captured["strategies"] = tuple(kwargs["strategies"])
        return real_constructor(*args, **kwargs)

    def unexpected_cp(*_args, **_kwargs):
        raise AssertionError("the native constructor should avoid the initial CP solve")

    monkeypatch.setattr(solver_service, "_run_solve_attempt", unexpected_cp)
    monkeypatch.setattr(
        solver_service,
        "construct_itc2007_schedule",
        observed_constructor,
    )
    monkeypatch.setattr(
        solver_service,
        "_run_adaptive_lns",
        lambda _inst, schedule, _options, **_kwargs: (
            schedule,
            {
                "enabled": True,
                "status": "TEST_BYPASS",
                "returned_source": "projected_time_search",
            },
        ),
    )

    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=5.0,
            workers=1,
            random_seed=17,
            projected_time_search=True,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.is_feasible
    assert validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []
    assert len(result.attempts) == 1
    assert result.attempts[0].room_mode == "itc2007_course_constructive"
    research = result.meta["research_adaptive"]
    assert research["returned_source"] == "projected_time_search"
    assert research["constructive_initializer"]["feasible"] is True
    assert captured["strategies"] == ("balanced",)
    assert research["constructive_initializer_policy"] == {
        "requested_strategy": "balanced",
        "effective_strategy": "balanced",
        "reason": "small_lossless_itc2007_balanced_default",
        "applied": False,
        "activity_count": len(inst.activities),
        "large_activity_threshold": 256,
        "lossless_import_eligible": True,
        "eligibility_reasons": [],
    }


def test_large_lossless_itc2007_constructor_policy_uses_day_spread_only() -> None:
    large = _instance(
        name="large-lossless-constructor-policy",
        days=5,
        periods_per_day=5,
        courses=(ITC2007Course("A", "TA", 257, 5, 10),),
        room_capacities=(20,),
    )

    selected = solver_service._itc2007_constructive_initializer_strategy_policy(
        large,
        activity_count=len(large.activities),
        requested_strategy="balanced",
    )
    large.sla_targets["translation"] = "Enriched local model"
    rejected = solver_service._itc2007_constructive_initializer_strategy_policy(
        large,
        activity_count=len(large.activities),
        requested_strategy="balanced",
    )

    assert selected["effective_strategy"] == "spread"
    assert selected["reason"] == "large_lossless_itc2007_day_spread"
    assert selected["applied"] is True
    assert selected["lossless_import_eligible"] is True
    assert rejected["effective_strategy"] == "balanced"
    assert rejected["reason"] == "requires_lossless_itc2007_import"
    assert rejected["applied"] is False
    assert rejected["lossless_import_eligible"] is False
    assert "requires_lossless_itc2007_import" in rejected["eligibility_reasons"]
