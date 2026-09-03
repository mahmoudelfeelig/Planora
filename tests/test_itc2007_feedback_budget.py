from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from services import solver_service
from services.contracts import SolveOptions


@dataclass
class _ProjectedResult:
    schedule: dict[int, dict[str, Any]]
    status: str = "improved"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status}


@dataclass
class _FeedbackResult:
    schedule: dict[int, dict[str, Any]]
    improved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "improved" if self.improved else "no_improvement",
            "improved": self.improved,
        }


@dataclass
class _CompoundResult:
    schedule: dict[int, dict[str, Any]]
    improved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "improved" if self.improved else "no_improvement",
            "improved": self.improved,
            "telemetry": {
                "best_trajectory": [{"atomic_step": 1}, {"atomic_step": 2}],
            },
        }


@dataclass
class _RootedResult:
    schedule: dict[int, dict[str, Any]]
    improved: bool = True
    status: str = "improved"
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "improved": bool(self.improved),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
        }


@dataclass(frozen=True)
class _OfficialScore:
    total: int

    def to_dict(self) -> dict[str, int]:
        return {
            "room_capacity": int(self.total),
            "minimum_working_days": 0,
            "curriculum_compactness": 0,
            "room_stability": 0,
            "total": int(self.total),
        }


@dataclass
class _RoomCPResult:
    schedule: dict[int, dict[str, Any]]
    status: str = "improved"
    improved: bool = True
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        score = int(self.schedule[0]["score"])
        components = _OfficialScore(score).to_dict()
        return {
            "status": str(self.status),
            "improved": bool(self.improved),
            "initial_score": None,
            "candidate_score": dict(components),
            "final_score": dict(components),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
        }


def _instance(activity_count: int) -> SimpleNamespace:
    return SimpleNamespace(
        activities={activity_id: object() for activity_id in range(activity_count)},
        sla_targets={},
        hard_constraints={},
    )


def _timed_schedule(
    score: int,
    *,
    slot: int = 0,
    room_id: int = 1,
    source: str | None = None,
) -> dict[int, dict[str, Any]]:
    row: dict[str, Any] = {
        "score": int(score),
        "week": 1,
        "day": "D0",
        "slot": int(slot),
        "duration": 1,
        "room_id": int(room_id),
    }
    if source is not None:
        row["source"] = str(source)
    return {0: row}


def _install_service_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    from benchmarks import itc2007

    monkeypatch.setattr(
        solver_service,
        "projected_time_search_eligibility",
        lambda _inst, _schedule: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_fixed_time_room_cp_eligibility",
        lambda _inst, _schedule: (True, ()),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_rooted_adjacency_eligibility",
        lambda _inst, schedule: SimpleNamespace(
            eligible=True,
            reasons=(),
            canonical_schedule={
                int(activity_id): dict(row) for activity_id, row in schedule.items()
            },
        ),
    )
    monkeypatch.setattr(
        solver_service,
        "validate_schedule_against_instance",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        solver_service,
        "_adaptive_acceptance_score",
        lambda _inst, schedule: (
            int(schedule[0]["score"]),
            "test_objective",
        ),
    )
    monkeypatch.setattr(
        itc2007,
        "score_itc2007_instance_schedule",
        lambda _inst, schedule: _OfficialScore(int(schedule[0]["score"])),
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_compound",
        lambda *_args, **_kwargs: _CompoundResult(
            dict(_args[1]),
            improved=False,
        ),
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda *_args, **_kwargs: _RoomCPResult(
            dict(_args[1]),
            status="no_improvement",
            improved=False,
        ),
    )


def test_feedback_reserve_uses_fraction_before_size_cap() -> None:
    small = solver_service._projected_feedback_phase_policy(
        activity_count=200,
        available_seconds=4.0,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=4,
    )
    large = solver_service._projected_feedback_phase_policy(
        activity_count=201,
        available_seconds=5.0,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=4,
    )

    assert small["reserved_seconds"] == pytest.approx(1.6)
    assert small["effective_rounds"] == 4
    assert large["reserved_seconds"] == pytest.approx(0.9)
    assert large["effective_rounds"] == 1


def test_compound_tail_policy_uses_small_and_large_safe_slices() -> None:
    small = solver_service._projected_compound_phase_policy(
        activity_count=200,
        available_seconds=4.0,
        eligible=True,
    )
    large = solver_service._projected_compound_phase_policy(
        activity_count=201,
        available_seconds=4.0,
        eligible=True,
    )
    starved = solver_service._projected_compound_phase_policy(
        activity_count=200,
        available_seconds=0.9,
        eligible=True,
    )

    assert small["reserved_seconds"] == pytest.approx(0.65)
    assert large["reserved_seconds"] == pytest.approx(0.35)
    assert starved["reserved_seconds"] == 0.0
    assert starved["reason"] == "insufficient_shared_deadline"


