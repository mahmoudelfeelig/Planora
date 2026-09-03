from __future__ import annotations

import copy
import time

import pytest

import core.itc2007_room_stability_dispatcher as dispatcher
from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    canonicalize_itc2007_schedule,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_stability_ejection import (
    StabilityEjectionResult,
    StabilityEjectionTelemetry,
)
from core.itc2007_room_stability_dispatcher import (
    optimize_itc2007_room_stability,
)


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="room-stability-dispatcher",
            days=1,
            periods_per_day=6,
            courses=(ITC2007Course("A", "TA", 6, 1, 10),),
            rooms=tuple(ITC2007Room(f"R{index}", 20) for index in range(1, 7)),
            curricula={},
            unavailability=(),
        )
    )


def _schedule(instance) -> dict[int, dict]:
    output: dict[int, dict] = {}
    for slot, (activity_id, activity) in enumerate(sorted(instance.activities.items())):
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(slot + 1),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _room_result(instance, schedule):
    score = score_itc2007_instance_schedule(instance, schedule)
    return copy.deepcopy(schedule), {
        "cycles_requested": dispatcher.ROOM_POLISH_CYCLES,
        "cycles_completed": dispatcher.ROOM_POLISH_CYCLES,
        "final_score": int(score.total),
        "trace": [],
        "deadline_exhausted": False,
    }


def _stability_result(instance, schedule, candidate, *, seed, status="improved"):
    initial = score_itc2007_instance_schedule(instance, schedule)
    final = score_itc2007_instance_schedule(instance, candidate)
    improved = status == "improved"
    return StabilityEjectionResult(
        status=status,
        schedule=copy.deepcopy(candidate if improved else schedule),
        improved=improved,
        initial_score=initial,
        final_score=final if improved else initial,
        telemetry=StabilityEjectionTelemetry(seed=int(seed)),
    )


def _install_noop_room(monkeypatch) -> None:
    monkeypatch.setattr(
        dispatcher,
        "_polish_large_fixed_time_rooms",
        lambda instance, schedule, **_kwargs: _room_result(instance, schedule),
    )


def _install_terminal_stability(monkeypatch) -> None:
    def terminal(instance, schedule, *, seed, **_kwargs):
        return _stability_result(
            instance,
            schedule,
            schedule,
            seed=seed,
            status="no_improvement",
        )

    monkeypatch.setattr(dispatcher, "optimize_itc2007_stability_ejection", terminal)


