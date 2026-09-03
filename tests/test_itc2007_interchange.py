from __future__ import annotations

import sys
from collections import Counter
from itertools import permutations
from pathlib import Path

import pytest

from benchmarks.itc2007 import (
    ITC2007ValidatorError,
    canonicalize_itc2007_schedule,
    convert_itc2007_to_instance,
    load_itc2007_solution,
    parse_itc2007_ctt,
    parse_itc2007_out,
    parse_itc2007_validator_output,
    run_itc2007_validator,
    score_itc2007_instance_schedule,
    score_itc2007_schedule,
    write_itc2007_solution,
)


ITC2007_SAMPLE = """\
Name: interchange-toy
Courses: 2
Rooms: 2
Days: 2
Periods_per_day: 2
Curricula: 1
Constraints: 0
COURSES:
C1 T1 2 2 25
C2 T2 1 1 20
ROOMS:
R1 10
R2 30
CURRICULA:
CUR1 2 C1 C2
UNAVAILABILITY_CONSTRAINTS:
END.
"""


OFFICIAL_VALIDATOR_EXAMPLE = """\
[H] Courses ArcTec and TecCos have both a lecture at period 1 (day 0, timeslot 1)
Violations of Lectures (hard) : 0
Violations of Conflicts (hard) : 3
Violations of Availability (hard) : 0
Violations of RoomOccupation (hard) : 2
Cost of RoomCapacity (soft) : 8
Cost of MinWorkingDays (soft) : 15
Cost of CurriculumCompactness (soft) : 4
Cost of RoomStability (soft) : 3

Summary: Violations = 5, Total Cost = 30
"""


