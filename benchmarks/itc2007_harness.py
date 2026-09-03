from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None  # type: ignore[assignment]

from benchmarks.itc2007 import (
    ITC2007Validation,
    ITC2007ValidatorError,
    load_itc2007_instance,
    parse_itc2007_ctt,
    run_itc2007_validator,
    score_itc2007_instance_schedule,
    write_itc2007_solution,
)


SCHEMA_VERSION = "planora.itc2007-benchmark.v1"
SOLVER_PLANORA = "planora"
SOLVER_CPSOLVER = "cpsolver-itc2007"
PLANORA_SOURCE_ROOTS = ("benchmarks", "core", "services", "utils")
BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES = (
    "PYTHONHOME",
    "PYTHONPATH",
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
    "JDK_JAVA_OPTIONS",
    "TT_CP_ROOM_CANDIDATE_LIMIT",
    "TT_DECOMPOSITION_MAX_ROUNDS",
    "TT_PARTITION_WORKERS_CAP",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: str | Path) -> str:
    root = Path(path)
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = file_path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(file_path)))
    return digest.hexdigest()


def planora_source_snapshot(repo_root: str | Path) -> tuple[str, dict[str, str]]:
    """Hash every Planora source file that can affect an ITC-2007 run."""

    root = Path(repo_root).resolve()
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    paths = sorted(
        path
        for source_root in PLANORA_SOURCE_ROOTS
        for path in (root / source_root).rglob("*.py")
        if path.is_file()
    )
    for path in paths:
        relative = path.relative_to(root).as_posix()
        file_digest = sha256_file(path)
        files[relative] = file_digest
        digest.update(relative.encode("utf-8"))
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest(), files


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _json_safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _status_name(raw_status: int) -> str:
    from ortools.sat.python import cp_model

    try:
        return cp_model.CpSolverStatus(int(raw_status)).name
    except ValueError:
        return f"STATUS_{int(raw_status)}"


def _set_cpu_affinity(cpu: int | None) -> None:
    if cpu is None:
        return
    if not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("CPU affinity is not supported on this platform")
    available = set(os.sched_getaffinity(0))
    if int(cpu) not in available:
        raise ValueError(f"CPU {cpu} is unavailable; allowed CPUs are {sorted(available)}")
    os.sched_setaffinity(0, {int(cpu)})


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES:
        environment.pop(name, None)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    return environment


def _cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    processor = str(platform.processor() or "").strip()
    if processor:
        return processor
    return None


def _offline_fixed_time_room_proof_replay(
    inst,
    returned_schedule: dict[int, dict[str, Any]],
    adaptive_meta: dict[str, Any],
) -> dict[str, Any]:
    """Replay claim-bearing oracle telemetry outside the timed solve path."""

    room_meta = dict(adaptive_meta.get("fixed_time_room_dive") or {})
    oracle_payload = room_meta.get("oracle")
    if not isinstance(oracle_payload, dict):
        return {
            "attempted": False,
            "valid": None,
            "reason": "oracle_payload_unavailable",
        }
    eligibility = oracle_payload.get("eligibility")
    status = str(oracle_payload.get("status", ""))
    if (
        status not in {"improved", "no_improvement"}
        or not isinstance(eligibility, dict)
        or eligibility.get("eligible") is not True
    ):
        return {
            "attempted": False,
            "valid": None,
            "reason": "oracle_result_not_claim_bearing",
            "oracle_status": status,
        }

    try:
        assignment_rows = room_meta.get("incumbent_room_assignment")
        if not isinstance(assignment_rows, list):
            raise ValueError("incumbent_room_assignment_missing")
        incumbent_rooms: dict[int, int] = {}
        for row in assignment_rows:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or type(row[0]) is not int
                or type(row[1]) is not int
                or int(row[0]) in incumbent_rooms
            ):
                raise ValueError("incumbent_room_assignment_noncanonical")
            incumbent_rooms[int(row[0])] = int(row[1])
        expected_ids = {int(value) for value in inst.activities}
        if set(incumbent_rooms) != expected_ids:
            raise ValueError("incumbent_room_assignment_incomplete")
        if set(int(value) for value in returned_schedule) != expected_ids:
            raise ValueError("returned_schedule_incomplete")
        incumbent_schedule = {
            int(activity_id): {
                **dict(returned_schedule[int(activity_id)]),
                "room_id": int(incumbent_rooms[int(activity_id)]),
            }
            for activity_id in sorted(expected_ids)
        }

        roundtrip_started = time.perf_counter()
        serialized = json.loads(
            json.dumps(oracle_payload, sort_keys=True, allow_nan=False)
        )
        roundtrip_seconds = float(time.perf_counter() - roundtrip_started)
        from core.fixed_time_room_proof_checker import (
            verify_fixed_time_room_oracle_result,
        )

        replay_started = time.perf_counter()
        verification = verify_fixed_time_room_oracle_result(
            inst,
            incumbent_schedule,
            serialized,
        )
        replay_seconds = float(time.perf_counter() - replay_started)
        replay_errors = [str(value) for value in verification.errors]
        verified_candidate = verification.candidate_schedule
        returned_fields = ("week", "day", "slot", "duration", "room_id")
        returned_candidate_matches = bool(
            verified_candidate is not None
            and set(int(value) for value in verified_candidate) == expected_ids
            and all(
                tuple(
                    verified_candidate[int(activity_id)].get(field)
                    for field in returned_fields
                )
                == tuple(
                    returned_schedule[int(activity_id)].get(field)
                    for field in returned_fields
                )
                for activity_id in expected_ids
            )
        )
        if not returned_candidate_matches:
            replay_errors.append("verified_candidate_does_not_match_returned_schedule")
        return {
            "attempted": True,
            "valid": bool(verification.valid and returned_candidate_matches),
            "errors": replay_errors,
            "oracle_status": status,
            "scope": "eligible_fixed_time_room_mathematical_certificate",
            "integrity": "unsigned_json_roundtrip",
            "verified_candidate_matches_returned_schedule": bool(
                returned_candidate_matches
            ),
            "roundtrip_seconds": roundtrip_seconds,
            "replay_seconds": replay_seconds,
            "serialized_bytes": len(
                json.dumps(serialized, sort_keys=True, allow_nan=False).encode(
                    "utf-8"
                )
            ),
            "capacity_lower_bound": verification.capacity_lower_bound,
            "room_lower_bound": verification.room_lower_bound,
            "exclusions": [
                "deadline_and_timing_provenance",
                "selected_start_sweeps_and_search_trajectory",
                "nonclaim_status_causality",
                "source_identity_and_signature",
                "official_external_validation",
            ],
        }
    except Exception as exc:
        return {
            "attempted": True,
            "valid": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "oracle_status": status,
            "scope": "eligible_fixed_time_room_mathematical_certificate",
        }