def test_rooted_adjacency_tail_policy_is_dense_lossless_and_caller_bounded() -> None:
    dense = solver_service._projected_rooted_adjacency_tail_policy(
        activity_count=257,
        available_seconds=5.0,
        exchangeable_eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=3,
    )
    boundary = solver_service._projected_rooted_adjacency_tail_policy(
        activity_count=256,
        available_seconds=5.0,
        exchangeable_eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=3,
    )
    nonlossless = solver_service._projected_rooted_adjacency_tail_policy(
        activity_count=257,
        available_seconds=5.0,
        exchangeable_eligible=False,
        eligibility_reasons=("itc2007_lectures_not_exchangeable",),
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=3,
    )
    one_round = solver_service._projected_rooted_adjacency_tail_policy(
        activity_count=257,
        available_seconds=5.0,
        exchangeable_eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=1,
    )
    two_rounds = solver_service._projected_rooted_adjacency_tail_policy(
        activity_count=257,
        available_seconds=5.0,
        exchangeable_eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=5.0,
        requested_feedback_rounds=2,
    )

    assert dense["enabled"] is True
    assert dense["reserved_seconds"] == pytest.approx(1.45)
    assert dense["continuation_feedback_rounds"] == 2
    assert two_rounds["enabled"] is True
    assert two_rounds["reserved_seconds"] == pytest.approx(1.10)
    assert two_rounds["continuation_feedback_rounds"] == 1
    assert boundary["enabled"] is False
    assert boundary["reason"] == "requires_more_than_256_activities"
    assert nonlossless["enabled"] is False
    assert nonlossless["reason"] == "itc2007_lectures_not_exchangeable"
    assert one_round["enabled"] is False
    assert one_round["reason"] == "additional_feedback_round_not_requested"


def test_room_cp_tail_policy_reserves_one_second_without_starving_upstream() -> None:
    reserved = solver_service._projected_room_cp_tail_policy(
        activity_count=200,
        available_seconds=4.0,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )
    starved = solver_service._projected_room_cp_tail_policy(
        activity_count=200,
        available_seconds=2.39,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )
    large = solver_service._projected_room_cp_tail_policy(
        activity_count=201,
        available_seconds=10.0,
        eligible=True,
        feedback_enabled=True,
        requested_feedback_seconds=2.0,
    )

    assert reserved["reserved_seconds"] == pytest.approx(1.0)
    assert reserved["projected_minimum_seconds"] == pytest.approx(0.50)
    assert reserved["feedback_minimum_seconds"] == pytest.approx(0.25)
    assert reserved["compound_minimum_seconds"] == pytest.approx(0.65)
    assert reserved["shared_search_minimum_seconds"] == pytest.approx(5 / 6)
    assert reserved["admission_required_seconds"] == pytest.approx(1.0 + 0.65 + (5 / 6))
    assert starved["reserved_seconds"] == 0.0
    assert starved["reason"] == "insufficient_shared_deadline"
    assert large["reserved_seconds"] == 0.0
    assert large["reason"] == "activity_limit_exceeded"