def _problem_and_instance(tmp_path: Path):
    source = tmp_path / "toy.ctt"
    source.write_text(ITC2007_SAMPLE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    return source, problem, convert_itc2007_to_instance(problem)


def _schedule(inst) -> dict[int, dict]:
    by_course: dict[int, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        by_course.setdefault(int(activity.course_id), []).append(int(activity_id))
    return {
        sorted(by_course[1])[0]: {
            "week": 1,
            "day": "D0",
            "slot": 1,
            "duration": 1,
            "room_id": 1,
        },
        sorted(by_course[1])[1]: {
            "week": 1,
            "day": "D1",
            "slot": 0,
            "duration": 1,
            "room_id": 2,
        },
        sorted(by_course[2])[0]: {
            "week": 1,
            "day": "D0",
            "slot": 0,
            "duration": 1,
            "room_id": 2,
        },
    }


def test_itc2007_out_roundtrip_is_official_and_deterministic(tmp_path: Path) -> None:
    _, problem, inst = _problem_and_instance(tmp_path)
    schedule = _schedule(inst)
    solution_path = tmp_path / "toy.out"

    write_itc2007_solution(solution_path, problem, inst, schedule)

    assert solution_path.read_text(encoding="utf-8") == (
        "C1 R1 0 1\n"
        "C1 R2 1 0\n"
        "C2 R2 0 0\n"
    )
    assignments = parse_itc2007_out(solution_path, problem=problem, require_complete=True)
    assert [(row.course_id, row.room_id, row.day, row.period) for row in assignments] == [
        ("C1", "R1", 0, 1),
        ("C1", "R2", 1, 0),
        ("C2", "R2", 0, 0),
    ]
    assert load_itc2007_solution(solution_path, problem, inst) == schedule


def test_every_official_lecture_row_order_has_the_same_canonical_representative(
    tmp_path: Path,
) -> None:
    _, problem, inst = _problem_and_instance(tmp_path)
    course_rows = ["C1 R1 0 1", "C1 R2 1 0"]
    fixed_row = "C2 R2 0 0"
    expected = _schedule(inst)
    expected_score = score_itc2007_schedule(problem, inst, expected)

    for index, row_order in enumerate(permutations(course_rows)):
        source = tmp_path / f"permutation-{index}.out"
        source.write_text("\n".join([*row_order, fixed_row]) + "\n", encoding="utf-8")
        loaded = load_itc2007_solution(source, problem, inst)
        canonical = canonicalize_itc2007_schedule(inst, loaded)

        c1_ids = sorted(
            activity_id
            for activity_id, activity in inst.activities.items()
            if int(activity.course_id) == 1
        )
        starts = [
            inst.days.index(str(canonical[activity_id]["day"])) * inst.slots_per_day
            + int(canonical[activity_id]["slot"])
            for activity_id in c1_ids
        ]
        assert starts == sorted(starts)
        assert loaded == expected
        assert canonical == expected
        assert score_itc2007_schedule(problem, inst, loaded) == expected_score
        assert score_itc2007_schedule(problem, inst, canonical) == expected_score

        exported = tmp_path / f"canonical-{index}.out"
        write_itc2007_solution(exported, problem, inst, canonical)
        assert Counter(parse_itc2007_out(exported)) == Counter(parse_itc2007_out(source))


@pytest.mark.parametrize(
    "line, message",
    [
        ("UNKNOWN R1 0 0\n", "unknown course"),
        ("C1 UNKNOWN 0 0\nC1 R1 1 0\nC2 R1 0 1\n", "unknown room"),
        ("C1 R1 2 0\nC1 R1 1 0\nC2 R1 0 1\n", "outside"),
        ("C1 R1 0 0\nC2 R1 0 1\n", "lecture count"),
    ],
)
def test_itc2007_out_rejects_semantically_invalid_rows(
    tmp_path: Path,
    line: str,
    message: str,
) -> None:
    _, problem, _ = _problem_and_instance(tmp_path)
    solution_path = tmp_path / "invalid.out"
    solution_path.write_text(line, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        parse_itc2007_out(solution_path, problem=problem, require_complete=True)


def test_official_validator_example_is_parsed_with_independent_totals() -> None:
    result = parse_itc2007_validator_output(OFFICIAL_VALIDATOR_EXAMPLE)

    assert result.hard_violations == 5
    assert result.feasible is False
    assert result.soft_score.to_dict() == {
        "room_capacity": 8,
        "minimum_working_days": 15,
        "curriculum_compactness": 4,
        "room_stability": 3,
        "total": 30,
    }


def test_actual_official_feasible_summary_variant_is_parsed() -> None:
    feasible = OFFICIAL_VALIDATOR_EXAMPLE.replace(
        "Summary: Violations = 5, Total Cost = 30",
        "Summary: Total Cost = 30",
    ).replace("Violations of Conflicts (hard) : 3", "Violations of Conflicts (hard) : 0").replace(
        "Violations of RoomOccupation (hard) : 2",
        "Violations of RoomOccupation (hard) : 0",
    )

    result = parse_itc2007_validator_output(feasible)
    assert result.feasible is True
    assert result.total_cost == 30


def test_validator_output_rejects_internally_inconsistent_summary() -> None:
    corrupted = OFFICIAL_VALIDATOR_EXAMPLE.replace("Total Cost = 30", "Total Cost = 29")

    with pytest.raises(ValueError, match="soft-cost summary mismatch"):
        parse_itc2007_validator_output(corrupted)


def test_validator_output_accepts_official_feasible_summary_without_violation_field() -> None:
    feasible = OFFICIAL_VALIDATOR_EXAMPLE.replace(
        "Violations of Conflicts (hard) : 3",
        "Violations of Conflicts (hard) : 0",
    ).replace(
        "Violations of RoomOccupation (hard) : 2",
        "Violations of RoomOccupation (hard) : 0",
    ).replace(
        "Summary: Violations = 5, Total Cost = 30",
        "Summary: Total Cost = 30",
    )

    result = parse_itc2007_validator_output(feasible)

    assert result.feasible is True
    assert result.hard_violations == 0


def test_validator_runner_uses_argument_vector_and_bridges_official_score(
    tmp_path: Path,
) -> None:
    source, problem, inst = _problem_and_instance(tmp_path)
    solution_path = tmp_path / "toy.out"
    schedule = _schedule(inst)
    write_itc2007_solution(solution_path, problem, inst, schedule)
    expected_score = score_itc2007_schedule(problem, inst, schedule)
    assert score_itc2007_instance_schedule(inst, schedule) == expected_score
    fake_validator = tmp_path / "validator.py"
    fake_validator.write_text(
        """\
import pathlib
import sys

assert pathlib.Path(sys.argv[1]).suffix == ".ctt"
assert pathlib.Path(sys.argv[2]).suffix == ".out"
print("Violations of Lectures (hard) : 0")
print("Violations of Conflicts (hard) : 0")
print("Violations of Availability (hard) : 0")
print("Violations of RoomOccupation (hard) : 0")
print("Cost of RoomCapacity (soft) : 15")
print("Cost of MinWorkingDays (soft) : 0")
print("Cost of CurriculumCompactness (soft) : 2")
print("Cost of RoomStability (soft) : 1")
print("Summary: Violations = 0, Total Cost = 18")
""",
        encoding="utf-8",
    )

    result = run_itc2007_validator(
        [sys.executable, fake_validator],
        source,
        solution_path,
        timeout_seconds=5,
    )

    assert result.returncode == 0
    assert result.feasible is True
    assert result.soft_score == expected_score


def test_validator_runner_surfaces_process_failure(tmp_path: Path) -> None:
    source, problem, inst = _problem_and_instance(tmp_path)
    solution_path = tmp_path / "toy.out"
    write_itc2007_solution(solution_path, problem, inst, _schedule(inst))
    fake_validator = tmp_path / "validator.py"
    fake_validator.write_text(
        "import sys\nprint('malformed output', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )

    with pytest.raises(ITC2007ValidatorError, match="exit code 7"):
        run_itc2007_validator([sys.executable, fake_validator], source, solution_path)
