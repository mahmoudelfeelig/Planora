from __future__ import annotations

import copy
import time
from dataclasses import asdict

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core import itc2007_feedback_rooted_dispatcher as dispatcher
from core.itc2007_feedback_rooted_dispatcher import (
    FeedbackRootedBounds,
    optimize_itc2007_feedback_rooted,
)
from core.itc2007_iterative_feedback_dispatcher import (
    IterativeFeedbackResult,
    IterativeFeedbackTelemetry,
)
from core.itc2007_rooted_adjacency import (
    RootedAdjacencyResult,
    RootedAdjacencyTelemetry,
)
from utils.specs import validate_schedule_against_instance


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="feedback-rooted-policy",
            days=1,
            periods_per_day=3,
            courses=(ITC2007Course("A", "TA", 2, 1, 10),),
            rooms=(ITC2007Room("R1", 20), ITC2007Room("R2", 20)),
            curricula={},
            unavailability=(),
        )
    )


def _schedule(instance, *, stable: bool) -> dict[int, dict]:
    output: dict[int, dict] = {}
    for index, (activity_id, activity) in enumerate(
        sorted(instance.activities.items())
    ):
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(index),
            "duration": int(activity.duration),
            "room_id": 1 if stable or index == 0 else 2,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _iterative_result(
    instance,
    incumbent,
    candidate,
    *,
    bounds,
    seed: int,
) -> IterativeFeedbackResult:
    initial = score_itc2007_instance_schedule(instance, incumbent)
    final = score_itc2007_instance_schedule(instance, candidate)
    improved = final.total < initial.total
    telemetry = IterativeFeedbackTelemetry(seed=int(seed), bounds=asdict(bounds))
    telemetry.feedback_rounds_completed = int(bounds.feedback_rounds)
    telemetry.feedback_rounds_accepted = 1 if improved else 0
    for round_index in range(int(bounds.feedback_rounds)):
        telemetry.round_trace.append(
            {
                "round": round_index + 1,
                "iterations": int(bounds.feedback_iterations_per_round),
                "iteration_quota": int(bounds.feedback_iterations_per_round),
                "termination_reason": "iteration_checkpoint",
                "checkpoint_complete": True,
                "status": "accepted" if improved and round_index == 0 else "rejected",
            }
        )
    for phase, quota in (
        ("time", int(bounds.time_rooted_relocations)),
        ("components", int(bounds.component_rooted_relocations)),
    ):
        if quota:
            telemetry.relocation_trace.append(
                {
                    "phase": phase,
                    "status": "local_optimum",
                    "move": 1,
                    "quota": quota,
                }
            )
        telemetry.relocation_trace.append(
            {
                "phase": phase,
                "status": "checkpoint",
                "quota": quota,
                "completed_moves": 0,
            }
        )
    return IterativeFeedbackResult(
        status="improved" if improved else "no_improvement",
        schedule=copy.deepcopy(candidate),
        improved=bool(improved),
        initial_score=initial,
        final_score=final,
        telemetry=telemetry,
    )


def _rooted_result(
    instance,
    incumbent,
    candidate,
    *,
    seed: int,
) -> RootedAdjacencyResult:
    initial = score_itc2007_instance_schedule(instance, incumbent)
    final = score_itc2007_instance_schedule(instance, candidate)
    improved = final.total < initial.total
    telemetry = RootedAdjacencyTelemetry(seed=int(seed))
    telemetry.termination_reason = "rooted_local_optimum"
    telemetry.iteration_trace.append({"status": "local_optimum"})
    return RootedAdjacencyResult(
        status="improved" if improved else "no_improvement",
        schedule=copy.deepcopy(candidate),
        improved=bool(improved),
        initial_score=initial,
        final_score=final,
        telemetry=telemetry,
    )


def _install_success_stages(monkeypatch, instance, improved):
    iterative_calls: list[dict] = []
    rooted_calls: list[dict] = []

    def iterative(_instance, schedule, **kwargs):
        iterative_calls.append(
            {"schedule": copy.deepcopy(schedule), **copy.deepcopy(kwargs)}
        )
        candidate = improved if len(iterative_calls) == 1 else schedule
        return _iterative_result(
            instance,
            schedule,
            candidate,
            bounds=kwargs["bounds"],
            seed=kwargs["seed"],
        )

    def rooted(_instance, schedule, **kwargs):
        rooted_calls.append(
            {"schedule": copy.deepcopy(schedule), **copy.deepcopy(kwargs)}
        )
        return _rooted_result(
            instance,
            schedule,
            schedule,
            seed=kwargs["seed"],
        )

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_iterative_feedback",
        iterative,
    )
    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_rooted_adjacency",
        rooted,
    )
    return iterative_calls, rooted_calls


