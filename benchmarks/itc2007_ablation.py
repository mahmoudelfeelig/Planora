from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import sys
from typing import Any, Callable, Mapping, Sequence

from benchmarks.itc2007 import parse_itc2007_ctt, parse_itc2007_validator_output
from benchmarks.itc2007_harness import (
    BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES,
    SOLVER_CPSOLVER,
    SOLVER_PLANORA,
    planora_source_snapshot,
    run_cpsolver_case,
    run_planora_case,
    sha256_file,
    sha256_tree,
)
from scripts.analyze_experiments import bootstrap_mean_ci, exact_sign_test_pvalue


SCHEMA_VERSION = "planora.itc2007-factorial-ablation.v1"
INDEX_SCHEMA_VERSION = "planora.itc2007-factorial-ablation-index.v1"
COMPONENT_NAMES = (
    "room_capacity",
    "minimum_working_days",
    "curriculum_compactness",
    "room_stability",
    "total",
)
EXECUTION_SOURCE_ROOTS = ("benchmarks", "core", "services", "utils", "scripts")
PUBLICATION_MINIMUM_EFFECTIVE_INSTANCES = 30
PUBLICATION_MINIMUM_SEEDS = 2
OFFICIAL_ITC2007_VALIDATOR_PINS: dict[str, dict[str, str]] = {
    "6b991efa2195ed59f9e514532d9add65b4790791bd6de054ce6f5cbdc19546b3": {
        "implementation": "official_itc2007_cpp_validator",
        "provenance": (
            "Repository-pinned binary identity used by the checked ITC-2007 and "
            "CB-CTT compatibility evidence."
        ),
    }
}


class SourceSnapshotDrift(RuntimeError):
    """Raised when benchmark-relevant Planora source changes during a matrix."""


class BenchmarkInputDrift(RuntimeError):
    """Raised when an instance or validator executable changes during a matrix."""


class ArtifactIntegrityError(RuntimeError):
    """Raised when a frozen matrix artifact does not match its index."""


@dataclass(frozen=True)
class AblationCondition:
    condition_id: str
    fixed_time_room_strategy: str
    compact_adaptive_arms: bool
    matched_finalization_reserve: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "planora_strategy": "research_adaptive",
            "fixed_time_room_dive": True,
        }