def run_planora_worker(
    instance_path: str | Path,
    solution_path: str | Path,
    metadata_path: str | Path,
    *,
    seed: int,
    time_limit_seconds: float,
    workers: int = 1,
    strategy: str = "research_adaptive",
    itc2007_course_symmetry: bool = False,
    itc2007_adaptive_seeding: bool = True,
    itc2007_compact_adaptive_arms: bool = False,
    itc2007_fixed_time_room_dive: bool = False,
    itc2007_fixed_time_room_strategy: str = "oracle_then_cp",
    itc2007_stability_collision_weight: int = 1,
    itc2007_stability_proxy_mode: str = "collision_events",
    cpu: int | None = None,
) -> dict[str, Any]:
    """Run one Planora case inside the already-isolated worker process."""

    if int(itc2007_stability_collision_weight) < 1:
        raise ValueError("itc2007_stability_collision_weight must be positive")
    if str(itc2007_stability_proxy_mode) not in {
        "collision_events",
        "fragmented_courses",
    }:
        raise ValueError("unsupported itc2007_stability_proxy_mode")

    _set_cpu_affinity(cpu)
    instance_path = Path(instance_path).resolve()
    solution_path = Path(solution_path).resolve()
    metadata_path = Path(metadata_path).resolve()
    problem = parse_itc2007_ctt(instance_path)
    inst = load_itc2007_instance(instance_path)
    inst.hard_constraints["enable_itc2007_course_symmetry"] = bool(
        itc2007_course_symmetry
    )
    inst.hard_constraints["enable_context_eligible_adaptive_arms"] = bool(
        itc2007_adaptive_seeding
    )
    inst.hard_constraints["enable_itc2007_compact_adaptive_arms"] = bool(
        itc2007_compact_adaptive_arms
    )
    started = time.perf_counter()
    cpu_started = time.process_time()

    if strategy in {"research_adaptive", "projected_hybrid"}:
        from services.contracts import SolveOptions
        from services.solver_service import solve_instance

        result = solve_instance(
            inst,
            SolveOptions(
                objective_profile="research_adaptive",
                time_limit_seconds=float(time_limit_seconds),
                workers=int(workers),
                random_seed=int(seed),
                adaptive_lns_seconds=0.0,
                projected_time_search=(strategy == "projected_hybrid"),
                projected_time_room_reserve_seconds=0.8,
                projected_time_stability_collision_weight=int(
                    itc2007_stability_collision_weight
                ),
                projected_time_stability_proxy_mode=str(itc2007_stability_proxy_mode),
                fixed_time_room_dive=bool(itc2007_fixed_time_room_dive),
                fixed_time_room_strategy=str(itc2007_fixed_time_room_strategy),
            ),
        )
        feasible = bool(result.is_feasible and result.schedule)
        schedule = result.schedule if feasible else {}
        attempts = [asdict(attempt) for attempt in result.attempts]
        raw_status = int(result.raw_status)
        adaptive = dict((result.meta or {}).get("adaptive_lns") or {})
        solver_objective = None
        best_bound = None
        relative_gap = None
        bound_scope = "unavailable_for_adaptive_incumbent"
        strategy_meta: dict[str, Any] = {
            "adaptive_lns": adaptive,
            "quality": dict((result.meta or {}).get("quality") or {}),
            "research_adaptive": dict(
                (result.meta or {}).get("research_adaptive") or {}
            ),
            "timing": dict((result.meta or {}).get("timing") or {}),
        }
    elif strategy == "exact_cp_sat":
        from ortools.sat.python import cp_model

        from core.solver_cp_sat import TimetableSolver

        model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)
        solver, status = model.solve(
            time_limit_seconds=float(time_limit_seconds),
            workers=int(workers),
            random_seed=int(seed),
            log_progress=False,
        )
        raw_status = int(status)
        feasible = raw_status in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
        schedule = model.extract_solution(solver) if feasible else {}
        solver_objective = (
            _json_safe_float(solver.ObjectiveValue()) if feasible else None
        )
        best_bound = _json_safe_float(solver.BestObjectiveBound())
        relative_gap = None
        if solver_objective is not None and best_bound is not None:
            relative_gap = max(0.0, solver_objective - best_bound) / max(
                1.0,
                abs(solver_objective),
            )
        attempts = [
            {
                "room_mode": "cp_rooms",
                "use_objective": True,
                "time_limit_seconds": float(time_limit_seconds),
                "raw_status": int(raw_status),
                "objective_value": solver_objective,
                "best_objective_bound": best_bound,
                "relative_gap": relative_gap,
            }
        ]
        bound_scope = "global_cp_sat_model"
        strategy_meta = {"symmetry": dict(model.symmetry_report)}
    else:
        raise ValueError(f"Unsupported Planora ITC-2007 strategy: {strategy}")

    solve_wall_time_seconds = float(time.perf_counter() - started)
    solve_cpu_time_seconds = float(time.process_time() - cpu_started)
    proof_replay = (
        _offline_fixed_time_room_proof_replay(inst, schedule, adaptive)
        if strategy == "research_adaptive" and feasible
        else {
            "attempted": False,
            "valid": None,
            "reason": "research_adaptive_feasible_schedule_required",
        }
    )
    strategy_meta["fixed_time_room_proof_replay"] = dict(proof_replay)

    official_score = None
    if feasible:
        write_itc2007_solution(solution_path, problem, inst, schedule)
        official_score = score_itc2007_instance_schedule(inst, schedule).to_dict()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "solver_id": SOLVER_PLANORA,
        "strategy": str(strategy),
        "raw_status": int(raw_status),
        "status": _status_name(raw_status),
        "feasible": bool(feasible),
        "solver_objective_value": solver_objective,
        "best_objective_bound": best_bound,
        "relative_gap": relative_gap,
        "bound_scope": str(bound_scope),
        "itc2007_course_symmetry": bool(itc2007_course_symmetry),
        "itc2007_adaptive_seeding": bool(itc2007_adaptive_seeding),
        "itc2007_compact_adaptive_arms": bool(itc2007_compact_adaptive_arms),
        "itc2007_fixed_time_room_dive": bool(itc2007_fixed_time_room_dive),
        "itc2007_fixed_time_room_strategy": str(itc2007_fixed_time_room_strategy),
        "itc2007_stability_collision_weight": int(itc2007_stability_collision_weight),
        "itc2007_stability_proxy_mode": str(itc2007_stability_proxy_mode),
        "official_score_internal": official_score,
        "attempts": attempts,
        "worker_wall_time_seconds": float(solve_wall_time_seconds),
        "worker_cpu_time_seconds": float(solve_cpu_time_seconds),
        "postsolve_proof_replay_wall_time_seconds": float(
            (proof_replay.get("roundtrip_seconds") or 0.0)
            + (proof_replay.get("replay_seconds") or 0.0)
        ),
        "worker_total_wall_time_seconds": float(time.perf_counter() - started),
        "worker_total_cpu_time_seconds": float(time.process_time() - cpu_started),
        "strategy_meta": strategy_meta,
    }
    _write_json(metadata_path, payload)
    return payload