def test_frozen_policy_recomputes_four_accepted_stability_passes(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)
    activity_ids = sorted(incumbent)
    room_calls: list[dict] = []
    stability_calls: list[tuple[dict, dict]] = []

    def room_polish(
        helper_instance,
        schedule,
        *,
        deadline,
        seed,
        validator,
        max_cycles,
    ):
        assert helper_instance is instance
        assert not validator(helper_instance, schedule)
        room_calls.append(
            {
                "schedule": copy.deepcopy(schedule),
                "deadline": float(deadline),
                "seed": int(seed),
                "max_cycles": int(max_cycles),
            }
        )
        candidate = copy.deepcopy(schedule)
        candidate[activity_ids[-1]]["room_id"] = 1
        return _room_result(instance, candidate)

    def stability(helper_instance, schedule, **kwargs):
        assert helper_instance is instance
        stability_calls.append((copy.deepcopy(schedule), dict(kwargs)))
        candidate = copy.deepcopy(schedule)
        remaining = [
            activity_id
            for activity_id in reversed(activity_ids)
            if int(candidate[activity_id]["room_id"]) != 1
        ]
        candidate[remaining[0]]["room_id"] = 1
        return _stability_result(
            instance,
            schedule,
            candidate,
            seed=int(kwargs["seed"]),
        )

    monkeypatch.setattr(dispatcher, "_polish_large_fixed_time_rooms", room_polish)
    monkeypatch.setattr(dispatcher, "optimize_itc2007_stability_ejection", stability)
    started = time.perf_counter()
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=started + 5.0,
        seed=17,
    )

    assert incumbent == original
    assert result.status == "improved"
    assert result.improved
    assert result.initial_score is not None and result.initial_score.total == 5
    assert result.final_score is not None and result.final_score.total == 0
    assert len(room_calls) == 1
    assert room_calls[0]["max_cycles"] == 3
    assert room_calls[0]["seed"] == 17
    assert room_calls[0]["deadline"] == pytest.approx(started + 1.5, abs=0.03)
    assert len(stability_calls) == 4
    for pass_index, (seen, kwargs) in enumerate(stability_calls):
        expected_support = 4 - pass_index
        assert score_itc2007_instance_schedule(instance, seen).total == expected_support
        assert kwargs["seed"] == 17 + pass_index * dispatcher.PASS_SEED_STRIDE
        assert kwargs["max_target_courses"] == 8
        assert kwargs["max_frontier_courses"] == 12
        assert kwargs["max_frontier_activities"] == 72
        assert kwargs["max_frontier_depth"] == 1
        assert kwargs["max_moved_activities"] == 14
        assert kwargs["max_seconds_per_target"] == pytest.approx(0.28)
        assert kwargs["completion_reserve_seconds"] == pytest.approx(0.075)
    assert result.telemetry.stability_passes_started == 4
    assert result.telemetry.stability_passes_accepted == 4
    assert [row["total"] for row in result.telemetry.score_trajectory] == [
        5,
        4,
        3,
        2,
        1,
        0,
    ]


def test_exchangeable_input_is_canonicalized_before_room_helper(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    first, second = sorted(incumbent)[:2]
    incumbent[first], incumbent[second] = incumbent[second], incumbent[first]
    expected = canonicalize_itc2007_schedule(instance, copy.deepcopy(incumbent))
    seen: list[dict] = []

    def room_polish(helper_instance, schedule, **_kwargs):
        seen.append(copy.deepcopy(schedule))
        return _room_result(helper_instance, schedule)

    monkeypatch.setattr(dispatcher, "_polish_large_fixed_time_rooms", room_polish)
    _install_terminal_stability(monkeypatch)
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert seen == [expected]
    assert result.status == "no_improvement"
    assert result.schedule == incumbent


def test_nonexchangeable_import_is_rejected_before_helpers(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    activity_ids = sorted(instance.activities)
    instance.precedence_rules = [
        {
            "before_activity_id": activity_ids[0],
            "after_activity_id": activity_ids[1],
            "min_gap_slots": 1,
        }
    ]
    helper_called = False

    def room_polish(*_args, **_kwargs):
        nonlocal helper_called
        helper_called = True
        raise AssertionError("ineligible schedule reached room helper")

    monkeypatch.setattr(dispatcher, "_polish_large_fixed_time_rooms", room_polish)
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
    )

    assert not helper_called
    assert result.status == "ineligible"
    assert result.schedule == incumbent
    assert "itc2007_lectures_not_exchangeable" in result.eligibility_reasons


def test_invalid_room_handoff_rolls_back_byte_exact_input(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)

    def invalid_room(helper_instance, schedule, **_kwargs):
        candidate = copy.deepcopy(schedule)
        del candidate[max(candidate)]
        return candidate, {
            "cycles_requested": 3,
            "cycles_completed": 3,
            "final_score": 0,
            "deadline_exhausted": False,
        }

    monkeypatch.setattr(dispatcher, "_polish_large_fixed_time_rooms", invalid_room)
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert incumbent == original
    assert not result.improved
    assert result.schedule == original
    assert result.status in {"error", "invalid_candidate"}


def test_each_mutating_helper_rolls_back(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)

    def mutating_room(helper_instance, schedule, **_kwargs):
        schedule[min(schedule)]["room_id"] = 6
        return _room_result(helper_instance, schedule)

    monkeypatch.setattr(dispatcher, "_polish_large_fixed_time_rooms", mutating_room)
    room_result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )
    assert room_result.status == "mutation_detected"
    assert room_result.schedule == original
    assert incumbent == original

    _install_noop_room(monkeypatch)

    def mutating_stability(helper_instance, schedule, *, seed, **_kwargs):
        schedule[min(schedule)]["room_id"] = 6
        return _stability_result(
            helper_instance,
            schedule,
            schedule,
            seed=seed,
            status="no_improvement",
        )

    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_stability_ejection",
        mutating_stability,
    )
    stability_result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )
    assert stability_result.status == "mutation_detected"
    assert stability_result.schedule == original
    assert incumbent == original


