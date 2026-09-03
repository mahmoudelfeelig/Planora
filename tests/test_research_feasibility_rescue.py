from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

from benchmarks.itc2007 import convert_itc2007_to_instance, parse_itc2007_ctt
from benchmarks.itc2007_harness import run_planora_worker
from services import solver_service
from services.contracts import SolveAttempt, SolveOptions, SolveResult


TINY_ITC2007 = """\
Name: rescue
Courses: 1
Rooms: 1
Days: 1
Periods_per_day: 1
Curricula: 0
Constraints: 0
COURSES:
C1 T1 1 1 10
ROOMS:
R1 20
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def _instance(tmp_path: Path):
    source = tmp_path / "rescue.ctt"
    source.write_text(TINY_ITC2007, encoding="utf-8")
    return source, convert_itc2007_to_instance(parse_itc2007_ctt(source))


def _schedule(inst) -> dict[int, dict[str, Any]]:
    activity_id = next(iter(inst.activities))
    activity = inst.activities[activity_id]
    return {
        int(activity_id): {
            "week": int(activity.week),
            "day": str(inst.days[0]),
            "slot": 0,
            "duration": int(activity.duration),
            "room_id": next(iter(inst.rooms)),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": [int(group_id) for group_id in activity.group_ids],
            "kind": str(activity.kind),
        }
    }


def _attempt(
    *,
    room_mode: str,
    use_objective: bool,
    seconds: float | None,
    status: int,
    build: float,
    search: float,
) -> SolveAttempt:
    return SolveAttempt(
        room_mode=str(room_mode),
        use_objective=bool(use_objective),
        time_limit_seconds=seconds,
        raw_status=int(status),
        status_name=str(cp_model.CpSolverStatus(int(status))),
        proof_status=(
            "optimal" if int(status) == int(cp_model.OPTIMAL) else "no_solution"
        ),
        budget_seconds=seconds,
        elapsed_seconds=float(build + search),
        model_build_seconds=float(build),
        setup_seconds=0.001,
        deadline_safety_margin_seconds=0.01,
        search_budget_seconds=(
            None if seconds is None else max(0.0, float(seconds) - build - 0.01)
        ),
        search_seconds=float(search),
        deadline_overrun_seconds=0.0,
    )


def test_itc_compact_arm_candidate_is_explicit_and_telemetry_backed(
    tmp_path: Path,
) -> None:
    _source, inst = _instance(tmp_path)
    options = SolveOptions(adaptive_lns_seconds=0.0)

    assert inst.hard_constraints["enable_itc2007_compact_adaptive_arms"] is False
    sizes, policy = solver_service._adaptive_lns_neighborhood_policy(
        inst,
        options,
        activity_count=100,
    )
    assert sizes == (12, 24, 48)
    assert policy == {
        "requested_sizes": [12, 24, 48],
        "configured_sizes": [12, 24, 48],
        "effective_sizes": [12, 24, 48],
        "activity_count": 100,
        "imported_itc2007_eligible": True,
        "compact_switch_enabled": False,
        "applied": False,
        "reason": "itc2007_compact_candidate_disabled",
    }

    inst.hard_constraints["enable_itc2007_compact_adaptive_arms"] = True
    sizes, policy = solver_service._adaptive_lns_neighborhood_policy(
        inst,
        options,
        activity_count=100,
    )
    assert sizes == (12, 24)
    assert policy["effective_sizes"] == [12, 24]
    assert policy["compact_switch_enabled"] is True
    assert policy["applied"] is True
    assert policy["reason"] == "itc2007_compact_candidate_explicitly_enabled"

    schedule = _schedule(inst)
    returned, adaptive_meta = solver_service._run_adaptive_lns(
        inst,
        schedule,
        options,
    )
    assert returned == schedule
    assert adaptive_meta["neighborhood_size_policy"]["requested_sizes"] == [
        12,
        24,
        48,
    ]
    assert adaptive_meta["neighborhood_size_policy"]["configured_sizes"] == [
        12,
        24,
        48,
    ]
    assert adaptive_meta["neighborhood_size_policy"]["effective_sizes"] == [1]
    assert adaptive_meta["neighborhood_size_policy"]["reason"] == (
        "itc2007_compact_candidate_explicitly_enabled"
    )


def test_research_adaptive_rescues_unknown_with_diversified_validated_incumbent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _source, inst = _instance(tmp_path)
    valid_schedule = _schedule(inst)
    calls: list[tuple[str, bool, float | None, int | None]] = []

    class FakeModel:
        decomposition_report: dict[str, Any] = {}

        def __init__(self, schedule: dict[int, dict[str, Any]]):
            self.schedule = schedule

        def extract_solution(self, _solver):
            return {
                int(activity_id): dict(info)
                for activity_id, info in self.schedule.items()
            }

    def fake_attempt(inst_arg, *, room_mode, use_objective, options):
        del inst_arg
        calls.append(
            (
                str(room_mode),
                bool(use_objective),
                options.time_limit_seconds,
                options.random_seed,
            )
        )
        if len(calls) == 1:
            return (
                FakeModel({}),
                cp_model.CpSolver(),
                int(cp_model.UNKNOWN),
                _attempt(
                    room_mode=room_mode,
                    use_objective=use_objective,
                    seconds=options.time_limit_seconds,
                    status=int(cp_model.UNKNOWN),
                    build=0.02,
                    search=0.03,
                ),
            )
        return (
            FakeModel(valid_schedule),
            cp_model.CpSolver(),
            int(cp_model.OPTIMAL),
            _attempt(
                room_mode=room_mode,
                use_objective=use_objective,
                seconds=options.time_limit_seconds,
                status=int(cp_model.OPTIMAL),
                build=0.04,
                search=0.25,
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fake_attempt)
    monkeypatch.setattr(
        solver_service,
        "_run_adaptive_lns",
        lambda _inst, schedule, _options, **_kwargs: (
            schedule,
            {"enabled": True, "status": "COMPLETE"},
        ),
    )

    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=10.0,
            workers=1,
            random_seed=17,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.is_feasible, result.meta
    assert result.schedule == valid_schedule
    assert len(result.attempts) == 2
    assert calls[0][:2] == ("partitioned", False)
    assert calls[0][2] is not None and 2.99 < float(calls[0][2]) <= 3.0
    assert calls[0][3] == 17
    assert calls[1][:2] == ("partitioned", False)
    assert calls[1][2] is not None and 0.0 < float(calls[1][2]) <= 7.0
    assert calls[1][3] == 18
    research = result.meta["research_adaptive"]
    assert research["initial_valid"] is False
    assert research["rescue_attempted"] is True
    assert research["rescue_valid"] is True
    assert research["returned_source"] == "rescue_incumbent"
    assert research["status"] == "RESCUE_INCUMBENT_VALIDATED"
    assert research["rescue"]["model_build_seconds"] == 0.04
    assert research["rescue"]["search_seconds"] == 0.25
    assert research["rescue"]["deadline_overrun_seconds"] == 0.0
    assert research["adaptive_started"] is True
    assert research["total_timing"]["deadline_overrun_seconds"] == 0.0


def test_research_adaptive_rejects_an_incomplete_rescue_incumbent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _source, inst = _instance(tmp_path)
    calls = 0

    class FakeModel:
        decomposition_report: dict[str, Any] = {}

        def extract_solution(self, _solver):
            return {}

    def fake_attempt(inst_arg, *, room_mode, use_objective, options):
        nonlocal calls
        del inst_arg
        calls += 1
        status = int(cp_model.UNKNOWN if calls == 1 else cp_model.FEASIBLE)
        return (
            FakeModel(),
            cp_model.CpSolver(),
            status,
            _attempt(
                room_mode=room_mode,
                use_objective=use_objective,
                seconds=options.time_limit_seconds,
                status=status,
                build=0.01,
                search=0.01,
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", fake_attempt)
    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=10.0,
            workers=1,
            random_seed=17,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.is_feasible is False
    assert result.schedule == {}
    assert calls == 2
    research = result.meta["research_adaptive"]
    assert research["rescue_attempted"] is True
    assert research["rescue_valid"] is False
    assert research["returned_source"] == "none"
    assert research["rescue_validation_attempted"] is True
    assert research["rescue_validation_error_count"] > 0
    assert research["status"] == "RESCUE_NO_VALIDATED_INCUMBENT"


def test_research_adaptive_does_not_rescue_after_the_total_deadline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _source, inst = _instance(tmp_path)
    calls = 0

    class FakeModel:
        decomposition_report: dict[str, Any] = {}

    def slow_unknown(inst_arg, *, room_mode, use_objective, options):
        nonlocal calls
        del inst_arg
        calls += 1
        time.sleep(0.06)
        return (
            FakeModel(),
            cp_model.CpSolver(),
            int(cp_model.UNKNOWN),
            _attempt(
                room_mode=room_mode,
                use_objective=use_objective,
                seconds=options.time_limit_seconds,
                status=int(cp_model.UNKNOWN),
                build=0.02,
                search=0.04,
            ),
        )

    monkeypatch.setattr(solver_service, "_run_solve_attempt", slow_unknown)
    result = solver_service.solve_instance(
        inst,
        SolveOptions(
            objective_profile="research_adaptive",
            time_limit_seconds=0.05,
            workers=1,
            random_seed=17,
        ),
        progress_hook=lambda _event, _payload: None,
    )

    assert result.is_feasible is False
    assert calls == 1
    research = result.meta["research_adaptive"]
    assert research["rescue_attempted"] is False
    assert research["status"] == "RESCUE_NOT_STARTED"
    assert research["rescue_skip_reason"] == "insufficient_remaining_budget"
    assert research["total_timing"]["deadline_overrun_seconds"] > 0.0


def test_itc_worker_exposes_research_rescue_and_total_timing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source, inst = _instance(tmp_path)
    schedule = _schedule(inst)

    observed_compact_arm_flags: list[bool] = []

    def fake_solve(_inst, _options):
        observed_compact_arm_flags.append(
            bool(
                _inst.hard_constraints.get(
                    "enable_itc2007_compact_adaptive_arms",
                    False,
                )
            )
        )
        return SolveResult(
            status=0,
            raw_status=int(cp_model.FEASIBLE),
            schedule=schedule,
            meta={
                "adaptive_lns": {"status": "COMPLETE"},
                "quality": {},
                "research_adaptive": {
                    "rescue_attempted": True,
                    "rescue_valid": True,
                },
                "timing": {
                    "budget_seconds": 10.0,
                    "deadline_overrun_seconds": 0.0,
                },
            },
        )

    monkeypatch.setattr(solver_service, "solve_instance", fake_solve)
    payload = run_planora_worker(
        source,
        tmp_path / "solution.out",
        tmp_path / "worker.json",
        seed=17,
        time_limit_seconds=10.0,
        workers=1,
        strategy="research_adaptive",
    )

    assert payload["feasible"] is True
    assert payload["itc2007_compact_adaptive_arms"] is False
    explicit_payload = run_planora_worker(
        source,
        tmp_path / "solution-compact.out",
        tmp_path / "worker-compact.json",
        seed=17,
        time_limit_seconds=10.0,
        workers=1,
        strategy="research_adaptive",
        itc2007_compact_adaptive_arms=True,
    )
    assert explicit_payload["itc2007_compact_adaptive_arms"] is True
    assert observed_compact_arm_flags == [False, True]
    assert payload["strategy_meta"]["research_adaptive"] == {
        "rescue_attempted": True,
        "rescue_valid": True,
    }
    assert payload["strategy_meta"]["timing"] == {
        "budget_seconds": 10.0,
        "deadline_overrun_seconds": 0.0,
    }
