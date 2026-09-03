from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from benchmarks.cbctt import (
    CBCTT_ITC2007_PROJECTION_ID,
    parse_cbctt_ectt,
    project_cbctt_to_itc2007,
    render_projected_itc2007_ctt,
    write_projected_itc2007_ctt,
)
from benchmarks.itc2007 import parse_itc2007_ctt


ECTT_SAMPLE = """\
Name: EA01
Courses: 2
Rooms: 2
Days: 5
Periods_per_day: 5
Curricula: 1
Min_Max_Daily_Lectures: 2 4
UnavailabilityConstraints: 1
RoomConstraints: 2

COURSES:
c41 t41 1 10 0 0
c42 t42 2 1 35 1

ROOMS:
r1 30 0
r2 60 2

CURRICULA:
q1 2 c41 c42

UNAVAILABILITY_CONSTRAINTS:
c42 4 4

ROOM_CONSTRAINTS:
c41 r2
c42 r1

END.
"""


def _write_sample(tmp_path: Path, text: str = ECTT_SAMPLE) -> Path:
    source = tmp_path / "EA01.ectt"
    source.write_text(text, encoding="utf-8")
    return source


def test_parser_accepts_authentic_soft_minimum_working_day_request(
    tmp_path: Path,
) -> None:
    problem = parse_cbctt_ectt(_write_sample(tmp_path))

    assert problem.name == "EA01"
    assert problem.courses[0].minimum_working_days == 10
    assert problem.courses[0].lectures == 1
    assert problem.courses[1].double_lectures is True
    assert problem.rooms[1].location == 2
    assert problem.room_constraints == (("c41", "r2"), ("c42", "r1"))


def test_projection_is_explicitly_lossy_and_retains_four_term_inputs(
    tmp_path: Path,
) -> None:
    source = parse_cbctt_ectt(_write_sample(tmp_path))
    projection = project_cbctt_to_itc2007(source)
    evidence = projection.to_dict()

    assert projection.projection_id == CBCTT_ITC2007_PROJECTION_ID
    assert evidence["projection_kind"] == "lossy_four_term_projection"
    assert evidence["retained_itc2007_soft_terms"] == [
        "room_capacity",
        "minimum_working_days",
        "curriculum_compactness",
        "room_stability",
    ]
    assert evidence["extension_losses"] == {
        "double_lecture_course_preferences": 1,
        "room_location_attributes": 2,
        "nonzero_room_locations": 1,
        "course_room_constraint_rows": 2,
        "daily_load_bound_values": 2,
    }
    assert evidence["excluded_semantic_records"] == 7
    assert projection.problem.courses[0].minimum_working_days == 10
    assert projection.problem.rooms[1].capacity == 60
    assert projection.problem.curricula == {"q1": ("c41", "c42")}
    assert projection.problem.unavailability == (("c42", 4, 4),)


def test_projected_writer_round_trips_standard_itc2007_problem(
    tmp_path: Path,
) -> None:
    projection = project_cbctt_to_itc2007(parse_cbctt_ectt(_write_sample(tmp_path)))
    output = tmp_path / "EA01.ctt"

    write_projected_itc2007_ctt(output, projection)

    rendered = output.read_text(encoding="utf-8")
    assert rendered == render_projected_itc2007_ctt(projection)
    assert "ROOM_CONSTRAINTS" not in rendered
    assert "Min_Max_Daily_Lectures" not in rendered
    assert "c42 t42 2 1 35\n" in rendered
    assert parse_itc2007_ctt(output) == projection.problem


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda text: text.replace("Courses: 2", "Courses: 2\nCourses: 2"),
            "Duplicate ECTT metadata field",
        ),
        (
            lambda text: text.replace("ROOMS:\n", "ROOMS:\nROOMS:\n"),
            "Duplicate ECTT section",
        ),
        (
            lambda text: text.replace("END.\n", ""),
            "missing the END marker",
        ),
        (
            lambda text: text.replace("END.\n", "END.\nnot allowed\n"),
            "content after END",
        ),
        (
            lambda text: text.replace("Name: EA01", "Name: EA01\nMystery: 7"),
            "Unsupported ECTT metadata fields",
        ),
        (
            lambda text: text.replace("c42 t42 2 1 35 1", "c42 t42 2 1 35 2"),
            "double-lecture flag",
        ),
        (
            lambda text: text.replace(
                "Min_Max_Daily_Lectures: 2 4", "Min_Max_Daily_Lectures: 2 6"
            ),
            "maximum daily lectures exceed",
        ),
    ],
)
def test_parser_rejects_ambiguous_or_malformed_structure(
    tmp_path: Path,
    mutation: Callable[[str], str],
    message: str,
) -> None:
    source = _write_sample(tmp_path, mutation(ECTT_SAMPLE))

    with pytest.raises(ValueError, match=message):
        parse_cbctt_ectt(source)


def test_parser_preserves_duplicate_constraint_rows_and_rejects_unknown_references(
    tmp_path: Path,
) -> None:
    duplicate = ECTT_SAMPLE.replace(
        "UnavailabilityConstraints: 1",
        "UnavailabilityConstraints: 2",
    ).replace("c42 4 4\n\nROOM_CONSTRAINTS", "c42 4 4\nc42 4 4\n\nROOM_CONSTRAINTS")
    duplicated_problem = parse_cbctt_ectt(_write_sample(tmp_path, duplicate))
    assert duplicated_problem.unavailability == (("c42", 4, 4), ("c42", 4, 4))

    unknown_room = ECTT_SAMPLE.replace("c42 r1", "c42 missing-room")
    with pytest.raises(ValueError, match="unknown course or room"):
        parse_cbctt_ectt(_write_sample(tmp_path, unknown_room))