def test_mutating_validator_and_scorer_are_guarded(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)

    def mutating_validator(_instance, schedule):
        schedule[min(schedule)]["day"] = "MUTATED"
        return []

    validator_result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        validator=mutating_validator,
    )
    assert validator_result.status == "mutation_detected"
    assert validator_result.schedule == original

    official = score_itc2007_instance_schedule(instance, incumbent)

    def mutating_scorer(_instance, schedule):
        schedule[min(schedule)]["day"] = "MUTATED"
        return official

    scorer_result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        scorer=mutating_scorer,
    )
    assert scorer_result.status == "mutation_detected"
    assert scorer_result.schedule == original
    assert incumbent == original


@pytest.mark.parametrize(
    ("status", "improved", "overrun"),
    (("error", False, 0.0), ("improved", True, 0.001)),
)
def test_inconsistent_or_overrun_stability_result_rolls_back(
    monkeypatch,
    status,
    improved,
    overrun,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)
    activity_ids = sorted(incumbent)

    def improving_room(helper_instance, schedule, **_kwargs):
        candidate = copy.deepcopy(schedule)
        candidate[activity_ids[-1]]["room_id"] = 1
        return _room_result(helper_instance, candidate)

    def rejected_stability(helper_instance, schedule, *, seed, **_kwargs):
        candidate = copy.deepcopy(schedule)
        candidate[activity_ids[-2]]["room_id"] = 1
        result = _stability_result(
            helper_instance,
            schedule,
            candidate,
            seed=seed,
            status="improved" if improved else "no_improvement",
        )
        result.status = status
        result.deadline_overrun_seconds = float(overrun)
        return result

    monkeypatch.setattr(
        dispatcher,
        "_polish_large_fixed_time_rooms",
        improving_room,
    )
    monkeypatch.setattr(
        dispatcher,
        "optimize_itc2007_stability_ejection",
        rejected_stability,
    )
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.0,
    )

    assert result.status == "helper_rejected"
    assert not result.improved
    assert result.schedule == original


def test_final_deadline_crossing_discards_accepted_room_stage(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    original = copy.deepcopy(incumbent)
    activity_ids = sorted(incumbent)
    clock = [100.0]
    scorer_calls = [0]
    monkeypatch.setattr(dispatcher.time, "perf_counter", lambda: float(clock[0]))

    def improving_room(helper_instance, schedule, **_kwargs):
        candidate = copy.deepcopy(schedule)
        candidate[activity_ids[-1]]["room_id"] = 1
        return _room_result(helper_instance, candidate)

    def late_final_scorer(helper_instance, schedule):
        scorer_calls[0] += 1
        score = score_itc2007_instance_schedule(helper_instance, schedule)
        if scorer_calls[0] == 4:
            clock[0] = 105.01
        return score

    monkeypatch.setattr(
        dispatcher,
        "_polish_large_fixed_time_rooms",
        improving_room,
    )
    _install_terminal_stability(monkeypatch)
    result = optimize_itc2007_room_stability(
        instance,
        incumbent,
        deadline=105.0,
        scorer=late_final_scorer,
    )

    assert scorer_calls[0] == 4
    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert result.deadline_overrun_seconds > 0.0
    assert not result.improved
    assert result.schedule == original
