"""Claim-grade Docker resource-controller primitives for ITC-2019 runs.

This module deliberately does not know how any solver works.  It defines the
common, immutable external resource contract, constructs deterministic Docker
commands, and validates already-captured Docker/cgroup/supervisor evidence.
Actual command execution is an injectable boundary so unit tests never need a
Docker daemon.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence


RESOURCE_PROFILE_SCHEMA = "planora.itc2019.resource-profile.v1"
CAPABILITY_EVIDENCE_SCHEMA = "planora.itc2019.docker-capabilities.v1"
RESOURCE_EVIDENCE_SCHEMA = "planora.itc2019.resource-evidence.v1"
DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA = (
    "planora.itc2019.descriptive-resource-evidence.v1"
)
CONTROLLER_LABEL = "planora.itc2019.resource-controller"
CONTROLLER_VERSION = "docker-cgroup-v2-phase3"
TRUSTED_SUPERVISOR_ENTRYPOINT = "/opt/planora/itc2019-container-supervisor"
DEFAULT_CAPABILITY_MAX_AGE_SECONDS = 300.0
OUTER_CLEANUP_ALLOWANCE_SECONDS = 15.0
SUPERVISOR_EVIDENCE_RELATIVE_PATH = "resource-controller-supervisor.json"
CGROUP_EVIDENCE_RELATIVE_PATH = "resource-controller-cgroup.json"

_DIGEST_REFERENCE = re.compile(
    r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64})\Z"
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_CGROUP_REQUIRED_MEMORY_EVENTS = frozenset(
    {"low", "high", "max", "oom", "oom_kill", "oom_group_kill"}
)
_CGROUP_REQUIRED_CPU_STAT = frozenset(
    {
        "usage_usec",
        "user_usec",
        "system_usec",
        "nr_periods",
        "nr_throttled",
        "throttled_usec",
    }
)
_CGROUP_REQUIRED_SWAP_EVENTS = frozenset({"high", "max", "fail"})
_RESOURCE_EVIDENCE_PARSE_CAPABILITY = object()


class ResourceControllerError(ValueError):
    """Raised when a claim-grade resource contract cannot be proven."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def resource_evidence_sha256(value: Mapping[str, Any]) -> str:
    """Hash either resource-evidence schema using the shared canonical form."""

    if not isinstance(value, Mapping):
        raise ResourceControllerError("resource evidence must be an object")
    schema = value.get("schema")
    if schema not in {
        RESOURCE_EVIDENCE_SCHEMA,
        DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    }:
        raise ResourceControllerError("unsupported resource evidence schema")
    return _canonical_sha256(value)


def _require_plain_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResourceControllerError(f"{field_name} must be an integer")
    if value < minimum:
        raise ResourceControllerError(f"{field_name} must be >= {minimum}")
    return value


def _require_finite_number(
    value: Any, field_name: str, *, minimum: float, inclusive: bool
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceControllerError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ResourceControllerError(f"{field_name} must be a finite number")
    valid = result >= minimum if inclusive else result > minimum
    if not valid:
        comparator = ">=" if inclusive else ">"
        raise ResourceControllerError(f"{field_name} must be {comparator} {minimum}")
    return result


def _canonical_cpuset(value: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ResourceControllerError("cpuset_cpus must be a non-empty CPU-set string")
    cpus: set[int] = set()
    for part in value.split(","):
        if not part:
            raise ResourceControllerError("cpuset_cpus contains an empty segment")
        bounds = part.split("-")
        if len(bounds) == 1:
            if not bounds[0].isdigit():
                raise ResourceControllerError("cpuset_cpus contains a non-numeric CPU")
            start = end = int(bounds[0])
        elif len(bounds) == 2 and all(bound.isdigit() for bound in bounds):
            start, end = (int(bound) for bound in bounds)
            if start >= end:
                raise ResourceControllerError(
                    "cpuset_cpus ranges must be strictly increasing"
                )
        else:
            raise ResourceControllerError("cpuset_cpus contains a malformed range")
        if end > 1_048_575 or end - start > 4_095:
            raise ResourceControllerError("cpuset_cpus exceeds the supported bound")
        for cpu in range(start, end + 1):
            if cpu in cpus:
                raise ResourceControllerError("cpuset_cpus contains duplicate CPUs")
            cpus.add(cpu)
        if len(cpus) > 4_096:
            raise ResourceControllerError("cpuset_cpus contains too many CPUs")

    ordered = sorted(cpus)
    ranges: list[str] = []
    start = previous = ordered[0]
    for cpu in ordered[1:]:
        if cpu == previous + 1:
            previous = cpu
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = cpu
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _is_absolute_host_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _validated_host_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or not _is_absolute_host_path(value):
        raise ResourceControllerError(f"{field_name} must be an absolute host path")
    if any(character in value for character in ("\x00", "\n", "\r", ",")):
        raise ResourceControllerError(f"{field_name} contains unsupported characters")
    return value


def _validated_container_path(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in ("\x00", "\n", "\r", ","))
    ):
        raise ResourceControllerError(f"{field_name} is malformed")
    path = PurePosixPath(value)
    if not path.is_absolute() or value == "/" or ".." in path.parts:
        raise ResourceControllerError(f"{field_name} must be an absolute non-root path")
    return str(path)


def _paths_overlap(left: str, right: str) -> bool:
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def _normalize_mounts(
    mounts: Sequence[Sequence[str]], field_name: str
) -> tuple[tuple[str, str], ...]:
    if isinstance(mounts, (str, bytes)):
        raise ResourceControllerError(f"{field_name} must be a sequence of path pairs")
    normalized: list[tuple[str, str]] = []
    for index, mount in enumerate(mounts):
        if isinstance(mount, (str, bytes)) or len(mount) != 2:
            raise ResourceControllerError(f"{field_name}[{index}] must be a path pair")
        source = _validated_host_path(mount[0], f"{field_name}[{index}].source")
        destination = _validated_container_path(
            mount[1], f"{field_name}[{index}].destination"
        )
        normalized.append((source, destination))
    normalized.sort(key=lambda item: (item[1], item[0]))
    if len({destination for _, destination in normalized}) != len(normalized):
        raise ResourceControllerError(f"{field_name} contains duplicate destinations")
    return tuple(normalized)


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResourceControllerError(f"{field_name} must be an object")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ResourceControllerError(f"{field_name} must be a boolean")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResourceControllerError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    """One externally enforced resource profile shared by every solver."""

    wall_time_seconds: float
    artifact_grace_seconds: float
    memory_bytes: int
    memory_swap_bytes: int
    cpuset_cpus: str
    cpu_period_us: int = 100_000
    cpu_quota_us: int = 100_000
    pids_limit: int = 256
    schema: str = RESOURCE_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RESOURCE_PROFILE_SCHEMA:
            raise ResourceControllerError("unsupported resource profile schema")
        object.__setattr__(
            self,
            "wall_time_seconds",
            _require_finite_number(
                self.wall_time_seconds,
                "wall_time_seconds",
                minimum=0.0,
                inclusive=False,
            ),
        )
        object.__setattr__(
            self,
            "artifact_grace_seconds",
            _require_finite_number(
                self.artifact_grace_seconds,
                "artifact_grace_seconds",
                minimum=0.0,
                inclusive=True,
            ),
        )
        _require_plain_int(self.memory_bytes, "memory_bytes", minimum=1)
        _require_plain_int(self.memory_swap_bytes, "memory_swap_bytes", minimum=1)
        if self.memory_swap_bytes < self.memory_bytes:
            raise ResourceControllerError(
                "memory_swap_bytes is Docker's combined memory+swap ceiling and "
                "must be >= memory_bytes"
            )
        _require_plain_int(self.cpu_period_us, "cpu_period_us", minimum=1_000)
        if self.cpu_period_us > 1_000_000:
            raise ResourceControllerError("cpu_period_us must be <= 1000000")
        _require_plain_int(self.cpu_quota_us, "cpu_quota_us", minimum=1_000)
        _require_plain_int(self.pids_limit, "pids_limit", minimum=1)
        object.__setattr__(self, "cpuset_cpus", _canonical_cpuset(self.cpuset_cpus))

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "wall_time_seconds": self.wall_time_seconds,
            "artifact_grace_seconds": self.artifact_grace_seconds,
            "memory_bytes": self.memory_bytes,
            "memory_swap_bytes": self.memory_swap_bytes,
            "cpuset_cpus": self.cpuset_cpus,
            "cpu_period_us": self.cpu_period_us,
            "cpu_quota_us": self.cpu_quota_us,
            "pids_limit": self.pids_limit,
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_canonical_dict())


@dataclass(frozen=True, slots=True)
class SolverInvocation:
    """Immutable solver command plus its permitted bind-mount surface.

    ``argv`` is always the solver command.  The container entrypoint is owned by
    the controller and cannot be supplied by an invocation.
    """

    run_id: str
    solver: str
    image: str
    argv: tuple[str, ...]
    host_run_directory: str
    input_mounts: tuple[tuple[str, str], ...] = ()
    binary_mounts: tuple[tuple[str, str], ...] = ()
    container_run_directory: str = "/run/planora"
    artifact_relative_path: str = "solution.xml"
    capability_snapshot_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _IDENTIFIER.fullmatch(self.run_id):
            raise ResourceControllerError("run_id contains unsupported characters")
        if not isinstance(self.solver, str) or not _IDENTIFIER.fullmatch(self.solver):
            raise ResourceControllerError("solver contains unsupported characters")
        if not isinstance(self.image, str) or not _DIGEST_REFERENCE.fullmatch(
            self.image
        ):
            raise ResourceControllerError(
                "image must be an immutable sha256 image ID or digest reference"
            )
        if isinstance(self.argv, (str, bytes)):
            raise ResourceControllerError("argv must be a sequence of arguments")
        argv = tuple(self.argv)
        if not argv or any(
            not isinstance(argument, str)
            or not argument
            or any(character in argument for character in ("\x00", "\n", "\r"))
            for argument in argv
        ):
            raise ResourceControllerError("argv must contain safe non-empty strings")
        object.__setattr__(self, "argv", argv)
        artifact_path = PurePosixPath(self.artifact_relative_path)
        if (
            not isinstance(self.artifact_relative_path, str)
            or not self.artifact_relative_path
            or artifact_path.is_absolute()
            or ".." in artifact_path.parts
            or self.artifact_relative_path in {".", ".."}
            or any(
                character in self.artifact_relative_path
                for character in ("\x00", "\n", "\r", "\\")
            )
        ):
            raise ResourceControllerError(
                "artifact_relative_path must be a safe POSIX-relative path"
            )
        object.__setattr__(self, "artifact_relative_path", str(artifact_path))
        if self.capability_snapshot_sha256 is not None and not _HEX_SHA256.fullmatch(
            self.capability_snapshot_sha256
        ):
            raise ResourceControllerError(
                "capability_snapshot_sha256 must be a SHA-256 digest"
            )
        object.__setattr__(
            self,
            "host_run_directory",
            _validated_host_path(self.host_run_directory, "host_run_directory"),
        )
        object.__setattr__(
            self,
            "container_run_directory",
            _validated_container_path(
                self.container_run_directory, "container_run_directory"
            ),
        )
        inputs = _normalize_mounts(self.input_mounts, "input_mounts")
        binaries = _normalize_mounts(self.binary_mounts, "binary_mounts")
        object.__setattr__(self, "input_mounts", inputs)
        object.__setattr__(self, "binary_mounts", binaries)

        all_read_only = inputs + binaries
        destinations = [destination for _, destination in all_read_only]
        if len(set(destinations)) != len(destinations):
            raise ResourceControllerError(
                "input and binary mounts contain duplicate destinations"
            )
        for index, destination in enumerate(destinations):
            if _paths_overlap(destination, self.container_run_directory):
                raise ResourceControllerError(
                    "read-only mounts must not overlap the writable run directory"
                )
            for other in destinations[index + 1 :]:
                if _paths_overlap(destination, other):
                    raise ResourceControllerError(
                        "read-only mount destinations must not overlap"
                    )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "solver": self.solver,
            "image": self.image,
            "argv": list(self.argv),
            "host_run_directory": self.host_run_directory,
            "input_mounts": [list(mount) for mount in self.input_mounts],
            "binary_mounts": [list(mount) for mount in self.binary_mounts],
            "container_run_directory": self.container_run_directory,
            "artifact_relative_path": self.artifact_relative_path,
            "capability_snapshot_sha256": self.capability_snapshot_sha256,
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_canonical_dict())


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    """Race-checked host view of the committed output artifact."""

    canonical_path: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    file_identity: str


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    """Host-observed lifecycle facts from one Docker execution attempt."""

    run_id: str
    container_id: str
    image_id: str
    host_started_monotonic_ns: int
    host_solver_deadline_monotonic_ns: int
    host_artifact_deadline_monotonic_ns: int
    host_finished_monotonic_ns: int
    host_started_wall_ns: int
    host_artifact_deadline_wall_ns: int
    attach_returncode: int
    timed_out: bool
    cleanup_complete: bool
    residual_processes: int


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """One host-observed cleanup command or evidence-processing outcome."""

    operation: str
    returncode: int | None
    error: str | None
    absence_verified: bool = False


