from __future__ import annotations

from pathlib import Path

from ortools.sat.python import cp_model

from benchmarks.itc2007 import (
    load_itc2007_instance,
    parse_itc2007_ctt,
    score_itc2007_schedule,
)
from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    count_itc2019_student_conflicts,
    inspect_itc2019_xml,
    parse_itc2019_solution,
    parse_itc2019_xml,
    solve_itc2019_student_sectioning,
    summarize_itc2019_problem,
    validate_itc2019_class_placements,
    validate_itc2019_solution,
    validate_itc2019_student_sectioning,
    write_itc2019_solution,
)
from core.metaheuristics import LocalSearchImprover
from core.solver_cp_sat import TimetableSolver
from utils.generator import write_instance
from utils.io import read_instance
from utils.specs import validate_schedule_against_instance


ITC2007_SAMPLE = """\
Name: toy
Courses: 2
Rooms: 2
Days: 2
Periods_per_day: 2
Curricula: 1
Constraints: 1

COURSES:
C1 T1 2 2 25
C2 T2 1 1 20
ROOMS:
R1 10
R2 30
CURRICULA:
CUR1 2 C1 C2
UNAVAILABILITY_CONSTRAINTS:
C1 0 0
END.
"""


ITC2019_SAMPLE = """\
<problem name="sectioning-toy" nrDays="7" slotsPerDay="288" nrWeeks="1" campus="demo">
  <optimization time="3" room="2" distribution="11" student="7"/>
  <rooms>
    <room id="R1" capacity="2">
      <travel room="R3" value="3"/>
    </room>
    <room id="R2" capacity="2">
      <travel room="R3" value="4"/>
    </room>
    <room id="R3" capacity="2">
      <unavailable days="0010000" start="100" length="2" weeks="1"/>
    </room>
  </rooms>
  <courses>
    <course id="C1">
      <config id="CFG1">
        <subpart id="LECT">
          <class id="L1" limit="1">
            <room id="R1" penalty="2"/>
            <time days="1000000" start="10" length="2" weeks="1" penalty="3"/>
          </class>
          <class id="L2" limit="1">
            <room id="R2"/>
            <time days="0100000" start="10" length="2" weeks="1"/>
          </class>
        </subpart>
        <subpart id="TUTORIAL">
          <class id="T1" limit="1" parent="L1">
            <room id="R1"/>
            <time days="1000000" start="20" length="2" weeks="1"/>
          </class>
          <class id="T2" limit="1" parent="L2">
            <room id="R2"/>
            <time days="0100000" start="20" length="2" weeks="1"/>
          </class>
        </subpart>
      </config>
      <config id="CFG2">
        <subpart id="ALT">
          <class id="A3" limit="0" room="false" delivery="online">
            <time days="0010000" start="30" length="2" weeks="1"/>
          </class>
        </subpart>
      </config>
    </course>
    <course id="C2">
      <config id="CFG3">
        <subpart id="SEMINAR">
          <class id="B1" limit="1">
            <room id="R3"/>
            <time days="1000000" start="13" length="2" weeks="1"/>
          </class>
          <class id="B2" limit="1">
            <room id="R3"/>
            <time days="0100000" start="13" length="2" weeks="1"/>
          </class>
        </subpart>
      </config>
    </course>
  </courses>
  <distributions>
    <distribution type="SameRoom" required="true">
      <class id="L1"/><class id="T1"/>
    </distribution>
    <distribution type="MinGap(2)" required="false" penalty="4">
      <class id="L1"/><class id="T1"/>
    </distribution>
  </distributions>
  <students>
    <student id="S1"><course id="C1"/><course id="C2"/></student>
    <student id="S2"><course id="C1"/><course id="C2"/></student>
  </students>
</problem>
"""


def _itc2019_placements() -> tuple[ITC2019ClassPlacement, ...]:
    return (
        ITC2019ClassPlacement("L1", "1000000", 10, "1", "R1"),
        ITC2019ClassPlacement("L2", "0100000", 10, "1", "R2"),
        ITC2019ClassPlacement("T1", "1000000", 20, "1", "R1"),
        ITC2019ClassPlacement("T2", "0100000", 20, "1", "R2"),
        ITC2019ClassPlacement("A3", "0010000", 30, "1", None),
        ITC2019ClassPlacement("B1", "1000000", 13, "1", "R3"),
        ITC2019ClassPlacement("B2", "0100000", 13, "1", "R3"),
    )


