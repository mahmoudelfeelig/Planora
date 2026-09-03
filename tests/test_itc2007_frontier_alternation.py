from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    ITC2007Score,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core import itc2007_frontier_alternation as alternation
from utils.specs import validate_schedule_against_instance


@dataclass
class _ExactResult:
    schedule: dict[int, dict[str, Any]]
    improved: bool = True
    status: str = "improved"
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0


def _synthetic_schedule(
    total: int,
    *,
    compactness: int,
    stability: int,
    source: str,
) -> dict[int, dict[str, Any]]:
    return {
        0: {
            "score": int(total),
            "room_capacity": 0,
            "minimum_working_days": int(total - compactness - stability),
            "curriculum_compactness": int(compactness),
            "room_stability": int(stability),
            "source": str(source),
        }
    }


def _synthetic_score(
    _inst: Any,
    schedule: dict[int, dict[str, Any]],
) -> ITC2007Score:
    row = schedule[0]
    return ITC2007Score(
        room_capacity=int(row["room_capacity"]),
        minimum_working_days=int(row["minimum_working_days"]),
        curriculum_compactness=int(row["curriculum_compactness"]),
        room_stability=int(row["room_stability"]),
        total=int(row["score"]),
    )


def _synthetic_setup(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    instance = SimpleNamespace(activities={0: object()})
    monkeypatch.setattr(
        alternation,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        alternation,
        "score_itc2007_instance_schedule",
        _synthetic_score,
    )
    return instance


def _tradeoff_instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="relocate-tradeoff",
            days=1,
            periods_per_day=4,
            courses=(
                ITC2007Course("A", "TA", 2, 1, 10),
                ITC2007Course("B", "TB", 1, 1, 10),
                ITC2007Course("C", "TC", 1, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={"ROOT": ("A",)},
            unavailability=(),
        )
    )


def _by_code(instance) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for activity_id, activity in instance.activities.items():
        code = str(instance.courses[int(activity.course_id)].code)
        grouped.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in grouped.items()}


def _tradeoff_schedule(instance) -> dict[int, dict[str, Any]]:
    by_code = _by_code(instance)
    a1, a2 = by_code["A"]
    placement = {
        a1: (0, 1),
        by_code["B"][0]: (1, 1),
        by_code["C"][0]: (2, 1),
        a2: (3, 1),
    }
    schedule: dict[int, dict[str, Any]] = {}
    for activity_id, activity in instance.activities.items():
        slot, room_id = placement[int(activity_id)]
        schedule[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return schedule


def test_exact_frontier_then_polish_alternates_and_accepts_total_tradeoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _synthetic_setup(monkeypatch)
    incumbent = _synthetic_schedule(
        10,
        compactness=4,
        stability=1,
        source="incumbent",
    )
    exact_candidate = _synthetic_schedule(
        8,
        compactness=2,
        stability=1,
        source="exact",
    )
    polish_candidate = _synthetic_schedule(
        7,
        compactness=0,
        stability=2,
        source="polish",
    )
    calls: list[tuple[str, int]] = []

    def exact(_inst, schedule, **_kwargs):
        calls.append(("exact", int(schedule[0]["score"])))
        return _ExactResult(
            copy.deepcopy(exact_candidate),
            initial_score=_synthetic_score(instance, schedule),
            final_score=_synthetic_score(instance, exact_candidate),
        )

    def cheap(_inst, schedule, score, **_kwargs):
        calls.append(("polish", int(score.total)))
        if int(score.total) == 8:
            return alternation._CheapSearchBatch(
                candidates=(
                    alternation._CheapCandidate(
                        schedule=copy.deepcopy(polish_candidate),
                        predicted_score=_synthetic_score(instance, polish_candidate),
                        move={"kind": "relocate", "activity_id": 0},
                    ),
                ),
                relocate_checks=1,
                swap_checks=0,
                search_deadline_reached=False,
            )
        return alternation._CheapSearchBatch(
            candidates=(),
            relocate_checks=0,
            swap_checks=0,
            search_deadline_reached=False,
        )

    monkeypatch.setattr(alternation, "_find_relocate_swap_candidates", cheap)
    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        exact_frontiers=(
            alternation.ExactFrontierStage("synthetic_exact", exact, 0.2),
        ),
        max_cycles=1,
        max_polish_passes_per_stage=1,
        validator=lambda *_args: [],
    )

    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None
    assert result.final_score.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 5,
        "curriculum_compactness": 0,
        "room_stability": 2,
        "total": 7,
    }
    assert calls == [("polish", 10), ("exact", 10), ("polish", 8)]
    assert result.telemetry.accepted_sources == [
        "synthetic_exact",
        "relocate_swap_polish",
    ]
    assert [row["total"] for row in result.telemetry.component_trajectory] == [
        10,
        8,
        7,
    ]
    assert result.telemetry.validation_calls == 3
    assert result.telemetry.independent_rescores == 3
    assert incumbent[0]["source"] == "incumbent"


