from __future__ import annotations

import copy
import time

import pytest

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    ITC2007Score,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core import itc2007_rooted_adjacency as rooted_adjacency
from core.itc2007_rooted_adjacency import (
    _rooted_target_periods,
    optimize_itc2007_rooted_adjacency,
)
from core.projected_time_search import _ITCProjectedState
from utils.specs import validate_schedule_against_instance


def _instance(
    *,
    days: int,
    periods_per_day: int,
    courses: tuple[ITC2007Course, ...],
    curricula: dict[str, tuple[str, ...]],
):
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="rooted-adjacency",
            days=int(days),
            periods_per_day=int(periods_per_day),
            courses=courses,
            rooms=(ITC2007Room("R1", 40), ITC2007Room("R2", 40)),
            curricula=curricula,
            unavailability=(),
        )
    )


def _schedule(inst, placements: dict[int, tuple[int, int, int]]):
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        day, slot, room_id = placements[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": f"D{int(day)}",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _compactness_case():
    inst = _instance(
        days=1,
        periods_per_day=4,
        courses=(
            ITC2007Course("A", "TA", 1, 1, 10),
            ITC2007Course("B", "TB", 1, 1, 10),
        ),
        curricula={"Q": ("A", "B")},
    )
    return inst, _schedule(inst, {1: (0, 0, 1), 2: (0, 3, 2)})


def test_rooted_targets_admit_a_curriculum_peer_next_to_isolation() -> None:
    inst, incumbent = _compactness_case()
    state = _ITCProjectedState(inst, incumbent, seed=17)

    targets = _rooted_target_periods(state)

    assert targets[1] == (1, 2)
    assert targets[2] == (1, 2)


def test_rooted_adjacency_returns_a_valid_strict_compactness_gain() -> None:
    inst, incumbent = _compactness_case()
    initial = score_itc2007_instance_schedule(inst, incumbent)

    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score == initial
    assert result.final_score is not None
    assert result.final_score.total == 0
    assert result.final_score.curriculum_compactness == 0
    assert result.telemetry.accepted_moves == 1
    assert result.telemetry.candidates_evaluated > 0
    assert result.telemetry.lift_status == "majority_aware_optimal_lift"
    assert result.telemetry.coordinate_status == "one_period_local_optimum"
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_exchangeable_lecture_ids_are_canonicalized_before_rooted_search() -> None:
    inst = _instance(
        days=2,
        periods_per_day=2,
        courses=(ITC2007Course("A", "TA", 2, 2, 10),),
        curricula={},
    )
    exchanged = _schedule(inst, {1: (0, 1, 2), 2: (0, 0, 1)})

    result = optimize_itc2007_rooted_adjacency(
        inst,
        exchanged,
        deadline=time.perf_counter() + 0.5,
        seed=17,
    )

    assert result.improved
    assert result.telemetry.canonicalized_input is True
    assert result.final_score is not None
    assert result.final_score.total == 0


def test_rooted_adjacency_repairs_a_missing_working_day() -> None:
    inst = _instance(
        days=2,
        periods_per_day=2,
        courses=(ITC2007Course("A", "TA", 2, 2, 10),),
        curricula={},
    )
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 1)})

    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert result.improved
    assert result.initial_score is not None
    assert result.initial_score.minimum_working_days == 5
    assert result.final_score is not None
    assert result.final_score.minimum_working_days == 0
    assert result.final_score.total == 0
    assert result.telemetry.trace[0]["time_delta"] == -5


def test_expired_deadline_returns_the_exact_incumbent() -> None:
    inst, incumbent = _compactness_case()

    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0


def test_room_lift_deadline_exhaustion_discards_an_improving_time_candidate(
    monkeypatch,
) -> None:
    inst, incumbent = _compactness_case()

    monkeypatch.setattr(
        "core.itc2007_rooted_adjacency._majority_aware_room_lift",
        lambda *_args, **_kwargs: (None, "deadline_exhausted"),
    )
    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.accepted_moves == 1


