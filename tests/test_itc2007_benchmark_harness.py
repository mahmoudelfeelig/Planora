from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from benchmarks.itc2007 import (
    convert_itc2007_to_instance,
    parse_itc2007_ctt,
    score_itc2007_schedule,
)
from benchmarks.itc2007_harness import (
    BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES,
    SOLVER_CPSOLVER,
    SOLVER_PLANORA,
    _child_environment,
    _offline_fixed_time_room_proof_replay,
    build_cpsolver_command,
    run_benchmark_matrix,
    run_planora_worker,
    summarize_records,
)
from core.fixed_time_room_oracle import optimize_fixed_time_rooms
from core.solver_cp_sat import TimetableSolver
from services.solver_service import _adaptive_acceptance_score
from services import solver_service
from utils.specs import validate_schedule_against_instance


ZERO_SCORE_INSTANCE = """\
Name: zero-score
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


SCORING_INSTANCE = """\
Name: score
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


AUXILIARY_INSTANCE = """\
Name: auxiliary
Courses: 1
Rooms: 2
Days: 1
Periods_per_day: 1
Curricula: 0
Constraints: 0
COURSES:
C1 T1 1 1 10
ROOMS:
R1 20
R2 20
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def test_child_environment_removes_behavior_changing_inherited_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "poisoned")
    monkeypatch.setenv("PLANORA_UNRELATED_TEST_VALUE", "preserved")

    environment = _child_environment()

    assert all(
        name not in environment
        for name in BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES
    )
    assert environment["PLANORA_UNRELATED_TEST_VALUE"] == "preserved"
    assert environment["PYTHONHASHSEED"] == "0"
    assert environment["OMP_NUM_THREADS"] == "1"
    assert environment["OPENBLAS_NUM_THREADS"] == "1"


def test_pre_finalization_fingerprint_ignores_rooms_but_not_lecture_times() -> None:
    schedule = {
        1: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 1},
        2: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 2},
    }
    room_change = {
        activity_id: {**row, "room_id": 3}
        for activity_id, row in schedule.items()
    }
    time_change = {
        activity_id: dict(row) for activity_id, row in schedule.items()
    }
    time_change[2]["slot"] = 2

    fingerprint = solver_service._fixed_time_schedule_fingerprint(schedule)

    assert fingerprint == solver_service._fixed_time_schedule_fingerprint(
        room_change
    )
    assert fingerprint != solver_service._fixed_time_schedule_fingerprint(
        time_change
    )


def test_cpsolver_command_pins_runtime_contract(tmp_path: Path) -> None:
    root = tmp_path / "cpsolver"
    classes = tmp_path / "classes"
    instance = tmp_path / "comp01.ctt"
    solution = tmp_path / "solution.out"
    command = build_cpsolver_command(
        java_command="java",
        cpsolver_root=root,
        classes_path=classes,
        instance_path=instance,
        solution_path=solution,
        time_limit_seconds=30,
        seed=17,
        java_xmx_mb=768,
    )

    assert command[:3] == ["java", "-Xmx768m", "-XX:ActiveProcessorCount=1"]
    assert command[-5:] == ["ctt", str(instance), str(solution), "30", "17"]
    assert str(classes) in command[4]
    assert str(root / "src") in command[4]


def test_adaptive_acceptance_uses_the_official_itc2007_objective(tmp_path: Path) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    inst = convert_itc2007_to_instance(problem)
    c1 = [activity_id for activity_id, row in inst.activities.items() if row.course_id == 1]
    c2 = [activity_id for activity_id, row in inst.activities.items() if row.course_id == 2]
    schedule = {
        c1[0]: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 1},
        c1[1]: {"week": 1, "day": "D1", "slot": 0, "duration": 1, "room_id": 2},
        c2[0]: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 2},
    }

    score, objective_id = _adaptive_acceptance_score(inst, schedule)

    assert objective_id == "itc2007_official"
    assert score == score_itc2007_schedule(problem, inst, schedule).total == 18


def test_fixed_time_room_dive_improves_itc_rooms_without_moving_lectures(
    tmp_path: Path,
) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    inst = convert_itc2007_to_instance(problem)
    c1 = sorted(
        activity_id
        for activity_id, row in inst.activities.items()
        if row.course_id == 1
    )
    c2 = sorted(
        activity_id
        for activity_id, row in inst.activities.items()
        if row.course_id == 2
    )
    incumbent = {
        c1[0]: {
            "week": 1,
            "day": "D0",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [],
            "kind": "LEC",
        },
        c1[1]: {
            "week": 1,
            "day": "D1",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [],
            "kind": "LEC",
        },
        c2[0]: {
            "week": 1,
            "day": "D0",
            "slot": 1,
            "duration": 1,
            "room_id": 2,
            "staff_id": 2,
            "course_id": 2,
            "group_ids": [],
            "kind": "LEC",
        },
    }
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    candidate, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        model,
        budget_seconds=1.0,
        final_deadline=None,
        workers=1,
        seed=19,
    )

    assert meta["status"] == "ACCEPTED_IMPROVEMENT"
    assert meta["returned_source"] == "fixed_time_room_dive"
    assert meta["fixed_starts_preserved"] is True
    assert meta["validation"]["valid"] is True
    assert meta["pre_room_components"]["room_capacity"] == 30
    assert meta["post_room_components"]["room_capacity"] == 0
    assert meta["improvement"] == 30
    assert all(
        (candidate[activity_id]["day"], candidate[activity_id]["slot"])
        == (incumbent[activity_id]["day"], incumbent[activity_id]["slot"])
        for activity_id in incumbent
    )
    assert validate_schedule_against_instance(
        inst,
        candidate,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_offline_room_certificate_replay_uses_the_preserved_incumbent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    activity_ids = sorted(inst.activities)
    incumbent = {
        activity_id: {
            "week": 1,
            "day": f"D{index // 2}",
            "slot": index % 2,
            "duration": 1,
            "room_id": 1,
            "staff_id": int(inst.activities[activity_id].prof_id),
            "course_id": int(inst.activities[activity_id].course_id),
            "group_ids": list(inst.activities[activity_id].group_ids),
            "kind": str(inst.activities[activity_id].kind),
        }
        for index, activity_id in enumerate(activity_ids)
    }
    result = optimize_fixed_time_rooms(inst, incumbent)
    assert result.best_schedule is not None
    adaptive = {
        "fixed_time_room_dive": {
            "oracle": result.to_dict(),
            "incumbent_room_assignment": [
                [int(activity_id), int(row["room_id"])]
                for activity_id, row in sorted(incumbent.items())
            ],
        }
    }

    replay = _offline_fixed_time_room_proof_replay(
        inst,
        result.best_schedule,
        adaptive,
    )

    assert replay["attempted"] is True
    assert replay["valid"] is True
    assert replay["errors"] == []
    assert replay["verified_candidate_matches_returned_schedule"] is True
    assert replay["scope"] == "eligible_fixed_time_room_mathematical_certificate"

    tampered_returned = {
        activity_id: dict(row)
        for activity_id, row in result.best_schedule.items()
    }
    first_activity = min(tampered_returned)
    tampered_returned[first_activity]["room_id"] = int(
        incumbent[first_activity]["room_id"]
    )
    if tampered_returned[first_activity]["room_id"] == result.best_schedule[
        first_activity
    ]["room_id"]:
        tampered_returned[first_activity]["room_id"] = 2

    rejected = _offline_fixed_time_room_proof_replay(
        inst,
        tampered_returned,
        adaptive,
    )

    assert rejected["attempted"] is True
    assert rejected["valid"] is False
    assert rejected["verified_candidate_matches_returned_schedule"] is False
    assert "verified_candidate_does_not_match_returned_schedule" in rejected["errors"]


@pytest.mark.parametrize(
    "variable_prefix",
    ["itc2007_missing_days", "itc2007_additional_rooms"],
)
def test_itc2007_objective_auxiliaries_are_functionally_channeled(
    tmp_path: Path,
    variable_prefix: str,
) -> None:
    source = tmp_path / "auxiliary.ctt"
    source.write_text(AUXILIARY_INSTANCE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    inst = convert_itc2007_to_instance(problem)
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)
    matching = [
        model.m.GetIntVarFromProtoIndex(index)
        for index, variable in enumerate(model.m.Proto().variables)
        if variable.name.startswith(variable_prefix)
    ]
    assert len(matching) == 1

    # The sole lecture necessarily uses the sole day and exactly one room, so
    # both official deficits are zero. A value of one must be impossible even
    # when CP-SAT stops at a merely feasible incumbent.
    model.m.Add(matching[0] == 1)
    _solver, status = model.solve(time_limit_seconds=2, workers=1, random_seed=3)

    assert int(status) == int(cp_model.INFEASIBLE)


def test_itc2007_course_lecture_orbits_use_strict_start_order(tmp_path: Path) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    inst.hard_constraints["enable_itc2007_course_symmetry"] = True
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)

    assert model.symmetry_report == {
        "family": "ITC-2007",
        "mode": "strict_start_order",
        "enabled": True,
        "eligible_course_orbits": 1,
        "ordered_activity_pairs": 1,
        "skipped_course_ids": [],
    }
    solver, status = model.solve(time_limit_seconds=2, workers=1, random_seed=5)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    c1_ids = sorted(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 1
    )
    starts = [
        inst.days.index(str(schedule[activity_id]["day"])) * inst.slots_per_day
        + int(schedule[activity_id]["slot"])
        for activity_id in c1_ids
    ]
    assert starts[0] < starts[1]

    inst.hard_constraints["enable_itc2007_course_symmetry"] = False
    ablation_model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)
    assert ablation_model.symmetry_report["enabled"] is False
    assert ablation_model.symmetry_report["ordered_activity_pairs"] == 0


def test_itc2007_course_symmetry_skips_an_activity_specific_domain(tmp_path: Path) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    c1_ids = sorted(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 1
    )
    inst.activity_unavailability[c1_ids[0]] = {("D0", 0)}
    inst.hard_constraints["enable_itc2007_course_symmetry"] = True

    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)

    assert model.symmetry_report["eligible_course_orbits"] == 0
    assert model.symmetry_report["ordered_activity_pairs"] == 0
    assert model.symmetry_report["skipped_course_ids"] == [1]


def test_generic_symmetry_does_not_conflate_different_locked_domains(
    tmp_path: Path,
) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(SCORING_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    inst.sla_targets = {}
    c1_ids = sorted(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 1
    )
    c2_id = next(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 2
    )
    inst.locked_activities = {
        c1_ids[0]: {"day": "D1", "slot": 0, "room_id": 1},
        c1_ids[1]: {"day": "D0", "slot": 1, "room_id": 1},
        c2_id: {"day": "D0", "slot": 0, "room_id": 2},
    }

    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=False)
    solver, status = model.solve(time_limit_seconds=2, workers=1, random_seed=7)

    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    first_start = (
        inst.days.index(str(schedule[c1_ids[0]]["day"])) * inst.slots_per_day
        + int(schedule[c1_ids[0]]["slot"])
    )
    second_start = (
        inst.days.index(str(schedule[c1_ids[1]]["day"])) * inst.slots_per_day
        + int(schedule[c1_ids[1]]["slot"])
    )
    assert first_start > second_start


def test_summary_uses_feasibility_first_then_official_objective() -> None:
    common = {
        "instance_sha256": "a" * 64,
        "instance_id": "comp01",
        "seed": 17,
        "time_limit_seconds": 30.0,
        "wall_time_seconds": 30.5,
    }
    summary = summarize_records(
        [
            {
                **common,
                "solver_id": SOLVER_PLANORA,
                "feasible": True,
                "official_objective": 10,
            },
            {
                **common,
                "solver_id": SOLVER_CPSOLVER,
                "feasible": True,
                "official_objective": 6,
            },
        ]
    )

    assert summary["paired"]["cpsolver_wins"] == 1
    assert summary["paired"]["planora_wins"] == 0
    assert summary["paired"]["comparisons"][0]["objective_delta_planora_minus_cpsolver"] == 4


def test_matrix_writes_validator_backed_jsonl_and_summary(tmp_path: Path) -> None:
    source = tmp_path / "zero.ctt"
    source.write_text(ZERO_SCORE_INSTANCE, encoding="utf-8")
    fake_validator = tmp_path / "validator.py"
    fake_validator.write_text(
        """\
