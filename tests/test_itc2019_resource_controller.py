from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from benchmarks.itc2019_resource_controller import (
    CAPABILITY_EVIDENCE_SCHEMA,
    DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    RESOURCE_EVIDENCE_SCHEMA,
    TRUSTED_SUPERVISOR_ENTRYPOINT,
    DockerCgroupV2Controller,
    ExecutionObservation,
    ResourceEvidence,
    ResourceControllerError,
    ResourceProfile,
    SolverInvocation,
    resource_evidence_sha256,
)


IMAGE = "registry.example/planora/fair@sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64
ARTIFACT_SHA256 = "d" * 64
SUPERVISOR_SHA256 = "e" * 64
DAEMON_ID = "f" * 64
CGROUP_IDENTITY = "1" * 64
NOW_NS = 2_000_000_000_000_000_000


def _json_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _profile(**overrides) -> ResourceProfile:
    values = {
        "wall_time_seconds": 60.0,
        "artifact_grace_seconds": 5.0,
        "memory_bytes": 512 * 1024 * 1024,
        "memory_swap_bytes": 640 * 1024 * 1024,
        "cpuset_cpus": "1,0",
        "cpu_period_us": 100_000,
        "cpu_quota_us": 100_000,
        "pids_limit": 128,
    }
    values.update(overrides)
    return ResourceProfile(**values)


def _capabilities(**overrides):
    values = {
        "schema": CAPABILITY_EVIDENCE_SCHEMA,
        "docker_available": True,
        "server_os": "linux",
        "cgroup_version": 2,
        "supports_memory_limit": True,
        "supports_swap_limit": True,
        "supports_cpu_quota": True,
        "supports_cpuset": True,
        "supports_pids_limit": True,
        "supports_read_only_rootfs": True,
        "total_memory_bytes": 8 * 1024 * 1024 * 1024,
        "available_cpuset_cpus": "0-7",
        "docker_server_version": "29.6.1",
        "available_swap_bytes": 4 * 1024 * 1024 * 1024,
        "daemon_id": DAEMON_ID,
        "docker_context": "desktop-linux",
        "captured_at_unix_ns": NOW_NS - 1_000_000_000,
    }
    values.update(overrides)
    return values


def _invocation(tmp_path, **overrides) -> SolverInvocation:
    values = {
        "run_id": "case-a__planora__seed-17__rep-01",
        "solver": "planora",
        "image": IMAGE,
        "argv": ("/opt/solver/bin", "--solver", "planora"),
        "host_run_directory": str(tmp_path / "run"),
        "input_mounts": ((str(tmp_path / "input.xml"), "/inputs/case.xml"),),
        "binary_mounts": ((str(tmp_path / "solver"), "/opt/solver/bin"),),
    }
    values.update(overrides)
    return SolverInvocation(**values)


def _controller(profile=None, capabilities=None, **overrides):
    values = {
        "profile": profile or _profile(),
        "capability_evidence": capabilities or _capabilities(),
        "supervisor_sha256": SUPERVISOR_SHA256,
        "monotonic_ns": lambda: 100_000_000_000,
        "wall_time_ns": lambda: NOW_NS + 70_000_000_000,
    }
    values.update(overrides)
    return DockerCgroupV2Controller(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"wall_time_seconds": 0},
        {"wall_time_seconds": float("nan")},
        {"artifact_grace_seconds": -0.01},
        {"memory_bytes": True},
        {"memory_bytes": 0},
        {"memory_swap_bytes": 1},
        {"cpuset_cpus": "0,0"},
        {"cpuset_cpus": "2-1"},
        {"cpu_period_us": 999},
        {"cpu_quota_us": -1},
        {"pids_limit": 0},
    ],
)
def test_resource_profile_rejects_invalid_limits(overrides) -> None:
    with pytest.raises(ResourceControllerError):
        _profile(**overrides)


def test_resource_profile_is_immutable_and_canonical() -> None:
    profile = _profile()

    assert profile.cpuset_cpus == "0-1"
    assert len(profile.sha256) == 64
    with pytest.raises(FrozenInstanceError):
        profile.memory_bytes = 1


def test_resource_evidence_hash_is_shared_across_supported_schemas() -> None:
    descriptive = {
        "schema": DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
        "run_id": "run-a",
        "nested": {"b": 2, "a": 1},
    }
    reordered = {
        "nested": {"a": 1, "b": 2},
        "run_id": "run-a",
        "schema": DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    }

    assert resource_evidence_sha256(descriptive) == resource_evidence_sha256(
        reordered
    )
    with pytest.raises(ResourceControllerError, match="unsupported"):
        resource_evidence_sha256({"schema": "unsupported"})