def build_cpsolver_command(
    *,
    java_command: str | Path,
    cpsolver_root: str | Path,
    classes_path: str | Path,
    instance_path: str | Path,
    solution_path: str | Path,
    time_limit_seconds: float,
    seed: int,
    java_xmx_mb: int = 1024,
) -> list[str]:
    root = Path(cpsolver_root).resolve()
    classes = Path(classes_path).resolve()
    if not float(time_limit_seconds).is_integer():
        raise ValueError("CPSolver ITC-2007 requires an integer time limit")
    classpath = os.pathsep.join(
        [
            str(classes),
            str(root / "src"),
            str(root / "lib" / "*"),
        ]
    )
    return [
        str(java_command),
        f"-Xmx{int(java_xmx_mb)}m",
        "-XX:ActiveProcessorCount=1",
        "-cp",
        classpath,
        "net.sf.cpsolver.itc.ItcTest",
        "ctt",
        str(Path(instance_path).resolve()),
        str(Path(solution_path).resolve()),
        str(int(time_limit_seconds)),
        str(int(seed)),
    ]


def _run_process(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    cpu: int | None,
) -> dict[str, Any]:
    normalized = [str(part) for part in command]
    started = time.perf_counter()
    timed_out = False
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    usage_before = (
        resource.getrusage(resource.RUSAGE_CHILDREN)
        if resource is not None
        else None
    )

    def pin_child() -> None:
        _set_cpu_affinity(cpu)

    try:
        completed = subprocess.run(
            normalized,
            cwd=str(cwd),
            env=_child_environment(),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_seconds),
            preexec_fn=pin_child if cpu is not None and os.name == "posix" else None,
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
    wall = float(time.perf_counter() - started)
    usage_after = (
        resource.getrusage(resource.RUSAGE_CHILDREN)
        if resource is not None
        else None
    )
    cpu_time_seconds = (
        max(
            0.0,
            float(usage_after.ru_utime - usage_before.ru_utime)
            + float(usage_after.ru_stime - usage_before.ru_stime),
        )
        if usage_before is not None and usage_after is not None
        else None
    )
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "command": normalized,
        "exit_code": exit_code,
        "timed_out": bool(timed_out),
        "wall_time_seconds": wall,
        "cpu_time_seconds": (
            float(cpu_time_seconds) if cpu_time_seconds is not None else None
        ),
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
    }


def _base_record(
    *,
    solver_id: str,
    instance_path: Path,
    solution_path: Path,
    seed: int,
    time_limit_seconds: float,
    workers: int,
    cpu: int | None,
    execution_index: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "solver_id": str(solver_id),
        "instance_id": str(instance_path.stem),
        "instance_path": str(instance_path.resolve()),
        "instance_sha256": sha256_file(instance_path),
        "seed": int(seed),
        "time_limit_seconds": float(time_limit_seconds),
        "workers": int(workers),
        "cpu_affinity": int(cpu) if cpu is not None else None,
        "execution_index": int(execution_index),
        "solution_path": str(solution_path.resolve()),
        "solution_sha256": None,
        "status": "NOT_RUN",
        "feasible": False,
        "hard_violations": None,
        "official_objective": None,
        "official_components": None,
        "solver_objective_value": None,
        "best_objective_bound": None,
        "relative_gap": None,
        "bound_scope": "unavailable",
        "validator_error": None,
    }