def test_itc2007_parser_conversion_roundtrip_and_solve(tmp_path: Path) -> None:
    source = tmp_path / "toy.ctt"
    source.write_text(ITC2007_SAMPLE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    assert problem.name == "toy"
    assert len(problem.courses) == 2

    inst = load_itc2007_instance(source)
    assert len(inst.activities) == 3
    assert inst.hard_constraints["enforce_room_capacity"] is False
    c1_activity_ids = [a_id for a_id, act in inst.activities.items() if act.course_id == 1]
    assert all(("D0", 0) in inst.activity_unavailability[a_id] for a_id in c1_activity_ids)

    serialized = tmp_path / "toy.json"
    write_instance(inst, serialized)
    restored = read_instance(serialized)
    assert restored.activity_unavailability == inst.activity_unavailability

    model = TimetableSolver(restored, room_mode="decomposed", use_objective=False)
    solver, status = model.solve(time_limit_seconds=5, workers=1, random_seed=4)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(restored, schedule, strict_rooms=True) == []
    assert all(
        (str(schedule[a_id]["day"]), int(schedule[a_id]["slot"])) != ("D0", 0)
        for a_id in c1_activity_ids
    )
    improver = LocalSearchImprover(restored, random_seed=4)
    assert all(
        not improver._activity_start_allowed(a_id, "D0", 0)
        for a_id in c1_activity_ids
    )


def test_itc2007_cp_objective_exactly_matches_independent_official_scorer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "toy.ctt"
    source.write_text(ITC2007_SAMPLE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    inst = load_itc2007_instance(source)

    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)
    solver, status = model.solve(time_limit_seconds=10, workers=1, random_seed=12)

    assert int(status) == int(cp_model.OPTIMAL)
    schedule = model.extract_solution(solver)
    score = score_itc2007_schedule(problem, inst, schedule)
    assert int(solver.ObjectiveValue()) == score.total
    assert validate_schedule_against_instance(inst, schedule, strict_rooms=True) == []


def test_local_search_respects_institutional_start_windows(tmp_path: Path) -> None:
    source = tmp_path / "toy.ctt"
    source.write_text(ITC2007_SAMPLE, encoding="utf-8")
    inst = load_itc2007_instance(source)
    inst.hard_constraints["enforce_standard_start_slots"] = True
    inst.institutional_policy = {
        "standard_start_slots": [0, 2],
        "allowed_day_slots": {"D1": [2]},
    }
    improver = LocalSearchImprover(inst, random_seed=5)
    activity_id = min(inst.activities)

    assert improver._activity_start_allowed(activity_id, "D0", 2)
    assert not improver._activity_start_allowed(activity_id, "D0", 1)
    assert not improver._activity_start_allowed(activity_id, "D1", 0)
    assert improver._activity_start_allowed(activity_id, "D1", 2)


def test_itc2019_xml_inspection_preserves_schema_evidence(tmp_path: Path) -> None:
    source = tmp_path / "tiny.xml"
    source.write_text(
        """<problem name="tiny"><rooms><room id="r1"/></rooms>"
        "<classes><class id="c1"/></classes>"
        "<distributions><distribution type="SameRoom"/></distributions></problem>""",
        encoding="utf-8",
    )
    report = inspect_itc2019_xml(source)
    assert report.instance_name == "tiny"
    assert report.element_counts["room"] == 1
    assert report.element_counts["class"] == 1
    assert report.distribution_types == {"SameRoom": 1}


def test_itc2019_full_parser_preserves_sectioning_and_constraint_domains(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sectioning-toy.xml"
    source.write_text(ITC2019_SAMPLE, encoding="utf-8")

    problem = parse_itc2019_xml(source)
    summary = summarize_itc2019_problem(problem)

    assert problem.name == "sectioning-toy"
    assert problem.optimization.student == 7
    assert problem.extra_attributes == (("campus", "demo"),)
    assert summary.to_dict() == {
        "instance_name": "sectioning-toy",
        "rooms": 3,
        "travel_entries": 2,
        "unavailable_periods": 1,
        "courses": 2,
        "configurations": 3,
        "subparts": 4,
        "classes": 7,
        "parent_relations": 2,
        "time_options": 7,
        "room_options": 6,
        "distributions": 2,
        "required_distributions": 1,
        "soft_distributions": 1,
        "students": 2,
        "course_requests": 4,
    }
    classes = {klass.id: klass for klass in problem.classes}
    assert classes["T1"].parent_id == "L1"
    assert classes["A3"].room_required is False
    assert classes["A3"].extra_attributes == (("delivery", "online"),)
    assert classes["L1"].time_options[0].penalty == 3
    assert classes["L1"].room_options[0].penalty == 2
    assert problem.distributions[1].type == "MinGap(2)"
    assert problem.distributions[1].penalty == 4
    assert problem.students[0].course_ids == ("C1", "C2")


def test_itc2019_room_domain_is_authoritative_over_informational_capacity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "room-domain.xml"
    source.write_text(
        """\
<problem name="room-domain" nrDays="1" slotsPerDay="2" nrWeeks="1">
  <rooms><room id="R" capacity="1"/></rooms>
  <courses><course id="C"><config id="CFG"><subpart id="SP">
    <class id="CL" limit="100">
      <room id="R"/><time days="1" start="0" length="1" weeks="1"/>
    </class>
  </subpart></config></course></courses>
</problem>
""",
        encoding="utf-8",
    )
    problem = parse_itc2019_xml(source)

    assert validate_itc2019_class_placements(
        problem,
        (ITC2019ClassPlacement("CL", "1", 0, "1", "R"),),
    ) == []


def test_itc2019_conditional_sectioning_is_capacity_safe_and_conflict_optimal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sectioning-toy.xml"
    source.write_text(ITC2019_SAMPLE, encoding="utf-8")
    problem = parse_itc2019_xml(source)
    placements = _itc2019_placements()

    assert validate_itc2019_class_placements(problem, placements) == []
    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=5,
        workers=1,
        random_seed=17,
    )

    assert result.status == "OPTIMAL"
    assert result.validation_errors == ()
    assert result.student_conflicts == 0
    assert result.weighted_objective == 0
    assert validate_itc2019_student_sectioning(problem, result.student_classes) == []
    assert validate_itc2019_solution(problem, placements, result.student_classes) == []
    assert count_itc2019_student_conflicts(
        problem,
        placements,
        result.student_classes,
    ) == 0
    assert all("A3" not in classes for classes in result.student_classes.values())
    assert sorted(
        next(class_id for class_id in classes if class_id in {"L1", "L2"})
        for classes in result.student_classes.values()
    ) == ["L1", "L2"]
    assert sorted(
        next(class_id for class_id in classes if class_id in {"B1", "B2"})
        for classes in result.student_classes.values()
    ) == ["B1", "B2"]

    invalid_sectioning = {
        "S1": ("L1", "T2", "B2"),
        "S2": ("L2", "T2", "B1"),
    }
    errors = validate_itc2019_student_sectioning(problem, invalid_sectioning)
    assert any("requires parent L2" in error for error in errors)
    assert any("class T2 load 2 exceeds limit 1" in error for error in errors)


def test_itc2019_solution_export_round_trips_validated_enrollments(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sectioning-toy.xml"
    source.write_text(ITC2019_SAMPLE, encoding="utf-8")
    problem = parse_itc2019_xml(source)
    placements = _itc2019_placements()
    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=5,
        workers=1,
        random_seed=19,
    )
    assert result.is_feasible

    destination = write_itc2019_solution(
        problem,
        placements,
        result.student_classes,
        tmp_path / "solution.xml",
        metadata={"runtime": "0", "technique": "Planora conditional CP-SAT"},
    )
    restored = parse_itc2019_solution(destination)

    assert {placement.class_id: placement for placement in restored.placements} == {
        placement.class_id: placement for placement in placements
    }
    assert restored.student_classes == result.student_classes
    assert dict(restored.metadata)["name"] == "sectioning-toy"
    assert dict(restored.metadata)["technique"] == "Planora conditional CP-SAT"
