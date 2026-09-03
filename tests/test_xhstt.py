from __future__ import annotations

from pathlib import Path
import time

import pytest

import benchmarks.xhstt as xhstt_module
from benchmarks.xhstt import (
    XHSTTMeet,
    XHSTTConstraint,
    XHSTTEvent,
    XHSTTEventGroup,
    XHSTTEventResource,
    XHSTTProblem,
    XHSTTResource,
    XHSTTResourceAssignment,
    XHSTTResourceGroup,
    XHSTTResourceType,
    XHSTTSolution,
    XHSTTTime,
    parse_xhstt,
    parse_xhstt_archive,
    parse_xhstt_solutions,
    solve_xhstt,
    validate_xhstt_solution,
    write_xhstt_solution,
)


def _toy_archive(*, extra_constraint: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<HighSchoolTimetableArchive Id="toy-archive">
  <Instances>
    <Instance Id="toy">
      <MetaData><Name>Toy</Name></MetaData>
      <Times>
        <TimeGroups>
          <Day Id="Monday"><Name>Monday</Name></Day>
          <Day Id="Tuesday"><Name>Tuesday</Name></Day>
        </TimeGroups>
        <Time Id="M1"><Name>M1</Name><Day Reference="Monday"/></Time>
        <Time Id="M2"><Name>M2</Name><Day Reference="Monday"/></Time>
        <Time Id="M3"><Name>M3</Name><Day Reference="Monday"/></Time>
        <Time Id="T1"><Name>T1</Name><Day Reference="Tuesday"/></Time>
      </Times>
      <Resources>
        <ResourceTypes>
          <ResourceType Id="Teacher"><Name>Teacher</Name></ResourceType>
          <ResourceType Id="Room"><Name>Room</Name></ResourceType>
        </ResourceTypes>
        <ResourceGroups>
          <ResourceGroup Id="Teachers"><Name>Teachers</Name><ResourceType Reference="Teacher"/></ResourceGroup>
          <ResourceGroup Id="Rooms"><Name>Rooms</Name><ResourceType Reference="Room"/></ResourceGroup>
        </ResourceGroups>
        <Resource Id="Teacher1"><Name>Teacher1</Name><ResourceType Reference="Teacher"/><ResourceGroups><ResourceGroup Reference="Teachers"/></ResourceGroups></Resource>
        <Resource Id="Room1"><Name>Room1</Name><ResourceType Reference="Room"/><ResourceGroups><ResourceGroup Reference="Rooms"/></ResourceGroups></Resource>
      </Resources>
      <Events>
        <EventGroups>
          <Course Id="Course"><Name>Course</Name></Course>
          <EventGroup Id="All"><Name>All</Name></EventGroup>
        </EventGroups>
        <Event Id="E1"><Name>E1</Name><Duration>1</Duration><Course Reference="Course"/><Resources><Resource Reference="Teacher1"><Role>Teacher</Role><ResourceType Reference="Teacher"/></Resource><Resource><Role>Room</Role><ResourceType Reference="Room"/></Resource></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
        <Event Id="E2"><Name>E2</Name><Duration>1</Duration><Course Reference="Course"/><Resources><Resource Reference="Teacher1"><Role>Teacher</Role><ResourceType Reference="Teacher"/></Resource><Resource><Role>Room</Role><ResourceType Reference="Room"/></Resource></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
      </Events>
      <Constraints>
        <AssignTimeConstraint Id="assign-time"><Name>assign-time</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo></AssignTimeConstraint>
        <AssignResourceConstraint Id="assign-room"><Name>assign-room</Name><Required>true</Required><Weight>2</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo><Role>Room</Role></AssignResourceConstraint>
        <AvoidClashesConstraint Id="clash"><Name>clash</Name><Required>true</Required><Weight>3</Weight><CostFunction>Linear</CostFunction><AppliesTo><ResourceGroups><ResourceGroup Reference="Teachers"/></ResourceGroups></AppliesTo></AvoidClashesConstraint>
        <PreferTimesConstraint Id="prefer"><Name>prefer</Name><Required>false</Required><Weight>5</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo><Times><Time Reference="M2"/></Times></PreferTimesConstraint>
        <SpreadEventsConstraint Id="spread"><Name>spread</Name><Required>false</Required><Weight>7</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="Course"/></EventGroups></AppliesTo><TimeGroups><TimeGroup Reference="Monday"><Minimum>0</Minimum><Maximum>1</Maximum></TimeGroup></TimeGroups></SpreadEventsConstraint>
        <LimitBusyTimesConstraint Id="busy"><Name>busy</Name><Required>false</Required><Weight>11</Weight><CostFunction>Linear</CostFunction><AppliesTo><Resources><Resource Reference="Teacher1"/></Resources></AppliesTo><TimeGroups><TimeGroup Reference="Monday"/></TimeGroups><Minimum>2</Minimum><Maximum>2</Maximum></LimitBusyTimesConstraint>
        {extra_constraint}
      </Constraints>
    </Instance>
  </Instances>
</HighSchoolTimetableArchive>
"""


def _balanced_coloring_archive() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<HighSchoolTimetableArchive>
  <Instances>
    <Instance Id="balanced">
      <MetaData><Name>Balanced tensor</Name></MetaData>
      <Times>
        <Time Id="T0"><Name>T0</Name></Time><Time Id="T1"><Name>T1</Name></Time>
        <Time Id="T2"><Name>T2</Name></Time><Time Id="T3"><Name>T3</Name></Time>
      </Times>
      <Resources>
        <ResourceTypes>
          <ResourceType Id="Class"><Name>Class</Name></ResourceType>
          <ResourceType Id="Teacher"><Name>Teacher</Name></ResourceType>
          <ResourceType Id="Room"><Name>Room</Name></ResourceType>
        </ResourceTypes>
        <ResourceGroups>
          <ResourceGroup Id="Classes"><Name>Classes</Name><ResourceType Reference="Class"/></ResourceGroup>
          <ResourceGroup Id="Teachers"><Name>Teachers</Name><ResourceType Reference="Teacher"/></ResourceGroup>
          <ResourceGroup Id="Rooms"><Name>Rooms</Name><ResourceType Reference="Room"/></ResourceGroup>
        </ResourceGroups>
        <Resource Id="C0"><Name>C0</Name><ResourceType Reference="Class"/><ResourceGroups><ResourceGroup Reference="Classes"/></ResourceGroups></Resource>
        <Resource Id="C1"><Name>C1</Name><ResourceType Reference="Class"/><ResourceGroups><ResourceGroup Reference="Classes"/></ResourceGroups></Resource>
        <Resource Id="P0"><Name>P0</Name><ResourceType Reference="Teacher"/><ResourceGroups><ResourceGroup Reference="Teachers"/></ResourceGroups></Resource>
        <Resource Id="P1"><Name>P1</Name><ResourceType Reference="Teacher"/><ResourceGroups><ResourceGroup Reference="Teachers"/></ResourceGroups></Resource>
        <Resource Id="R0"><Name>R0</Name><ResourceType Reference="Room"/><ResourceGroups><ResourceGroup Reference="Rooms"/></ResourceGroups></Resource>
        <Resource Id="R1"><Name>R1</Name><ResourceType Reference="Room"/><ResourceGroups><ResourceGroup Reference="Rooms"/></ResourceGroups></Resource>
      </Resources>
      <Events>
        <EventGroups><EventGroup Id="All"><Name>All</Name></EventGroup></EventGroups>
        <Event Id="E000"><Name>E000</Name><Duration>2</Duration><Resources><Resource Reference="C0"/><Resource Reference="P0"/><Resource Reference="R0"/></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
        <Event Id="E011"><Name>E011</Name><Duration>2</Duration><Resources><Resource Reference="C0"/><Resource Reference="P1"/><Resource Reference="R1"/></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
        <Event Id="E100"><Name>E100</Name><Duration>2</Duration><Resources><Resource Reference="C1"/><Resource Reference="P0"/><Resource Reference="R0"/></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
        <Event Id="E111"><Name>E111</Name><Duration>2</Duration><Resources><Resource Reference="C1"/><Resource Reference="P1"/><Resource Reference="R1"/></Resources><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
      </Events>
      <Constraints>
        <AssignTimeConstraint Id="assign"><Name>assign</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo></AssignTimeConstraint>
        <AvoidClashesConstraint Id="clash"><Name>clash</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><ResourceGroups><ResourceGroup Reference="Classes"/><ResourceGroup Reference="Teachers"/><ResourceGroup Reference="Rooms"/></ResourceGroups></AppliesTo></AvoidClashesConstraint>
      </Constraints>
    </Instance>
  </Instances>
</HighSchoolTimetableArchive>
"""


def _balanced_resource_archive() -> str:
    teachers = "".join(
        f'<Resource Id="P{index}"><Name>P{index}</Name>'
        '<ResourceType Reference="Teacher"/><ResourceGroups>'
        '<ResourceGroup Reference="Teachers"/></ResourceGroups></Resource>'
        for index in range(4)
    )
    events = "".join(
        f'<Event Id="E{index}"><Name>E{index}</Name><Duration>1</Duration>'
        f'<Resources><Resource Reference="P{index}"/><Resource><Role>Room</Role>'
        '<ResourceType Reference="Room"/></Resource></Resources><EventGroups>'
        '<EventGroup Reference="All"/></EventGroups></Event>'
        for index in range(4)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<HighSchoolTimetableArchive><Instances><Instance Id="balanced-resources">
  <MetaData><Name>Balanced resources</Name></MetaData>
  <Times><Time Id="T0"><Name>T0</Name></Time><Time Id="T1"><Name>T1</Name></Time></Times>
  <Resources>
    <ResourceTypes><ResourceType Id="Teacher"><Name>Teacher</Name></ResourceType><ResourceType Id="Room"><Name>Room</Name></ResourceType></ResourceTypes>
    <ResourceGroups><ResourceGroup Id="Teachers"><Name>Teachers</Name><ResourceType Reference="Teacher"/></ResourceGroup><ResourceGroup Id="Rooms"><Name>Rooms</Name><ResourceType Reference="Room"/></ResourceGroup></ResourceGroups>
    {teachers}
    <Resource Id="R0"><Name>R0</Name><ResourceType Reference="Room"/><ResourceGroups><ResourceGroup Reference="Rooms"/></ResourceGroups></Resource>
    <Resource Id="R1"><Name>R1</Name><ResourceType Reference="Room"/><ResourceGroups><ResourceGroup Reference="Rooms"/></ResourceGroups></Resource>
  </Resources>
  <Events><EventGroups><EventGroup Id="All"><Name>All</Name></EventGroup></EventGroups>{events}</Events>
  <Constraints>
    <AssignTimeConstraint Id="assign-time"><Name>assign-time</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo></AssignTimeConstraint>
    <AssignResourceConstraint Id="assign-room"><Name>assign-room</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo><Role>Room</Role></AssignResourceConstraint>
    <AvoidClashesConstraint Id="clash"><Name>clash</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><ResourceGroups><ResourceGroup Reference="Teachers"/><ResourceGroup Reference="Rooms"/></ResourceGroups></AppliesTo></AvoidClashesConstraint>
  </Constraints>
</Instance></Instances></HighSchoolTimetableArchive>
"""


def test_parser_and_independent_weighted_score(tmp_path: Path) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)
    solution = XHSTTSolution(
        instance_id="toy",
        meets=(
            XHSTTMeet("E1", 1, "M1"),
            XHSTTMeet("E2", 1, "M1"),
        ),
    )

    validation = validate_xhstt_solution(problem, solution)

    assert problem.id == "toy"
    assert len(problem.constraints) == 6
    assert validation.errors == ()
    assert validation.unsupported_features == ()
    assert validation.score.hard_cost == 7
    assert validation.score.soft_cost == 28
    assert validation.feasible is False


def test_unknown_constraint_fails_closed_instead_of_disappearing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "extension.xml"
    source.write_text(
        _toy_archive(
            extra_constraint="""
            <StudentChoiceConstraint Id="future"><Name>future</Name><Required>false</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><Resources><Resource Reference="Teacher1"/></Resources></AppliesTo></StudentChoiceConstraint>
            """
        ),
        encoding="utf-8",
    )
    problem = parse_xhstt(source)
    solution = XHSTTSolution(
        instance_id="toy",
        meets=(XHSTTMeet("E1", 1, None), XHSTTMeet("E2", 1, None)),
    )

    validation = validate_xhstt_solution(problem, solution)

    assert problem.unsupported_features == (
        "constraint StudentChoiceConstraint (future)",
    )
    assert validation.feasible is False
    assert validation.unsupported_features == problem.unsupported_features


def test_parser_rejects_doctypes_and_dangling_references(tmp_path: Path) -> None:
    doctype = tmp_path / "doctype.xml"
    doctype.write_text(
        _toy_archive().replace(
            '<HighSchoolTimetableArchive Id="toy-archive">',
            '<!DOCTYPE HighSchoolTimetableArchive [<!ENTITY probe "blocked">]>'
            '<HighSchoolTimetableArchive Id="toy-archive">',
        ),
        encoding="utf-8",
    )
    dangling = tmp_path / "dangling.xml"
    dangling.write_text(
        _toy_archive().replace(
            '<Resource Reference="Teacher1"',
            '<Resource Reference="MissingTeacher"',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_xhstt(doctype)
    with pytest.raises(ValueError, match="unknown resource reference"):
        parse_xhstt(dangling)


def test_solution_xml_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)
    original = XHSTTSolution(
        instance_id="toy",
        description="round trip",
        meets=(
            XHSTTMeet(
                "E1",
                1,
                "M2",
                (XHSTTResourceAssignment("Room", "Room1"),),
            ),
            XHSTTMeet(
                "E2",
                1,
                "T1",
                (XHSTTResourceAssignment("Room", "Room1"),),
            ),
        ),
    )
    output = tmp_path / "solution.xml"

    write_xhstt_solution(output, original, solution_group_id="Planora-test")
    parsed = parse_xhstt_solutions(output, problem)

    payload = output.read_text(encoding="utf-8")
    assert '<Solution Reference="toy">' in payload
    assert "<Description>round trip</Description>" in payload
    assert parsed == (original,)
    assert validate_xhstt_solution(problem, parsed[0]).errors == ()


def test_basic_native_solver_is_deadline_safe_and_finds_hard_feasibility(
    tmp_path: Path,
) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=2.0, seed=17, workers=1)

    assert result.deadline_overrun_seconds < 0.1
    assert result.validation.errors == ()
    assert result.validation.score.hard_cost == 0
    assert result.status in {"feasible", "partial_feasible"}


def test_native_solver_improves_a_feasible_structural_incumbent_on_soft_cost(
    tmp_path: Path,
) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=2.0, seed=17, workers=1)

    # The unit-incidence constructor yields a valid (0, 21) timetable for this
    # seed.  The general model must keep that incumbent fail-closed while using
    # its exact PreferTimes/SpreadEvents objective to reach the independent
    # evaluator's better lexicographic score across its encoded preference and
    # schedule-pattern families.
    assert result.validation.score.lexicographic == (0, 12)
    assert result.telemetry["returned_source"] == "native_cp_sat"
    assert result.telemetry["structural_incumbent_score"] == [0, 21]
    assert result.telemetry["objective_constraint_types"] == [
        "LimitBusyTimesConstraint",
        "PreferTimesConstraint",
        "SpreadEventsConstraint",
    ]


@pytest.mark.parametrize(
    "cost_function",
    ["Quadratic", "Step", "StepSum", "SquareSum"],
)
def test_soft_pattern_objective_matches_independent_nonlinear_costs(
    tmp_path: Path,
    cost_function: str,
) -> None:
    source = tmp_path / f"toy-{cost_function}.xml"
    source.write_text(
        _toy_archive().replace(
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            '<Required>false</Required><Weight>11</Weight>'
            "<CostFunction>Linear</CostFunction>",
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            '<Required>false</Required><Weight>11</Weight>'
            f"<CostFunction>{cost_function}</CostFunction>",
        ),
        encoding="utf-8",
    )
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=2.0, seed=17, workers=1)

    assert result.validation.score.lexicographic == (0, 12)
    assert result.telemetry["returned_source"] == "native_cp_sat"


def test_soft_link_objective_matches_independent_occupied_time_sets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "soft-link.xml"
    source.write_text(
        _toy_archive(
            extra_constraint="""
            <LinkEventsConstraint Id="link"><Name>link</Name><Required>false</Required><Weight>13</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="Course"/></EventGroups></AppliesTo></LinkEventsConstraint>
            """
        )
        .replace(
            '<Event Id="E1"><Name>E1</Name><Duration>1</Duration>',
            '<Event Id="E1"><Name>E1</Name><Duration>2</Duration>',
        )
        .replace(
            '<AppliesTo><ResourceGroups><ResourceGroup Reference="Teachers"/>'
            "</ResourceGroups></AppliesTo>",
            "<AppliesTo><ResourceGroups></ResourceGroups></AppliesTo>",
        ),
        encoding="utf-8",
    )
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=2.0, seed=17, workers=1)

    assert result.validation.score.lexicographic == (0, 20)
    assert result.telemetry["returned_source"] == "native_cp_sat"
    assert "LinkEventsConstraint" in result.telemetry[
        "objective_constraint_types"
    ]


def test_general_model_rescues_required_busy_pattern_after_coloring_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "hard-busy.xml"
    source.write_text(
        _toy_archive().replace(
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            "<Required>false</Required>",
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            "<Required>true</Required>",
        ),
        encoding="utf-8",
    )
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=2.0, seed=17, workers=1)

    assert result.validation.score.lexicographic == (0, 12)
    assert result.telemetry["returned_source"] == "native_cp_sat"
    assert "LimitBusyTimesConstraint" in result.telemetry[
        "encoded_constraint_types"
    ]
    assert result.telemetry["structural_incumbent_score"] is None


def test_resource_assignment_balances_variable_roles_before_time_coloring(
    tmp_path: Path,
) -> None:
    source = tmp_path / "balanced-resources.xml"
    source.write_text(_balanced_resource_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=1.0, seed=5, workers=1)

    assigned_rooms = {
        assignment.resource_id
        for meet in result.solution.meets
        for assignment in meet.resource_assignments
        if assignment.role == "Room"
    }
    assert assigned_rooms == {"R0", "R1"}
    assert result.validation.score.lexicographic == (0, 0)
    assert result.telemetry["returned_source"] == "incidence_coloring"
    assert result.telemetry["resource_assignment_complete"] is True
    assert result.telemetry["resource_assignment"]["maximum_assigned_load"] == 2


def test_scale_gate_returns_the_resource_complete_constructive_incumbent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scale-gated-resources.xml"
    source.write_text(_balanced_resource_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(
        problem,
        time_limit_seconds=1.0,
        seed=5,
        workers=1,
        max_cp_meets=0,
    )

    assign_resource_cost = next(
        cost.cost
        for cost in result.validation.score.constraint_costs
        if cost.constraint_type == "AssignResourceConstraint"
    )
    assert result.status == "scale_gated"
    assert result.telemetry["returned_source"] == "resource_assigned_fallback"
    assert assign_resource_cost == 0
    assert all(meet.time_id is None for meet in result.solution.meets)


def test_exact_resource_repair_recovers_a_greedy_capacity_trap() -> None:
    weights = (1, 2, 4, 3, 3, 2)
    domains = (
        ("R1",),
        ("R1", "R2"),
        ("R1",),
        ("R0", "R2"),
        ("R0",),
        ("R2",),
    )
    problem = XHSTTProblem(
        id="resource-trap",
        name="resource trap",
        times=tuple(XHSTTTime(f"T{index}", f"T{index}") for index in range(6)),
        time_groups=(),
        resource_types=(XHSTTResourceType("R", "R"),),
        resource_groups=(XHSTTResourceGroup("RG", "RG", "R"),),
        resources=tuple(
            XHSTTResource(f"R{index}", f"R{index}", "R", ("RG",))
            for index in range(3)
        ),
        event_groups=(XHSTTEventGroup("All", "All", "EventGroup"),),
        events=tuple(
            XHSTTEvent(
                id=f"E{index}",
                name=f"E{index}",
                duration=weight,
                resources=(XHSTTEventResource("Role", "R"),),
                event_group_ids=("All",),
            )
            for index, weight in enumerate(weights)
        ),
        constraints=(
            XHSTTConstraint(
                "AssignResourceConstraint",
                "assign-resource",
                "assign-resource",
                True,
                1,
                "Linear",
                applies_event_group_ids=("All",),
                role="Role",
            ),
            *tuple(
                XHSTTConstraint(
                    "PreferResourcesConstraint",
                    f"domain-{index}",
                    f"domain-{index}",
                    True,
                    1,
                    "Linear",
                    applies_event_ids=(f"E{index}",),
                    role="Role",
                    preferred_resource_ids=domain,
                )
                for index, domain in enumerate(domains)
            ),
            XHSTTConstraint(
                "LimitWorkloadConstraint",
                "workload",
                "workload",
                True,
                1,
                "Linear",
                applies_resource_group_ids=("RG",),
                minimum=0,
                maximum=6,
            ),
        ),
    )

    result = solve_xhstt(
        problem,
        time_limit_seconds=0.5,
        seed=17,
        workers=1,
        max_cp_meets=0,
    )

    assert result.telemetry["resource_assignment"][
        "exact_assignment_status"
    ] == "validated_feasible"
    assert result.telemetry["resource_assignment"][
        "remaining_capacity_violation"
    ] == 0
    assert result.validation.score.hard_cost == 0
    assert all(
        assignment.resource_id in domains[int(meet.event_id[1:])]
        for meet in result.solution.meets
        for assignment in meet.resource_assignments
    )


def test_balanced_tensor_uses_matching_decomposition_without_copy_symmetry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "balanced.xml"
    source.write_text(_balanced_coloring_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(
        problem,
        time_limit_seconds=0.5,
        seed=11,
        workers=1,
    )

    assert result.telemetry["returned_source"] == "matching_decomposition"
    assert result.validation.score.lexicographic == (0, 0)
    assert result.validation.errors == ()
    assert len(result.solution.meets) == 8


def test_zero_budget_returns_a_structurally_valid_fail_closed_solution(
    tmp_path: Path,
) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)

    result = solve_xhstt(problem, time_limit_seconds=0.0, seed=3, workers=1)

    assert result.status == "deadline_during_build"
    assert result.validation.errors == ()
    assert result.validation.score.hard_cost > 0
    assert all(meet.time_id is None for meet in result.solution.meets)


def test_late_structural_candidate_is_rejected_for_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "toy.xml"
    source.write_text(_toy_archive(), encoding="utf-8")
    problem = parse_xhstt(source)
    real_validate = xhstt_module.validate_xhstt_solution

    def slow_candidate_validation(
        candidate_problem: xhstt_module.XHSTTProblem,
        candidate: XHSTTSolution,
    ) -> xhstt_module.XHSTTValidation:
        validation = real_validate(candidate_problem, candidate)
        if validation.feasible and all(
            meet.time_id is not None for meet in candidate.meets
        ):
            time.sleep(0.22)
        return validation

    monkeypatch.setattr(
        xhstt_module,
        "validate_xhstt_solution",
        slow_candidate_validation,
    )

    result = solve_xhstt(
        problem,
        time_limit_seconds=0.20,
        seed=17,
        workers=1,
    )

    assert result.telemetry["returned_source"] == "resource_assigned_fallback"
    assert result.telemetry["incidence_coloring"][
        "candidate_rejected_reason"
    ] == "deadline"
    assert all(meet.time_id is None for meet in result.solution.meets)
    assert result.deadline_overrun_seconds > 0.0


def test_late_native_candidate_cannot_replace_fail_closed_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "hard-busy.xml"
    source.write_text(
        _toy_archive().replace(
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            "<Required>false</Required>",
            '<LimitBusyTimesConstraint Id="busy"><Name>busy</Name>'
            "<Required>true</Required>",
        ),
        encoding="utf-8",
    )
    problem = parse_xhstt(source)
    real_validate = xhstt_module.validate_xhstt_solution

    def slow_feasible_validation(
        candidate_problem: xhstt_module.XHSTTProblem,
        candidate: XHSTTSolution,
    ) -> xhstt_module.XHSTTValidation:
        validation = real_validate(candidate_problem, candidate)
        if validation.feasible:
            time.sleep(0.32)
        return validation

    monkeypatch.setattr(
        xhstt_module,
        "validate_xhstt_solution",
        slow_feasible_validation,
    )

    result = solve_xhstt(
        problem,
        time_limit_seconds=0.30,
        seed=17,
        workers=1,
    )

    assert result.status == "deadline_after_validation"
    assert result.telemetry["returned_source"] == "resource_assigned_fallback"
    assert result.telemetry["candidate_rejected_reason"] == "deadline"
    assert all(meet.time_id is None for meet in result.solution.meets)
    assert result.deadline_overrun_seconds > 0.0


def test_current_official_archive_parser_covers_all_2014_constraint_families() -> None:
    source = Path("/tmp/planora-xhstt-2014/XHSTT-2014.xml")
    if not source.exists():
        pytest.skip("official XHSTT-2014 archive is not cached")

    archive = parse_xhstt_archive(source)

    assert len(archive.problems) == 25
    assert not {
        feature
        for problem in archive.problems
        for feature in problem.unsupported_features
    }


def test_cached_official_solution_report_agrees_when_available() -> None:
    source = Path("/tmp/planora-xhstt-all/FinlandHighSchool.xml")
    if not source.exists():
        pytest.skip("official XHSTT all-instances archive is not cached")

    archive = parse_xhstt_archive(source, include_solutions=True)
    problem = archive.problems[0]
    solution = archive.solutions[-1]
    validation = validate_xhstt_solution(problem, solution)

    assert solution.reported_score == (0, 0)
    assert validation.errors == ()
    assert validation.unsupported_features == ()
    assert validation.score.lexicographic == solution.reported_score


def test_cached_dense_hdtt_instance_uses_unit_matching_decomposition() -> None:
    source = Path("/tmp/planora-xhstt-all/ArtificialORLibrary-hdtt4.xml")
    if not source.exists():
        pytest.skip("official XHSTT all-instances archive is not cached")

    problem = parse_xhstt(source)
    result = solve_xhstt(
        problem,
        time_limit_seconds=1.5,
        seed=0,
        workers=1,
    )

    assert result.telemetry["returned_source"] == "matching_decomposition"
    assert result.telemetry["partition_mode"] == "aggregated_unit_meets"
    assert len(result.solution.meets) == sum(
        event.duration for event in problem.events
    )
    assert result.validation.errors == ()
    assert result.validation.score.lexicographic == (0, 0)
    assert result.deadline_overrun_seconds < 0.05
