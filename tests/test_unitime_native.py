from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.unitime_native import (
    UniTimeAssignment,
    UniTimeSolution,
    parse_unitime_course_xml,
    parse_unitime_exam_xml,
    parse_unitime_sectioning_xml,
    parse_unitime_xml,
    solve_unitime_native,
    summarize_unitime_problem,
    validate_unitime_solution,
    write_unitime_solution_xml,
)


COURSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<timetable version="2.4" term="toy-course" nrDays="2" slotsPerDay="12">
  <rooms>
    <room id="R1" capacity="30"/>
    <room id="R2" capacity="30"/>
  </rooms>
  <instructors><instructor id="I"/></instructors>
  <classes>
    <class id="A" offering="O1" config="G1" subpart="L1" committed="false" classLimit="20">
      <instructor id="I"/>
      <room id="R1" pref="0" solution="true"/>
      <room id="R2" pref="1"/>
      <time days="10" start="0" length="3" pref="0" solution="true"/>
      <time days="10" start="6" length="3" pref="2"/>
    </class>
    <class id="B" offering="O2" config="G2" subpart="L2" committed="false" classLimit="20">
      <instructor id="I"/>
      <room id="R1" pref="0" solution="true"/>
      <room id="R2" pref="1"/>
      <time days="10" start="0" length="3" pref="0" solution="true"/>
      <time days="10" start="6" length="3" pref="2"/>
    </class>
  </classes>
  <groupConstraints>
    <constraint id="same-room" type="SAME_ROOM" pref="R">
      <class id="A"/><class id="B"/>
    </constraint>
  </groupConstraints>
  <students>
    <student id="S"><offering id="O1"/><offering id="O2"/><class id="A"/><class id="B"/></student>
  </students>
</timetable>
"""


EXAM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<examtt version="1.0" term="toy-exam">
  <parameters>
    <property name="directConflictWeight" value="1000"/>
    <property name="periodWeight" value="1"/>
  </parameters>
  <periods>
    <period id="P1" length="120" day="Monday" time="09:00" penalty="0"/>
    <period id="P2" length="120" day="Monday" time="13:00" penalty="1"/>
  </periods>
  <rooms>
    <room id="R1" size="30" alt="15"/>
    <room id="R2" size="30" alt="15"/>
  </rooms>
  <exams>
    <exam id="E1" length="60" alt="false" maxRooms="1">
      <period id="P1"/><period id="P2"/>
      <room id="R1"/><room id="R2"/>
    </exam>
    <exam id="E2" length="60" alt="false" maxRooms="1">
      <period id="P1"/><period id="P2"/>
      <room id="R1"/><room id="R2"/>
    </exam>
  </exams>
  <students><student id="S"><exam id="E1"/><exam id="E2"/></student></students>
  <instructors/>
  <constraints>
    <different-period id="D"><exam id="E1"/><exam id="E2"/></different-period>
  </constraints>
</examtt>
"""


SECTIONING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sectioning version="1.0" initiative="toy" term="Fall" year="2026" nrDays="2" slotsPerDay="12">
  <offerings>
    <offering id="O">
      <course id="C"/>
      <config id="G" limit="2">
        <subpart id="L" itype="10">
          <section id="L1" limit="1"><time days="10" start="0" length="2" dates="1"/></section>
          <section id="L2" limit="1"><time days="10" start="4" length="2" dates="1"/></section>
        </subpart>
        <subpart id="B" itype="30" parent="L">
          <section id="B1" limit="1" parent="L1"><time days="10" start="2" length="2" dates="1"/></section>
          <section id="B2" limit="1" parent="L2"><time days="10" start="6" length="2" dates="1"/></section>
        </subpart>
      </config>
    </offering>
  </offerings>
  <students>
    <student id="S1"><course id="Q1" priority="0" course="C"/></student>
    <student id="S2"><course id="Q2" priority="0" course="C"/></student>
    <student id="S3"><course id="Q3" priority="0" course="C"/></student>
  </students>