def test_nonlossless_room_domains_fail_closed_without_search() -> None:
    inst, incumbent = _compactness_case()
    enriched = copy.deepcopy(inst)
    enriched.rooms[1].availability = {("D0", 0)}

    result = optimize_itc2007_rooted_adjacency(
        enriched,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert result.status == "ineligible"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.candidates_evaluated == 0
    assert result.eligibility_reasons


def test_precedence_enriched_import_is_ineligible_before_rooted_search() -> None:
    inst, incumbent = _compactness_case()
    inst.precedence_rules = [
        {
            "before_activity_id": 1,
            "after_activity_id": 2,
            "min_gap_slots": 1,
        }
    ]

    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert result.status == "ineligible"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.candidates_evaluated == 0
    assert "itc2007_lectures_not_exchangeable" in result.eligibility_reasons


def test_unequal_activity_availability_is_ineligible_before_rooted_search() -> None:
    inst = _instance(
        days=2,
        periods_per_day=2,
        courses=(ITC2007Course("A", "TA", 2, 2, 10),),
        curricula={},
    )
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 1)})
    inst.activity_unavailability[1] = {("D1", 1)}

    result = optimize_itc2007_rooted_adjacency(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert result.status == "ineligible"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.candidates_evaluated == 0
    assert "itc2007_lectures_not_exchangeable" in result.eligibility_reasons


class _SlowClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return float(self.value)

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def _install_checkpoint_search_fakes(
    monkeypatch,
    clock: _SlowClock,
    *,
    scan_costs: tuple[float, ...],
) -> None:
    class _CheckpointState:
        def __init__(self, *_args, **_kwargs) -> None:
            self.assignment = {1: 0}
            self.course_code = {1: "A"}
            self.score = 10
            self.stability_proxy = 0
            self.use_stability_proxy = True

        def feasible(self, _move) -> bool:
            scan_index = min(
                len(scan_costs) - 1,
                max(0, 10 - int(self.score)),
            )
            clock.advance(float(scan_costs[scan_index]))
            return True

        def delta(self, _move) -> int:
            return -1

        def stability_proxy_delta(self, _move) -> int:
            return 0

        def apply(self, move) -> None:
            self.assignment.update(
                {int(key): int(value) for key, value in move.items()}
            )
            self.score -= 1

        def materialize(self):
            return {1: {"score": int(self.score)}}

    def score(_inst, schedule) -> ITC2007Score:
        total = int(schedule[1]["score"])
        return ITC2007Score(0, 0, 0, total, total)

    monkeypatch.setattr(rooted_adjacency.time, "perf_counter", clock.now)
    monkeypatch.setattr(rooted_adjacency, "_ITCProjectedState", _CheckpointState)
    monkeypatch.setattr(
        rooted_adjacency,
        "_rooted_target_periods",
        lambda state: (
            {1: tuple(int(state.assignment[1]) + offset for offset in (1, 2, 3))}
            if int(state.score) > 7
            else {}
        ),
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "canonicalize_itc2007_schedule",
        lambda _inst, schedule: copy.deepcopy(schedule),
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "_install_actual_majorities",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "_majority_aware_room_lift",
        lambda _inst, schedule, _rooms, **_kwargs: (
            copy.deepcopy(schedule),
            "majority_aware_optimal_lift",
        ),
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "_fast_coordinate_room_lift",
        lambda _inst, schedule, **_kwargs: (
            copy.deepcopy(schedule),
            "one_period_local_optimum",
        ),
    )
    monkeypatch.setattr(
        rooted_adjacency,
        "score_itc2007_instance_schedule",
        score,
    )


def test_root_scan_stops_before_an_iteration_that_cannot_fit_reserve(
    monkeypatch,
) -> None:
    clock = _SlowClock()
    _install_checkpoint_search_fakes(
        monkeypatch,
        clock,
        scan_costs=(0.01,),
    )
    incumbent = {1: {"score": 10}}

    result = optimize_itc2007_rooted_adjacency(
        object(),
        incumbent,
        deadline=0.14,
        completion_reserve_seconds=0.08,
        validator=lambda *_args: (),
    )

    assert result.improved
    assert result.final_score is not None
    assert result.final_score.total == 9
    assert result.telemetry.root_iterations_started == 2
    assert result.telemetry.root_iterations == 1
    assert result.telemetry.root_iterations_discarded == 0
    assert result.telemetry.candidates_evaluated == 3
    assert result.telemetry.completed_checkpoint_moves == 1
    assert [row["status"] for row in result.telemetry.iteration_trace] == [
        "accepted_checkpoint",
        "not_started_reserve",
    ]
    assert result.deadline_overrun_seconds == 0.0


def test_slow_completed_scan_is_discarded_at_the_previous_strict_checkpoint(
    monkeypatch,
) -> None:
    clock = _SlowClock()
    _install_checkpoint_search_fakes(
        monkeypatch,
        clock,
        scan_costs=(0.005, 0.04),
    )
    incumbent = {1: {"score": 10}}

    result = optimize_itc2007_rooted_adjacency(
        object(),
        incumbent,
        deadline=0.20,
        completion_reserve_seconds=0.08,
        validator=lambda *_args: (),
    )

    assert result.improved
    assert result.final_score is not None
    assert result.final_score.total == 9
    assert result.telemetry.root_iterations_started == 2
    assert result.telemetry.root_iterations == 2
    assert result.telemetry.root_iterations_discarded == 1
    assert result.telemetry.candidates_evaluated == 6
    assert result.telemetry.completed_checkpoint_moves == 1
    assert result.telemetry.iteration_trace[-1]["status"] == (
        "completed_not_applied_reserve"
    )
    assert result.telemetry.termination_reason == ("strict_official_improvement")
    assert result.deadline_overrun_seconds == 0.0


def test_root_scan_overrun_reports_consistent_deadline_exhaustion(monkeypatch) -> None:
    clock = _SlowClock()
    _install_checkpoint_search_fakes(
        monkeypatch,
        clock,
        scan_costs=(0.05,),
    )
    incumbent = {1: {"score": 10}}

    result = optimize_itc2007_rooted_adjacency(
        object(),
        incumbent,
        deadline=0.10,
        completion_reserve_seconds=0.08,
        validator=lambda *_args: (),
    )

    assert result.schedule == incumbent
    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted is True
    assert result.deadline_overrun_seconds == pytest.approx(0.05)
    assert result.telemetry.termination_reason == "completed_scan_reserve_reached"


def test_insufficient_window_reports_the_effective_completion_reserve(
    monkeypatch,
) -> None:
    clock = _SlowClock()
    _install_checkpoint_search_fakes(
        monkeypatch,
        clock,
        scan_costs=(0.01,),
    )

    result = optimize_itc2007_rooted_adjacency(
        object(),
        {1: {"score": 10}},
        deadline=0.04,
        completion_reserve_seconds=0.01,
        validator=lambda *_args: (),
    )

    assert result.status == "no_improvement"
    assert result.telemetry.termination_reason == "insufficient_completion_reserve"
    assert result.telemetry.timing["completion_reserve_seconds"] >= 0.08
