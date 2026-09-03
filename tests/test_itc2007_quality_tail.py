from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks import itc2007
from benchmarks.itc2007 import ITC2007Score
from core import itc2007_quality_tail as quality_tail
from services import solver_service
from services.contracts import SolveOptions


@dataclass
class _HelperResult:
    schedule: dict[int, dict[str, Any]]
    status: str = "improved"
    improved: bool = True
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "improved": bool(self.improved),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
        }


def _schedule(
    total: int,
    *,
    capacity: int,
    stability: int,
    slot: int = 0,
    source: str = "incumbent",
) -> dict[int, dict[str, Any]]:
    return {
        0: {
            "score": int(total),
            "room_capacity": int(capacity),
            "minimum_working_days": 0,
            "curriculum_compactness": int(total - capacity - stability),
            "room_stability": int(stability),
            "week": 1,
            "day": "D0",
            "slot": int(slot),
            "duration": 1,
            "room_id": 1,
            "source": str(source),
        }
    }


def _component_schedule(
    total: int,
    *,
    capacity: int,
    mwd: int,
    compactness: int,
    stability: int,
    source: str,
) -> dict[int, dict[str, Any]]:
    schedule = _schedule(
        total,
        capacity=capacity,
        stability=stability,
        source=source,
    )
    schedule[0]["minimum_working_days"] = int(mwd)
    schedule[0]["curriculum_compactness"] = int(compactness)
    return schedule


def _score(_inst: Any, schedule: dict[int, dict[str, Any]]) -> ITC2007Score:
    row = schedule[0]
    return ITC2007Score(
        room_capacity=int(row["room_capacity"]),
        minimum_working_days=int(row["minimum_working_days"]),
        curriculum_compactness=int(row["curriculum_compactness"]),
        room_stability=int(row["room_stability"]),
        total=int(row["score"]),
    )


def _eligible(activity_count: int = 20) -> tuple[SimpleNamespace, Any]:
    inst = SimpleNamespace(
        activities={index: object() for index in range(activity_count)}
    )
    assessment = quality_tail.ITC2007QualityTailEligibility(
        eligible=True,
        activity_count=activity_count,
    )
    return inst, assessment


