from __future__ import annotations

import copy
import time

import pytest

import core.itc2007_compactness_frontier as compactness_module
from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_compactness_frontier import (
    CompactnessRoot,
    optimize_itc2007_compactness_frontier,
)
from core.itc2007_stability_ejection import _ModelResult
from utils.specs import validate_schedule_against_instance


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="curriculum-rooted-ejection-chain",
            days=1,
            periods_per_day=6,
            courses=(
                ITC2007Course("A", "TA", 2, 1, 10),
                ITC2007Course("B", "TB", 1, 1, 10),
                ITC2007Course("C", "TC", 1, 1, 10),
                ITC2007Course("D", "TD", 1, 1, 10),
                ITC2007Course("E", "TE", 1, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={"ROOT": ("A",)},
            unavailability=(),
        )
    )


def _by_code(inst) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        grouped.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in grouped.items()}


def _schedule(inst, *, adjacent: bool = False) -> dict[int, dict]:
    by_code = _by_code(inst)
    a1, a2 = by_code["A"]
    if adjacent:
        placement = {
            a1: 0,
            a2: 1,
            by_code["B"][0]: 2,
            by_code["C"][0]: 3,
            by_code["D"][0]: 4,
            by_code["E"][0]: 5,
        }
    else:
        placement = {
            a1: 0,
            by_code["B"][0]: 1,
            by_code["C"][0]: 2,
            by_code["D"][0]: 3,
            by_code["E"][0]: 4,
            a2: 5,
        }
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(placement[int(activity_id)]),
            "duration": int(activity.duration),
            "room_id": 1,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


@pytest.mark.parametrize("seed", [17, 23, 31])
def test_atomic_curriculum_rooted_chain_improves_exact_score(seed: int) -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)

    initial = score_itc2007_instance_schedule(inst, incumbent)
    assert initial.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 0,
        "curriculum_compactness": 4,
        "room_stability": 0,
        "total": 4,
    }

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=seed,
    )

    assert result.status == "improved"
    assert result.improved is True
    assert result.final_score is not None
    assert result.final_score.to_dict() == {
        "room_capacity": 0,
        "minimum_working_days": 0,
        "curriculum_compactness": 0,
        "room_stability": 0,
        "total": 0,
    }
    assert result.telemetry.independent_rescores == 1
    assert result.telemetry.accepted_candidates == 1
    assert result.telemetry.attempts[0]["score_parity"] is True
    assert len(result.telemetry.accepted_changes) >= 2
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert score_itc2007_instance_schedule(inst, result.schedule) == result.final_score
    assert incumbent == before


def test_returns_adjacent_incumbent_without_search_or_mutation() -> None:
    inst = _instance()
    incumbent = _schedule(inst, adjacent=True)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
    )

    assert result.status == "no_isolated_lectures"
    assert result.improved is False
    assert result.schedule == before
    assert incumbent == before
    assert result.telemetry.models_solved == 0


def test_expired_deadline_returns_incumbent_without_validation() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() - 1.0,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert result.improved is False
    assert result.deadline_exhausted is True
    assert result.schedule == before
    assert incumbent == before
    assert result.telemetry.validation_calls == 0


def test_invalid_incumbent_fails_closed() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        validator=lambda _inst, _schedule: ["synthetic invalid incumbent"],
    )

    assert result.status == "invalid_incumbent"
    assert result.improved is False
    assert result.validation_errors == ("synthetic invalid incumbent",)
    assert result.schedule == before
    assert incumbent == before


def test_rejected_candidate_is_not_returned() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)
    validation_calls = 0

    def validator(_inst, _schedule):
        nonlocal validation_calls
        validation_calls += 1
        return [] if validation_calls == 1 else ["candidate rejected"]

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_target_courses=1,
        validator=validator,
    )

    assert result.status == "no_improvement"
    assert result.improved is False
    assert result.schedule == before
    assert incumbent == before
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 0
    assert result.telemetry.attempts[0]["status"] == "invalid_candidate"


def test_equal_candidate_is_rejected_after_exact_rescore(monkeypatch) -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)

    def unchanged(self, _frontier, *, incumbent_score, deadline, **_kwargs):
        return _ModelResult(
            status="feasible",
            schedule=copy.deepcopy(self.schedule),
            model_score=int(incumbent_score.total),
            solve_elapsed_seconds=0.0,
            solve_deadline=float(deadline),
        )

    monkeypatch.setattr(compactness_module._State, "solve_frontier", unchanged)
    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_target_courses=1,
    )

    assert result.status == "no_improvement"
    assert result.improved is False
    assert result.schedule == before
    assert incumbent == before
    assert result.telemetry.independent_rescores == 1
    assert result.telemetry.attempts[0]["status"] == "no_strict_improvement"


def test_model_and_official_rescore_disagreement_fails_closed(monkeypatch) -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    before = copy.deepcopy(incumbent)
    real_solve = compactness_module._State.solve_frontier

    def disagree(self, frontier, **kwargs):
        result = real_solve(self, frontier, **kwargs)
        if result.schedule is not None and result.model_score is not None:
            result.model_score += 1
        return result

    monkeypatch.setattr(compactness_module._State, "solve_frontier", disagree)
    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_target_courses=1,
    )

    assert result.status == "error"
    assert result.error == "model_official_score_disagreement"
    assert result.improved is False
    assert result.schedule == before
    assert incumbent == before


def test_invalid_search_bounds_are_rejected_without_solver_work() -> None:
    inst = _instance()
    incumbent = _schedule(inst)

    result = optimize_itc2007_compactness_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        max_frontier_courses=0,
    )

    assert result.status == "ineligible"
    assert result.eligibility_reasons == ("search_bounds_must_be_positive",)
    assert result.telemetry.validation_calls == 0
    assert result.telemetry.models_solved == 0


def test_root_priority_prefers_surgical_high_density_repairs() -> None:
    broad = CompactnessRoot(
        course_code="A-broad",
        primary_room=1,
        room_support=(1,),
        isolated_activities=(1, 2),
        isolated_occurrences=2,
        affected_curricula=("BROAD",),
        affected_compactness_penalty=8,
        affected_lecture_count=8,
    )
    low_density = CompactnessRoot(
        course_code="A-low-density",
        primary_room=1,
        room_support=(1,),
        isolated_activities=(3,),
        isolated_occurrences=1,
        affected_curricula=("LOW",),
        affected_compactness_penalty=2,
        affected_lecture_count=8,
    )
    high_density = CompactnessRoot(
        course_code="Z-high-density",
        primary_room=1,
        room_support=(1,),
        isolated_activities=(4,),
        isolated_occurrences=1,
        affected_curricula=("HIGH",),
        affected_compactness_penalty=4,
        affected_lecture_count=10,
    )

    ordered = sorted(
        (broad, low_density, high_density),
        key=compactness_module._compactness_root_priority,
    )

    assert ordered == [high_density, low_density, broad]
