from __future__ import annotations

import copy
import time

import pytest

import core.itc2007_mwd_conflict_frontier as frontier_module
from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_mwd_conflict_frontier import (
    MWDConflictRoot,
    optimize_itc2007_mwd_conflict_frontier,
)
from core.itc2007_stability_ejection import _ModelResult
from utils.specs import validate_schedule_against_instance


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="mwd-conflict-frontier",
            days=3,
            periods_per_day=2,
            courses=(
                ITC2007Course("A", "TA", 3, 3, 10),
                ITC2007Course("B", "TB", 1, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={},
            unavailability=(),
        )
    )


def _by_code(instance) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for activity_id, activity in instance.activities.items():
        code = str(instance.courses[int(activity.course_id)].code)
        grouped.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in grouped.items()}


def _schedule(instance, *, spread: bool = False) -> dict[int, dict]:
    by_code = _by_code(instance)
    a1, a2, a3 = by_code["A"]
    placement = (
        {
            a1: (0, 0, 1),
            a2: (1, 0, 1),
            a3: (2, 0, 1),
            by_code["B"][0]: (2, 1, 2),
        }
        if spread
        else {
            # Deliberately not start-ordered by synthetic lecture id. The
            # module must canonicalize its private working copy only.
            a1: (1, 0, 1),
            a2: (0, 1, 1),
            a3: (0, 0, 1),
            by_code["B"][0]: (2, 1, 2),
        }
    )
    output: dict[int, dict] = {}
    for activity_id, activity in instance.activities.items():
        day, slot, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": f"D{day}",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": f"original-{activity_id}",
        }
    return output


def _unchanged_model(self, _frontier, *, deadline: float, **_kwargs):
    return _ModelResult(
        status="optimal",
        schedule=copy.deepcopy(self.schedule),
        model_score=5,
        solve_elapsed_seconds=0.0,
        solve_deadline=float(deadline),
    )


def test_root_priority_uses_stability_closure_and_screens_caps() -> None:
    plain = MWDConflictRoot(
        course_code="PLAIN",
        mwd_penalty=5,
        covered_stability_penalty=0,
        stability_repair_support=0,
        fragmented_courses=(),
        primary_rooms=(1,),
        conflict_courses=("P1", "P2"),
        frontier_courses=("P1", "P2", "PLAIN"),
        frontier_activity_count=9,
    )
    leveraged = MWDConflictRoot(
        course_code="LEVERAGED",
        mwd_penalty=5,
        covered_stability_penalty=1,
        stability_repair_support=4,
        fragmented_courses=("FRAGMENTED",),
        primary_rooms=(1,),
        conflict_courses=("F1", "F2", "FRAGMENTED"),
        frontier_courses=("F1", "F2", "FRAGMENTED", "LEVERAGED"),
        frontier_activity_count=12,
    )
    oversized = MWDConflictRoot(
        course_code="OVERSIZED",
        mwd_penalty=10,
        covered_stability_penalty=3,
        stability_repair_support=12,
        fragmented_courses=("FRAGMENTED",),
        primary_rooms=(1,),
        conflict_courses=tuple(f"X{index}" for index in range(14)),
        frontier_courses=tuple(f"X{index}" for index in range(15)),
        frontier_activity_count=45,
    )

    ordered = frontier_module._prioritize_roots(
        (plain, oversized, leveraged),
        max_frontier_courses=14,
        max_frontier_activities=48,
    )

    assert [root.course_code for root in ordered] == [
        "LEVERAGED",
        "PLAIN",
        "OVERSIZED",
    ]


@pytest.mark.parametrize("seed", [17, 31])
def test_exact_mwd_root_improves_official_total_without_mutating_input(
    seed: int,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    by_code = _by_code(instance)
    outside_id = by_code["B"][0]

    initial = score_itc2007_instance_schedule(instance, incumbent)
    assert initial.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 5,
        "curriculum_compactness": 0,
        "room_stability": 0,
        "total": 5,
    }

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=seed,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None
    assert result.final_score.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 0,
        "curriculum_compactness": 0,
        "room_stability": 0,
        "total": 0,
    }
    assert result.telemetry.accepted_candidates == 1
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 2
    assert result.telemetry.attempts[0]["score_parity"] is True
    assert result.telemetry.roots[0]["course_code"] == "A"
    assert result.schedule[outside_id] == before[outside_id]
    assert not validate_schedule_against_instance(
        instance,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert score_itc2007_instance_schedule(instance, result.schedule) == (
        result.final_score
    )
    assert incumbent == before


def test_no_mwd_deficit_returns_exact_incumbent_without_model() -> None:
    instance = _instance()
    incumbent = _schedule(instance, spread=True)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == before
    assert result.telemetry.models_solved == 0
    assert incumbent == before


def test_lossless_eligibility_and_canonicalization_fail_closed() -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    instance.sla_targets["translation"] = "Projected test translation"

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
    )

    assert result.status == "ineligible"
    assert not result.improved
    assert "requires_lossless_itc2007_import" in result.eligibility_reasons
    assert result.schedule == before
    assert result.telemetry.validation_calls == 0


def test_expired_deadline_returns_incumbent_without_validation() -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() - 0.001,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == before
    assert result.telemetry.validation_calls == 0
    assert incumbent == before


def test_invalid_incumbent_fails_closed_before_canonicalization() -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        validator=lambda *_args: ["synthetic invalid incumbent"],
    )

    assert result.status == "invalid_incumbent"
    assert result.validation_errors == ("synthetic invalid incumbent",)
    assert not result.improved
    assert result.schedule == before
    assert incumbent == before


def test_mutating_candidate_validator_discards_model_and_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    validation_calls = 0
    monkeypatch.setattr(
        frontier_module._State,
        "solve_frontier",
        _unchanged_model,
    )

    def mutate_second(_instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            candidate[min(candidate)]["slot"] = 99
        return []

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        validator=mutate_second,
    )

    assert result.status == "error"
    assert result.error == "candidate:validator_mutated_candidate"
    assert not result.improved
    assert result.schedule == before
    assert validation_calls == 2
    assert incumbent == before


def test_model_and_official_score_disagreement_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)

    def disagreement(self, _frontier, *, deadline: float, **_kwargs):
        return _ModelResult(
            status="optimal",
            schedule=copy.deepcopy(self.schedule),
            model_score=999,
            solve_elapsed_seconds=0.0,
            solve_deadline=float(deadline),
        )

    monkeypatch.setattr(
        frontier_module._State,
        "solve_frontier",
        disagreement,
    )
    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
    )

    assert result.status == "error"
    assert result.error == "model_official_score_disagreement"
    assert not result.improved
    assert result.schedule == before
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 2


def test_deadline_crossed_during_candidate_validation_discards_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    validation_calls = 0
    monkeypatch.setattr(
        frontier_module._State,
        "solve_frontier",
        _unchanged_model,
    )

    def slow_second(_instance, _candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            time.sleep(0.02)
        return []

    result = optimize_itc2007_mwd_conflict_frontier(
        instance,
        incumbent,
        deadline=time.perf_counter() + 0.01,
        validator=slow_second,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert result.deadline_overrun_seconds > 0.0
    assert not result.improved
    assert result.schedule == before
    assert validation_calls == 2
    assert incumbent == before