@pytest.mark.parametrize(
    "image",
    (
        "registry.example/planora/fair:latest",
        "registry.example/planora/fair:1.0",
        "registry.example/planora/fair",
        "registry.example/planora/fair@sha256:short",
        "registry.example/planora/fair@sha256:" + "A" * 64,
    ),
)
def test_solver_invocation_rejects_mutable_or_malformed_images(tmp_path, image) -> None:
    with pytest.raises(ResourceControllerError, match="immutable"):
        _invocation(tmp_path, image=image)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"docker_available": False}, "docker_available"),
        ({"server_os": "windows"}, "Linux containers"),
        ({"cgroup_version": 1}, "cgroup v2"),
        ({"supports_swap_limit": False}, "supports_swap_limit"),
        ({"supports_cpu_quota": False}, "supports_cpu_quota"),
        ({"supports_cpuset": False}, "supports_cpuset"),
        ({"available_cpuset_cpus": "2-7"}, "not available"),
        ({"total_memory_bytes": 1024}, "less memory"),
    ],
)
def test_controller_rejects_unsupported_capability_evidence(overrides, message) -> None:
    with pytest.raises(ResourceControllerError, match=message):
        _controller(capabilities=_capabilities(**overrides))


def _limit_options(command: tuple[str, ...]) -> tuple[str, ...]:
    prefixes = (
        "--network=",
        "--memory=",
        "--memory-swap=",
        "--cpuset-cpus=",
        "--cpu-period=",
        "--cpu-quota=",
        "--pids-limit=",
        "--restart=",
    )
    exact = {
        "--pull=never",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    }
    return tuple(item for item in command if item in exact or item.startswith(prefixes))


def test_commands_are_deterministic_and_apply_equal_external_limits(tmp_path) -> None:
    controller = _controller()
    first = _invocation(tmp_path)
    second = _invocation(
        tmp_path,
        run_id="case-a__unitime__seed-17__rep-01",
        solver="unitime",
        argv=("/opt/solver/bin", "--solver", "unitime"),
        input_mounts=((str(tmp_path / "other.xml"), "/inputs/case.xml"),),
    )

    first_spec = controller.command_specification(first)
    assert first_spec == controller.command_specification(first)
    assert _limit_options(first_spec[0]) == _limit_options(
        controller.docker_create_command(second)
    )
    assert _limit_options(first_spec[0]) == (
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--memory={controller.profile.memory_bytes}",
        f"--memory-swap={controller.profile.memory_swap_bytes}",
        "--cpuset-cpus=0-1",
        "--cpu-period=100000",
        "--cpu-quota=100000",
        "--pids-limit=128",
        "--restart=no",
    )
    create = first_spec[0]
    assert create[:2] == ("docker", "create")
    assert f"--entrypoint={TRUSTED_SUPERVISOR_ENTRYPOINT}" in create
    assert first.argv[0] not in next(
        item for item in create if item.startswith("--entrypoint=")
    )
    image_index = create.index(first.image)
    assert create[image_index + 1 :] == controller.supervisor_command(first)
    assert (
        f"--mount=type=bind,src={first.input_mounts[0][0]},"
        "dst=/inputs/case.xml,readonly"
    ) in create
    assert (
        f"--mount=type=bind,src={first.binary_mounts[0][0]},"
        "dst=/opt/solver/bin,readonly"
    ) in create
    assert (
        f"--mount=type=bind,src={first.host_run_directory},dst=/run/planora"
    ) in create
    writable_mounts = [
        argument
        for argument in create
        if argument.startswith("--mount=") and not argument.endswith(",readonly")
    ]
    assert writable_mounts == [
        f"--mount=type=bind,src={first.host_run_directory},dst=/run/planora"
    ]
    assert first_spec[1] == (
        "docker",
        "start",
        "--attach",
        controller.container_name(first),
    )


def test_execution_is_injectable_and_fail_closed(tmp_path) -> None:
    observed = []
    invocation = _invocation(tmp_path)
    Path(invocation.host_run_directory).mkdir()

    def executor(command, *, timeout=None):
        observed.append((command, timeout))
        if command[1] == "create":
            return SimpleNamespace(returncode=0, stdout=CONTAINER_ID + "\n")
        if command[1] == "inspect":
            inspect_calls = sum(item[0][1] == "inspect" for item in observed)
            if inspect_calls == 3:
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "Error: No such container: "
                        f"{controller.container_name(invocation)}\n"
                    ),
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([_inspect(controller, invocation)]),
            )
        return SimpleNamespace(returncode=0, stdout="")

    controller = _controller(
        executor=executor,
        monotonic_ns=lambda: 1_000_000_000,
    )

    observation = controller.execute(invocation)

    assert observation.cleanup_complete
    assert observation.residual_processes == 0
    assert [command[0][1] for command in observed] == [
        "create",
        "inspect",
        "start",
        "inspect",
        "rm",
        "inspect",
    ]
    assert observed[2][1] == pytest.approx(65.0)

    failing_commands = []

    def failing_executor(command, *, timeout=None):
        failing_commands.append((command, timeout))
        return SimpleNamespace(returncode=1, stdout="")

    failing = _controller(
        executor=failing_executor,
        monotonic_ns=lambda: 1_000_000_000,
    )
    with pytest.raises(ResourceControllerError, match="docker create failed"):
        failing.execute(invocation)
    assert [command[0][1] for command in failing_commands] == [
        "create",
        "rm",
        "inspect",
    ]


