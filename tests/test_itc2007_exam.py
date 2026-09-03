from __future__ import annotations

from itertools import product
from pathlib import Path
import sys
from textwrap import dedent

import pytest

from benchmarks.itc2007_exam import (
    ITC2007ExamAssignment,
    ITC2007ExamValidatorError,
    parse_itc2007_exam,
    parse_itc2007_exam_solution,
    parse_itc2007_exam_validator_output,
    run_itc2007_exam_validator,
    solve_itc2007_exam,
    validate_itc2007_exam_solution,
    write_itc2007_exam_solution,
)


def _write_objective_problem(tmp_path: Path) -> Path:
    path = tmp_path / "objective.exam"
    path.write_text(
        dedent(
            """\
            [Exams:4]
            120, 0, 1
            180, 0
            90, 0
            90, 2
            [Periods:4]
            01:06:2026, 09:00:00, 180, 3
            01:06:2026, 12:00:00, 180, 0
            01:06:2026, 15:00:00, 180, 0
            02:06:2026, 09:00:00, 180, 0
            [Rooms:1]
            100, 5
            [PeriodHardConstraints]
            0, EXAM_COINCIDENCE, 1
            2, AFTER, 0
            0, EXCLUSION, 2
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 10
            TWOINADAY, 4
            PERIODSPREAD, 2
            NONMIXEDDURATIONS, 6
            FRONTLOAD, 1, 4, 7
            """
        ),
        encoding="utf-8",
    )
    return path


def _objective_assignments() -> tuple[ITC2007ExamAssignment, ...]:
    return (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
        ITC2007ExamAssignment(2, 2, 0),
        ITC2007ExamAssignment(3, 0, 0),
    )