@dataclass(frozen=True, slots=True)
class _CleanupResult:
    final_inspect: Mapping[str, Any] | None
    cleanup_complete: bool
    residual_processes: int
    outcomes: tuple[CleanupOutcome, ...]


@dataclass(frozen=True, slots=True)
class ResourceEvidence:
    """Normalized direct evidence admitted only by the authoritative parser."""

    run_id: str
    container_id: str
    container_name: str
    image_reference: str
    image_id: str
    profile_sha256: str
    invocation_sha256: str
    invocation: tuple[tuple[str, Any], ...]
    execution: tuple[tuple[str, Any], ...]
    capability_sha256: str
    capability_snapshot_sha256: str
    capability_snapshot: tuple[tuple[str, Any], ...]
    supervisor_sha256: str
    daemon_id: str
    docker_context: str
    cgroup_path: str
    cgroup_identity: str
    post_exit_cgroup_sampled_monotonic_ns: int
    exit_code: int
    elapsed_monotonic_ns: int
    artifact_committed: bool
    artifact_sha256: str | None
    artifact_relative_path: str | None
    artifact_size_bytes: int | None
    artifact_file_identity: str | None
    memory_current_bytes: int
    memory_peak_bytes: int
    memory_swap_current_bytes: int
    memory_swap_peak_bytes: int
    memory_events: tuple[tuple[str, int], ...]
    memory_swap_events: tuple[tuple[str, int], ...]
    cpu_stat: tuple[tuple[str, int], ...]
    pids_current: int
    pids_peak: int
    effective_memory_max: int
    effective_memory_swap_max: int
    effective_cpu_max: str
    effective_cpuset_cpus: str
    effective_pids_max: int
    deadline_exceeded: bool
    cleanup_complete: bool
    residual_processes: int
    cleanup_outcomes: tuple[tuple[str, int | None, str | None, bool], ...]
    claim_grade_ready: bool = False
    schema: str = RESOURCE_EVIDENCE_SCHEMA
    _parse_capability: InitVar[object | None] = None

    def __post_init__(self, _parse_capability: object | None) -> None:
        if _parse_capability is not _RESOURCE_EVIDENCE_PARSE_CAPABILITY:
            raise ResourceControllerError(
                "resource evidence lacks authoritative parse provenance"
            )
        if self.schema != RESOURCE_EVIDENCE_SCHEMA:
            raise ResourceControllerError("unsupported resource evidence schema")
        if not _IDENTIFIER.fullmatch(self.run_id):
            raise ResourceControllerError("resource evidence has an invalid run_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.container_id):
            raise ResourceControllerError("container_id must be a full Docker ID")
        if not self.container_name or any(
            char.isspace() for char in self.container_name
        ):
            raise ResourceControllerError("container_name is malformed")
        if not _DIGEST_REFERENCE.fullmatch(self.image_reference):
            raise ResourceControllerError("image_reference is not immutable")
        if not _IMAGE_ID.fullmatch(self.image_id):
            raise ResourceControllerError("image_id is malformed")
        for field_name in (
            "profile_sha256",
            "invocation_sha256",
            "capability_sha256",
            "supervisor_sha256",
            "cgroup_identity",
        ):
            if not _HEX_SHA256.fullmatch(getattr(self, field_name)):
                raise ResourceControllerError(f"{field_name} is malformed")
        if not _HEX_SHA256.fullmatch(self.daemon_id):
            raise ResourceControllerError("daemon_id is malformed")
        _require_string(self.docker_context, "docker_context")
        if not PurePosixPath(self.cgroup_path).is_absolute():
            raise ResourceControllerError("cgroup_path must be absolute")
        _require_plain_int(self.exit_code, "exit_code", minimum=0)
        for field_name in (
            "elapsed_monotonic_ns",
            "post_exit_cgroup_sampled_monotonic_ns",
            "memory_current_bytes",
            "memory_peak_bytes",
            "memory_swap_current_bytes",
            "memory_swap_peak_bytes",
            "pids_current",
            "pids_peak",
            "residual_processes",
            "effective_memory_max",
            "effective_memory_swap_max",
            "effective_pids_max",
        ):
            _require_plain_int(getattr(self, field_name), field_name, minimum=0)
        _require_bool(self.artifact_committed, "artifact_committed")
        _require_bool(self.deadline_exceeded, "deadline_exceeded")
        _require_bool(self.cleanup_complete, "cleanup_complete")
        normalized_cleanup = _normalize_cleanup_outcomes(self.cleanup_outcomes)
        if not any(item[3] for item in normalized_cleanup):
            raise ResourceControllerError(
                "cleanup outcomes do not contain a verified absence proof"
            )
        object.__setattr__(self, "cleanup_outcomes", normalized_cleanup)
        if self.claim_grade_ready is not True:
            raise ResourceControllerError(
                "authoritatively parsed resource evidence must be claim-grade ready"
            )
        snapshot = _normalize_capability_pairs(self.capability_snapshot)
        if _canonical_sha256(snapshot) != self.capability_snapshot_sha256:
            raise ResourceControllerError("capability snapshot hash mismatch")
        object.__setattr__(self, "capability_snapshot", tuple(snapshot.items()))
        invocation = _normalize_json_pairs(self.invocation, "invocation")
        if _canonical_sha256(invocation) != self.invocation_sha256:
            raise ResourceControllerError("resource evidence invocation hash mismatch")
        execution = _normalize_json_pairs(self.execution, "execution")
        if execution.get("run_id") != self.run_id:
            raise ResourceControllerError("resource evidence execution run_id mismatch")
        if execution.get("cleanup_complete") is not True:
            raise ResourceControllerError("resource evidence execution cleanup is incomplete")
        if execution.get("residual_processes") != 0:
            raise ResourceControllerError("resource evidence execution has residuals")
        object.__setattr__(self, "invocation", tuple(invocation.items()))
        object.__setattr__(self, "execution", tuple(execution.items()))
        if self.artifact_sha256 is not None and not _HEX_SHA256.fullmatch(
            self.artifact_sha256
        ):
            raise ResourceControllerError("artifact_sha256 is malformed")
        if self.artifact_committed != (self.artifact_sha256 is not None):
            raise ResourceControllerError(
                "artifact_sha256 must be present exactly when an artifact was committed"
            )
        artifact_fields = (
            self.artifact_relative_path,
            self.artifact_size_bytes,
            self.artifact_file_identity,
        )
        if self.artifact_committed:
            if not isinstance(self.artifact_relative_path, str):
                raise ResourceControllerError("artifact_relative_path is missing")
            _require_plain_int(
                self.artifact_size_bytes, "artifact_size_bytes", minimum=0
            )
            if not isinstance(
                self.artifact_file_identity, str
            ) or not _HEX_SHA256.fullmatch(self.artifact_file_identity):
                raise ResourceControllerError("artifact_file_identity is malformed")
        elif any(value is not None for value in artifact_fields):
            raise ResourceControllerError(
                "uncommitted artifact metadata must be absent"
            )
        _require_string(self.effective_cpu_max, "effective_cpu_max")
        _canonical_cpuset(self.effective_cpuset_cpus)
        object.__setattr__(
            self,
            "memory_events",
            _normalize_counter_pairs(self.memory_events, "memory_events"),
        )
        object.__setattr__(
            self, "cpu_stat", _normalize_counter_pairs(self.cpu_stat, "cpu_stat")
        )
        object.__setattr__(
            self,
            "memory_swap_events",
            _normalize_counter_pairs(self.memory_swap_events, "memory_swap_events"),
        )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "image_reference": self.image_reference,
            "image_id": self.image_id,
            "profile_sha256": self.profile_sha256,
            "invocation_sha256": self.invocation_sha256,
            "invocation": dict(self.invocation),
            "execution": dict(self.execution),
            "capability_sha256": self.capability_sha256,
            "capability_snapshot_sha256": self.capability_snapshot_sha256,
            "capability_snapshot": dict(self.capability_snapshot),
            "supervisor_sha256": self.supervisor_sha256,
            "daemon_id": self.daemon_id,
            "docker_context": self.docker_context,
            "cgroup_path": self.cgroup_path,
            "cgroup_identity": self.cgroup_identity,
            "post_exit_cgroup_sampled_monotonic_ns": (
                self.post_exit_cgroup_sampled_monotonic_ns
            ),
            "exit_code": self.exit_code,
            "elapsed_monotonic_ns": self.elapsed_monotonic_ns,
            "artifact_committed": self.artifact_committed,
            "artifact_sha256": self.artifact_sha256,
            "artifact_relative_path": self.artifact_relative_path,
            "artifact_size_bytes": self.artifact_size_bytes,
            "artifact_file_identity": self.artifact_file_identity,
            "memory_current_bytes": self.memory_current_bytes,
            "memory_peak_bytes": self.memory_peak_bytes,
            "memory_swap_current_bytes": self.memory_swap_current_bytes,
            "memory_swap_peak_bytes": self.memory_swap_peak_bytes,
            "memory_events": dict(self.memory_events),
            "memory_swap_events": dict(self.memory_swap_events),
            "cpu_stat": dict(self.cpu_stat),
            "pids_current": self.pids_current,
            "pids_peak": self.pids_peak,
            "effective_memory_max": self.effective_memory_max,
            "effective_memory_swap_max": self.effective_memory_swap_max,
            "effective_cpu_max": self.effective_cpu_max,
            "effective_cpuset_cpus": self.effective_cpuset_cpus,
            "effective_pids_max": self.effective_pids_max,
            "deadline_exceeded": self.deadline_exceeded,
            "cleanup_complete": self.cleanup_complete,
            "residual_processes": self.residual_processes,
            "cleanup_outcomes": [
                {
                    "operation": operation,
                    "returncode": returncode,
                    "error": error,
                    "absence_verified": absence_verified,
                }
                for operation, returncode, error, absence_verified in self.cleanup_outcomes
            ],
            "claim_grade_ready": self.claim_grade_ready,
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_canonical_dict())