def _attach_validation(
    record: dict[str, Any],
    validation: ITC2007Validation,
    *,
    validator_output_path: Path,
) -> None:
    validator_output_path.write_text(validation.stdout, encoding="utf-8")
    record.update(
        {
            "status": "FEASIBLE" if validation.feasible else "INVALID",
            "feasible": bool(validation.feasible),
            "hard_violations": int(validation.hard_violations),
            "official_objective": int(validation.total_cost),
            "official_components": validation.soft_score.to_dict(),
            "validator_output_path": str(validator_output_path.resolve()),
        }
    )


def _validate_solution_record(
    record: dict[str, Any],
    *,
    validator_command: Sequence[str | Path],
    instance_path: Path,
    solution_path: Path,
    validator_output_path: Path,
) -> None:
    if not solution_path.is_file():
        record["status"] = "NO_SOLUTION"
        return
    record["solution_sha256"] = sha256_file(solution_path)
    try:
        validation = run_itc2007_validator(
            validator_command,
            instance_path,
            solution_path,
        )
    except (ITC2007ValidatorError, ValueError, OSError) as exc:
        record["status"] = "VALIDATOR_ERROR"
        record["validator_error"] = f"{type(exc).__name__}: {exc}"
        return
    _attach_validation(
        record,
        validation,
        validator_output_path=validator_output_path,
    )