@pytest.mark.parametrize(
    ("activity_count", "expected_reserve", "expected_rounds"),
    [
        (200, 3.1, 3),
        (201, 1.6, 1),
    ],
)
def test_projected_search_reserves_feedback_tail_by_instance_size(
    monkeypatch: pytest.MonkeyPatch,
    activity_count: int,
    expected_reserve: float,
    expected_rounds: int,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [100.0]
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        calls["projected_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.05
        return _ProjectedResult({0: {"score": 9}})

    def feedback(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        max_feedback_rounds: int,
        run_consolidation: bool,
        **_kwargs: Any,
    ) -> _FeedbackResult:
        calls["feedback_deadline"] = float(deadline)
        calls["feedback_rounds"] = int(max_feedback_rounds)
        calls["run_consolidation"] = bool(run_consolidation)
        calls["stability_collision_weight"] = int(_kwargs["stability_collision_weight"])
        calls["stability_proxy_mode"] = str(_kwargs["stability_proxy_mode"])
        calls["feedback_input"] = schedule
        clock[0] = float(deadline) - 0.05
        return _FeedbackResult({0: {"score": 8}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(activity_count),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=10.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=5.0,
            projected_time_feedback_rounds=3,
            projected_time_stability_collision_weight=2,
            projected_time_stability_proxy_mode="fragmented_courses",
            random_seed=17,
        ),
        final_deadline=109.5,
    )

    phase = meta["phase_timing"]
    policy = phase["policy"]
    assert returned == {0: {"score": 8}}
    assert calls["feedback_input"] == {0: {"score": 9}}
    assert calls["projected_deadline"] < calls["feedback_deadline"]
    assert calls["projected_deadline"] == pytest.approx(
        phase["projected_time_search"]["actual_deadline_seconds"]
    )
    assert calls["feedback_deadline"] == pytest.approx(
        phase["itc2007_room_feedback"]["actual_deadline_seconds"]
    )
    assert policy["reserved_seconds"] == pytest.approx(expected_reserve)
    assert calls["feedback_rounds"] == expected_rounds
    assert calls["run_consolidation"] is True
    assert calls["stability_collision_weight"] == 2
    assert calls["stability_proxy_mode"] == "fragmented_courses"
    assert meta["itc2007_room_feedback"]["stability_collision_weight"] == 2
    assert meta["itc2007_room_feedback"]["stability_proxy_mode"] == (
        "fragmented_courses"
    )
    assert phase["adaptive"]["actual_deadline_seconds"] <= 109.45 + 1e-9
    assert phase["projected_time_search"]["elapsed_seconds"] >= 0.0
    assert phase["itc2007_room_feedback"]["elapsed_seconds"] >= 0.0
    assert meta["returned_source"] == "itc2007_room_feedback"
    assert meta["deadline_overrun_seconds"] == 0.0


def test_dense_lossless_service_runs_root_feedback_root_feedback_and_skips_compound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [100.0]
    calls: dict[str, Any] = {
        "feedback": [],
        "rooted": [],
    }
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        calls["projected_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.10
        return _ProjectedResult({0: {"score": 9}})

    def feedback(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        seed: int,
        max_feedback_rounds: int,
        **_kwargs: Any,
    ) -> _FeedbackResult:
        index = len(calls["feedback"])
        calls["feedback"].append(
            {
                "input": schedule,
                "deadline": float(deadline),
                "seed": int(seed),
                "rounds": int(max_feedback_rounds),
            }
        )
        clock[0] += 0.05
        return _FeedbackResult({0: {"score": (8, 6, 4)[index]}})

    def rooted(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        seed: int,
        **_kwargs: Any,
    ) -> _RootedResult:
        index = len(calls["rooted"])
        calls["rooted"].append(
            {
                "input": schedule,
                "deadline": float(deadline),
                "seed": int(seed),
                "completion_reserve_seconds": float(
                    _kwargs["completion_reserve_seconds"]
                ),
            }
        )
        clock[0] += 0.05
        return _RootedResult({0: {"score": 7 if index == 0 else 5}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_rooted_adjacency",
        rooted,
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_compound",
        lambda *_args, **_kwargs: pytest.fail(
            "dense rooted policy must replace the compound slice"
        ),
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(300),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=10.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=5.0,
            projected_time_feedback_rounds=3,
            random_seed=17,
        ),
        final_deadline=109.5,
    )

    assert returned == {0: {"score": 4}}
    assert [row["seed"] for row in calls["feedback"]] == [
        900_018,
        965_555,
        1_031_092,
    ]
    assert [row["rounds"] for row in calls["feedback"]] == [1, 1, 1]
    assert [row["seed"] for row in calls["rooted"]] == [
        1_850_018,
        1_850_019,
    ]
    assert calls["rooted"][0]["input"] == {0: {"score": 8}}
    assert calls["feedback"][1]["input"] == {0: {"score": 7}}
    assert calls["rooted"][1]["input"] == {0: {"score": 6}}
    assert calls["feedback"][2]["input"] == {0: {"score": 5}}
    tail = meta["itc2007_rooted_adjacency"]
    assert tail["status"] == "improved"
    assert [row["stage"] for row in tail["stages"]] == [
        "rooted_before_feedback",
        "feedback_continuation_round_2",
        "rooted_after_feedback",
        "feedback_continuation_round_3",
    ]
    assert tail["stages"][1]["deadline_seconds"] - calls["feedback"][1][
        "deadline"
    ] == pytest.approx(0.03)
    assert tail["stages"][2]["deadline_seconds"] - calls["rooted"][1][
        "deadline"
    ] == pytest.approx(0.02)
    assert tail["stages"][3]["deadline_seconds"] - calls["feedback"][2][
        "deadline"
    ] == pytest.approx(0.03)
    assert all(row["service_acceptance"]["accepted"] for row in tail["stages"])
    assert tail["service_acceptance"]["accepted"] is True
    assert tail["deadline_overrun_seconds"] == 0.0
    assert calls["rooted"][0]["deadline"] - tail["timing"][
        "started_at_seconds"
    ] == pytest.approx(0.50)
    assert calls["rooted"][0]["completion_reserve_seconds"] == pytest.approx(0.09)
    assert meta["phase_timing"]["policy"]["rooted_adjacency"][
        "reserved_seconds"
    ] == pytest.approx(1.45)
    assert meta["phase_timing"]["policy"]["compound"]["enabled"] is False
    assert meta["phase_timing"]["projected_time_search"][
        "reserved_for_rooted_adjacency_seconds"
    ] == pytest.approx(1.45)
    assert meta["returned_source"] == ("itc2007_rooted_feedback_continuation_round_3")
    assert meta["deadline_overrun_seconds"] == 0.0


def test_dense_nonexchangeable_service_preserves_the_compound_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [150.0]
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )
    monkeypatch.setattr(
        solver_service,
        "itc2007_rooted_adjacency_eligibility",
        lambda _inst, _schedule: SimpleNamespace(
            eligible=False,
            reasons=("itc2007_lectures_not_exchangeable",),
            canonical_schedule=None,
        ),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.10
        return _ProjectedResult({0: {"score": 9}})

    def feedback(*_args: Any, deadline: float, **_kwargs: Any) -> _FeedbackResult:
        clock[0] = float(deadline) - 0.05
        return _FeedbackResult({0: {"score": 8}})

    def compound(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        **_kwargs: Any,
    ) -> _CompoundResult:
        calls["compound_input"] = schedule
        calls["compound_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return _CompoundResult({0: {"score": 7}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_rooted_adjacency",
        lambda *_args, **_kwargs: pytest.fail(
            "nonexchangeable inputs must never enter rooted search"
        ),
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(300),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=10.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=5.0,
            projected_time_feedback_rounds=3,
        ),
        final_deadline=159.5,
    )

    rooted = meta["itc2007_rooted_adjacency"]
    compound_meta = meta["itc2007_compound_search"]
    assert returned == {0: {"score": 7}}
    assert calls["compound_input"] == {0: {"score": 8}}
    assert rooted["enabled"] is False
    assert rooted["reason"] == "itc2007_lectures_not_exchangeable"
    assert rooted["reserved_window_seconds"] == 0.0
    assert rooted["reservation_policy"]["eligibility_reasons"] == [
        "itc2007_lectures_not_exchangeable"
    ]
    assert compound_meta["enabled"] is True
    assert meta["phase_timing"]["policy"]["compound"]["reason"] != (
        "superseded_by_rooted_adjacency_tail"
    )


def test_outer_rooted_validation_overrun_is_merged_into_rooted_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [170.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.10
        return _ProjectedResult({0: {"score": 9}})

    def feedback(*_args: Any, deadline: float, **_kwargs: Any) -> _FeedbackResult:
        clock[0] = float(deadline) - 0.05
        return _FeedbackResult({0: {"score": 8}})

    def rooted_tail(*_args: Any, deadline: float, **_kwargs: Any):
        clock[0] = float(deadline) - 0.01
        return (
            {0: {"score": 7}},
            {
                "status": "improved",
                "service_acceptance": {"accepted": True},
                "deadline_exhausted": False,
                "deadline_overrun_seconds": 0.0,
            },
            "itc2007_rooted_adjacency",
        )

    original_admit = solver_service._admit_nonworsening_adaptive_candidate

    def slow_outer_admit(
        inst: Any,
        incumbent: dict[int, dict[str, Any]],
        candidate: dict[int, dict[str, Any]] | None,
        **kwargs: Any,
    ) -> Any:
        result = original_admit(inst, incumbent, candidate, **kwargs)
        if candidate and int(candidate[0]["score"]) == 7:
            clock[0] += 0.02
        return result

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)
    monkeypatch.setattr(
        solver_service,
        "_run_itc2007_rooted_adjacency_tail",
        rooted_tail,
    )
    monkeypatch.setattr(
        solver_service,
        "_admit_nonworsening_adaptive_candidate",
        slow_outer_admit,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(300),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=10.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=5.0,
            projected_time_feedback_rounds=3,
        ),
        final_deadline=179.5,
    )

    rooted = meta["itc2007_rooted_adjacency"]
    assert returned == {0: {"score": 8}}
    assert rooted["service_acceptance"]["reason"] == (
        "rooted_adjacency_service_validation_overrun"
    )
    assert rooted["deadline_exhausted"] is True
    assert rooted["deadline_overrun_seconds"] == pytest.approx(0.01)
    assert meta["phase_timing"]["itc2007_rooted_adjacency"][
        "deadline_overrun_seconds"
    ] == pytest.approx(0.01)


def test_dense_rooted_helper_deadline_exhaustion_reverts_the_whole_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [200.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.10
        return _ProjectedResult({0: {"score": 9}})

    def feedback(*_args: Any, **_kwargs: Any) -> _FeedbackResult:
        clock[0] += 0.05
        return _FeedbackResult({0: {"score": 8}})

    def exhausted_rooted(*_args: Any, **_kwargs: Any) -> _RootedResult:
        clock[0] += 0.05
        return _RootedResult(
            {0: {"score": 1}},
            improved=False,
            status="deadline_exhausted",
            deadline_exhausted=True,
        )

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_rooted_adjacency",
        exhausted_rooted,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(300),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=10.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=5.0,
            projected_time_feedback_rounds=3,
        ),
    )

    assert returned == {0: {"score": 8}}
    tail = meta["itc2007_rooted_adjacency"]
    assert tail["status"] == "rejected"
    assert tail["service_acceptance"]["accepted"] is False
    assert tail["service_acceptance"]["reason"] == (
        "rooted_adjacency_helper_deadline_exhausted"
    )
    assert tail["stages"][0]["service_acceptance"]["reason"] == (
        "stage_helper_deadline_exhausted"
    )
    assert meta["returned_source"] == "itc2007_room_feedback"


