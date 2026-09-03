from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import random
import time

import benchmarks.itc2007_exam as exam_solver
from benchmarks.itc2007_exam import (
    ITC2007ExamAssignment,
    parse_itc2007_exam,
    validate_itc2007_exam_solution,
)


def _write_period_problem(tmp_path: Path, *, kempe_barrier: bool) -> Path:
    path = tmp_path / "period-polish.exam"
    exams = "60, 0, 1\n60, 0\n60, 1" if kempe_barrier else "60, 0\n60, 0"
    exam_count = 3 if kempe_barrier else 2
    path.write_text(
        dedent(
            f"""\
            [Exams:{exam_count}]
            {exams}
            [Periods:6]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            02:06:2026, 09:00:00, 120, 0
            02:06:2026, 12:00:00, 120, 0
            03:06:2026, 09:00:00, 120, 0
            03:06:2026, 12:00:00, 120, 0
            [Rooms:1]
            3, 0
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 3
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_room_coupled_period_problem(tmp_path: Path) -> Path:
    path = tmp_path / "room-coupled-period-polish.exam"
    path.write_text(
        dedent(
            """\
            [Exams:3]
            60, 0
            120, 1
            60, 2
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            [Rooms:1]
            3, 0
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 10
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_flat_seed_compound_problem(tmp_path: Path) -> Path:
    path = tmp_path / "flat-seed-compound.exam"
    path.write_text(
        dedent(
            """\
            [Exams:3]
            60, 0
            60, 0, 1
            60, 2, 3, 4
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            [Rooms:2]
            3, 0
            2, 10
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 2, 1, 10
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_streaming_batch_problem(tmp_path: Path) -> Path:
    path = tmp_path / "streaming-batch.exam"
    path.write_text(
        dedent(
            """\
            [Exams:8]
            60, 0
            60, 1
            60, 2
            60, 3
            60, 4
            60, 5
            60, 6
            60, 7
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            [Rooms:1]
            8, 0
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_room_burden_exchange_problem(tmp_path: Path) -> Path:
    path = tmp_path / "room-burden-exchange.exam"
    path.write_text(
        dedent(
            """\
            [Exams:6]
            120, 0, 1, 2, 3, 4
            120, 5, 6, 7
            120, 8, 9
            120, 10, 11, 12, 13, 14, 15
            120, 16, 17, 18, 19
            120, 20, 21
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            [Rooms:3]
            6, 0
            4, 0
            4, 10
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def test_period_polish_strictly_reduces_spread_with_valid_atomic_move(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_period_problem(tmp_path, kempe_barrier=False))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert after.feasible
    assert after.objective.period_spread < before.objective.period_spread
    assert after.objective.total < before.objective.total
    assert telemetry["accepted"] is True
    assert telemetry["accepted_negative_temporal_moves"] >= 1
    assert {row.exam for row in assignments} == {0, 1}


def test_period_polish_crosses_conflict_barrier_with_atomic_kempe_chain(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_period_problem(tmp_path, kempe_barrier=True))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
        ITC2007ExamAssignment(2, 5, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert after.feasible
    assert after.objective.period_spread == 0
    assert after.objective.total < before.objective.total
    assert assignments != original
    assert telemetry["negative_temporal_sweep_attempts"] >= 1
    assert telemetry["accepted_negative_temporal_moves"] == 1
    assert telemetry["accepted"] is True


def test_period_polish_admits_flat_spread_move_for_mixed_duration_gain(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_coupled_period_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 0),
        ITC2007ExamAssignment(2, 1, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert before.objective.period_spread == after.objective.period_spread == 0
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.mixed_durations == before.objective.mixed_durations - 10
    assert after.objective.total == before.objective.total - 10
    assert {row.exam for row in assignments} == {0, 1, 2}
    assert telemetry["accepted_single_moves"] >= 1
    assert telemetry["accepted_without_spread_improvement"] >= 1


def test_period_polish_generates_compound_move_across_flat_seed_barrier(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_flat_seed_compound_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 1),
        ITC2007ExamAssignment(1, 1, 0),
        ITC2007ExamAssignment(2, 0, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        max_units_per_round=1,
        max_targets_per_unit=1,
        max_exchange_candidates=0,
    )

    assert before.feasible
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.period_spread == before.objective.period_spread == 0
    assert after.objective.frontload == 0
    assert after.objective.room_penalty == before.objective.room_penalty == 10
    assert after.objective.total == before.objective.total - 10
    by_exam = {row.exam: row for row in assignments}
    assert by_exam[0].period == 1
    assert by_exam[1].period == 0
    assert by_exam[2].period == 0
    assert telemetry["seed_barrier_compound_attempts"] >= 1
    assert telemetry["accepted_kempe_moves"] == 1


def test_period_polish_expiry_returns_exact_validated_incumbent(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_period_problem(tmp_path, kempe_barrier=False))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
    )

    assignments, validation, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() - 1.0,
    )

    assert assignments == original
    assert validation.feasible
    assert telemetry["accepted"] is False
    assert telemetry["single_attempts"] == 0
    assert telemetry["compound_attempts"] == 0


def test_period_polish_discards_candidate_completed_after_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_room_coupled_period_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 0),
        ITC2007ExamAssignment(2, 1, 0),
    )
    clock = [0.0]
    calls = [0]
    real_optimizer = exam_solver._optimize_exam_class_rooms

    def finish_late(*args, **kwargs):
        # Let the real optimizer see a stable pre-deadline clock, then expose
        # a late return after both affected periods have been optimized.
        result = real_optimizer(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:
            clock[0] = 2.0
        return result

    monkeypatch.setattr(exam_solver.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(exam_solver, "_optimize_exam_class_rooms", finish_late)

    assignments, validation, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=1.0,
    )

    assert assignments == original
    assert validation.feasible
    assert validation.objective.total == 10
    assert telemetry["accepted"] is False
    assert telemetry["late_candidates_discarded"] == 1


def test_period_polish_never_replaces_incumbent_without_strict_total_gain(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_coupled_period_problem(tmp_path))
    optimal = (
        ITC2007ExamAssignment(0, 1, 0),
        ITC2007ExamAssignment(1, 0, 0),
        ITC2007ExamAssignment(2, 1, 0),
    )
    before = validate_itc2007_exam_solution(problem, optimal)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        optimal,
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert before.objective.total == 0
    assert assignments == optimal
    assert after == before
    assert telemetry["accepted"] is False
    assert telemetry["score_after"] == telemetry["score_before"]


def test_period_polish_streams_four_unit_pricing_batches_before_stopping(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_streaming_batch_problem(tmp_path))
    original = tuple(
        ITC2007ExamAssignment(exam, int(exam >= 4), 0) for exam in range(8)
    )

    assignments, validation, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
    )

    assert assignments == original
    assert validation.feasible
    assert validation.objective.total == 0
    assert telemetry["pricing_batch_size"] == 4
    assert telemetry["pricing_batches"] == 2
    assert telemetry["completed_pricing_batches"] == 2
    assert telemetry["priced_units"] == 8
    assert telemetry["room_shadow_candidates"] == 8
    assert telemetry["single_attempts"] == 8
    assert telemetry["accepted"] is False


def test_period_polish_accepts_exact_room_burden_cross_period_exchange(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_burden_exchange_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 2),
        ITC2007ExamAssignment(2, 0, 1),
        ITC2007ExamAssignment(3, 1, 0),
        ITC2007ExamAssignment(4, 1, 1),
        ITC2007ExamAssignment(5, 1, 2),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        max_rounds=1,
    )

    exchange = telemetry["room_burden_exchange"]
    assert before.feasible
    assert before.objective.total == 20
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.total == 10
    assert after.objective.room_penalty == 10
    assert validate_itc2007_exam_solution(problem, assignments) == after
    assert exchange["candidate_limit"] > 0
    assert exchange["burden_units"] >= 2
    assert exchange["generated_swap_candidates"] >= 1
    assert exchange["retained_candidates"] <= exchange["candidate_limit"]
    assert exchange["evaluated_candidates"] >= 1
    assert exchange["accepted_swap_candidates"] == 1
    assert telemetry["accepted_room_burden_exchanges"] == 1
    assert exchange["score_before"] == 20
    assert exchange["score_after"] == 10
    by_exam = {row.exam: row for row in assignments}
    assert by_exam[1].period == 1
    assert by_exam[5].period == 0


def test_room_burden_exchange_generation_expiry_keeps_valid_incumbent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_room_burden_exchange_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 2),
        ITC2007ExamAssignment(2, 0, 1),
        ITC2007ExamAssignment(3, 1, 0),
        ITC2007ExamAssignment(4, 1, 1),
        ITC2007ExamAssignment(5, 1, 2),
    )
    before = validate_itc2007_exam_solution(problem, original)
    clock_calls = [0]

    def expire_at_exchange_generation() -> float:
        clock_calls[0] += 1
        return 0.0 if clock_calls[0] <= 5 else 2.0

    monkeypatch.setattr(
        exam_solver.time,
        "perf_counter",
        expire_at_exchange_generation,
    )

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=1.0,
        max_rounds=1,
    )

    exchange = telemetry["room_burden_exchange"]
    assert assignments == original
    assert after == before
    assert after.feasible
    assert after.hard.total == 0
    assert exchange["generation_deadline_stops"] == 1
    assert exchange["evaluated_candidates"] == 0
    assert exchange["accepted_candidates"] == 0


def test_room_burden_exchange_evaluation_cap_keeps_valid_incumbent(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_burden_exchange_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 2),
        ITC2007ExamAssignment(2, 0, 1),
        ITC2007ExamAssignment(3, 1, 0),
        ITC2007ExamAssignment(4, 1, 1),
        ITC2007ExamAssignment(5, 1, 2),
    )

    assignments, validation, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        max_rounds=1,
        max_exchange_evaluations=0,
        max_units_per_round=0,
    )

    exchange = telemetry["room_burden_exchange"]
    before = validate_itc2007_exam_solution(problem, original)
    assert {row.exam for row in assignments} == {row.exam for row in original}
    assert validation.feasible
    assert validation.hard.total == 0
    assert validation.objective.total <= before.objective.total
    assert exchange["evaluated_candidates"] == 0
    assert exchange["candidate_evaluation_limit_stops"] == 1
    assert exchange["accepted_candidates"] == 0


def test_temporal_unary_delta_matches_independent_randomized_scoring(
    tmp_path: Path,
) -> None:
    path = tmp_path / "randomized-temporal-delta.exam"
    path.write_text(
        dedent(
            """\
            [Exams:7]
            60, 0, 1
            60, 2
            60, 3
            60, 4
            60, 5
            60, 6
            60, 7
            [Periods:6]
            01:06:2026, 09:00:00, 120, 2
            01:06:2026, 12:00:00, 120, 0
            02:06:2026, 09:00:00, 120, 1
            02:06:2026, 12:00:00, 120, 0
            03:06:2026, 09:00:00, 120, 3
            03:06:2026, 12:00:00, 120, 0
            [Rooms:2]
            7, 0
            7, 0
            [PeriodHardConstraints]
            0, EXAM_COINCIDENCE, 1
            4, AFTER, 2
            5, EXCLUSION, 6
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 7
            TWOINADAY, 3
            PERIODSPREAD, 2
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 2, 2, 11
            """
        ),
        encoding="utf-8",
    )
    problem = parse_itc2007_exam(path)
    unit_members = ((0, 1), (2,), (3,), (4,), (5,), (6,))
    unit_by_exam = {
        exam_id: unit_id
        for unit_id, members in enumerate(unit_members)
        for exam_id in members
    }
    pair_weights = [dict() for _ in unit_members]
    for (left, right), common_students in problem.shared_student_counts.items():
        first = unit_by_exam[left]
        second = unit_by_exam[right]
        if first == second or common_students <= 0:
            continue
        pair_weights[first][second] = (
            pair_weights[first].get(second, 0) + common_students
        )
        pair_weights[second][first] = (
            pair_weights[second].get(first, 0) + common_students
        )
    period_by_unit = {0: 0, 1: 1, 2: 2, 3: 4, 4: 3, 5: 5}

    def assignments(periods: dict[int, int]):
        return tuple(
            ITC2007ExamAssignment(
                exam=exam_id,
                period=periods[unit_by_exam[exam_id]],
                room=0,
            )
            for exam_id in range(len(problem.exams))
        )

    baseline = validate_itc2007_exam_solution(problem, assignments(period_by_unit))
    assert baseline.feasible
    delta_cache = exam_solver._PeriodPolishDeltaCache(
        problem,
        unit_members,
        pair_weights,
    )
    delta_cache.reset(period_by_unit)

    rng = random.Random(17)
    proposals = [
        {0: 2},
        {3: 5},
        {4: 4},
        {5: 4},
        {3: period_by_unit[4], 4: period_by_unit[3]},
        {4: period_by_unit[5], 5: period_by_unit[4]},
    ]
    for _ in range(250):
        if rng.random() < 0.5:
            unit_id = rng.randrange(len(unit_members))
            proposals.append({unit_id: rng.randrange(len(problem.periods))})
        else:
            first, second = rng.sample(range(len(unit_members)), 2)
            proposals.append(
                {
                    first: period_by_unit[second],
                    second: period_by_unit[first],
                }
            )

    checked = 0
    for changes in proposals:
        candidate_periods = dict(period_by_unit)
        candidate_periods.update(changes)
        candidate = validate_itc2007_exam_solution(
            problem,
            assignments(candidate_periods),
        )
        if not candidate.feasible:
            continue
        expected = candidate.objective.total - baseline.objective.total
        observed = exam_solver._period_polish_temporal_unary_delta(
            problem,
            unit_members,
            pair_weights,
            period_by_unit,
            changes,
        )
        if len(changes) == 1:
            ((unit_id, target),) = changes.items()
            cached = delta_cache.placement_delta(unit_id, target)
        else:
            first, second = changes
            assert changes[first] == period_by_unit[second]
            assert changes[second] == period_by_unit[first]
            cached = delta_cache.swap_delta(first, second)
        assert cached == observed == expected
        checked += 1
    assert checked >= 20