CONDITIONS: tuple[AblationCondition, ...] = (
    AblationCondition("control_compact_off", "control", False),
    AblationCondition("control_compact_on", "control", True),
    AblationCondition("oracle_only_compact_off", "oracle_only", False),
    AblationCondition("oracle_only_compact_on", "oracle_only", True),
    AblationCondition("cp_only_compact_off", "cp_only", False),
    AblationCondition("cp_only_compact_on", "cp_only", True),
)
CONDITION_BY_ID = {condition.condition_id: condition for condition in CONDITIONS}
CLAIM_BOUNDARIES = (
    "The six cells cross control, structural-oracle, and full-CP finalization with "
    "compact arms off/on. They match the overall solve budget and reserve the same "
    "finalization window; they do not consume identical finalization CPU time.",
    "The structural oracle changes rooms only after lecture times are fixed. Its "
    "certificate scope is the scope reported by each replay, not a global timetable proof.",
    "Proof replay is an unsigned current-source JSON replay. It is not a signature, "
    "trusted timestamp, or independent official-validator implementation.",
    "The official ITC-2007 validator covers the standard four-term CB-CTT projection. "
    "Any source-corpus extensions listed as projection losses remain outside the claim.",
    "At least 30 distinct, independently validated instance hashes are required per "
    "condition on held-out hashes. The four compact-arm calibration hashes are reported "
    "separately and never increase that distinct-instance count.",
    "Paired effects describe this source snapshot, corpus projection, budget, seed set, "
    "validator, and hardware; they do not establish universal solver superiority.",
    "This matrix does not validate ITC-2019 student sectioning semantics.",
)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def execution_source_snapshot(
    repo_root: str | Path,
) -> tuple[str, dict[str, str]]:
    """Hash every Python source surface used by orchestration and workers."""

    root = Path(repo_root).resolve()
    _base_digest, base_files = planora_source_snapshot(root)
    files = dict(base_files)
    scripts_root = root / "scripts"
    if scripts_root.is_dir():
        for path in sorted(scripts_root.rglob("*.py")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = sha256_file(path)
    digest = _payload_sha256(
        {
            "schema_version": "planora.execution-source-snapshot.v1",
            "source_roots": list(EXECUTION_SOURCE_ROOTS),
            "files": dict(sorted(files.items())),
        }
    )
    return digest, dict(sorted(files.items()))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl_row(path: Path, row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()


def _record_digest(row: Mapping[str, Any]) -> str:
    return _payload_sha256(
        {key: value for key, value in row.items() if key != "record_payload_sha256"}
    )


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.")
    return slug[:72] or "instance"


def balanced_williams_orders(
    condition_ids: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Return the even-order Williams design used by the factorial matrix.

    Across a complete block, every condition occupies every position once and
    every ordered first-order carryover pair occurs once.
    """

    labels = tuple(condition_ids or tuple(CONDITION_BY_ID))
    if len(labels) < 2 or len(labels) % 2:
        raise ValueError("Williams ordering requires an even number of conditions")
    if len(set(labels)) != len(labels):
        raise ValueError("Williams ordering requires distinct condition identifiers")
    n = len(labels)
    base_indices = [0]
    for offset in range(1, n):
        base_indices.append((offset + 1) // 2 if offset % 2 else n - offset // 2)
    return tuple(
        tuple(labels[(index + shift) % n] for index in base_indices)
        for shift in range(n)
    )


def williams_order(cell_index: int) -> tuple[str, ...]:
    orders = balanced_williams_orders()
    return orders[int(cell_index) % len(orders)]


def _balanced_crossover_orders(
    treatment_ids: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    """Return a first-order balanced Williams crossover for even or odd N.

    Odd treatment counts require the cyclic Williams rows and their reversals;
    this gives every ordered carryover pair twice per complete 2N-row block.
    """

    labels = tuple(str(value) for value in treatment_ids)
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("Crossover treatments must be distinct and non-trivial")
    if len(labels) % 2 == 0:
        return balanced_williams_orders(labels)
    n = len(labels)
    base_indices = [0]
    for offset in range(1, n):
        base_indices.append((offset + 1) // 2 if offset % 2 else n - offset // 2)
    cyclic = tuple(
        tuple(labels[(index + shift) % n] for index in base_indices)
        for shift in range(n)
    )
    return (*cyclic, *(tuple(reversed(order)) for order in cyclic))


def _execution_orders(*, include_cpsolver: bool) -> tuple[tuple[str, ...], ...]:
    treatments = tuple(CONDITION_BY_ID)
    if include_cpsolver:
        treatments = (*treatments, "cpsolver_reference")
    return _balanced_crossover_orders(treatments)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _load_provenance(
    provenance_json: str | Path | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if provenance_json is None:
        return {"supplied": False}, {}
    path = Path(provenance_json).resolve()
    payload = _read_json(path)
    rows = payload.get("instances")
    if not isinstance(rows, list):
        raise ValueError("CB-CTT provenance JSON must contain an instances list")
    by_projection_hash: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"Malformed provenance instance row at index {index}")
        digest = str(raw.get("projected_sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Malformed projected_sha256 at provenance row {index}")
        metadata = {
            "provenance_match": "projected_sha256",
            "family": str(raw.get("family") or "unclassified"),
            "projected_relative_path": raw.get("projected_relative_path"),
            "projected_sha256": digest,
            "source_relative_path": raw.get("source_relative_path"),
            "source_sha256": raw.get("source_sha256"),
            "source_content_swhid": raw.get("source_content_swhid"),
            "projection": dict(raw.get("projection") or {}),
        }
        previous = by_projection_hash.get(digest)
        if previous is not None and previous != metadata:
            raise ValueError(
                "Provenance maps one projected hash to conflicting corpus metadata"
            )
        by_projection_hash[digest] = metadata
    corpus = dict(payload.get("corpus") or {})
    return (
        {
            "supplied": True,
            "path": str(path),
            "sha256": sha256_file(path),
            "schema_version": payload.get("schema_version"),
            "projection_scope": corpus.get("projection_scope"),
            "source_manifest_sha256": corpus.get("source_manifest_sha256"),
            "projection_set_sha256": corpus.get("projection_set_sha256"),
            "licensing": dict(payload.get("licensing") or {}),
        },
        by_projection_hash,
    )


def _corpus_metadata(
    instance_path: Path,
    instance_sha256: str,
    provenance_header: Mapping[str, Any],
    provenance_by_hash: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    matched = provenance_by_hash.get(instance_sha256)
    if matched is not None:
        projection = dict(matched.get("projection") or {})
        return {
            **dict(matched),
            "projection_scope": provenance_header.get("projection_scope"),
            "extension_losses": dict(projection.get("extension_losses") or {}),
            "provenance_sha256": provenance_header.get("sha256"),
        }
    return {
        "provenance_match": "none",
        "family": "unclassified",
        "instance_filename": instance_path.name,
        "projected_sha256": instance_sha256,
        "claim_boundary": (
            "No supplied provenance row matched this instance hash; the matrix does "
            "not infer an institution or official-corpus identity from its filename."
        ),
    }


def _command_file_evidence(command: Sequence[str | Path]) -> list[dict[str, Any]]:
    """Resolve every behavior-bearing command artifact or fail closed.

    Hashing only an interpreter while accepting inline code would let an arbitrary
    scorer be labelled as the official validator.  Resolve argv[0], reject opaque
    container launchers, require a file-backed program for interpreter commands,
    and fail when a path-like argument cannot be resolved.
    """

    normalized = [str(value) for value in command]
    if not normalized:
        raise ValueError("A validator command is required")
    evidence: list[dict[str, Any]] = []
    for index, token in enumerate(normalized):
        candidate_token = token.split("=", 1)[1] if "=" in token else token
        candidate = Path(candidate_token).expanduser()
        resolved: Path | None = None
        if candidate.is_file():
            resolved = candidate.resolve()
        elif index == 0:
            executable = shutil.which(token)
            if executable is not None and Path(executable).is_file():
                resolved = Path(executable).resolve()
        elif (
            "/" in candidate_token
            or "\\" in candidate_token
            or candidate.suffix.casefold()
            in {".exe", ".jar", ".js", ".py", ".sh"}
        ):
            raise ValueError(
                f"Validator command artifact cannot be resolved: argv[{index}]={token!r}"
            )
        if resolved is None:
            continue
        evidence.append(
            {
                "argument_index": int(index),
                "argument_token": token,
                "path": str(resolved),
                "sha256": sha256_file(resolved),
                "bytes": resolved.stat().st_size,
            }
        )

    if not evidence or evidence[0]["argument_index"] != 0:
        raise ValueError(
            "Validator executable provenance cannot be resolved to a local file"
        )
    executable_name = Path(str(evidence[0]["path"])).name.casefold()
    if executable_name in {"docker", "docker.exe", "podman", "podman.exe"}:
        raise ValueError(
            "Containerized validator commands require a separately pinned image and "
            "are not accepted by this publication harness"
        )
    interpreter = executable_name.startswith(
        ("python", "pypy", "java", "node", "bash", "sh", "pwsh", "powershell")
    )
    if interpreter and len(evidence) == 1:
        raise ValueError(
            "Interpreter-based validator provenance is unresolved; provide the "
            "validator script or archive as a file argument"
        )
    return evidence


def _validator_identity_evidence(
    command: Sequence[str | Path],
    *,
    expected_sha256: str | None,
) -> dict[str, Any]:
    files = _command_file_evidence(command)
    executable_name = Path(str(files[0]["path"])).name.casefold()
    interpreter = executable_name.startswith(
        ("python", "pypy", "java", "node", "bash", "sh", "pwsh", "powershell")
    )
    primary = files[-1] if interpreter else files[0]
    observed = str(primary["sha256"]).lower()
    expected = str(expected_sha256 or "").strip().lower() or None
    if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("official_validator_sha256 must be a lowercase SHA-256")
    if expected is not None and expected != observed:
        raise BenchmarkInputDrift(
            "Validator identity does not match the explicit pin: "
            f"expected={expected}, observed={observed}"
        )
    recognized = OFFICIAL_ITC2007_VALIDATOR_PINS.get(observed)
    explicitly_pinned = expected == observed
    official_identity_verified = bool(explicitly_pinned and recognized is not None)
    return {
        "command": [str(value) for value in command],
        "command_files": files,
        "primary_path": str(primary["path"]),
        "primary_sha256": observed,
        "expected_primary_sha256": expected,
        "explicit_pin_match": bool(explicitly_pinned),
        "recognized_official_identity": dict(recognized or {}),
        "official_identity_verified": bool(official_identity_verified),
        "identity_gate": "PASS" if official_identity_verified else "NO-GO",
        "role": (
            "pinned_official_external_itc2007_validator"
            if official_identity_verified
            else "external_itc2007_validator_without_recognized_official_pin"
        ),
    }


def _sorted_instances(instances: Sequence[str | Path]) -> list[Path]:
    paths = [Path(value).resolve() for value in instances]
    if not paths:
        raise ValueError("At least one ITC-2007 or projected CB-CTT instance is required")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate instance paths are not allowed")
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        by_hash[sha256_file(path)].append(path)
    duplicates = {
        digest: [str(path) for path in duplicate_paths]
        for digest, duplicate_paths in by_hash.items()
        if len(duplicate_paths) > 1
    }
    if duplicates:
        raise ValueError(
            "Duplicate instance contents are not allowed: "
            + json.dumps(duplicates, sort_keys=True)
        )
    return sorted(paths, key=lambda path: (sha256_file(path), path.as_posix()))


def _normalized_seeds(seeds: Sequence[int]) -> list[int]:
    normalized = sorted(int(seed) for seed in seeds)
    if not normalized:
        raise ValueError("At least one seed is required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Duplicate seeds are not allowed")
    return normalized


def _compact_calibration_declaration(
    instance_paths: Sequence[str | Path] | None,
    explicit_sha256: Sequence[str] | None,
) -> dict[str, Any]:
    path_evidence: list[dict[str, Any]] = []
    path_hashes: set[str] = set()
    resolved_paths: set[Path] = set()
    for raw_path in instance_paths or ():
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path in resolved_paths:
            raise ValueError(f"Duplicate compact calibration path: {path}")
        resolved_paths.add(path)
        problem = parse_itc2007_ctt(path)
        digest = sha256_file(path)
        path_evidence.append(
            {
                "path": str(path),
                "sha256": digest,
                "bytes": path.stat().st_size,
                "instance_name": str(problem.name),
            }
        )
        path_hashes.add(digest)
    explicit_hashes: set[str] = set()
    for raw_digest in explicit_sha256 or ():
        digest = str(raw_digest).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Malformed compact calibration SHA-256: {raw_digest!r}")
        explicit_hashes.add(digest)
    if explicit_hashes and path_hashes and explicit_hashes != path_hashes:
        raise BenchmarkInputDrift(
            "Explicit compact calibration hashes do not exactly match the supplied "
            "canonical calibration files"
        )
    declared_hashes = explicit_hashes or path_hashes
    canonical_files_verified = bool(
        len(path_evidence) == 4
        and len(path_hashes) == 4
        and (not explicit_hashes or explicit_hashes == path_hashes)
    )
    ordered = sorted(declared_hashes)
    return {
        "declaration": (
            "canonical_content_hashed_instance_files"
            if canonical_files_verified
            else "unverified_hash_declaration"
            if ordered
            else "not_declared"
        ),
        "instance_sha256": ordered,
        "path_evidence": sorted(path_evidence, key=lambda row: str(row["path"])),
        "required_calibration_hash_count": 4,
        "declared_calibration_hash_count": len(ordered),
        "canonical_file_evidence_verified": bool(canonical_files_verified),
        "cardinality_gate": (
            "PASS" if canonical_files_verified else "NO-GO"
        ),
        "selection_history": (
            "The operator must supply the four exact preselected ITC-2007 files. "
            "Bare hashes do not establish calibration history or held-out status."
        ),
        "publication_policy": (
            "Calibration hashes are excluded from held-out compact-policy effect claims."
        ),
    }


def _assert_calibration_unchanged(
    manifest: Mapping[str, Any], *, phase: str
) -> None:
    declaration = dict(manifest.get("compact_policy_calibration") or {})
    for evidence in declaration.get("path_evidence") or []:
        path = Path(str(evidence["path"]))
        observed = sha256_file(path)
        expected = str(evidence["sha256"])
        if observed != expected:
            raise BenchmarkInputDrift(
                f"Compact calibration file changed {phase}: {path}; "
                f"expected={expected}, observed={observed}"
            )


def _build_execution_cells(
    instance_rows: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    *,
    include_cpsolver: bool,
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    execution_orders = _execution_orders(include_cpsolver=include_cpsolver)
    cell_index = 0
    for instance in instance_rows:
        for seed in seeds:
            execution = list(execution_orders[cell_index % len(execution_orders)])
            order = [task_id for task_id in execution if task_id in CONDITION_BY_ID]
            competitor_gap = (
                execution.index("cpsolver_reference") if include_cpsolver else None
            )
            cells.append(
                {
                    "cell_index": int(cell_index),
                    "instance_id": instance["instance_id"],
                    "instance_sha256": instance["sha256"],
                    "seed": int(seed),
                    "williams_sequence_index": int(
                        cell_index % len(execution_orders)
                    ),
                    "condition_order": order,
                    "cpsolver_insertion_gap": competitor_gap,
                    "execution_order": execution,
                }
            )
            cell_index += 1
    return cells


def _resolve_executable_evidence(command: str | Path) -> dict[str, Any]:
    token = str(command)
    candidate = Path(token).expanduser()
    resolved: Path | None = candidate.resolve() if candidate.is_file() else None
    if resolved is None:
        executable = shutil.which(token)
        if executable is not None and Path(executable).is_file():
            resolved = Path(executable).resolve()
    if resolved is None:
        raise FileNotFoundError(f"Executable cannot be resolved: {token}")
    return {
        "command": token,
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _cpsolver_execution_evidence(
    *,
    cpsolver_root: str | Path,
    classes_path: str | Path,
    java_command: str | Path,
    java_xmx_mb: int,
) -> dict[str, Any]:
    root = Path(cpsolver_root).resolve()
    classes = Path(classes_path).resolve()
    source = root / "src"
    libraries = root / "lib"
    for label, path in (
        ("CPSolver root", root),
        ("CPSolver classes", classes),
        ("CPSolver runtime source/resources", source),
        ("CPSolver runtime libraries", libraries),
    ):
        if not path.is_dir():
            raise FileNotFoundError(f"{label} directory is missing: {path}")
    java = _resolve_executable_evidence(java_command)
    if int(java_xmx_mb) <= 0:
        raise ValueError("java_xmx_mb must be positive")
    surfaces = {
        "classes_sha256": sha256_tree(classes),
        "source_resources_sha256": sha256_tree(source),
        "libraries_sha256": sha256_tree(libraries),
        "java_executable_sha256": str(java["sha256"]),
        "java_xmx_mb": int(java_xmx_mb),
    }
    return {
        "root": str(root),
        "classes_path": str(classes),
        "source_resources_path": str(source),
        "libraries_path": str(libraries),
        "java": java,
        **surfaces,
        "execution_surface_sha256": _payload_sha256(surfaces),
        "provenance_gate": "PASS",
    }


def build_ablation_manifest(
    *,
    repo_root: str | Path,
    instances: Sequence[str | Path],
    seeds: Sequence[int],
    time_limit_seconds: float,
    validator_command: Sequence[str | Path],
    workers: int = 1,
    cpu: int | None = None,
    include_cpsolver: bool = False,
    cpsolver_root: str | Path | None = None,
    classes_path: str | Path | None = None,
    java_command: str | Path = "java",
    java_xmx_mb: int = 1024,
    provenance_json: str | Path | None = None,
    compact_calibration_instances: Sequence[str | Path] | None = None,
    compact_calibration_sha256: Sequence[str] | None = None,
    minimum_effective_instances: int = 30,
    deadline_overrun_tolerance_seconds: float = 0.0,
    supervision_grace_seconds: float = 30.0,
    itc2007_course_symmetry: bool = False,
    itc2007_adaptive_seeding: bool = True,
    official_validator_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    instance_paths = _sorted_instances(instances)
    normalized_seeds = _normalized_seeds(seeds)
    if float(time_limit_seconds) <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if int(workers) != 1:
        raise ValueError("Publication ablations require one solver worker")
    if int(minimum_effective_instances) <= 0:
        raise ValueError("minimum_effective_instances must be positive")
    if float(deadline_overrun_tolerance_seconds) < 0:
        raise ValueError("deadline_overrun_tolerance_seconds cannot be negative")
    if float(supervision_grace_seconds) < 0:
        raise ValueError("supervision_grace_seconds cannot be negative")
    if not validator_command:
        raise ValueError("An official ITC-2007 validator command is required")
    if include_cpsolver and (cpsolver_root is None or classes_path is None):
        raise ValueError("CPSolver root and classes path are required when enabled")
    if include_cpsolver and not float(time_limit_seconds).is_integer():
        raise ValueError("CPSolver ITC-2007 requires an integer time limit")

    source_sha256, source_files = execution_source_snapshot(root)
    compact_calibration = _compact_calibration_declaration(
        compact_calibration_instances,
        compact_calibration_sha256,
    )
    calibration_hashes = set(compact_calibration["instance_sha256"])
    provenance_header, provenance_by_hash = _load_provenance(provenance_json)
    instance_rows: list[dict[str, Any]] = []
    for path in instance_paths:
        digest = sha256_file(path)
        instance_rows.append(
            {
                "instance_id": path.stem,
                "path": str(path),
                "sha256": digest,
                "bytes": path.stat().st_size,
                "corpus": _corpus_metadata(
                    path,
                    digest,
                    provenance_header,
                    provenance_by_hash,
                ),
                "compact_policy_partition": (
                    "calibration" if digest in calibration_hashes else "held_out"
                ),
            }
        )
    validator_evidence = _validator_identity_evidence(
        validator_command,
        expected_sha256=official_validator_sha256,
    )
    cpsolver_evidence: dict[str, Any] = {"enabled": bool(include_cpsolver)}
    if include_cpsolver:
        cpsolver_evidence.update(
            _cpsolver_execution_evidence(
                cpsolver_root=Path(str(cpsolver_root)),
                classes_path=Path(str(classes_path)),
                java_command=java_command,
                java_xmx_mb=int(java_xmx_mb),
            )
        )

    cells = _build_execution_cells(
        instance_rows,
        normalized_seeds,
        include_cpsolver=include_cpsolver,
    )
    planned_planora = len(cells) * len(CONDITIONS)
    planned_cpsolver = len(cells) if include_cpsolver else 0
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "repo_root": str(root),
        "planora_source_sha256": source_sha256,
        "planora_source_files": source_files,
        "planora_execution_source_roots": list(EXECUTION_SOURCE_ROOTS),
        "instances": instance_rows,
        "seeds": normalized_seeds,
        "time_limit_seconds": float(time_limit_seconds),
        "workers": int(workers),
        "cpu_affinity": int(cpu) if cpu is not None else None,
        "conditions": [condition.to_dict() for condition in CONDITIONS],
        "execution_design": {
            "name": "balanced_williams_first_order_carryover",
            "orders": [
                list(order)
                for order in _execution_orders(include_cpsolver=include_cpsolver)
            ],
            "assignment": (
                "canonical_instance_then_seed_cell_index_modulo_execution_order_count"
            ),
            "cpsolver_policy": (
                "joint_seven_treatment_odd_williams_crossover"
                if include_cpsolver
                else "disabled"
            ),
            "cells": cells,
        },
        "planned_runs": {
            "planora": int(planned_planora),
            "cpsolver": int(planned_cpsolver),
            "total": int(planned_planora + planned_cpsolver),
        },
        "minimum_effective_instances_per_condition": int(
            minimum_effective_instances
        ),
        "deadline_policy": {
            "metric": "strategy_meta.timing.deadline_overrun_seconds",
            "maximum_seconds": float(deadline_overrun_tolerance_seconds),
            "missing_value_is_failure": True,
        },
        "supervision_policy": {
            "grace_seconds": float(supervision_grace_seconds),
            "scope": (
                "process_hang_guard_only; solver budgets remain time_limit_seconds"
            ),
        },
        "solver_options": {
            "planora_strategy": "research_adaptive",
            "itc2007_course_symmetry": bool(itc2007_course_symmetry),
            "itc2007_adaptive_seeding": bool(itc2007_adaptive_seeding),
            "fixed_time_room_dive": True,
        },
        "validator": validator_evidence,
        "cpsolver": cpsolver_evidence,
        "corpus_provenance": provenance_header,
        "compact_policy_calibration": compact_calibration,
        "environment": {
            "python_version": platform.python_version(),
            "ortools_version": importlib.metadata.version("ortools"),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "sanitized_child_environment_variables": list(
                BENCHMARK_SANITIZED_ENVIRONMENT_VARIABLES
            ),
        },
        "claim_boundaries": list(CLAIM_BOUNDARIES),
    }


def _assert_source_snapshot(
    repo_root: Path,
    expected_sha256: str,
    *,
    phase: str,
) -> tuple[str, dict[str, str]]:
    observed_sha256, observed_files = execution_source_snapshot(repo_root)
    if observed_sha256 != expected_sha256:
        raise SourceSnapshotDrift(
            f"Planora source changed {phase}: expected={expected_sha256}, "
            f"observed={observed_sha256}"
        )
    return observed_sha256, observed_files


def _assert_instance_unchanged(instance: Mapping[str, Any], *, phase: str) -> None:
    path = Path(str(instance["path"]))
    observed = sha256_file(path)
    expected = str(instance["sha256"])
    if observed != expected:
        raise BenchmarkInputDrift(
            f"Instance changed {phase}: {path}; expected={expected}, observed={observed}"
        )


def _assert_validator_unchanged(manifest: Mapping[str, Any], *, phase: str) -> None:
    validator = dict(manifest.get("validator") or {})
    for evidence in validator.get("command_files") or []:
        path = Path(str(evidence["path"]))
        observed = sha256_file(path)
        expected = str(evidence["sha256"])
        if observed != expected:
            raise BenchmarkInputDrift(
                f"Validator command file changed {phase}: {path}; "
                f"expected={expected}, observed={observed}"
            )


def _assert_cpsolver_unchanged(manifest: Mapping[str, Any], *, phase: str) -> None:
    cpsolver = dict(manifest.get("cpsolver") or {})
    if cpsolver.get("enabled") is not True:
        return
    surfaces = (
        ("classes", "classes_path", "classes_sha256"),
        (
            "runtime source/resources",
            "source_resources_path",
            "source_resources_sha256",
        ),
        ("runtime libraries", "libraries_path", "libraries_sha256"),
    )
    for label, path_key, digest_key in surfaces:
        path = Path(str(cpsolver[path_key]))
        observed = sha256_tree(path)
        expected = str(cpsolver[digest_key])
        if observed != expected:
            raise BenchmarkInputDrift(
                f"CPSolver {label} changed {phase}: "
                f"expected={expected}, observed={observed}"
            )
    java = dict(cpsolver.get("java") or {})
    java_path = Path(str(java.get("path", "")))
    observed_java = sha256_file(java_path)
    expected_java = str(java.get("sha256"))
    if observed_java != expected_java:
        raise BenchmarkInputDrift(
            f"Java executable changed {phase}: "
            f"expected={expected_java}, observed={observed_java}"
        )


def _relative_artifact(path: Path, output_directory: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(output_directory.resolve()).as_posix()
    except ValueError as exc:
        raise ArtifactIntegrityError(
            f"Runner artifact escaped the matrix directory: {resolved}"
        ) from exc


def _capture_run_artifacts(
    record: Mapping[str, Any], output_directory: Path
) -> dict[str, dict[str, Any]]:
    fields = (
        "solution_path",
        "worker_metadata_path",
        "validator_output_path",
        "stdout_path",
        "stderr_path",
    )
    evidence: dict[str, dict[str, Any]] = {}
    for field in fields:
        raw = record.get(field)
        if raw is None:
            continue
        path = Path(str(raw))
        if not path.is_file():
            continue
        evidence[field] = {
            "path": _relative_artifact(path, output_directory),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return evidence


def _worker_internal_score(record: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = record.get("worker_metadata_path")
    if raw is None:
        return None
    path = Path(str(raw))
    if not path.is_file():
        return None
    payload = _read_json(path)
    score = payload.get("official_score_internal")
    return dict(score) if isinstance(score, dict) else None


def _official_validation_evidence(
    record: Mapping[str, Any], *, solver_id: str
) -> dict[str, Any]:
    solution_produced = bool(record.get("solution_sha256"))
    status = str(record.get("status", ""))
    validator_completed = bool(
        solution_produced
        and status
        in {"FEASIBLE", "INVALID", "SCORER_MISMATCH", "PROOF_REPLAY_MISMATCH"}
        and record.get("hard_violations") is not None
        and isinstance(record.get("official_components"), dict)
    )
    externally_feasible = bool(
        validator_completed
        and int(record.get("hard_violations") or 0) == 0
        and record.get("official_objective") is not None
    )
    internal_score = _worker_internal_score(record) if solver_id == SOLVER_PLANORA else None
    internal_agreement = (
        internal_score == record.get("official_components")
        if internal_score is not None
        else None
    )
    if solver_id == SOLVER_PLANORA and solution_produced and internal_agreement is None:
        internal_agreement = False
    return {
        "solution_produced": bool(solution_produced),
        "validator_attempted": bool(solution_produced),
        "validator_completed": bool(validator_completed),
        "externally_feasible": bool(externally_feasible),
        "hard_violations": record.get("hard_violations"),
        "official_objective": record.get("official_objective"),
        "internal_score": internal_score,
        "internal_external_component_agreement": internal_agreement,
        "validator_error": record.get("validator_error"),
        "claim": (
            "official ITC-2007 validator result; projected CB-CTT extensions are excluded"
        ),
    }


def _strategy_deadline_evidence(
    record: Mapping[str, Any], *, tolerance_seconds: float
) -> dict[str, Any]:
    strategy_meta = dict(record.get("strategy_meta") or {})
    timing = dict(strategy_meta.get("timing") or {})
    raw_overrun = timing.get("deadline_overrun_seconds")
    overrun = float(raw_overrun) if isinstance(raw_overrun, (int, float)) else None
    adaptive = dict(strategy_meta.get("adaptive_lns") or {})
    room_dive = dict(adaptive.get("fixed_time_room_dive") or {})
    room_overrun_raw = room_dive.get("deadline_overrun_seconds")
    room_overrun = (
        float(room_overrun_raw)
        if isinstance(room_overrun_raw, (int, float))
        else None
    )
    return {
        "budget_seconds": timing.get("budget_seconds"),
        "elapsed_seconds": timing.get("elapsed_seconds"),
        "deadline_overrun_seconds": overrun,
        "maximum_allowed_overrun_seconds": float(tolerance_seconds),
        "strict_pass": bool(
            overrun is not None and overrun <= float(tolerance_seconds)
        ),
        "room_finalization_deadline_overrun_seconds": room_overrun,
    }


def _normalize_planora_record(
    raw_record: Mapping[str, Any],
    *,
    condition: AblationCondition,
    cell: Mapping[str, Any],
    execution_index: int,
    execution_position: int,
    source_sha256: str,
    source_match: bool,
    corpus: Mapping[str, Any],
    compact_policy_partition: str,
    output_directory: Path,
    deadline_overrun_tolerance_seconds: float,
) -> dict[str, Any]:
    record = dict(raw_record)
    proof_replay = dict(record.get("fixed_time_room_proof_replay") or {})
    adaptive = dict((record.get("strategy_meta") or {}).get("adaptive_lns") or {})
    room_dive = dict(adaptive.get("fixed_time_room_dive") or {})
    record.update(
        {
            "schema_version": SCHEMA_VERSION,
            "condition_id": condition.condition_id,
            "condition": condition.to_dict(),
            "cell_index": int(cell["cell_index"]),
            "williams_sequence_index": int(cell["williams_sequence_index"]),
            "condition_execution_position": int(execution_position),
            "execution_index": int(execution_index),
            "source_snapshot_sha256": str(source_sha256),
            "source_snapshot_match": bool(source_match),
            "corpus": dict(corpus),
            "compact_policy_partition": str(compact_policy_partition),
            "fixed_time_room_proof_replay": proof_replay,
            "fixed_time_room_strategy_telemetry": room_dive,
            "deadline": _strategy_deadline_evidence(
                record,
                tolerance_seconds=deadline_overrun_tolerance_seconds,
            ),
        }
    )
    record["official_validation"] = _official_validation_evidence(
        record, solver_id=SOLVER_PLANORA
    )
    record["artifacts"] = _capture_run_artifacts(record, output_directory)
    record["record_payload_sha256"] = _record_digest(record)
    return record


def _normalize_cpsolver_record(
    raw_record: Mapping[str, Any],
    *,
    cell: Mapping[str, Any],
    execution_index: int,
    source_sha256: str,
    source_match: bool,
    corpus: Mapping[str, Any],
    compact_policy_partition: str,
    output_directory: Path,
) -> dict[str, Any]:
    record = dict(raw_record)
    record.update(
        {
            "schema_version": SCHEMA_VERSION,
            "condition_id": "cpsolver_reference",
            "cell_index": int(cell["cell_index"]),
            "williams_sequence_index": int(cell["williams_sequence_index"]),
            "condition_execution_position": list(cell["execution_order"]).index(
                "cpsolver_reference"
            ),
            "execution_index": int(execution_index),
            "source_snapshot_sha256": str(source_sha256),
            "source_snapshot_match": bool(source_match),
            "corpus": dict(corpus),
            "compact_policy_partition": str(compact_policy_partition),
            "deadline": {
                "strict_pass": bool(not record.get("timed_out")),
                "scope": "supervisor_timeout_only; CPSolver does not expose Planora timing",
            },
        }
    )
    record["official_validation"] = _official_validation_evidence(
        record, solver_id=SOLVER_CPSOLVER
    )
    record["artifacts"] = _capture_run_artifacts(record, output_directory)
    record["record_payload_sha256"] = _record_digest(record)
    return record


def _condition_parity(row: Mapping[str, Any]) -> bool:
    condition = CONDITION_BY_ID.get(str(row.get("condition_id")))
    if condition is None:
        return False
    return bool(
        str(row.get("solver_id")) == SOLVER_PLANORA
        and str(row.get("strategy")) == "research_adaptive"
        and row.get("itc2007_fixed_time_room_dive") is True
        and str(row.get("itc2007_fixed_time_room_strategy"))
        == condition.fixed_time_room_strategy
        and row.get("itc2007_compact_adaptive_arms")
        is condition.compact_adaptive_arms
    )


def _claim_bearing_proof_is_complete(proof: Mapping[str, Any]) -> bool:
    """Require evidence of an actual successful serialization and replay."""

    roundtrip = proof.get("roundtrip_seconds")
    replay = proof.get("replay_seconds")
    serialized_bytes = proof.get("serialized_bytes")
    return bool(
        proof.get("attempted") is True
        and proof.get("valid") is True
        and proof.get("verified_candidate_matches_returned_schedule") is True
        and proof.get("scope")
        == "eligible_fixed_time_room_mathematical_certificate"
        and proof.get("integrity") == "unsigned_json_roundtrip"
        and proof.get("errors") == []
        and isinstance(roundtrip, (int, float))
        and not isinstance(roundtrip, bool)
        and math.isfinite(float(roundtrip))
        and float(roundtrip) >= 0.0
        and isinstance(replay, (int, float))
        and not isinstance(replay, bool)
        and math.isfinite(float(replay))
        and float(replay) >= 0.0
        and type(serialized_bytes) is int
        and int(serialized_bytes) > 0
        and type(proof.get("capacity_lower_bound")) is int
        and type(proof.get("room_lower_bound")) is int
    )


def _effectiveness_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not _condition_parity(row):
        reasons.append("condition_configuration_mismatch")
    if row.get("source_snapshot_match") is not True:
        reasons.append("source_snapshot_mismatch")
    validation = dict(row.get("official_validation") or {})
    if validation.get("validator_completed") is not True:
        reasons.append("official_validator_not_completed")
    if validation.get("externally_feasible") is not True:
        reasons.append("official_validator_not_feasible")
    if validation.get("internal_external_component_agreement") is not True:
        reasons.append("internal_external_score_mismatch")
    if dict(row.get("deadline") or {}).get("strict_pass") is not True:
        reasons.append("strict_solve_deadline_overrun_or_missing")
    proof = dict(row.get("fixed_time_room_proof_replay") or {})
    if proof.get("attempted") is True and not _claim_bearing_proof_is_complete(proof):
        reasons.append("claim_bearing_proof_replay_failed")
    components = row.get("official_components")
    if not isinstance(components, dict) or any(
        name not in components for name in COMPONENT_NAMES
    ):
        reasons.append("official_components_incomplete")
    elif row.get("official_objective") != components.get("total"):
        reasons.append("official_total_component_mismatch")
    if not row.get("solution_sha256"):
        reasons.append("solution_hash_missing")
    return reasons


def _is_effective(row: Mapping[str, Any]) -> bool:
    return not _effectiveness_reasons(row)


def _is_cpsolver_effective(row: Mapping[str, Any]) -> bool:
    validation = dict(row.get("official_validation") or {})
    components = row.get("official_components")
    return bool(
        str(row.get("solver_id")) == SOLVER_CPSOLVER
        and row.get("source_snapshot_match") is True
        and validation.get("validator_completed") is True
        and validation.get("externally_feasible") is True
        and dict(row.get("deadline") or {}).get("strict_pass") is True
        and isinstance(components, dict)
        and all(name in components for name in COMPONENT_NAMES)
        and row.get("official_objective") == components.get("total")
        and bool(row.get("solution_sha256"))
    )


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * float(probability)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _component_sums(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        name: sum(int(dict(row["official_components"])[name]) for row in rows)
        for name in COMPONENT_NAMES
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, int, float]:
    return (
        str(row.get("instance_sha256")),
        int(row.get("seed", 0)),
        float(row.get("time_limit_seconds", 0.0)),
    )


def _unique_by_key(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, int, float], Mapping[str, Any]], list[list[Any]]]:
    grouped: dict[tuple[str, int, float], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_row_key(row)].append(row)
    duplicates = [list(key) for key, values in grouped.items() if len(values) != 1]
    return (
        {key: values[0] for key, values in grouped.items() if len(values) == 1},
        sorted(duplicates),
    )


def _paired_comparison(
    left_id: str,
    right_id: str,
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_resamples: int,
    left_effective: Callable[[Mapping[str, Any]], bool] = _is_effective,
    right_effective: Callable[[Mapping[str, Any]], bool] = _is_effective,
    wall_time_scope: str = "worker_solve",
) -> dict[str, Any]:
    left_by_key, left_duplicates = _unique_by_key(left_rows)
    right_by_key, right_duplicates = _unique_by_key(right_rows)
    keys = sorted(set(left_by_key) & set(right_by_key))

    def externally_feasible(row: Mapping[str, Any]) -> bool:
        return bool(
            dict(row.get("official_validation") or {}).get(
                "externally_feasible"
            )
            is True
        )

    feasibility_counts = Counter()
    winner_counts = Counter()
    for key in keys:
        left = left_by_key[key]
        right = right_by_key[key]
        left_feasible = externally_feasible(left)
        right_feasible = externally_feasible(right)
        if left_feasible and right_feasible:
            feasibility_counts["both_feasible"] += 1
            left_objective = int(left["official_objective"])
            right_objective = int(right["official_objective"])
            winner_counts[
                "left"
                if left_objective < right_objective
                else "right"
                if right_objective < left_objective
                else "tie"
            ] += 1
        elif left_feasible:
            feasibility_counts["left_only_feasible"] += 1
            winner_counts["left"] += 1
        elif right_feasible:
            feasibility_counts["right_only_feasible"] += 1
            winner_counts["right"] += 1
        else:
            feasibility_counts["neither_feasible_or_validated"] += 1
            winner_counts["unresolved"] += 1
    effective_pairs = [
        (key, left_by_key[key], right_by_key[key])
        for key in keys
        if left_effective(left_by_key[key]) and right_effective(right_by_key[key])
    ]
    objective_seed_deltas = [
        float(left["official_objective"]) - float(right["official_objective"])
        for _key, left, right in effective_pairs
    ]
    if wall_time_scope not in {"worker_solve", "supervisor_process"}:
        raise ValueError(f"Unknown wall_time_scope: {wall_time_scope}")

    def wall_value(row: Mapping[str, Any]) -> float:
        if wall_time_scope == "supervisor_process":
            return float(row.get("wall_time_seconds") or 0.0)
        return float(
            row.get("worker_wall_time_seconds")
            or row.get("wall_time_seconds")
            or 0.0
        )

    wall_seed_deltas = [
        wall_value(left) - wall_value(right)
        for _key, left, right in effective_pairs
    ]
    objective_by_instance: dict[str, list[float]] = defaultdict(list)
    wall_by_instance: dict[str, list[float]] = defaultdict(list)
    component_by_instance: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (key, left, right), objective_delta, wall_delta in zip(
        effective_pairs,
        objective_seed_deltas,
        wall_seed_deltas,
        strict=True,
    ):
        objective_by_instance[key[0]].append(objective_delta)
        wall_by_instance[key[0]].append(wall_delta)
        for name in COMPONENT_NAMES:
            component_by_instance[key[0]][name].append(
                float(dict(left["official_components"])[name])
                - float(dict(right["official_components"])[name])
            )
    objective_deltas = [
        statistics.fmean(objective_by_instance[digest])
        for digest in sorted(objective_by_instance)
    ]
    wall_deltas = [
        statistics.fmean(wall_by_instance[digest])
        for digest in sorted(wall_by_instance)
    ]
    component_seed_pair_sums = {
        name: sum(
            int(dict(left["official_components"])[name])
            - int(dict(right["official_components"])[name])
            for _key, left, right in effective_pairs
        )
        for name in COMPONENT_NAMES
    }
    component_instance_mean_sums = {
        name: sum(
            statistics.fmean(component_by_instance[digest][name])
            for digest in sorted(component_by_instance)
        )
        for name in COMPONENT_NAMES
    }
    family_by_instance: dict[str, str] = {}
    family_mismatches: list[str] = []
    for key, left, right in effective_pairs:
        digest = key[0]
        left_family = str(
            dict(left.get("corpus") or {}).get("family", "unclassified")
        )
        right_family = str(
            dict(right.get("corpus") or {}).get("family", "unclassified")
        )
        if left_family != right_family:
            family_mismatches.append(digest)
        family_by_instance.setdefault(digest, left_family)
    objective_by_family: dict[str, list[float]] = defaultdict(list)
    for digest, seed_deltas in objective_by_instance.items():
        objective_by_family[family_by_instance.get(digest, "unclassified")].append(
            statistics.fmean(seed_deltas)
        )
    family_mean_deltas = [
        statistics.fmean(objective_by_family[family])
        for family in sorted(objective_by_family)
    ]
    return {
        "left": str(left_id),
        "right": str(right_id),
        "difference_orientation": "left_minus_right; positive objective favors right",
        "available_pairs": len(keys),
        "effective_pairs": len(effective_pairs),
        "effective_distinct_instances": len(objective_deltas),
        "statistical_unit": (
            "distinct instance hash; repeated seed-pair deltas are averaged within instance"
        ),
        "duplicate_left_keys": left_duplicates,
        "duplicate_right_keys": right_duplicates,
        "feasibility_first": {
            "rule": (
                "officially validated feasibility dominates objective; objective is "
                "compared only when both schedules are externally feasible"
            ),
            "both_feasible": int(feasibility_counts["both_feasible"]),
            "left_only_feasible": int(
                feasibility_counts["left_only_feasible"]
            ),
            "right_only_feasible": int(
                feasibility_counts["right_only_feasible"]
            ),
            "neither_feasible_or_validated": int(
                feasibility_counts["neither_feasible_or_validated"]
            ),
            "left_wins": int(winner_counts["left"]),
            "right_wins": int(winner_counts["right"]),
            "ties": int(winner_counts["tie"]),
            "unresolved": int(winner_counts["unresolved"]),
        },
        "family_cluster_sensitivity": {
            "family_count": len(family_mean_deltas),
            "families": {
                family: {
                    "distinct_instances": len(values),
                    "instance_mean_delta": statistics.fmean(values),
                }
                for family, values in sorted(objective_by_family.items())
            },
            "family_metadata_mismatch_instance_sha256": sorted(
                set(family_mismatches)
            ),
            "equal_family_weighted_mean_delta": (
                statistics.fmean(family_mean_deltas)
                if family_mean_deltas
                else None
            ),
            "family_cluster_bootstrap_mean_ci95": list(
                bootstrap_mean_ci(
                    family_mean_deltas,
                    resamples=int(bootstrap_resamples),
                    seed=0,
                )
            ),
            "exact_two_sided_family_sign_test_p": exact_sign_test_pvalue(
                family_mean_deltas
            ),
            "claim_boundary": (
                "Family-level sensitivity gives equal weight to each declared corpus "
                "family. With few institutions it is descriptive, not a population-level "
                "generalization test."
            ),
        },
        "objective": {
            "left_minus_right_sum": sum(objective_deltas),
            "left_minus_right_mean": (
                statistics.fmean(objective_deltas) if objective_deltas else None
            ),
            "left_minus_right_median": (
                statistics.median(objective_deltas) if objective_deltas else None
            ),
            "paired_bootstrap_mean_ci95": list(
                bootstrap_mean_ci(
                    objective_deltas,
                    resamples=int(bootstrap_resamples),
                    seed=0,
                )
            ),
            "exact_two_sided_sign_test_p": exact_sign_test_pvalue(objective_deltas),
            "left_wins": sum(value < 0 for value in objective_deltas),
            "right_wins": sum(value > 0 for value in objective_deltas),
            "ties": sum(value == 0 for value in objective_deltas),
        },
        "solve_wall_time_seconds": {
            "scope": str(wall_time_scope),
            "left_minus_right_median": (
                statistics.median(wall_deltas) if wall_deltas else None
            ),
            "paired_bootstrap_mean_ci95": list(
                bootstrap_mean_ci(
                    wall_deltas,
                    resamples=int(bootstrap_resamples),
                    seed=0,
                )
            ),
            "exact_two_sided_sign_test_p": exact_sign_test_pvalue(wall_deltas),
        },
        "official_component_left_minus_right_seed_pair_sums": (
            component_seed_pair_sums
        ),
        "official_component_left_minus_right_instance_mean_sums": (
            component_instance_mean_sums
        ),
    }


def _oracle_attribution(
    grouped: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    bootstrap_resamples: int,
) -> dict[str, Any]:
    strata: list[dict[str, Any]] = []
    gain_by_compact: dict[bool, dict[tuple[str, int, float], float]] = {}
    for compact in (False, True):
        suffix = "on" if compact else "off"
        control_id = f"control_compact_{suffix}"
        oracle_id = f"oracle_only_compact_{suffix}"
        comparison = _paired_comparison(
            control_id,
            oracle_id,
            grouped.get(control_id, []),
            grouped.get(oracle_id, []),
            bootstrap_resamples=bootstrap_resamples,
        )
        control_by_key, _ = _unique_by_key(grouped.get(control_id, []))
        oracle_by_key, _ = _unique_by_key(grouped.get(oracle_id, []))
        direct_rows: list[dict[str, Any]] = []
        gains: dict[tuple[str, int, float], float] = {}
        for key in sorted(set(control_by_key) & set(oracle_by_key)):
            control = control_by_key[key]
            oracle = oracle_by_key[key]
            if not (_is_effective(control) and _is_effective(oracle)):
                continue
            objective_gain = int(control["official_objective"]) - int(
                oracle["official_objective"]
            )
            telemetry = dict(oracle.get("fixed_time_room_strategy_telemetry") or {})
            raw_improvement = telemetry.get("improvement")
            telemetry_improvement = (
                int(raw_improvement) if isinstance(raw_improvement, (int, float)) else None
            )
            control_telemetry = dict(
                control.get("fixed_time_room_strategy_telemetry") or {}
            )
            control_fingerprint = control_telemetry.get(
                "incumbent_fixed_time_fingerprint"
            )
            oracle_fingerprint = telemetry.get("incumbent_fixed_time_fingerprint")
            pre_finalization_match = bool(
                isinstance(control_fingerprint, str)
                and len(control_fingerprint) == 64
                and control_fingerprint == oracle_fingerprint
            )
            components = {
                name: int(dict(control["official_components"])[name])
                - int(dict(oracle["official_components"])[name])
                for name in COMPONENT_NAMES
            }
            direct_rows.append(
                {
                    "instance_sha256": key[0],
                    "seed": key[1],
                    "official_objective_gain_control_minus_oracle": objective_gain,
                    "oracle_telemetry_improvement": telemetry_improvement,
                    "telemetry_agrees_with_official_pair": (
                        telemetry_improvement == objective_gain
                    ),
                    "official_component_gains": components,
                    "non_room_components_unchanged": bool(
                        components["minimum_working_days"] == 0
                        and components["curriculum_compactness"] == 0
                    ),
                    "control_incumbent_fixed_time_fingerprint": control_fingerprint,
                    "oracle_incumbent_fixed_time_fingerprint": oracle_fingerprint,
                    "pre_finalization_fixed_time_match": bool(
                        pre_finalization_match
                    ),
                    "returned_source": telemetry.get("returned_source"),
                }
            )
            if pre_finalization_match:
                gains[key] = float(objective_gain)
        gain_by_compact[compact] = gains
        comparison["attribution_orientation"] = (
            "control_minus_oracle; positive is direct oracle improvement"
        )
        comparison["direct_telemetry_rows"] = direct_rows
        comparison["telemetry_agreement"] = {
            "checked_pairs": len(direct_rows),
            "agreeing_pairs": sum(
                row["telemetry_agrees_with_official_pair"] for row in direct_rows
            ),
            "all_agree": bool(direct_rows)
            and all(row["telemetry_agrees_with_official_pair"] for row in direct_rows),
            "all_non_room_components_unchanged": bool(direct_rows)
            and all(row["non_room_components_unchanged"] for row in direct_rows),
            "all_pre_finalization_fixed_times_match": bool(direct_rows)
            and all(
                row["pre_finalization_fixed_time_match"] for row in direct_rows
            ),
        }
        strata.append(comparison)

    common = sorted(set(gain_by_compact[False]) & set(gain_by_compact[True]))
    interaction_by_instance: dict[str, list[float]] = defaultdict(list)
    for key in common:
        interaction_by_instance[key[0]].append(
            gain_by_compact[True][key] - gain_by_compact[False][key]
        )
    interaction = [
        statistics.fmean(interaction_by_instance[digest])
        for digest in sorted(interaction_by_instance)
    ]
    return {
        "definition": (
            "Within each compact-arm stratum, compare the matched-reserve control to "
            "oracle_only with identical instance, seed, source, and total budget."
        ),
        "strata": strata,
        "interaction": {
            "orientation": "oracle_gain_with_compact_on_minus_oracle_gain_with_compact_off",
            "effective_complete_factorial_seed_pairs": len(common),
            "effective_complete_factorial_pairs": len(interaction),
            "statistical_unit": (
                "distinct instance hash; repeated seed interactions are averaged"
            ),
            "mean": statistics.fmean(interaction) if interaction else None,
            "median": statistics.median(interaction) if interaction else None,
            "paired_bootstrap_mean_ci95": list(
                bootstrap_mean_ci(
                    interaction,
                    resamples=int(bootstrap_resamples),
                    seed=0,
                )
            ),
            "exact_two_sided_sign_test_p": exact_sign_test_pvalue(interaction),
        },
    }


def _strategy_telemetry_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    effective = [row for row in rows if _is_effective(row)]
    telemetry_rows = [
        dict(row.get("fixed_time_room_strategy_telemetry") or {})
        for row in effective
    ]
    improvements = [
        int(row["improvement"])
        for row in telemetry_rows
        if isinstance(row.get("improvement"), (int, float))
    ]
    elapsed = [
        float(row["elapsed_seconds"])
        for row in telemetry_rows
        if isinstance(row.get("elapsed_seconds"), (int, float))
    ]
    proof_scopes = Counter()
    for row in telemetry_rows:
        oracle = dict(row.get("oracle") or {})
        scope = row.get("proof_scope") or oracle.get("proof_scope")
        if scope:
            proof_scopes[str(scope)] += 1
    return {
        "effective_runs": len(effective),
        "statuses": dict(
            sorted(Counter(str(row.get("status", "missing")) for row in telemetry_rows).items())
        ),
        "returned_sources": dict(
            sorted(
                Counter(
                    str(row.get("returned_source", "missing"))
                    for row in telemetry_rows
                ).items()
            )
        ),
        "accepted_improvement_runs": sum(value > 0 for value in improvements),
        "accepted_improvement_sum": sum(max(0, value) for value in improvements),
        "reported_improvement_sum": sum(improvements),
        "finalization_elapsed_seconds": {
            "observations": len(elapsed),
            "sum": sum(elapsed),
            "median": statistics.median(elapsed) if elapsed else None,
            "iqr": [_quantile(elapsed, 0.25), _quantile(elapsed, 0.75)],
        },
        "proof_scopes": dict(sorted(proof_scopes.items())),
        "strict_total_deadline_pass_runs": sum(
            dict(row.get("deadline") or {}).get("strict_pass") is True
            for row in effective
        ),
        "claim_bearing_replay_valid_runs": sum(
            dict(row.get("fixed_time_room_proof_replay") or {}).get("attempted")
            is True
            and dict(row.get("fixed_time_room_proof_replay") or {}).get("valid")
            is True
            for row in effective
        ),
    }


def _oracle_vs_cp_comparison(
    grouped: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    bootstrap_resamples: int,
) -> dict[str, Any]:
    strata: list[dict[str, Any]] = []
    for compact in (False, True):
        suffix = "on" if compact else "off"
        oracle_id = f"oracle_only_compact_{suffix}"
        cp_id = f"cp_only_compact_{suffix}"
        comparison = _paired_comparison(
            oracle_id,
            cp_id,
            grouped.get(oracle_id, []),
            grouped.get(cp_id, []),
            bootstrap_resamples=bootstrap_resamples,
        )
        oracle_by_key, _ = _unique_by_key(grouped.get(oracle_id, []))
        cp_by_key, _ = _unique_by_key(grouped.get(cp_id, []))
        finalization_by_instance: dict[str, list[float]] = defaultdict(list)
        improvement_by_instance: dict[str, list[float]] = defaultdict(list)
        finalization_seed_pairs = 0
        improvement_seed_pairs = 0
        pre_finalization_matches = 0
        pre_finalization_mismatches = 0
        for key in sorted(set(oracle_by_key) & set(cp_by_key)):
            oracle = oracle_by_key[key]
            cp = cp_by_key[key]
            if not (_is_effective(oracle) and _is_effective(cp)):
                continue
            oracle_meta = dict(
                oracle.get("fixed_time_room_strategy_telemetry") or {}
            )
            cp_meta = dict(cp.get("fixed_time_room_strategy_telemetry") or {})
            oracle_fingerprint = oracle_meta.get(
                "incumbent_fixed_time_fingerprint"
            )
            cp_fingerprint = cp_meta.get("incumbent_fixed_time_fingerprint")
            pre_finalization_match = bool(
                isinstance(oracle_fingerprint, str)
                and len(oracle_fingerprint) == 64
                and oracle_fingerprint == cp_fingerprint
            )
            if pre_finalization_match:
                pre_finalization_matches += 1
            else:
                pre_finalization_mismatches += 1
                continue
            oracle_elapsed = oracle_meta.get("elapsed_seconds")
            cp_elapsed = cp_meta.get("elapsed_seconds")
            if isinstance(oracle_elapsed, (int, float)) and isinstance(
                cp_elapsed, (int, float)
            ):
                finalization_by_instance[key[0]].append(
                    float(oracle_elapsed) - float(cp_elapsed)
                )
                finalization_seed_pairs += 1
            oracle_gain = oracle_meta.get("improvement")
            cp_gain = cp_meta.get("improvement")
            if isinstance(oracle_gain, (int, float)) and isinstance(
                cp_gain, (int, float)
            ):
                improvement_by_instance[key[0]].append(
                    float(oracle_gain) - float(cp_gain)
                )
                improvement_seed_pairs += 1
        finalization_deltas = [
            statistics.fmean(finalization_by_instance[digest])
            for digest in sorted(finalization_by_instance)
        ]
        improvement_deltas = [
            statistics.fmean(improvement_by_instance[digest])
            for digest in sorted(improvement_by_instance)
        ]
        comparison.update(
            {
                "comparison_scope": (
                    "structural fixed-time room oracle versus full-CP fixed-time room dive"
                ),
                "objective_orientation": (
                    "oracle_minus_cp; negative objective favors oracle"
                ),
                "pre_finalization_fingerprint_agreement": {
                    "matching_seed_pairs": int(pre_finalization_matches),
                    "mismatching_or_missing_seed_pairs": int(
                        pre_finalization_mismatches
                    ),
                    "all_match": bool(pre_finalization_matches)
                    and pre_finalization_mismatches == 0,
                },
                "finalization_elapsed_oracle_minus_cp_seconds": {
                    "paired_seed_observations": finalization_seed_pairs,
                    "paired_observations": len(finalization_deltas),
                    "statistical_unit": "distinct instance hash",
                    "median": (
                        statistics.median(finalization_deltas)
                        if finalization_deltas
                        else None
                    ),
                    "paired_bootstrap_mean_ci95": list(
                        bootstrap_mean_ci(
                            finalization_deltas,
                            resamples=int(bootstrap_resamples),
                            seed=0,
                        )
                    ),
                    "exact_two_sided_sign_test_p": exact_sign_test_pvalue(
                        finalization_deltas
                    ),
                },
                "accepted_gain_oracle_minus_cp": {
                    "paired_seed_observations": improvement_seed_pairs,
                    "paired_observations": len(improvement_deltas),
                    "statistical_unit": "distinct instance hash",
                    "sum": sum(improvement_deltas),
                    "median": (
                        statistics.median(improvement_deltas)
                        if improvement_deltas
                        else None
                    ),
                    "paired_bootstrap_mean_ci95": list(
                        bootstrap_mean_ci(
                            improvement_deltas,
                            resamples=int(bootstrap_resamples),
                            seed=0,
                        )
                    ),
                    "exact_two_sided_sign_test_p": exact_sign_test_pvalue(
                        improvement_deltas
                    ),
                },
                "oracle_telemetry": _strategy_telemetry_summary(
                    grouped.get(oracle_id, [])
                ),
                "cp_telemetry": _strategy_telemetry_summary(
                    grouped.get(cp_id, [])
                ),
            }
        )
        strata.append(comparison)
    return {
        "definition": (
            "Within compact-arm strata, compare the structural oracle and the existing "
            "full-CP fixed-time room dive under identical total budgets, instances, and seeds."
        ),
        "strata": strata,
        "claim_boundary": (
            "A fixed-time room comparison does not establish global timetable optimality."
        ),
    }


def _compact_policy_effects(
    grouped: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    bootstrap_resamples: int,
    minimum_effective_instances: int,
) -> dict[str, Any]:
    def partitioned(condition_id: str, partition: str) -> list[Mapping[str, Any]]:
        return [
            row
            for row in grouped.get(condition_id, [])
            if str(row.get("compact_policy_partition")) == partition
        ]

    partition_reports: dict[str, list[dict[str, Any]]] = {}
    for partition in ("held_out", "calibration"):
        comparisons: list[dict[str, Any]] = []
        for strategy in ("control", "oracle_only", "cp_only"):
            off_id = f"{strategy}_compact_off"
            on_id = f"{strategy}_compact_on"
            comparison = _paired_comparison(
                off_id,
                on_id,
                partitioned(off_id, partition),
                partitioned(on_id, partition),
                bootstrap_resamples=bootstrap_resamples,
            )
            off_by_key, _ = _unique_by_key(partitioned(off_id, partition))
            on_by_key, _ = _unique_by_key(partitioned(on_id, partition))
            effective_keys = [
                key
                for key in set(off_by_key) & set(on_by_key)
                if _is_effective(off_by_key[key]) and _is_effective(on_by_key[key])
            ]
            effective_distinct_instances = len({key[0] for key in effective_keys})
            comparison.update(
                {
                    "fixed_time_room_strategy": strategy,
                    "partition": partition,
                    "effect_orientation": (
                        "compact_off_minus_compact_on; positive objective favors compact on"
                    ),
                    "effective_distinct_instances": effective_distinct_instances,
                    "minimum_effective_distinct_instances": int(
                        minimum_effective_instances
                    ),
                    "effective_instance_gate": (
                        "PASS"
                        if effective_distinct_instances
                        >= int(minimum_effective_instances)
                        else "NO-GO"
                    ),
                }
            )
            comparisons.append(comparison)
        partition_reports[partition] = comparisons
    held_out_gate = all(
        row["effective_instance_gate"] == "PASS"
        for row in partition_reports["held_out"]
    )
    return {
        "claim_partition": "held_out",
        "publication_gate": "PASS" if held_out_gate else "NO-GO",
        "held_out": partition_reports["held_out"],
        "calibration_descriptive_only": partition_reports["calibration"],
        "claim_boundary": (
            "Compact-arm effects use held-out content hashes only. Calibration-instance "
            "effects are displayed descriptively and are excluded from the publication gate."
        ),
    }


def summarize_ablation_records(
    records: Sequence[Mapping[str, Any]],
    *,
    minimum_effective_instances: int = 30,
    matrix_complete: bool = True,
    planned_runs: int | None = None,
    source_sha256: str | None = None,
    bootstrap_resamples: int = 10_000,
    aborted_reason: str | None = None,
    source_stable_override: bool | None = None,
    compact_calibration_hashes: Sequence[str] | None = None,
    compact_calibration_evidence_verified: bool = False,
    official_validator_identity_verified: bool = False,
    cpsolver_provenance_verified: bool = False,
    execution_budget_contract_verified: bool = False,
) -> dict[str, Any]:
    if int(bootstrap_resamples) <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    if source_stable_override is True:
        raise ValueError(
            "source_stable_override cannot force a mismatched row set to stable"
        )
    rows = [dict(row) for row in records]
    calibration_hashes = {
        str(value).strip().lower() for value in (compact_calibration_hashes or ())
    }
    malformed_calibration_hashes = sorted(
        digest
        for digest in calibration_hashes
        if not re.fullmatch(r"[0-9a-f]{64}", digest)
    )
    if malformed_calibration_hashes:
        raise ValueError(
            f"Malformed compact calibration hashes: {malformed_calibration_hashes}"
        )
    calibration_declaration_gate = bool(
        compact_calibration_evidence_verified and len(calibration_hashes) == 4
    )
    publication_minimum = max(
        PUBLICATION_MINIMUM_EFFECTIVE_INSTANCES,
        int(minimum_effective_instances),
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("condition_id"))].append(row)

    condition_summaries: list[dict[str, Any]] = []
    all_condition_parity = True
    all_partition_parity = True
    for condition in CONDITIONS:
        condition_rows = grouped.get(condition.condition_id, [])
        effective = [row for row in condition_rows if _is_effective(row)]
        partition_parity = all(
            str(row.get("compact_policy_partition"))
            == (
                "calibration"
                if str(row.get("instance_sha256", "")).lower()
                in calibration_hashes
                else "held_out"
            )
            for row in condition_rows
        )
        all_partition_parity = all_partition_parity and partition_parity
        effective = [
            row
            for row in effective
            if str(row.get("compact_policy_partition"))
            == (
                "calibration"
                if str(row.get("instance_sha256", "")).lower()
                in calibration_hashes
                else "held_out"
            )
        ]
        effective_held_out = [
            row
            for row in effective
            if str(row.get("compact_policy_partition")) == "held_out"
        ]
        effective_calibration = [
            row
            for row in effective
            if str(row.get("compact_policy_partition")) == "calibration"
        ]
        unique_effective_all = {str(row["instance_sha256"]) for row in effective}
        unique_effective_held_out = {
            str(row["instance_sha256"]) for row in effective_held_out
        }
        unique_effective_calibration = {
            str(row["instance_sha256"]) for row in effective_calibration
        }
        exclusions = Counter(
            reason
            for row in condition_rows
            for reason in _effectiveness_reasons(row)
        )
        parity = all(_condition_parity(row) for row in condition_rows)
        all_condition_parity = all_condition_parity and parity
        objectives = [int(row["official_objective"]) for row in effective]
        walls = [
            float(row.get("worker_wall_time_seconds") or row.get("wall_time_seconds") or 0.0)
            for row in effective
        ]
        proof_rows = [
            dict(row.get("fixed_time_room_proof_replay") or {})
            for row in condition_rows
        ]
        proof_attempted = [row for row in proof_rows if row.get("attempted") is True]
        condition_summaries.append(
            {
                "condition_id": condition.condition_id,
                "configuration": condition.to_dict(),
                "configuration_parity": bool(parity),
                "compact_policy_partition_parity": bool(partition_parity),
                "runs": len(condition_rows),
                "effective_runs": len(effective),
                "effective_distinct_instances_all": len(unique_effective_all),
                "effective_distinct_instances": len(unique_effective_held_out),
                "effective_distinct_held_out_instances": len(
                    unique_effective_held_out
                ),
                "effective_distinct_calibration_instances": len(
                    unique_effective_calibration
                ),
                "minimum_effective_distinct_instances": int(
                    minimum_effective_instances
                ),
                "effective_instance_gate": (
                    "PASS"
                    if len(unique_effective_held_out)
                    >= int(minimum_effective_instances)
                    else "NO-GO"
                ),
                "publication_minimum_effective_distinct_instances": int(
                    publication_minimum
                ),
                "publication_effective_instance_gate": (
                    "PASS"
                    if len(unique_effective_held_out) >= int(publication_minimum)
                    else "NO-GO"
                ),
                "exclusion_reasons": dict(sorted(exclusions.items())),
                "official_objective_sum": sum(objectives),
                "official_objective_mean": (
                    statistics.fmean(objectives) if objectives else None
                ),
                "official_objective_median": (
                    statistics.median(objectives) if objectives else None
                ),
                "official_component_sums": (
                    _component_sums(effective)
                    if effective
                    else {name: 0 for name in COMPONENT_NAMES}
                ),
                "held_out_official_component_sums": (
                    _component_sums(effective_held_out)
                    if effective_held_out
                    else {name: 0 for name in COMPONENT_NAMES}
                ),
                "calibration_official_component_sums": (
                    _component_sums(effective_calibration)
                    if effective_calibration
                    else {name: 0 for name in COMPONENT_NAMES}
                ),
                "solve_wall_time_seconds": {
                    "median": statistics.median(walls) if walls else None,
                    "iqr": [_quantile(walls, 0.25), _quantile(walls, 0.75)],
                },
                "proof_replay": {
                    "claim_bearing_attempts": len(proof_attempted),
                    "valid": sum(
                        _claim_bearing_proof_is_complete(row)
                        for row in proof_attempted
                    ),
                    "invalid": sum(
                        not _claim_bearing_proof_is_complete(row)
                        for row in proof_attempted
                    ),
                    "all_claim_bearing_replays_valid": all(
                        _claim_bearing_proof_is_complete(row)
                        for row in proof_attempted
                    )
                    and bool(proof_attempted),
                    "verified_candidate_matches_returned_schedule": sum(
                        row.get("verified_candidate_matches_returned_schedule")
                        is True
                        for row in proof_attempted
                    ),
                },
            }
        )

    pairwise: list[dict[str, Any]] = []
    for left_index, left in enumerate(CONDITIONS):
        for right in CONDITIONS[left_index + 1 :]:
            pairwise.append(
                _paired_comparison(
                    left.condition_id,
                    right.condition_id,
                    grouped.get(left.condition_id, []),
                    grouped.get(right.condition_id, []),
                    bootstrap_resamples=bootstrap_resamples,
                )
            )

    cpsolver_rows = grouped.get("cpsolver_reference", [])
    competitor_comparisons = [
        _paired_comparison(
            condition.condition_id,
            "cpsolver_reference",
            grouped.get(condition.condition_id, []),
            cpsolver_rows,
            bootstrap_resamples=bootstrap_resamples,
            right_effective=_is_cpsolver_effective,
            wall_time_scope="supervisor_process",
        )
        for condition in CONDITIONS
        if cpsolver_rows
    ]

    observed_source_stable = all(
        row.get("source_snapshot_match") is True
        and (source_sha256 is None or row.get("source_snapshot_sha256") == source_sha256)
        for row in rows
    )
    source_stable = bool(
        observed_source_stable and source_stable_override is not False
    )
    produced_solutions = [
        row
        for row in rows
        if dict(row.get("official_validation") or {}).get("solution_produced") is True
    ]
    planora_solutions = [
        row for row in produced_solutions if str(row.get("solver_id")) == SOLVER_PLANORA
    ]
    validator_complete = all(
        dict(row.get("official_validation") or {}).get("validator_completed") is True
        for row in produced_solutions
    )
    internal_agreement = all(
        dict(row.get("official_validation") or {}).get(
            "internal_external_component_agreement"
        )
        is True
        for row in planora_solutions
    )
    planora_rows = [
        row for row in rows if str(row.get("condition_id")) in CONDITION_BY_ID
    ]
    deadline_pass = all(
        dict(row.get("deadline") or {}).get("strict_pass") is True
        for row in planora_rows
    )
    proof_attempts = [
        dict(row.get("fixed_time_room_proof_replay") or {})
        for row in planora_rows
        if dict(row.get("fixed_time_room_proof_replay") or {}).get("attempted")
        is True
    ]
    proof_integrity_pass = all(
        _claim_bearing_proof_is_complete(row)
        for row in proof_attempts
    )
    complete_cell_groups: dict[tuple[str, int, float], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for row in planora_rows:
        complete_cell_groups[_row_key(row)].append(row)
    include_cpsolver_design = any(
        str(row.get("condition_id")) == "cpsolver_reference" for row in rows
    )
    execution_orders = _execution_orders(
        include_cpsolver=include_cpsolver_design
    )
    complete_factorial_cells = 0
    williams_design_parity = True
    malformed_factorial_cells: list[dict[str, Any]] = []
    observed_cell_indices: list[int] = []
    for key, cell_rows in sorted(complete_cell_groups.items()):
        counts = Counter(str(row.get("condition_id")) for row in cell_rows)
        exact_factorial = bool(
            set(counts) == set(CONDITION_BY_ID)
            and all(counts[condition_id] == 1 for condition_id in CONDITION_BY_ID)
        )
        by_condition = {str(row.get("condition_id")): row for row in cell_rows}
        cell_indices = {int(row.get("cell_index", -1)) for row in cell_rows}
        expected_order = (
            execution_orders[next(iter(cell_indices)) % len(execution_orders)]
            if len(cell_indices) == 1 and next(iter(cell_indices)) >= 0
            else ()
        )
        expected_positions = {
            task_id: position for position, task_id in enumerate(expected_order)
        }
        cell_index = next(iter(cell_indices)) if len(cell_indices) == 1 else -1
        if cell_index >= 0:
            observed_cell_indices.append(cell_index)
        position_parity = bool(
            exact_factorial
            and len(expected_order)
            == len(CONDITIONS) + (1 if include_cpsolver_design else 0)
            and all(
                int(by_condition[condition_id].get("condition_execution_position", -1))
                == expected_positions[condition_id]
                and int(by_condition[condition_id].get("williams_sequence_index", -1))
                == cell_index % len(execution_orders)
                for condition_id in CONDITION_BY_ID
            )
        )
        if exact_factorial:
            complete_factorial_cells += 1
        if not position_parity:
            williams_design_parity = False
        if not exact_factorial or not position_parity:
            malformed_factorial_cells.append(
                {
                    "instance_sha256": key[0],
                    "seed": key[1],
                    "time_limit_seconds": key[2],
                    "condition_counts": dict(sorted(counts.items())),
                    "cell_indices": sorted(cell_indices),
                    "exact_factorial": exact_factorial,
                    "williams_position_parity": position_parity,
                }
            )
    factorial_structure_parity = bool(
        complete_cell_groups
        and complete_factorial_cells == len(complete_cell_groups)
        and williams_design_parity
        and len(set(observed_cell_indices)) == len(complete_cell_groups)
    )
    configured_condition_gates_pass = all(
        row["effective_instance_gate"] == "PASS" for row in condition_summaries
    )
    publication_condition_gates_pass = all(
        row["publication_effective_instance_gate"] == "PASS"
        for row in condition_summaries
    )
    compact_policy_report = _compact_policy_effects(
        grouped,
        bootstrap_resamples=bootstrap_resamples,
        minimum_effective_instances=publication_minimum,
    )
    compact_main_effect_gate = compact_policy_report["publication_gate"] == "PASS"
    oracle_attribution_report = _oracle_attribution(
        grouped,
        bootstrap_resamples=bootstrap_resamples,
    )
    oracle_vs_cp_report = _oracle_vs_cp_comparison(
        grouped,
        bootstrap_resamples=bootstrap_resamples,
    )
    pre_finalization_fingerprint_gate = bool(
        all(
            dict(stratum.get("telemetry_agreement") or {}).get(
                "all_pre_finalization_fixed_times_match"
            )
            is True
            for stratum in oracle_attribution_report["strata"]
        )
        and all(
            dict(stratum.get("pre_finalization_fingerprint_agreement") or {}).get(
                "all_match"
            )
            is True
            for stratum in oracle_vs_cp_report["strata"]
        )
    )
    count_matches = planned_runs is None or len(rows) == int(planned_runs)

    proof_coverage_by_condition: list[dict[str, Any]] = []
    for compact in (False, True):
        suffix = "on" if compact else "off"
        condition_id = f"oracle_only_compact_{suffix}"
        effective_claim_rows = [
            row
            for row in grouped.get(condition_id, [])
            if str(row.get("compact_policy_partition")) == "held_out"
            and _is_effective(row)
        ]
        valid_rows = [
            row
            for row in effective_claim_rows
            if _claim_bearing_proof_is_complete(
                dict(row.get("fixed_time_room_proof_replay") or {})
            )
        ]
        distinct = {str(row.get("instance_sha256")) for row in valid_rows}
        complete_run_coverage = len(valid_rows) == len(effective_claim_rows)
        proof_coverage_by_condition.append(
            {
                "condition_id": condition_id,
                "effective_claim_bearing_runs": len(effective_claim_rows),
                "valid_claim_bearing_replay_runs": len(valid_rows),
                "complete_effective_run_coverage": bool(complete_run_coverage),
                "valid_claim_bearing_replay_distinct_instances": len(distinct),
                "minimum_distinct_instances": int(publication_minimum),
                "gate": (
                    "PASS"
                    if complete_run_coverage
                    and len(distinct) >= int(publication_minimum)
                    else "NO-GO"
                ),
            }
        )
    proof_claim_coverage_gate = all(
        row["gate"] == "PASS" for row in proof_coverage_by_condition
    )

    cpsolver_by_key, cpsolver_duplicate_keys = _unique_by_key(cpsolver_rows)
    expected_comparator_keys = set(complete_cell_groups)
    observed_comparator_keys = set(cpsolver_by_key)
    cpsolver_exact_cell_coverage = bool(
        expected_comparator_keys
        and not cpsolver_duplicate_keys
        and observed_comparator_keys == expected_comparator_keys
    )
    cpsolver_effective_held_out = [
        row
        for row in cpsolver_rows
        if str(row.get("compact_policy_partition")) == "held_out"
        and _is_cpsolver_effective(row)
    ]
    cpsolver_effective_distinct = {
        str(row.get("instance_sha256")) for row in cpsolver_effective_held_out
    }
    cpsolver_effective_gate = bool(
        len(cpsolver_effective_distinct) >= int(publication_minimum)
    )
    cpsolver_publication_gate = bool(
        cpsolver_provenance_verified
        and cpsolver_exact_cell_coverage
        and cpsolver_effective_gate
    )
    observed_seeds = {int(row.get("seed", 0)) for row in planora_rows}
    repeated_seed_gate = len(observed_seeds) >= PUBLICATION_MINIMUM_SEEDS
    engineering_smoke_condition_gate = all(
        int(row["effective_distinct_instances_all"]) >= 1
        for row in condition_summaries
    )
    engineering_smoke_pass = bool(
        matrix_complete
        and count_matches
        and engineering_smoke_condition_gate
        and all_condition_parity
        and all_partition_parity
        and factorial_structure_parity
        and source_stable
        and validator_complete
        and internal_agreement
        and deadline_pass
        and proof_integrity_pass
    )
    gate_pass = bool(
        matrix_complete
        and count_matches
        and publication_condition_gates_pass
        and all_condition_parity
        and all_partition_parity
        and calibration_declaration_gate
        and compact_main_effect_gate
        and pre_finalization_fingerprint_gate
        and execution_budget_contract_verified
        and factorial_structure_parity
        and source_stable
        and official_validator_identity_verified
        and validator_complete
        and internal_agreement
        and deadline_pass
        and proof_integrity_pass
        and proof_claim_coverage_gate
        and repeated_seed_gate
        and cpsolver_publication_gate
    )
    corpus_family_by_instance: dict[str, str] = {}
    for row in planora_rows:
        corpus_family_by_instance.setdefault(
            str(row.get("instance_sha256")),
            str(dict(row.get("corpus") or {}).get("family", "unclassified")),
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_config": {
            "bootstrap_resamples": int(bootstrap_resamples),
            "source_stable_override": source_stable_override,
            "compact_calibration_evidence_verified": bool(
                compact_calibration_evidence_verified
            ),
            "official_validator_identity_verified": bool(
                official_validator_identity_verified
            ),
            "cpsolver_provenance_verified": bool(cpsolver_provenance_verified),
            "execution_budget_contract_verified": bool(
                execution_budget_contract_verified
            ),
        },
        "complete": bool(matrix_complete),
        "aborted_reason": aborted_reason,
        "record_count": len(rows),
        "planned_runs": planned_runs,
        "completed_run_count_matches_plan": bool(count_matches),
        "source_snapshot_sha256": source_sha256,
        "source_stable": bool(source_stable),
        "condition_configuration_parity": bool(all_condition_parity),
        "compact_policy_calibration": {
            "declared_instance_sha256": sorted(calibration_hashes),
            "required_hash_count": 4,
            "declared_hash_count": len(calibration_hashes),
            "canonical_file_evidence_verified": bool(
                compact_calibration_evidence_verified
            ),
            "declaration_gate": (
                "PASS" if calibration_declaration_gate else "NO-GO"
            ),
            "row_partition_parity": bool(all_partition_parity),
            "publication_count_partition": "held_out",
        },
        "factorial_cells": {
            "observed": len(complete_cell_groups),
            "required_conditions_per_cell": len(CONDITIONS),
            "complete_condition_cells": int(complete_factorial_cells),
            "exact_structure_parity": bool(factorial_structure_parity),
            "williams_position_parity": bool(williams_design_parity),
            "malformed_cells": malformed_factorial_cells,
        },
        "corpus_families": dict(
            sorted(
                Counter(
                    corpus_family_by_instance.values()
                ).items()
            )
        ),
        "official_validation": {
            "recognized_pinned_validator_identity": bool(
                official_validator_identity_verified
            ),
            "produced_solutions": len(produced_solutions),
            "validator_completed_for_every_produced_solution": bool(
                validator_complete
            ),
            "planora_internal_external_component_agreement": bool(
                internal_agreement
            ),
        },
        "strict_deadline": {
            "all_planora_rows_pass": bool(deadline_pass),
            "failed_rows": sum(
                dict(row.get("deadline") or {}).get("strict_pass") is not True
                for row in planora_rows
            ),
        },
        "proof_replay": {
            "claim_bearing_attempts": len(proof_attempts),
            "all_attempted_claim_bearing_replays_valid": bool(
                proof_integrity_pass
            ),
            "publication_coverage_by_oracle_condition": (
                proof_coverage_by_condition
            ),
            "publication_coverage_gate": bool(proof_claim_coverage_gate),
        },
        "conditions": condition_summaries,
        "paired_condition_comparisons": pairwise,
        "oracle_direct_attribution": oracle_attribution_report,
        "oracle_vs_full_cp_fixed_time": oracle_vs_cp_report,
        "compact_policy_effects": compact_policy_report,
        "cpsolver_reference": {
            "enabled": bool(cpsolver_rows),
            "runs": len(cpsolver_rows),
            "effective_runs": sum(_is_cpsolver_effective(row) for row in cpsolver_rows),
            "effective_distinct_held_out_instances": len(
                cpsolver_effective_distinct
            ),
            "duplicate_cell_keys": cpsolver_duplicate_keys,
            "exact_factorial_cell_coverage": bool(cpsolver_exact_cell_coverage),
            "execution_provenance_verified": bool(cpsolver_provenance_verified),
            "publication_gate": "PASS" if cpsolver_publication_gate else "NO-GO",
            "comparisons": competitor_comparisons,
        },
        "engineering_smoke_gate": {
            "status": "PASS" if engineering_smoke_pass else "NO-GO",
            "claim_scope": (
                "runtime wiring and one-or-more effective instances per condition; "
                "never publication-scale evidence"
            ),
            "requirements": {
                "complete_matrix": bool(matrix_complete and count_matches),
                "one_effective_instance_per_condition": bool(
                    engineering_smoke_condition_gate
                ),
                "configured_condition_threshold": bool(
                    configured_condition_gates_pass
                ),
                "condition_configuration_parity": bool(all_condition_parity),
                "factorial_and_williams_structure": bool(
                    factorial_structure_parity
                ),
                "one_source_snapshot": bool(source_stable),
                "external_validator_for_every_solution": bool(validator_complete),
                "internal_external_component_agreement": bool(internal_agreement),
                "strict_planora_deadline": bool(deadline_pass),
                "attempted_proof_replay_integrity": bool(proof_integrity_pass),
            },
        },
        "publication_gate": {
            "status": "PASS" if gate_pass else "NO-GO",
            "meaning": (
                "evidence-completeness gate only; it is not a superiority result"
            ),
            "minimum_distinct_effective_instances_per_condition": int(
                publication_minimum
            ),
            "configured_minimum_effective_instances": int(
                minimum_effective_instances
            ),
            "observed_distinct_seeds": sorted(observed_seeds),
            "requirements": {
                "complete_matrix": bool(matrix_complete and count_matches),
                "condition_counts": bool(publication_condition_gates_pass),
                "condition_configuration_parity": bool(all_condition_parity),
                "canonical_compact_calibration_files": bool(
                    calibration_declaration_gate
                ),
                "compact_calibration_vs_held_out_partition": bool(
                    all_partition_parity
                ),
                "held_out_compact_main_effect_counts": bool(
                    compact_main_effect_gate
                ),
                "identical_pre_finalization_fixed_time_incumbents": bool(
                    pre_finalization_fingerprint_gate
                ),
                "factorial_and_williams_structure": bool(
                    factorial_structure_parity
                ),
                "one_source_snapshot": bool(source_stable),
                "recognized_pinned_official_validator_identity": bool(
                    official_validator_identity_verified
                ),
                "fixed_single_cpu_equal_budget_contract": bool(
                    execution_budget_contract_verified
                ),
                "official_validator_for_every_solution": bool(validator_complete),
                "internal_external_component_agreement": bool(internal_agreement),
                "strict_planora_deadline": bool(deadline_pass),
                "attempted_proof_replay_integrity": bool(proof_integrity_pass),
                "claim_bearing_proof_replay_coverage": bool(
                    proof_claim_coverage_gate
                ),
                "at_least_two_predeclared_seeds": bool(repeated_seed_gate),
                "immutable_cpsolver_comparator_coverage": bool(
                    cpsolver_publication_gate
                ),
            },
        },
        "claim_boundaries": list(CLAIM_BOUNDARIES),
    }


def _progress_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any],
    aborted_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "complete": False,
        "aborted_reason": aborted_reason,
        "record_count": len(records),
        "planned_runs": int(dict(manifest["planned_runs"])["total"]),
        "source_snapshot_sha256": manifest["planora_source_sha256"],
        "source_stable": all(row.get("source_snapshot_match") is True for row in records),
        "condition_counts": dict(
            sorted(Counter(str(row.get("condition_id")) for row in records).items())
        ),
        "publication_gate": {
            "status": "NO-GO",
            "reason": "matrix_incomplete",
        },
        "claim_boundaries": list(CLAIM_BOUNDARIES),
    }


def _load_results(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ArtifactIntegrityError(f"Result row {index} is not a JSON object")
        expected = row.get("record_payload_sha256")
        if expected != _record_digest(row):
            raise ArtifactIntegrityError(f"Result row {index} payload hash mismatch")
    return rows


def _manifest_publication_evidence(manifest: Mapping[str, Any]) -> dict[str, bool]:
    calibration = dict(manifest.get("compact_policy_calibration") or {})
    validator = dict(manifest.get("validator") or {})
    cpsolver = dict(manifest.get("cpsolver") or {})
    calibration_paths = list(calibration.get("path_evidence") or [])
    calibration_path_hashes = {
        str(row.get("sha256", "")).lower()
        for row in calibration_paths
        if isinstance(row, dict)
    }
    calibration_declared = {
        str(value).lower() for value in calibration.get("instance_sha256", [])
    }
    validator_primary = str(validator.get("primary_sha256", "")).lower()
    validator_expected = str(
        validator.get("expected_primary_sha256", "")
    ).lower()
    calibration_files_current = False
    validator_files_current = False
    cpsolver_files_current = False
    try:
        calibration_files_current = bool(
            len(calibration_paths) == 4
            and all(
                isinstance(row, dict)
                and Path(str(row.get("path", ""))).is_file()
                and Path(str(row["path"])).stat().st_size == int(row.get("bytes", -1))
                and sha256_file(Path(str(row["path"])))
                == str(row.get("sha256", "")).lower()
                and parse_itc2007_ctt(Path(str(row["path"]))).name
                == str(row.get("instance_name", ""))
                for row in calibration_paths
            )
        )
    except (OSError, TypeError, ValueError):
        calibration_files_current = False

    validator_files = list(validator.get("command_files") or [])
    try:
        validator_files_current = bool(
            validator_files
            and all(
                isinstance(row, dict)
                and Path(str(row.get("path", ""))).is_file()
                and Path(str(row["path"])).stat().st_size == int(row.get("bytes", -1))
                and sha256_file(Path(str(row["path"])))
                == str(row.get("sha256", "")).lower()
                for row in validator_files
            )
        )
    except (OSError, TypeError, ValueError):
        validator_files_current = False

    cpsolver_surfaces = {
        "classes_sha256": cpsolver.get("classes_sha256"),
        "source_resources_sha256": cpsolver.get("source_resources_sha256"),
        "libraries_sha256": cpsolver.get("libraries_sha256"),
        "java_executable_sha256": cpsolver.get("java_executable_sha256"),
        "java_xmx_mb": cpsolver.get("java_xmx_mb"),
    }
    deadline_policy = dict(manifest.get("deadline_policy") or {})
    supervision_policy = dict(manifest.get("supervision_policy") or {})
    try:
        java = dict(cpsolver.get("java") or {})
        classes_path = Path(str(cpsolver.get("classes_path", "")))
        source_resources_path = Path(
            str(cpsolver.get("source_resources_path", ""))
        )
        libraries_path = Path(str(cpsolver.get("libraries_path", "")))
        cpsolver_files_current = bool(
            cpsolver.get("enabled") is True
            and bool(cpsolver.get("classes_path"))
            and classes_path.is_dir()
            and sha256_tree(classes_path)
            == str(cpsolver.get("classes_sha256", ""))
            and bool(cpsolver.get("source_resources_path"))
            and source_resources_path.is_dir()
            and sha256_tree(source_resources_path)
            == str(cpsolver.get("source_resources_sha256", ""))
            and bool(cpsolver.get("libraries_path"))
            and libraries_path.is_dir()
            and sha256_tree(libraries_path)
            == str(cpsolver.get("libraries_sha256", ""))
            and Path(str(java.get("path", ""))).is_file()
            and sha256_file(Path(str(java["path"])))
            == str(java.get("sha256", ""))
            == str(cpsolver.get("java_executable_sha256", ""))
            and int(cpsolver.get("java_xmx_mb", 0)) > 0
        )
    except (OSError, TypeError, ValueError):
        cpsolver_files_current = False
    return {
        "execution_budget_contract_verified": bool(
            int(manifest.get("workers", 0)) == 1
            and type(manifest.get("cpu_affinity")) is int
            and float(manifest.get("time_limit_seconds", 0.0)) > 0.0
            and float(deadline_policy.get("maximum_seconds", -1.0)) == 0.0
            and deadline_policy.get("missing_value_is_failure") is True
            and float(supervision_policy.get("grace_seconds", -1.0)) >= 0.0
            and cpsolver.get("enabled") is True
        ),
        "compact_calibration_evidence_verified": bool(
            calibration.get("canonical_file_evidence_verified") is True
            and calibration.get("cardinality_gate") == "PASS"
            and len(calibration_paths) == 4
            and len(calibration_path_hashes) == 4
            and calibration_path_hashes == calibration_declared
            and calibration_files_current
        ),
        "official_validator_identity_verified": bool(
            validator.get("official_identity_verified") is True
            and validator.get("identity_gate") == "PASS"
            and validator_primary == validator_expected
            and validator_primary in OFFICIAL_ITC2007_VALIDATOR_PINS
            and validator.get("recognized_official_identity")
            == OFFICIAL_ITC2007_VALIDATOR_PINS.get(validator_primary)
            and validator_files_current
        ),
        "cpsolver_provenance_verified": bool(
            cpsolver.get("enabled") is True
            and cpsolver.get("provenance_gate") == "PASS"
            and all(cpsolver_surfaces.values())
            and cpsolver.get("execution_surface_sha256")
            == _payload_sha256(cpsolver_surfaces)
            and cpsolver_files_current
        ),
    }


def build_matrix_index(
    output_directory: str | Path,
    *,
    complete: bool,
    source_sha256: str,
) -> dict[str, Any]:
    root = Path(output_directory).resolve()
    artifacts: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "matrix-index.json" or Path(relative).name.startswith("."):
            continue
        artifacts.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    results_path = root / "results.jsonl"
    record_count = (
        sum(1 for line in results_path.read_text(encoding="utf-8").splitlines() if line)
        if results_path.is_file()
        else 0
    )
    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "complete": bool(complete),
        "source_snapshot_sha256": str(source_sha256),
        "record_count": int(record_count),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "artifact_set_sha256": _payload_sha256(artifacts),
        "self_exclusion": "matrix-index.json is excluded to avoid a circular digest",
    }
    return index


def write_matrix_index(
    output_directory: str | Path,
    *,
    complete: bool,
    source_sha256: str,
) -> dict[str, Any]:
    root = Path(output_directory).resolve()
    index = build_matrix_index(
        root,
        complete=complete,
        source_sha256=source_sha256,
    )
    _write_json(root / "matrix-index.json", index)
    return index


def _verify_manifest_execution(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> None:
    if manifest.get("conditions") != [condition.to_dict() for condition in CONDITIONS]:
        raise ArtifactIntegrityError("Manifest factorial conditions changed")
    raw_instances = manifest.get("instances")
    raw_seeds = manifest.get("seeds")
    if not isinstance(raw_instances, list) or not all(
        isinstance(row, dict) for row in raw_instances
    ):
        raise ArtifactIntegrityError("Manifest instances are missing or malformed")
    if not isinstance(raw_seeds, list):
        raise ArtifactIntegrityError("Manifest seeds are missing or malformed")
    instance_rows = [dict(row) for row in raw_instances]
    instance_order = [
        (str(row.get("sha256", "")), str(row.get("path", "")))
        for row in instance_rows
    ]
    if (
        not instance_rows
        or any(not digest for digest, _path in instance_order)
        or len({digest for digest, _path in instance_order}) != len(instance_order)
        or instance_order != sorted(instance_order)
    ):
        raise ArtifactIntegrityError(
            "Manifest instances are not a unique canonical content-hash order"
        )
    try:
        seeds = [int(value) for value in raw_seeds]
    except (TypeError, ValueError) as exc:
        raise ArtifactIntegrityError("Manifest seeds are malformed") from exc
    if not seeds or seeds != sorted(seeds) or len(set(seeds)) != len(seeds):
        raise ArtifactIntegrityError("Manifest seeds are not a unique canonical order")

    design = dict(manifest.get("execution_design") or {})
    cells = design.get("cells")
    if not isinstance(cells, list):
        raise ArtifactIntegrityError("Manifest execution cells are missing")
    include_cpsolver = dict(manifest.get("cpsolver") or {}).get("enabled") is True
    expected_cells = _build_execution_cells(
        instance_rows,
        seeds,
        include_cpsolver=include_cpsolver,
    )
    expected_design = {
        "name": "balanced_williams_first_order_carryover",
        "orders": [
            list(order)
            for order in _execution_orders(include_cpsolver=include_cpsolver)
        ],
        "assignment": (
            "canonical_instance_then_seed_cell_index_modulo_execution_order_count"
        ),
        "cpsolver_policy": (
            "joint_seven_treatment_odd_williams_crossover"
            if include_cpsolver
            else "disabled"
        ),
        "cells": expected_cells,
    }
    if design != expected_design:
        raise ArtifactIntegrityError(
            "Manifest execution design is not the canonical Williams/CPSolver plan"
        )
    expected_planned_runs = {
        "planora": len(expected_cells) * len(CONDITIONS),
        "cpsolver": len(expected_cells) if include_cpsolver else 0,
        "total": len(expected_cells)
        * (len(CONDITIONS) + (1 if include_cpsolver else 0)),
    }
    if manifest.get("planned_runs") != expected_planned_runs:
        raise ArtifactIntegrityError("Manifest execution plan/run count mismatch")

    expected: list[tuple[int, int, str, int, str, int | None]] = []
    execution_index = 0
    for raw_cell in expected_cells:
        for task_id in list(raw_cell.get("execution_order") or []):
            execution_index += 1
            expected.append(
                (
                    execution_index,
                    int(raw_cell["cell_index"]),
                    str(raw_cell["instance_sha256"]),
                    int(raw_cell["seed"]),
                    str(task_id),
                    list(raw_cell.get("execution_order") or []).index(
                        str(task_id)
                    ),
                )
            )
    observed = [
        (
            int(row.get("execution_index", -1)),
            int(row.get("cell_index", -1)),
            str(row.get("instance_sha256")),
            int(row.get("seed", 0)),
            str(row.get("condition_id")),
            (
                int(row["condition_execution_position"])
                if row.get("condition_execution_position") is not None
                else None
            ),
        )
        for row in sorted(rows, key=lambda item: int(item.get("execution_index", -1)))
    ]
    configured_time_limit = float(manifest.get("time_limit_seconds", 0.0))
    configured_cpu = manifest.get("cpu_affinity")
    for row_index, row in enumerate(rows):
        if float(row.get("time_limit_seconds", -1.0)) != configured_time_limit:
            raise ArtifactIntegrityError(
                f"Result row {row_index} uses a different solver time budget"
            )
        if int(row.get("workers", 0)) != 1:
            raise ArtifactIntegrityError(
                f"Result row {row_index} does not use the single-worker contract"
            )
        if row.get("cpu_affinity") != configured_cpu:
            raise ArtifactIntegrityError(
                f"Result row {row_index} uses a different CPU-affinity contract"
            )
    if observed != expected[: len(observed)]:
        raise ArtifactIntegrityError(
            "Result execution order diverges from the manifest Williams plan"
        )
    if len(expected) != expected_planned_runs["total"]:
        raise ArtifactIntegrityError("Canonical execution plan/run count mismatch")


def verify_ablation_artifacts(
    output_directory: str | Path,
    *,
    repo_root: str | Path | None = None,
    check_current_source: bool = False,
) -> dict[str, Any]:
    root = Path(output_directory).resolve()
    index = _read_json(root / "matrix-index.json")
    if index.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise ArtifactIntegrityError("Unexpected matrix index schema")
    raw_artifacts = index.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ArtifactIntegrityError("Matrix index artifacts must be a list")
    expected_paths: set[str] = set()
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise ArtifactIntegrityError("Malformed matrix index artifact row")
        relative = str(raw.get("path", ""))
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ArtifactIntegrityError(f"Unsafe indexed artifact path: {relative!r}")
        if relative in expected_paths:
            raise ArtifactIntegrityError(f"Duplicate indexed artifact path: {relative}")
        expected_paths.add(relative)
        path = (root / candidate).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ArtifactIntegrityError(f"Indexed artifact is missing: {relative}")
        if path.stat().st_size != int(raw.get("bytes", -1)):
            raise ArtifactIntegrityError(f"Indexed artifact size mismatch: {relative}")
        if sha256_file(path) != str(raw.get("sha256")):
            raise ArtifactIntegrityError(f"Indexed artifact hash mismatch: {relative}")
    observed_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.relative_to(root).as_posix() != "matrix-index.json"
        and not path.name.startswith(".")
    }
    if observed_paths != expected_paths:
        raise ArtifactIntegrityError(
            "Matrix artifact set differs from the index: "
            f"missing={sorted(expected_paths - observed_paths)}, "
            f"unexpected={sorted(observed_paths - expected_paths)}"
        )
    if _payload_sha256(raw_artifacts) != index.get("artifact_set_sha256"):
        raise ArtifactIntegrityError("Matrix artifact-set digest mismatch")

    manifest = _read_json(root / "manifest.json")
    summary = _read_json(root / "summary.json")
    rows = _load_results(root / "results.jsonl")
    expected_source = str(manifest.get("planora_source_sha256"))
    calibration_hashes = {
        str(value).lower()
        for value in dict(manifest.get("compact_policy_calibration") or {}).get(
            "instance_sha256", []
        )
    }
    if expected_source != str(index.get("source_snapshot_sha256")):
        raise ArtifactIntegrityError("Manifest/index source snapshot mismatch")
    for row_index, row in enumerate(rows):
        if row.get("source_snapshot_sha256") != expected_source:
            raise ArtifactIntegrityError(
                f"Result row {row_index} uses a different source snapshot"
            )
        if manifest.get("schema_version") == SCHEMA_VERSION:
            expected_partition = (
                "calibration"
                if str(row.get("instance_sha256", "")).lower()
                in calibration_hashes
                else "held_out"
            )
            if row.get("compact_policy_partition") != expected_partition:
                raise ArtifactIntegrityError(
                    f"Result row {row_index} has an incorrect calibration partition"
                )
        validation = dict(row.get("official_validation") or {})
        solution_produced = bool(row.get("solution_sha256"))
        if validation.get("solution_produced") is not solution_produced:
            raise ArtifactIntegrityError(
                f"Result row {row_index} solution/validation evidence disagrees"
            )
        if solution_produced and validation.get("validator_attempted") is not True:
            raise ArtifactIntegrityError(
                f"Result row {row_index} produced a solution without validator invocation"
            )
        artifacts = dict(row.get("artifacts") or {})
        resolved_artifacts: dict[str, Path] = {}
        for artifact_name, raw_artifact in artifacts.items():
            if not isinstance(raw_artifact, dict):
                raise ArtifactIntegrityError(
                    f"Result row {row_index} has malformed {artifact_name} evidence"
                )
            relative = str(raw_artifact.get("path", ""))
            candidate = Path(relative)
            artifact_path = (root / candidate).resolve()
            if (
                not relative
                or candidate.is_absolute()
                or ".." in candidate.parts
                or not artifact_path.is_relative_to(root)
                or not artifact_path.is_file()
                or artifact_path.stat().st_size != int(raw_artifact.get("bytes", -1))
                or sha256_file(artifact_path) != str(raw_artifact.get("sha256", ""))
            ):
                raise ArtifactIntegrityError(
                    f"Result row {row_index} has invalid {artifact_name} evidence"
                )
            resolved_artifacts[str(artifact_name)] = artifact_path
        if solution_produced:
            solution = dict(artifacts.get("solution_path") or {})
            if solution.get("sha256") != row.get("solution_sha256"):
                raise ArtifactIntegrityError(
                    f"Result row {row_index} solution artifact hash disagrees"
                )
        if validation.get("validator_completed") is True and not isinstance(
            artifacts.get("validator_output_path"), dict
        ):
            raise ArtifactIntegrityError(
                f"Result row {row_index} lacks completed-validator output evidence"
            )
        if validation.get("validator_completed") is True:
            try:
                external = parse_itc2007_validator_output(
                    resolved_artifacts["validator_output_path"].read_text(
                        encoding="utf-8"
                    )
                )
            except (KeyError, OSError, ValueError) as exc:
                raise ArtifactIntegrityError(
                    f"Result row {row_index} validator output cannot be replayed"
                ) from exc
            if (
                int(external.hard_violations)
                != int(validation.get("hard_violations", -1))
                or int(external.hard_violations)
                != int(row.get("hard_violations", -1))
                or int(external.total_cost)
                != int(validation.get("official_objective", -1))
                or int(external.total_cost)
                != int(row.get("official_objective", -1))
                or external.soft_score.to_dict() != row.get("official_components")
            ):
                raise ArtifactIntegrityError(
                    f"Result row {row_index} disagrees with replayed validator output"
                )
        if str(row.get("solver_id")) == SOLVER_PLANORA:
            proof = dict(row.get("fixed_time_room_proof_replay") or {})
            worker_path = resolved_artifacts.get("worker_metadata_path")
            if worker_path is None:
                if proof.get("attempted") is True:
                    raise ArtifactIntegrityError(
                        f"Result row {row_index} lacks proof-replay worker evidence"
                    )
            else:
                worker = _read_json(worker_path)
                worker_proof = dict(
                    dict(worker.get("strategy_meta") or {}).get(
                        "fixed_time_room_proof_replay"
                    )
                    or {}
                )
                if proof != worker_proof:
                    raise ArtifactIntegrityError(
                        f"Result row {row_index} proof replay diverges from worker evidence"
                    )
    if len(rows) != int(index.get("record_count", -1)):
        raise ArtifactIntegrityError("Index/result row count mismatch")
    if len(rows) != int(summary.get("record_count", -1)):
        raise ArtifactIntegrityError("Summary/result row count mismatch")
    if bool(summary.get("complete")) != bool(index.get("complete")):
        raise ArtifactIntegrityError("Summary/index completion mismatch")
    if manifest.get("schema_version") == SCHEMA_VERSION:
        expected_conditions = [condition.to_dict() for condition in CONDITIONS]
        if manifest.get("conditions") != expected_conditions:
            raise ArtifactIntegrityError("Manifest factorial conditions changed")
        _verify_manifest_execution(manifest, rows)
        analysis_config = dict(summary.get("analysis_config") or {})
        recomputed = summarize_ablation_records(
            rows,
            minimum_effective_instances=int(
                manifest["minimum_effective_instances_per_condition"]
            ),
            matrix_complete=bool(index.get("complete")),
            planned_runs=int(dict(manifest["planned_runs"])["total"]),
            source_sha256=expected_source,
            bootstrap_resamples=int(
                analysis_config.get("bootstrap_resamples", 10_000)
            ),
            aborted_reason=summary.get("aborted_reason"),
            source_stable_override=analysis_config.get("source_stable_override"),
            compact_calibration_hashes=list(
                dict(manifest.get("compact_policy_calibration") or {}).get(
                    "instance_sha256", []
                )
            ),
            **_manifest_publication_evidence(manifest),
        )
        if recomputed != summary:
            raise ArtifactIntegrityError(
                "Summary does not reproduce from the indexed result rows"
            )
    if check_current_source:
        current_root = Path(repo_root or manifest["repo_root"]).resolve()
        observed_source, _ = execution_source_snapshot(current_root)
        if observed_source != expected_source:
            raise ArtifactIntegrityError(
                "Current Planora source does not match the matrix snapshot"
            )
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "valid": True,
        "complete": bool(index.get("complete")),
        "record_count": len(rows),
        "artifact_count": len(raw_artifacts),
        "source_snapshot_sha256": expected_source,
        "current_source_checked": bool(check_current_source),
    }


def analyze_ablation_directory(
    output_directory: str | Path,
    *,
    write: bool = True,
    bootstrap_resamples: int = 10_000,
) -> dict[str, Any]:
    root = Path(output_directory).resolve()
    if not (root / "matrix-index.json").is_file():
        raise ArtifactIntegrityError(
            "A frozen matrix index is required before analysis can be regenerated"
        )
    verify_ablation_artifacts(root)
    manifest = _read_json(root / "manifest.json")
    rows = _load_results(root / "results.jsonl")
    previous_summary = (
        _read_json(root / "summary.json")
        if (root / "summary.json").is_file()
        else {}
    )
    planned = int(dict(manifest["planned_runs"])["total"])
    _verify_manifest_execution(manifest, rows)
    previous_analysis = dict(previous_summary.get("analysis_config") or {})
    previous_abort = previous_summary.get("aborted_reason")
    matrix_complete = bool(len(rows) == planned and not previous_abort)
    summary = summarize_ablation_records(
        rows,
        minimum_effective_instances=int(
            manifest["minimum_effective_instances_per_condition"]
        ),
        matrix_complete=matrix_complete,
        planned_runs=planned,
        source_sha256=str(manifest["planora_source_sha256"]),
        bootstrap_resamples=bootstrap_resamples,
        aborted_reason=previous_abort,
        source_stable_override=previous_analysis.get("source_stable_override"),
        compact_calibration_hashes=list(
            dict(manifest.get("compact_policy_calibration") or {}).get(
                "instance_sha256", []
            )
        ),
        **_manifest_publication_evidence(manifest),
    )
    if write:
        _write_json(root / "summary.json", summary)
        write_matrix_index(
            root,
            complete=bool(summary["complete"]),
            source_sha256=str(manifest["planora_source_sha256"]),
        )
    return summary


def run_ablation_matrix(
    *,
    repo_root: str | Path,
    output_directory: str | Path,
    instances: Sequence[str | Path],
    seeds: Sequence[int],
    time_limit_seconds: float,
    validator_command: Sequence[str | Path],
    python_command: str | Path = sys.executable,
    workers: int = 1,
    cpu: int | None = None,
    supervision_grace_seconds: float = 30.0,
    include_cpsolver: bool = False,
    cpsolver_root: str | Path | None = None,
    classes_path: str | Path | None = None,
    java_command: str | Path = "java",
    java_xmx_mb: int = 1024,
    provenance_json: str | Path | None = None,
    compact_calibration_instances: Sequence[str | Path] | None = None,
    compact_calibration_sha256: Sequence[str] | None = None,
    minimum_effective_instances: int = 30,
    deadline_overrun_tolerance_seconds: float = 0.0,
    itc2007_course_symmetry: bool = False,
    itc2007_adaptive_seeding: bool = True,
    official_validator_sha256: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(repo_root).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise FileExistsError(
            f"Ablation output directory already exists; choose a fresh path: {output}"
        )
    manifest = build_ablation_manifest(
        repo_root=root,
        instances=instances,
        seeds=seeds,
        time_limit_seconds=time_limit_seconds,
        validator_command=validator_command,
        workers=workers,
        cpu=cpu,
        include_cpsolver=include_cpsolver,
        cpsolver_root=cpsolver_root,
        classes_path=classes_path,
        java_command=java_command,
        java_xmx_mb=java_xmx_mb,
        provenance_json=provenance_json,
        compact_calibration_instances=compact_calibration_instances,
        compact_calibration_sha256=compact_calibration_sha256,
        minimum_effective_instances=minimum_effective_instances,
        deadline_overrun_tolerance_seconds=deadline_overrun_tolerance_seconds,
        supervision_grace_seconds=supervision_grace_seconds,
        itc2007_course_symmetry=itc2007_course_symmetry,
        itc2007_adaptive_seeding=itc2007_adaptive_seeding,
        official_validator_sha256=official_validator_sha256,
    )
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "manifest.json", manifest)
    results_path = output / "results.jsonl"
    results_path.write_text("", encoding="utf-8")
    _write_json(output / "summary.json", _progress_summary([], manifest=manifest))

    instances_by_hash = {
        str(row["sha256"]): dict(row) for row in manifest["instances"]
    }
    source_sha256 = str(manifest["planora_source_sha256"])
    records: list[dict[str, Any]] = []
    execution_index = 0
    try:
        for cell in dict(manifest["execution_design"])["cells"]:
            instance = instances_by_hash[str(cell["instance_sha256"])]
            instance_path = Path(str(instance["path"]))
            corpus = dict(instance["corpus"])
            compact_policy_partition = str(instance["compact_policy_partition"])
            execution_order = list(cell["execution_order"])
            for task_id in execution_order:
                _assert_source_snapshot(
                    root,
                    source_sha256,
                    phase=f"before cell {cell['cell_index']} task {task_id}",
                )
                _assert_instance_unchanged(instance, phase="before run")
                _assert_validator_unchanged(manifest, phase="before run")
                _assert_calibration_unchanged(manifest, phase="before run")
                if task_id == "cpsolver_reference":
                    _assert_cpsolver_unchanged(manifest, phase="before run")
                execution_index += 1
                instance_directory = (
                    output
                    / "runs"
                    / (
                        f"{int(cell['cell_index']):04d}-"
                        f"{_safe_slug(str(cell['instance_id']))}-"
                        f"{str(cell['instance_sha256'])[:12]}"
                    )
                    / f"seed-{int(cell['seed'])}"
                )
                run_directory = (
                    instance_directory
                    / f"execution-{execution_index:06d}-{_safe_slug(str(task_id))}"
                )
                if task_id == "cpsolver_reference":
                    raw = run_cpsolver_case(
                        validator_command=validator_command,
                        java_command=java_command,
                        cpsolver_root=Path(str(cpsolver_root)),
                        classes_path=Path(str(classes_path)),
                        instance_path=instance_path,
                        run_directory=run_directory,
                        seed=int(cell["seed"]),
                        time_limit_seconds=float(time_limit_seconds),
                        cpu=cpu,
                        supervision_grace_seconds=float(supervision_grace_seconds),
                        execution_index=int(execution_index),
                        java_xmx_mb=int(java_xmx_mb),
                    )
                else:
                    condition = CONDITION_BY_ID[str(task_id)]
                    raw = run_planora_case(
                        repo_root=root,
                        python_command=python_command,
                        validator_command=validator_command,
                        instance_path=instance_path,
                        run_directory=run_directory,
                        seed=int(cell["seed"]),
                        time_limit_seconds=float(time_limit_seconds),
                        workers=int(workers),
                        strategy="research_adaptive",
                        itc2007_course_symmetry=bool(itc2007_course_symmetry),
                        itc2007_adaptive_seeding=bool(itc2007_adaptive_seeding),
                        itc2007_compact_adaptive_arms=bool(
                            condition.compact_adaptive_arms
                        ),
                        itc2007_fixed_time_room_dive=True,
                        itc2007_fixed_time_room_strategy=(
                            condition.fixed_time_room_strategy
                        ),
                        cpu=cpu,
                        supervision_grace_seconds=float(supervision_grace_seconds),
                        execution_index=int(execution_index),
                    )

                observed_source, _ = execution_source_snapshot(root)
                source_match = observed_source == source_sha256
                _assert_instance_unchanged(instance, phase="after run")
                _assert_validator_unchanged(manifest, phase="after run")
                _assert_calibration_unchanged(manifest, phase="after run")
                if task_id == "cpsolver_reference":
                    _assert_cpsolver_unchanged(manifest, phase="after run")
                if task_id == "cpsolver_reference":
                    record = _normalize_cpsolver_record(
                        raw,
                        cell=cell,
                        execution_index=execution_index,
                        source_sha256=source_sha256,
                        source_match=source_match,
                        corpus=corpus,
                        compact_policy_partition=compact_policy_partition,
                        output_directory=output,
                    )
                else:
                    condition = CONDITION_BY_ID[str(task_id)]
                    record = _normalize_planora_record(
                        raw,
                        condition=condition,
                        cell=cell,
                        execution_index=execution_index,
                        execution_position=execution_order.index(str(task_id)),
                        source_sha256=source_sha256,
                        source_match=source_match,
                        corpus=corpus,
                        compact_policy_partition=compact_policy_partition,
                        output_directory=output,
                        deadline_overrun_tolerance_seconds=(
                            deadline_overrun_tolerance_seconds
                        ),
                    )
                records.append(record)
                _write_jsonl_row(results_path, record)
                _write_json(
                    output / "summary.json",
                    _progress_summary(records, manifest=manifest),
                )
                if not source_match:
                    raise SourceSnapshotDrift(
                        "Planora source changed while a benchmark worker was running: "
                        f"expected={source_sha256}, observed={observed_source}"
                    )

        summary = summarize_ablation_records(
            records,
            minimum_effective_instances=minimum_effective_instances,
            matrix_complete=True,
            planned_runs=int(dict(manifest["planned_runs"])["total"]),
            source_sha256=source_sha256,
            compact_calibration_hashes=list(
                dict(manifest["compact_policy_calibration"])["instance_sha256"]
            ),
            **_manifest_publication_evidence(manifest),
        )
        _assert_source_snapshot(root, source_sha256, phase="during final analysis")
        _assert_validator_unchanged(manifest, phase="during final analysis")
        _assert_calibration_unchanged(manifest, phase="during final analysis")
        _assert_cpsolver_unchanged(manifest, phase="during final analysis")
        _write_json(output / "summary.json", summary)
        write_matrix_index(output, complete=True, source_sha256=source_sha256)
        verify_ablation_artifacts(output)
        return records, summary
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        source_stable_override = False if isinstance(exc, SourceSnapshotDrift) else None
        summary = summarize_ablation_records(
            records,
            minimum_effective_instances=minimum_effective_instances,
            matrix_complete=False,
            planned_runs=int(dict(manifest["planned_runs"])["total"]),
            source_sha256=source_sha256,
            aborted_reason=reason,
            source_stable_override=source_stable_override,
            compact_calibration_hashes=list(
                dict(manifest["compact_policy_calibration"])["instance_sha256"]
            ),
            **_manifest_publication_evidence(manifest),
        )
        _write_json(output / "summary.json", summary)
        write_matrix_index(output, complete=False, source_sha256=source_sha256)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and verify the current-source ITC/CB-CTT 3x2 ablation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--instances", nargs="+", required=True)
    run.add_argument("--seeds", nargs="+", type=int, required=True)
    run.add_argument("--time-limit-seconds", type=float, required=True)
    run.add_argument("--validator-command", nargs="+", required=True)
    run.add_argument(
        "--official-validator-sha256",
        help=(
            "Explicitly pin the recognized official validator binary/archive. "
            "Without this pin, engineering smokes may run but publication stays NO-GO."
        ),
    )
    run.add_argument("--output-directory", required=True)
    run.add_argument("--repo-root", default=str(Path.cwd()))
    run.add_argument("--python-command", default=sys.executable)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--cpu", type=int)
    run.add_argument("--supervision-grace-seconds", type=float, default=30.0)
    run.add_argument("--include-cpsolver", action="store_true")
    run.add_argument("--cpsolver-root")
    run.add_argument("--classes")
    run.add_argument("--java-command", default="java")
    run.add_argument("--java-xmx-mb", type=int, default=1024)
    run.add_argument("--provenance-json")
    run.add_argument("--compact-calibration-instances", nargs="*", default=[])
    run.add_argument("--compact-calibration-sha256", nargs="*", default=[])
    run.add_argument("--minimum-effective-instances", type=int, default=30)
    run.add_argument("--deadline-overrun-tolerance-seconds", type=float, default=0.0)
    run.add_argument(
        "--itc2007-course-symmetry", choices=("on", "off"), default="off"
    )
    run.add_argument(
        "--itc2007-adaptive-seeding", choices=("on", "off"), default="on"
    )

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--output-directory", required=True)
    analyze.add_argument("--bootstrap-resamples", type=int, default=10_000)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--output-directory", required=True)
    verify.add_argument("--repo-root")
    verify.add_argument("--check-current-source", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        _records, summary = run_ablation_matrix(
            repo_root=args.repo_root,
            output_directory=args.output_directory,
            instances=args.instances,
            seeds=args.seeds,
            time_limit_seconds=args.time_limit_seconds,
            validator_command=args.validator_command,
            official_validator_sha256=args.official_validator_sha256,
            python_command=args.python_command,
            workers=args.workers,
            cpu=args.cpu,
            supervision_grace_seconds=args.supervision_grace_seconds,
            include_cpsolver=args.include_cpsolver,
            cpsolver_root=args.cpsolver_root,
            classes_path=args.classes,
            java_command=args.java_command,
            java_xmx_mb=args.java_xmx_mb,
            provenance_json=args.provenance_json,
            compact_calibration_instances=args.compact_calibration_instances,
            compact_calibration_sha256=args.compact_calibration_sha256,
            minimum_effective_instances=args.minimum_effective_instances,
            deadline_overrun_tolerance_seconds=(
                args.deadline_overrun_tolerance_seconds
            ),
            itc2007_course_symmetry=args.itc2007_course_symmetry == "on",
            itc2007_adaptive_seeding=args.itc2007_adaptive_seeding == "on",
        )
        print(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if args.command == "analyze":
        summary = analyze_ablation_directory(
            args.output_directory,
            bootstrap_resamples=args.bootstrap_resamples,
        )
        print(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False))
        return 0
    verification = verify_ablation_artifacts(
        args.output_directory,
        repo_root=args.repo_root,
        check_current_source=args.check_current_source,
    )
    print(json.dumps(verification, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