def test_rooted_tail_validation_overrun_reverts_the_whole_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [300.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def rooted(*_args: Any, **_kwargs: Any) -> _RootedResult:
        clock[0] = float(_kwargs["deadline"]) - 0.01
        return _RootedResult({0: {"score": 9}})

    original_admit = solver_service._admit_nonworsening_adaptive_candidate

    def slow_admit(*args: Any, **kwargs: Any) -> Any:
        result = original_admit(*args, **kwargs)
        clock[0] += 0.02
        return result

    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_rooted_adjacency",
        rooted,
    )
    monkeypatch.setattr(
        solver_service,
        "_admit_nonworsening_adaptive_candidate",
        slow_admit,
    )

    incumbent = {0: {"score": 10}}
    returned, meta, source = solver_service._run_itc2007_rooted_adjacency_tail(
        _instance(300),
        incumbent,
        deadline=301.10,
        seed=17,
        continuation_feedback_rounds=1,
    )

    assert returned == incumbent
    assert source is None
    assert meta["status"] == "deadline_rejected"
    assert meta["service_acceptance"]["accepted"] is False
    assert meta["service_acceptance"]["reason"] == ("phase_helper_deadline_exhausted")
    assert meta["stages"][0]["service_acceptance"]["reason"] == (
        "stage_service_validation_overrun"
    )