def test_post_exit_cgroup_probe_runs_before_removal_and_is_retained(tmp_path) -> None:
    invocation = _invocation(tmp_path)
    Path(invocation.host_run_directory).mkdir()
    observed = []
    captured = {"sample_phase": "post-exit-pre-removal", "files": {}}

    def executor(command, *, timeout=None):
        observed.append(command)
        operation = command[1]
        if operation == "create":
            return SimpleNamespace(returncode=0, stdout=CONTAINER_ID + "\n")
        if operation == "inspect":
            inspect_calls = sum(item[1] == "inspect" for item in observed)
            if inspect_calls == 4:
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "Error: No such container: "
                        f"{controller.container_name(invocation)}\n"
                    ),
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([_inspect(controller, invocation)]),
            )
        return SimpleNamespace(returncode=0, stdout="")

    provider_calls = []

    def cgroup_provider(bound_invocation, inspect):
        provider_calls.append((bound_invocation, inspect))
        return captured

    controller = _controller(
        executor=executor,
        monotonic_ns=lambda: 1_000_000_000,
        post_exit_cgroup_evidence_provider=cgroup_provider,
    )

    observation = controller.execute(invocation)

    assert observation.cleanup_complete is True
    assert len(provider_calls) == 1
    assert provider_calls[0][0] == invocation
    assert provider_calls[0][1]["State"]["Status"] == "exited"
    assert controller.last_post_exit_cgroup_evidence == captured
    assert [command[1] for command in observed] == [
        "create",
        "inspect",
        "start",
        "inspect",
        "inspect",
        "rm",
        "inspect",
    ]


def test_post_exit_cgroup_probe_failure_still_cleans_up(tmp_path) -> None:
    invocation = _invocation(tmp_path)
    Path(invocation.host_run_directory).mkdir()
    observed = []

    def executor(command, *, timeout=None):
        observed.append(command)
        if command[1] == "create":
            return SimpleNamespace(returncode=0, stdout=CONTAINER_ID + "\n")
        if command[1] == "inspect":
            inspect_calls = sum(item[1] == "inspect" for item in observed)
            if inspect_calls == 4:
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "Error: No such container: "
                        f"{controller.container_name(invocation)}\n"
                    ),
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([_inspect(controller, invocation)]),
            )
        return SimpleNamespace(returncode=0, stdout="")

    def failing_provider(*_args):
        raise RuntimeError("probe failed")

    controller = _controller(
        executor=executor,
        monotonic_ns=lambda: 1_000_000_000,
        post_exit_cgroup_evidence_provider=failing_provider,
    )

    with pytest.raises(ResourceControllerError, match="capture failed"):
        controller.execute(invocation)
    assert observed[-2][1] == "rm"
    assert observed[-1][1] == "inspect"


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("[]", "Error response from daemon: permission denied"),
        ("[]", "Error response from daemon: No such container: wrong-name"),
        ("unexpected", "Error: No such container: expected"),
        ("", "Error response from daemon: No such container: expected\nextra"),
    ],
)
def test_absence_proof_rejects_ambiguous_docker_errors(
    tmp_path, stdout: str, stderr: str
) -> None:
    invocation = _invocation(tmp_path)
    controller = _controller()

    result = SimpleNamespace(returncode=1, stdout=stdout, stderr=stderr)

    assert controller._inspect_proves_absent(result, invocation) is False


def test_absence_proof_accepts_only_legacy_and_docker_29_exact_spellings(
    tmp_path,
) -> None:
    invocation = _invocation(tmp_path)
    controller = _controller()
    name = controller.container_name(invocation)

    legacy = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr=f"Error: No such container: {name}\n",
    )
    docker_29 = SimpleNamespace(
        returncode=1,
        stdout="[]\n",
        stderr=f"Error response from daemon: No such container: {name}\n",
    )

    assert controller._inspect_proves_absent(legacy, invocation) is True
    assert controller._inspect_proves_absent(docker_29, invocation) is True


