from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import ortools


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.itc2019 import (
    parse_itc2019_solution,
    parse_itc2019_xml,
    score_itc2019_solution,
    solve_itc2019_native,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_corpus import (
    ITC2019_EFFECTIVE_COMPETITION_FILES,
    ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256,
    ITC2019_OFFICIAL_CORRECTED_INPUT_SHA256 as OFFICIAL_CORRECTED_INPUT_SHA256,
)
from benchmarks.itc2019_competitor_provenance import (
    CompetitorProvenanceError,
    provenance_bindings_match_exactly,
    verify_competitor_provenance,
)
from benchmarks.itc2019_resource_controller import (
    CGROUP_EVIDENCE_RELATIVE_PATH,
    CONTROLLER_VERSION,
    DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    RESOURCE_EVIDENCE_SCHEMA,
    SUPERVISOR_EVIDENCE_RELATIVE_PATH,
    DockerCgroupV2Controller,
    ResourceControllerError,
    ResourceProfile,
    SolverInvocation,
    resource_evidence_sha256,
)


OFFICIAL_TEST_CASES = (
    "wbg-fal10",
    "lums-sum17",
    "bet-sum18",
    "pu-cs-fal07",
    "pu-llr-spr07",
    "pu-c8-spr07",
)
SUPPORTED_TEST_CASES = tuple(
    case for case in OFFICIAL_TEST_CASES if case not in {"pu-llr-spr07", "pu-c8-spr07"}
)
_COMPETITION_PHASES = ("early", "middle", "late")
_EFFECTIVE_COMPETITION_PROBLEMS = tuple(
    row
    for phase in _COMPETITION_PHASES
    for row in ITC2019_EFFECTIVE_COMPETITION_FILES
    if row.kind == "problem" and row.phase == phase
)
COMPETITION_CASES = tuple(row.instance for row in _EFFECTIVE_COMPETITION_PROBLEMS)
CANONICAL_COMPETITION_INPUT_SHA256 = {
    row.instance: row.sha256 for row in _EFFECTIVE_COMPETITION_PROBLEMS
}
if (
    len(COMPETITION_CASES) != 30
    or len(set(COMPETITION_CASES)) != 30
    or set(CANONICAL_COMPETITION_INPUT_SHA256) != set(COMPETITION_CASES)
):
    raise RuntimeError("ITC-2019 effective competition corpus is not canonical-30")
DEFAULT_SOLVERS = ("planora", "gashi-sa", "unitime-cpsolver", "lemos-maxsat")
EXTERNAL_COMPETITOR_SOLVERS = frozenset(DEFAULT_SOLVERS) - {"planora"}
EXPLICITLY_SEEDED_SOLVERS = frozenset({"planora", "gashi-sa", "unitime-cpsolver"})
UNSEEDED_SOLVERS = frozenset({"lemos-maxsat"})
CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS = {
    # The image digest pins which solver-specific wrapper is reached by this
    # common in-image command.  Claim-grade admission recognizes only these
    # complete, ordered wrapper interfaces; it never infers option semantics.
    "planora": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seed",
        "{seed}",
        "--seconds",
        "{seconds}",
    ),
    "gashi-sa": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seed",
        "{seed}",
        "--seconds",
        "{seconds}",
    ),
    "unitime-cpsolver": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seed",
        "{seed}",
        "--seconds",
        "{seconds}",
    ),
    "lemos-maxsat": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seconds",
        "{seconds}",
    ),
}
if (
    EXPLICITLY_SEEDED_SOLVERS & UNSEEDED_SOLVERS
    or EXPLICITLY_SEEDED_SOLVERS | UNSEEDED_SOLVERS != set(DEFAULT_SOLVERS)
    or set(CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS) != set(DEFAULT_SOLVERS)
):
    raise RuntimeError("Every ITC-2019 competitor adapter needs one seed policy")
DEFAULT_INPUT_ROOT = (
    ROOT / "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019"
)
DEFAULT_GASHI = Path("/tmp/planora-gashi-itc2019/bin/linux-x64/Timetabling.CLI.dll")
DEFAULT_CPS_ROOT = Path("/tmp/planora-cpsolver-itc2019")
DEFAULT_MAXSAT = Path("/tmp/planora-maxsat-itc2019/timetabler")
DEFAULT_MAXSAT_LOCALE = Path("/tmp/planora-maxsat-locale")
MATRIX_SCHEMA = "planora.itc2019.competitor-matrix.v2"
CLAIM_GRADE_CONTROLLER_CONFIG_SCHEMA = (
    "planora.itc2019.claim-grade-controller-config.v1"
)
CLAIM_GRADE_CONTROLLER_MODE = "claim-grade-controller"
EVIDENCE_ONLY_CONTROLLER_MODE = "evidence-only-controller"
CONTROLLER_BUDGET_BASIS = (
    "Docker cgroup-v2 external profile with immutable images, trusted supervisor, "
    "refreshable daemon-bound capabilities, and authoritative per-run evidence"
)
CAPABILITY_REFRESH_CONFIG_SCHEMA = "planora.itc2019.capability-refresh-command.v1"
POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA = (
    "planora.itc2019.post-exit-cgroup-probe-command.v1"
)
RAW_RESOURCE_EVIDENCE_SCHEMA = "planora.itc2019.raw-resource-evidence.v1"
CORPUS_ADMISSION_SCHEMA = "planora.itc2019.corpus-admission.v1"
CPSOLVER_COMPLETION_OVERHEAD_SECONDS = 120.0
MAXSAT_COMPLETION_OVERHEAD_SECONDS = 30.0
PLANORA_COMPLETION_OVERHEAD_SECONDS = 15.0
PLANORA_SOURCE_FILES = (
    "benchmarks/itc2019.py",
    "benchmarks/itc2019_compact_joint.py",
    "benchmarks/itc2019_decomposed.py",
    "benchmarks/itc2019_decomposed_quality.py",
    "benchmarks/itc2019_factorized.py",
    "benchmarks/itc2019_generalized_occurrences.py",
    "benchmarks/itc2019_grouped_calendar.py",
    "benchmarks/itc2019_global_components.py",
    "benchmarks/itc2019_global_quality.py",
    "benchmarks/itc2019_resource_seed.py",
    "benchmarks/itc2019_sparse_joint.py",
    "benchmarks/itc2019_structural.py",
    "benchmarks/itc2019_violation_lns.py",
)
QUALITY_ONLY_RESOURCE_POLICY = {
    "comparison_scope": "same-host quality-only under nominal solver budgets",
    "equal_wall_time_claim": False,
    "equal_memory_limit_claim": False,
    "wall_policy": (
        "Upstream tools expose different internal timing and shutdown semantics; "
        "the supervisor bounds runaway completion but does not create equal wall time."
    ),
    "memory_policy": (
        "Peak RSS is observed, but this platform does not provide a verified common "
        "memory cgroup for every runtime. CPSolver retains its JVM heap guard."
    ),
    "seed_policy": (
        "Planora, Gashi SA, and CPSolver use explicit paired seeds. Lemos MaxSAT "
        "does not expose a seed and is recorded only as independent unseeded trials."
    ),
}
CLAIM_GRADE_RESOURCE_POLICY = {
    "comparison_scope": (
        "same-host equal external wall-time, CPU, memory, swap, PID, network, and "
        "read-only-filesystem controls"
    ),
    "equal_wall_time_claim": True,
    "equal_memory_limit_claim": True,
    "wall_policy": (
        "A trusted external supervisor and an independent host deadline enforce the "
        "same solver wall-time profile for every runtime."
    ),
    "memory_policy": (
        "Docker cgroup v2 enforces and records the same memory and swap ceilings, "
        "with post-exit cgroup samples and complete process-tree cleanup."
    ),
    "seed_policy": QUALITY_ONLY_RESOURCE_POLICY["seed_policy"],
}
_ARTIFACT_BINDING_FIELDS = (
    "run_id",
    "case",
    "solver",
    "seed",
    "effective_seed",
    "seed_control",
    "seed_pairing_group",
    "repetition",
    "unseeded_trial",
)
_NO_ARTIFACT_VALIDATION_STATUS = "not_run_no_artifact"


@dataclass(frozen=True, slots=True)
class ClaimGradeControllerRuntime:
    """Validated, non-serializable controller plus its immutable manifest binding."""

    controller: DockerCgroupV2Controller
    manifest_binding: dict[str, Any]
    supervisor_path: Path
    solver_argv_templates: dict[str, tuple[str, ...]]