def test_rooted_tail_without_strict_gain_preserves_exact_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [400.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def rooted(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        **_kwargs: Any,
    ) -> _RootedResult:
        clock[0] += 0.01
        return _RootedResult(dict(schedule), improved=False, status="no_improvement")

    def feedback(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        **_kwargs: Any,
    ) -> _FeedbackResult:
        clock[0] += 0.01
        return _FeedbackResult(dict(schedule), improved=False)

    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_rooted_adjacency",
        rooted,
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_feedback",
        feedback,
    )

    incumbent = {0: {"score": 10, "marker": ["incumbent"]}}
    returned, meta, source = solver_service._run_itc2007_rooted_adjacency_tail(
        _instance(300),
        incumbent,
        deadline=401.45,
        seed=17,
        continuation_feedback_rounds=2,
    )

    assert returned == incumbent
    assert source is None
    assert meta["status"] == "no_improvement"
    assert meta["service_acceptance"]["accepted"] is False
    assert meta["service_acceptance"]["reason"] == ("candidate_not_strictly_better")
    assert len(meta["stages"]) == 4
    assert all(row["service_acceptance"]["accepted"] is False for row in meta["stages"])
    returned[0]["marker"].append("returned-mutation")
    assert incumbent[0]["marker"] == ["incumbent"]