print("Violations of Lectures (hard) : 0")
print("Violations of Conflicts (hard) : 0")
print("Violations of Availability (hard) : 0")
print("Violations of RoomOccupation (hard) : 0")
print("Cost of RoomCapacity (soft) : 0")
print("Cost of MinWorkingDays (soft) : 0")
print("Cost of CurriculumCompactness (soft) : 0")
print("Cost of RoomStability (soft) : 0")
print("Summary: Total Cost = 0")
""",
        encoding="utf-8",
    )
    classes = tmp_path / "classes"
    classes.mkdir()
    output = tmp_path / "results"
    repo_root = Path(__file__).resolve().parents[1]

    records, summary = run_benchmark_matrix(
        repo_root=repo_root,
        output_directory=output,
        instances=[source],
        seeds=[3],
        time_limit_seconds=1,
        validator_command=[sys.executable, fake_validator],
        cpsolver_root=tmp_path,
        classes_path=classes,
        python_command=sys.executable,
        workers=1,
        strategy="exact_cp_sat",
        itc2007_stability_collision_weight=2,
        itc2007_stability_proxy_mode="fragmented_courses",
        supervision_grace_seconds=10,
        solvers=[SOLVER_PLANORA],
    )

    assert len(records) == 1
    assert records[0]["feasible"] is True
    assert records[0]["official_objective"] == 0
    assert records[0]["best_objective_bound"] == 0.0
    assert summary["aggregate"][SOLVER_PLANORA]["feasibility_rate"] == 1.0
    assert summary["complete"] is True
    assert summary["source_stable"] is True
    assert summary["completed_runs"] == summary["planned_runs"] == 1
    lines = (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["solution_sha256"] == records[0]["solution_sha256"]
    assert (output / "manifest.json").is_file()
    assert (output / "summary.json").is_file()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["itc2007_course_symmetry"] is False
    assert manifest["itc2007_adaptive_seeding"] is True
    assert manifest["itc2007_compact_adaptive_arms"] is False
    assert manifest["itc2007_fixed_time_room_dive"] is False
    assert manifest["itc2007_fixed_time_room_strategy"] == "oracle_then_cp"
    assert manifest["itc2007_stability_collision_weight"] == 2
    assert manifest["itc2007_stability_proxy_mode"] == "fragmented_courses"
    assert "core/solver_cp_sat.py" in manifest["planora_source_files"]
    assert records[0]["itc2007_course_symmetry"] is False
    assert records[0]["itc2007_adaptive_seeding"] is True
    assert records[0]["itc2007_compact_adaptive_arms"] is False
    assert records[0]["itc2007_fixed_time_room_dive"] is False
    assert records[0]["itc2007_fixed_time_room_strategy"] == "oracle_then_cp"
    assert records[0]["itc2007_stability_collision_weight"] == 2
    assert records[0]["itc2007_stability_proxy_mode"] == "fragmented_courses"
    assert records[0]["fixed_time_room_proof_replay"]["attempted"] is False
    assert records[0]["source_snapshot_match"] is True
    assert records[0]["cpu_time_seconds"] is None or records[0]["cpu_time_seconds"] >= 0
    assert records[0]["worker_cpu_time_seconds"] >= 0


@pytest.mark.parametrize(
    ("weight", "mode", "match"),
    [
        (0, "collision_events", "must be positive"),
        (1, "unknown", "unsupported"),
    ],
)
def test_planora_worker_rejects_invalid_support_proxy_options_before_io(
    tmp_path: Path,
    weight: int,
    mode: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        run_planora_worker(
            tmp_path / "missing.ctt",
            tmp_path / "solution.out",
            tmp_path / "metadata.json",
            seed=17,
            time_limit_seconds=1.0,
            itc2007_stability_collision_weight=weight,
            itc2007_stability_proxy_mode=mode,
        )