def test_quality_tail_runs_reserved_sequence_and_two_stability_gains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [100.0]
    calls: list[tuple[str, float, int, int]] = []
    stability_frontiers: list[tuple[int, int]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    def room(_inst, incumbent, *, deadline: float, seed: int):
        calls.append(("room", float(deadline), int(seed), incumbent[0]["score"]))
        clock[0] = 100.20
        return _HelperResult(_schedule(9, capacity=5, stability=2, source="room"))

    stability_outputs = iter(
        (
            _schedule(7, capacity=4, stability=1, slot=1, source="stability-1"),
            _schedule(6, capacity=4, stability=0, slot=2, source="stability-2"),
        )
    )

    def stability(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        call_index = sum(1 for name, *_rest in calls if name == "stability")
        calls.append(("stability", float(deadline), int(seed), incumbent[0]["score"]))
        stability_frontiers.append(
            (
                int(kwargs["max_frontier_courses"]),
                int(kwargs["max_frontier_activities"]),
            )
        )
        clock[0] = 100.60 + 0.20 * call_index
        return _HelperResult(next(stability_outputs))

    def capacity(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
        calls.append(("capacity", float(deadline), int(seed), incumbent[0]["score"]))
        clock[0] = 100.40
        return _HelperResult(_schedule(8, capacity=4, stability=2, source="capacity"))

    def compactness(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
        calls.append(("compactness", float(deadline), int(seed), incumbent[0]["score"]))
        clock[0] = 100.95
        return _HelperResult(
            _schedule(4, capacity=4, stability=0, source="compactness")
        )

    monkeypatch.setattr(quality_tail, "optimize_itc2007_fixed_time_rooms_cp", room)
    monkeypatch.setattr(quality_tail, "optimize_itc2007_stability_ejection", stability)
    monkeypatch.setattr(quality_tail, "optimize_itc2007_capacity_frontier", capacity)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_compactness_frontier",
        compactness,
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _schedule(10, capacity=5, stability=3),
        deadline=102.25,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None and result.final_score.total == 4
    assert result.accepted_source == "compactness_frontier"
    assert [name for name, *_rest in calls] == [
        "room",
        "capacity",
        "stability",
        "stability",
        "compactness",
    ]
    assert [
        deadline for _name, deadline, _seed, _score_value in calls
    ] == pytest.approx([100.75, 101.15, 100.95, 101.15, 102.25])
    assert [seed for _name, _deadline, seed, _score_value in calls] == [
        17,
        17,
        17,
        65_554,
        17,
    ]
    assert [score for _name, _deadline, _seed, score in calls] == [10, 9, 8, 7, 6]
    assert stability_frontiers == [(8, 52), (8, 52)]
    assert [row["total"] for row in result.telemetry.component_trajectory] == [
        10,
        9,
        8,
        7,
        6,
        4,
    ]
    assert result.telemetry.validation_calls == 6
    assert result.telemetry.independent_rescores == 6
    assert result.deadline_overrun_seconds == 0.0


def test_quality_tail_runs_rooted_then_compactness_alternation_when_window_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [100.0]
    calls: list[tuple[str, float, int]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    def rooted(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
        calls.append(("rooted", float(deadline), int(seed)))
        clock[0] = 100.25
        return _HelperResult(_schedule(8, capacity=4, stability=1, source="rooted"))

    def alternation(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(("alternation", float(deadline), int(seed)))
        assert kwargs["max_cycles"] == 1
        assert [stage.name for stage in kwargs["exact_frontiers"]] == [
            "compactness_frontier"
        ]
        clock[0] = 101.15
        return _HelperResult(
            _schedule(5, capacity=4, stability=1, source="alternation")
        )

    monkeypatch.setattr(quality_tail, "optimize_itc2007_rooted_adjacency", rooted)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_frontier_alternation",
        alternation,
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_capacity_frontier",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_stability_ejection",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_compactness_frontier",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _schedule(10, capacity=5, stability=2),
        deadline=102.25,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.improved
    assert result.final_score is not None and result.final_score.total == 5
    assert calls == [
        ("rooted", pytest.approx(100.55), 17),
        ("alternation", pytest.approx(101.75), 17),
    ]
    assert result.telemetry.accepted_sources[:2] == [
        "rooted_adjacency",
        "frontier_alternation",
    ]


def test_mwd_capacity_pressure_runs_two_small_frontiers_around_rooted_descent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [100.0]
    calls: list[tuple[str, float, int, int, dict[str, Any]]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    mwd_outputs = iter(
        (
            _component_schedule(
                452,
                capacity=10,
                mwd=220,
                compactness=220,
                stability=2,
                source="mwd-1",
            ),
            _component_schedule(
                444,
                capacity=5,
                mwd=210,
                compactness=226,
                stability=3,
                source="mwd-2",
            ),
        )
    )

    def mwd(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(("mwd", float(deadline), int(seed), incumbent[0]["score"], kwargs))
        clock[0] += (
            0.25 if len([row for row in calls if row[0] == "mwd"]) == 1 else 0.50
        )
        return _HelperResult(next(mwd_outputs))

    def rooted(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(
            ("rooted", float(deadline), int(seed), incumbent[0]["score"], kwargs)
        )
        clock[0] += 0.20
        return _HelperResult(
            _component_schedule(
                446,
                capacity=5,
                mwd=220,
                compactness=219,
                stability=2,
                source="rooted",
            )
        )

    def compactness(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(
            (
                "compactness",
                float(deadline),
                int(seed),
                incumbent[0]["score"],
                kwargs,
            )
        )
        clock[0] = 101.70
        return _HelperResult(
            _component_schedule(
                440,
                capacity=0,
                mwd=210,
                compactness=228,
                stability=2,
                source="compactness",
            )
        )

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_mwd_conflict_frontier",
        mwd,
    )
    monkeypatch.setattr(quality_tail, "optimize_itc2007_rooted_adjacency", rooted)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_compactness_frontier",
        compactness,
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _component_schedule(
            459,
            capacity=10,
            mwd=225,
            compactness=222,
            stability=2,
            source="incumbent",
        ),
        deadline=102.25,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.improved
    assert result.final_score is not None and result.final_score.total == 440
    assert [row[0] for row in calls] == ["mwd", "rooted", "mwd", "compactness"]
    assert [row[2] for row in calls] == [17, 104_746, 209_475, 314_204]
    assert [row[3] for row in calls] == [459, 452, 446, 444]
    assert calls[0][4]["max_frontier_courses"] == 7
    assert calls[0][4]["max_frontier_activities"] == 21
    assert calls[2][4]["max_frontier_courses"] == 7
    assert calls[3][4]["max_seconds_per_target"] == pytest.approx(0.38)
    assert result.deadline_overrun_seconds == 0.0


def test_mwd_without_capacity_polishes_before_wider_conflict_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [200.0]
    calls: list[tuple[str, float, int, int, dict[str, Any]]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    def polish(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(
            ("polish", float(deadline), int(seed), incumbent[0]["score"], kwargs)
        )
        clock[0] = 200.50
        return _HelperResult(
            _component_schedule(
                138,
                capacity=0,
                mwd=90,
                compactness=46,
                stability=2,
                source="polish",
            )
        )

    def mwd(_inst, incumbent, *, deadline: float, seed: int, **kwargs):
        calls.append(("mwd", float(deadline), int(seed), incumbent[0]["score"], kwargs))
        clock[0] = 202.20
        return _HelperResult(
            _component_schedule(
                128,
                capacity=0,
                mwd=85,
                compactness=42,
                stability=1,
                source="mwd",
            )
        )

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_frontier_alternation",
        polish,
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_mwd_conflict_frontier",
        mwd,
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _component_schedule(
            143,
            capacity=0,
            mwd=90,
            compactness=52,
            stability=1,
            source="incumbent",
        ),
        deadline=202.25,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.improved
    assert result.final_score is not None and result.final_score.total == 128
    assert [row[0] for row in calls] == ["polish", "mwd"]
    assert calls[0][4]["exact_frontiers"] == ()
    assert calls[0][4]["max_polish_passes_per_stage"] == 2
    assert calls[1][4]["max_frontier_courses"] == 14
    assert calls[1][4]["max_frontier_activities"] == 48
    assert calls[1][4]["max_seconds_per_target"] == pytest.approx(0.45)
    assert result.deadline_overrun_seconds == 0.0


def test_only_room_cp_requires_fixed_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)
    stability_inputs: list[dict[int, dict[str, Any]]] = []

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda *_args, **_kwargs: _HelperResult(
            _schedule(2, capacity=1, stability=0, slot=1, source="moved-room")
        ),
    )

    def stability(_inst, incumbent, **_kwargs):
        stability_inputs.append(incumbent)
        return _HelperResult(
            _schedule(1, capacity=1, stability=0, slot=1, source="stability")
        )

    monkeypatch.setattr(quality_tail, "optimize_itc2007_stability_ejection", stability)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_capacity_frontier",
        lambda *_args, **_kwargs: _HelperResult(
            dict(_args[1]), status="no_improvement", improved=False
        ),
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _schedule(3, capacity=1, stability=1),
        deadline=quality_tail.time.perf_counter() + 2.25,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.improved
    assert result.schedule[0]["slot"] == 1
    assert stability_inputs[0][0]["slot"] == 0
    room_stage = next(
        stage
        for stage in result.telemetry.stages
        if stage["name"] == "fixed_time_room_cp"
    )
    capacity_stage = next(
        stage
        for stage in result.telemetry.stages
        if stage["name"] == "capacity_frontier"
    )
    stability_stage = next(
        stage
        for stage in result.telemetry.stages
        if stage["name"] == "stability_ejection_1"
    )
    assert room_stage["status"] == "rejected_fixed_starts_changed"
    assert capacity_stage["status"] == "no_strict_improvement"
    assert stability_stage["status"] == "improved"
    assert stability_stage["fixed_starts_required"] is False


def test_capacity_handoff_preserves_an_exact_minimum_stability_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [100.0]
    deadline = 101.25
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    def room(_inst, incumbent, *, deadline: float, **_kwargs):
        calls.append(("room", float(deadline)))
        return _HelperResult(
            incumbent,
            status="no_improvement",
            improved=False,
        )

    def capacity(_inst, _incumbent, *, deadline: float, **_kwargs):
        calls.append(("capacity", float(deadline)))
        clock[0] = 100.85
        return _HelperResult(_schedule(1, capacity=0, stability=1, source="capacity"))

    def stability(_inst, _incumbent, *, deadline: float, **_kwargs):
        calls.append(("stability", float(deadline)))
        clock[0] = 100.95
        return _HelperResult(
            _schedule(0, capacity=0, stability=0, slot=1, source="stability")
        )

    monkeypatch.setattr(quality_tail, "optimize_itc2007_fixed_time_rooms_cp", room)
    monkeypatch.setattr(quality_tail, "optimize_itc2007_capacity_frontier", capacity)
    monkeypatch.setattr(quality_tail, "optimize_itc2007_stability_ejection", stability)

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _schedule(2, capacity=1, stability=1),
        deadline=deadline,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.improved
    assert result.final_score is not None and result.final_score.total == 0
    assert [name for name, _boundary in calls] == [
        "room",
        "capacity",
        "stability",
    ]
    assert calls[1][1] == pytest.approx(100.45)
    assert deadline - clock[0] > 0.0
    assert result.telemetry.stages[2]["effective_deadline_seconds"] == pytest.approx(
        deadline
    )


def test_compactness_runs_last_with_reserved_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [300.0]
    deadline = 302.25
    calls: list[tuple[str, float, int, int]] = []
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)

    def unchanged(name: str, finished: float):
        def helper(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
            calls.append((name, float(deadline), int(seed), incumbent[0]["score"]))
            clock[0] = finished
            return _HelperResult(
                incumbent,
                status="no_improvement",
                improved=False,
            )

        return helper

    def compactness(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
        calls.append(("compactness", float(deadline), int(seed), incumbent[0]["score"]))
        clock[0] = 301.40
        return _HelperResult(
            _schedule(6, capacity=4, stability=2, source="compactness")
        )

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_fixed_time_rooms_cp",
        unchanged("room", 300.20),
    )
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_capacity_frontier",
        unchanged("capacity", 300.40),
    )
    stability_calls = iter(
        (
            _HelperResult(_schedule(9, capacity=4, stability=3, source="stability-1")),
            _HelperResult(_schedule(8, capacity=4, stability=2, source="stability-2")),
        )
    )

    def stability(_inst, incumbent, *, deadline: float, seed: int, **_kwargs):
        calls.append(("stability", float(deadline), int(seed), incumbent[0]["score"]))
        clock[0] += 0.20
        return next(stability_calls)

    monkeypatch.setattr(quality_tail, "optimize_itc2007_stability_ejection", stability)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_compactness_frontier",
        compactness,
    )

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        _schedule(10, capacity=4, stability=4),
        deadline=deadline,
        seed=17,
        validator=lambda *_args: [],
    )

    assert result.final_score is not None and result.final_score.total == 6
    assert result.accepted_source == "compactness_frontier"
    assert [name for name, *_rest in calls] == [
        "room",
        "capacity",
        "stability",
        "stability",
        "compactness",
    ]
    assert calls[0][1] == pytest.approx(300.75)
    assert calls[1][1] == pytest.approx(301.15)
    assert calls[2][1] == pytest.approx(300.95)
    assert calls[3][1] == pytest.approx(301.15)
    assert calls[4][1] == pytest.approx(deadline)
    assert result.telemetry.stages[-1]["name"] == "compactness_frontier"
    assert result.telemetry.stages[-1]["accepted"] is True


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        ("equal", "rejected_not_strictly_better"),
        ("late", "rejected_helper_deadline_overrun"),
        ("exhausted", "rejected_helper_deadline_exhausted"),
        ("error", "error"),
    ],
)
def test_compactness_stage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
) -> None:
    inst, assessment = _eligible()
    clock = [400.0]
    deadline = 402.25
    monkeypatch.setattr(quality_tail.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )

    def compactness(_inst, incumbent, **_kwargs):
        if mode == "error":
            raise RuntimeError("synthetic helper failure")
        if mode == "late":
            clock[0] = deadline + 0.001
        candidate = (
            _schedule(2, capacity=0, stability=0, slot=1, source=mode)
            if mode != "equal"
            else copy_schedule(incumbent)
        )
        return _HelperResult(
            candidate,
            deadline_exhausted=mode == "exhausted",
        )

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_compactness_frontier",
        compactness,
    )
    incumbent = _schedule(3, capacity=0, stability=0)

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        incumbent,
        deadline=deadline,
        validator=lambda *_args: [],
    )

    assert result.improved is False
    assert result.schedule == incumbent
    assert result.telemetry.stages[-1]["name"] == "compactness_frontier"
    assert result.telemetry.stages[-1]["status"] == expected_status


def copy_schedule(schedule: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {activity_id: dict(row) for activity_id, row in schedule.items()}


def test_rejected_mutating_helper_cannot_corrupt_returned_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    monkeypatch.setattr(
        quality_tail,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(quality_tail, "score_itc2007_instance_schedule", _score)
    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda _inst, incumbent, **_kwargs: _HelperResult(
            incumbent, status="no_improvement", improved=False
        ),
    )

    def mutate_then_reject(_inst, incumbent, **_kwargs):
        incumbent[0]["slot"] = 99
        return _HelperResult(incumbent, status="no_improvement", improved=False)

    monkeypatch.setattr(
        quality_tail,
        "optimize_itc2007_stability_ejection",
        mutate_then_reject,
    )
    incumbent = _schedule(1, capacity=0, stability=1)

    result = quality_tail.optimize_itc2007_quality_tail(
        inst,
        incumbent,
        deadline=quality_tail.time.perf_counter() + 2.25,
        validator=lambda *_args: [],
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.schedule[0]["slot"] == 0
    assert [stage["name"] for stage in result.telemetry.stages][-2:] == [
        "fixed_time_room_cp",
        "stability_ejection_1",
    ]


def test_quality_tail_eligibility_rejects_large_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, _assessment = _eligible(activity_count=201)
    monkeypatch.setattr(
        quality_tail,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )

    assessment = quality_tail.itc2007_quality_tail_eligibility(inst, {})

    assert not assessment.eligible
    assert assessment.reasons == ("activity_limit_exceeded",)


def test_service_reserves_quality_tail_and_does_not_stack_old_tails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, assessment = _eligible()
    clock = [100.0]
    calls: dict[str, Any] = {}
    monkeypatch.setattr(solver_service.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        solver_service,
        "projected_time_search_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(
        solver_service,
        "validate_schedule_against_instance",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        solver_service,
        "_adaptive_acceptance_score",
        lambda _inst, schedule: (int(schedule[0]["score"]), "itc2007_official"),
    )
    monkeypatch.setattr(itc2007, "score_itc2007_instance_schedule", _score)

    def projected(*_args, deadline: float, **_kwargs):
        calls["projected_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return SimpleNamespace(
            schedule=_schedule(9, capacity=5, stability=2, source="projected"),
            to_dict=lambda: {"status": "improved"},
        )

    def tail(_inst, incumbent, *, deadline: float, seed: int):
        calls["tail_input"] = incumbent
        calls["tail_deadline"] = float(deadline)
        calls["tail_seed"] = int(seed)
        clock[0] = float(deadline) - 0.05
        return SimpleNamespace(
            schedule=_schedule(5, capacity=4, stability=0, source="quality-tail"),
            status="improved",
            improved=True,
            deadline_overrun_seconds=0.0,
            to_dict=lambda: {
                "status": "improved",
                "improved": True,
                "accepted_source": "capacity_frontier",
                "telemetry": {
                    "component_trajectory": [
                        {"source": "capacity_frontier", "total": 5}
                    ]
                },
            },
        )

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_quality_tail", tail)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_compound",
        lambda *_args, **_kwargs: pytest.fail(
            "compound must not stack before quality tail"
        ),
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda *_args, **_kwargs: pytest.fail(
            "standalone room CP must be inside quality tail"
        ),
    )

    returned, meta = solver_service._run_adaptive_lns(
        inst,
        _schedule(10, capacity=5, stability=3),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
            random_seed=17,
        ),
    )

    phase = meta["phase_timing"]
    assert returned == _schedule(5, capacity=4, stability=0, source="quality-tail")
    assert calls["tail_input"] == _schedule(
        9, capacity=5, stability=2, source="projected"
    )
    assert calls["tail_seed"] == 17
    assert calls["projected_deadline"] == pytest.approx(102.65)
    assert calls["tail_deadline"] == pytest.approx(104.90)
    assert phase["projected_time_search"][
        "reserved_for_quality_tail_seconds"
    ] == pytest.approx(2.30)
    assert phase["itc2007_quality_tail"]["reserved_budget_seconds"] == pytest.approx(
        2.30
    )
    assert phase["itc2007_quality_tail"][
        "service_validation_reserve_seconds"
    ] == pytest.approx(0.05)
    assert meta["itc2007_compound_search"]["reason"] == (
        "superseded_by_coordinated_quality_tail"
    )
    assert meta["itc2007_fixed_time_room_cp"]["status"] == "skipped_unreserved"
    assert meta["itc2007_quality_tail"]["service_acceptance"]["accepted"] is True
    assert meta["returned_source"] == "itc2007_quality_tail"


@pytest.mark.parametrize(
    ("mode", "candidate_score", "deadline_exhausted", "expected_reason"),
    [
        ("equal", 9, False, "candidate_not_strictly_better"),
        ("worse", 12, False, "candidate_not_strictly_better"),
        ("late", 1, False, "quality_tail_search_deadline_overrun"),
        ("exhausted", 1, True, "quality_tail_helper_deadline_exhausted"),
    ],
)
def test_service_quality_tail_rejects_equal_worse_and_late_candidates(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    candidate_score: int,
    deadline_exhausted: bool,
    expected_reason: str,
) -> None:
    inst, assessment = _eligible()
    clock = [200.0]
    monkeypatch.setattr(solver_service.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        solver_service,
        "projected_time_search_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda *_args, **_kwargs: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_quality_tail_eligibility",
        lambda *_args, **_kwargs: assessment,
    )
    monkeypatch.setattr(
        solver_service,
        "validate_schedule_against_instance",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        solver_service,
        "_adaptive_acceptance_score",
        lambda _inst, schedule: (int(schedule[0]["score"]), "itc2007_official"),
    )
    monkeypatch.setattr(itc2007, "score_itc2007_instance_schedule", _score)

    def projected(*_args, deadline: float, **_kwargs):
        clock[0] = float(deadline) - 0.01
        return SimpleNamespace(
            schedule=_schedule(9, capacity=5, stability=2, source="projected"),
            to_dict=lambda: {"status": "improved"},
        )

    def tail(*_args, deadline: float, **_kwargs):
        clock[0] = float(deadline) + (0.001 if mode == "late" else -0.05)
        return SimpleNamespace(
            schedule=_schedule(
                candidate_score,
                capacity=max(0, candidate_score - 1),
                stability=1,
                source=f"quality-{mode}",
            ),
            status="improved",
            improved=True,
            deadline_exhausted=bool(deadline_exhausted),
            deadline_overrun_seconds=0.0,
            to_dict=lambda: {"status": "improved", "improved": True},
        )

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_quality_tail", tail)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_compound",
        lambda *_args, **_kwargs: pytest.fail("compound must remain superseded"),
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda *_args, **_kwargs: pytest.fail("room CP must remain superseded"),
    )

    returned, meta = solver_service._run_adaptive_lns(
        inst,
        _schedule(10, capacity=5, stability=3),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    acceptance = meta["itc2007_quality_tail"]["service_acceptance"]
    assert returned == _schedule(9, capacity=5, stability=2, source="projected")
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == expected_reason
    assert meta["returned_source"] == "projected_time_search"


def test_quality_tail_policy_preserves_projected_and_feedback_minimums() -> None:
    admitted = solver_service._projected_quality_tail_policy(
        activity_count=200,
        available_seconds=4.0,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )
    starved = solver_service._projected_quality_tail_policy(
        activity_count=200,
        available_seconds=3.12,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )
    large = solver_service._projected_quality_tail_policy(
        activity_count=201,
        available_seconds=10.0,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )

    assert admitted["reserved_seconds"] == pytest.approx(2.30)
    assert admitted["shared_search_minimum_seconds"] == pytest.approx(5 / 6)
    assert admitted["admission_required_seconds"] == pytest.approx(2.30 + 5 / 6)
    assert starved["reserved_seconds"] == 0.0
    assert starved["reason"] == "insufficient_shared_deadline"
    assert large["reserved_seconds"] == 0.0
    assert large["reason"] == "activity_limit_exceeded"