def test_real_relocate_accepts_compactness_gain_despite_stability_regression() -> None:
    instance = _tradeoff_instance()
    incumbent = _tradeoff_schedule(instance)
    before = copy.deepcopy(incumbent)
    initial_score = score_itc2007_instance_schedule(instance, incumbent)
    assert initial_score.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 0,
        "curriculum_compactness": 4,
        "room_stability": 0,
        "total": 4,
    }

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        exact_frontiers=(),
        max_cycles=1,
        max_polish_passes_per_stage=1,
        max_swap_checks=0,
    )

    assert result.status == "improved"
    assert result.final_score is not None
    assert result.final_score.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 0,
        "curriculum_compactness": 0,
        "room_stability": 1,
        "total": 1,
    }
    assert result.telemetry.stages[0]["accepted_move"]["kind"] == "relocate"
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


def test_real_swap_polish_is_supported_independently_of_relocation() -> None:
    instance = _tradeoff_instance()
    incumbent = _tradeoff_schedule(instance)

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        exact_frontiers=(),
        max_cycles=1,
        max_polish_passes_per_stage=1,
        max_relocate_checks=0,
    )

    assert result.improved
    assert result.final_score is not None and result.final_score.total == 0
    assert result.telemetry.stages[0]["accepted_move"]["kind"] == "swap"
    assert not validate_schedule_against_instance(
        instance,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_mutating_exact_helper_fails_closed_to_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _synthetic_setup(monkeypatch)
    incumbent = _synthetic_schedule(
        10,
        compactness=4,
        stability=1,
        source="incumbent",
    )
    before = copy.deepcopy(incumbent)

    def mutate(_inst, schedule, **_kwargs):
        schedule[0]["score"] = 1
        schedule[0]["source"] = "mutated"
        return _ExactResult(schedule)

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        exact_frontiers=(alternation.ExactFrontierStage("mutator", mutate, 0.2),),
        max_cycles=1,
        max_polish_passes_per_stage=0,
        validator=lambda *_args: [],
    )

    assert result.status == "error"
    assert not result.improved
    assert result.error == "mutator:helper_mutated_incumbent"
    assert result.schedule == before
    assert incumbent == before


def test_official_score_disagreement_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _synthetic_setup(monkeypatch)
    incumbent = _synthetic_schedule(
        10,
        compactness=4,
        stability=1,
        source="incumbent",
    )
    candidate = _synthetic_schedule(
        9,
        compactness=2,
        stability=1,
        source="candidate",
    )
    false_report = ITC2007Score(0, 0, 0, 0, 0)

    def disagree(_inst, schedule, **_kwargs):
        return _ExactResult(
            copy.deepcopy(candidate),
            initial_score=_synthetic_score(instance, schedule),
            final_score=false_report,
        )

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        exact_frontiers=(alternation.ExactFrontierStage("disagree", disagree, 0.2),),
        max_cycles=1,
        max_polish_passes_per_stage=0,
        validator=lambda *_args: [],
    )

    assert result.status == "error"
    assert not result.improved
    assert result.error == "disagree:helper_official_score_disagreement"
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 2


def test_late_exact_helper_candidate_is_rejected_without_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _synthetic_setup(monkeypatch)
    incumbent = _synthetic_schedule(
        10,
        compactness=4,
        stability=1,
        source="incumbent",
    )
    candidate = _synthetic_schedule(
        9,
        compactness=2,
        stability=1,
        source="candidate",
    )

    def late(_inst, schedule, **_kwargs):
        return _ExactResult(
            copy.deepcopy(candidate),
            initial_score=_synthetic_score(instance, schedule),
            final_score=_synthetic_score(instance, candidate),
            deadline_overrun_seconds=0.001,
        )

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        exact_frontiers=(alternation.ExactFrontierStage("late", late, 0.2),),
        max_cycles=1,
        max_polish_passes_per_stage=0,
        validator=lambda *_args: [],
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.stages[0]["status"] == "rejected_helper_deadline"
    assert result.telemetry.validation_calls == 1
    assert result.telemetry.independent_rescores == 1


def test_global_deadline_crossed_during_candidate_validation_discards_all_gains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _synthetic_setup(monkeypatch)
    incumbent = _synthetic_schedule(
        10,
        compactness=4,
        stability=1,
        source="incumbent",
    )
    candidate = _synthetic_schedule(
        9,
        compactness=2,
        stability=1,
        source="candidate",
    )
    clock = [100.0]
    validation_calls = 0
    monkeypatch.setattr(alternation.time, "perf_counter", lambda: float(clock[0]))

    def validator(_inst, _schedule):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            clock[0] = 101.001
        return []

    def exact(_inst, schedule, **_kwargs):
        return _ExactResult(
            copy.deepcopy(candidate),
            initial_score=_synthetic_score(instance, schedule),
            final_score=_synthetic_score(instance, candidate),
        )

    result = alternation.optimize_itc2007_frontier_alternation(
        instance,
        incumbent,
        deadline=101.0,
        exact_frontiers=(
            alternation.ExactFrontierStage("late_validation", exact, 0.5),
        ),
        max_cycles=1,
        max_polish_passes_per_stage=0,
        validator=validator,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert result.deadline_overrun_seconds == pytest.approx(0.001)
    assert not result.improved
    assert result.schedule == incumbent
    assert validation_calls == 2


def test_expired_deadline_returns_exact_incumbent_without_validation() -> None:
    instance = _tradeoff_instance()
    incumbent = _tradeoff_schedule(instance)
    before = copy.deepcopy(incumbent)

    result = alternation.optimize_itc2007_frontier_alternation(
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
