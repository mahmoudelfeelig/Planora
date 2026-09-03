from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path

import pytest

from benchmarks import itc2007_ablation
from benchmarks.itc2007_ablation import (
    ArtifactIntegrityError,
    BenchmarkInputDrift,
    CONDITIONS,
    OFFICIAL_ITC2007_VALIDATOR_PINS,
    SourceSnapshotDrift,
    _record_digest,
    balanced_williams_orders,
    build_ablation_manifest,
    run_ablation_matrix,
    summarize_ablation_records,
    verify_ablation_artifacts,
    write_matrix_index,
)
from benchmarks.itc2007_harness import sha256_file


MINIMAL_INSTANCE = """\
Name: ablation-toy
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
CALIBRATION_HASHES = [f"{value:064x}" for value in (101, 102, 103, 104)]


def _complete_proof(*, attempted: bool) -> dict[str, object]:
    if not attempted:
        return {"attempted": False, "valid": None, "reason": "not_claim_bearing"}
    return {
        "attempted": True,
        "valid": True,
        "errors": [],
        "scope": "eligible_fixed_time_room_mathematical_certificate",
        "integrity": "unsigned_json_roundtrip",
        "verified_candidate_matches_returned_schedule": True,
        "roundtrip_seconds": 0.001,
        "replay_seconds": 0.002,
        "serialized_bytes": 128,
        "capacity_lower_bound": 0,
        "room_lower_bound": 0,
    }


def _validator_output(components: dict[str, int]) -> str:
    return "\n".join(
        [
            "Violations of Lectures (hard) : 0",
            "Violations of Conflicts (hard) : 0",
            "Violations of Availability (hard) : 0",
            "Violations of RoomOccupation (hard) : 0",
            f"Cost of RoomCapacity (soft) : {components['room_capacity']}",
            (
                "Cost of MinWorkingDays (soft) : "
                f"{components['minimum_working_days']}"
            ),
            (
                "Cost of CurriculumCompactness (soft) : "
                f"{components['curriculum_compactness']}"
            ),
            f"Cost of RoomStability (soft) : {components['room_stability']}",
            f"Summary: Violations = 0, Total Cost = {components['total']}",
            "",
        ]
    )


def _write_calibration_instances(
    tmp_path: Path,
    *,
    first: Path | None = None,
) -> list[Path]:
    paths = [first] if first is not None else []
    start = 1 if first is not None else 0
    for index in range(start, 4):
        path = tmp_path / f"calibration-{index}.ctt"
        path.write_text(
            MINIMAL_INSTANCE.replace(
                "Name: ablation-toy",
                f"Name: calibration-{index}",
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return [path for path in paths if path is not None]


def test_balanced_williams_order_balances_position_and_first_order_carryover() -> None:
    orders = balanced_williams_orders()
    condition_ids = tuple(condition.condition_id for condition in CONDITIONS)

    assert orders[0] == (
        "control_compact_off",
        "control_compact_on",
        "cp_only_compact_on",
        "oracle_only_compact_off",
        "cp_only_compact_off",
        "oracle_only_compact_on",
    )
    assert len(orders) == len(condition_ids) == 6
    for position in range(6):
        assert {order[position] for order in orders} == set(condition_ids)

    carryovers = Counter(
        (order[index], order[index + 1])
        for order in orders
        for index in range(len(order) - 1)
    )
    assert len(carryovers) == 30
    assert set(carryovers.values()) == {1}


def test_68_cell_joint_cpsolver_design_balances_positions_and_carryover() -> None:
    instance_rows = [
        {"instance_id": f"i{index:02d}", "sha256": f"{index + 1:064x}"}
        for index in range(34)
    ]
    cells = itc2007_ablation._build_execution_cells(
        instance_rows,
        [17, 29],
        include_cpsolver=True,
    )
    positions = Counter(
        (task_id, position)
        for cell in cells
        for position, task_id in enumerate(cell["execution_order"])
    )
    carryovers = Counter(
        pair
        for cell in cells
        for pair in zip(
            cell["execution_order"],
            cell["execution_order"][1:],
        )
    )

    assert len(cells) == 68
    assert len(positions) == 49
    assert min(positions.values()) == 9
    assert max(positions.values()) == 10
    assert len(carryovers) == 42
    assert min(carryovers.values()) == 9
    assert max(carryovers.values()) == 10


def test_source_drift_aborts_before_any_condition_and_freezes_incomplete_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "toy.ctt"
    instance.write_text(MINIMAL_INSTANCE, encoding="utf-8")
    validator = tmp_path / "validator"
    validator.write_text("validator", encoding="utf-8")
    calls = 0

    def drifting_snapshot(_repo_root: str | Path):
        nonlocal calls
        calls += 1
        digest = "a" * 64 if calls == 1 else "b" * 64
        return digest, {"benchmarks/example.py": digest}

    monkeypatch.setattr(
        itc2007_ablation,
        "planora_source_snapshot",
        drifting_snapshot,
    )
    output = tmp_path / "matrix"

    with pytest.raises(SourceSnapshotDrift, match="before cell 0"):
        run_ablation_matrix(
            repo_root=Path(__file__).resolve().parents[1],
            output_directory=output,
            instances=[instance],
            seeds=[17],
            time_limit_seconds=1.0,
            validator_command=[validator],
        )

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert summary["record_count"] == 0
    assert summary["source_stable"] is False
    assert "SourceSnapshotDrift" in summary["aborted_reason"]
    assert summary["publication_gate"]["status"] == "NO-GO"
    verification = verify_ablation_artifacts(output)
    assert verification["valid"] is True
    assert verification["complete"] is False


def test_manifest_uses_content_hashes_for_corpus_family_and_calibration_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "renamed-input.ctt"
    instance.write_text(MINIMAL_INSTANCE, encoding="utf-8")
    instance_sha256 = sha256_file(instance)
    validator = tmp_path / "validator"
    validator.write_text("validator", encoding="utf-8")
    provenance = tmp_path / "PROVENANCE.json"
    provenance.write_text(
        json.dumps(
            {
                "schema_version": "planora.cbctt-external-corpus.v1",
                "corpus": {
                    "projection_scope": "standard_itc2007_four_term_only",
                    "source_manifest_sha256": "b" * 64,
                    "projection_set_sha256": "c" * 64,
                },
                "instances": [
                    {
                        "family": "EasyAcademy",
                        "projected_relative_path": (
                            "projected-itc2007/EasyAcademy/EA01.ctt"
                        ),
                        "projected_sha256": instance_sha256,
                        "source_relative_path": "raw/EasyAcademy/EA01.ectt",
                        "source_sha256": "d" * 64,
                        "projection": {
                            "extension_losses": {"course_room_constraint_rows": 7}
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        itc2007_ablation,
        "planora_source_snapshot",
        lambda _repo_root: ("a" * 64, {"benchmarks/example.py": "a" * 64}),
    )

    manifest = build_ablation_manifest(
        repo_root=Path(__file__).resolve().parents[1],
        instances=[instance],
        seeds=[17],
        time_limit_seconds=1.0,
        validator_command=[validator],
        provenance_json=provenance,
        compact_calibration_instances=_write_calibration_instances(
            tmp_path,
            first=instance,
        ),
    )

    instance_row = manifest["instances"][0]
    assert instance_row["corpus"]["family"] == "EasyAcademy"
    assert instance_row["corpus"]["provenance_match"] == "projected_sha256"
    assert instance_row["corpus"]["extension_losses"] == {
        "course_room_constraint_rows": 7
    }
    assert instance_row["compact_policy_partition"] == "calibration"
    assert manifest["compact_policy_calibration"]["cardinality_gate"] == "PASS"
    assert manifest["compact_policy_calibration"][
        "canonical_file_evidence_verified"
    ] is True
    assert itc2007_ablation._manifest_publication_evidence(manifest)[
        "compact_calibration_evidence_verified"
    ] is True
    assert "scripts/analyze_experiments.py" in manifest["planora_source_files"]
    assert "scripts/benchmark_itc2007_ablation.py" in manifest[
        "planora_source_files"
    ]


def test_orchestrator_runs_the_six_cells_in_williams_order_with_fresh_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "toy.ctt"
    instance.write_text(MINIMAL_INSTANCE, encoding="utf-8")
    validator = tmp_path / "validator"
    validator.write_text("validator", encoding="utf-8")
    source_sha256 = "a" * 64
    monkeypatch.setattr(
        itc2007_ablation,
        "planora_source_snapshot",
        lambda _repo_root: (
            source_sha256,
            {"benchmarks/itc2007_ablation.py": source_sha256},
        ),
    )
    calls: list[tuple[str, bool, Path]] = []

    def fake_planora_case(**kwargs):
        strategy = str(kwargs["itc2007_fixed_time_room_strategy"])
        compact = bool(kwargs["itc2007_compact_adaptive_arms"])
        run_directory = Path(kwargs["run_directory"])
        run_directory.mkdir(parents=True, exist_ok=False)
        solution = run_directory / "solution.out"
        solution.write_text("C1 R1 0 0\n", encoding="utf-8")
        objective = {
            ("control", False): 100,
            ("control", True): 95,
            ("oracle_only", False): 90,
            ("oracle_only", True): 82,
            ("cp_only", False): 88,
            ("cp_only", True): 84,
        }[(strategy, compact)]
        components = {
            "room_capacity": objective - 60,
            "minimum_working_days": 20,
            "curriculum_compactness": 30,
            "room_stability": 10,
            "total": objective,
        }
        improvement = {
            ("control", False): 0,
            ("control", True): 0,
            ("oracle_only", False): 10,
            ("oracle_only", True): 13,
            ("cp_only", False): 12,
            ("cp_only", True): 11,
        }[(strategy, compact)]
        proof = _complete_proof(attempted=strategy == "oracle_only")
        worker = run_directory / "worker.json"
        worker.write_text(
            json.dumps(
                {
                    "official_score_internal": components,
                    "strategy_meta": {
                        "fixed_time_room_proof_replay": proof,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        validator_log = run_directory / "validator.log"
        validator_log.write_text(_validator_output(components), encoding="utf-8")
        stdout = run_directory / "stdout.log"
        stderr = run_directory / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        calls.append((strategy, compact, run_directory))
        return {
            "solver_id": "planora",
            "instance_id": instance.stem,
            "instance_path": str(instance),
            "instance_sha256": sha256_file(instance),
            "seed": kwargs["seed"],
            "workers": kwargs["workers"],
            "time_limit_seconds": kwargs["time_limit_seconds"],
            "strategy": kwargs["strategy"],
            "itc2007_fixed_time_room_dive": True,
            "itc2007_fixed_time_room_strategy": strategy,
            "itc2007_compact_adaptive_arms": compact,
            "status": "FEASIBLE",
            "feasible": True,
            "hard_violations": 0,
            "official_objective": objective,
            "official_components": components,
            "solution_path": str(solution),
            "solution_sha256": sha256_file(solution),
            "worker_metadata_path": str(worker),
            "validator_output_path": str(validator_log),
            "stdout_path": str(stdout),
            "stderr_path": str(stderr),
            "worker_wall_time_seconds": 0.5,
            "wall_time_seconds": 0.6,
            "timed_out": False,
            "validator_error": None,
            "fixed_time_room_proof_replay": proof,
            "strategy_meta": {
                "timing": {
                    "budget_seconds": kwargs["time_limit_seconds"],
                    "elapsed_seconds": 0.5,
                    "deadline_overrun_seconds": 0.0,
                },
                "adaptive_lns": {
                        "fixed_time_room_dive": {
                            "strategy": strategy,
                            "incumbent_fixed_time_fingerprint": (
                                f"{(17_000 + int(compact)):064x}"
                            ),
                        "improvement": improvement,
                        "returned_source": (
                            "fixed_time_room_oracle"
                            if strategy == "oracle_only"
                            else "fixed_time_room_dive"
                            if strategy == "cp_only"
                            else "incumbent"
                        ),
                        "deadline_overrun_seconds": 0.0,
                        "elapsed_seconds": (
                            0.05
                            if strategy == "oracle_only"
                            else 0.4
                            if strategy == "cp_only"
                            else 0.0
                        ),
                        "proof_scope": (
                            "fixed_time_room"
                            if strategy in {"oracle_only", "cp_only"}
                            else None
                        ),
                    }
                },
            },
        }

    monkeypatch.setattr(itc2007_ablation, "run_planora_case", fake_planora_case)
    output = tmp_path / "matrix"

    records, summary = run_ablation_matrix(
        repo_root=Path(__file__).resolve().parents[1],
        output_directory=output,
        instances=[instance],
        seeds=[17],
        time_limit_seconds=1.0,
        validator_command=[validator],
        minimum_effective_instances=1,
        compact_calibration_sha256=CALIBRATION_HASHES,
    )

    expected = [
        (
            itc2007_ablation.CONDITION_BY_ID[condition_id].fixed_time_room_strategy,
            itc2007_ablation.CONDITION_BY_ID[condition_id].compact_adaptive_arms,
        )
        for condition_id in itc2007_ablation.williams_order(0)
    ]
    assert [(strategy, compact) for strategy, compact, _ in calls] == expected
    assert len({run_directory for _, _, run_directory in calls}) == 6
    assert len(records) == 6
    assert summary["engineering_smoke_gate"]["status"] == "PASS"
    assert summary["publication_gate"]["status"] == "NO-GO"
    assert summary["publication_gate"]["requirements"]["condition_counts"] is False
    assert summary["publication_gate"]["requirements"][
        "immutable_cpsolver_comparator_coverage"
    ] is False
    assert verify_ablation_artifacts(output)["valid"] is True

    results_path = output / "results.jsonl"
    original_results = results_path.read_text(encoding="utf-8")

    def refresh_row_artifact(path: Path, artifact_name: str) -> None:
        relative = path.relative_to(output).as_posix()
        rows = [json.loads(line) for line in original_results.splitlines()]
        for row in rows:
            artifact = dict(dict(row.get("artifacts") or {}).get(artifact_name) or {})
            if artifact.get("path") == relative:
                artifact["sha256"] = sha256_file(path)
                artifact["bytes"] = path.stat().st_size
                row["artifacts"][artifact_name] = artifact
                row["record_payload_sha256"] = _record_digest(row)
        results_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    validator_log = next((output / "runs").rglob("validator.log"))
    original_validator_output = validator_log.read_text(encoding="utf-8")
    validator_log.write_text(
        original_validator_output + "Summary: Total Cost = 0\n",
        encoding="utf-8",
    )
    refresh_row_artifact(validator_log, "validator_output_path")
    write_matrix_index(
        output,
        complete=True,
        source_sha256=str(summary["source_snapshot_sha256"]),
    )
    with pytest.raises(ArtifactIntegrityError, match="validator output cannot be replayed"):
        verify_ablation_artifacts(output)
    validator_log.write_text(original_validator_output, encoding="utf-8")
    results_path.write_text(original_results, encoding="utf-8")

    worker_path = next((output / "runs").rglob("worker.json"))
    original_worker = worker_path.read_text(encoding="utf-8")
    worker_payload = json.loads(original_worker)
    worker_payload["strategy_meta"]["fixed_time_room_proof_replay"] = {
        "attempted": True,
        "valid": False,
    }
    worker_path.write_text(json.dumps(worker_payload) + "\n", encoding="utf-8")
    refresh_row_artifact(worker_path, "worker_metadata_path")
    write_matrix_index(
        output,
        complete=True,
        source_sha256=str(summary["source_snapshot_sha256"]),
    )
    with pytest.raises(ArtifactIntegrityError, match="proof replay diverges"):
        verify_ablation_artifacts(output)
    worker_path.write_text(original_worker, encoding="utf-8")
    results_path.write_text(original_results, encoding="utf-8")
    write_matrix_index(
        output,
        complete=True,
        source_sha256=str(summary["source_snapshot_sha256"]),
    )
    assert verify_ablation_artifacts(output)["valid"] is True

    stored_rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
    ]
    stored_rows[0]["tampered_after_freeze"] = True
    stored_rows[0]["record_payload_sha256"] = _record_digest(stored_rows[0])
    results_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in stored_rows),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        itc2007_ablation.analyze_ablation_directory(output)


def _synthetic_row(
    condition_id: str,
    instance_index: int,
    *,
    objective: int,
    room_capacity: int,
    room_stability: int,
    oracle_improvement: int = 0,
    seed: int = 17,
    cell_index: int | None = None,
    include_cpsolver_design: bool = False,
) -> dict[str, object]:
    condition = next(row for row in CONDITIONS if row.condition_id == condition_id)
    is_oracle = condition.fixed_time_room_strategy == "oracle_only"
    resolved_cell_index = (
        instance_index - 1 if cell_index is None else int(cell_index)
    )
    execution_orders = itc2007_ablation._execution_orders(
        include_cpsolver=include_cpsolver_design
    )
    execution_order = execution_orders[resolved_cell_index % len(execution_orders)]
    components = {
        "room_capacity": room_capacity,
        "minimum_working_days": 20,
        "curriculum_compactness": 30,
        "room_stability": room_stability,
        "total": objective,
    }
    return {
        "schema_version": itc2007_ablation.SCHEMA_VERSION,
        "condition_id": condition_id,
        "cell_index": resolved_cell_index,
        "williams_sequence_index": resolved_cell_index % len(execution_orders),
        "condition_execution_position": execution_order.index(condition_id),
        "solver_id": "planora",
        "strategy": "research_adaptive",
        "itc2007_fixed_time_room_dive": True,
        "itc2007_fixed_time_room_strategy": condition.fixed_time_room_strategy,
        "itc2007_compact_adaptive_arms": condition.compact_adaptive_arms,
        "instance_sha256": f"{instance_index:064x}",
        "seed": int(seed),
        "time_limit_seconds": 10.0,
        "source_snapshot_sha256": "f" * 64,
        "source_snapshot_match": True,
        "compact_policy_partition": "held_out",
        "status": "FEASIBLE",
        "feasible": True,
        "hard_violations": 0,
        "official_objective": objective,
        "official_components": components,
        "solution_sha256": "e" * 64,
        "worker_wall_time_seconds": 9.5,
        "wall_time_seconds": 9.8,
        "official_validation": {
            "solution_produced": True,
            "validator_attempted": True,
            "validator_completed": True,
            "externally_feasible": True,
            "internal_external_component_agreement": True,
        },
        "deadline": {
            "deadline_overrun_seconds": 0.0,
            "strict_pass": True,
        },
        "fixed_time_room_proof_replay": _complete_proof(attempted=is_oracle),
        "fixed_time_room_strategy_telemetry": {
            "strategy": condition.fixed_time_room_strategy,
            "incumbent_fixed_time_fingerprint": (
                f"{(instance_index * 100_000 + int(seed) * 10 + int(condition.compact_adaptive_arms)):064x}"
            ),
            "improvement": oracle_improvement,
            "elapsed_seconds": (
                0.05
                if condition.fixed_time_room_strategy == "oracle_only"
                else 0.4
                if condition.fixed_time_room_strategy == "cp_only"
                else 0.0
            ),
            "proof_scope": (
                "fixed_time_room"
                if condition.fixed_time_room_strategy in {"oracle_only", "cp_only"}
                else None
            ),
            "returned_source": (
                "fixed_time_room_oracle" if oracle_improvement else "incumbent"
            ),
        },
    }


def _factorial_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for instance_index in (1, 2):
        rows.extend(
            [
                _synthetic_row(
                    "control_compact_off",
                    instance_index,
                    objective=100 + instance_index,
                    room_capacity=40 + instance_index,
                    room_stability=10,
                ),
                _synthetic_row(
                    "control_compact_on",
                    instance_index,
                    objective=95 + instance_index,
                    room_capacity=35 + instance_index,
                    room_stability=10,
                ),
                _synthetic_row(
                    "oracle_only_compact_off",
                    instance_index,
                    objective=90 + instance_index,
                    room_capacity=32 + instance_index,
                    room_stability=8,
                    oracle_improvement=10,
                ),
                _synthetic_row(
                    "oracle_only_compact_on",
                    instance_index,
                    objective=82 + instance_index,
                    room_capacity=24 + instance_index,
                    room_stability=8,
                    oracle_improvement=13,
                ),
                _synthetic_row(
                    "cp_only_compact_off",
                    instance_index,
                    objective=88 + instance_index,
                    room_capacity=30 + instance_index,
                    room_stability=8,
                    oracle_improvement=12,
                ),
                _synthetic_row(
                    "cp_only_compact_on",
                    instance_index,
                    objective=84 + instance_index,
                    room_capacity=26 + instance_index,
                    room_stability=8,
                    oracle_improvement=11,
                ),
            ]
        )
    return rows


def _synthetic_cpsolver_row(
    instance_index: int,
    *,
    seed: int,
    cell_index: int,
    objective: int,
    room_capacity: int,
) -> dict[str, object]:
    execution_orders = itc2007_ablation._execution_orders(include_cpsolver=True)
    execution_order = execution_orders[int(cell_index) % len(execution_orders)]
    components = {
        "room_capacity": int(room_capacity),
        "minimum_working_days": 20,
        "curriculum_compactness": 30,
        "room_stability": 8,
        "total": int(objective),
    }
    return {
        "schema_version": itc2007_ablation.SCHEMA_VERSION,
        "condition_id": "cpsolver_reference",
        "cell_index": int(cell_index),
        "williams_sequence_index": int(cell_index) % len(execution_orders),
        "condition_execution_position": execution_order.index(
            "cpsolver_reference"
        ),
        "solver_id": "cpsolver-itc2007",
        "instance_sha256": f"{instance_index:064x}",
        "seed": int(seed),
        "time_limit_seconds": 10.0,
        "source_snapshot_sha256": "f" * 64,
        "source_snapshot_match": True,
        "compact_policy_partition": "held_out",
        "status": "FEASIBLE",
        "feasible": True,
        "hard_violations": 0,
        "official_objective": int(objective),
        "official_components": components,
        "solution_sha256": "d" * 64,
        "wall_time_seconds": 9.9,
        "official_validation": {
            "solution_produced": True,
            "validator_attempted": True,
            "validator_completed": True,
            "externally_feasible": True,
            "internal_external_component_agreement": None,
        },
        "deadline": {"strict_pass": True},
    }


def _publication_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for instance_offset in range(30):
        instance_index = 1001 + instance_offset
        delta = instance_offset % 5
        for seed_offset, seed in enumerate((17, 29)):
            cell_index = instance_offset * 2 + seed_offset
            rows.extend(
                [
                    _synthetic_row(
                        "control_compact_off",
                        instance_index,
                        objective=100 + delta,
                        room_capacity=40 + delta,
                        room_stability=10,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_row(
                        "control_compact_on",
                        instance_index,
                        objective=95 + delta,
                        room_capacity=35 + delta,
                        room_stability=10,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_row(
                        "oracle_only_compact_off",
                        instance_index,
                        objective=90 + delta,
                        room_capacity=32 + delta,
                        room_stability=8,
                        oracle_improvement=10,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_row(
                        "oracle_only_compact_on",
                        instance_index,
                        objective=82 + delta,
                        room_capacity=24 + delta,
                        room_stability=8,
                        oracle_improvement=13,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_row(
                        "cp_only_compact_off",
                        instance_index,
                        objective=88 + delta,
                        room_capacity=30 + delta,
                        room_stability=8,
                        oracle_improvement=12,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_row(
                        "cp_only_compact_on",
                        instance_index,
                        objective=84 + delta,
                        room_capacity=26 + delta,
                        room_stability=8,
                        oracle_improvement=11,
                        seed=seed,
                        cell_index=cell_index,
                        include_cpsolver_design=True,
                    ),
                    _synthetic_cpsolver_row(
                        instance_index,
                        seed=seed,
                        cell_index=cell_index,
                        objective=86 + delta,
                        room_capacity=28 + delta,
                    ),
                ]
            )
    return rows


def _publication_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    return summarize_ablation_records(
        rows,
        minimum_effective_instances=1,
        matrix_complete=True,
        planned_runs=30 * 2 * 7,
        source_sha256="f" * 64,
        bootstrap_resamples=50,
        compact_calibration_hashes=CALIBRATION_HASHES,
        compact_calibration_evidence_verified=True,
        official_validator_identity_verified=True,
        cpsolver_provenance_verified=True,
        execution_budget_contract_verified=True,
    )


def test_publication_gate_requires_full_non_vacuous_evidence() -> None:
    summary = _publication_summary(_publication_rows())

    assert summary["publication_gate"]["status"] == "PASS"
    assert summary["publication_gate"][
        "minimum_distinct_effective_instances_per_condition"
    ] == 30
    assert summary["publication_gate"]["observed_distinct_seeds"] == [17, 29]
    assert summary["proof_replay"]["publication_coverage_gate"] is True
    assert all(
        row["complete_effective_run_coverage"] is True
        for row in summary["proof_replay"][
            "publication_coverage_by_oracle_condition"
        ]
    )
    assert summary["cpsolver_reference"]["publication_gate"] == "PASS"
    assert summary["cpsolver_reference"][
        "effective_distinct_held_out_instances"
    ] == 30
    assert all(
        comparison["feasibility_first"]["both_feasible"] == 60
        for comparison in summary["cpsolver_reference"]["comparisons"]
    )


def test_publication_gate_rejects_missing_comparator_and_vacuous_proofs() -> None:
    rows = _publication_rows()
    without_comparator = [
        row for row in rows if row["condition_id"] != "cpsolver_reference"
    ]
    comparator_summary = summarize_ablation_records(
        without_comparator,
        minimum_effective_instances=1,
        matrix_complete=True,
        planned_runs=len(without_comparator),
        source_sha256="f" * 64,
        bootstrap_resamples=25,
        compact_calibration_hashes=CALIBRATION_HASHES,
        compact_calibration_evidence_verified=True,
        official_validator_identity_verified=True,
        cpsolver_provenance_verified=True,
    )
    assert comparator_summary["publication_gate"]["status"] == "NO-GO"
    assert comparator_summary["publication_gate"]["requirements"][
        "immutable_cpsolver_comparator_coverage"
    ] is False

    without_proof = copy.deepcopy(rows)
    for row in without_proof:
        if str(row["condition_id"]).startswith("oracle_only"):
            row["fixed_time_room_proof_replay"] = _complete_proof(attempted=False)
    proof_summary = _publication_summary(without_proof)
    assert proof_summary["publication_gate"]["status"] == "NO-GO"
    assert proof_summary["proof_replay"]["claim_bearing_attempts"] == 0
    assert proof_summary["proof_replay"]["publication_coverage_gate"] is False

    mismatched_incumbent = copy.deepcopy(rows)
    oracle_row = next(
        row
        for row in mismatched_incumbent
        if row["condition_id"] == "oracle_only_compact_off"
    )
    oracle_row["fixed_time_room_strategy_telemetry"][
        "incumbent_fixed_time_fingerprint"
    ] = "0" * 64
    fingerprint_summary = _publication_summary(mismatched_incumbent)
    assert fingerprint_summary["publication_gate"]["status"] == "NO-GO"
    assert fingerprint_summary["publication_gate"]["requirements"][
        "identical_pre_finalization_fixed_time_incumbents"
    ] is False


def test_source_stability_override_cannot_mask_a_row_mismatch() -> None:
    rows = _publication_rows()
    rows[0]["source_snapshot_match"] = False

    with pytest.raises(ValueError, match="cannot force"):
        summarize_ablation_records(
            rows,
            matrix_complete=True,
            planned_runs=len(rows),
            source_sha256="f" * 64,
            bootstrap_resamples=10,
            compact_calibration_hashes=CALIBRATION_HASHES,
            source_stable_override=True,
        )


def test_summary_enforces_factorial_parity_effective_counts_and_direct_attribution() -> None:
    rows = _factorial_rows()
    summary = summarize_ablation_records(
        rows,
        minimum_effective_instances=2,
        matrix_complete=True,
        planned_runs=12,
        source_sha256="f" * 64,
        bootstrap_resamples=500,
        compact_calibration_hashes=CALIBRATION_HASHES,
    )

    assert summary["engineering_smoke_gate"]["status"] == "PASS"
    assert summary["publication_gate"]["status"] == "NO-GO"
    assert summary["condition_configuration_parity"] is True
    assert summary["factorial_cells"]["complete_condition_cells"] == 2
    assert summary["factorial_cells"]["required_conditions_per_cell"] == 6
    assert all(
        condition["effective_distinct_instances"] == 2
        for condition in summary["conditions"]
    )
    control = next(
        condition
        for condition in summary["conditions"]
        if condition["condition_id"] == "control_compact_off"
    )
    assert control["official_objective_sum"] == 203
    assert control["official_component_sums"]["room_capacity"] == 83

    attribution = summary["oracle_direct_attribution"]
    assert attribution["interaction"]["effective_complete_factorial_pairs"] == 2
    assert attribution["interaction"]["mean"] == 3.0
    assert all(
        stratum["telemetry_agreement"]["all_agree"]
        for stratum in attribution["strata"]
    )
    assert all(
        stratum["telemetry_agreement"]["all_non_room_components_unchanged"]
        for stratum in attribution["strata"]
    )
    oracle_vs_cp = summary["oracle_vs_full_cp_fixed_time"]
    assert len(oracle_vs_cp["strata"]) == 2
    assert all(stratum["effective_pairs"] == 2 for stratum in oracle_vs_cp["strata"])
    assert all(
        stratum["finalization_elapsed_oracle_minus_cp_seconds"]["median"] < 0
        for stratum in oracle_vs_cp["strata"]
    )

    rows[2]["fixed_time_room_proof_replay"] = {
        "attempted": True,
        "valid": False,
    }
    rejected = summarize_ablation_records(
        rows,
        minimum_effective_instances=2,
        matrix_complete=True,
        planned_runs=12,
        source_sha256="f" * 64,
        bootstrap_resamples=100,
        compact_calibration_hashes=CALIBRATION_HASHES,
    )
    oracle_off = next(
        condition
        for condition in rejected["conditions"]
        if condition["condition_id"] == "oracle_only_compact_off"
    )
    assert oracle_off["effective_distinct_instances"] == 1
    assert oracle_off["exclusion_reasons"]["claim_bearing_proof_replay_failed"] == 1
    assert rejected["publication_gate"]["status"] == "NO-GO"


def test_compact_policy_gate_excludes_declared_calibration_hashes() -> None:
    rows = _factorial_rows()
    calibration_hash = f"{1:064x}"
    calibration_hashes = [calibration_hash, *CALIBRATION_HASHES[:3]]
    for row in rows:
        if row["instance_sha256"] == calibration_hash:
            row["compact_policy_partition"] = "calibration"

    summary = summarize_ablation_records(
        rows,
        minimum_effective_instances=2,
        matrix_complete=True,
        planned_runs=12,
        source_sha256="f" * 64,
        bootstrap_resamples=100,
        compact_calibration_hashes=calibration_hashes,
    )

    assert summary["publication_gate"]["status"] == "NO-GO"
    assert summary["compact_policy_effects"]["publication_gate"] == "NO-GO"
    assert all(
        condition["effective_distinct_instances_all"] == 2
        and condition["effective_distinct_held_out_instances"] == 1
        and condition["effective_distinct_calibration_instances"] == 1
        for condition in summary["conditions"]
    )
    assert all(
        comparison["effective_distinct_instances"] == 1
        for comparison in summary["compact_policy_effects"]["held_out"]
    )


def test_manifest_rejects_unverifiable_calibration_and_validator_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "toy.ctt"
    instance.write_text(MINIMAL_INSTANCE, encoding="utf-8")
    validator = tmp_path / "validator"
    validator.write_text("not-the-official-validator", encoding="utf-8")
    monkeypatch.setattr(
        itc2007_ablation,
        "planora_source_snapshot",
        lambda _repo_root: ("a" * 64, {"benchmarks/example.py": "a" * 64}),
    )

    bare_hash_manifest = build_ablation_manifest(
        repo_root=Path(__file__).resolve().parents[1],
        instances=[instance],
        seeds=[17],
        time_limit_seconds=1.0,
        validator_command=[validator],
        compact_calibration_sha256=CALIBRATION_HASHES,
    )
    calibration = bare_hash_manifest["compact_policy_calibration"]
    assert calibration["cardinality_gate"] == "NO-GO"
    assert calibration["canonical_file_evidence_verified"] is False
    assert calibration["path_evidence"] == []

    calibration_paths = _write_calibration_instances(tmp_path)
    with pytest.raises(BenchmarkInputDrift, match="do not exactly match"):
        build_ablation_manifest(
            repo_root=Path(__file__).resolve().parents[1],
            instances=[instance],
            seeds=[17],
            time_limit_seconds=1.0,
            validator_command=[validator],
            compact_calibration_instances=calibration_paths,
            compact_calibration_sha256=CALIBRATION_HASHES,
        )

    validator_sha256 = sha256_file(validator)
    unrecognized_manifest = build_ablation_manifest(
        repo_root=Path(__file__).resolve().parents[1],
        instances=[instance],
        seeds=[17],
        time_limit_seconds=1.0,
        validator_command=[validator],
        official_validator_sha256=validator_sha256,
    )
    assert validator_sha256 not in OFFICIAL_ITC2007_VALIDATOR_PINS
    assert unrecognized_manifest["validator"]["explicit_pin_match"] is True
    assert unrecognized_manifest["validator"]["identity_gate"] == "NO-GO"
    assert unrecognized_manifest["validator"][
        "official_identity_verified"
    ] is False

    with pytest.raises(ValueError, match="Interpreter-based validator provenance"):
        build_ablation_manifest(
            repo_root=Path(__file__).resolve().parents[1],
            instances=[instance],
            seeds=[17],
            time_limit_seconds=1.0,
            validator_command=[itc2007_ablation.sys.executable, "-c", "print(0)"],
        )


def test_manifest_reconstructs_williams_plan_and_tracks_full_cpsolver_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "toy.ctt"
    instance.write_text(MINIMAL_INSTANCE, encoding="utf-8")
    validator = tmp_path / "validator"
    validator.write_text("validator", encoding="utf-8")
    cpsolver_root = tmp_path / "cpsolver"
    classes = tmp_path / "classes"
    source = cpsolver_root / "src"
    libraries = cpsolver_root / "lib"
    for directory in (classes, source, libraries):
        directory.mkdir(parents=True)
    (classes / "ItcTest.class").write_bytes(b"class-v1")
    properties = source / "ctt.properties"
    properties.write_text("Termination.TimeOut=10\n", encoding="utf-8")
    (libraries / "runtime.jar").write_bytes(b"jar-v1")
    java = tmp_path / "java"
    java.write_bytes(b"java-v1")
    monkeypatch.setattr(
        itc2007_ablation,
        "planora_source_snapshot",
        lambda _repo_root: ("a" * 64, {"benchmarks/example.py": "a" * 64}),
    )

    manifest = build_ablation_manifest(
        repo_root=Path(__file__).resolve().parents[1],
        instances=[instance],
        seeds=[17, 29],
        time_limit_seconds=10.0,
        validator_command=[validator],
        include_cpsolver=True,
        cpsolver_root=cpsolver_root,
        classes_path=classes,
        java_command=java,
        java_xmx_mb=768,
    )
    assert manifest["cpsolver"]["java_xmx_mb"] == 768
    assert manifest["cpsolver"]["source_resources_sha256"]
    assert manifest["cpsolver"]["libraries_sha256"]
    itc2007_ablation._verify_manifest_execution(manifest, [])

    malformed = copy.deepcopy(manifest)
    malformed["execution_design"]["cells"][0]["execution_order"] = list(
        reversed(malformed["execution_design"]["cells"][0]["execution_order"])
    )
    with pytest.raises(ArtifactIntegrityError, match="canonical Williams"):
        itc2007_ablation._verify_manifest_execution(malformed, [])

    assert itc2007_ablation._manifest_publication_evidence(manifest)[
        "cpsolver_provenance_verified"
    ] is True
    properties.write_text("Termination.TimeOut=20\n", encoding="utf-8")
    assert itc2007_ablation._manifest_publication_evidence(manifest)[
        "cpsolver_provenance_verified"
    ] is False
    with pytest.raises(BenchmarkInputDrift, match="runtime source/resources changed"):
        itc2007_ablation._assert_cpsolver_unchanged(manifest, phase="after test")


def test_matrix_index_detects_artifact_tampering(tmp_path: Path) -> None:
    output = tmp_path / "matrix"
    output.mkdir()
    source_sha256 = "a" * 64
    (output / "manifest.json").write_text(
        json.dumps({"planora_source_sha256": source_sha256}) + "\n",
        encoding="utf-8",
    )
    row: dict[str, object] = {
        "source_snapshot_sha256": source_sha256,
        "official_validation": {
            "solution_produced": False,
            "validator_attempted": False,
        },
    }
    row["record_payload_sha256"] = _record_digest(row)
    (output / "results.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps({"complete": True, "record_count": 1}) + "\n",
        encoding="utf-8",
    )
    run_directory = output / "runs/example"
    run_directory.mkdir(parents=True)
    (run_directory / "validator.log").write_text("official", encoding="utf-8")

    write_matrix_index(output, complete=True, source_sha256=source_sha256)

    verified = verify_ablation_artifacts(output)
    assert verified["valid"] is True
    assert verified["artifact_count"] == 4

    (run_directory / "validator.log").write_text("tampered", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        verify_ablation_artifacts(output)