def run_planora_case(
    *,
    repo_root: str | Path,
    python_command: str | Path,
    validator_command: Sequence[str | Path],
    instance_path: str | Path,
    run_directory: str | Path,
    seed: int,
    time_limit_seconds: float,
    workers: int,
    strategy: str,
    itc2007_course_symmetry: bool,
    itc2007_adaptive_seeding: bool,
    itc2007_compact_adaptive_arms: bool,
    itc2007_fixed_time_room_dive: bool,
    itc2007_fixed_time_room_strategy: str,
    itc2007_stability_collision_weight: int,
    itc2007_stability_proxy_mode: str,
    cpu: int | None,
    supervision_grace_seconds: float,
    execution_index: int,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    instance_path = Path(instance_path).resolve()
    run_directory = Path(run_directory).resolve()
    run_directory.mkdir(parents=True, exist_ok=False)
    solution_path = run_directory / "solution.out"
    worker_metadata = run_directory / "worker.json"
    command = [
        str(python_command),
        "-m",
        "benchmarks.itc2007_harness",
        "planora-worker",
        "--instance",
        str(instance_path),
        "--solution",
        str(solution_path),
        "--metadata",
        str(worker_metadata),
        "--seed",
        str(int(seed)),
        "--time-limit-seconds",
        str(float(time_limit_seconds)),
        "--workers",
        str(int(workers)),
        "--strategy",
        str(strategy),
        "--itc2007-course-symmetry",
        "on" if itc2007_course_symmetry else "off",
        "--itc2007-adaptive-seeding",
        "on" if itc2007_adaptive_seeding else "off",
        "--itc2007-compact-adaptive-arms",
        "on" if itc2007_compact_adaptive_arms else "off",
        "--itc2007-fixed-time-room-dive",
        "on" if itc2007_fixed_time_room_dive else "off",
        "--itc2007-fixed-time-room-strategy",
        str(itc2007_fixed_time_room_strategy),
        "--itc2007-stability-collision-weight",
        str(int(itc2007_stability_collision_weight)),
        "--itc2007-stability-proxy-mode",
        str(itc2007_stability_proxy_mode),
    ]
    if cpu is not None:
        command.extend(["--cpu", str(int(cpu))])
    process = _run_process(
        command,
        cwd=repo_root,
        stdout_path=run_directory / "stdout.log",
        stderr_path=run_directory / "stderr.log",
        timeout_seconds=float(time_limit_seconds) + float(supervision_grace_seconds),
        cpu=cpu,
    )
    record = _base_record(
        solver_id=SOLVER_PLANORA,
        instance_path=instance_path,
        solution_path=solution_path,
        seed=seed,
        time_limit_seconds=time_limit_seconds,
        workers=workers,
        cpu=cpu,
        execution_index=execution_index,
    )
    record.update(process)
    record["strategy"] = str(strategy)
    record["itc2007_course_symmetry"] = bool(itc2007_course_symmetry)
    record["itc2007_adaptive_seeding"] = bool(itc2007_adaptive_seeding)
    record["itc2007_compact_adaptive_arms"] = bool(itc2007_compact_adaptive_arms)
    record["itc2007_fixed_time_room_dive"] = bool(itc2007_fixed_time_room_dive)
    record["itc2007_fixed_time_room_strategy"] = str(itc2007_fixed_time_room_strategy)
    record["itc2007_stability_collision_weight"] = int(
        itc2007_stability_collision_weight
    )
    record["itc2007_stability_proxy_mode"] = str(itc2007_stability_proxy_mode)
    if process["timed_out"]:
        record["status"] = "SUPERVISOR_TIMEOUT"
        return record
    if process["exit_code"] != 0 or not worker_metadata.is_file():
        record["status"] = "PROCESS_ERROR"
        return record
    worker = json.loads(worker_metadata.read_text(encoding="utf-8"))
    record.update(
        {
            "worker_status": worker.get("status"),
            "worker_raw_status": worker.get("raw_status"),
            "worker_wall_time_seconds": worker.get("worker_wall_time_seconds"),
            "worker_cpu_time_seconds": worker.get("worker_cpu_time_seconds"),
            "worker_total_wall_time_seconds": worker.get(
                "worker_total_wall_time_seconds"
            ),
            "worker_total_cpu_time_seconds": worker.get(
                "worker_total_cpu_time_seconds"
            ),
            "postsolve_proof_replay_wall_time_seconds": worker.get(
                "postsolve_proof_replay_wall_time_seconds"
            ),
            "solver_objective_value": worker.get("solver_objective_value"),
            "best_objective_bound": worker.get("best_objective_bound"),
            "relative_gap": worker.get("relative_gap"),
            "bound_scope": worker.get("bound_scope", "unavailable"),
            "strategy_meta": worker.get("strategy_meta", {}),
            "fixed_time_room_proof_replay": dict(
                (worker.get("strategy_meta") or {}).get("fixed_time_room_proof_replay")
                or {}
            ),
            "worker_metadata_path": str(worker_metadata.resolve()),
        }
    )
    _validate_solution_record(
        record,
        validator_command=validator_command,
        instance_path=instance_path,
        solution_path=solution_path,
        validator_output_path=run_directory / "validator.log",
    )
    internal_score = worker.get("official_score_internal")
    if internal_score is not None and record.get("official_components") != internal_score:
        record["status"] = "SCORER_MISMATCH"
        record["feasible"] = False
        record["validator_error"] = (
            "Planora internal official score does not match the external validator"
        )
    proof_replay = dict(record.get("fixed_time_room_proof_replay") or {})
    if proof_replay.get("attempted") is True and proof_replay.get("valid") is not True:
        record["status"] = "PROOF_REPLAY_MISMATCH"
        record["feasible"] = False
        record["validator_error"] = (
            "The claim-bearing fixed-time room certificate failed offline replay"
        )
    return record


def run_cpsolver_case(
    *,
    validator_command: Sequence[str | Path],
    java_command: str | Path,
    cpsolver_root: str | Path,
    classes_path: str | Path,
    instance_path: str | Path,
    run_directory: str | Path,
    seed: int,
    time_limit_seconds: float,
    cpu: int | None,
    supervision_grace_seconds: float,
    execution_index: int,
    java_xmx_mb: int = 1024,
) -> dict[str, Any]:
    instance_path = Path(instance_path).resolve()
    run_directory = Path(run_directory).resolve()
    run_directory.mkdir(parents=True, exist_ok=False)
    solution_path = run_directory / "solution.out"
    command = build_cpsolver_command(
        java_command=java_command,
        cpsolver_root=cpsolver_root,
        classes_path=classes_path,
        instance_path=instance_path,
        solution_path=solution_path,
        time_limit_seconds=time_limit_seconds,
        seed=seed,
        java_xmx_mb=java_xmx_mb,
    )
    process = _run_process(
        command,
        cwd=run_directory,
        stdout_path=run_directory / "stdout.log",
        stderr_path=run_directory / "stderr.log",
        timeout_seconds=float(time_limit_seconds) + float(supervision_grace_seconds),
        cpu=cpu,
    )
    record = _base_record(
        solver_id=SOLVER_CPSOLVER,
        instance_path=instance_path,
        solution_path=solution_path,
        seed=seed,
        time_limit_seconds=time_limit_seconds,
        workers=1,
        cpu=cpu,
        execution_index=execution_index,
    )
    record.update(process)
    record["strategy"] = "official_itc2007_entry"
    if process["timed_out"]:
        record["status"] = "SUPERVISOR_TIMEOUT"
        return record
    if process["exit_code"] != 0:
        record["status"] = "PROCESS_ERROR"
        return record
    _validate_solution_record(
        record,
        validator_command=validator_command,
        instance_path=instance_path,
        solution_path=solution_path,
        validator_output_path=run_directory / "validator.log",
    )
    if record.get("feasible"):
        record["solver_objective_value"] = record.get("official_objective")
    record["bound_scope"] = "not_reported_by_cpsolver_itc2007"
    return record


def summarize_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, dict[str, Any]] = {}
    for solver_id in sorted({str(row["solver_id"]) for row in records}):
        rows = [row for row in records if str(row["solver_id"]) == solver_id]
        feasible = [row for row in rows if bool(row.get("feasible"))]
        objectives = [int(row["official_objective"]) for row in feasible]
        walls = [float(row["wall_time_seconds"]) for row in rows]
        aggregate[solver_id] = {
            "runs": len(rows),
            "feasible_runs": len(feasible),
            "feasibility_rate": float(len(feasible) / len(rows)) if rows else 0.0,
            "objective_min": min(objectives) if objectives else None,
            "objective_median": float(statistics.median(objectives)) if objectives else None,
            "objective_mean": float(statistics.fmean(objectives)) if objectives else None,
            "objective_max": max(objectives) if objectives else None,
            "wall_time_median_seconds": float(statistics.median(walls)) if walls else None,
        }

    paired: dict[tuple[str, int, float], dict[str, dict[str, Any]]] = {}
    for row in records:
        key = (
            str(row["instance_sha256"]),
            int(row["seed"]),
            float(row["time_limit_seconds"]),
        )
        paired.setdefault(key, {})[str(row["solver_id"])] = row
    planora_wins = cpsolver_wins = ties = unpaired = 0
    comparisons: list[dict[str, Any]] = []
    for key in sorted(paired):
        pair = paired[key]
        if SOLVER_PLANORA not in pair or SOLVER_CPSOLVER not in pair:
            unpaired += 1
            continue
        planora = pair[SOLVER_PLANORA]
        cpsolver = pair[SOLVER_CPSOLVER]
        if bool(planora.get("feasible")) != bool(cpsolver.get("feasible")):
            winner = SOLVER_PLANORA if bool(planora.get("feasible")) else SOLVER_CPSOLVER
        elif not bool(planora.get("feasible")):
            winner = "tie"
        else:
            left = int(planora["official_objective"])
            right = int(cpsolver["official_objective"])
            winner = SOLVER_PLANORA if left < right else SOLVER_CPSOLVER if right < left else "tie"
        if winner == SOLVER_PLANORA:
            planora_wins += 1
        elif winner == SOLVER_CPSOLVER:
            cpsolver_wins += 1
        else:
            ties += 1
        comparisons.append(
            {
                "instance_id": str(planora["instance_id"]),
                "seed": int(planora["seed"]),
                "winner": winner,
                "planora_objective": planora.get("official_objective"),
                "cpsolver_objective": cpsolver.get("official_objective"),
                "objective_delta_planora_minus_cpsolver": (
                    int(planora["official_objective"]) - int(cpsolver["official_objective"])
                    if planora.get("official_objective") is not None
                    and cpsolver.get("official_objective") is not None
                    else None
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "record_count": len(records),
        "aggregate": aggregate,
        "paired": {
            "planora_wins": int(planora_wins),
            "cpsolver_wins": int(cpsolver_wins),
            "ties": int(ties),
            "unpaired": int(unpaired),
            "comparisons": comparisons,
        },
    }


def _command_output(command: Sequence[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output if result.returncode == 0 and output else None


def build_manifest(
    *,
    repo_root: Path,
    validator_command: Sequence[str | Path],
    cpsolver_root: Path,
    classes_path: Path,
    instances: Sequence[Path],
    seeds: Sequence[int],
    time_limit_seconds: float,
    workers: int,
    cpu: int | None,
    strategy: str,
    itc2007_course_symmetry: bool,
    itc2007_adaptive_seeding: bool,
    itc2007_compact_adaptive_arms: bool,
    itc2007_fixed_time_room_dive: bool,
    itc2007_fixed_time_room_strategy: str,
    itc2007_stability_collision_weight: int,
    itc2007_stability_proxy_mode: str,
) -> dict[str, Any]:
    source_digest, source_files = planora_source_snapshot(repo_root)
    validator_executable = Path(str(validator_command[0])).resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "planora_git_head": _command_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root
        ),
        "planora_source_sha256": source_digest,
        "planora_source_files": source_files,
        "cpsolver_git_head": _command_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cpsolver_root,
        ),
        "cpsolver_classes_sha256": sha256_tree(classes_path),
        "validator_command": [str(value) for value in validator_command],
        "validator_sha256": (
            sha256_file(validator_executable)
            if validator_executable.is_file()
            else None
        ),
        "instances": [
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
            for path in instances
        ],
        "seeds": [int(seed) for seed in seeds],
        "time_limit_seconds": float(time_limit_seconds),
        "workers": int(workers),
        "cpu_affinity": int(cpu) if cpu is not None else None,
        "planora_strategy": str(strategy),
        "itc2007_course_symmetry": bool(itc2007_course_symmetry),
        "itc2007_adaptive_seeding": bool(itc2007_adaptive_seeding),
        "itc2007_compact_adaptive_arms": bool(itc2007_compact_adaptive_arms),
        "itc2007_fixed_time_room_dive": bool(itc2007_fixed_time_room_dive),
        "itc2007_fixed_time_room_strategy": str(itc2007_fixed_time_room_strategy),
        "itc2007_stability_collision_weight": int(itc2007_stability_collision_weight),
        "itc2007_stability_proxy_mode": str(itc2007_stability_proxy_mode),
        "python_version": platform.python_version(),
        "ortools_version": importlib.metadata.version("ortools"),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_model": _cpu_model(),
        "logical_cpu_count": os.cpu_count(),
    }


def run_benchmark_matrix(
    *,
    repo_root: str | Path,
    output_directory: str | Path,
    instances: Sequence[str | Path],
    seeds: Sequence[int],
    time_limit_seconds: float,
    validator_command: Sequence[str | Path],
    cpsolver_root: str | Path,
    classes_path: str | Path,
    python_command: str | Path = sys.executable,
    java_command: str | Path = "java",
    workers: int = 1,
    strategy: str = "research_adaptive",
    itc2007_course_symmetry: bool = False,
    itc2007_adaptive_seeding: bool = True,
    itc2007_compact_adaptive_arms: bool = False,
    itc2007_fixed_time_room_dive: bool = False,
    itc2007_fixed_time_room_strategy: str = "oracle_then_cp",
    itc2007_stability_collision_weight: int = 1,
    itc2007_stability_proxy_mode: str = "collision_events",
    cpu: int | None = None,
    supervision_grace_seconds: float = 30.0,
    java_xmx_mb: int = 1024,
    solvers: Sequence[str] = (SOLVER_PLANORA, SOLVER_CPSOLVER),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repo_root = Path(repo_root).resolve()
    output_directory = Path(output_directory).resolve()
    instance_paths = [Path(path).resolve() for path in instances]
    if output_directory.exists():
        raise FileExistsError(
            f"Benchmark output directory already exists; choose a fresh path: {output_directory}"
        )
    if not instance_paths:
        raise ValueError("At least one ITC-2007 instance is required")
    if not seeds:
        raise ValueError("At least one random seed is required")
    if workers != 1:
        raise ValueError("The primary ITC-2007 comparison requires workers=1")
    if int(itc2007_stability_collision_weight) < 1:
        raise ValueError("itc2007_stability_collision_weight must be positive")
    if str(itc2007_stability_proxy_mode) not in {
        "collision_events",
        "fragmented_courses",
    }:
        raise ValueError("unsupported itc2007_stability_proxy_mode")
    for path in instance_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    output_directory.mkdir(parents=True)
    cpsolver_root = Path(cpsolver_root).resolve()
    classes_path = Path(classes_path).resolve()
    manifest = build_manifest(
        repo_root=repo_root,
        validator_command=validator_command,
        cpsolver_root=cpsolver_root,
        classes_path=classes_path,
        instances=instance_paths,
        seeds=seeds,
        time_limit_seconds=time_limit_seconds,
        workers=workers,
        cpu=cpu,
        strategy=strategy,
        itc2007_course_symmetry=itc2007_course_symmetry,
        itc2007_adaptive_seeding=itc2007_adaptive_seeding,
        itc2007_compact_adaptive_arms=itc2007_compact_adaptive_arms,
        itc2007_fixed_time_room_dive=itc2007_fixed_time_room_dive,
        itc2007_fixed_time_room_strategy=itc2007_fixed_time_room_strategy,
        itc2007_stability_collision_weight=itc2007_stability_collision_weight,
        itc2007_stability_proxy_mode=itc2007_stability_proxy_mode,
    )
    _write_json(output_directory / "manifest.json", manifest)

    selected = [str(value) for value in solvers]
    unknown = sorted(set(selected) - {SOLVER_PLANORA, SOLVER_CPSOLVER})
    if unknown:
        raise ValueError(f"Unknown benchmark solvers: {unknown}")
    records: list[dict[str, Any]] = []
    execution_index = 0
    for instance_index, instance_path in enumerate(instance_paths):
        for seed_index, seed in enumerate(seeds):
            order = list(selected)
            if (instance_index + seed_index) % 2 == 1:
                order.reverse()
            for solver_id in order:
                execution_index += 1
                run_directory = (
                    output_directory
                    / "runs"
                    / instance_path.stem
                    / f"seed-{int(seed)}"
                    / solver_id
                )
                if solver_id == SOLVER_PLANORA:
                    record = run_planora_case(
                        repo_root=repo_root,
                        python_command=python_command,
                        validator_command=validator_command,
                        instance_path=instance_path,
                        run_directory=run_directory,
                        seed=int(seed),
                        time_limit_seconds=float(time_limit_seconds),
                        workers=int(workers),
                        strategy=strategy,
                        itc2007_course_symmetry=itc2007_course_symmetry,
                        itc2007_adaptive_seeding=itc2007_adaptive_seeding,
                        itc2007_compact_adaptive_arms=itc2007_compact_adaptive_arms,
                        itc2007_fixed_time_room_dive=itc2007_fixed_time_room_dive,
                        itc2007_fixed_time_room_strategy=(
                            itc2007_fixed_time_room_strategy
                        ),
                        itc2007_stability_collision_weight=(
                            itc2007_stability_collision_weight
                        ),
                        itc2007_stability_proxy_mode=(itc2007_stability_proxy_mode),
                        cpu=cpu,
                        supervision_grace_seconds=supervision_grace_seconds,
                        execution_index=execution_index,
                    )
                else:
                    record = run_cpsolver_case(
                        validator_command=validator_command,
                        java_command=java_command,
                        cpsolver_root=cpsolver_root,
                        classes_path=classes_path,
                        instance_path=instance_path,
                        run_directory=run_directory,
                        seed=int(seed),
                        time_limit_seconds=float(time_limit_seconds),
                        cpu=cpu,
                        supervision_grace_seconds=supervision_grace_seconds,
                        execution_index=execution_index,
                        java_xmx_mb=java_xmx_mb,
                    )
                records.append(record)
                current_source_digest, _current_source_files = planora_source_snapshot(
                    repo_root
                )
                source_snapshot_match = (
                    current_source_digest == manifest["planora_source_sha256"]
                )
                record["source_snapshot_match"] = bool(source_snapshot_match)
                with (output_directory / "results.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                interim_summary = summarize_records(records)
                interim_summary.update(
                    {
                        "complete": False,
                        "completed_runs": len(records),
                        "planned_runs": len(instance_paths) * len(seeds) * len(selected),
                        "manifest_path": str(
                            (output_directory / "manifest.json").resolve()
                        ),
                        "source_stable": bool(source_snapshot_match),
                    }
                )
                _write_json(output_directory / "summary.json", interim_summary)
                if not source_snapshot_match:
                    raise RuntimeError(
                        "Planora source changed during the benchmark; results are retained "
                        "with complete=false and must not be compared"
                    )

    summary = summarize_records(records)
    summary.update(
        {
            "complete": True,
            "completed_runs": len(records),
            "planned_runs": len(instance_paths) * len(seeds) * len(selected),
            "manifest_path": str((output_directory / "manifest.json").resolve()),
            "source_stable": True,
        }
    )
    _write_json(output_directory / "summary.json", summary)
    return records, summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a reproducible ITC-2007 Planora/CPSolver comparison.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    worker = subparsers.add_parser("planora-worker", help=argparse.SUPPRESS)
    worker.add_argument("--instance", required=True)
    worker.add_argument("--solution", required=True)
    worker.add_argument("--metadata", required=True)
    worker.add_argument("--seed", required=True, type=int)
    worker.add_argument("--time-limit-seconds", required=True, type=float)
    worker.add_argument("--workers", type=int, default=1)
    worker.add_argument(
        "--strategy",
        choices=("research_adaptive", "projected_hybrid", "exact_cp_sat"),
        default="research_adaptive",
    )
    worker.add_argument(
        "--itc2007-course-symmetry",
        choices=("on", "off"),
        default="off",
    )
    worker.add_argument(
        "--itc2007-adaptive-seeding",
        choices=("on", "off"),
        default="on",
    )
    worker.add_argument(
        "--itc2007-compact-adaptive-arms",
        choices=("on", "off"),
        default="off",
    )
    worker.add_argument(
        "--itc2007-fixed-time-room-dive",
        choices=("on", "off"),
        default="off",
    )
    worker.add_argument(
        "--itc2007-fixed-time-room-strategy",
        choices=("control", "oracle_only", "cp_only", "oracle_then_cp"),
        default="oracle_then_cp",
    )
    worker.add_argument(
        "--itc2007-stability-collision-weight",
        type=int,
        default=1,
    )
    worker.add_argument(
        "--itc2007-stability-proxy-mode",
        choices=("collision_events", "fragmented_courses"),
        default="collision_events",
    )
    worker.add_argument("--cpu", type=int)

    run = subparsers.add_parser("run")
    run.add_argument("--instances", nargs="+", required=True)
    run.add_argument("--seeds", nargs="+", required=True, type=int)
    run.add_argument("--time-limit-seconds", required=True, type=float)
    run.add_argument("--validator", required=True)
    run.add_argument("--cpsolver-root", required=True)
    run.add_argument("--classes", required=True)
    run.add_argument("--output-directory", required=True)
    run.add_argument("--repo-root", default=str(Path.cwd()))
    run.add_argument("--python-command", default=sys.executable)
    run.add_argument("--java-command", default="java")
    run.add_argument("--java-xmx-mb", type=int, default=1024)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--cpu", type=int)
    run.add_argument("--supervision-grace-seconds", type=float, default=30.0)
    run.add_argument(
        "--strategy",
        choices=("research_adaptive", "projected_hybrid", "exact_cp_sat"),
        default="research_adaptive",
    )
    run.add_argument(
        "--itc2007-course-symmetry",
        choices=("on", "off"),
        default="off",
        help="Enable or disable the metadata-backed strict course-lecture orbit cut.",
    )
    run.add_argument(
        "--itc2007-adaptive-seeding",
        choices=("on", "off"),
        default="on",
        help="Enable context-eligible UCB arms and official ITC penalty-support seeds.",
    )
    run.add_argument(
        "--itc2007-compact-adaptive-arms",
        choices=("on", "off"),
        default="off",
        help=(
            "Enable the candidate imported-ITC compact arm set (12,24); the "
            "default retains the legacy (12,24,48) set until the paired gate."
        ),
    )
    run.add_argument(
        "--itc2007-fixed-time-room-dive",
        choices=("on", "off"),
        default="off",
        help="Enable the default-off fixed-time exact room finalization ablation.",
    )
    run.add_argument(
        "--itc2007-fixed-time-room-strategy",
        choices=("control", "oracle_only", "cp_only", "oracle_then_cp"),
        default="oracle_then_cp",
        help=(
            "Select the finalization ablation: matched-budget control, "
            "structural oracle only, full CP only, or the production dispatcher."
        ),
    )
    run.add_argument(
        "--itc2007-stability-collision-weight",
        type=int,
        default=1,
        help=(
            "Weight incumbent-majority room collisions in the projected "
            "feedback scalar; 1 preserves the official-unit baseline."
        ),
    )
    run.add_argument(
        "--itc2007-stability-proxy-mode",
        choices=("collision_events", "fragmented_courses"),
        default="collision_events",
        help=(
            "Choose event-collision or distinct-fragmented-course room-support "
            "feedback; the default preserves the established baseline."
        ),
    )
    run.add_argument(
        "--solvers",
        nargs="+",
        choices=(SOLVER_PLANORA, SOLVER_CPSOLVER),
        default=[SOLVER_PLANORA, SOLVER_CPSOLVER],
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "planora-worker":
        run_planora_worker(
            args.instance,
            args.solution,
            args.metadata,
            seed=args.seed,
            time_limit_seconds=args.time_limit_seconds,
            workers=args.workers,
            strategy=args.strategy,
            itc2007_course_symmetry=args.itc2007_course_symmetry == "on",
            itc2007_adaptive_seeding=args.itc2007_adaptive_seeding == "on",
            itc2007_compact_adaptive_arms=(args.itc2007_compact_adaptive_arms == "on"),
            itc2007_fixed_time_room_dive=(args.itc2007_fixed_time_room_dive == "on"),
            itc2007_fixed_time_room_strategy=(args.itc2007_fixed_time_room_strategy),
            itc2007_stability_collision_weight=(
                args.itc2007_stability_collision_weight
            ),
            itc2007_stability_proxy_mode=args.itc2007_stability_proxy_mode,
            cpu=args.cpu,
        )
        return 0

    _records, summary = run_benchmark_matrix(
        repo_root=args.repo_root,
        output_directory=args.output_directory,
        instances=args.instances,
        seeds=args.seeds,
        time_limit_seconds=args.time_limit_seconds,
        validator_command=[args.validator],
        cpsolver_root=args.cpsolver_root,
        classes_path=args.classes,
        python_command=args.python_command,
        java_command=args.java_command,
        workers=args.workers,
        strategy=args.strategy,
        itc2007_course_symmetry=args.itc2007_course_symmetry == "on",
        itc2007_adaptive_seeding=args.itc2007_adaptive_seeding == "on",
        itc2007_compact_adaptive_arms=(args.itc2007_compact_adaptive_arms == "on"),
        itc2007_fixed_time_room_dive=(args.itc2007_fixed_time_room_dive == "on"),
        itc2007_fixed_time_room_strategy=(args.itc2007_fixed_time_room_strategy),
        itc2007_stability_collision_weight=(args.itc2007_stability_collision_weight),
        itc2007_stability_proxy_mode=args.itc2007_stability_proxy_mode,
        cpu=args.cpu,
        supervision_grace_seconds=args.supervision_grace_seconds,
        java_xmx_mb=args.java_xmx_mb,
        solvers=args.solvers,
    )
    print(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