def test_fixed_policy_uses_shared_deadline_partitions_and_seed_namespaces(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    improved = _schedule(instance, stable=True)
    original = copy.deepcopy(incumbent)
    iterative_calls, rooted_calls = _install_success_stages(
        monkeypatch,
        instance,
        improved,
    )
    bounds = FeedbackRootedBounds()
    deadline = time.perf_counter() + 2.0

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=deadline,
        seed=23,
        bounds=bounds,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None
    assert result.final_score.room_stability == 0
    assert result.schedule == dispatcher.canonicalize_itc2007_schedule(
        instance,
        improved,
    )
    assert incumbent == original
    assert len(iterative_calls) == 2
    initial = iterative_calls[0]
    post = iterative_calls[1]
    assert initial["deadline"] == deadline - 0.50
    assert initial["seed"] == 23
    assert initial["bounds"].feedback_rounds == 4
    assert initial["bounds"].feedback_iterations_per_round == 32
    assert initial["bounds"].time_rooted_relocations == 2
    assert initial["bounds"].component_rooted_relocations == 2
    assert initial["bounds"].stability_collision_weight == 1
    assert initial["bounds"].stability_proxy_mode == "collision_events"
    assert post["deadline"] == deadline - 0.16
    assert post["seed"] == 23 + 5 * 65_537
    assert post["bounds"].feedback_rounds == 1
    assert post["bounds"].time_rooted_relocations == 0
    assert post["bounds"].component_rooted_relocations == 0
    assert post["bounds"].stability_collision_weight == 1
    assert post["bounds"].stability_proxy_mode == "collision_events"
    assert len(rooted_calls) == 1
    assert rooted_calls[0]["deadline"] == deadline - 0.02
    assert rooted_calls[0]["max_moves"] == 8
    assert rooted_calls[0]["coordinate_room_sweeps"] == 4
    assert rooted_calls[0]["completion_reserve_seconds"] == 0.08
    assert result.telemetry.validation_calls == 6
    assert result.telemetry.independent_rescores == 6
    assert [stage["status"] for stage in result.telemetry.stages] == [
        "accepted",
        "no_improvement",
        "no_improvement",
    ]
    assert not validate_schedule_against_instance(
        instance,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_incomplete_feedback_checkpoint_rolls_back_the_exact_incumbent(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    improved = _schedule(instance, stable=True)
    original = copy.deepcopy(incumbent)

    def incomplete(_instance, schedule, **kwargs):
        result = _iterative_result(
            instance,
            schedule,
            improved,
            bounds=kwargs["bounds"],
            seed=kwargs["seed"],
        )
        result.telemetry.feedback_rounds_completed -= 1
        return result

    rooted_called = False

    def rooted(*_args, **_kwargs):
        nonlocal rooted_called
        rooted_called = True
        raise AssertionError("rooted stage must not run")

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_iterative_feedback",
        incomplete,
    )
    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_rooted_adjacency",
        rooted,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert result.status == "incomplete_checkpoint"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert not rooted_called


def test_incomplete_rooted_checkpoint_discards_prior_stage_gains(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    improved = _schedule(instance, stable=True)
    original = copy.deepcopy(incumbent)
    _install_success_stages(monkeypatch, instance, improved)

    def incomplete_rooted(_instance, schedule, **kwargs):
        result = _rooted_result(
            instance,
            schedule,
            schedule,
            seed=kwargs["seed"],
        )
        result.telemetry.termination_reason = "checkpoint_reserve_reached"
        result.telemetry.iteration_trace = [{"status": "not_started_reserve"}]
        return result

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_rooted_adjacency",
        incomplete_rooted,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert result.status == "incomplete_checkpoint"
    assert result.error == "rooted_adjacency:rooted_incomplete_checkpoint"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert [stage["status"] for stage in result.telemetry.stages] == [
        "accepted",
        "no_improvement",
        "incomplete_checkpoint",
    ]


def test_mutating_helper_rolls_back_without_exposing_its_candidate(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    original = copy.deepcopy(incumbent)

    def mutating_helper(_instance, schedule, **_kwargs):
        schedule[min(schedule)]["room_id"] = 2
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_iterative_feedback",
        mutating_helper,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert result.status == "mutation_detected"
    assert result.error == "initial_feedback_and_relocation:helper_mutated_incumbent"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.mutation_guard_failures == 1


def test_mutating_helper_validator_is_detected_inside_the_stage(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    original = copy.deepcopy(incumbent)
    validator_calls = 0

    def validator(_instance, schedule):
        nonlocal validator_calls
        validator_calls += 1
        if validator_calls == 3:
            schedule[min(schedule)]["room_id"] = 2
        return ()

    def invokes_validator(_instance, schedule, **kwargs):
        validation_input = copy.deepcopy(schedule)
        kwargs["validator"](instance, validation_input)
        return _iterative_result(
            instance,
            schedule,
            schedule,
            bounds=kwargs["bounds"],
            seed=kwargs["seed"],
        )

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_iterative_feedback",
        invokes_validator,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        validator=validator,
    )

    assert result.status == "mutation_detected"
    assert result.error == "initial_feedback_and_relocation:validator_mutated_candidate"
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.mutation_guard_failures == 1


def test_mutating_official_scorer_rolls_back_the_exact_incumbent(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    original = copy.deepcopy(incumbent)
    official = score_itc2007_instance_schedule(instance, incumbent)

    def mutating_scorer(_instance, schedule):
        schedule[min(schedule)]["room_id"] = 2
        return official

    monkeypatch.setattr(
        dispatcher,
        "score_itc2007_instance_schedule",
        mutating_scorer,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert result.status == "mutation_detected"
    assert result.error == "incumbent:scorer_mutated_candidate"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.mutation_guard_failures == 1


def test_mutating_final_independent_rescore_discards_the_complete_chain(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    improved = _schedule(instance, stable=True)
    original = copy.deepcopy(incumbent)
    _install_success_stages(monkeypatch, instance, improved)
    real_scorer = dispatcher.score_itc2007_instance_schedule
    score_calls = 0

    def mutating_final_score(_instance, schedule):
        nonlocal score_calls
        score_calls += 1
        official = real_scorer(_instance, schedule)
        if score_calls == 6:
            schedule[min(schedule)]["room_id"] = 2
        return official

    monkeypatch.setattr(
        dispatcher,
        "score_itc2007_instance_schedule",
        mutating_final_score,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert score_calls == 6
    assert result.status == "mutation_detected"
    assert result.error == "final:scorer_mutated_candidate"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.mutation_guard_failures == 1


def test_expired_deadline_does_not_admit_or_run_any_stage(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("stage must not run")

    monkeypatch.setattr(
        dispatcher,
        "itc2007_iterative_feedback_eligibility",
        unexpected,
    )
    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_iterative_feedback",
        unexpected,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() - 0.001,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert not called
    assert result.telemetry.validation_calls == 0


def test_bounds_reject_non_monotone_tail_reserves_before_admission(
    monkeypatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance, stable=False)
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("eligibility must not run")

    monkeypatch.setattr(
        dispatcher,
        "itc2007_iterative_feedback_eligibility",
        unexpected,
    )
    bounds = FeedbackRootedBounds(
        initial_phase_tail_reserve_seconds=0.10,
        post_feedback_tail_reserve_seconds=0.20,
    )

    result = optimize_itc2007_feedback_rooted(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        bounds=bounds,
    )

    assert result.status == "ineligible"
    assert "reserves_not_monotone:tail" in result.eligibility_reasons
    assert not called
    assert result.schedule == incumbent


def test_bounds_forward_support_proxy_policy_and_reject_invalid_values() -> None:
    bounds = FeedbackRootedBounds(
        stability_collision_weight=3,
        stability_proxy_mode="fragmented_courses",
    )

    assert bounds.validation_errors() == ()
    assert bounds.initial_bounds().stability_collision_weight == 3
    assert bounds.initial_bounds().stability_proxy_mode == "fragmented_courses"
    assert bounds.post_bounds().stability_collision_weight == 3
    assert bounds.post_bounds().stability_proxy_mode == "fragmented_courses"
    assert "nonpositive_bound:stability_collision_weight" in (
        FeedbackRootedBounds(stability_collision_weight=0).validation_errors()
    )
    assert (
        "invalid_stability_proxy_mode"
        in FeedbackRootedBounds(stability_proxy_mode="unsupported").validation_errors()
    )


def test_source_policy_contains_no_benchmark_instance_or_comparator_target() -> None:
    source = dispatcher.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read().lower()
    assert "comp21" not in text
    assert "cpsolver" not in text