def test_zero_feedback_budget_preserves_the_compound_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [40.0]
    calls: dict[str, float] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        calls["deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return _ProjectedResult({0: {"score": 9}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)

    def room_cp(*_args: Any, deadline: float, **_kwargs: Any) -> _RoomCPResult:
        calls["room_cp_deadline"] = float(deadline)
        return _RoomCPResult(
            dict(_args[1]),
            status="no_improvement",
            improved=False,
        )

    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        room_cp,
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_feedback",
        lambda *_args, **_kwargs: pytest.fail("zero-budget feedback must not run"),
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(50),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=4.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=0.0,
        ),
    )

    phase = meta["phase_timing"]
    assert returned == {0: {"score": 9}}
    assert calls["deadline"] == pytest.approx(42.30)
    assert phase["policy"]["reserved_seconds"] == 0.0
    assert phase["projected_time_search"]["reserved_budget_seconds"] == pytest.approx(
        2.30
    )
    assert phase["projected_time_search"][
        "reserved_for_compound_seconds"
    ] == pytest.approx(0.65)
    assert phase["itc2007_compound_search"]["reserved_budget_seconds"] == pytest.approx(
        0.65
    )
    assert phase["projected_time_search"][
        "reserved_for_room_cp_seconds"
    ] == pytest.approx(1.0)
    assert phase["itc2007_fixed_time_room_cp"][
        "reserved_budget_seconds"
    ] == pytest.approx(1.0)
    assert phase["itc2007_fixed_time_room_cp"][
        "reservation_start_deadline_seconds"
    ] == pytest.approx(42.95)
    assert phase["itc2007_compound_search"]["actual_deadline_seconds"] <= 42.95 + 1e-9
    assert (
        phase["itc2007_compound_search"]["actual_deadline_seconds"]
        - phase["itc2007_compound_search"]["started_at_seconds"]
        <= 0.65 + 1e-9
    )
    assert calls["room_cp_deadline"] == pytest.approx(43.90)
    assert phase["adaptive"]["service_completion_reserve_seconds"] == pytest.approx(
        0.05
    )
    assert phase["itc2007_room_feedback"]["actual_deadline_seconds"] is None
    assert meta["itc2007_room_feedback"]["status"] == "skipped_zero_budget"
    assert meta["deadline_overrun_seconds"] == 0.0


def test_exact_phase_deadlines_leave_service_completion_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [70.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline)
        return _ProjectedResult({0: {"score": 9}})

    def feedback(*_args: Any, deadline: float, **_kwargs: Any) -> _FeedbackResult:
        clock[0] = float(deadline)
        return _FeedbackResult({0: {"score": 8}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=2.0,
            projected_time_feedback_rounds=2,
        ),
    )

    phase = meta["phase_timing"]
    assert returned == {0: {"score": 8}}
    assert phase["adaptive"]["finished_at_seconds"] == pytest.approx(73.30)
    assert phase["adaptive"]["actual_deadline_seconds"] == pytest.approx(75.0)
    assert phase["adaptive"]["service_completion_reserve_seconds"] == pytest.approx(
        0.05
    )
    assert phase["projected_time_search"]["deadline_overrun_seconds"] == 0.0
    assert phase["itc2007_room_feedback"]["deadline_overrun_seconds"] == 0.0
    assert meta["deadline_overrun_seconds"] == 0.0