def _inspect(controller, invocation):
    return {
        "Id": CONTAINER_ID,
        "Name": "/" + controller.container_name(invocation),
        "Image": IMAGE_ID,
        "Config": {
            "Image": invocation.image,
            "WorkingDir": invocation.container_run_directory,
            "Entrypoint": [TRUSTED_SUPERVISOR_ENTRYPOINT],
            "Cmd": list(controller.supervisor_command(invocation)),
            "Labels": {
                "unrelated.image.label": "allowed",
                **controller.expected_labels(invocation),
            },
        },
        "State": {
            "Status": "exited",
            "Running": False,
            "Pid": 0,
            "ExitCode": 0,
            "OOMKilled": False,
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Memory": controller.profile.memory_bytes,
            "MemorySwap": controller.profile.memory_swap_bytes,
            "CpusetCpus": controller.profile.cpuset_cpus,
            "CpuPeriod": controller.profile.cpu_period_us,
            "CpuQuota": controller.profile.cpu_quota_us,
            "PidsLimit": controller.profile.pids_limit,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "Mounts": [
            *(
                {
                    "Type": "bind",
                    "Source": source,
                    "Destination": destination,
                    "RW": False,
                }
                for source, destination in (
                    invocation.input_mounts + invocation.binary_mounts
                )
            ),
            {
                "Type": "bind",
                "Source": invocation.host_run_directory,
                "Destination": invocation.container_run_directory,
                "RW": True,
            },
        ],
    }


def _cgroup_files():
    return {
        "memory.current": "1048576\n",
        "memory.peak": "2097152\n",
        "memory.swap.current": "0\n",
        "memory.swap.peak": "4096\n",
        "memory.events": (
            "low 0\nhigh 0\nmax 1\noom 0\noom_kill 0\noom_group_kill 0\n"
        ),
        "memory.swap.events": "high 0\nmax 0\nfail 0\n",
        "memory.max": str(512 * 1024 * 1024) + "\n",
        "memory.swap.max": str(128 * 1024 * 1024) + "\n",
        "cpu.stat": (
            "usage_usec 12000\nuser_usec 10000\nsystem_usec 2000\n"
            "nr_periods 4\nnr_throttled 1\nthrottled_usec 500\n"
        ),
        "pids.current": "0\n",
        "pids.peak": "7\n",
        "cpu.max": "100000 100000\n",
        "cpuset.cpus.effective": "0-1\n",
        "pids.max": "128\n",
        "cgroup.procs": "",
    }


def _execution(profile, invocation):
    started = 1_000_000_000
    solver_deadline = started + round(profile.wall_time_seconds * 1e9)
    artifact_deadline = solver_deadline + round(profile.artifact_grace_seconds * 1e9)
    return ExecutionObservation(
        run_id=invocation.run_id,
        container_id=CONTAINER_ID,
        image_id=IMAGE_ID,
        host_started_monotonic_ns=started,
        host_solver_deadline_monotonic_ns=solver_deadline,
        host_artifact_deadline_monotonic_ns=artifact_deadline,
        host_finished_monotonic_ns=started + 4_000_000_000,
        host_started_wall_ns=NOW_NS,
        host_artifact_deadline_wall_ns=NOW_NS + artifact_deadline - started,
        attach_returncode=0,
        timed_out=False,
        cleanup_complete=True,
        residual_processes=0,
    )


def _cgroup(controller, invocation):
    return {
        "run_id": invocation.run_id,
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "profile_sha256": controller.profile.sha256,
        "supervisor_sha256": SUPERVISOR_SHA256,
        "capability_snapshot_sha256": (
            invocation.capability_snapshot_sha256
            or controller.capability_snapshot_sha256
        ),
        "path": f"/docker/{CONTAINER_ID}",
        "identity": CGROUP_IDENTITY,
        "sample_phase": "post-exit-pre-removal",
        "sampled_monotonic_ns": 5_100_000_000,
        "files": _cgroup_files(),
    }


def _supervisor(controller, invocation, execution, snapshot):
    launched = execution.host_started_monotonic_ns + 100_000_000
    return {
        "schema": RESOURCE_EVIDENCE_SCHEMA,
        "run_id": invocation.run_id,
        "container_id": CONTAINER_ID,
        "image_reference": invocation.image,
        "image_id": IMAGE_ID,
        "profile_sha256": controller.profile.sha256,
        "invocation_sha256": invocation.sha256,
        "capability_sha256": controller.capability_sha256,
        "capability_snapshot_sha256": (
            invocation.capability_snapshot_sha256
            or controller.capability_snapshot_sha256
        ),
        "supervisor_sha256": SUPERVISOR_SHA256,
        "daemon_id": DAEMON_ID,
        "docker_context": "desktop-linux",
        "cgroup_path": f"/docker/{CONTAINER_ID}",
        "cgroup_identity": CGROUP_IDENTITY,
        "launched_monotonic_ns": launched,
        "solver_deadline_monotonic_ns": execution.host_solver_deadline_monotonic_ns,
        "artifact_deadline_monotonic_ns": execution.host_artifact_deadline_monotonic_ns,
        "solver_stopped_monotonic_ns": launched + 2_000_000_000,
        "finished_monotonic_ns": launched + 3_000_000_000,
        "deadline_exceeded": False,
        "cleanup_complete": True,
        "residual_processes": 0,
        "artifact_committed": True,
        "artifact_committed_monotonic_ns": launched + 2_000_000_000,
        "artifact_relative_path": invocation.artifact_relative_path,
        "artifact_sha256": snapshot.sha256,
        "artifact_size_bytes": snapshot.size_bytes,
        "artifact_mtime_ns": snapshot.mtime_ns,
        "artifact_file_identity": snapshot.file_identity,
    }


def _valid_evidence(tmp_path):
    capture = NOW_NS - 10_000_000_000

    def provider():
        nonlocal capture
        capture += 1_000_000_000
        return _capabilities(captured_at_unix_ns=capture)

    controller = _controller(
        capabilities=_capabilities(captured_at_unix_ns=NOW_NS - 11_000_000_000),
        capability_evidence_provider=provider,
    )
    capability_snapshot = controller.refresh_capability_evidence()
    invocation = _invocation(
        tmp_path, capability_snapshot_sha256=_json_sha256(capability_snapshot)
    )
    controller, invocation, supplied = _valid_evidence_for(controller, invocation)
    supplied["capability_snapshot"] = capability_snapshot
    return controller, invocation, supplied


def _valid_evidence_for(controller, invocation):
    run_directory = Path(invocation.host_run_directory)
    run_directory.mkdir()
    artifact = run_directory / invocation.artifact_relative_path
    artifact.write_bytes(b"valid solution")
    os.utime(artifact, ns=(NOW_NS + 2_000_000_000,) * 2)
    execution = _execution(controller.profile, invocation)
    snapshot = controller._filesystem.read_artifact(
        str(run_directory.resolve()), invocation.artifact_relative_path
    )
    return (
        controller,
        invocation,
        {
            "inspect": _inspect(controller, invocation),
            "execution": execution,
            "cgroup": _cgroup(controller, invocation),
            "supervisor": _supervisor(controller, invocation, execution, snapshot),
            "cleanup_outcomes": (
                {
                    "operation": "absence-verification",
                    "returncode": 1,
                    "error": None,
                    "absence_verified": True,
                },
            ),
        },
    )


def test_valid_evidence_is_normalized_and_hashes_canonically(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    first = controller.parse_evidence(invocation, **supplied)

    reordered = {
        "inspect": dict(reversed(list(supplied["inspect"].items()))),
        "execution": supplied["execution"],
        "cgroup": {
            **supplied["cgroup"],
            "files": dict(reversed(list(supplied["cgroup"]["files"].items()))),
        },
        "supervisor": dict(reversed(list(supplied["supervisor"].items()))),
        "capability_snapshot": dict(
            reversed(list(supplied["capability_snapshot"].items()))
        ),
        "cleanup_outcomes": supplied["cleanup_outcomes"],
    }
    second = controller.parse_evidence(invocation, **reordered)

    assert first == second
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert first.memory_peak_bytes == 2_097_152
    assert first.memory_swap_peak_bytes == 4_096
    assert dict(first.memory_events)["max"] == 1
    assert dict(first.cpu_stat)["nr_throttled"] == 1
    assert first.artifact_sha256 == hashlib.sha256(b"valid solution").hexdigest()
    assert first.claim_grade_ready is True
    assert first.capability_snapshot_sha256 == invocation.capability_snapshot_sha256
    assert dict(first.capability_snapshot) == supplied["capability_snapshot"]
    with pytest.raises(FrozenInstanceError):
        first.exit_code = 7


def test_resource_evidence_cannot_be_forged_from_parsed_or_serialized_fields(
    tmp_path,
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    parsed = controller.parse_evidence(invocation, **supplied)
    reconstructed = {
        field.name: getattr(parsed, field.name) for field in fields(ResourceEvidence)
    }

    with pytest.raises(ResourceControllerError, match="parse provenance"):
        ResourceEvidence(**reconstructed)

    assert controller.authorizes_claim_grade_evidence(parsed.to_canonical_dict())
    forged = parsed.to_canonical_dict()
    forged["memory_peak_bytes"] += 1
    assert not controller.authorizes_claim_grade_evidence(forged)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda supplied: supplied.update(
                execution=replace(
                    supplied["execution"], host_finished_monotonic_ns=999_999_999
                )
            ),
            "completion predates host launch",
        ),
        (
            lambda supplied: supplied["supervisor"].update(
                launched_monotonic_ns=5_000_000_001
            ),
            "launch follows host completion",
        ),
        (
            lambda supplied: supplied["supervisor"].update(
                finished_monotonic_ns=1_050_000_000
            ),
            "completion is outside",
        ),
        (
            lambda supplied: supplied["cgroup"].update(
                sampled_monotonic_ns=4_999_999_999
            ),
            "not sampled after container exit",
        ),
        (
            lambda supplied: supplied["cgroup"].update(
                sampled_monotonic_ns=100_000_000_001
            ),
            "trusted observation window",
        ),
        (
            lambda supplied: supplied.update(
                execution=replace(
                    supplied["execution"],
                    host_finished_monotonic_ns=100_000_000_001,
                    host_solver_deadline_monotonic_ns=160_000_000_001,
                    host_artifact_deadline_monotonic_ns=165_000_000_001,
                    host_started_monotonic_ns=100_000_000_001,
                )
            ),
            "future",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"cpu.stat": "usage_usec -1\n"}
            ),
            "malformed",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"memory.current": "2097153\n"}
            ),
            "memory.current exceeds memory.peak",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"memory.swap.current": "4097\n"}
            ),
            "memory.swap.current exceeds memory.swap.peak",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"pids.current": "8\n"}
            ),
            "pids.current exceeds pids.peak",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {
                    "cpu.stat": (
                        "usage_usec 1\nuser_usec 1\nsystem_usec 1\n"
                        "nr_periods 4\nnr_throttled 1\nthrottled_usec 1\n"
                    )
                }
            ),
            "cpu.stat counters are inconsistent",
        ),
        (
            lambda supplied: supplied["supervisor"].update(
                artifact_committed_monotonic_ns=4_200_000_001
            ),
            "before supervisor completion",
        ),
    ),
)
def test_authoritative_parser_rejects_twelve_impossible_states(
    tmp_path, mutation, message
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    mutation(supplied)

    with pytest.raises(ResourceControllerError, match=message):
        controller.parse_evidence(invocation, **supplied)


def test_authoritative_parser_rejects_inconsistent_zero_counters(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    supplied["cgroup"]["files"]["cpu.stat"] = (
        "usage_usec 0\nuser_usec 0\nsystem_usec 0\n"
        "nr_periods 0\nnr_throttled 1\nthrottled_usec 1\n"
    )

    with pytest.raises(ResourceControllerError, match="period counters are inconsistent"):
        controller.parse_evidence(invocation, **supplied)


def test_refreshable_snapshot_is_bound_and_direct_parse_is_claim_grade(tmp_path) -> None:
    baseline = _capabilities(captured_at_unix_ns=NOW_NS - 3_000_000_000)
    snapshots = iter(
        (
            _capabilities(captured_at_unix_ns=NOW_NS - 2_000_000_000),
            _capabilities(captured_at_unix_ns=NOW_NS - 1_000_000_000),
        )
    )
    controller = _controller(
        capabilities=baseline,
        capability_evidence_provider=lambda: next(snapshots),
    )
    run_snapshot = controller.refresh_capability_evidence()
    invocation = _invocation(
        tmp_path, capability_snapshot_sha256=_json_sha256(run_snapshot)
    )
    controller, invocation, supplied = _valid_evidence_for(controller, invocation)
    supplied["capability_snapshot"] = run_snapshot

    evidence = controller.parse_evidence(invocation, **supplied)

    assert evidence.claim_grade_ready is True
    assert evidence.capability_snapshot_sha256 == _json_sha256(run_snapshot)
    assert evidence.post_exit_cgroup_sampled_monotonic_ns == 5_100_000_000
    assert any(item[3] for item in evidence.cleanup_outcomes)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda supplied: supplied["cgroup"].pop("capability_snapshot_sha256"),
            "snapshot hash mismatch",
        ),
        (
            lambda supplied: supplied["supervisor"].update(
                {"capability_snapshot_sha256": "0" * 64}
            ),
            "snapshot_sha256 binding mismatch",
        ),
        (
            lambda supplied: supplied["cgroup"].update({"sample_phase": "pre-exit"}),
            "not a post-exit sample",
        ),
        (
            lambda supplied: supplied["cgroup"].update(
                {"sampled_monotonic_ns": 4_999_999_999}
            ),
            "not sampled after container exit",
        ),
        (
            lambda supplied: supplied.update(
                {
                    "cleanup_outcomes": (
                        {
                            "operation": "remove",
                            "returncode": 0,
                            "error": None,
                            "absence_verified": False,
                        },
                    )
                }
            ),
            "verified absence proof",
        ),
    ),
)
def test_direct_true_transition_rejects_missing_or_forged_evidence(
    tmp_path, mutation, message
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    mutation(supplied)

    with pytest.raises(ResourceControllerError, match=message):
        controller.parse_evidence(invocation, **supplied)


def test_refresh_rejects_failure_replay_daemon_drift_and_downgrade() -> None:
    baseline = _capabilities(captured_at_unix_ns=NOW_NS - 4_000_000_000)

    def assert_rejected(snapshot_or_error, message: str) -> None:
        def provider():
            if isinstance(snapshot_or_error, BaseException):
                raise snapshot_or_error
            return snapshot_or_error

        controller = _controller(
            capabilities=baseline,
            capability_evidence_provider=provider,
        )
        with pytest.raises(ResourceControllerError, match=message):
            controller.refresh_capability_evidence()

    assert_rejected(RuntimeError("probe failed"), "refresh failed")
    assert_rejected(baseline, "did not advance")
    assert_rejected(
        _capabilities(
            captured_at_unix_ns=NOW_NS - 3_000_000_000,
            daemon_id="0" * 64,
        ),
        "daemon identity changed",
    )
    assert_rejected(
        _capabilities(
            captured_at_unix_ns=NOW_NS - 3_000_000_000,
            available_cpuset_cpus="0-6",
        ),
        "downgraded or drifted",
    )


def test_capability_identity_is_stable_while_snapshot_freshness_advances() -> None:
    older = _capabilities(captured_at_unix_ns=NOW_NS - 4_000_000_000)
    newer = _capabilities(captured_at_unix_ns=NOW_NS - 3_000_000_000)
    first = _controller(capabilities=older, capability_evidence_provider=lambda: newer)
    second = _controller(capabilities=newer, capability_evidence_provider=lambda: newer)

    assert first.capability_sha256 == second.capability_sha256
    assert first.capability_snapshot_sha256 != second.capability_snapshot_sha256
    assert first.refresh_capability_evidence() == newer


def test_execute_rejects_stale_bound_snapshot_before_docker(tmp_path) -> None:
    observed = []
    controller = _controller(executor=lambda *args, **kwargs: observed.append(args))
    stale = _capabilities(captured_at_unix_ns=NOW_NS - 301_000_000_000)
    invocation = _invocation(
        tmp_path, capability_snapshot_sha256=_json_sha256(stale)
    )

    with pytest.raises(ResourceControllerError, match="stale"):
        controller.execute(invocation, capability_snapshot=stale)
    assert observed == []


def test_direct_parse_requires_refreshable_capabilities(tmp_path) -> None:
    controller = _controller()
    invocation = _invocation(tmp_path)
    controller, invocation, supplied = _valid_evidence_for(controller, invocation)

    with pytest.raises(ResourceControllerError, match="requires a refresh provider"):
        controller.parse_evidence(invocation, **supplied)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda supplied: supplied["cgroup"]["files"].pop("memory.peak"),
            "missing memory.peak",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"memory.current": "not-a-number\n"}
            ),
            "memory.current is malformed",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {"cpu.stat": "usage_usec 1\n"}
            ),
            "cpu.stat is missing",
        ),
        (
            lambda supplied: supplied["inspect"]["HostConfig"].update({"Memory": 1}),
            "Memory mismatch",
        ),
        (
            lambda supplied: supplied["inspect"]["Mounts"].append(
                {
                    "Type": "bind",
                    "Source": "/tmp/escape",
                    "Destination": "/escape",
                    "RW": True,
                }
            ),
            "exactly one writable",
        ),
    ],
)
def test_malformed_missing_or_mismatched_evidence_fails_closed(
    tmp_path, mutation, message
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    mutation(supplied)

    with pytest.raises(ResourceControllerError, match=message):
        controller.parse_evidence(invocation, **supplied)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda supplied: supplied["inspect"]["State"].update({"OOMKilled": True}),
            "OOM kill",
        ),
        (
            lambda supplied: supplied["cgroup"]["files"].update(
                {
                    "memory.events": (
                        "low 0\nhigh 0\nmax 1\noom 1\noom_kill 1\noom_group_kill 0\n"
                    )
                }
            ),
            "OOM event",
        ),
        (
            lambda supplied: supplied["supervisor"].update({"deadline_exceeded": True}),
            "deadline violation",
        ),
        (
            lambda supplied: supplied["supervisor"].update({"cleanup_complete": False}),
            "cleanup is incomplete",
        ),
        (
            lambda supplied: supplied["supervisor"].update({"residual_processes": 1}),
            "residual processes",
        ),
    ],
)
def test_oom_deadline_or_cleanup_evidence_is_rejected(
    tmp_path, mutation, message
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    mutation(supplied)

    with pytest.raises(ResourceControllerError, match=message):
        controller.parse_evidence(invocation, **supplied)


def test_stale_capability_evidence_is_rejected() -> None:
    with pytest.raises(ResourceControllerError, match="stale"):
        _controller(
            capabilities=_capabilities(captured_at_unix_ns=NOW_NS - 301_000_000_000)
        )


def test_stale_baseline_is_allowed_only_with_a_fresh_provider() -> None:
    stale = _capabilities(captured_at_unix_ns=NOW_NS - 301_000_000_000)
    fresh = _capabilities(captured_at_unix_ns=NOW_NS - 1_000_000_000)
    controller = _controller(
        capabilities=stale,
        capability_evidence_provider=lambda: fresh,
    )

    assert controller.refresh_capability_evidence() == fresh


@pytest.mark.parametrize(
    "effective_file",
    (
        "memory.max",
        "memory.swap.max",
        "memory.swap.events",
        "cpu.max",
        "cpuset.cpus.effective",
        "pids.max",
    ),
)
def test_missing_effective_limit_evidence_is_rejected(tmp_path, effective_file) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    supplied["cgroup"]["files"].pop(effective_file)

    with pytest.raises(ResourceControllerError, match="missing"):
        controller.parse_evidence(invocation, **supplied)


def test_swap_failure_counter_is_rejected(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    supplied["cgroup"]["files"]["memory.swap.events"] = "high 0\nmax 0\nfail 1\n"

    with pytest.raises(ResourceControllerError, match="swap failure"):
        controller.parse_evidence(invocation, **supplied)


@pytest.mark.parametrize(
    ("surface", "field", "value", "message"),
    (
        ("cgroup", "container_id", "a" * 64, "cgroup container identity"),
        ("cgroup", "identity", "2" * 64, "cgroup_identity binding"),
        ("supervisor", "container_id", "a" * 64, "container_id binding"),
        ("supervisor", "profile_sha256", "a" * 64, "profile_sha256 binding"),
        ("supervisor", "supervisor_sha256", "a" * 64, "supervisor_sha256 binding"),
    ),
)
def test_fabricated_or_cross_run_bindings_are_rejected(
    tmp_path, surface, field, value, message
) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    supplied[surface][field] = value

    with pytest.raises(ResourceControllerError, match=message):
        controller.parse_evidence(invocation, **supplied)


def test_nonexistent_run_directory_is_rejected(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    artifact = Path(invocation.host_run_directory) / invocation.artifact_relative_path
    artifact.unlink()
    Path(invocation.host_run_directory).rmdir()

    with pytest.raises(ResourceControllerError, match="does not exist"):
        controller.parse_evidence(invocation, **supplied)


def test_post_cutoff_artifact_is_rejected_even_with_matching_report(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    execution = supplied["execution"]
    artifact = Path(invocation.host_run_directory) / invocation.artifact_relative_path
    # NTFS timestamp conversion may round at sub-microsecond boundaries.
    late_ns = execution.host_artifact_deadline_wall_ns + 2_000_000_000
    os.utime(artifact, ns=(late_ns, late_ns))
    snapshot = controller._filesystem.read_artifact(
        str(Path(invocation.host_run_directory).resolve()),
        invocation.artifact_relative_path,
    )
    supplied["supervisor"].update(
        {
            "artifact_sha256": snapshot.sha256,
            "artifact_size_bytes": snapshot.size_bytes,
            "artifact_mtime_ns": snapshot.mtime_ns,
            "artifact_file_identity": snapshot.file_identity,
        }
    )

    with pytest.raises(ResourceControllerError, match="post-cutoff"):
        controller.parse_evidence(invocation, **supplied)


def test_replaced_artifact_is_rejected(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    artifact = Path(invocation.host_run_directory) / invocation.artifact_relative_path
    artifact.write_bytes(b"replacement")
    os.utime(artifact, ns=(NOW_NS + 3_000_000_000,) * 2)

    with pytest.raises(ResourceControllerError, match="does not match"):
        controller.parse_evidence(invocation, **supplied)


def test_symlink_artifact_is_rejected(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    artifact = Path(invocation.host_run_directory) / invocation.artifact_relative_path
    target = Path(invocation.host_run_directory) / "other.xml"
    target.write_bytes(b"replacement")
    artifact.unlink()
    try:
        artifact.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable on this Windows host")

    with pytest.raises(ResourceControllerError, match="must not be a link"):
        controller.parse_evidence(invocation, **supplied)


def test_host_cleanup_evidence_is_not_hard_coded(tmp_path) -> None:
    controller, invocation, supplied = _valid_evidence(tmp_path)
    execution = supplied["execution"]
    supplied["execution"] = replace(execution, cleanup_complete=False)

    with pytest.raises(ResourceControllerError, match="host cleanup is incomplete"):
        controller.parse_evidence(invocation, **supplied)


def test_hung_attach_is_killed_removed_and_rejected(tmp_path) -> None:
    invocation = _invocation(tmp_path)
    Path(invocation.host_run_directory).mkdir()
    observed = []

    def executor(command, *, timeout=None):
        observed.append((command, timeout))
        operation = command[1]
        if operation == "create":
            return SimpleNamespace(returncode=0, stdout=CONTAINER_ID + "\n")
        if operation == "start":
            raise subprocess.TimeoutExpired(command, timeout)
        if operation == "inspect":
            inspect_calls = sum(item[0][1] == "inspect" for item in observed)
            if inspect_calls == 3:
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "Error: No such container: "
                        f"{controller.container_name(invocation)}\n"
                    ),
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([_inspect(controller, invocation)]),
            )
        return SimpleNamespace(returncode=0, stdout="")

    controller = _controller(
        executor=executor,
        monotonic_ns=lambda: 1_000_000_000,
    )

    with pytest.raises(ResourceControllerError, match="outer host deadline"):
        controller.execute(invocation)

    operations = [command[0][1] for command in observed]
    assert operations == [
        "create",
        "inspect",
        "start",
        "kill",
        "inspect",
        "rm",
        "inspect",
    ]