def _normalize_counter_pairs(
    pairs: Sequence[Sequence[Any]], field_name: str
) -> tuple[tuple[str, int], ...]:
    if isinstance(pairs, (str, bytes)):
        raise ResourceControllerError(f"{field_name} must be key/value pairs")
    normalized: dict[str, int] = {}
    for pair in pairs:
        if isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise ResourceControllerError(f"{field_name} contains a malformed pair")
        key, value = pair
        if not isinstance(key, str) or not key or key in normalized:
            raise ResourceControllerError(f"{field_name} contains an invalid key")
        normalized[key] = _require_plain_int(value, f"{field_name}.{key}")
    return tuple(sorted(normalized.items()))


def _normalize_capability_pairs(
    pairs: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    if isinstance(pairs, (str, bytes)):
        raise ResourceControllerError("capability_snapshot must be key/value pairs")
    normalized: dict[str, Any] = {}
    for pair in pairs:
        if isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise ResourceControllerError("capability_snapshot contains a malformed pair")
        key, value = pair
        if not isinstance(key, str) or not key or key in normalized:
            raise ResourceControllerError("capability_snapshot contains an invalid key")
        normalized[key] = value
    try:
        return json.loads(_canonical_json_bytes(normalized))
    except (TypeError, ValueError) as exc:
        raise ResourceControllerError("capability_snapshot is not canonical JSON") from exc


def _normalize_json_pairs(
    pairs: Sequence[Sequence[Any]], field_name: str
) -> dict[str, Any]:
    if isinstance(pairs, (str, bytes)):
        raise ResourceControllerError(f"{field_name} must be key/value pairs")
    normalized: dict[str, Any] = {}
    for pair in pairs:
        if isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise ResourceControllerError(f"{field_name} contains a malformed pair")
        key, value = pair
        if not isinstance(key, str) or not key or key in normalized:
            raise ResourceControllerError(f"{field_name} contains an invalid key")
        normalized[key] = value
    try:
        return json.loads(_canonical_json_bytes(normalized))
    except (TypeError, ValueError) as exc:
        raise ResourceControllerError(f"{field_name} is not canonical JSON") from exc


def _normalize_cleanup_outcomes(
    outcomes: Sequence[Any],
) -> tuple[tuple[str, int | None, str | None, bool], ...]:
    if isinstance(outcomes, (str, bytes)) or not outcomes:
        raise ResourceControllerError("cleanup_outcomes must be a non-empty sequence")
    normalized = []
    for index, raw in enumerate(outcomes):
        if isinstance(raw, CleanupOutcome):
            values = (
                raw.operation,
                raw.returncode,
                raw.error,
                raw.absence_verified,
            )
        elif isinstance(raw, Mapping):
            values = (
                raw.get("operation"),
                raw.get("returncode"),
                raw.get("error"),
                raw.get("absence_verified", False),
            )
        elif not isinstance(raw, (str, bytes)) and len(raw) == 4:
            values = tuple(raw)
        else:
            raise ResourceControllerError(
                f"cleanup_outcomes[{index}] is malformed"
            )
        operation, returncode, error, absence_verified = values
        _require_string(operation, f"cleanup_outcomes[{index}].operation")
        if returncode is not None:
            _require_plain_int(
                returncode, f"cleanup_outcomes[{index}].returncode", minimum=0
            )
        if error is not None:
            _require_string(error, f"cleanup_outcomes[{index}].error")
        _require_bool(
            absence_verified, f"cleanup_outcomes[{index}].absence_verified"
        )
        normalized.append((operation, returncode, error, absence_verified))
    return tuple(normalized)


CommandExecutor = Callable[..., Any]


def _default_executor(
    command: tuple[str, ...], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class LocalFileSystem:
    """Minimal injectable filesystem boundary used by the controller."""

    def canonical_directory(self, value: str) -> str:
        path = Path(value)
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ResourceControllerError("host run directory does not exist") from exc
        is_junction = bool(getattr(path, "is_junction", lambda: False)())
        if stat.S_ISLNK(metadata.st_mode) or is_junction:
            raise ResourceControllerError("host run directory must not be a link")
        if not stat.S_ISDIR(metadata.st_mode):
            raise ResourceControllerError("host run directory is not a directory")
        resolved = path.resolve(strict=True)
        if os.path.normcase(str(resolved)) != os.path.normcase(os.path.abspath(value)):
            raise ResourceControllerError("host run directory is not canonical")
        return str(resolved)

    def read_artifact(
        self, canonical_run_directory: str, relative_path: str
    ) -> ArtifactSnapshot:
        run_directory = Path(canonical_run_directory)
        artifact = run_directory.joinpath(*PurePosixPath(relative_path).parts)
        try:
            metadata_before = artifact.lstat()
        except OSError as exc:
            raise ResourceControllerError("committed artifact is missing") from exc
        is_junction = bool(getattr(artifact, "is_junction", lambda: False)())
        if stat.S_ISLNK(metadata_before.st_mode) or is_junction:
            raise ResourceControllerError("committed artifact must not be a link")
        if not stat.S_ISREG(metadata_before.st_mode):
            raise ResourceControllerError("committed artifact is not a regular file")
        resolved = artifact.resolve(strict=True)
        if run_directory != resolved and run_directory not in resolved.parents:
            raise ResourceControllerError(
                "committed artifact escapes the run directory"
            )

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise ResourceControllerError(
                "committed artifact could not be opened"
            ) from exc
        digest = hashlib.sha256()
        try:
            opened = os.fstat(descriptor)
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            closed_view = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            metadata_after = artifact.lstat()
        except OSError as exc:
            raise ResourceControllerError("committed artifact disappeared") from exc

        def identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
            return (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )

        if not (
            identity(metadata_before)
            == identity(opened)
            == identity(closed_view)
            == identity(metadata_after)
        ):
            raise ResourceControllerError(
                "committed artifact was replaced or modified while hashing"
            )
        file_identity = _canonical_sha256(
            {
                "device": opened.st_dev,
                "inode": opened.st_ino,
                "size_bytes": opened.st_size,
                "mtime_ns": opened.st_mtime_ns,
            }
        )
        return ArtifactSnapshot(
            canonical_path=str(resolved),
            sha256=digest.hexdigest(),
            size_bytes=opened.st_size,
            mtime_ns=opened.st_mtime_ns,
            file_identity=file_identity,
        )


class DockerCgroupV2Controller:
    """Build Docker commands and admit only complete, policy-matched evidence."""

    def __init__(
        self,
        profile: ResourceProfile,
        capability_evidence: Mapping[str, Any],
        *,
        supervisor_sha256: str,
        executor: CommandExecutor | None = None,
        filesystem: Any | None = None,
        monotonic_ns: Callable[[], int] | None = None,
        wall_time_ns: Callable[[], int] | None = None,
        capability_evidence_provider: Callable[[], Mapping[str, Any]] | None = None,
        post_exit_cgroup_evidence_provider: (
            Callable[[SolverInvocation, Mapping[str, Any]], Mapping[str, Any]] | None
        ) = None,
        capability_max_age_seconds: float = DEFAULT_CAPABILITY_MAX_AGE_SECONDS,
        docker_executable: str = "docker",
    ) -> None:
        if not isinstance(profile, ResourceProfile):
            raise ResourceControllerError("profile must be a ResourceProfile")
        if not isinstance(docker_executable, str) or not docker_executable:
            raise ResourceControllerError("docker_executable must be non-empty")
        if not isinstance(supervisor_sha256, str) or not _HEX_SHA256.fullmatch(
            supervisor_sha256
        ):
            raise ResourceControllerError("supervisor_sha256 must be a SHA-256 digest")
        max_age = _require_finite_number(
            capability_max_age_seconds,
            "capability_max_age_seconds",
            minimum=0.0,
            inclusive=False,
        )
        self.profile = profile
        self.docker_executable = docker_executable
        self.supervisor_sha256 = supervisor_sha256
        self._executor = executor or _default_executor
        self._filesystem = filesystem or LocalFileSystem()
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._wall_time_ns = wall_time_ns or time.time_ns
        self._capability_evidence_provider = capability_evidence_provider
        self._post_exit_cgroup_evidence_provider = (
            post_exit_cgroup_evidence_provider
        )
        self._capability_max_age_ns = round(max_age * 1e9)
        self._capabilities = self._validate_capabilities(
            capability_evidence,
            enforce_freshness=capability_evidence_provider is None,
        )
        self._capability_contract = self._capability_contract_payload(
            self._capabilities
        )
        self.capability_sha256 = _canonical_sha256(self._capability_contract)
        self.capability_snapshot_sha256 = _canonical_sha256(self._capabilities)
        self._last_capability_capture_ns = self._capabilities[
            "captured_at_unix_ns"
        ]
        self._last_cleanup_outcomes: tuple[CleanupOutcome, ...] = ()
        self._last_final_inspect: Mapping[str, Any] | None = None
        self._last_post_exit_cgroup_evidence: Mapping[str, Any] | None = None
        self._authoritative_evidence_sha256: set[str] = set()

    def _validate_capabilities(
        self, evidence: Mapping[str, Any], *, enforce_freshness: bool = True
    ) -> dict[str, Any]:
        evidence = _require_mapping(evidence, "capability_evidence")
        required = {
            "schema",
            "docker_available",
            "server_os",
            "cgroup_version",
            "supports_memory_limit",
            "supports_swap_limit",
            "supports_cpu_quota",
            "supports_cpuset",
            "supports_pids_limit",
            "supports_read_only_rootfs",
            "total_memory_bytes",
            "available_swap_bytes",
            "available_cpuset_cpus",
            "daemon_id",
            "docker_context",
            "captured_at_unix_ns",
        }
        missing = sorted(required - set(evidence))
        if missing:
            raise ResourceControllerError(
                "capability_evidence is missing: " + ", ".join(missing)
            )
        if evidence["schema"] != CAPABILITY_EVIDENCE_SCHEMA:
            raise ResourceControllerError("unsupported capability evidence schema")
        if evidence["server_os"] != "linux":
            raise ResourceControllerError("Docker server must use Linux containers")
        if evidence["cgroup_version"] != 2 or isinstance(
            evidence["cgroup_version"], bool
        ):
            raise ResourceControllerError("Docker must use cgroup v2")
        for key in (
            "docker_available",
            "supports_memory_limit",
            "supports_swap_limit",
            "supports_cpu_quota",
            "supports_cpuset",
            "supports_pids_limit",
            "supports_read_only_rootfs",
        ):
            if _require_bool(evidence[key], key) is not True:
                raise ResourceControllerError(f"unsupported Docker capability: {key}")
        total_memory = _require_plain_int(
            evidence["total_memory_bytes"], "total_memory_bytes", minimum=1
        )
        if total_memory < self.profile.memory_bytes:
            raise ResourceControllerError(
                "Docker reports less memory than the requested memory limit"
            )
        available_swap = _require_plain_int(
            evidence["available_swap_bytes"], "available_swap_bytes", minimum=0
        )
        required_swap = self.profile.memory_swap_bytes - self.profile.memory_bytes
        if available_swap < required_swap:
            raise ResourceControllerError(
                "Docker reports less available swap than the requested allowance"
            )
        daemon_id = _require_string(evidence["daemon_id"], "daemon_id")
        if not _HEX_SHA256.fullmatch(daemon_id):
            raise ResourceControllerError("daemon_id must be a SHA-256 identity")
        docker_context = _require_string(evidence["docker_context"], "docker_context")
        if any(character.isspace() for character in docker_context):
            raise ResourceControllerError("docker_context is malformed")
        captured_at = _require_plain_int(
            evidence["captured_at_unix_ns"], "captured_at_unix_ns", minimum=0
        )
        now = _require_plain_int(self._wall_time_ns(), "wall clock", minimum=0)
        if captured_at > now:
            raise ResourceControllerError("capability evidence is from the future")
        if enforce_freshness and now - captured_at > self._capability_max_age_ns:
            raise ResourceControllerError("capability evidence is stale")
        available_cpuset = _canonical_cpuset(evidence["available_cpuset_cpus"])
        requested_cpus = _expand_cpuset(self.profile.cpuset_cpus)
        if not requested_cpus.issubset(_expand_cpuset(available_cpuset)):
            raise ResourceControllerError(
                "requested cpuset_cpus is not available to Docker"
            )
        normalized = dict(evidence)
        normalized["available_cpuset_cpus"] = available_cpuset
        return json.loads(_canonical_json_bytes(normalized))

    @staticmethod
    def _capability_contract_payload(evidence: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in evidence.items()
            if key != "captured_at_unix_ns"
        }

    def _validate_capability_contract(self, current: Mapping[str, Any]) -> None:
        if current["daemon_id"] != self._capabilities["daemon_id"]:
            raise ResourceControllerError("Docker daemon identity changed")
        if current["docker_context"] != self._capabilities["docker_context"]:
            raise ResourceControllerError("Docker context identity changed")
        if self._capability_contract_payload(current) != self._capability_contract:
            raise ResourceControllerError("Docker capability evidence was downgraded or drifted")

    def refresh_capability_evidence(self) -> dict[str, Any]:
        """Return a fresh daemon-bound snapshot or fail closed.

        A configured provider must advance the capture timestamp.  All other
        capability fields are immutable for the matrix, which makes daemon
        changes and capability downgrades explicit rather than silently
        changing the comparison contract between runs.
        """

        if self._capability_evidence_provider is None:
            current = self._validate_capabilities(self._capabilities)
            return json.loads(_canonical_json_bytes(current))
        try:
            supplied = self._capability_evidence_provider()
        except ResourceControllerError:
            raise
        except BaseException as exc:
            raise ResourceControllerError("capability evidence refresh failed") from exc
        current = self._validate_capabilities(supplied)
        self._validate_capability_contract(current)
        captured_at = current["captured_at_unix_ns"]
        if captured_at <= self._last_capability_capture_ns:
            raise ResourceControllerError(
                "capability evidence refresh did not advance its capture timestamp"
            )
        self._last_capability_capture_ns = captured_at
        return json.loads(_canonical_json_bytes(current))

    def _validate_bound_capability_snapshot(
        self,
        invocation: SolverInvocation,
        capability_snapshot: Mapping[str, Any],
        *,
        enforce_freshness: bool,
    ) -> dict[str, Any]:
        current = self._validate_capabilities(
            capability_snapshot, enforce_freshness=enforce_freshness
        )
        self._validate_capability_contract(current)
        expected_sha256 = invocation.capability_snapshot_sha256
        if expected_sha256 is None:
            expected_sha256 = self.capability_snapshot_sha256
        if _canonical_sha256(current) != expected_sha256:
            raise ResourceControllerError("invocation capability snapshot hash mismatch")
        return current

    @property
    def last_cleanup_outcomes(self) -> tuple[CleanupOutcome, ...]:
        return self._last_cleanup_outcomes

    @property
    def last_final_inspect(self) -> dict[str, Any]:
        if self._last_final_inspect is None:
            raise ResourceControllerError("final Docker inspect evidence is unavailable")
        return json.loads(_canonical_json_bytes(self._last_final_inspect))

    @property
    def last_post_exit_cgroup_evidence(self) -> dict[str, Any]:
        if self._last_post_exit_cgroup_evidence is None:
            raise ResourceControllerError("post-exit cgroup evidence is unavailable")
        return json.loads(
            _canonical_json_bytes(self._last_post_exit_cgroup_evidence)
        )

    @property
    def capability_evidence(self) -> dict[str, Any]:
        """Return a detached canonical copy suitable for immutable manifests."""

        return json.loads(_canonical_json_bytes(self._capabilities))

    def authorizes_claim_grade_evidence(self, evidence: Mapping[str, Any]) -> bool:
        """Return whether this process admitted these exact normalized bytes."""

        try:
            evidence_sha256 = resource_evidence_sha256(evidence)
        except ResourceControllerError:
            return False
        return evidence_sha256 in self._authoritative_evidence_sha256

    def container_name(self, invocation: SolverInvocation) -> str:
        self._require_invocation(invocation)
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", invocation.run_id)[:48]
        return f"planora-itc2019-{slug}-{invocation.sha256[:12]}"

    def expected_labels(self, invocation: SolverInvocation) -> dict[str, str]:
        self._require_invocation(invocation)
        snapshot_sha256 = (
            invocation.capability_snapshot_sha256 or self.capability_snapshot_sha256
        )
        return {
            CONTROLLER_LABEL: CONTROLLER_VERSION,
            "planora.itc2019.run-id": invocation.run_id,
            "planora.itc2019.solver": invocation.solver,
            "planora.itc2019.profile-sha256": self.profile.sha256,
            "planora.itc2019.invocation-sha256": invocation.sha256,
            "planora.itc2019.capability-sha256": self.capability_sha256,
            "planora.itc2019.capability-snapshot-sha256": snapshot_sha256,
            "planora.itc2019.supervisor-sha256": self.supervisor_sha256,
            "planora.itc2019.daemon-id": self._capabilities["daemon_id"],
            "planora.itc2019.context-sha256": hashlib.sha256(
                self._capabilities["docker_context"].encode("utf-8")
            ).hexdigest(),
        }

    def supervisor_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        """Return the fixed trusted entrypoint arguments for one invocation."""

        self._require_invocation(invocation)
        snapshot_sha256 = (
            invocation.capability_snapshot_sha256 or self.capability_snapshot_sha256
        )
        return (
            "--expected-supervisor-sha256",
            self.supervisor_sha256,
            "--run-id",
            invocation.run_id,
            "--profile-sha256",
            self.profile.sha256,
            "--invocation-sha256",
            invocation.sha256,
            "--capability-sha256",
            self.capability_sha256,
            "--capability-snapshot-sha256",
            snapshot_sha256,
            "--image-digest",
            invocation.image,
            "--artifact-relative-path",
            invocation.artifact_relative_path,
            "--",
            *invocation.argv,
        )

    def docker_create_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        """Return a deterministic ``docker create`` command for one run."""

        self._require_invocation(invocation)
        command = [
            self.docker_executable,
            "create",
            "--pull=never",
            f"--name={self.container_name(invocation)}",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={self.profile.memory_bytes}",
            f"--memory-swap={self.profile.memory_swap_bytes}",
            f"--cpuset-cpus={self.profile.cpuset_cpus}",
            f"--cpu-period={self.profile.cpu_period_us}",
            f"--cpu-quota={self.profile.cpu_quota_us}",
            f"--pids-limit={self.profile.pids_limit}",
            "--restart=no",
            f"--workdir={invocation.container_run_directory}",
            f"--entrypoint={TRUSTED_SUPERVISOR_ENTRYPOINT}",
        ]
        for key, value in sorted(self.expected_labels(invocation).items()):
            command.append(f"--label={key}={value}")
        for source, destination in invocation.input_mounts + invocation.binary_mounts:
            command.append(f"--mount=type=bind,src={source},dst={destination},readonly")
        command.append(
            "--mount=type=bind,"
            f"src={invocation.host_run_directory},"
            f"dst={invocation.container_run_directory}"
        )
        command.extend((invocation.image, *self.supervisor_command(invocation)))
        return tuple(command)

    def docker_start_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        """Return the deterministic attached start command for a created run."""

        return (
            self.docker_executable,
            "start",
            "--attach",
            self.container_name(invocation),
        )

    def command_specification(
        self, invocation: SolverInvocation
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (
            self.docker_create_command(invocation),
            self.docker_start_command(invocation),
        )

    def docker_inspect_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        return (
            self.docker_executable,
            "inspect",
            "--type=container",
            self.container_name(invocation),
        )

    def docker_kill_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        return (self.docker_executable, "kill", self.container_name(invocation))

    def docker_remove_command(self, invocation: SolverInvocation) -> tuple[str, ...]:
        return (
            self.docker_executable,
            "rm",
            "--force",
            self.container_name(invocation),
        )

    def _run_command(
        self, command: tuple[str, ...], *, timeout: float | None = None
    ) -> Any:
        try:
            return self._executor(command, timeout=timeout)
        except TypeError as exc:
            raise ResourceControllerError(
                "executor must accept a keyword-only timeout argument"
            ) from exc

    def _inspect_from_result(self, result: Any) -> Mapping[str, Any]:
        if _command_returncode(result) != 0:
            raise ResourceControllerError("docker inspect failed")
        raw = _command_stdout(result)
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ResourceControllerError(
                "docker inspect returned malformed JSON"
            ) from exc
        if not isinstance(payload, list) or len(payload) != 1:
            raise ResourceControllerError(
                "docker inspect did not identify one container"
            )
        return _require_mapping(payload[0], "docker inspect result")

    def _inspect_proves_absent(self, result: Any, invocation: SolverInvocation) -> bool:
        if _command_returncode(result) != 1:
            return False
        name = self.container_name(invocation)
        stdout = _command_stdout(result).strip()
        stderr = _command_stderr(result).strip()
        legacy = f"Error: No such container: {name}"
        docker_29 = f"Error response from daemon: No such container: {name}"
        return (stdout == "" and stderr == legacy) or (
            stdout == "[]" and stderr == docker_29
        )

    def _cleanup_after_execution(
        self,
        invocation: SolverInvocation,
        *,
        force_kill: bool,
    ) -> _CleanupResult:
        outcomes: list[CleanupOutcome] = []

        def run_cleanup_command(operation: str, command: tuple[str, ...]) -> Any | None:
            try:
                result = self._run_command(
                    command,
                    timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
                )
                returncode = _command_returncode(result)
            except BaseException as exc:
                outcomes.append(CleanupOutcome(operation, None, type(exc).__name__))
                return None
            outcomes.append(CleanupOutcome(operation, returncode, None))
            return result

        def record_evidence_error(operation: str, exc: BaseException) -> None:
            outcomes.append(CleanupOutcome(operation, None, type(exc).__name__))

        final_inspect: Mapping[str, Any] | None = None
        residual_processes = 1
        initial_absence_verified = False
        remove_result: Any | None = None
        absent_result: Any | None = None
        try:
            if force_kill:
                run_cleanup_command(
                    "kill-before-inspect", self.docker_kill_command(invocation)
                )
            inspect_result = run_cleanup_command(
                "inspect-before-remove", self.docker_inspect_command(invocation)
            )
            if inspect_result is not None:
                try:
                    initial_absence_verified = self._inspect_proves_absent(
                        inspect_result, invocation
                    )
                    if initial_absence_verified:
                        residual_processes = 0
                    elif _command_returncode(inspect_result) == 0:
                        final_inspect = self._inspect_from_result(inspect_result)
                        state = _require_mapping(
                            final_inspect.get("State"), "inspect.State"
                        )
                        running = _require_bool(
                            state.get("Running"), "inspect.State.Running"
                        )
                        pid = _require_plain_int(
                            state.get("Pid"), "inspect.State.Pid", minimum=0
                        )
                        residual_processes = 0 if not running and pid == 0 else 1
                        if residual_processes:
                            run_cleanup_command(
                                "kill-residual", self.docker_kill_command(invocation)
                            )
                            reinspection = run_cleanup_command(
                                "inspect-after-kill",
                                self.docker_inspect_command(invocation),
                            )
                            if reinspection is not None:
                                if self._inspect_proves_absent(
                                    reinspection, invocation
                                ):
                                    final_inspect = None
                                    residual_processes = 0
                                elif _command_returncode(reinspection) == 0:
                                    final_inspect = self._inspect_from_result(
                                        reinspection
                                    )
                                    state = _require_mapping(
                                        final_inspect.get("State"), "inspect.State"
                                    )
                                    running = _require_bool(
                                        state.get("Running"),
                                        "inspect.State.Running",
                                    )
                                    pid = _require_plain_int(
                                        state.get("Pid"),
                                        "inspect.State.Pid",
                                        minimum=0,
                                    )
                                    residual_processes = (
                                        0 if not running and pid == 0 else 1
                                    )
                except BaseException as exc:
                    record_evidence_error("inspect-evidence", exc)
                    residual_processes = 1
        finally:
            try:
                remove_result = run_cleanup_command(
                    "remove", self.docker_remove_command(invocation)
                )
            finally:
                absent_result = run_cleanup_command(
                    "inspect-after-remove", self.docker_inspect_command(invocation)
                )

        final_absence_verified = False
        if absent_result is not None:
            try:
                final_absence_verified = self._inspect_proves_absent(
                    absent_result, invocation
                )
            except BaseException as exc:
                record_evidence_error("absence-evidence", exc)
        if final_absence_verified:
            outcomes.append(CleanupOutcome("absence-verification", 1, None, True))

        remove_succeeded = (
            remove_result is not None and _command_returncode(remove_result) == 0
        )
        cleanup_complete = (
            residual_processes == 0
            and final_absence_verified
            and (remove_succeeded or initial_absence_verified)
        )
        result = _CleanupResult(
            final_inspect=final_inspect,
            cleanup_complete=cleanup_complete,
            residual_processes=residual_processes,
            outcomes=tuple(outcomes),
        )
        self._last_cleanup_outcomes = result.outcomes
        return result

    def _cleanup_after_failed_create(self, invocation: SolverInvocation) -> bool:
        outcomes: list[CleanupOutcome] = []
        remove_result: Any | None = None
        absent_result: Any | None = None
        try:
            try:
                remove_result = self._run_command(
                    self.docker_remove_command(invocation),
                    timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
                )
                outcomes.append(
                    CleanupOutcome("remove", _command_returncode(remove_result), None)
                )
            except BaseException as exc:
                outcomes.append(CleanupOutcome("remove", None, type(exc).__name__))
        finally:
            try:
                absent_result = self._run_command(
                    self.docker_inspect_command(invocation),
                    timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
                )
                outcomes.append(
                    CleanupOutcome(
                        "inspect-after-remove",
                        _command_returncode(absent_result),
                        None,
                    )
                )
            except BaseException as exc:
                outcomes.append(
                    CleanupOutcome("inspect-after-remove", None, type(exc).__name__)
                )
        absence_verified = False
        if absent_result is not None:
            try:
                absence_verified = self._inspect_proves_absent(
                    absent_result, invocation
                )
            except BaseException as exc:
                outcomes.append(
                    CleanupOutcome("absence-evidence", None, type(exc).__name__)
                )
        if absence_verified:
            outcomes.append(CleanupOutcome("absence-verification", 1, None, True))
        self._last_cleanup_outcomes = tuple(outcomes)
        return absence_verified

    def cleanup_after_failure(self, invocation: SolverInvocation) -> bool:
        """Idempotently drain a possibly-created container after a later failure."""

        self._require_invocation(invocation)
        return self._cleanup_after_execution(
            invocation, force_kill=True
        ).cleanup_complete

    def execute(
        self,
        invocation: SolverInvocation,
        *,
        capability_snapshot: Mapping[str, Any] | None = None,
    ) -> ExecutionObservation:
        """Run with an outer deadline and independently prove Docker cleanup."""

        self._require_invocation(invocation)
        self._last_final_inspect = None
        self._last_post_exit_cgroup_evidence = None
        bound_snapshot = (
            self._capabilities
            if capability_snapshot is None
            else capability_snapshot
        )
        self._validate_bound_capability_snapshot(
            invocation, bound_snapshot, enforce_freshness=True
        )
        canonical_run_directory = self._filesystem.canonical_directory(
            invocation.host_run_directory
        )
        if os.path.normcase(canonical_run_directory) != os.path.normcase(
            os.path.abspath(invocation.host_run_directory)
        ):
            raise ResourceControllerError("host run directory is not canonical")

        create_result = self._run_command(
            self.docker_create_command(invocation),
            timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
        )
        try:
            create_returncode = _command_returncode(create_result)
        except BaseException:
            self._cleanup_after_failed_create(invocation)
            raise
        if create_returncode != 0:
            if not self._cleanup_after_failed_create(invocation):
                raise ResourceControllerError(
                    "docker create failed and cleanup could not be proven complete"
                )
            raise ResourceControllerError("docker create failed")
        primary_error: BaseException | None = None
        container_id = ""
        image_id = ""
        started_monotonic = 0
        started_wall = 0
        solver_deadline = 0
        artifact_deadline = 0
        artifact_deadline_wall = 0
        finished_monotonic = 0
        attach_returncode = -1
        try:
            container_id = _command_stdout(create_result).strip()
            if not re.fullmatch(r"[0-9a-f]{64}", container_id):
                raise ResourceControllerError(
                    "docker create did not return a full container ID"
                )
            initial_inspect = self._inspect_from_result(
                self._run_command(
                    self.docker_inspect_command(invocation),
                    timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
                )
            )
            if initial_inspect.get("Id") != container_id:
                raise ResourceControllerError("created container identity mismatch")
            image_id = _require_string(initial_inspect.get("Image"), "inspect.Image")
            if not _IMAGE_ID.fullmatch(image_id):
                raise ResourceControllerError("created image identity is malformed")

            started_monotonic = _require_plain_int(
                self._monotonic_ns(), "monotonic clock", minimum=0
            )
            started_wall = _require_plain_int(
                self._wall_time_ns(), "wall clock", minimum=0
            )
            solver_deadline = started_monotonic + round(
                self.profile.wall_time_seconds * 1e9
            )
            artifact_deadline = solver_deadline + round(
                self.profile.artifact_grace_seconds * 1e9
            )
            artifact_deadline_wall = started_wall + (
                artifact_deadline - started_monotonic
            )
            remaining_seconds = max(
                0.0, (artifact_deadline - self._monotonic_ns()) / 1e9
            )
            start_result = self._run_command(
                self.docker_start_command(invocation), timeout=remaining_seconds
            )
            attach_returncode = _command_returncode(start_result)
            if self._monotonic_ns() > artifact_deadline:
                raise ResourceControllerError(
                    "docker start exceeded the outer host deadline"
                )
        except subprocess.TimeoutExpired as exc:
            primary_error = ResourceControllerError(
                "docker start exceeded the outer host deadline"
            )
            primary_error.__cause__ = exc
        except BaseException as exc:
            primary_error = exc
        if primary_error is None:
            try:
                finished_monotonic = _require_plain_int(
                    self._monotonic_ns(), "monotonic clock", minimum=0
                )
                if attach_returncode != 0:
                    raise ResourceControllerError("docker start failed")
                if self._post_exit_cgroup_evidence_provider is not None:
                    post_exit_inspect = self._inspect_from_result(
                        self._run_command(
                            self.docker_inspect_command(invocation),
                            timeout=OUTER_CLEANUP_ALLOWANCE_SECONDS,
                        )
                    )
                    if post_exit_inspect.get("Id") != container_id:
                        raise ResourceControllerError(
                            "post-exit inspect container identity mismatch"
                        )
                    post_exit_state = _require_mapping(
                        post_exit_inspect.get("State"), "post-exit inspect.State"
                    )
                    if (
                        post_exit_state.get("Status") != "exited"
                        or _require_bool(
                            post_exit_state.get("Running"),
                            "post-exit inspect.State.Running",
                        )
                        or _require_plain_int(
                            post_exit_state.get("Pid"),
                            "post-exit inspect.State.Pid",
                            minimum=0,
                        )
                        != 0
                    ):
                        raise ResourceControllerError(
                            "post-exit inspect does not prove container exit"
                        )
                    captured = self._post_exit_cgroup_evidence_provider(
                        invocation, post_exit_inspect
                    )
                    self._last_post_exit_cgroup_evidence = json.loads(
                        _canonical_json_bytes(
                            _require_mapping(captured, "post-exit cgroup evidence")
                        )
                    )
            except BaseException as exc:
                if isinstance(exc, ResourceControllerError):
                    primary_error = exc
                else:
                    primary_error = ResourceControllerError(
                        "post-exit cgroup evidence capture failed"
                    )
                    primary_error.__cause__ = exc
        cleanup = self._cleanup_after_execution(
            invocation,
            force_kill=primary_error is not None or attach_returncode != 0,
        )
        final_inspect = cleanup.final_inspect
        cleanup_complete = cleanup.cleanup_complete
        residual_processes = cleanup.residual_processes
        if final_inspect is None:
            cleanup_complete = False
        if final_inspect is not None and final_inspect.get("Id") != container_id:
            cleanup_complete = False
        if primary_error is not None:
            if not cleanup_complete:
                primary_error.add_note(
                    "Docker cleanup could not be proven complete after the primary failure"
                )
            raise primary_error
        if not cleanup_complete:
            raise ResourceControllerError("Docker cleanup could not be proven complete")
        if final_inspect is None:
            raise ResourceControllerError("final container state is unavailable")
        self._last_final_inspect = json.loads(_canonical_json_bytes(final_inspect))
        state = _require_mapping(final_inspect.get("State"), "inspect.State")
        if state.get("Status") != "exited":
            raise ResourceControllerError("container state is not exited")
        return ExecutionObservation(
            run_id=invocation.run_id,
            container_id=container_id,
            image_id=image_id,
            host_started_monotonic_ns=started_monotonic,
            host_solver_deadline_monotonic_ns=solver_deadline,
            host_artifact_deadline_monotonic_ns=artifact_deadline,
            host_finished_monotonic_ns=finished_monotonic,
            host_started_wall_ns=started_wall,
            host_artifact_deadline_wall_ns=artifact_deadline_wall,
            attach_returncode=attach_returncode,
            timed_out=False,
            cleanup_complete=cleanup_complete,
            residual_processes=residual_processes,
        )

    def parse_evidence(
        self,
        invocation: SolverInvocation,
        *,
        inspect: Mapping[str, Any],
        execution: ExecutionObservation | Mapping[str, Any],
        cgroup: Mapping[str, Any],
        supervisor: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any] | None = None,
        cleanup_outcomes: Sequence[Any] = (),
    ) -> ResourceEvidence:
        """Validate and normalize one run's evidence, rejecting uncertainty."""

        self._require_invocation(invocation)
        if self._capability_evidence_provider is None:
            raise ResourceControllerError(
                "claim-grade evidence parsing requires a refresh provider"
            )
        bound_snapshot = self._validate_bound_capability_snapshot(
            invocation,
            self._capabilities if capability_snapshot is None else capability_snapshot,
            enforce_freshness=False,
        )
        # A second direct probe after execution proves that the Docker daemon and
        # its capability contract did not change while the run was in flight.
        self.refresh_capability_evidence()
        observed_monotonic_ns = _require_plain_int(
            self._monotonic_ns(), "monotonic clock", minimum=0
        )
        observed_wall_ns = _require_plain_int(
            self._wall_time_ns(), "wall clock", minimum=0
        )
        normalized_cleanup = _normalize_cleanup_outcomes(cleanup_outcomes)
        inspect = _require_mapping(inspect, "inspect")
        execution_values = self._validate_execution_observation(
            invocation,
            execution,
            observed_monotonic_ns=observed_monotonic_ns,
            observed_wall_ns=observed_wall_ns,
        )
        cgroup_values = self._validate_cgroup_binding(invocation, inspect, cgroup)
        cgroup_files = cgroup_values["files"]
        supervisor = _require_mapping(supervisor, "supervisor")
        self._validate_inspect(invocation, inspect)
        if inspect.get("Id") != execution_values["container_id"]:
            raise ResourceControllerError("execution container identity mismatch")
        if inspect.get("Image") != execution_values["image_id"]:
            raise ResourceControllerError("execution image identity mismatch")

        memory_current = _parse_scalar_cgroup_file(cgroup_files, "memory.current")
        memory_peak = _parse_scalar_cgroup_file(cgroup_files, "memory.peak")
        swap_current = _parse_scalar_cgroup_file(cgroup_files, "memory.swap.current")
        swap_peak = _parse_scalar_cgroup_file(cgroup_files, "memory.swap.peak")
        pids_current = _parse_scalar_cgroup_file(cgroup_files, "pids.current")
        pids_peak = _parse_scalar_cgroup_file(cgroup_files, "pids.peak")
        memory_events = _parse_counter_cgroup_file(cgroup_files, "memory.events")
        swap_events = _parse_counter_cgroup_file(cgroup_files, "memory.swap.events")
        cpu_stat = _parse_counter_cgroup_file(cgroup_files, "cpu.stat")
        effective_memory_max = _parse_limit_cgroup_file(cgroup_files, "memory.max")
        effective_swap_max = _parse_limit_cgroup_file(cgroup_files, "memory.swap.max")
        effective_pids_max = _parse_limit_cgroup_file(cgroup_files, "pids.max")
        effective_cpu_max = _parse_cpu_max(cgroup_files)
        effective_cpuset = _parse_cpuset_file(cgroup_files, "cpuset.cpus.effective")
        cgroup_procs = cgroup_files.get("cgroup.procs")
        if not isinstance(cgroup_procs, str) or cgroup_procs.strip():
            raise ResourceControllerError("cgroup.procs does not prove zero residuals")
        missing_memory = sorted(_CGROUP_REQUIRED_MEMORY_EVENTS - set(memory_events))
        if missing_memory:
            raise ResourceControllerError(
                "memory.events is missing: " + ", ".join(missing_memory)
            )
        missing_cpu = sorted(_CGROUP_REQUIRED_CPU_STAT - set(cpu_stat))
        if missing_cpu:
            raise ResourceControllerError(
                "cpu.stat is missing: " + ", ".join(missing_cpu)
            )
        missing_swap = sorted(_CGROUP_REQUIRED_SWAP_EVENTS - set(swap_events))
        if missing_swap:
            raise ResourceControllerError(
                "memory.swap.events is missing: " + ", ".join(missing_swap)
            )

        swap_limit = self.profile.memory_swap_bytes - self.profile.memory_bytes
        if effective_memory_max != self.profile.memory_bytes:
            raise ResourceControllerError("effective memory.max mismatch")
        if effective_swap_max != swap_limit:
            raise ResourceControllerError("effective memory.swap.max mismatch")
        if effective_pids_max != self.profile.pids_limit:
            raise ResourceControllerError("effective pids.max mismatch")
        expected_cpu_max = f"{self.profile.cpu_quota_us} {self.profile.cpu_period_us}"
        if effective_cpu_max != expected_cpu_max:
            raise ResourceControllerError("effective cpu.max mismatch")
        if effective_cpuset != self.profile.cpuset_cpus:
            raise ResourceControllerError("effective cpuset.cpus mismatch")
        if (
            memory_current > self.profile.memory_bytes
            or memory_peak > self.profile.memory_bytes
        ):
            raise ResourceControllerError("memory evidence exceeds memory_bytes")
        if swap_current > swap_limit or swap_peak > swap_limit:
            raise ResourceControllerError(
                "swap evidence exceeds the configured swap allowance"
            )
        if (
            pids_current > self.profile.pids_limit
            or pids_peak > self.profile.pids_limit
        ):
            raise ResourceControllerError("PID evidence exceeds pids_limit")
        if memory_current > memory_peak:
            raise ResourceControllerError("memory.current exceeds memory.peak")
        if swap_current > swap_peak:
            raise ResourceControllerError(
                "memory.swap.current exceeds memory.swap.peak"
            )
        if pids_current > pids_peak:
            raise ResourceControllerError("pids.current exceeds pids.peak")
        if pids_peak == 0:
            raise ResourceControllerError("pids.peak cannot be zero after launch")
        if cpu_stat["user_usec"] + cpu_stat["system_usec"] > cpu_stat["usage_usec"]:
            raise ResourceControllerError("cpu.stat counters are inconsistent")
        if cpu_stat["nr_throttled"] > cpu_stat["nr_periods"]:
            raise ResourceControllerError("cpu.stat period counters are inconsistent")
        if cpu_stat["nr_periods"] == 0 and (
            cpu_stat["nr_throttled"] != 0 or cpu_stat["throttled_usec"] != 0
        ):
            raise ResourceControllerError("cpu.stat zero counters are inconsistent")
        if any(memory_events[key] > 0 for key in ("oom", "oom_kill", "oom_group_kill")):
            raise ResourceControllerError("cgroup evidence records an OOM event")
        if any(swap_events[key] > 0 for key in ("max", "fail")):
            raise ResourceControllerError("cgroup evidence records a swap failure")

        state = _require_mapping(inspect.get("State"), "inspect.State")
        if _require_bool(state.get("OOMKilled"), "inspect.State.OOMKilled"):
            raise ResourceControllerError("Docker inspect records an OOM kill")
        supervisor_values = self._validate_supervisor(
            invocation,
            supervisor,
            inspect=inspect,
            execution=execution_values,
            cgroup=cgroup_values,
            observed_monotonic_ns=observed_monotonic_ns,
        )
        artifact_snapshot: ArtifactSnapshot | None = None
        if supervisor_values["artifact_committed"]:
            canonical_run_directory = self._filesystem.canonical_directory(
                invocation.host_run_directory
            )
            artifact_snapshot = self._filesystem.read_artifact(
                canonical_run_directory, invocation.artifact_relative_path
            )
            if artifact_snapshot.mtime_ns < execution_values["host_started_wall_ns"]:
                raise ResourceControllerError("committed artifact predates this run")
            if artifact_snapshot.mtime_ns > observed_wall_ns:
                raise ResourceControllerError(
                    "committed artifact timestamp is in the future"
                )
            if (
                artifact_snapshot.mtime_ns
                > execution_values["host_artifact_deadline_wall_ns"]
            ):
                raise ResourceControllerError("committed artifact is post-cutoff")
            expected_artifact = {
                "artifact_sha256": artifact_snapshot.sha256,
                "artifact_size_bytes": artifact_snapshot.size_bytes,
                "artifact_mtime_ns": artifact_snapshot.mtime_ns,
                "artifact_file_identity": artifact_snapshot.file_identity,
            }
            for key, observed in expected_artifact.items():
                if supervisor_values[key] != observed:
                    raise ResourceControllerError(
                        f"supervisor {key} does not match the host artifact"
                    )

        evidence = ResourceEvidence(
            run_id=invocation.run_id,
            container_id=_require_string(inspect.get("Id"), "inspect.Id"),
            container_name=_require_string(inspect.get("Name"), "inspect.Name").lstrip(
                "/"
            ),
            image_reference=invocation.image,
            image_id=_require_string(inspect.get("Image"), "inspect.Image"),
            profile_sha256=self.profile.sha256,
            invocation_sha256=invocation.sha256,
            invocation=tuple(sorted(invocation.to_canonical_dict().items())),
            execution=tuple(sorted(execution_values.items())),
            capability_sha256=self.capability_sha256,
            capability_snapshot_sha256=_canonical_sha256(bound_snapshot),
            capability_snapshot=tuple(sorted(bound_snapshot.items())),
            supervisor_sha256=self.supervisor_sha256,
            daemon_id=self._capabilities["daemon_id"],
            docker_context=self._capabilities["docker_context"],
            cgroup_path=cgroup_values["path"],
            cgroup_identity=cgroup_values["identity"],
            post_exit_cgroup_sampled_monotonic_ns=cgroup_values[
                "sampled_monotonic_ns"
            ],
            exit_code=_require_plain_int(
                state.get("ExitCode"), "inspect.State.ExitCode", minimum=0
            ),
            elapsed_monotonic_ns=supervisor_values["elapsed_monotonic_ns"],
            artifact_committed=supervisor_values["artifact_committed"],
            artifact_sha256=(
                artifact_snapshot.sha256 if artifact_snapshot is not None else None
            ),
            artifact_relative_path=(
                invocation.artifact_relative_path
                if artifact_snapshot is not None
                else None
            ),
            artifact_size_bytes=(
                artifact_snapshot.size_bytes if artifact_snapshot is not None else None
            ),
            artifact_file_identity=(
                artifact_snapshot.file_identity
                if artifact_snapshot is not None
                else None
            ),
            memory_current_bytes=memory_current,
            memory_peak_bytes=memory_peak,
            memory_swap_current_bytes=swap_current,
            memory_swap_peak_bytes=swap_peak,
            memory_events=tuple(memory_events.items()),
            memory_swap_events=tuple(swap_events.items()),
            cpu_stat=tuple(cpu_stat.items()),
            pids_current=pids_current,
            pids_peak=pids_peak,
            effective_memory_max=effective_memory_max,
            effective_memory_swap_max=effective_swap_max,
            effective_cpu_max=effective_cpu_max,
            effective_cpuset_cpus=effective_cpuset,
            effective_pids_max=effective_pids_max,
            deadline_exceeded=execution_values["timed_out"],
            cleanup_complete=execution_values["cleanup_complete"],
            residual_processes=execution_values["residual_processes"],
            cleanup_outcomes=normalized_cleanup,
            claim_grade_ready=True,
            _parse_capability=_RESOURCE_EVIDENCE_PARSE_CAPABILITY,
        )
        self._authoritative_evidence_sha256.add(evidence.sha256)
        return evidence

    def _validate_execution_observation(
        self,
        invocation: SolverInvocation,
        execution: ExecutionObservation | Mapping[str, Any],
        *,
        observed_monotonic_ns: int,
        observed_wall_ns: int,
    ) -> dict[str, Any]:
        if isinstance(execution, ExecutionObservation):
            values = {
                field_name: getattr(execution, field_name)
                for field_name in execution.__dataclass_fields__
            }
        else:
            values = dict(_require_mapping(execution, "execution"))
        if values.get("run_id") != invocation.run_id:
            raise ResourceControllerError("execution run_id mismatch")
        container_id = _require_string(
            values.get("container_id"), "execution.container_id"
        )
        image_id = _require_string(values.get("image_id"), "execution.image_id")
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise ResourceControllerError("execution container_id is malformed")
        if not _IMAGE_ID.fullmatch(image_id):
            raise ResourceControllerError("execution image_id is malformed")
        integer_fields = (
            "host_started_monotonic_ns",
            "host_solver_deadline_monotonic_ns",
            "host_artifact_deadline_monotonic_ns",
            "host_finished_monotonic_ns",
            "host_started_wall_ns",
            "host_artifact_deadline_wall_ns",
            "attach_returncode",
            "residual_processes",
        )
        for field_name in integer_fields:
            values[field_name] = _require_plain_int(
                values.get(field_name), f"execution.{field_name}", minimum=0
            )
        values["timed_out"] = _require_bool(
            values.get("timed_out"), "execution.timed_out"
        )
        values["cleanup_complete"] = _require_bool(
            values.get("cleanup_complete"), "execution.cleanup_complete"
        )
        expected_solver_deadline = values["host_started_monotonic_ns"] + round(
            self.profile.wall_time_seconds * 1e9
        )
        expected_artifact_deadline = expected_solver_deadline + round(
            self.profile.artifact_grace_seconds * 1e9
        )
        if values["host_solver_deadline_monotonic_ns"] != expected_solver_deadline:
            raise ResourceControllerError("host solver deadline mismatch")
        if values["host_artifact_deadline_monotonic_ns"] != expected_artifact_deadline:
            raise ResourceControllerError("host artifact deadline mismatch")
        expected_wall_deadline = values["host_started_wall_ns"] + (
            expected_artifact_deadline - values["host_started_monotonic_ns"]
        )
        if values["host_artifact_deadline_wall_ns"] != expected_wall_deadline:
            raise ResourceControllerError("host wall deadline mismatch")
        if values["host_finished_monotonic_ns"] > expected_artifact_deadline:
            raise ResourceControllerError("host completion exceeded the outer deadline")
        if values["host_finished_monotonic_ns"] < values["host_started_monotonic_ns"]:
            raise ResourceControllerError("host completion predates host launch")
        if values["host_finished_monotonic_ns"] > observed_monotonic_ns:
            raise ResourceControllerError("host completion is in the future")
        if values["host_started_monotonic_ns"] > observed_monotonic_ns:
            raise ResourceControllerError("host launch is in the future")
        if values["host_started_wall_ns"] > observed_wall_ns:
            raise ResourceControllerError("host wall launch is in the future")
        if values["timed_out"]:
            raise ResourceControllerError("host execution records a timeout")
        if not values["cleanup_complete"]:
            raise ResourceControllerError("host cleanup is incomplete")
        if values["residual_processes"] != 0:
            raise ResourceControllerError("host inspection found residual processes")
        return values

    def _validate_cgroup_binding(
        self,
        invocation: SolverInvocation,
        inspect: Mapping[str, Any],
        cgroup: Mapping[str, Any],
    ) -> dict[str, Any]:
        values = dict(_require_mapping(cgroup, "cgroup"))
        container_id = _require_string(
            values.get("container_id"), "cgroup.container_id"
        )
        if container_id != inspect.get("Id"):
            raise ResourceControllerError("cgroup container identity mismatch")
        if values.get("run_id") != invocation.run_id:
            raise ResourceControllerError("cgroup run_id mismatch")
        if values.get("image_id") != inspect.get("Image"):
            raise ResourceControllerError("cgroup image identity mismatch")
        if values.get("profile_sha256") != self.profile.sha256:
            raise ResourceControllerError("cgroup profile hash mismatch")
        if values.get("supervisor_sha256") != self.supervisor_sha256:
            raise ResourceControllerError("cgroup supervisor hash mismatch")
        expected_snapshot_sha256 = (
            invocation.capability_snapshot_sha256 or self.capability_snapshot_sha256
        )
        if values.get("capability_snapshot_sha256") != expected_snapshot_sha256:
            raise ResourceControllerError("cgroup capability snapshot hash mismatch")
        path = _require_string(values.get("path"), "cgroup.path")
        parsed_path = PurePosixPath(path)
        if not parsed_path.is_absolute() or ".." in parsed_path.parts:
            raise ResourceControllerError("cgroup path is malformed")
        if container_id not in path:
            raise ResourceControllerError("cgroup path is not bound to the container")
        identity = _require_string(values.get("identity"), "cgroup.identity")
        if not _HEX_SHA256.fullmatch(identity):
            raise ResourceControllerError("cgroup identity is malformed")
        files = _require_mapping(values.get("files"), "cgroup.files")
        if values.get("sample_phase") != "post-exit-pre-removal":
            raise ResourceControllerError("cgroup evidence is not a post-exit sample")
        sampled_at = _require_plain_int(
            values.get("sampled_monotonic_ns"),
            "cgroup.sampled_monotonic_ns",
            minimum=0,
        )
        return {
            **values,
            "path": path,
            "identity": identity,
            "files": files,
            "sample_phase": "post-exit-pre-removal",
            "sampled_monotonic_ns": sampled_at,
        }

    def _require_invocation(self, invocation: SolverInvocation) -> None:
        if not isinstance(invocation, SolverInvocation):
            raise ResourceControllerError("invocation must be a SolverInvocation")

    def _validate_inspect(
        self, invocation: SolverInvocation, inspect: Mapping[str, Any]
    ) -> None:
        container_id = _require_string(inspect.get("Id"), "inspect.Id")
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise ResourceControllerError("inspect.Id must be a full Docker ID")
        if inspect.get("Name") != f"/{self.container_name(invocation)}":
            raise ResourceControllerError("inspect.Name does not match the run")
        if not _IMAGE_ID.fullmatch(
            _require_string(inspect.get("Image"), "inspect.Image")
        ):
            raise ResourceControllerError("inspect.Image is not an immutable image ID")

        config = _require_mapping(inspect.get("Config"), "inspect.Config")
        if config.get("Image") != invocation.image:
            raise ResourceControllerError(
                "inspect.Config.Image does not match invocation"
            )
        if config.get("WorkingDir") != invocation.container_run_directory:
            raise ResourceControllerError("inspect.Config.WorkingDir does not match")
        if config.get("Entrypoint") != [TRUSTED_SUPERVISOR_ENTRYPOINT]:
            raise ResourceControllerError("inspect.Config.Entrypoint does not match")
        if config.get("Cmd") != list(self.supervisor_command(invocation)):
            raise ResourceControllerError("inspect.Config.Cmd does not match")
        labels = _require_mapping(config.get("Labels"), "inspect.Config.Labels")
        for key, expected in self.expected_labels(invocation).items():
            if labels.get(key) != expected:
                raise ResourceControllerError(f"inspect label mismatch: {key}")

        state = _require_mapping(inspect.get("State"), "inspect.State")
        if _require_bool(state.get("Running"), "inspect.State.Running"):
            raise ResourceControllerError("container is still running")
        if state.get("Status") != "exited":
            raise ResourceControllerError("container state is not exited")
        if _require_plain_int(state.get("Pid"), "inspect.State.Pid", minimum=0) != 0:
            raise ResourceControllerError("container inspect reports a residual PID")
        _require_plain_int(state.get("ExitCode"), "inspect.State.ExitCode", minimum=0)
        _require_bool(state.get("OOMKilled"), "inspect.State.OOMKilled")

        host = _require_mapping(inspect.get("HostConfig"), "inspect.HostConfig")
        expected_values = {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Memory": self.profile.memory_bytes,
            "MemorySwap": self.profile.memory_swap_bytes,
            "CpusetCpus": self.profile.cpuset_cpus,
            "CpuPeriod": self.profile.cpu_period_us,
            "CpuQuota": self.profile.cpu_quota_us,
            "PidsLimit": self.profile.pids_limit,
        }
        for key, expected in expected_values.items():
            if host.get(key) != expected or (
                isinstance(expected, int)
                and not isinstance(expected, bool)
                and isinstance(host.get(key), bool)
            ):
                raise ResourceControllerError(f"inspect.HostConfig.{key} mismatch")
        if set(host.get("CapDrop") or ()) != {"ALL"}:
            raise ResourceControllerError("inspect.HostConfig.CapDrop mismatch")
        if set(host.get("SecurityOpt") or ()) != {"no-new-privileges"}:
            raise ResourceControllerError("inspect.HostConfig.SecurityOpt mismatch")
        restart = _require_mapping(
            host.get("RestartPolicy"), "inspect.HostConfig.RestartPolicy"
        )
        if restart.get("Name") != "no":
            raise ResourceControllerError("inspect.HostConfig.RestartPolicy mismatch")
        self._validate_mount_evidence(invocation, inspect.get("Mounts"))

    def _validate_mount_evidence(
        self, invocation: SolverInvocation, mounts_value: Any
    ) -> None:
        if not isinstance(mounts_value, list):
            raise ResourceControllerError("inspect.Mounts must be an array")
        expected = {
            (source, destination): False
            for source, destination in invocation.input_mounts
            + invocation.binary_mounts
        }
        expected[
            (invocation.host_run_directory, invocation.container_run_directory)
        ] = True
        observed: dict[tuple[str, str], bool] = {}
        for index, raw_mount in enumerate(mounts_value):
            mount = _require_mapping(raw_mount, f"inspect.Mounts[{index}]")
            if mount.get("Type") != "bind":
                raise ResourceControllerError(
                    "all container mounts must be bind mounts"
                )
            source = _require_string(mount.get("Source"), "inspect mount source")
            destination = _require_string(
                mount.get("Destination"), "inspect mount destination"
            )
            writable = _require_bool(mount.get("RW"), "inspect mount RW")
            key = (source, destination)
            if key in observed:
                raise ResourceControllerError("inspect.Mounts contains a duplicate")
            observed[key] = writable
        if observed != expected:
            raise ResourceControllerError(
                "inspect.Mounts does not prove exactly one writable run directory"
            )

    def _validate_supervisor(
        self,
        invocation: SolverInvocation,
        supervisor: Mapping[str, Any],
        *,
        inspect: Mapping[str, Any],
        execution: Mapping[str, Any],
        cgroup: Mapping[str, Any],
        observed_monotonic_ns: int,
    ) -> dict[str, Any]:
        if supervisor.get("schema") != RESOURCE_EVIDENCE_SCHEMA:
            raise ResourceControllerError("unsupported supervisor evidence schema")
        if supervisor.get("run_id") != invocation.run_id:
            raise ResourceControllerError("supervisor run_id mismatch")
        required_bindings = {
            "container_id": inspect.get("Id"),
            "image_reference": invocation.image,
            "image_id": inspect.get("Image"),
            "profile_sha256": self.profile.sha256,
            "invocation_sha256": invocation.sha256,
            "capability_sha256": self.capability_sha256,
            "capability_snapshot_sha256": (
                invocation.capability_snapshot_sha256
                or self.capability_snapshot_sha256
            ),
            "supervisor_sha256": self.supervisor_sha256,
            "daemon_id": self._capabilities["daemon_id"],
            "docker_context": self._capabilities["docker_context"],
            "cgroup_path": cgroup["path"],
            "cgroup_identity": cgroup["identity"],
        }
        for field_name, expected in required_bindings.items():
            if supervisor.get(field_name) != expected:
                raise ResourceControllerError(
                    f"supervisor {field_name} binding mismatch"
                )
        launched = _require_plain_int(
            supervisor.get("launched_monotonic_ns"),
            "supervisor.launched_monotonic_ns",
            minimum=0,
        )
        solver_deadline = _require_plain_int(
            supervisor.get("solver_deadline_monotonic_ns"),
            "supervisor.solver_deadline_monotonic_ns",
            minimum=0,
        )
        artifact_deadline = _require_plain_int(
            supervisor.get("artifact_deadline_monotonic_ns"),
            "supervisor.artifact_deadline_monotonic_ns",
            minimum=0,
        )
        finished = _require_plain_int(
            supervisor.get("finished_monotonic_ns"),
            "supervisor.finished_monotonic_ns",
            minimum=0,
        )
        solver_stopped = _require_plain_int(
            supervisor.get("solver_stopped_monotonic_ns"),
            "supervisor.solver_stopped_monotonic_ns",
            minimum=0,
        )
        if solver_deadline != execution["host_solver_deadline_monotonic_ns"]:
            raise ResourceControllerError("supervisor host solver deadline mismatch")
        if artifact_deadline != execution["host_artifact_deadline_monotonic_ns"]:
            raise ResourceControllerError("supervisor host artifact deadline mismatch")
        if launched < execution["host_started_monotonic_ns"]:
            raise ResourceControllerError("supervisor launch predates the host launch")
        if launched > execution["host_finished_monotonic_ns"]:
            raise ResourceControllerError("supervisor launch follows host completion")
        if launched > observed_monotonic_ns:
            raise ResourceControllerError("supervisor launch is in the future")
        if solver_stopped < launched or solver_stopped > solver_deadline:
            raise ResourceControllerError("solver was not stopped before cutoff")
        sampled_at = cgroup["sampled_monotonic_ns"]
        if sampled_at < max(finished, execution["host_finished_monotonic_ns"]):
            raise ResourceControllerError(
                "cgroup evidence was not sampled after container exit"
            )
        if sampled_at > observed_monotonic_ns:
            raise ResourceControllerError(
                "cgroup evidence was sampled after the trusted observation window"
            )
        if finished < solver_stopped or finished > artifact_deadline:
            raise ResourceControllerError(
                "supervisor completion is outside the deadline"
            )
        if finished > execution["host_finished_monotonic_ns"]:
            raise ResourceControllerError(
                "supervisor completion follows host completion"
            )
        if finished > observed_monotonic_ns:
            raise ResourceControllerError("supervisor completion is in the future")
        if _require_bool(
            supervisor.get("deadline_exceeded"), "supervisor.deadline_exceeded"
        ):
            raise ResourceControllerError("supervisor records a deadline violation")
        if not _require_bool(
            supervisor.get("cleanup_complete"), "supervisor.cleanup_complete"
        ):
            raise ResourceControllerError("supervisor cleanup is incomplete")
        residual = _require_plain_int(
            supervisor.get("residual_processes"),
            "supervisor.residual_processes",
            minimum=0,
        )
        if residual != 0:
            raise ResourceControllerError("supervisor reports residual processes")

        committed = _require_bool(
            supervisor.get("artifact_committed"), "supervisor.artifact_committed"
        )
        committed_at = supervisor.get("artifact_committed_monotonic_ns")
        artifact_sha256 = supervisor.get("artifact_sha256")
        artifact_size = supervisor.get("artifact_size_bytes")
        artifact_mtime = supervisor.get("artifact_mtime_ns")
        artifact_identity = supervisor.get("artifact_file_identity")
        if committed:
            committed_at = _require_plain_int(
                committed_at,
                "supervisor.artifact_committed_monotonic_ns",
                minimum=0,
            )
            if committed_at < launched or committed_at > finished:
                raise ResourceControllerError(
                    "artifact was not committed before supervisor completion"
                )
            if not isinstance(artifact_sha256, str) or not _HEX_SHA256.fullmatch(
                artifact_sha256
            ):
                raise ResourceControllerError(
                    "committed artifact hash is missing or malformed"
                )
            artifact_size = _require_plain_int(
                artifact_size, "supervisor.artifact_size_bytes", minimum=0
            )
            artifact_mtime = _require_plain_int(
                artifact_mtime, "supervisor.artifact_mtime_ns", minimum=0
            )
            if not isinstance(artifact_identity, str) or not _HEX_SHA256.fullmatch(
                artifact_identity
            ):
                raise ResourceControllerError(
                    "committed artifact file identity is missing or malformed"
                )
            if (
                supervisor.get("artifact_relative_path")
                != invocation.artifact_relative_path
            ):
                raise ResourceControllerError("supervisor artifact path mismatch")
        elif any(
            value is not None
            for value in (
                committed_at,
                artifact_sha256,
                artifact_size,
                artifact_mtime,
                artifact_identity,
                supervisor.get("artifact_relative_path"),
            )
        ):
            raise ResourceControllerError("uncommitted artifact must not have metadata")
        return {
            "elapsed_monotonic_ns": finished - launched,
            "artifact_committed": committed,
            "artifact_sha256": artifact_sha256,
            "artifact_size_bytes": artifact_size,
            "artifact_mtime_ns": artifact_mtime,
            "artifact_file_identity": artifact_identity,
        }


def _expand_cpuset(value: str) -> set[int]:
    result: set[int] = set()
    for part in value.split(","):
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            result.update(range(int(start_text), int(end_text) + 1))
        else:
            result.add(int(part))
    return result


def _command_returncode(result: Any) -> int:
    if isinstance(result, Mapping):
        value = result.get("returncode")
    else:
        value = getattr(result, "returncode", None)
    return _require_plain_int(value, "command returncode", minimum=0)


def _command_stdout(result: Any) -> str:
    if isinstance(result, Mapping):
        value = result.get("stdout", "")
    else:
        value = getattr(result, "stdout", "")
    if not isinstance(value, str):
        raise ResourceControllerError("command stdout must be text")
    return value


def _command_stderr(result: Any) -> str:
    if isinstance(result, Mapping):
        value = result.get("stderr", "")
    else:
        value = getattr(result, "stderr", "")
    if not isinstance(value, str):
        raise ResourceControllerError("command stderr must be text")
    return value


def _parse_scalar_cgroup_file(files: Mapping[str, str], name: str) -> int:
    if name not in files:
        raise ResourceControllerError(f"cgroup evidence is missing {name}")
    raw = files[name]
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+\n?", raw):
        raise ResourceControllerError(f"cgroup evidence {name} is malformed")
    return int(raw.strip())


def _parse_counter_cgroup_file(files: Mapping[str, str], name: str) -> dict[str, int]:
    if name not in files:
        raise ResourceControllerError(f"cgroup evidence is missing {name}")
    raw = files[name]
    if not isinstance(raw, str) or not raw:
        raise ResourceControllerError(f"cgroup evidence {name} is malformed")
    counters: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_.]+", parts[0]):
            raise ResourceControllerError(f"cgroup evidence {name} is malformed")
        if not parts[1].isdigit() or parts[0] in counters:
            raise ResourceControllerError(f"cgroup evidence {name} is malformed")
        counters[parts[0]] = int(parts[1])
    if not counters:
        raise ResourceControllerError(f"cgroup evidence {name} is empty")
    return dict(sorted(counters.items()))


def _parse_limit_cgroup_file(files: Mapping[str, str], name: str) -> int:
    if name not in files:
        raise ResourceControllerError(f"cgroup evidence is missing {name}")
    raw = files[name]
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+\n?", raw):
        raise ResourceControllerError(f"cgroup evidence {name} is malformed")
    return int(raw.strip())


def _parse_cpu_max(files: Mapping[str, str]) -> str:
    name = "cpu.max"
    if name not in files:
        raise ResourceControllerError(f"cgroup evidence is missing {name}")
    raw = files[name]
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+ [0-9]+\n?", raw):
        raise ResourceControllerError(f"cgroup evidence {name} is malformed")
    return raw.strip()


def _parse_cpuset_file(files: Mapping[str, str], name: str) -> str:
    if name not in files:
        raise ResourceControllerError(f"cgroup evidence is missing {name}")
    raw = files[name]
    if not isinstance(raw, str):
        raise ResourceControllerError(f"cgroup evidence {name} is malformed")
    try:
        return _canonical_cpuset(raw.strip())
    except ResourceControllerError as exc:
        raise ResourceControllerError(f"cgroup evidence {name} is malformed") from exc


__all__ = [
    "CAPABILITY_EVIDENCE_SCHEMA",
    "DEFAULT_CAPABILITY_MAX_AGE_SECONDS",
    "CGROUP_EVIDENCE_RELATIVE_PATH",
    "RESOURCE_EVIDENCE_SCHEMA",
    "DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA",
    "resource_evidence_sha256",
    "RESOURCE_PROFILE_SCHEMA",
    "TRUSTED_SUPERVISOR_ENTRYPOINT",
    "SUPERVISOR_EVIDENCE_RELATIVE_PATH",
    "ArtifactSnapshot",
    "DockerCgroupV2Controller",
    "ExecutionObservation",
    "LocalFileSystem",
    "ResourceControllerError",
    "ResourceEvidence",
    "ResourceProfile",
    "SolverInvocation",
]