def _write_hard_problem(tmp_path: Path) -> Path:
    path = tmp_path / "hard.exam"
    path.write_text(
        dedent(
            """\
            [Exams:4]
            200, 0, 1
            100, 0
            100, 2
            100, 3
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 180, 0
            [Rooms:1]
            2, 0
            [PeriodHardConstraints]
            0, AFTER, 1
            0, EXCLUSION, 1
            1, EXAM_COINCIDENCE, 2
            [RoomHardConstraints]
            2, ROOM_EXCLUSIVE
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


def test_parse_solution_round_trip_and_crlf_output(tmp_path: Path) -> None:
    problem = parse_itc2007_exam(_write_objective_problem(tmp_path))

    assert problem.name == "objective"
    assert [exam.duration for exam in problem.exams] == [120, 180, 90, 90]
    assert problem.exams[0].students == (0, 1)
    assert problem.periods[0].date == "01:06:2026"
    assert problem.periods[0].time == "09:00:00"
    assert problem.rooms[0].capacity == 100
    assert [constraint.kind for constraint in problem.period_constraints] == [
        "EXAM_COINCIDENCE",
        "AFTER",
        "EXCLUSION",
    ]
    assert problem.weights.period_spread == 2
    assert problem.weights.frontload_last_periods == 4

    output = tmp_path / "objective.sln"
    write_itc2007_exam_solution(
        output,
        tuple(reversed(_objective_assignments())),
        problem=problem,
    )

    assert output.read_bytes().endswith(b"\r\n")
    assert b"\r\n" in output.read_bytes()
    assert parse_itc2007_exam_solution(output, problem) == _objective_assignments()


def test_independent_objective_covers_all_official_components(tmp_path: Path) -> None:
    problem = parse_itc2007_exam(_write_objective_problem(tmp_path))

    validation = validate_itc2007_exam_solution(problem, _objective_assignments())

    # The coincidence row is ignored by the official rules because exams 0 and 1
    # have a common student; the active AFTER and EXCLUSION rows are satisfied.
    assert validation.feasible
    assert validation.hard.distance_to_feasibility == 0
    assert validation.objective.two_in_a_row == 20
    assert validation.objective.two_in_a_day == 4
    assert validation.objective.period_spread == 3
    assert validation.objective.mixed_durations == 6
    assert validation.objective.frontload == 7
    assert validation.objective.room_penalty == 20
    assert validation.objective.period_penalty == 6
    assert validation.objective.total == 66


def test_independent_validator_counts_every_official_hard_category(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_hard_problem(tmp_path))
    assignments = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 0),
        ITC2007ExamAssignment(2, 1, 0),
        ITC2007ExamAssignment(3, 1, 0),
    )

    validation = validate_itc2007_exam_solution(problem, assignments)

    assert not validation.feasible
    assert validation.hard.required == 0
    assert validation.hard.conflicts == 1
    assert validation.hard.room_occupancy == 1
    assert validation.hard.period_utilisation == 1
    assert validation.hard.period_related == 3
    assert validation.hard.room_related == 1
    assert validation.hard.distance_to_feasibility == 7


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("[Exams:5]", "count mismatch"),
        ("[Unknown]", "unsupported"),
        ("MYSTERY, 4", "unknown ITC-2007 exam institutional weighting"),
    ],
)
def test_parser_fails_closed_on_semantic_drift(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    source = _write_objective_problem(tmp_path)
    text = source.read_text(encoding="utf-8")
    if replacement == "[Exams:5]":
        text = text.replace("[Exams:4]", replacement)
    elif replacement == "[Unknown]":
        text = text.replace("[RoomHardConstraints]", replacement)
    else:
        text = text.replace("TWOINAROW, 10", replacement)
    source.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        parse_itc2007_exam(source)


def test_external_validator_parser_checks_both_totals() -> None:
    output = dedent(
        """\
        Conflicts: 0
        RoomOccupancy: 0
        PeriodUtilisation: 0
        PeriodRelated: 0
        RoomRelated: 0
        Distance to Feasibility: 0
        Two Exams in a Row Penalty = 20
        Two Exams in a Day Penalty = 4
        Period Spread Penalty = 3
        Mixed Durations Penalty = 6
        Larger Exams Constraints = 7
        Room Penalty = 20
        Period Penalty = 6
        Overall Penalty = 66
        """
    )

    parsed = parse_itc2007_exam_validator_output(output)

    assert parsed.feasible
    assert parsed.overall_penalty == 66
    with pytest.raises(ITC2007ExamValidatorError, match="soft components"):
        parse_itc2007_exam_validator_output(
            output.replace("Overall Penalty = 66", "Overall Penalty = 67")
        )


def test_external_validator_runner_uses_explicit_paths(tmp_path: Path) -> None:
    instance = _write_objective_problem(tmp_path)
    solution = tmp_path / "objective.sln"
    problem = parse_itc2007_exam(instance)
    write_itc2007_exam_solution(
        solution,
        _objective_assignments(),
        problem=problem,
    )
    output = dedent(
        """\
        Conflicts: 0
        RoomOccupancy: 0
        PeriodUtilisation: 0
        PeriodRelated: 0
        RoomRelated: 0
        Distance to Feasibility: 0
        TwoInARow: 0, pen=20
        TwoInADay: 0, pen=4
        WiderSpreads: 0, pen=3
        MixDurationPenalties: 0, pen=6
        FrontLoadPenalties: 0, pen=7
        RoomPenalties: 0, pen=20
        PeriodPenalties: 0, pen=6
        Overall penalty = 66
        """
    )
    validator = tmp_path / "validator.py"
    validator.write_text(f"print({output!r})\n", encoding="utf-8")

    parsed = run_itc2007_exam_validator(
        sys.executable,
        instance,
        solution,
        extra_arguments=(str(validator),),
    )

    assert parsed.returncode == 0
    assert parsed.overall_penalty == 66


def test_scale_gated_native_solver_is_exact_and_fail_closed(tmp_path: Path) -> None:
    problem = parse_itc2007_exam(_write_objective_problem(tmp_path))
    brute_force_scores = []
    for periods in product(range(len(problem.periods)), repeat=len(problem.exams)):
        candidate = tuple(
            ITC2007ExamAssignment(exam, period, 0)
            for exam, period in enumerate(periods)
        )
        validation = validate_itc2007_exam_solution(problem, candidate)
        if validation.feasible:
            brute_force_scores.append(validation.objective.total)

    result = solve_itc2007_exam(problem, time_limit_seconds=3.0, seed=17)

    assert result.status == "optimal"
    assert result.validation.feasible
    assert result.objective_value == result.validation.objective.total
    assert result.objective_value == min(brute_force_scores)
    assert len(result.assignments) == len(problem.exams)

    gated = solve_itc2007_exam(
        problem,
        time_limit_seconds=0.1,
        max_exams=3,
    )
    assert gated.status == "unsupported_scale"
    assert gated.assignments == ()
    assert not gated.validation.feasible
    assert gated.validation.hard.required == len(problem.exams)
    assert gated.telemetry["fail_closed"] is True


def test_public_corpus_parser_smoke_when_local_corpus_is_available() -> None:
    corpus = Path("/tmp/planora-itc2007-cpsolver/data/exam")
    paths = sorted(corpus.glob("exam_comp_set*.exam"))
    if not paths:
        pytest.skip("optional local ITC-2007 examination corpus is unavailable")

    problems = [parse_itc2007_exam(path) for path in paths]
    problem = problems[0]

    assert len(problems) == 8
    assert len(problem.exams) == 607
    assert len(problem.periods) == 54
    assert len(problem.rooms) == 7
    assert problem.weights.two_in_a_row == 7
    assert problems[5].exams[93].duration == 0