</sectioning>
"""


def test_course_parser_score_is_native_and_solver_finds_supported_feasibility(
    tmp_path: Path,
) -> None:
    source = tmp_path / "course.xml"
    source.write_text(COURSE_XML, encoding="utf-8")
    problem = parse_unitime_xml(source)

    assert problem.kind == "course"
    assert problem.embedded_solution is not None
    embedded = validate_unitime_solution(problem, problem.embedded_solution)
    assert embedded.native_feasible is False
    assert any("instructor" in error for error in embedded.errors)
    assert embedded.score.scheme == "planora-unitime-native-v1"
    assert embedded.score.official_total is None
    assert embedded.score.officially_comparable is False

    result = solve_unitime_native(problem, time_limit_seconds=2.0, seed=17, workers=1)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.validation.feasible is True
    assert result.deadline_overrun_seconds < 0.1
    assignments = result.solution.by_item()
    assert assignments["A"].room_ids == assignments["B"].room_ids
    assert assignments["A"].time_id != assignments["B"].time_id


def test_unknown_course_constraint_is_reported_and_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "unsupported.xml"
    source.write_text(
        COURSE_XML.replace(
            "</groupConstraints>",
            '<constraint id="future" type="QUANTUM_GAP" pref="R"><class id="A"/><class id="B"/></constraint></groupConstraints>',
        ),
        encoding="utf-8",
    )
    problem = parse_unitime_course_xml(source)

    assert "course constraint QUANTUM_GAP (future)" in problem.unsupported_features
    result = solve_unitime_native(problem, time_limit_seconds=1.0)
    assert result.status == "UNSUPPORTED"
    assert result.validation.supported is False
    assert result.validation.feasible is False


def test_exam_solver_obeys_required_distribution_and_uses_native_score(
    tmp_path: Path,
) -> None:
    source = tmp_path / "exam.xml"
    source.write_text(EXAM_XML, encoding="utf-8")
    problem = parse_unitime_exam_xml(source)

    result = solve_unitime_native(problem, time_limit_seconds=2.0, seed=3, workers=1)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.validation.feasible is True
    assert result.solution.by_item()["E1"].time_id != result.solution.by_item()["E2"].time_id
    assert result.validation.score.officially_comparable is False
    assert result.validation.score.official_total is None


def test_exam_validator_rejects_room_clash_and_same_student_conflict_is_scored(
    tmp_path: Path,
) -> None:
    source = tmp_path / "exam.xml"
    source.write_text(
        EXAM_XML.replace("<different-period", "<same-period").replace(
            "</different-period>", "</same-period>"
        ),
        encoding="utf-8",
    )
    problem = parse_unitime_exam_xml(source)
    solution = UniTimeSolution(
        kind="exam",
        assignments=(
            UniTimeAssignment("E1", time_id="P1", room_ids=("R1",)),
            UniTimeAssignment("E2", time_id="P1", room_ids=("R1",)),
        ),
    )

    validation = validate_unitime_solution(problem, solution)

    assert validation.native_feasible is False
    assert any("clash in room R1" in error for error in validation.errors)
    assert dict(validation.score.components)["student_direct_conflicts"] == 1000


def test_sectioning_solver_respects_hierarchy_capacity_and_conflicts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sectioning.xml"
    source.write_text(SECTIONING_XML, encoding="utf-8")
    problem = parse_unitime_sectioning_xml(source)

    result = solve_unitime_native(problem, time_limit_seconds=2.0, seed=11, workers=1)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.validation.feasible is True
    first = set(result.solution.by_item()["Q1"].section_ids)
    second = set(result.solution.by_item()["Q2"].section_ids)
    third = set(result.solution.by_item()["Q3"].section_ids)
    assert first in ({"L1", "B1"}, {"L2", "B2"})
    assert second in ({"L1", "B1"}, {"L2", "B2"})
    assert third in ({"L1", "B1"}, {"L2", "B2"})
    assert len({frozenset(first), frozenset(second), frozenset(third)}) == 2


def test_sectioning_validator_rejects_child_without_its_parent(tmp_path: Path) -> None:
    source = tmp_path / "sectioning.xml"
    source.write_text(SECTIONING_XML, encoding="utf-8")
    problem = parse_unitime_sectioning_xml(source)
    invalid = UniTimeSolution(
        kind="sectioning",
        assignments=(
            UniTimeAssignment("Q1", section_ids=("L1", "B2")),
            UniTimeAssignment("Q2", assigned=False),
        ),
    )

    validation = validate_unitime_solution(problem, invalid)

    assert validation.native_feasible is False
    assert any("without parent L2" in error for error in validation.errors)


@pytest.mark.parametrize(
    ("name", "document"),
    (("course", COURSE_XML), ("exam", EXAM_XML), ("sectioning", SECTIONING_XML)),
)
def test_native_solution_xml_round_trip(
    tmp_path: Path,
    name: str,
    document: str,
) -> None:
    source = tmp_path / f"{name}-input.xml"
    source.write_text(document, encoding="utf-8")
    problem = parse_unitime_xml(source)
    result = solve_unitime_native(problem, time_limit_seconds=2.0, workers=1)
    assert result.validation.feasible
    output = tmp_path / f"{name}-solution.xml"

    write_unitime_solution_xml(output, problem, result.solution)
    restored = parse_unitime_xml(output)

    assert restored.embedded_solution is not None
    assert validate_unitime_solution(restored, restored.embedded_solution).feasible


def test_zero_budget_is_deadline_safe_and_returns_structural_solution(tmp_path: Path) -> None:
    source = tmp_path / "exam.xml"
    source.write_text(EXAM_XML, encoding="utf-8")
    problem = parse_unitime_exam_xml(source)

    result = solve_unitime_native(problem, time_limit_seconds=0.0)

    assert result.status == "DEADLINE_DURING_BUILD"
    assert result.deadline_overrun_seconds < 0.1
    assert result.validation.native_feasible is False


def test_xml_entity_declarations_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "entity.xml"
    source.write_text(
        '<!DOCTYPE timetable [<!ENTITY x "2.4">]><timetable version="&x;"><rooms/><classes/></timetable>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entity declarations"):
        parse_unitime_xml(source)


@pytest.mark.parametrize(
    ("path", "kind", "expected"),
    [
        (
            Path("/tmp/planora-unitime-corpus/course/pu-spr07-llr.xml"),
            "course",
            {"classes": 803, "rooms": 55, "students": 27881},
        ),
        (
            Path("/tmp/planora-unitime-corpus/exam/pu-exam-fal08.xml"),
            "exam",
            {"exams": 2198, "periods": 29, "students": 34988},
        ),
        (
            Path("/tmp/planora-unitime-corpus/sectioning/pu-sectll-fal07.xml"),
            "sectioning",
            {"offerings": 4517, "sections": 17775, "students": 38740},
        ),
    ],
)
def test_cached_official_unitime_corpora_parse_losslessly_at_core_counts(
    path: Path,
    kind: str,
    expected: dict[str, int],
) -> None:
    if not path.exists():
        pytest.skip("official UniTime benchmark archive is not cached")

    problem = parse_unitime_xml(path)
    summary = summarize_unitime_problem(problem)

    assert summary["kind"] == kind
    for key, value in expected.items():
        assert summary[key] == value
    assert summary["officially_comparable"] is False
    if kind == "course":
        assert any("SPREAD" in item for item in problem.unsupported_features)
