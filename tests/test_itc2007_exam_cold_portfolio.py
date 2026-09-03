from __future__ import annotations

import inspect
import time

import pytest

from benchmarks import itc2007_exam as exam_solver
from benchmarks.itc2007_exam import (
    ITC2007Exam,
    ITC2007ExamAssignment,
    ITC2007ExamPeriod,
    ITC2007ExamProblem,
    ITC2007ExamRoom,
    ITC2007ExamWeights,
    polish_itc2007_exam_post_incumbent,
    validate_itc2007_exam_solution,
)


def _room_pressure_problem() -> ITC2007ExamProblem:
    return ITC2007ExamProblem(
        name="room-pressure",
        exams=(
            ITC2007Exam(duration=60, students=(0,)),
            ITC2007Exam(duration=60, students=(1,)),
        ),
        periods=(
            ITC2007ExamPeriod(
                date="01:06:2026",
                time="09:00:00",
                duration=60,
                penalty=0,
            ),
        ),
        rooms=(
            ITC2007ExamRoom(capacity=2, penalty=0),
            ITC2007ExamRoom(capacity=1, penalty=10),
        ),
        period_constraints=(),
        room_constraints=(),
        weights=ITC2007ExamWeights(
            two_in_a_row=0,
            two_in_a_day=0,
            period_spread=0,
            non_mixed_durations=0,
            frontload_largest_exams=0,
            frontload_last_periods=0,
            frontload_penalty=0,
        ),
    )


def _pressured_assignments() -> tuple[ITC2007ExamAssignment, ...]:
    return (
        ITC2007ExamAssignment(exam=0, period=0, room=0),
        ITC2007ExamAssignment(exam=1, period=0, room=1),
    )


def _zero_cost_assignments() -> tuple[ITC2007ExamAssignment, ...]:
    return (
        ITC2007ExamAssignment(exam=0, period=0, room=0),
        ITC2007ExamAssignment(exam=1, period=0, room=0),
    )