def _capability_refresh_provider(
    value: Any, *, config_directory: Path
) -> tuple[Any | None, dict[str, Any] | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict) or value.get("schema") != (
        CAPABILITY_REFRESH_CONFIG_SCHEMA
    ):
        raise ResourceControllerError("capability refresh config is malformed")
    argv = value.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(
            not isinstance(argument, str)
            or not argument
            or any(character in argument for character in ("\x00", "\n", "\r"))
            for argument in argv
        )
    ):
        raise ResourceControllerError("capability refresh argv is malformed")
    executable = Path(argv[0])
    if not executable.is_absolute():
        executable = (config_directory / executable).resolve(strict=True)
    else:
        executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ResourceControllerError("capability refresh executable is not a file")
    normalized_argv = (str(executable), *(str(argument) for argument in argv[1:]))
    bound_files_value = value.get("bound_files", [])
    if not isinstance(bound_files_value, list):
        raise ResourceControllerError("capability refresh bound_files is malformed")
    bound_files = []
    seen_bound_paths: set[str] = set()
    for index, raw_binding in enumerate(bound_files_value):
        if not isinstance(raw_binding, dict):
            raise ResourceControllerError(
                f"capability refresh bound_files[{index}] is malformed"
            )
        raw_path = raw_binding.get("path")
        expected_sha256 = raw_binding.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise ResourceControllerError(
                f"capability refresh bound_files[{index}].path is malformed"
            )
        path = Path(raw_path)
        if not path.is_absolute():
            path = config_directory / path
        try:
            path = path.resolve(strict=True)
        except OSError as exc:
            raise ResourceControllerError(
                "capability refresh bound file is unavailable"
            ) from exc
        if not path.is_file() or str(path) in seen_bound_paths:
            raise ResourceControllerError("capability refresh bound file is invalid")
        actual_sha256 = _sha256(path)
        if expected_sha256 != actual_sha256:
            raise ResourceControllerError("capability refresh bound file hash mismatch")
        seen_bound_paths.add(str(path))
        bound_files.append({"path": str(path), "sha256": actual_sha256})
    referenced_files = set()
    for argument in normalized_argv[1:]:
        candidate = Path(argument)
        if not candidate.is_absolute():
            candidate = config_directory / candidate
        try:
            candidate = candidate.resolve(strict=True)
        except OSError:
            continue
        if candidate.is_file():
            referenced_files.add(str(candidate))
    if not referenced_files.issubset(seen_bound_paths):
        raise ResourceControllerError(
            "capability refresh file arguments must be hash-bound"
        )
    timeout_value = value.get("timeout_seconds", 15.0)
    if (
        isinstance(timeout_value, bool)
        or not isinstance(timeout_value, (int, float))
        or not math.isfinite(float(timeout_value))
        or float(timeout_value) <= 0
        or float(timeout_value) > 60
    ):
        raise ResourceControllerError("capability refresh timeout is invalid")
    binding = {
        "schema": CAPABILITY_REFRESH_CONFIG_SCHEMA,
        "argv": list(normalized_argv),
        "executable_sha256": _sha256(executable),
        "bound_files": sorted(bound_files, key=lambda item: item["path"]),
        "timeout_seconds": float(timeout_value),
    }

    def provider() -> Mapping[str, Any]:
        if _sha256(executable) != binding["executable_sha256"]:
            raise ResourceControllerError("capability refresh executable hash drift")
        for item in binding["bound_files"]:
            path = Path(item["path"])
            try:
                actual_sha256 = _sha256(path.resolve(strict=True))
            except OSError as exc:
                raise ResourceControllerError(
                    "capability refresh bound file is unavailable"
                ) from exc
            if actual_sha256 != item["sha256"]:
                raise ResourceControllerError(
                    "capability refresh bound file hash drift"
                )
        try:
            completed = subprocess.run(
                normalized_argv,
                cwd=str(config_directory),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=float(timeout_value),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ResourceControllerError("capability refresh command failed") from exc
        if completed.returncode != 0 or completed.stderr:
            raise ResourceControllerError("capability refresh command failed")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ResourceControllerError(
                "capability refresh command returned malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ResourceControllerError(
                "capability refresh command must return one JSON object"
            )
        return payload

    return provider, binding


def _post_exit_cgroup_probe_provider(
    value: Any, *, config_directory: Path
) -> tuple[Any | None, dict[str, Any] | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict) or value.get("schema") != (
        POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA
    ):
        raise ResourceControllerError("post-exit cgroup probe config is malformed")
    argv = value.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(
            not isinstance(argument, str)
            or not argument
            or any(character in argument for character in ("\x00", "\n", "\r"))
            for argument in argv
        )
    ):
        raise ResourceControllerError("post-exit cgroup probe argv is malformed")
    executable = Path(argv[0])
    if not executable.is_absolute():
        executable = config_directory / executable
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ResourceControllerError("post-exit cgroup probe executable is not a file")
    timeout_value = value.get("timeout_seconds", 15.0)
    if (
        isinstance(timeout_value, bool)
        or not isinstance(timeout_value, (int, float))
        or not math.isfinite(float(timeout_value))
        or float(timeout_value) <= 0
        or float(timeout_value) > 60
    ):
        raise ResourceControllerError("post-exit cgroup probe timeout is invalid")
    bound_files_value = value.get("bound_files", [])
    if not isinstance(bound_files_value, list):
        raise ResourceControllerError("post-exit cgroup probe bound_files is malformed")
    bound_files = []
    seen_paths: set[str] = set()
    for raw_binding in bound_files_value:
        if not isinstance(raw_binding, dict) or not isinstance(
            raw_binding.get("path"), str
        ):
            raise ResourceControllerError(
                "post-exit cgroup probe bound file is malformed"
            )
        path = Path(raw_binding["path"])
        if not path.is_absolute():
            path = config_directory / path
        path = path.resolve(strict=True)
        actual_sha256 = _sha256(path)
        if (
            not path.is_file()
            or str(path) in seen_paths
            or raw_binding.get("sha256") != actual_sha256
        ):
            raise ResourceControllerError(
                "post-exit cgroup probe bound file hash mismatch"
            )
        seen_paths.add(str(path))
        bound_files.append({"path": str(path), "sha256": actual_sha256})
    normalized_argv = (str(executable), *(str(argument) for argument in argv[1:]))
    referenced_files = set()
    for argument in normalized_argv[1:]:
        if "{" in argument or "}" in argument:
            continue
        candidate = Path(argument)
        if not candidate.is_absolute():
            candidate = config_directory / candidate
        try:
            candidate = candidate.resolve(strict=True)
        except OSError:
            continue
        if candidate.is_file():
            referenced_files.add(str(candidate))
    if not referenced_files.issubset(seen_paths):
        raise ResourceControllerError(
            "post-exit cgroup probe file arguments must be hash-bound"
        )
    binding = {
        "schema": POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA,
        "argv": list(normalized_argv),
        "executable_sha256": _sha256(executable),
        "bound_files": sorted(bound_files, key=lambda item: item["path"]),
        "timeout_seconds": float(timeout_value),
    }

    def provider(
        invocation: SolverInvocation, inspect: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if _sha256(executable) != binding["executable_sha256"]:
            raise ResourceControllerError(
                "post-exit cgroup probe executable hash drift"
            )
        for item in binding["bound_files"]:
            if _sha256(Path(item["path"]).resolve(strict=True)) != item["sha256"]:
                raise ResourceControllerError(
                    "post-exit cgroup probe bound file hash drift"
                )
        replacements = {
            "{run_id}": invocation.run_id,
            "{container_id}": str(inspect.get("Id", "")),
            "{container_name}": str(inspect.get("Name", "")).lstrip("/"),
            "{image_id}": str(inspect.get("Image", "")),
        }
        command = []
        for argument in normalized_argv:
            rendered = argument
            for placeholder, replacement in replacements.items():
                rendered = rendered.replace(placeholder, replacement)
            if "{" in rendered or "}" in rendered or not rendered:
                raise ResourceControllerError(
                    "post-exit cgroup probe has an unsupported placeholder"
                )
            command.append(rendered)
        try:
            completed = subprocess.run(
                command,
                cwd=str(config_directory),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=float(timeout_value),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ResourceControllerError("post-exit cgroup probe failed") from exc
        if completed.returncode != 0 or completed.stderr:
            raise ResourceControllerError("post-exit cgroup probe failed")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ResourceControllerError(
                "post-exit cgroup probe returned malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ResourceControllerError(
                "post-exit cgroup probe must return one JSON object"
            )
        return payload

    return provider, binding


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json_object(path: Path, field_name: str) -> dict[str, Any]:
    def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ResourceControllerError(
                    f"{field_name} contains duplicate JSON member {key!r}"
                )
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> None:
        raise ResourceControllerError(
            f"{field_name} contains non-standard JSON constant {value!r}"
        )

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_members,
            parse_constant=reject_nonstandard_constant,
        )
    except ResourceControllerError:
        raise
    except OSError as exc:
        raise ResourceControllerError(f"{field_name} could not be read") from exc
    except json.JSONDecodeError as exc:
        raise ResourceControllerError(f"{field_name} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ResourceControllerError(f"{field_name} must contain a JSON object")
    return payload


_CONTROLLER_ARGV_PLACEHOLDERS = {
    "{input}",
    "{output}",
    "{run_dir}",
    "{seed}",
    "{seconds}",
}


def _validate_claim_grade_argv_template(template: tuple[str, ...], solver: str) -> None:
    contract = CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS.get(solver)
    if contract is None or template != contract:
        raise ResourceControllerError(
            "controller argv template does not match the pinned complete argv "
            f"contract for solver: {solver}"
        )


def _render_claim_grade_contract(
    solver: str, *, seed: int, seconds: float
) -> tuple[str, ...]:
    contract = CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS.get(solver)
    if contract is None:
        raise ResourceControllerError(
            f"no pinned complete argv contract exists for solver: {solver}"
        )
    replacements = {
        "{input}": "/inputs/instance.xml",
        "{output}": "/run/planora/solution.xml",
        "{run_dir}": "/run/planora",
        "{seed}": str(int(seed)),
        "{seconds}": str(float(seconds)),
    }
    return tuple(replacements.get(argument, argument) for argument in contract)


def _validate_claim_grade_executed_argv(
    argv: tuple[str, ...], solver: str, *, seed: int, seconds: float
) -> None:
    if argv != _render_claim_grade_contract(solver, seed=seed, seconds=seconds):
        raise ResourceControllerError(
            "rendered controller argv does not match the pinned complete argv "
            f"contract for solver: {solver}"
        )


def _validate_controller_argv_templates(
    payload: Any,
    solvers: list[str],
    *,
    require_seed_binding: bool = False,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(payload, dict):
        raise ResourceControllerError("controller config solver_argv must be an object")
    selected: dict[str, tuple[str, ...]] = {}
    for solver in solvers:
        raw = payload.get(solver)
        if (
            not isinstance(raw, list)
            or not raw
            or any(not isinstance(argument, str) or not argument for argument in raw)
        ):
            raise ResourceControllerError(
                f"controller config has no valid argv template for selected solver: {solver}"
            )
        template = tuple(raw)
        joined = "\n".join(template)
        unknown = {
            token
            for token in set(re.findall(r"\{[^{}]+\}", joined))
            if token not in _CONTROLLER_ARGV_PLACEHOLDERS
        }
        if unknown or joined.count("{") != joined.count("}"):
            raise ResourceControllerError(
                f"controller argv template has unsupported placeholders for {solver}"
            )
        if "{input}" not in joined or "{output}" not in joined:
            raise ResourceControllerError(
                f"controller argv template must bind input and output for {solver}"
            )
        if require_seed_binding:
            _validate_claim_grade_argv_template(template, solver)
        selected[solver] = template
    return selected


def _render_controller_argv(
    template: tuple[str, ...], *, seed: int, seconds: float
) -> tuple[str, ...]:
    replacements = {
        "{input}": "/inputs/instance.xml",
        "{output}": "/run/planora/solution.xml",
        "{run_dir}": "/run/planora",
        "{seed}": str(int(seed)),
        "{seconds}": str(float(seconds)),
    }
    rendered = []
    for argument in template:
        value = argument
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        if "{" in value or "}" in value or not value:
            raise ResourceControllerError(
                "controller argv rendering left an unsupported placeholder"
            )
        rendered.append(value)
    return tuple(rendered)


def _claim_grade_controller_preflight(
    config_path: Path,
    *,
    solvers: list[str],
    seconds: float,
    cpu: int,
    execution_mode: str = CLAIM_GRADE_CONTROLLER_MODE,
) -> ClaimGradeControllerRuntime:
    """Validate the immutable controller contract without starting a solver."""

    if execution_mode not in {
        CLAIM_GRADE_CONTROLLER_MODE,
        EVIDENCE_ONLY_CONTROLLER_MODE,
    }:
        raise ResourceControllerError("unsupported controller execution mode")

    try:
        resolved_config = config_path.resolve(strict=True)
    except OSError as exc:
        raise ResourceControllerError(
            "claim-grade controller config does not exist"
        ) from exc
    config = _read_json_object(resolved_config, "claim-grade controller config")
    if config.get("schema") != CLAIM_GRADE_CONTROLLER_CONFIG_SCHEMA:
        raise ResourceControllerError(
            "unsupported claim-grade controller config schema"
        )
    selected_argv = _validate_controller_argv_templates(
        config.get("solver_argv"),
        solvers,
        require_seed_binding=execution_mode == CLAIM_GRADE_CONTROLLER_MODE,
    )

    profile_payload = config.get("profile")
    if not isinstance(profile_payload, dict):
        raise ResourceControllerError("controller config profile must be an object")
    try:
        profile = ResourceProfile(**profile_payload)
    except TypeError as exc:
        raise ResourceControllerError("controller config profile is malformed") from exc
    if profile.wall_time_seconds != float(seconds):
        raise ResourceControllerError(
            "controller profile wall_time_seconds must equal --time-limit"
        )
    if profile.cpuset_cpus != str(int(cpu)):
        raise ResourceControllerError(
            "controller profile cpuset_cpus must equal the single --cpu selection"
        )
    if profile.cpu_quota_us != profile.cpu_period_us:
        raise ResourceControllerError(
            "claim-grade controller mode requires exactly one CPU of quota"
        )

    capabilities = config.get("capability_evidence")
    if not isinstance(capabilities, dict):
        raise ResourceControllerError(
            "controller config capability_evidence must be an object"
        )

    supervisor_value = config.get("supervisor_path")
    if not isinstance(supervisor_value, str) or not supervisor_value:
        raise ResourceControllerError(
            "controller config supervisor_path must be a non-empty path"
        )
    supervisor_path = Path(supervisor_value)
    if not supervisor_path.is_absolute():
        supervisor_path = resolved_config.parent / supervisor_path
    supervisor_path = supervisor_path.resolve(strict=True)
    if not supervisor_path.is_file():
        raise ResourceControllerError("controller supervisor_path is not a file")
    supervisor_sha256 = _sha256(supervisor_path)
    if config.get("supervisor_sha256") != supervisor_sha256:
        raise ResourceControllerError("controller supervisor SHA-256 mismatch")

    docker_executable = config.get("docker_executable", "docker")
    if not isinstance(docker_executable, str) or not docker_executable:
        raise ResourceControllerError(
            "controller config docker_executable must be non-empty"
        )
    refresh_provider, refresh_binding = _capability_refresh_provider(
        config.get("capability_refresh"), config_directory=resolved_config.parent
    )
    cgroup_provider, cgroup_probe_binding = _post_exit_cgroup_probe_provider(
        config.get("post_exit_cgroup_probe"),
        config_directory=resolved_config.parent,
    )
    if execution_mode == CLAIM_GRADE_CONTROLLER_MODE and (
        refresh_provider is None or cgroup_provider is None
    ):
        raise ResourceControllerError(
            "claim-grade controller mode requires capability refresh and a "
            "post-exit cgroup probe"
        )
    controller = DockerCgroupV2Controller(
        profile,
        capabilities,
        supervisor_sha256=supervisor_sha256,
        capability_evidence_provider=refresh_provider,
        post_exit_cgroup_evidence_provider=cgroup_provider,
        docker_executable=docker_executable,
    )
    preflight_snapshot = (
        controller.refresh_capability_evidence()
        if refresh_provider is not None
        else controller.capability_evidence
    )

    images = config.get("solver_images")
    if not isinstance(images, dict):
        raise ResourceControllerError(
            "controller config solver_images must be an object"
        )
    selected_images: dict[str, str] = {}
    for solver in solvers:
        image = images.get(solver)
        if not isinstance(image, str) or not image:
            raise ResourceControllerError(
                f"controller config has no image for selected solver: {solver}"
            )
        # Reuse the controller's public invocation contract to reject mutable tags
        # and malformed solver identities without invoking Docker.
        SolverInvocation(
            run_id=f"preflight-{solver}",
            solver=solver,
            image=image,
            argv=("/bin/true",),
            host_run_directory=str(ROOT.resolve()),
        )
        selected_images[solver] = image

    external_solvers = [
        solver for solver in solvers if solver in EXTERNAL_COMPETITOR_SOLVERS
    ]
    provenance_config = config.get("competitor_provenance")
    competitor_provenance: dict[str, Any] | None = None
    if external_solvers:
        if provenance_config is None:
            if execution_mode == CLAIM_GRADE_CONTROLLER_MODE:
                raise ResourceControllerError(
                    "claim-grade controller requires competitor provenance"
                )
        else:
            if type(provenance_config) is not dict or set(provenance_config) != {
                "manifest_path",
                "manifest_sha256",
            }:
                raise ResourceControllerError(
                    "controller competitor_provenance binding is malformed"
                )
            manifest_value = provenance_config["manifest_path"]
            manifest_sha256 = provenance_config["manifest_sha256"]
            if not isinstance(manifest_value, str) or not manifest_value:
                raise ResourceControllerError(
                    "controller competitor provenance path is malformed"
                )
            if (
                not isinstance(manifest_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None
            ):
                raise ResourceControllerError(
                    "controller competitor provenance hash is malformed"
                )
            provenance_path = Path(manifest_value)
            if not provenance_path.is_absolute():
                provenance_path = resolved_config.parent / provenance_path
            try:
                observed_manifest_sha256 = _sha256(provenance_path)
            except OSError as exc:
                raise ResourceControllerError(
                    "controller competitor provenance manifest is unavailable"
                ) from exc
            if observed_manifest_sha256 != manifest_sha256:
                raise ResourceControllerError(
                    "controller competitor provenance manifest hash drift"
                )
            try:
                competitor_provenance = verify_competitor_provenance(
                    provenance_path,
                    expected_solvers=external_solvers,
                    selected_images={
                        solver: selected_images[solver] for solver in external_solvers
                    },
                )
            except CompetitorProvenanceError as exc:
                raise ResourceControllerError(
                    f"controller competitor provenance rejected: {exc}"
                ) from exc
            if competitor_provenance.get("manifest_sha256") != manifest_sha256:
                raise ResourceControllerError(
                    "controller competitor provenance binding hash mismatch"
                )

    manifest_binding = {
        "mode": execution_mode,
        "config_path": str(resolved_config),
        "config_sha256": _sha256(resolved_config),
        "controller_version": CONTROLLER_VERSION,
        "controller_source_sha256": _sha256(
            ROOT / "benchmarks/itc2019_resource_controller.py"
        ),
        "profile": profile.to_canonical_dict(),
        "profile_sha256": profile.sha256,
        "capability_evidence": controller.capability_evidence,
        "capability_sha256": controller.capability_sha256,
        "capability_refresh": refresh_binding,
        "capability_refresh_sha256": (
            _json_sha256(refresh_binding) if refresh_binding is not None else None
        ),
        "preflight_capability_snapshot": preflight_snapshot,
        "preflight_capability_snapshot_sha256": _json_sha256(preflight_snapshot),
        "post_exit_cgroup_probe": cgroup_probe_binding,
        "post_exit_cgroup_probe_sha256": (
            _json_sha256(cgroup_probe_binding)
            if cgroup_probe_binding is not None
            else None
        ),
        "supervisor_path": str(supervisor_path),
        "supervisor_sha256": supervisor_sha256,
        "solver_images": selected_images,
        "competitor_provenance": competitor_provenance,
        "competitor_provenance_binding_sha256": (
            competitor_provenance["binding_sha256"]
            if competitor_provenance is not None
            else None
        ),
        "solver_argv": {solver: list(selected_argv[solver]) for solver in solvers},
        "solver_argv_sha256": _json_sha256(
            {solver: list(selected_argv[solver]) for solver in solvers}
        ),
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
        "claim_grade_ready": False,
        "execution_admission_ready": (
            execution_mode == CLAIM_GRADE_CONTROLLER_MODE
            and refresh_provider is not None
            and cgroup_provider is not None
        ),
        "claim_evidence_set_sha256": None,
        "readiness_blocker": (
            "Claim readiness is pending authoritative direct evidence for every run."
            if execution_mode == CLAIM_GRADE_CONTROLLER_MODE
            else "Evidence-only mode does not authorize equal-resource claims."
        ),
    }
    return ClaimGradeControllerRuntime(
        controller=controller,
        manifest_binding=manifest_binding,
        supervisor_path=supervisor_path,
        solver_argv_templates=selected_argv,
    )


def _run_identity(
    case: str,
    solver: str,
    seed: int,
    repetition: int,
    *,
    seeds: list[int],
    repetitions: int,
) -> dict[str, Any]:
    if solver in UNSEEDED_SOLVERS:
        trial = seeds.index(int(seed)) * int(repetitions) + int(repetition)
        return {
            "run_id": f"{case}__{solver}__unseeded-trial-{trial:03d}",
            "case": str(case),
            "solver": str(solver),
            "seed": None,
            "effective_seed": None,
            "seed_control": "unsupported_upstream_clock_seed",
            "seed_pairing_group": None,
            "repetition": int(repetition),
            "unseeded_trial": int(trial),
        }
    return {
        "run_id": f"{case}__{solver}__seed-{seed}__rep-{repetition:02d}",
        "case": str(case),
        "solver": str(solver),
        "seed": int(seed),
        "effective_seed": int(seed),
        "seed_control": "explicit",
        "seed_pairing_group": int(seed),
        "repetition": int(repetition),
        "unseeded_trial": None,
    }


def _expected_run_specs(
    cases: list[str],
    solvers: list[str],
    seeds: list[int],
    repetitions: int,
) -> list[dict[str, Any]]:
    return [
        _run_identity(
            case,
            solver,
            seed,
            repetition,
            seeds=seeds,
            repetitions=repetitions,
        )
        for case in cases
        for solver in solvers
        for seed in seeds
        for repetition in range(1, int(repetitions) + 1)
    ]


def _resume_binding_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "schema",
        "cases",
        "instance_set",
        "solvers",
        "seeds",
        "repetitions",
        "configured_solver_seconds",
        "workers",
        "cpu_affinity",
        "input_root",
        "host",
        "inputs",
        "corpus_admission",
        "tool_paths",
        "tools",
        "harness_sha256",
        "official_validator_helper_sha256",
        "resource_policy",
        "resource_controller",
        "expected_runs",
    )
    payload = {field: manifest.get(field) for field in fields}
    controller = payload.get("resource_controller")
    if isinstance(controller, dict):
        controller = json.loads(json.dumps(controller))
        # Preflight freshness is intentionally per process.  Resume binds the
        # immutable capability identity and validates each historical run's own
        # timestamped snapshot instead of requiring timestamp equality.
        controller.pop("preflight_capability_snapshot", None)
        controller.pop("preflight_capability_snapshot_sha256", None)
        # These fields are derived only after every expected run has passed the
        # authoritative evidence parser.  Excluding their final transition keeps
        # each run bound to the immutable preflight contract.
        controller.update(
            {
                "claim_grade_ready": False,
                "equal_wall_time_claim": False,
                "equal_memory_limit_claim": False,
                "claim_evidence_set_sha256": None,
                "readiness_blocker": (
                    "Claim readiness is pending authoritative direct evidence for "
                    "every run."
                    if controller.get("mode") == CLAIM_GRADE_CONTROLLER_MODE
                    else "Evidence-only mode does not authorize equal-resource claims."
                ),
            }
        )
        payload["resource_controller"] = controller
        if controller.get("mode") == CLAIM_GRADE_CONTROLLER_MODE:
            payload["resource_policy"] = dict(QUALITY_ONLY_RESOURCE_POLICY)
    return payload


def _resume_binding_sha256(manifest: dict[str, Any]) -> str:
    return _json_sha256(_resume_binding_payload(manifest))


def _capability_identity_payload(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in evidence.items() if key != "captured_at_unix_ns"
    }


def _git_commit(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _command_version(command: list[str]) -> str | None:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    value = "\n".join(
        item.strip() for item in (result.stdout, result.stderr) if item.strip()
    )
    return value[:2000] or None


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _memory_total_kib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def _tree_digest(paths: Iterable[Path]) -> str:
    rows = []
    for path in sorted((item.resolve() for item in paths), key=str):
        if path.is_file():
            rows.append((str(path), _sha256(path)))
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _corrected_input_hash_errors(input_root: Path, cases: Iterable[str]) -> list[str]:
    """Reject the withdrawn middle instances with infeasible class limits."""

    errors = []
    for case in cases:
        expected = OFFICIAL_CORRECTED_INPUT_SHA256.get(case)
        if expected is None:
            continue
        actual = _sha256(input_root / f"{case}.xml")
        if actual != expected:
            errors.append(f"{case}: expected {expected}, got {actual}")
    return errors


def _claim_grade_case_set_error(
    *, expected: set[str], actual: set[str], label: str
) -> ResourceControllerError:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if extra:
        details.append("extra=" + ",".join(extra))
    return ResourceControllerError(
        f"claim-grade corpus {label} mismatch (" + "; ".join(details) + ")"
    )


def _validate_claim_grade_competition_corpus(
    cases: Iterable[str], input_hashes: Mapping[str, str]
) -> None:
    """Require the exact effective 30-instance organizer corpus."""

    selected = tuple(cases)
    if any(not isinstance(case, str) or not case for case in selected):
        raise ResourceControllerError("claim-grade corpus case list is malformed")
    if len(selected) != len(set(selected)):
        raise ResourceControllerError(
            "claim-grade corpus case list contains duplicates"
        )
    expected_cases = set(COMPETITION_CASES)
    selected_cases = set(selected)
    if selected_cases != expected_cases:
        raise _claim_grade_case_set_error(
            expected=expected_cases,
            actual=selected_cases,
            label="case set",
        )
    if not isinstance(input_hashes, Mapping) or any(
        not isinstance(case, str) for case in input_hashes
    ):
        raise ResourceControllerError("claim-grade corpus input manifest is malformed")
    manifest_cases = set(input_hashes)
    if manifest_cases != expected_cases:
        raise _claim_grade_case_set_error(
            expected=expected_cases,
            actual=manifest_cases,
            label="input manifest key",
        )
    for case in COMPETITION_CASES:
        expected = CANONICAL_COMPETITION_INPUT_SHA256[case]
        actual = input_hashes.get(case)
        if actual != expected:
            raise ResourceControllerError(
                "claim-grade corpus substituted input: "
                f"{case}: expected {expected}, got {actual}"
            )


def _corpus_admission_binding(
    cases: Iterable[str],
    input_hashes: Mapping[str, str],
    *,
    execution_mode: str | None,
) -> dict[str, Any]:
    selected = tuple(cases)
    selected_hashes = {case: input_hashes[case] for case in selected}
    claim_grade = execution_mode == CLAIM_GRADE_CONTROLLER_MODE
    if claim_grade:
        _validate_claim_grade_competition_corpus(selected, selected_hashes)
    return {
        "schema": CORPUS_ADMISSION_SCHEMA,
        "scope": (
            "canonical-effective-competition-30"
            if claim_grade
            else "descriptive-selected-corpus"
        ),
        "claim_grade_ready": claim_grade,
        "selected_instance_count": len(selected),
        "selected_input_manifest_sha256": _json_sha256(selected_hashes),
        "canonical_input_manifest_sha256": _json_sha256(
            CANONICAL_COMPETITION_INPUT_SHA256
        ),
        "effective_corpus_manifest_sha256": (
            ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256
        ),
        "readiness_blocker": (
            None
            if claim_grade
            else "Descriptive corpus selection does not authorize claim-grade comparison."
        ),
    }


def _validate_claim_grade_corpus_manifest(
    manifest: Mapping[str, Any], *, verify_files: bool
) -> None:
    if manifest.get("instance_set") != "competition":
        raise ResourceControllerError(
            "claim-grade controller requires --instance-set competition"
        )
    cases = manifest.get("cases")
    input_hashes = manifest.get("inputs")
    if not isinstance(cases, list) or not isinstance(input_hashes, dict):
        raise ResourceControllerError("claim-grade corpus manifest is malformed")
    _validate_claim_grade_competition_corpus(cases, input_hashes)
    expected_binding = _corpus_admission_binding(
        cases,
        input_hashes,
        execution_mode=CLAIM_GRADE_CONTROLLER_MODE,
    )
    if manifest.get("corpus_admission") != expected_binding:
        raise ResourceControllerError("claim-grade corpus admission binding mismatch")
    if not verify_files:
        return
    input_root = manifest.get("input_root")
    if not isinstance(input_root, str) or not input_root:
        raise ResourceControllerError("claim-grade corpus input root is malformed")
    for case in COMPETITION_CASES:
        try:
            path = (Path(input_root) / f"{case}.xml").resolve(strict=True)
        except OSError as exc:
            raise ResourceControllerError(
                f"claim-grade corpus input is unavailable: {case}"
            ) from exc
        if not path.is_file() or _sha256(path) != input_hashes[case]:
            raise ResourceControllerError(
                f"claim-grade corpus input hash drift: {case}"
            )


def _planora_source_provenance() -> dict[str, Any]:
    """Bind every solver module reachable from the public auto formulation."""

    paths = tuple(ROOT / relative for relative in PLANORA_SOURCE_FILES)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing Planora solver provenance files: " + ", ".join(missing)
        )
    return {
        "source_sha256": _tree_digest(paths),
        "source_files": {
            relative: _sha256(ROOT / relative) for relative in PLANORA_SOURCE_FILES
        },
    }


def _environment(*, maxsat_locale: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "DOTNET_ROLL_FORWARD": "Major",
        }
    )
    if maxsat_locale is not None:
        env.update(
            {
                "LANG": "en_US.UTF-8",
                "LC_ALL": "en_US.UTF-8",
                "LOCPATH": str(maxsat_locale),
            }
        )
    return env


def _score(instance_path: Path, output_path: Path) -> dict[str, Any]:
    problem = parse_itc2019_xml(instance_path)
    solution = parse_itc2019_solution(output_path)
    errors = validate_itc2019_solution_document(problem, solution)
    objective = None
    if not errors:
        objective = score_itc2019_solution(
            problem, solution.placements, solution.student_classes
        ).to_dict()
    return {
        "validator": "planora-separate-post-run-validation-v1",
        "feasible": not errors,
        "errors": list(errors),
        "objective": objective,
    }


def _expected_output_relative_path(identity: Mapping[str, Any]) -> str:
    run_id = identity.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("Run identity has no canonical run_id")
    if (
        Path(run_id).name != run_id
        or "/" in run_id
        or "\\" in run_id
        or ":" in run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("Run identity cannot name a path")
    return (Path("runs") / run_id / "solution.xml").as_posix()


def _artifact_binding(
    identity: Mapping[str, Any], *, relative_path: str, output_sha256: str
) -> str:
    return _json_sha256(
        {
            "identity": {
                field: identity.get(field) for field in _ARTIFACT_BINDING_FIELDS
            },
            "output_relative_path": relative_path,
            "output_sha256": output_sha256,
        }
    )


def _output_artifact_metadata(
    matrix_root: Path,
    identity: Mapping[str, Any],
    output_path: Path,
) -> dict[str, str]:
    resolved_root = matrix_root.resolve(strict=True)
    resolved_output = output_path.resolve(strict=True)
    if not resolved_output.is_file():
        raise ValueError("Solution artifact is not a regular file")
    try:
        relative_path = resolved_output.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError("Solution artifact escapes the matrix root") from exc
    expected_relative_path = _expected_output_relative_path(identity)
    if relative_path != expected_relative_path:
        raise ValueError("Solution artifact is not at its deterministic run path")
    output_sha256 = _sha256(resolved_output)
    return {
        "output_path": str(resolved_output),
        "output_relative_path": relative_path,
        "output_sha256": output_sha256,
        "artifact_binding_sha256": _artifact_binding(
            identity,
            relative_path=relative_path,
            output_sha256=output_sha256,
        ),
    }


def _no_artifact_validation(identity: Mapping[str, Any]) -> dict[str, Any]:
    expected_relative_path = _expected_output_relative_path(identity)
    observation = {
        "status": "absent",
        "expected_output_relative_path": expected_relative_path,
        "checked_after_solver_exit": True,
    }
    observation["binding_sha256"] = _json_sha256(
        {
            "identity": {
                field: identity.get(field) for field in _ARTIFACT_BINDING_FIELDS
            },
            **observation,
        }
    )
    return {
        "validator": "planora-separate-post-run-validation-v1",
        "status": _NO_ARTIFACT_VALIDATION_STATUS,
        "feasible": None,
        "errors": [
            "No solution artifact was produced; schedule feasibility remains unknown."
        ],
        "objective": None,
        "artifact_observation": observation,
    }


def _planora_worker(args: argparse.Namespace) -> int:
    instance_path = Path(args.instance).resolve()
    output_path = Path(args.output).resolve()
    problem = parse_itc2019_xml(instance_path)
    result = solve_itc2019_native(
        problem,
        time_limit_seconds=float(args.time_limit),
        workers=1,
        random_seed=int(args.seed),
        formulation="auto",
    )
    if result.is_feasible:
        write_itc2019_solution(
            problem,
            result.placements,
            result.student_classes,
            output_path,
            metadata={
                "runtime": f"{result.wall_time_seconds:.6f}",
                "cores": "1",
                "technique": "Planora native auto formulation",
            },
        )
    print(
        "PLANORA_ITC2019_RESULT="
        + json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return 0 if result.is_feasible else 2


def _render_cpsolver_config(*, source: Path, seconds: float, seed: int) -> str:
    lines = source.read_text(encoding="utf-8").splitlines()
    overrides = {
        "Termination.TimeOut": str(max(1, int(math.ceil(seconds)))),
        "Parallel.NrSolvers": "1",
        "General.Seed": str(int(seed)),
        "General.SaveBestUnassigned": "-1",
    }
    seen: set[str] = set()
    rewritten = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in overrides:
            rewritten.append(f"{key}={overrides[key]}")
            seen.add(key)
        else:
            rewritten.append(line)
    for key in sorted(set(overrides) - seen):
        rewritten.append(f"{key}={overrides[key]}")
    return "\n".join(rewritten) + "\n"


def _write_cpsolver_config(
    destination: Path, *, source: Path, seconds: float, seed: int
) -> None:
    destination.write_text(
        _render_cpsolver_config(source=source, seconds=seconds, seed=seed),
        encoding="utf-8",
    )


def _command_for(
    solver: str,
    *,
    instance_path: Path,
    run_dir: Path,
    output_path: Path,
    seed: int,
    seconds: float,
    cpu: int,
    gashi: Path,
    cps_root: Path,
    maxsat: Path,
    write_config: bool = True,
) -> tuple[list[str], Path, float, str]:
    if solver == "planora":
        return (
            [
                "taskset",
                "-c",
                str(cpu),
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--instance",
                str(instance_path),
                "--output",
                str(output_path),
                "--seed",
                str(seed),
                "--time-limit",
                str(seconds),
            ],
            ROOT,
            seconds + PLANORA_COMPLETION_OVERHEAD_SECONDS,
            (
                "internal wall deadline includes model construction and search; "
                "bounded process overhead covers input parse, solution serialization, "
                "and result handoff"
            ),
        )
    if solver == "gashi-sa":
        return (
            [
                "taskset",
                "-c",
                str(cpu),
                "dotnet",
                str(gashi),
                "--instance",
                str(instance_path),
                "--seed",
                str(seed),
            ],
            run_dir,
            seconds,
            "whole solver process until SIGINT, followed by bounded solution save",
        )
    if solver == "unitime-cpsolver":
        config = run_dir / "cpsolver.cfg"
        if write_config:
            _write_cpsolver_config(
                config,
                source=cps_root / "configuration/default.cfg",
                seconds=seconds,
                seed=seed,
            )
        return (
            [
                "taskset",
                "-c",
                str(cpu),
                "java",
                "-XX:ActiveProcessorCount=1",
                "-Xmx768m",
                "-jar",
                str(cps_root / "target/cpsolver-itc2019-1.0-SNAPSHOT.jar"),
                str(config),
                str(instance_path),
                str(run_dir / "cpsolver-output"),
            ],
            run_dir,
            seconds + CPSOLVER_COMPLETION_OVERHEAD_SECONDS,
            (
                "configured Termination.TimeOut applies to search; one solver; "
                "bounded model-load, student-switch, and serialization overhead"
            ),
        )
    if solver == "lemos-maxsat":
        (run_dir / "data/output/ITC-2019").mkdir(parents=True, exist_ok=True)
        return (
            [
                "taskset",
                "-c",
                str(cpu),
                str(maxsat.resolve()),
                str(instance_path.resolve()),
                "-formula=1",
                "-verbosity=0",
                "-algorithm=6",
                "-pb=0",
                "-opt-allocation",
                "-opt-stu",
                "-opt-cons",
                f"-cpu-lim={max(1, int(math.ceil(seconds)))}",
            ],
            run_dir,
            seconds + MAXSAT_COMPLETION_OVERHEAD_SECONDS,
            (
                "internal CPU limit in a host process pinned to one CPU; "
                "bounded model, student-allocation, and serialization completion overhead"
            ),
        )
    raise ValueError(f"Unknown solver: {solver}")


def _find_output(solver: str, run_dir: Path, expected: Path) -> Path | None:
    if expected.is_file() and expected.stat().st_size:
        return expected
    candidates: list[Path] = []
    if solver == "gashi-sa":
        candidates = list(run_dir.glob("solution_*.xml"))
    elif solver == "unitime-cpsolver":
        candidates = list((run_dir / "cpsolver-output").glob("**/solution.xml"))
    elif solver == "lemos-maxsat":
        candidates = list((run_dir / "data/output/ITC-2019").glob("*.xml"))
    candidates = [path for path in candidates if path.is_file() and path.stat().st_size]
    return (
        max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    )


def _peak_rss_kb(pid: int) -> int:
    total = 0
    pending = [int(pid)]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        status = Path(f"/proc/{current}/status")
        children = Path(f"/proc/{current}/task/{current}/children")
        try:
            for line in status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
            if children.is_file():
                pending.extend(int(value) for value in children.read_text().split())
        except (FileNotFoundError, ProcessLookupError, ValueError):
            continue
    return total


def _overrun_signal(solver: str) -> signal.Signals:
    if solver == "lemos-maxsat":
        # The pinned upstream binary installs a SIGTERM handler that dereferences
        # an uninitialised global solver pointer.  SIGKILL preserves the original
        # algorithm and converts a supervisor overrun into an unambiguous timeout
        # instead of a misleading SIGSEGV from that crash-only handler.
        return signal.SIGKILL
    return signal.SIGTERM


def _run_one(
    solver: str,
    *,
    identity: dict[str, Any],
    case: str,
    instance_path: Path,
    root: Path,
    seed: int,
    repetition: int,
    seconds: float,
    cpu: int,
    gashi: Path,
    cps_root: Path,
    maxsat: Path,
    maxsat_locale: Path,
    resume_binding_sha256: str,
) -> dict[str, Any]:
    run_id = str(identity["run_id"])
    run_dir = root / "runs" / run_id
    orphan_lineage = None
    if run_dir.exists() and not (run_dir / "result.json").is_file():
        orphan = run_dir.with_name(f"{run_dir.name}.incomplete-{time.time_ns()}")
        run_dir.rename(orphan)
        orphan_lineage = {
            "state": "fail_closed_rerun",
            "previous_run_directory": str(orphan.resolve()),
            "previous_run_directory_name": orphan.name,
        }
    run_dir.mkdir(parents=True, exist_ok=False)
    expected = run_dir / "solution.xml"
    command, cwd, supervisor_seconds, budget_basis = _command_for(
        solver,
        instance_path=instance_path,
        run_dir=run_dir,
        output_path=expected,
        seed=seed,
        seconds=seconds,
        cpu=cpu,
        gashi=gashi,
        cps_root=cps_root,
        maxsat=maxsat,
    )
    command_sha256 = _json_sha256(command)
    run_configuration_sha256 = (
        _sha256(run_dir / "cpsolver.cfg") if solver == "unitime-cpsolver" else None
    )
    state = {
        "schema": "planora.itc2019.run-state.v1",
        **dict(identity),
        "status": "running",
        "run_directory": str(run_dir.resolve()),
        "input_path": str(instance_path.resolve()),
        "input_sha256": _sha256(instance_path),
        "configured_solver_seconds": float(seconds),
        "configured_workers": 1,
        "cpu_affinity": int(cpu),
        "command": list(command),
        "command_sha256": command_sha256,
        "run_configuration_sha256": run_configuration_sha256,
        "resume_binding_sha256": str(resume_binding_sha256),
        "orphan_lineage": orphan_lineage,
    }
    _write_json_atomic(run_dir / "state.json", state)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    started = time.perf_counter()
    peak_rss = 0
    timed_out = False
    supervisor_termination_signal = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=_environment(
                maxsat_locale=maxsat_locale if solver == "lemos-maxsat" else None
            ),
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        deadline = started + supervisor_seconds
        signal_at = started + seconds if solver == "gashi-sa" else None
        signalled = False
        while process.poll() is None:
            peak_rss = max(peak_rss, _peak_rss_kb(process.pid))
            now = time.perf_counter()
            if signal_at is not None and now >= signal_at and not signalled:
                os.killpg(process.pid, signal.SIGINT)
                signalled = True
                deadline = now + 5.0
            if now >= deadline:
                timed_out = True
                termination_signal = _overrun_signal(solver)
                supervisor_termination_signal = termination_signal.name
                os.killpg(process.pid, termination_signal)
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.02)
        exit_code = process.wait()
    wall = time.perf_counter() - started
    found = _find_output(solver, run_dir, expected)
    if found is not None and found != expected:
        shutil.copy2(found, expected)
        found = expected
    artifact_metadata = (
        _output_artifact_metadata(root, identity, found)
        if found is not None
        else {
            "output_path": None,
            "output_relative_path": None,
            "output_sha256": None,
            "artifact_binding_sha256": None,
        }
    )
    score = _no_artifact_validation(identity) if found is None else None
    parse_error = None
    if found is not None:
        try:
            score = _score(instance_path, found)
        except Exception as exc:  # competitor output is deliberately untrusted
            parse_error = f"{type(exc).__name__}: {exc}"
    record = {
        **dict(identity),
        "configured_solver_seconds": float(seconds),
        "configured_workers": 1,
        "cpu_affinity": int(cpu),
        "budget_basis": budget_basis,
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
        "comparison_scope": QUALITY_ONLY_RESOURCE_POLICY["comparison_scope"],
        "command": list(command),
        "command_sha256": command_sha256,
        "run_configuration_sha256": run_configuration_sha256,
        "working_directory": str(cwd),
        "controlled_environment": {
            key: _environment(
                maxsat_locale=maxsat_locale if solver == "lemos-maxsat" else None
            )[key]
            for key in (
                "PYTHONHASHSEED",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "DOTNET_ROLL_FORWARD",
                "LANG",
                "LC_ALL",
                "LOCPATH",
            )
            if key
            in _environment(
                maxsat_locale=maxsat_locale if solver == "lemos-maxsat" else None
            )
        },
        "process_wall_seconds": float(wall),
        "supervisor_deadline_seconds": float(supervisor_seconds),
        "supervisor_termination_signal": supervisor_termination_signal,
        "peak_rss_kb": int(peak_rss),
        "timed_out": bool(timed_out),
        "exit_code": int(exit_code),
        "input_path": str(instance_path.resolve()),
        "input_sha256": _sha256(instance_path),
        **artifact_metadata,
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
        "resume_binding_sha256": str(resume_binding_sha256),
        "orphan_lineage": orphan_lineage,
        "independent_validation": score,
        "parse_error": parse_error,
        "official_validator_status": "pending_upload",
        "official_validator_agreement": None,
    }
    result_path = run_dir / "result.json"
    _write_json_atomic(result_path, record)
    state.update({"status": "complete", "initial_result_sha256": _sha256(result_path)})
    _write_json_atomic(run_dir / "state.json", state)
    return record


def _controller_invocation(
    runtime: ClaimGradeControllerRuntime,
    *,
    identity: Mapping[str, Any],
    solver: str,
    instance_path: Path,
    run_dir: Path,
    seed: int,
    seconds: float,
    capability_snapshot_sha256: str,
) -> SolverInvocation:
    template = runtime.solver_argv_templates.get(solver)
    image = runtime.manifest_binding["solver_images"].get(solver)
    if template is None or not isinstance(image, str):
        raise ResourceControllerError(
            f"controller runtime is incomplete for selected solver: {solver}"
        )
    claim_grade = runtime.manifest_binding.get("mode") == CLAIM_GRADE_CONTROLLER_MODE
    if claim_grade:
        _validate_claim_grade_argv_template(template, solver)
    rendered_argv = _render_controller_argv(template, seed=seed, seconds=seconds)
    if claim_grade:
        _validate_claim_grade_executed_argv(
            rendered_argv,
            solver,
            seed=seed,
            seconds=seconds,
        )
    return SolverInvocation(
        run_id=str(identity["run_id"]),
        solver=solver,
        image=image,
        argv=rendered_argv,
        host_run_directory=str(run_dir.resolve()),
        input_mounts=((str(instance_path.resolve()), "/inputs/instance.xml"),),
        binary_mounts=(
            (
                str(runtime.supervisor_path.resolve()),
                "/opt/planora/itc2019-container-supervisor",
            ),
        ),
        artifact_relative_path="solution.xml",
        capability_snapshot_sha256=capability_snapshot_sha256,
    )


def _controller_execution_evidence(
    runtime: ClaimGradeControllerRuntime,
    invocation: SolverInvocation,
    execution: Any,
    *,
    output_sha256: str | None,
    capability_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    cleanup = [asdict(item) for item in runtime.controller.last_cleanup_outcomes]
    binding = runtime.manifest_binding
    return {
        "schema": DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
        "mode": EVIDENCE_ONLY_CONTROLLER_MODE,
        "run_id": invocation.run_id,
        "controller_version": binding["controller_version"],
        "controller_source_sha256": binding["controller_source_sha256"],
        "config_sha256": binding["config_sha256"],
        "profile": binding["profile"],
        "profile_sha256": binding["profile_sha256"],
        "capability_sha256": binding["capability_sha256"],
        "capability_snapshot": dict(capability_snapshot),
        "capability_snapshot_sha256": _json_sha256(capability_snapshot),
        "supervisor_sha256": binding["supervisor_sha256"],
        "image_reference": invocation.image,
        "invocation": invocation.to_canonical_dict(),
        "invocation_sha256": invocation.sha256,
        "execution": asdict(execution),
        "cleanup": cleanup,
        "artifact_sha256": output_sha256,
        "trusted_supervisor_evidence_complete": False,
        "post_exit_cgroup_evidence_complete": False,
        "cross_runtime_image_guarantees_complete": False,
        "claim_grade_ready": False,
        "readiness_blocker": binding["readiness_blocker"],
    }


def _finish_controller_run(
    runtime: ClaimGradeControllerRuntime,
    invocation: SolverInvocation,
    *,
    capability_snapshot: Mapping[str, Any],
    identity: dict[str, Any],
    instance_path: Path,
    root: Path,
    run_dir: Path,
    seconds: float,
    cpu: int,
    resume_binding_sha256: str,
    orphan_lineage: dict[str, Any] | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    execution = runtime.controller.execute(
        invocation, capability_snapshot=capability_snapshot
    )
    if (
        _sha256(runtime.supervisor_path)
        != runtime.manifest_binding["supervisor_sha256"]
    ):
        raise ResourceControllerError("controller supervisor hash drift after run")
    expected = run_dir / invocation.artifact_relative_path
    found = expected if expected.is_file() else None
    artifact_metadata = (
        _output_artifact_metadata(root, identity, found)
        if found is not None
        else {
            "output_path": None,
            "output_relative_path": None,
            "output_sha256": None,
            "artifact_binding_sha256": None,
        }
    )
    output_sha256 = artifact_metadata["output_sha256"]
    raw_evidence = None
    raw_evidence_path = None
    raw_evidence_sha256 = None
    raw_evidence_file_sha256 = None
    if runtime.manifest_binding["mode"] == CLAIM_GRADE_CONTROLLER_MODE:
        inspect = runtime.controller.last_final_inspect
        cgroup = runtime.controller.last_post_exit_cgroup_evidence
        supervisor = _read_json_object(
            run_dir / SUPERVISOR_EVIDENCE_RELATIVE_PATH,
            "trusted supervisor evidence",
        )
        cleanup_outcomes = [
            asdict(item) for item in runtime.controller.last_cleanup_outcomes
        ]
        raw_evidence = {
            "schema": RAW_RESOURCE_EVIDENCE_SCHEMA,
            "invocation_sha256": invocation.sha256,
            "inspect": inspect,
            "execution": asdict(execution),
            "cgroup": cgroup,
            "supervisor": supervisor,
            "capability_snapshot": dict(capability_snapshot),
            "cleanup_outcomes": cleanup_outcomes,
        }
        parsed_evidence = runtime.controller.parse_evidence(
            invocation,
            inspect=inspect,
            execution=execution,
            cgroup=cgroup,
            supervisor=supervisor,
            capability_snapshot=capability_snapshot,
            cleanup_outcomes=cleanup_outcomes,
        )
        evidence = parsed_evidence.to_canonical_dict()
        if not runtime.controller.authorizes_claim_grade_evidence(evidence):
            raise ResourceControllerError(
                "authoritative parser did not grant evidence provenance"
            )
        if evidence["artifact_sha256"] != output_sha256:
            raise ResourceControllerError(
                "authoritative artifact evidence does not match runner output"
            )
        raw_evidence_path = run_dir / "resource-evidence-raw.json"
        _write_json_atomic(raw_evidence_path, raw_evidence)
        raw_evidence_sha256 = _json_sha256(raw_evidence)
        raw_evidence_file_sha256 = _sha256(raw_evidence_path)
    else:
        evidence = _controller_execution_evidence(
            runtime,
            invocation,
            execution,
            output_sha256=output_sha256,
            capability_snapshot=capability_snapshot,
        )
    evidence_path = run_dir / "resource-evidence.json"
    _write_json_atomic(evidence_path, evidence)
    evidence_sha256 = resource_evidence_sha256(evidence)
    evidence_file_sha256 = _sha256(evidence_path)

    score = _no_artifact_validation(identity) if found is None else None
    parse_error = None
    if found is not None:
        try:
            score = _score(instance_path, found)
        except Exception as exc:  # container output is deliberately untrusted
            parse_error = f"{type(exc).__name__}: {exc}"
    wall_seconds = (
        execution.host_finished_monotonic_ns - execution.host_started_monotonic_ns
    ) / 1e9
    record = {
        **dict(identity),
        "configured_solver_seconds": float(seconds),
        "configured_workers": 1,
        "cpu_affinity": int(cpu),
        "budget_basis": CONTROLLER_BUDGET_BASIS,
        "equal_wall_time_claim": evidence.get("claim_grade_ready") is True,
        "equal_memory_limit_claim": evidence.get("claim_grade_ready") is True,
        "comparison_scope": (
            CLAIM_GRADE_RESOURCE_POLICY["comparison_scope"]
            if evidence.get("claim_grade_ready") is True
            else QUALITY_ONLY_RESOURCE_POLICY["comparison_scope"]
        ),
        "execution_mode": str(runtime.manifest_binding["mode"]),
        "command": list(invocation.argv),
        "command_sha256": _json_sha256(list(invocation.argv)),
        "run_configuration_sha256": None,
        "working_directory": invocation.container_run_directory,
        "controlled_environment": {},
        "process_wall_seconds": float(wall_seconds),
        "supervisor_deadline_seconds": float(
            runtime.controller.profile.wall_time_seconds
            + runtime.controller.profile.artifact_grace_seconds
        ),
        "supervisor_termination_signal": None,
        "peak_rss_kb": None,
        "timed_out": bool(execution.timed_out),
        "exit_code": int(execution.attach_returncode),
        "input_path": str(instance_path.resolve()),
        "input_sha256": _sha256(instance_path),
        **artifact_metadata,
        "stdout_path": None,
        "stderr_path": None,
        "resume_binding_sha256": str(resume_binding_sha256),
        "orphan_lineage": orphan_lineage,
        "controller_invocation": invocation.to_canonical_dict(),
        "controller_invocation_sha256": invocation.sha256,
        "resource_evidence": evidence,
        "resource_evidence_path": str(evidence_path.resolve()),
        "resource_evidence_sha256": evidence_sha256,
        "resource_evidence_file_sha256": evidence_file_sha256,
        "raw_resource_evidence": raw_evidence,
        "raw_resource_evidence_path": (
            str(raw_evidence_path.resolve()) if raw_evidence_path is not None else None
        ),
        "raw_resource_evidence_sha256": raw_evidence_sha256,
        "raw_resource_evidence_file_sha256": raw_evidence_file_sha256,
        "independent_validation": score,
        "parse_error": parse_error,
        "official_validator_status": "pending_upload",
        "official_validator_agreement": None,
    }
    result_path = run_dir / "result.json"
    _write_json_atomic(result_path, record)
    state.update({"status": "complete", "initial_result_sha256": _sha256(result_path)})
    _write_json_atomic(run_dir / "state.json", state)
    return record


def _run_one_controller(
    runtime: ClaimGradeControllerRuntime,
    solver: str,
    *,
    identity: dict[str, Any],
    case: str,
    instance_path: Path,
    root: Path,
    seed: int,
    repetition: int,
    seconds: float,
    cpu: int,
    resume_binding_sha256: str,
) -> dict[str, Any]:
    """Execute exclusively through DockerCgroupV2Controller.

    This path deliberately has no call to ``_run_one`` and no host-process
    fallback. Claim mode invokes the authoritative direct-evidence parser;
    evidence-only mode emits an explicitly descriptive record.
    """

    run_id = str(identity["run_id"])
    run_dir = root / "runs" / run_id
    orphan_lineage = None
    if run_dir.exists() and not (run_dir / "result.json").is_file():
        orphan = run_dir.with_name(f"{run_dir.name}.incomplete-{time.time_ns()}")
        run_dir.rename(orphan)
        orphan_lineage = {
            "state": "fail_closed_rerun",
            "previous_run_directory": str(orphan.resolve()),
            "previous_run_directory_name": orphan.name,
        }
    run_dir.mkdir(parents=True, exist_ok=False)
    if (
        _sha256(runtime.supervisor_path)
        != runtime.manifest_binding["supervisor_sha256"]
    ):
        raise ResourceControllerError("controller supervisor hash drift before run")
    capability_snapshot = runtime.controller.refresh_capability_evidence()
    capability_snapshot_sha256 = _json_sha256(capability_snapshot)
    invocation = _controller_invocation(
        runtime,
        identity=identity,
        solver=solver,
        instance_path=instance_path,
        run_dir=run_dir,
        seed=seed,
        seconds=seconds,
        capability_snapshot_sha256=capability_snapshot_sha256,
    )
    state = {
        "schema": "planora.itc2019.run-state.v1",
        **dict(identity),
        "status": "running",
        "execution_mode": str(runtime.manifest_binding["mode"]),
        "run_directory": str(run_dir.resolve()),
        "input_path": str(instance_path.resolve()),
        "input_sha256": _sha256(instance_path),
        "configured_solver_seconds": float(seconds),
        "configured_workers": 1,
        "cpu_affinity": int(cpu),
        "controller_invocation": invocation.to_canonical_dict(),
        "controller_invocation_sha256": invocation.sha256,
        "resume_binding_sha256": str(resume_binding_sha256),
        "orphan_lineage": orphan_lineage,
    }
    _write_json_atomic(run_dir / "state.json", state)

    try:
        return _finish_controller_run(
            runtime,
            invocation,
            capability_snapshot=capability_snapshot,
            identity=identity,
            instance_path=instance_path,
            root=root,
            run_dir=run_dir,
            seconds=seconds,
            cpu=cpu,
            resume_binding_sha256=resume_binding_sha256,
            orphan_lineage=orphan_lineage,
            state=state,
        )
    except BaseException as primary_error:
        cleanup_complete = False
        try:
            cleanup_complete = runtime.controller.cleanup_after_failure(invocation)
        except BaseException as cleanup_error:
            primary_error.add_note(
                "post-create cleanup raised "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        try:
            cleanup_outcomes = [
                asdict(item) for item in runtime.controller.last_cleanup_outcomes
            ]
        except BaseException as outcome_error:
            cleanup_outcomes = []
            primary_error.add_note(
                "cleanup outcome recording raised "
                f"{type(outcome_error).__name__}: {outcome_error}"
            )
        state.update(
            {
                "status": "failed",
                "failure_type": type(primary_error).__name__,
                "failure": str(primary_error),
                "cleanup_complete": cleanup_complete,
                "cleanup_outcomes": cleanup_outcomes,
            }
        )
        try:
            _write_json_atomic(run_dir / "state.json", state)
        except BaseException as state_error:
            primary_error.add_note(
                "failure state recording raised "
                f"{type(state_error).__name__}: {state_error}"
            )
        raise


def _tool_provenance(args: argparse.Namespace) -> dict[str, Any]:
    cps_jars = list((Path(args.cpsolver_root) / "target").glob("*.jar"))
    gashi_files = list(Path(args.gashi).parent.glob("*"))
    locale_files = list(Path(args.maxsat_locale).rglob("*"))
    return {
        "planora": {
            "git_commit": _git_commit(ROOT),
            "git_status_sha256": hashlib.sha256(
                subprocess.run(
                    ["git", "status", "--porcelain=v1"],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                ).stdout
            ).hexdigest(),
            **_planora_source_provenance(),
            "ortools_version": str(ortools.__version__),
        },
        "gashi-sa": {
            "git_commit": _git_commit(Path(args.gashi).parents[2]),
            "artifact_sha256": _tree_digest(gashi_files),
            "dotnet_version": _command_version(["dotnet", "--info"]),
        },
        "unitime-cpsolver": {
            "git_commit": _git_commit(Path(args.cpsolver_root)),
            "cpsolver_core_git_commit": _git_commit(Path("/tmp/planora-cpsolver-core")),
            "artifact_sha256": _tree_digest(cps_jars),
            "java_version": _command_version(["java", "-version"]),
            "configuration_sha256": _sha256(
                Path(args.cpsolver_root) / "configuration/default.cfg"
            ),
        },
        "lemos-maxsat": {
            "git_commit": _git_commit(Path(args.maxsat).parent),
            "binary_sha256": _sha256(Path(args.maxsat)),
            "locale_root": str(Path(args.maxsat_locale).resolve()),
            "locale_sha256": _tree_digest(locale_files),
        },
    }


def _summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in records:
        groups.setdefault((row["case"], row["solver"]), []).append(row)
    summary = []
    for (case, solver), rows in sorted(groups.items()):
        valid = [
            row
            for row in rows
            if (row.get("independent_validation") or {}).get("feasible") is True
        ]
        scores = [
            int(row["independent_validation"]["objective"]["total"]) for row in valid
        ]
        walls = [float(row["process_wall_seconds"]) for row in rows]
        summary.append(
            {
                "case": case,
                "solver": solver,
                "runs": len(rows),
                "valid_runs": len(valid),
                "best_score": min(scores) if scores else None,
                "median_score": sorted(scores)[len(scores) // 2] if scores else None,
                "median_process_wall_seconds": sorted(walls)[len(walls) // 2],
                "max_process_wall_seconds": max(walls),
                "official_validator_agreement_complete": all(
                    row.get("official_validator_agreement") is True for row in rows
                ),
            }
        )
    return summary


def _write_report(
    root: Path,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    official_validation: dict[str, Any] | None = None,
) -> None:
    payload = {
        "manifest": manifest,
        "records": records,
        "summary": _summary(records),
    }
    if official_validation is not None:
        payload["official_validation"] = dict(official_validation)
    _write_json_atomic(root / "report.json", payload)


def _assert_complete_record_set(
    records: list[dict[str, Any]], manifest: dict[str, Any]
) -> None:
    expected = [str(item["run_id"]) for item in manifest.get("expected_runs") or []]
    actual = [str(item.get("run_id", "")) for item in records]
    if (
        len(expected) != len(set(expected))
        or len(actual) != len(set(actual))
        or len(expected) != len(actual)
        or set(expected) != set(actual)
    ):
        raise ValueError(
            "The completed benchmark record set does not match the manifest"
        )


def _controller_seed_for_expected_run(
    manifest: Mapping[str, Any], expected: Mapping[str, Any]
) -> int:
    effective_seed = expected.get("effective_seed")
    if isinstance(effective_seed, int) and not isinstance(effective_seed, bool):
        return effective_seed
    if expected.get("solver") != "lemos-maxsat":
        raise ResourceControllerError("expected controller run has no effective seed")
    seeds = manifest.get("seeds")
    repetitions = manifest.get("repetitions")
    trial = expected.get("unseeded_trial")
    repetition = expected.get("repetition")
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
        or not isinstance(repetitions, int)
        or isinstance(repetitions, bool)
        or repetitions < 1
        or not isinstance(trial, int)
        or isinstance(trial, bool)
        or not isinstance(repetition, int)
        or isinstance(repetition, bool)
    ):
        raise ResourceControllerError("unseeded controller run identity is malformed")
    seed_index, derived_repetition = divmod(trial - 1, repetitions)
    if (
        seed_index < 0
        or seed_index >= len(seeds)
        or derived_repetition + 1 != repetition
    ):
        raise ResourceControllerError(
            "unseeded controller trial identity is inconsistent"
        )
    return int(seeds[seed_index])


def _refresh_competitor_provenance_for_claims(
    controller: Mapping[str, Any],
    *,
    selected_solvers: Iterable[str] | None = None,
) -> None:
    images = controller.get("solver_images")
    external_solvers = (
        [solver for solver in selected_solvers if solver in EXTERNAL_COMPETITOR_SOLVERS]
        if selected_solvers is not None
        else [
            solver
            for solver in (images if isinstance(images, dict) else ())
            if solver in EXTERNAL_COMPETITOR_SOLVERS
        ]
    )
    if not external_solvers:
        return
    if not isinstance(images, dict):
        raise ResourceControllerError(
            "claim-grade finalization competitor image binding is missing"
        )
    provenance = controller.get("competitor_provenance")
    if (
        not isinstance(provenance, dict)
        or not isinstance(provenance.get("manifest_path"), str)
        or provenance.get("binding_sha256")
        != controller.get("competitor_provenance_binding_sha256")
    ):
        raise ResourceControllerError(
            "claim-grade finalization competitor provenance binding is malformed"
        )
    try:
        refreshed = verify_competitor_provenance(
            Path(provenance["manifest_path"]),
            expected_solvers=external_solvers,
            selected_images={solver: images[solver] for solver in external_solvers},
        )
    except CompetitorProvenanceError as exc:
        raise ResourceControllerError(
            f"claim-grade finalization competitor provenance rejected: {exc}"
        ) from exc
    if not provenance_bindings_match_exactly(refreshed, provenance):
        raise ResourceControllerError(
            "claim-grade finalization competitor provenance binding drift"
        )


def _claim_finalization_solver_set(
    manifest: Mapping[str, Any],
    controller: Mapping[str, Any],
    runtime: ClaimGradeControllerRuntime,
) -> list[str]:
    manifest_solvers_value = manifest.get("solvers")
    manifest_solvers = (
        manifest_solvers_value
        if isinstance(manifest_solvers_value, list)
        and all(isinstance(item, str) for item in manifest_solvers_value)
        and len(manifest_solvers_value) == len(set(manifest_solvers_value))
        else None
    )
    expected_runs = manifest.get("expected_runs")
    expected_solvers = (
        {
            str(item["solver"])
            for item in expected_runs
            if isinstance(item, dict) and isinstance(item.get("solver"), str)
        }
        if isinstance(expected_runs, list)
        and all(isinstance(item, dict) for item in expected_runs)
        else set()
    )
    controller_images = controller.get("solver_images")
    controller_argv = controller.get("solver_argv")
    runtime_binding = runtime.manifest_binding
    runtime_images = (
        runtime_binding.get("solver_images")
        if isinstance(runtime_binding, dict)
        else None
    )
    runtime_argv = (
        runtime_binding.get("solver_argv")
        if isinstance(runtime_binding, dict)
        else None
    )
    sets = {
        "manifest": set(manifest_solvers or ()),
        "expected_runs": expected_solvers,
        "controller_images": (
            set(controller_images) if isinstance(controller_images, dict) else set()
        ),
        "controller_argv": (
            set(controller_argv) if isinstance(controller_argv, dict) else set()
        ),
        "runtime_images": (
            set(runtime_images) if isinstance(runtime_images, dict) else set()
        ),
        "runtime_argv": (
            set(runtime_argv) if isinstance(runtime_argv, dict) else set()
        ),
        "runtime_templates": set(runtime.solver_argv_templates),
    }
    union = set().union(*sets.values())
    if union & EXTERNAL_COMPETITOR_SOLVERS:
        if (
            manifest_solvers is None
            or not union
            or any(value != union for value in sets.values())
            or controller_images != runtime_images
            or controller_argv != runtime_argv
            or controller_argv
            != {
                solver: list(template)
                for solver, template in runtime.solver_argv_templates.items()
            }
            or not provenance_bindings_match_exactly(
                controller.get("competitor_provenance"),
                runtime_binding.get("competitor_provenance"),
            )
            or controller.get("competitor_provenance_binding_sha256")
            != runtime_binding.get("competitor_provenance_binding_sha256")
        ):
            details = ", ".join(
                f"{label}={sorted(value)}" for label, value in sets.items()
            )
            raise ResourceControllerError(
                "claim-grade finalization solver-set mismatch: " + details
            )
        return list(manifest_solvers)
    if manifest_solvers is not None:
        return list(manifest_solvers)
    if isinstance(controller_images, dict):
        return list(controller_images)
    return sorted(expected_solvers)


def _finalize_controller_claims(
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    root: Path,
    controller_runtime: ClaimGradeControllerRuntime | None = None,
) -> None:
    controller = manifest.get("resource_controller")
    if not isinstance(controller, dict) or controller.get("mode") != (
        CLAIM_GRADE_CONTROLLER_MODE
    ):
        return
    _validate_claim_grade_corpus_manifest(manifest, verify_files=True)
    if controller_runtime is None:
        raise ResourceControllerError(
            "claim-grade finalization requires authoritative evidence with "
            "in-process parser provenance"
        )
    finalization_solvers = _claim_finalization_solver_set(
        manifest, controller, controller_runtime
    )
    _refresh_competitor_provenance_for_claims(
        controller,
        selected_solvers=finalization_solvers,
    )
    _assert_complete_record_set(records, manifest)
    expected_by_run_id = {
        str(item["run_id"]): dict(item)
        for item in list(manifest.get("expected_runs") or [])
    }
    matrix_root = root.resolve()
    runs_root = (matrix_root / "runs").resolve()
    evidence_bindings: list[dict[str, str]] = []
    seen_evidence_sha256: set[str] = set()
    seen_invocation_sha256: set[str] = set()
    seen_controller_identities: dict[str, set[str]] = {
        field: set()
        for field in (
            "container_id",
            "container_name",
            "cgroup_path",
            "cgroup_identity",
        )
    }
    for row in sorted(records, key=lambda item: str(item.get("run_id", ""))):
        run_id = str(row["run_id"])
        expected = expected_by_run_id[run_id]
        evidence = row.get("resource_evidence")
        evidence_sha256 = row.get("resource_evidence_sha256")
        if (
            not isinstance(evidence, dict)
            or evidence.get("schema") != RESOURCE_EVIDENCE_SCHEMA
            or evidence.get("claim_grade_ready") is not True
            or row.get("equal_wall_time_claim") is not True
            or row.get("equal_memory_limit_claim") is not True
            or not isinstance(evidence_sha256, str)
            or resource_evidence_sha256(evidence) != evidence_sha256
            or not controller_runtime.controller.authorizes_claim_grade_evidence(
                evidence
            )
        ):
            raise ResourceControllerError(
                "claim-grade finalization requires authoritative evidence for every run"
            )
        for field in _ARTIFACT_BINDING_FIELDS:
            if row.get(field) != expected.get(field):
                raise ResourceControllerError(
                    f"claim-grade record identity mismatch ({field}): {run_id}"
                )
        evidence_invocation = evidence.get("invocation")
        execution = evidence.get("execution")
        if (
            evidence.get("run_id") != run_id
            or not isinstance(evidence_invocation, dict)
            or evidence_invocation.get("run_id") != run_id
            or not isinstance(execution, dict)
            or execution.get("run_id") != run_id
        ):
            raise ResourceControllerError(
                f"claim-grade controller run identity mismatch: {run_id}"
            )

        case = expected.get("case")
        solver = expected.get("solver")
        input_root = manifest.get("input_root")
        input_hashes = manifest.get("inputs")
        configured_seconds = manifest.get("configured_solver_seconds")
        if (
            not isinstance(case, str)
            or not isinstance(solver, str)
            or not isinstance(input_root, str)
            or not isinstance(input_hashes, dict)
            or not isinstance(configured_seconds, (int, float))
            or isinstance(configured_seconds, bool)
        ):
            raise ResourceControllerError(
                f"claim-grade manifest cell is incomplete: {run_id}"
            )
        try:
            instance_path = (Path(input_root) / f"{case}.xml").resolve(strict=True)
        except OSError as exc:
            raise ResourceControllerError(
                f"claim-grade manifest input is unavailable: {run_id}"
            ) from exc
        if _sha256(instance_path) != input_hashes.get(case):
            raise ResourceControllerError(
                f"claim-grade manifest input hash drift: {run_id}"
            )
        run_dir = (runs_root / run_id).resolve()
        if run_dir.parent != runs_root:
            raise ResourceControllerError(
                f"claim-grade run directory escapes matrix root: {run_id}"
            )
        evidence_path = row.get("resource_evidence_path")
        if not isinstance(evidence_path, str) or Path(evidence_path).resolve() != (
            run_dir / "resource-evidence.json"
        ):
            raise ResourceControllerError(
                f"claim-grade evidence path mismatch: {run_id}"
            )
        capability_snapshot_sha256 = evidence.get("capability_snapshot_sha256")
        if not isinstance(capability_snapshot_sha256, str):
            raise ResourceControllerError(
                f"claim-grade capability snapshot binding is missing: {run_id}"
            )
        expected_invocation = _controller_invocation(
            controller_runtime,
            identity=expected,
            solver=solver,
            instance_path=instance_path,
            run_dir=run_dir,
            seed=_controller_seed_for_expected_run(manifest, expected),
            seconds=float(configured_seconds),
            capability_snapshot_sha256=capability_snapshot_sha256,
        )
        expected_invocation_payload = expected_invocation.to_canonical_dict()
        if (
            row.get("controller_invocation") != expected_invocation_payload
            or row.get("controller_invocation_sha256") != expected_invocation.sha256
            or evidence_invocation != expected_invocation_payload
            or evidence.get("invocation_sha256") != expected_invocation.sha256
        ):
            raise ResourceControllerError(
                f"claim-grade controller invocation mismatch: {run_id}"
            )
        expected_container_name = controller_runtime.controller.container_name(
            expected_invocation
        )
        if evidence.get("container_name") != expected_container_name:
            raise ResourceControllerError(
                f"claim-grade controller container identity mismatch: {run_id}"
            )
        if evidence_sha256 in seen_evidence_sha256:
            raise ResourceControllerError(
                f"duplicate claim-grade evidence across runs: {run_id}"
            )
        if expected_invocation.sha256 in seen_invocation_sha256:
            raise ResourceControllerError(
                f"duplicate claim-grade invocation across runs: {run_id}"
            )
        for field, seen in seen_controller_identities.items():
            value = evidence.get(field)
            if not isinstance(value, str) or not value:
                raise ResourceControllerError(
                    f"claim-grade controller identity is incomplete ({field}): {run_id}"
                )
            if value in seen:
                raise ResourceControllerError(
                    f"duplicate claim-grade controller run identity ({field}): {run_id}"
                )
            seen.add(value)
        seen_evidence_sha256.add(evidence_sha256)
        seen_invocation_sha256.add(expected_invocation.sha256)
        evidence_bindings.append(
            {"run_id": run_id, "resource_evidence_sha256": evidence_sha256}
        )
    controller.update(
        {
            "claim_grade_ready": True,
            "equal_wall_time_claim": True,
            "equal_memory_limit_claim": True,
            "claim_evidence_set_sha256": _json_sha256(evidence_bindings),
            "readiness_blocker": None,
        }
    )
    manifest["resource_policy"] = dict(CLAIM_GRADE_RESOURCE_POLICY)
    manifest["claim_boundary"] = (
        "Claim-grade same-host comparison under identical externally enforced wall "
        "time, CPU, memory, swap, PID, network, and read-only-filesystem controls. "
        "Per-run claim readiness is admitted only from authoritative direct evidence. "
        "Lemos MaxSAT remains an unseeded independent trial and is excluded from "
        "paired-seed claims."
    )


def _validate_controller_manifest_binding(binding: Any) -> dict[str, Any] | None:
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("Resume controller binding must be an object")
    if binding.get("mode") not in {
        CLAIM_GRADE_CONTROLLER_MODE,
        EVIDENCE_ONLY_CONTROLLER_MODE,
    }:
        raise ValueError("Resume controller mode is unsupported")
    mode = binding["mode"]
    claim_flags = (
        binding.get("claim_grade_ready"),
        binding.get("equal_wall_time_claim"),
        binding.get("equal_memory_limit_claim"),
    )
    if mode == EVIDENCE_ONLY_CONTROLLER_MODE:
        if claim_flags != (False, False, False):
            raise ValueError("Resume evidence-only controller claims must remain false")
    elif claim_flags not in {(False, False, False), (True, True, True)}:
        raise ValueError("Resume claim-grade controller readiness is inconsistent")
    if (
        mode == CLAIM_GRADE_CONTROLLER_MODE
        and binding.get("execution_admission_ready") is not True
    ):
        raise ValueError("Resume claim-grade controller admission is incomplete")
    evidence_set_sha256 = binding.get("claim_evidence_set_sha256")
    if claim_flags == (True, True, True):
        if not isinstance(evidence_set_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", evidence_set_sha256
        ):
            raise ValueError("Resume claim evidence set hash is malformed")
    elif evidence_set_sha256 is not None:
        raise ValueError("Resume pending controller has a claim evidence set hash")
    try:
        config_path = Path(str(binding.get("config_path", ""))).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Resume controller config is unavailable") from exc
    if _sha256(config_path) != binding.get("config_sha256"):
        raise ValueError("Resume controller config hash drift")
    controller_source = ROOT / "benchmarks/itc2019_resource_controller.py"
    if _sha256(controller_source) != binding.get("controller_source_sha256"):
        raise ValueError("Resume controller source hash drift")
    profile_payload = binding.get("profile")
    if not isinstance(profile_payload, dict):
        raise ValueError("Resume controller profile is missing")
    try:
        profile = ResourceProfile(**profile_payload)
    except (TypeError, ResourceControllerError) as exc:
        raise ValueError("Resume controller profile is malformed") from exc
    if profile.sha256 != binding.get("profile_sha256"):
        raise ValueError("Resume controller profile hash drift")
    capabilities = binding.get("capability_evidence")
    if not isinstance(capabilities, dict) or _json_sha256(
        _capability_identity_payload(capabilities)
    ) != binding.get("capability_sha256"):
        raise ValueError("Resume controller capability hash drift")
    preflight_snapshot = binding.get("preflight_capability_snapshot")
    if not isinstance(preflight_snapshot, dict) or _json_sha256(
        preflight_snapshot
    ) != binding.get("preflight_capability_snapshot_sha256"):
        raise ValueError("Resume controller preflight capability snapshot drift")
    if _capability_identity_payload(preflight_snapshot) != (
        _capability_identity_payload(capabilities)
    ):
        raise ValueError("Resume controller preflight capability identity drift")
    refresh = binding.get("capability_refresh")
    refresh_sha256 = binding.get("capability_refresh_sha256")
    if refresh is None:
        if mode == CLAIM_GRADE_CONTROLLER_MODE or refresh_sha256 is not None:
            raise ValueError("Resume controller capability refresh binding is missing")
    else:
        if not isinstance(refresh, dict) or _json_sha256(refresh) != refresh_sha256:
            raise ValueError("Resume controller capability refresh hash drift")
        argv = refresh.get("argv")
        executable_sha256 = refresh.get("executable_sha256")
        if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
            raise ValueError("Resume controller capability refresh argv is malformed")
        try:
            refresh_executable = Path(argv[0]).resolve(strict=True)
        except OSError as exc:
            raise ValueError(
                "Resume controller capability refresh executable is unavailable"
            ) from exc
        if _sha256(refresh_executable) != executable_sha256:
            raise ValueError(
                "Resume controller capability refresh executable hash drift"
            )
        bound_files = refresh.get("bound_files")
        if not isinstance(bound_files, list):
            raise ValueError("Resume controller capability refresh files are malformed")
        for item in bound_files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError(
                    "Resume controller capability refresh files are malformed"
                )
            try:
                bound_path = Path(item["path"]).resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    "Resume controller capability refresh bound file is unavailable"
                ) from exc
            if _sha256(bound_path) != item.get("sha256"):
                raise ValueError(
                    "Resume controller capability refresh bound file hash drift"
                )
    cgroup_probe = binding.get("post_exit_cgroup_probe")
    cgroup_probe_sha256 = binding.get("post_exit_cgroup_probe_sha256")
    if cgroup_probe is None:
        if mode == CLAIM_GRADE_CONTROLLER_MODE or cgroup_probe_sha256 is not None:
            raise ValueError("Resume post-exit cgroup probe binding is missing")
    else:
        if (
            not isinstance(cgroup_probe, dict)
            or _json_sha256(cgroup_probe) != cgroup_probe_sha256
        ):
            raise ValueError("Resume post-exit cgroup probe hash drift")
        probe_argv = cgroup_probe.get("argv")
        if (
            not isinstance(probe_argv, list)
            or not probe_argv
            or not isinstance(probe_argv[0], str)
        ):
            raise ValueError("Resume post-exit cgroup probe argv is malformed")
        try:
            probe_executable = Path(probe_argv[0]).resolve(strict=True)
        except OSError as exc:
            raise ValueError(
                "Resume post-exit cgroup probe executable is unavailable"
            ) from exc
        if _sha256(probe_executable) != cgroup_probe.get("executable_sha256"):
            raise ValueError("Resume post-exit cgroup probe executable hash drift")
        probe_files = cgroup_probe.get("bound_files")
        if not isinstance(probe_files, list):
            raise ValueError("Resume post-exit cgroup probe files are malformed")
        for item in probe_files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Resume post-exit cgroup probe files are malformed")
            try:
                probe_path = Path(item["path"]).resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    "Resume post-exit cgroup probe bound file is unavailable"
                ) from exc
            if _sha256(probe_path) != item.get("sha256"):
                raise ValueError("Resume post-exit cgroup probe bound file hash drift")
    try:
        supervisor_path = Path(str(binding.get("supervisor_path", ""))).resolve(
            strict=True
        )
    except OSError as exc:
        raise ValueError("Resume controller supervisor is unavailable") from exc
    if _sha256(supervisor_path) != binding.get("supervisor_sha256"):
        raise ValueError("Resume controller supervisor hash drift")
    solver_argv = binding.get("solver_argv")
    if not isinstance(solver_argv, dict) or _json_sha256(solver_argv) != binding.get(
        "solver_argv_sha256"
    ):
        raise ValueError("Resume controller argv hash drift")
    try:
        _validate_controller_argv_templates(
            solver_argv,
            list(solver_argv),
            require_seed_binding=mode == CLAIM_GRADE_CONTROLLER_MODE,
        )
    except ResourceControllerError as exc:
        raise ValueError(f"Resume controller argv binding is invalid: {exc}") from exc
    images = binding.get("solver_images")
    if not isinstance(images, dict):
        raise ValueError("Resume controller image binding is missing")
    external_solvers = [
        solver for solver in images if solver in EXTERNAL_COMPETITOR_SOLVERS
    ]
    provenance = binding.get("competitor_provenance")
    provenance_binding_sha256 = binding.get("competitor_provenance_binding_sha256")
    if external_solvers:
        if mode == CLAIM_GRADE_CONTROLLER_MODE and not isinstance(provenance, dict):
            raise ValueError("Resume competitor provenance binding is missing")
        if provenance is not None:
            if (
                not isinstance(provenance, dict)
                or provenance.get("binding_sha256") != provenance_binding_sha256
                or not isinstance(provenance.get("manifest_path"), str)
            ):
                raise ValueError("Resume competitor provenance binding is malformed")
            try:
                refreshed_provenance = verify_competitor_provenance(
                    Path(provenance["manifest_path"]),
                    expected_solvers=external_solvers,
                    selected_images={
                        solver: images[solver] for solver in external_solvers
                    },
                )
            except CompetitorProvenanceError as exc:
                raise ValueError(
                    f"Resume competitor provenance rejected: {exc}"
                ) from exc
            if not provenance_bindings_match_exactly(
                refreshed_provenance,
                provenance,
            ):
                raise ValueError("Resume competitor provenance binding drift")
    elif provenance is not None or provenance_binding_sha256 is not None:
        raise ValueError("Resume controller has unexpected competitor provenance")
    return binding


def _load_resume_manifest_before_controller(
    manifest_path: Path,
    *,
    execution_mode: str | None,
    controller_config: str,
) -> dict[str, Any]:
    """Validate persisted immutable state without constructing a controller."""

    try:
        manifest = _read_json_object(manifest_path, "resume manifest")
    except ResourceControllerError as exc:
        raise ValueError(str(exc)) from exc
    if manifest.get("schema") != MATRIX_SCHEMA:
        raise ValueError("Resume manifest schema mismatch")
    if execution_mode == CLAIM_GRADE_CONTROLLER_MODE:
        try:
            _validate_claim_grade_corpus_manifest(manifest, verify_files=True)
        except ResourceControllerError as exc:
            raise ValueError(str(exc)) from exc
    binding = _validate_controller_manifest_binding(manifest.get("resource_controller"))
    if execution_mode is None:
        if binding is not None:
            raise ValueError("Resume controller mode mismatch")
        return manifest
    if binding is None or binding.get("mode") != execution_mode:
        raise ValueError("Resume controller mode mismatch")
    try:
        current_config = Path(controller_config).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Resume controller config is unavailable") from exc
    if str(current_config) != binding.get("config_path"):
        raise ValueError("Resume controller config path mismatch")
    solvers = manifest.get("solvers")
    images = binding.get("solver_images")
    templates = binding.get("solver_argv")
    if (
        not isinstance(solvers, list)
        or any(not isinstance(solver, str) for solver in solvers)
        or len(solvers) != len(set(solvers))
        or any(solver not in DEFAULT_SOLVERS for solver in solvers)
        or not isinstance(images, dict)
        or not isinstance(templates, dict)
        or set(images) != set(solvers)
        or set(templates) != set(solvers)
    ):
        raise ValueError("Resume controller solver binding mismatch")
    return manifest


def _resume_records(
    root: Path,
    manifest: dict[str, Any],
    *,
    controller_runtime: ClaimGradeControllerRuntime | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    expected_specs = {
        str(item["run_id"]): dict(item)
        for item in list(manifest.get("expected_runs") or [])
    }
    if not expected_specs:
        raise ValueError("Resume manifest has no expected run identities")
    binding_sha256 = _resume_binding_sha256(manifest)
    validated_controller_binding = _validate_controller_manifest_binding(
        manifest.get("resource_controller")
    )
    if (
        isinstance(validated_controller_binding, dict)
        and validated_controller_binding.get("mode") == CLAIM_GRADE_CONTROLLER_MODE
    ):
        try:
            _validate_claim_grade_corpus_manifest(manifest, verify_files=True)
        except ResourceControllerError as exc:
            raise ValueError(f"Resume claim-grade corpus is invalid: {exc}") from exc
    seen: set[str] = set()
    runs_root = (root / "runs").resolve()
    for result_path in sorted((root / "runs").glob("*/result.json")):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("run_id"):
            raise ValueError(f"Invalid checkpoint record: {result_path}")
        state_path = result_path.parent / "state.json"
        if not state_path.is_file():
            raise ValueError(
                f"Checkpoint state is unavailable: {result_path.parent.name}"
            )
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Checkpoint state is unreadable: {result_path.parent.name}"
            ) from exc
        if not isinstance(state, dict) or state.get("schema") != (
            "planora.itc2019.run-state.v1"
        ):
            raise ValueError(
                f"Checkpoint state schema mismatch: {result_path.parent.name}"
            )
        if state.get("status") != "complete":
            raise ValueError(
                f"Checkpoint state is not complete: {result_path.parent.name}"
            )
        result_sha256 = _sha256(result_path)
        if state.get("initial_result_sha256") != result_sha256:
            raise ValueError(
                f"Checkpoint persisted result hash drift: {result_path.parent.name}"
            )
        run_id = str(payload["run_id"])
        if run_id in seen or run_id not in expected_specs:
            raise ValueError(f"Unexpected or duplicate checkpoint run_id: {run_id}")
        if result_path.parent.name != run_id:
            raise ValueError(f"Checkpoint directory does not match run_id: {run_id}")
        expected = expected_specs[run_id]
        for field in (
            "case",
            "solver",
            "seed",
            "effective_seed",
            "seed_control",
            "seed_pairing_group",
            "repetition",
            "unseeded_trial",
        ):
            if payload.get(field) != expected.get(field):
                raise ValueError(f"Checkpoint identity mismatch ({field}): {run_id}")
        immutable = {
            "configured_solver_seconds": float(manifest["configured_solver_seconds"]),
            "configured_workers": int(manifest["workers"]),
            "cpu_affinity": int(manifest["cpu_affinity"]),
            "resume_binding_sha256": binding_sha256,
            "input_sha256": manifest["inputs"][str(payload["case"])],
        }
        if validated_controller_binding is None:
            immutable.update(
                {
                    "equal_wall_time_claim": False,
                    "equal_memory_limit_claim": False,
                    "comparison_scope": QUALITY_ONLY_RESOURCE_POLICY[
                        "comparison_scope"
                    ],
                }
            )
        for field, value in immutable.items():
            if payload.get(field) != value:
                raise ValueError(f"Checkpoint manifest mismatch ({field}): {run_id}")
        run_dir = result_path.parent.resolve()
        if run_dir.parent != runs_root:
            raise ValueError(f"Checkpoint is outside the controlled run root: {run_id}")
        instance_path = (
            Path(manifest["input_root"]) / f"{payload['case']}.xml"
        ).resolve()
        if (
            not instance_path.is_file()
            or _sha256(instance_path) != manifest["inputs"][str(payload["case"])]
        ):
            raise ValueError(f"Checkpoint manifest-bound input hash drift: {run_id}")
        controller_binding = validated_controller_binding
        controller_mode = controller_binding is not None
        expected_invocation = None
        controller_evidence_payload = None
        if controller_mode:
            solver = str(payload["solver"])
            templates = controller_binding.get("solver_argv")
            images = controller_binding.get("solver_images")
            if not isinstance(templates, dict) or not isinstance(images, dict):
                raise ValueError("Resume controller binding is incomplete")
            template = templates.get(solver)
            image = images.get(solver)
            if not isinstance(template, list) or not isinstance(image, str):
                raise ValueError(
                    f"Resume controller solver binding is missing: {run_id}"
                )
            persisted_invocation = payload.get("controller_invocation")
            snapshot_sha256 = (
                persisted_invocation.get("capability_snapshot_sha256")
                if isinstance(persisted_invocation, dict)
                else None
            )
            expected_invocation = SolverInvocation(
                run_id=run_id,
                solver=solver,
                image=image,
                argv=_render_controller_argv(
                    tuple(template),
                    seed=int(expected.get("effective_seed") or manifest["seeds"][0]),
                    seconds=float(manifest["configured_solver_seconds"]),
                ),
                host_run_directory=str(run_dir),
                input_mounts=((str(instance_path), "/inputs/instance.xml"),),
                binary_mounts=(
                    (
                        str(Path(controller_binding["supervisor_path"]).resolve()),
                        "/opt/planora/itc2019-container-supervisor",
                    ),
                ),
                artifact_relative_path="solution.xml",
                capability_snapshot_sha256=snapshot_sha256,
            )
            command = list(expected_invocation.argv)
            expected_cwd = expected_invocation.container_run_directory
            expected_basis = CONTROLLER_BUDGET_BASIS
        else:
            command, expected_cwd, _supervisor, expected_basis = _command_for(
                str(payload["solver"]),
                instance_path=instance_path,
                run_dir=run_dir,
                output_path=run_dir / "solution.xml",
                seed=int(expected.get("effective_seed") or manifest["seeds"][0]),
                seconds=float(manifest["configured_solver_seconds"]),
                cpu=int(manifest["cpu_affinity"]),
                gashi=Path(manifest["tool_paths"]["gashi"]),
                cps_root=Path(manifest["tool_paths"]["cpsolver_root"]),
                maxsat=Path(manifest["tool_paths"]["maxsat"]),
                write_config=False,
            )
        if payload.get("command") != command or payload.get(
            "command_sha256"
        ) != _json_sha256(command):
            raise ValueError(f"Checkpoint command mismatch: {run_id}")
        if payload.get("working_directory") != str(expected_cwd):
            raise ValueError(f"Checkpoint working-directory mismatch: {run_id}")
        if payload.get("budget_basis") != expected_basis:
            raise ValueError(f"Checkpoint budget-basis mismatch: {run_id}")
        if payload.get("input_path") != str(instance_path):
            raise ValueError(f"Checkpoint input-path mismatch: {run_id}")
        expected_config_sha256 = None
        if not controller_mode and payload["solver"] == "unitime-cpsolver":
            expected_config_sha256 = hashlib.sha256(
                _render_cpsolver_config(
                    source=Path(manifest["tool_paths"]["cpsolver_root"])
                    / "configuration/default.cfg",
                    seconds=float(manifest["configured_solver_seconds"]),
                    seed=int(expected["effective_seed"]),
                ).encode("utf-8")
            ).hexdigest()
            config_path = run_dir / "cpsolver.cfg"
            if (
                not config_path.is_file()
                or _sha256(config_path) != expected_config_sha256
            ):
                raise ValueError(f"Checkpoint generated configuration drift: {run_id}")
        if payload.get("run_configuration_sha256") != expected_config_sha256:
            raise ValueError(f"Checkpoint configuration hash mismatch: {run_id}")
        if controller_mode:
            if payload.get("execution_mode") != controller_binding.get("mode"):
                raise ValueError(f"Checkpoint controller mode mismatch: {run_id}")
            if (
                expected_invocation is None
                or payload.get("controller_invocation")
                != expected_invocation.to_canonical_dict()
            ):
                raise ValueError(f"Checkpoint controller invocation mismatch: {run_id}")
            if (
                payload.get("controller_invocation_sha256")
                != expected_invocation.sha256
            ):
                raise ValueError(
                    f"Checkpoint controller invocation hash mismatch: {run_id}"
                )
            evidence_path_raw = payload.get("resource_evidence_path")
            evidence_hash = payload.get("resource_evidence_sha256")
            evidence_file_hash = payload.get("resource_evidence_file_sha256")
            if (
                not isinstance(evidence_path_raw, str)
                or not isinstance(evidence_hash, str)
                or not isinstance(evidence_file_hash, str)
            ):
                raise ValueError(f"Checkpoint controller evidence is missing: {run_id}")
            evidence_path = Path(evidence_path_raw).resolve(strict=True)
            if evidence_path != run_dir / "resource-evidence.json":
                raise ValueError(
                    f"Checkpoint controller evidence path mismatch: {run_id}"
                )
            if _sha256(evidence_path) != evidence_file_hash:
                raise ValueError(
                    f"Checkpoint controller evidence file hash drift: {run_id}"
                )
            evidence_payload = _read_json_object(
                evidence_path, "checkpoint controller evidence"
            )
            if payload.get("resource_evidence") != evidence_payload:
                raise ValueError(
                    f"Checkpoint inline resource evidence mismatch: {run_id}"
                )
            if resource_evidence_sha256(evidence_payload) != evidence_hash:
                raise ValueError(f"Checkpoint controller evidence hash drift: {run_id}")
            direct_evidence = (
                controller_binding.get("mode") == CLAIM_GRADE_CONTROLLER_MODE
                and evidence_payload.get("schema") == RESOURCE_EVIDENCE_SCHEMA
                and evidence_payload.get("claim_grade_ready") is True
            )
            if (
                controller_binding.get("mode") == CLAIM_GRADE_CONTROLLER_MODE
                and not direct_evidence
            ):
                raise ValueError(
                    f"Checkpoint claim-grade evidence is incomplete: {run_id}"
                )
            if direct_evidence:
                if controller_runtime is None:
                    raise ValueError(
                        "Checkpoint claim-grade evidence requires live parser provenance"
                    )
                raw_path_value = payload.get("raw_resource_evidence_path")
                raw_hash = payload.get("raw_resource_evidence_sha256")
                raw_file_hash = payload.get("raw_resource_evidence_file_sha256")
                if not all(
                    isinstance(value, str)
                    for value in (raw_path_value, raw_hash, raw_file_hash)
                ):
                    raise ValueError(
                        f"Checkpoint raw controller evidence is missing: {run_id}"
                    )
                raw_path = Path(raw_path_value).resolve(strict=True)
                if raw_path != run_dir / "resource-evidence-raw.json":
                    raise ValueError(
                        f"Checkpoint raw controller evidence path mismatch: {run_id}"
                    )
                if _sha256(raw_path) != raw_file_hash:
                    raise ValueError(
                        f"Checkpoint raw controller evidence file hash drift: {run_id}"
                    )
                raw_evidence = _read_json_object(
                    raw_path, "checkpoint raw controller evidence"
                )
                if payload.get("raw_resource_evidence") != raw_evidence:
                    raise ValueError(
                        f"Checkpoint inline raw controller evidence mismatch: {run_id}"
                    )
                if _json_sha256(raw_evidence) != raw_hash:
                    raise ValueError(
                        f"Checkpoint raw controller evidence hash drift: {run_id}"
                    )
                if (
                    raw_evidence.get("schema") != RAW_RESOURCE_EVIDENCE_SCHEMA
                    or raw_evidence.get("invocation_sha256")
                    != expected_invocation.sha256
                ):
                    raise ValueError(
                        f"Checkpoint raw controller evidence binding mismatch: {run_id}"
                    )
                try:
                    reparsed = controller_runtime.controller.parse_evidence(
                        expected_invocation,
                        inspect=raw_evidence.get("inspect"),
                        execution=raw_evidence.get("execution"),
                        cgroup=raw_evidence.get("cgroup"),
                        supervisor=raw_evidence.get("supervisor"),
                        capability_snapshot=raw_evidence.get("capability_snapshot"),
                        cleanup_outcomes=raw_evidence.get("cleanup_outcomes", ()),
                    ).to_canonical_dict()
                except (ResourceControllerError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Checkpoint authoritative evidence reparse failed: {run_id}"
                    ) from exc
                if reparsed != evidence_payload:
                    raise ValueError(
                        f"Checkpoint normalized evidence differs from raw parse: {run_id}"
                    )
                if not controller_runtime.controller.authorizes_claim_grade_evidence(
                    evidence_payload
                ):
                    raise ValueError(
                        f"Checkpoint parser provenance was not retained: {run_id}"
                    )
            evidence_binding = {
                "schema": (
                    RESOURCE_EVIDENCE_SCHEMA
                    if direct_evidence
                    else DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA
                ),
                "run_id": run_id,
                "profile_sha256": controller_binding.get("profile_sha256"),
                "capability_sha256": controller_binding.get("capability_sha256"),
                "supervisor_sha256": controller_binding.get("supervisor_sha256"),
                "image_reference": expected_invocation.image,
                "invocation_sha256": expected_invocation.sha256,
                "claim_grade_ready": direct_evidence,
            }
            if not direct_evidence:
                evidence_binding.update(
                    {
                        "mode": EVIDENCE_ONLY_CONTROLLER_MODE,
                        "controller_version": controller_binding.get(
                            "controller_version"
                        ),
                        "controller_source_sha256": controller_binding.get(
                            "controller_source_sha256"
                        ),
                        "config_sha256": controller_binding.get("config_sha256"),
                    }
                )
            for field, value in evidence_binding.items():
                if evidence_payload.get(field) != value:
                    raise ValueError(
                        f"Checkpoint controller evidence mismatch ({field}): {run_id}"
                    )
            capability_snapshot = evidence_payload.get("capability_snapshot")
            if (
                not isinstance(capability_snapshot, dict)
                or _json_sha256(capability_snapshot)
                != expected_invocation.capability_snapshot_sha256
            ):
                raise ValueError(
                    f"Checkpoint controller capability snapshot mismatch: {run_id}"
                )
            baseline = controller_binding.get("capability_evidence")
            if not isinstance(baseline, dict) or {
                key: value
                for key, value in capability_snapshot.items()
                if key != "captured_at_unix_ns"
            } != {
                key: value
                for key, value in baseline.items()
                if key != "captured_at_unix_ns"
            }:
                raise ValueError(
                    f"Checkpoint controller capability contract drift: {run_id}"
                )
            if (
                evidence_payload.get("invocation")
                != expected_invocation.to_canonical_dict()
            ):
                raise ValueError(
                    f"Checkpoint controller evidence invocation mismatch: {run_id}"
                )
            execution_evidence = evidence_payload.get("execution")
            cleanup_evidence = evidence_payload.get(
                "cleanup_outcomes" if direct_evidence else "cleanup"
            )
            if (
                not isinstance(execution_evidence, dict)
                or execution_evidence.get("run_id") != run_id
                or execution_evidence.get("cleanup_complete") is not True
                or execution_evidence.get("residual_processes") != 0
            ):
                raise ValueError(
                    f"Checkpoint controller execution evidence is incomplete: {run_id}"
                )
            if not isinstance(cleanup_evidence, list) or not any(
                isinstance(item, dict) and item.get("absence_verified") is True
                for item in cleanup_evidence
            ):
                raise ValueError(
                    f"Checkpoint controller cleanup evidence is incomplete: {run_id}"
                )
            if direct_evidence:
                profile = controller_binding["profile"]
                sampled_monotonic_ns = evidence_payload.get(
                    "post_exit_cgroup_sampled_monotonic_ns"
                )
                host_finished_monotonic_ns = execution_evidence.get(
                    "host_finished_monotonic_ns"
                )
                if (
                    type(sampled_monotonic_ns) is not int
                    or type(host_finished_monotonic_ns) is not int
                    or sampled_monotonic_ns < host_finished_monotonic_ns
                ):
                    raise ValueError(
                        "Checkpoint cgroup evidence was not sampled after "
                        f"container exit: {run_id}"
                    )
                expected_direct = {
                    "effective_memory_max": profile["memory_bytes"],
                    "effective_memory_swap_max": (
                        profile["memory_swap_bytes"] - profile["memory_bytes"]
                    ),
                    "effective_cpu_max": (
                        f"{profile['cpu_quota_us']} {profile['cpu_period_us']}"
                    ),
                    "effective_cpuset_cpus": profile["cpuset_cpus"],
                    "effective_pids_max": profile["pids_limit"],
                    "deadline_exceeded": False,
                    "cleanup_complete": True,
                    "residual_processes": 0,
                }
                for field, value in expected_direct.items():
                    if evidence_payload.get(field) != value:
                        raise ValueError(
                            f"Checkpoint direct resource evidence mismatch "
                            f"({field}): {run_id}"
                        )
                if (
                    payload.get("equal_wall_time_claim") is not True
                    or payload.get("equal_memory_limit_claim") is not True
                    or payload.get("comparison_scope")
                    != CLAIM_GRADE_RESOURCE_POLICY["comparison_scope"]
                ):
                    raise ValueError(
                        f"Checkpoint direct resource claims are incomplete: {run_id}"
                    )
            elif (
                payload.get("equal_wall_time_claim") is not False
                or payload.get("equal_memory_limit_claim") is not False
                or payload.get("comparison_scope")
                != QUALITY_ONLY_RESOURCE_POLICY["comparison_scope"]
            ):
                raise ValueError(
                    f"Checkpoint descriptive resource claims are invalid: {run_id}"
                )
            controller_evidence_payload = evidence_payload
        output_path_raw = payload.get("output_path")
        output_relative_path = payload.get("output_relative_path")
        output_hash = payload.get("output_sha256")
        artifact_binding_sha256 = payload.get("artifact_binding_sha256")
        if bool(output_path_raw) != bool(output_hash):
            raise ValueError(f"Checkpoint output metadata is incomplete: {run_id}")
        if output_path_raw:
            output_path = Path(str(output_path_raw)).resolve(strict=True)
            try:
                expected_metadata = _output_artifact_metadata(
                    root, expected, output_path
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(f"Checkpoint output path mismatch: {run_id}") from exc
            if expected_metadata["output_path"] != str(output_path):
                raise ValueError(f"Checkpoint output path mismatch: {run_id}")
            if expected_metadata["output_sha256"] != output_hash:
                raise ValueError(f"Checkpoint output hash drift: {run_id}")
            if expected_metadata["output_relative_path"] != output_relative_path:
                raise ValueError(f"Checkpoint output relative path mismatch: {run_id}")
            if expected_metadata["artifact_binding_sha256"] != artifact_binding_sha256:
                raise ValueError(f"Checkpoint artifact binding mismatch: {run_id}")
        else:
            if output_relative_path is not None or artifact_binding_sha256 is not None:
                raise ValueError(
                    f"Checkpoint absent-output metadata mismatch: {run_id}"
                )
            if _find_output(str(payload["solver"]), run_dir, run_dir / "solution.xml"):
                raise ValueError(f"Checkpoint artifact absence drift: {run_id}")
        if controller_mode and (
            controller_evidence_payload is None
            or controller_evidence_payload.get("artifact_sha256") != output_hash
        ):
            raise ValueError(
                f"Checkpoint controller artifact binding mismatch: {run_id}"
            )
        recomputed_validation = _no_artifact_validation(expected)
        recomputed_parse_error = None
        if output_path_raw:
            try:
                recomputed_validation = _score(instance_path, output_path)
            except Exception as exc:  # persisted solver output remains untrusted
                recomputed_parse_error = f"{type(exc).__name__}: {exc}"
        if (
            payload.get("independent_validation") != recomputed_validation
            or payload.get("parse_error") != recomputed_parse_error
        ):
            raise ValueError(f"Checkpoint independent validation mismatch: {run_id}")
        expected_state = {
            "schema": "planora.itc2019.run-state.v1",
            **expected,
            "status": "complete",
            "run_directory": str(run_dir),
            "input_path": str(instance_path),
            "input_sha256": manifest["inputs"][str(payload["case"])],
            "configured_solver_seconds": float(manifest["configured_solver_seconds"]),
            "configured_workers": int(manifest["workers"]),
            "cpu_affinity": int(manifest["cpu_affinity"]),
            "resume_binding_sha256": binding_sha256,
            "orphan_lineage": payload.get("orphan_lineage"),
            "initial_result_sha256": result_sha256,
        }
        if controller_mode:
            expected_state.update(
                {
                    "execution_mode": controller_binding["mode"],
                    "controller_invocation": expected_invocation.to_canonical_dict(),
                    "controller_invocation_sha256": expected_invocation.sha256,
                }
            )
        else:
            expected_state.update(
                {
                    "command": command,
                    "command_sha256": _json_sha256(command),
                    "run_configuration_sha256": expected_config_sha256,
                }
            )
        if state != expected_state:
            raise ValueError(f"Checkpoint completed state mismatch: {run_id}")
        seen.add(run_id)
        records.append(payload)
    if (
        isinstance(validated_controller_binding, dict)
        and validated_controller_binding.get("claim_grade_ready") is True
    ):
        evidence_bindings = [
            {
                "run_id": str(row["run_id"]),
                "resource_evidence_sha256": str(row["resource_evidence_sha256"]),
            }
            for row in sorted(records, key=lambda item: str(item["run_id"]))
        ]
        if len(records) != len(expected_specs) or _json_sha256(
            evidence_bindings
        ) != validated_controller_binding.get("claim_evidence_set_sha256"):
            raise ValueError("Checkpoint claim evidence set hash mismatch")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Controlled ITC-2019 comparison against pinned open-source finalists."
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--instance", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument(
        "--instance-set",
        choices=["public", "competition"],
        default="public",
    )
    parser.add_argument("--instances", default="")
    parser.add_argument("--solvers", default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--seeds", default="17,23,31")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--output-root", default="")
    parser.add_argument("--gashi", default=str(DEFAULT_GASHI))
    parser.add_argument("--cpsolver-root", default=str(DEFAULT_CPS_ROOT))
    parser.add_argument("--maxsat", default=str(DEFAULT_MAXSAT))
    parser.add_argument("--maxsat-locale", default=str(DEFAULT_MAXSAT_LOCALE))
    parser.add_argument(
        "--claim-grade-controller-config",
        default="",
        metavar="PATH",
        help=(
            "explicitly opt in to the claim-grade Docker resource-controller "
            "preflight; legacy runs remain descriptive when this is omitted"
        ),
    )
    parser.add_argument(
        "--evidence-only-controller-config",
        default="",
        metavar="PATH",
        help=(
            "explicitly run the Docker resource controller for descriptive "
            "evidence gathering; this mode never enables equal-resource claims"
        ),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.worker:
        if not args.instance or not args.output:
            parser.error("--worker requires --instance and --output")
        return _planora_worker(args)

    selected_cases = (
        SUPPORTED_TEST_CASES if args.instance_set == "public" else COMPETITION_CASES
    )
    cases = (
        [value.strip() for value in args.instances.split(",") if value.strip()]
        if args.instances
        else list(selected_cases)
    )
    solvers = [value.strip() for value in args.solvers.split(",") if value.strip()]
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    if not cases or not solvers or not seeds:
        parser.error("cases, solvers, and seeds must each contain at least one value")
    if len(cases) != len(set(cases)):
        parser.error("instance selection contains duplicates")
    if len(solvers) != len(set(solvers)):
        parser.error("solver selection contains duplicates")
    if len(seeds) != len(set(seeds)):
        parser.error("seed selection contains duplicates")
    unknown = sorted(set(solvers) - set(DEFAULT_SOLVERS))
    if unknown:
        parser.error(f"Unknown solvers: {', '.join(unknown)}")
    if args.time_limit <= 0 or args.repetitions <= 0:
        parser.error("time limit and repetitions must be positive")
    if args.claim_grade_controller_config and args.evidence_only_controller_config:
        parser.error(
            "--claim-grade-controller-config and --evidence-only-controller-config "
            "are mutually exclusive"
        )
    controller_config = (
        args.claim_grade_controller_config or args.evidence_only_controller_config
    )
    execution_mode: str | None = None
    if controller_config:
        execution_mode = (
            CLAIM_GRADE_CONTROLLER_MODE
            if args.claim_grade_controller_config
            else EVIDENCE_ONLY_CONTROLLER_MODE
        )
    input_root = Path(args.input_root).resolve()
    missing = [case for case in cases if not (input_root / f"{case}.xml").is_file()]
    if missing:
        parser.error(f"Missing input instances: {', '.join(missing)}")
    input_hashes = {case: _sha256(input_root / f"{case}.xml") for case in cases}
    if execution_mode == CLAIM_GRADE_CONTROLLER_MODE:
        try:
            if args.instance_set != "competition":
                raise ResourceControllerError(
                    "claim-grade controller requires --instance-set competition"
                )
            _validate_claim_grade_competition_corpus(cases, input_hashes)
        except ResourceControllerError as exc:
            parser.error(f"claim-grade corpus preflight failed: {exc}")
    elif args.instance_set == "competition":
        corrected_input_errors = _corrected_input_hash_errors(input_root, cases)
        if corrected_input_errors:
            parser.error(
                "Withdrawn ITC-2019 input detected; use the organizer-corrected file: "
                + "; ".join(corrected_input_errors)
            )
    corpus_admission = _corpus_admission_binding(
        cases,
        input_hashes,
        execution_mode=execution_mode,
    )

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    root = (
        Path(args.output_root).resolve()
        if args.output_root
        else ROOT / "output" / f"itc2019-open-source-controlled-{timestamp}"
    )
    manifest_path = root / "manifest.json"
    existing_manifest: dict[str, Any] | None = None
    if args.resume:
        if not manifest_path.is_file():
            parser.error(
                "resume manifest preflight failed: resume manifest is unavailable"
            )
        try:
            existing_manifest = _load_resume_manifest_before_controller(
                manifest_path,
                execution_mode=execution_mode,
                controller_config=controller_config,
            )
        except ValueError as exc:
            parser.error(f"resume manifest preflight failed: {exc}")

    expected_runs = _expected_run_specs(cases, solvers, seeds, int(args.repetitions))
    tool_paths = {
        "gashi": str(Path(args.gashi).resolve()),
        "cpsolver_root": str(Path(args.cpsolver_root).resolve()),
        "maxsat": str(Path(args.maxsat).resolve()),
        "maxsat_locale": str(Path(args.maxsat_locale).resolve()),
    }
    host_binding: dict[str, Any] | None = None
    tools_binding: dict[str, Any] | None = None
    harness_sha256 = _sha256(Path(__file__).resolve())
    validator_helper_sha256 = _sha256(
        ROOT / "scripts/validate_itc2019_official_browser.cjs"
    )
    if existing_manifest is not None:
        host_binding = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "cpu_model": _cpu_model(),
            "memory_total_kib": _memory_total_kib(),
            "allowed_cpu_affinity": sorted(os.sched_getaffinity(0)),
        }
        tools_binding = _tool_provenance(args)
        pre_controller_manifest = {
            "schema": MATRIX_SCHEMA,
            "cases": cases,
            "instance_set": str(args.instance_set),
            "solvers": solvers,
            "seeds": seeds,
            "repetitions": int(args.repetitions),
            "configured_solver_seconds": float(args.time_limit),
            "workers": 1,
            "cpu_affinity": int(args.cpu),
            "input_root": str(input_root),
            "tool_paths": tool_paths,
            "tools": tools_binding,
            "expected_runs": expected_runs,
            "resource_policy": dict(QUALITY_ONLY_RESOURCE_POLICY),
            "harness_sha256": harness_sha256,
            "official_validator_helper_sha256": validator_helper_sha256,
            "host": host_binding,
            "inputs": input_hashes,
            "corpus_admission": corpus_admission,
        }
        normalized_existing = _resume_binding_payload(existing_manifest)
        for field, current_value in pre_controller_manifest.items():
            existing_value = normalized_existing.get(field)
            if existing_value != current_value:
                parser.error(
                    "resume manifest preflight failed: "
                    f"Resume manifest mismatch: {field}"
                )

    controller_runtime: ClaimGradeControllerRuntime | None = None
    if controller_config:
        try:
            controller_runtime = _claim_grade_controller_preflight(
                Path(controller_config),
                solvers=solvers,
                seconds=float(args.time_limit),
                cpu=int(args.cpu),
                execution_mode=execution_mode,
            )
        except (OSError, ResourceControllerError) as exc:
            parser.error(f"resource controller preflight failed: {exc}")
        if (
            execution_mode == CLAIM_GRADE_CONTROLLER_MODE
            and controller_runtime.manifest_binding["execution_admission_ready"]
            is not True
        ):
            parser.error(
                "claim-grade controller preflight failed closed: "
                + str(controller_runtime.manifest_binding["readiness_blocker"])
            )
    root.mkdir(parents=True, exist_ok=bool(args.resume))
    if host_binding is None:
        host_binding = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "cpu_model": _cpu_model(),
            "memory_total_kib": _memory_total_kib(),
            "allowed_cpu_affinity": sorted(os.sched_getaffinity(0)),
        }
    if tools_binding is None:
        tools_binding = _tool_provenance(args)
    manifest = {
        "schema": MATRIX_SCHEMA,
        "created_utc": timestamp,
        "cases": cases,
        "instance_set": str(args.instance_set),
        "solvers": solvers,
        "seeds": seeds,
        "repetitions": int(args.repetitions),
        "configured_solver_seconds": float(args.time_limit),
        "workers": 1,
        "cpu_affinity": int(args.cpu),
        "input_root": str(input_root),
        "tool_paths": tool_paths,
        "host": host_binding,
        "inputs": input_hashes,
        "corpus_admission": corpus_admission,
        "tools": tools_binding,
        "expected_runs": expected_runs,
        "resource_policy": dict(QUALITY_ONLY_RESOURCE_POLICY),
        "resource_controller": (
            dict(controller_runtime.manifest_binding)
            if controller_runtime is not None
            else None
        ),
        "harness_sha256": harness_sha256,
        "official_validator_helper_sha256": validator_helper_sha256,
        "claim_boundary": (
            "Controlled same-host open-source quality-only comparison under nominal "
            "solver budgets. The upstream tools expose different timing and memory "
            "semantics, so equal-wall, equal-memory, runtime, and speed claims are prohibited. "
            "Lemos MaxSAT trials are unseeded and are not paired to seeded solvers. Scores receive "
            "a separate local validation pass; official website agreement remains "
            "pending until explicitly recorded for every output."
        ),
    }
    if existing_manifest is not None:
        for field in (
            "schema",
            "cases",
            "instance_set",
            "solvers",
            "seeds",
            "repetitions",
            "configured_solver_seconds",
            "workers",
            "cpu_affinity",
            "input_root",
            "tool_paths",
            "tools",
            "expected_runs",
            "resource_policy",
            "resource_controller",
            "harness_sha256",
            "official_validator_helper_sha256",
            "host",
            "inputs",
            "corpus_admission",
        ):
            existing_value = existing_manifest.get(field)
            current_value = manifest.get(field)
            if field == "resource_controller":
                existing_value = _resume_binding_payload(
                    {"resource_controller": existing_value}
                )["resource_controller"]
                current_value = _resume_binding_payload(
                    {"resource_controller": current_value}
                )["resource_controller"]
            elif field == "resource_policy" and isinstance(
                existing_manifest.get("resource_controller"), dict
            ):
                existing_value = _resume_binding_payload(
                    {
                        "resource_controller": existing_manifest.get(
                            "resource_controller"
                        ),
                        "resource_policy": existing_value,
                    }
                )["resource_policy"]
                current_value = _resume_binding_payload(
                    {
                        "resource_controller": manifest.get("resource_controller"),
                        "resource_policy": current_value,
                    }
                )["resource_policy"]
            if existing_value != current_value:
                raise ValueError(f"Resume manifest mismatch: {field}")
        manifest = existing_manifest
    else:
        _write_json_atomic(manifest_path, manifest)
    binding_sha256 = _resume_binding_sha256(manifest)
    records = (
        _resume_records(root, manifest, controller_runtime=controller_runtime)
        if args.resume
        else []
    )
    prior_report = {}
    if args.resume and (root / "report.json").is_file():
        prior_report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    completed_run_ids = {str(row["run_id"]) for row in records}
    for case_index, case in enumerate(cases):
        instance_path = input_root / f"{case}.xml"
        for seed_index, seed in enumerate(seeds):
            for repetition in range(1, args.repetitions + 1):
                offset = (case_index + seed_index + repetition - 1) % len(solvers)
                execution_solvers = solvers[offset:] + solvers[:offset]
                for solver in execution_solvers:
                    identity = _run_identity(
                        case,
                        solver,
                        seed,
                        repetition,
                        seeds=seeds,
                        repetitions=int(args.repetitions),
                    )
                    run_id = str(identity["run_id"])
                    if run_id in completed_run_ids:
                        print(json.dumps({"run": run_id, "resumed": True}), flush=True)
                        continue
                    if controller_runtime is None:
                        row = _run_one(
                            solver,
                            identity=identity,
                            case=case,
                            instance_path=instance_path,
                            root=root,
                            seed=seed,
                            repetition=repetition,
                            seconds=float(args.time_limit),
                            cpu=int(args.cpu),
                            gashi=Path(args.gashi).resolve(),
                            cps_root=Path(args.cpsolver_root).resolve(),
                            maxsat=Path(args.maxsat).resolve(),
                            maxsat_locale=Path(args.maxsat_locale).resolve(),
                            resume_binding_sha256=binding_sha256,
                        )
                    else:
                        row = _run_one_controller(
                            controller_runtime,
                            solver,
                            identity=identity,
                            case=case,
                            instance_path=instance_path,
                            root=root,
                            seed=seed,
                            repetition=repetition,
                            seconds=float(args.time_limit),
                            cpu=int(args.cpu),
                            resume_binding_sha256=binding_sha256,
                        )
                    records.append(row)
                    completed_run_ids.add(run_id)
                    _write_report(
                        root,
                        manifest,
                        records,
                        official_validation=prior_report.get("official_validation"),
                    )
                    print(
                        json.dumps(
                            {
                                "run": row["run_id"],
                                "valid": (row.get("independent_validation") or {}).get(
                                    "feasible"
                                ),
                                "score": (
                                    (row.get("independent_validation") or {}).get(
                                        "objective"
                                    )
                                    or {}
                                ).get("total"),
                                "wall": row["process_wall_seconds"],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    _assert_complete_record_set(records, manifest)
    _finalize_controller_claims(
        manifest, records, root=root, controller_runtime=controller_runtime
    )
    _write_json_atomic(manifest_path, manifest)
    _write_report(
        root,
        manifest,
        records,
        official_validation=prior_report.get("official_validation"),
    )
    print(f"report={root / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