def test_feedback_candidate_is_rejected_when_it_worsens_projected_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [10.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.1
        return _ProjectedResult({0: {"score": 7}})

    def feedback(*_args: Any, deadline: float, **_kwargs: Any) -> _FeedbackResult:
        clock[0] = float(deadline) - 0.1
        return _FeedbackResult({0: {"score": 12}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=2.0,
            projected_time_feedback_rounds=2,
        ),
    )

    assert returned == {0: {"score": 7}}
    acceptance = meta["itc2007_room_feedback"]["service_acceptance"]
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == "candidate_worsened_objective"
    assert meta["returned_source"] == "projected_time_search"
    assert meta["status"] == "improved"
    assert meta["deadline_overrun_seconds"] == 0.0


def test_compound_runs_after_feedback_and_accepts_only_strict_improvement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [10.0]
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        calls["projected_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return _ProjectedResult({0: {"score": 9}})

    def feedback(*_args: Any, deadline: float, **_kwargs: Any) -> _FeedbackResult:
        calls["feedback_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return _FeedbackResult({0: {"score": 8}})

    def compound(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        **_kwargs: Any,
    ) -> _CompoundResult:
        calls["compound_input"] = schedule
        calls["compound_deadline"] = float(deadline)
        clock[0] = float(deadline) - 0.01
        return _CompoundResult({0: {"score": 7}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_feedback", feedback)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=2.0,
            projected_time_feedback_rounds=2,
        ),
    )

    phase = meta["phase_timing"]
    assert returned == {0: {"score": 7}}
    assert calls["compound_input"] == {0: {"score": 8}}
    assert calls["projected_deadline"] < calls["feedback_deadline"]
    assert calls["feedback_deadline"] < calls["compound_deadline"]
    assert calls["compound_deadline"] == pytest.approx(
        phase["itc2007_compound_search"]["actual_deadline_seconds"]
    )
    assert (
        meta["itc2007_compound_search"]["service_acceptance"]["reason"]
        == "strictly_improving_candidate"
    )
    assert meta["itc2007_compound_search"]["telemetry"]["best_trajectory"] == [
        {"atomic_step": 1},
        {"atomic_step": 2},
    ]
    assert meta["returned_source"] == "itc2007_compound_search"


def test_equal_compound_candidate_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [30.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.01
        return _ProjectedResult({0: {"score": 9, "source": "projected"}})

    def compound(*_args: Any, deadline: float, **_kwargs: Any) -> _CompoundResult:
        clock[0] = float(deadline) - 0.01
        return _CompoundResult({0: {"score": 9, "source": "compound"}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=3.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    assert returned == {0: {"score": 9, "source": "projected"}}
    acceptance = meta["itc2007_compound_search"]["service_acceptance"]
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == "candidate_not_strictly_better"
    assert meta["returned_source"] == "projected_time_search"


def test_late_compound_result_is_rejected_without_overwriting_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [20.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, deadline: float, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = float(deadline) - 0.01
        return _ProjectedResult({0: {"score": 9}})

    def compound(*_args: Any, deadline: float, **_kwargs: Any) -> _CompoundResult:
        clock[0] = float(deadline) + 0.01
        return _CompoundResult({0: {"score": 1}})

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        {0: {"score": 10}},
        SolveOptions(
            adaptive_lns_seconds=3.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    assert returned == {0: {"score": 9}}
    acceptance = meta["itc2007_compound_search"]["service_acceptance"]
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == "compound_phase_deadline_overrun"
    assert meta["returned_source"] == "projected_time_search"
    assert meta["phase_timing"]["itc2007_compound_search"][
        "deadline_overrun_seconds"
    ] == pytest.approx(0.01)


def test_phase_errors_fail_closed_to_the_validated_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    monkeypatch.setattr(solver_service.time, "perf_counter", lambda: 1.0)
    monkeypatch.setattr(
        solver_service,
        "optimize_projected_times",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("projected")),
    )
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_feedback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("feedback")),
    )

    incumbent = {0: {"score": 10}}
    returned, meta = solver_service._run_adaptive_lns(
        _instance(10),
        incumbent,
        SolveOptions(
            adaptive_lns_seconds=2.0,
            projected_time_search=True,
            projected_time_feedback=True,
            projected_time_feedback_seconds=1.0,
        ),
        initial_source="constructive_initializer",
    )

    assert returned == incumbent
    assert meta["projected_time_search"]["status"] == "error"
    assert meta["itc2007_room_feedback"]["status"] == "error"
    assert meta["returned_source"] == "constructive_initializer"
    assert meta["deadline_overrun_seconds"] == 0.0


def test_fixed_time_room_cp_tail_uses_leftover_window_and_is_last_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [100.0]
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = 102.0
        return _ProjectedResult(_timed_schedule(9, source="projected"))

    def compound(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        **_kwargs: Any,
    ) -> _CompoundResult:
        clock[0] = 103.5
        return _CompoundResult(dict(schedule), improved=False)

    def room_cp(
        _inst: Any,
        schedule: dict[int, dict[str, Any]],
        *,
        deadline: float,
        seed: int,
    ) -> _RoomCPResult:
        calls["input"] = schedule
        calls["deadline"] = float(deadline)
        calls["seed"] = int(seed)
        clock[0] = 104.8
        return _RoomCPResult(_timed_schedule(8, room_id=2, source="room_cp"))

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        room_cp,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        _timed_schedule(10, source="incumbent"),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
            random_seed=17,
        ),
    )

    phase = meta["phase_timing"]["itc2007_fixed_time_room_cp"]
    tail = meta["itc2007_fixed_time_room_cp"]
    assert returned == _timed_schedule(8, room_id=2, source="room_cp")
    assert calls["input"] == _timed_schedule(9, source="projected")
    assert calls["seed"] == 2_700_018
    assert calls["deadline"] == pytest.approx(104.90)
    assert phase["phase_completion_deadline_seconds"] == pytest.approx(104.95)
    assert phase["service_validation_reserve_seconds"] == pytest.approx(0.05)
    assert phase["remaining_at_start_seconds"] == pytest.approx(1.45)
    assert phase["search_deadline_overrun_seconds"] == 0.0
    assert phase["phase_completion_overrun_seconds"] == 0.0
    assert tail["service_acceptance"]["accepted"] is True
    assert tail["service_acceptance"]["fixed_starts_preserved"] is True
    assert tail["service_acceptance"]["incumbent_score"] == 9
    assert tail["service_acceptance"]["candidate_score"] == 8
    assert tail["service_acceptance"]["candidate_components"]["total"] == 8
    assert tail["returned_source"] == "itc2007_fixed_time_room_cp"
    assert meta["returned_source"] == "itc2007_fixed_time_room_cp"


@pytest.mark.parametrize(
    ("candidate", "expected_reason"),
    [
        (
            _timed_schedule(9, room_id=2, source="equal"),
            "candidate_not_strictly_better",
        ),
        (_timed_schedule(8, slot=1, room_id=2, source="moved"), "fixed_starts_changed"),
    ],
)
def test_fixed_time_room_cp_tail_rejects_equal_or_time_changed_candidates(
    monkeypatch: pytest.MonkeyPatch,
    candidate: dict[int, dict[str, Any]],
    expected_reason: str,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [20.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = 21.0
        return _ProjectedResult(_timed_schedule(9, source="projected"))

    def room_cp(*_args: Any, **_kwargs: Any) -> _RoomCPResult:
        clock[0] = 23.0
        return _RoomCPResult(candidate)

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        room_cp,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        _timed_schedule(10, source="incumbent"),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    acceptance = meta["itc2007_fixed_time_room_cp"]["service_acceptance"]
    assert returned == _timed_schedule(9, source="projected")
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == expected_reason
    assert meta["returned_source"] == "projected_time_search"


def test_late_fixed_time_room_cp_result_cannot_overwrite_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [30.0]
    calls: dict[str, float] = {}
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = 31.0
        return _ProjectedResult(_timed_schedule(9, source="projected"))

    def room_cp(*_args: Any, deadline: float, **_kwargs: Any) -> _RoomCPResult:
        calls["deadline"] = float(deadline)
        clock[0] = float(deadline) + 0.001
        return _RoomCPResult(_timed_schedule(1, room_id=2, source="late"))

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        room_cp,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        _timed_schedule(10, source="incumbent"),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    acceptance = meta["itc2007_fixed_time_room_cp"]["service_acceptance"]
    phase = meta["phase_timing"]["itc2007_fixed_time_room_cp"]
    assert returned == _timed_schedule(9, source="projected")
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == "room_cp_search_deadline_overrun"
    assert acceptance["deadline_overrun_seconds"] == pytest.approx(0.001)
    assert phase["search_deadline_overrun_seconds"] == pytest.approx(0.001)
    assert phase["phase_completion_overrun_seconds"] == 0.0
    assert meta["returned_source"] == "projected_time_search"


def test_fixed_time_room_cp_tail_requires_one_full_second_after_compound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [40.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = 41.0
        return _ProjectedResult(_timed_schedule(9, source="projected"))

    def compound(*_args: Any, deadline: float, **_kwargs: Any) -> _CompoundResult:
        clock[0] = 43.951
        return _CompoundResult(_timed_schedule(9), improved=False)

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(solver_service, "optimize_itc2007_compound", compound)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        lambda *_args, **_kwargs: pytest.fail("sub-second room tail must not run"),
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        _timed_schedule(10, source="incumbent"),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    tail = meta["itc2007_fixed_time_room_cp"]
    assert returned == _timed_schedule(9, source="projected")
    assert tail["status"] == "skipped_insufficient_remaining_time"
    assert tail["remaining_at_start_seconds"] == pytest.approx(0.999)
    assert tail["service_acceptance"]["reason"] == "room_cp_not_attempted"


def test_fixed_time_room_cp_tail_error_retains_last_accepted_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_service_boundaries(monkeypatch)
    clock = [60.0]
    monkeypatch.setattr(
        solver_service.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def projected(*_args: Any, **_kwargs: Any) -> _ProjectedResult:
        clock[0] = 61.0
        return _ProjectedResult(_timed_schedule(9, source="projected"))

    def room_cp(*_args: Any, **_kwargs: Any) -> _RoomCPResult:
        clock[0] = 62.0
        raise RuntimeError("synthetic room CP failure")

    monkeypatch.setattr(solver_service, "optimize_projected_times", projected)
    monkeypatch.setattr(
        solver_service,
        "optimize_itc2007_fixed_time_rooms_cp",
        room_cp,
    )

    returned, meta = solver_service._run_adaptive_lns(
        _instance(20),
        _timed_schedule(10, source="incumbent"),
        SolveOptions(
            adaptive_lns_seconds=5.0,
            projected_time_search=True,
            projected_time_feedback=False,
        ),
    )

    tail = meta["itc2007_fixed_time_room_cp"]
    assert returned == _timed_schedule(9, source="projected")
    assert tail["status"] == "error"
    assert tail["service_acceptance"]["accepted"] is False
    assert tail["service_acceptance"]["reason"] == "room_cp_search_error"
    assert "synthetic room CP failure" in tail["error"]
    assert meta["returned_source"] == "projected_time_search"