def test_post_incumbent_portfolio_directly_improves_room_pressure() -> None:
    problem = _room_pressure_problem()
    source = _pressured_assignments()
    before = validate_itc2007_exam_solution(problem, source)

    assignments, validation, telemetry = polish_itc2007_exam_post_incumbent(
        problem,
        source,
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert before.objective.total == 10
    assert validation.feasible
    assert validation.objective.total == 0
    assert assignments == _zero_cost_assignments()
    assert telemetry["accepted"] is True
    accepted = [stage for stage in telemetry["stages"] if stage["accepted"]]
    assert accepted
    assert accepted[0]["stage"] == "room_quota_1"
    for stage in telemetry["stages"]:
        assert stage["operator_origin"] == "established_exam_timetabling"
        assert stage["established_operator_family"]
        assert stage["selection_origin"] == "planora"
        assert stage["planora_selection_policy"]
        assert stage["orchestration_origin"] == "planora"
        assert stage["planora_orchestration_role"]


def test_solver_portfolio_is_explicit_and_default_incumbent_path_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _room_pressure_problem()
    source = _pressured_assignments()
    calls: list[str] = []

    def coupled(
        active_problem,
        assignments,
        *,
        deadline,
        seed,
        period_radius,
        workers,
    ):
        del deadline, seed, period_radius, workers
        calls.append("coupled")
        rows = tuple(assignments)
        return (
            rows,
            validate_itc2007_exam_solution(active_problem, rows),
            {"accepted": False, "status": "captured"},
        )

    def portfolio(active_problem, assignments, *, deadline):
        assert deadline > time.perf_counter()
        calls.append("portfolio")
        rows = tuple(assignments)
        return (
            rows,
            validate_itc2007_exam_solution(active_problem, rows),
            {
                "accepted": False,
                "fail_closed": False,
                "status": "captured",
            },
        )

    monkeypatch.setattr(
        exam_solver,
        "_optimize_exam_period_room_neighborhood",
        coupled,
    )
    monkeypatch.setattr(
        exam_solver,
        "polish_itc2007_exam_post_incumbent",
        portfolio,
    )

    default_result = exam_solver.solve_itc2007_exam(
        problem,
        time_limit_seconds=1.0,
        initial_assignments=source,
    )
    explicit_result = exam_solver.solve_itc2007_exam(
        problem,
        time_limit_seconds=1.0,
        initial_assignments=source,
        post_incumbent_portfolio=True,
    )

    assert (
        inspect.signature(exam_solver.solve_itc2007_exam)
        .parameters["post_incumbent_portfolio"]
        .default
        is False
    )
    assert calls == ["coupled", "portfolio"]
    assert default_result.telemetry["strategy"] == (
        "incumbent_hinted_coupled_period_room_lns"
    )
    assert explicit_result.telemetry["strategy"] == (
        "explicit_post_incumbent_portfolio"
    )


def test_solver_rejects_portfolio_without_explicit_incumbent() -> None:
    with pytest.raises(ValueError, match="requires explicit initial_assignments"):
        exam_solver.solve_itc2007_exam(
            _room_pressure_problem(),
            time_limit_seconds=1.0,
            post_incumbent_portfolio=True,
        )


def test_post_incumbent_portfolio_rolls_back_after_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _room_pressure_problem()
    source = list(_pressured_assignments())
    expected = tuple(source)
    clock = [0.0]

    def late_improvement(active_problem, rows, **_kwargs):
        candidate = _zero_cost_assignments()
        clock[0] = 2.0
        return (
            candidate,
            validate_itc2007_exam_solution(active_problem, candidate),
            {"accepted": True},
        )

    monkeypatch.setattr(exam_solver.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(
        exam_solver,
        "_polish_post_incumbent_singleton_room_exchanges",
        late_improvement,
    )

    assignments, validation, telemetry = polish_itc2007_exam_post_incumbent(
        problem,
        source,
        deadline=1.0,
    )

    assert tuple(source) == expected
    assert assignments == expected
    assert validation.objective.total == 10
    assert telemetry["status"] == "deadline_rollback"
    assert telemetry["fail_closed"] is True
    assert telemetry["accepted"] is False


def test_post_incumbent_portfolio_rejects_invalid_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _room_pressure_problem()
    source = _zero_cost_assignments()
    source_validation = validate_itc2007_exam_solution(problem, source)
    invalid = (ITC2007ExamAssignment(exam=0, period=0, room=0),)
    invalid_validation = validate_itc2007_exam_solution(problem, invalid)

    monkeypatch.setattr(
        exam_solver,
        "_polish_post_incumbent_singleton_room_exchanges",
        lambda *_args, **_kwargs: (invalid, invalid_validation, {}),
    )

    assignments, validation, telemetry = polish_itc2007_exam_post_incumbent(
        problem,
        source,
        deadline=time.perf_counter() + 1.0,
    )

    assert assignments == source
    assert validation == source_validation
    assert telemetry["stages"][0]["status"] == "invalid_candidate"
    assert telemetry["fail_closed"] is True


def test_post_incumbent_portfolio_uses_immutable_stage_handoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _room_pressure_problem()
    caller_rows = list(_zero_cost_assignments())
    expected = list(caller_rows)

    def attempt_mutation(_problem, rows, **_kwargs):
        rows.clear()

    monkeypatch.setattr(
        exam_solver,
        "_polish_post_incumbent_singleton_room_exchanges",
        attempt_mutation,
    )

    assignments, validation, telemetry = polish_itc2007_exam_post_incumbent(
        problem,
        caller_rows,
        deadline=time.perf_counter() + 1.0,
    )

    assert caller_rows == expected
    assert assignments == tuple(expected)
    assert validation.objective.total == 0
    assert telemetry["stages"][0]["status"] == "operator_error"
    assert telemetry["fail_closed"] is True


def test_post_incumbent_portfolio_rejects_invalid_source_and_noops_at_optimum() -> None:
    problem = _room_pressure_problem()
    with pytest.raises(ValueError, match="complete and hard-feasible"):
        polish_itc2007_exam_post_incumbent(
            problem,
            _zero_cost_assignments()[:1],
            deadline=time.perf_counter() + 1.0,
        )

    source = _zero_cost_assignments()
    assignments, validation, telemetry = polish_itc2007_exam_post_incumbent(
        problem,
        source,
        deadline=time.perf_counter() + 1.0,
    )

    assert assignments == source
    assert validation.feasible
    assert validation.objective.total == 0
    assert telemetry["status"] == "no_improvement"
    assert telemetry["fail_closed"] is False
    assert telemetry["accepted"] is False
