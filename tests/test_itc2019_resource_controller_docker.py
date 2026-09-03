"""Real Docker trust-boundary tests for the ITC-2019 resource controller.

These tests use only synthetic Python workloads and local Docker images.  They
never pull images, execute official cases, or run benchmark matrices.  The
module skips when Docker, Linux containers, cgroup v2, the required controllers,
or a suitable already-local Python image are unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

import pytest

import benchmarks.itc2019_resource_controller as resource_controller
from benchmarks.itc2019_resource_controller import (
    CAPABILITY_EVIDENCE_SCHEMA,
    DockerCgroupV2Controller,
    LocalFileSystem,
    ResourceControllerError,
    ResourceProfile,
    SolverInvocation,
    TRUSTED_SUPERVISOR_ENTRYPOINT,
)
from scripts import benchmark_itc2019_competitors as competitor_harness


def _integration_marker() -> pytest.MarkDecorator:
    """Register locally so this one-file addition works with strict markers."""

    config = getattr(pytest.mark, "_config", None)
    if config is not None:
        config.addinivalue_line(
            "markers",
            "integration: tests that exercise a real external runtime boundary",
        )
    return pytest.mark.integration


pytestmark = [pytest.mark.slow, _integration_marker()]

_MIB = 1024 * 1024
_SUPERVISOR_SOURCE = b"""#!/usr/local/bin/python3
import os
import sys

arguments = sys.argv[1:]
try:
    separator = arguments.index("--")
except ValueError:
    raise SystemExit(97)
command = arguments[separator + 1:]
if not command:
    raise SystemExit(98)
os.execvp(command[0], command)
"""


@dataclass(frozen=True)
class DockerRuntime:
    executable: str
    image_id: str
    daemon_id: str
    context: str
    total_memory_bytes: int
    cpuset_cpu: str


class RecordingExecutor:
    """Real executor that retains inspect snapshots.

    The optional normalizer remains available only to prove compatibility with
    the legacy spelling.  Real integration tests use Docker's response bytes.
    """

    def __init__(self, *, normalize_docker_29_absence: bool = False) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.inspections: list[dict[str, object]] = []
        self.normalize_docker_29_absence = normalize_docker_29_absence

    def __call__(
        self, command: tuple[str, ...], *, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if len(command) > 1 and command[1] == "inspect" and result.returncode == 0:
            payload = json.loads(result.stdout)
            if isinstance(payload, list) and len(payload) == 1:
                self.inspections.append(payload[0])
        if (
            self.normalize_docker_29_absence
            and len(command) > 1
            and command[1] == "inspect"
            and result.returncode == 1
            and result.stdout.strip() == "[]"
            and result.stderr.strip()
            == f"Error response from daemon: No such container: {command[-1]}"
        ):
            return subprocess.CompletedProcess(
                result.args,
                result.returncode,
                stdout="",
                stderr=f"Error: No such container: {command[-1]}\n",
            )
        return result


def _docker(
    executable: str,
    *arguments: str,
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (executable, *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _docker_json(executable: str, *arguments: str) -> dict[str, object]:
    result = _docker(executable, *arguments)
    if result.returncode != 0:
        pytest.skip(f"Docker prerequisite failed: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.skip("Docker prerequisite returned malformed JSON")
    if not isinstance(payload, dict):
        pytest.skip("Docker prerequisite did not return a JSON object")
    return payload


def _local_python_image(executable: str) -> tuple[str, str]:
    configured = os.environ.get("PLANORA_DOCKER_TEST_IMAGE")
    candidates = tuple(
        candidate
        for candidate in (
            configured,
            "python:3.13-slim",
            "python:3.12-slim",
            "python:3.11-slim",
        )
        if candidate
    )
    for candidate in candidates:
        inspected = _docker(
            executable,
            "image",
            "inspect",
            "--format={{json .}}",
            candidate,
        )
        if inspected.returncode != 0:
            continue
        try:
            image = json.loads(inspected.stdout)
        except json.JSONDecodeError:
            continue
        image_id = image.get("Id") if isinstance(image, dict) else None
        image_os = image.get("Os") if isinstance(image, dict) else None
        if (
            isinstance(image_id, str)
            and image_id.startswith("sha256:")
            and len(image_id) == 71
            and image_os == "linux"
        ):
            probe = _docker(
                executable,
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--entrypoint=python3",
                image_id,
                "-c",
                (
                    "import pathlib,sys; assert sys.version_info >= (3,9); "
                    "print(pathlib.Path('/sys/fs/cgroup/cpuset.cpus.effective')"
                    ".read_text().strip())"
                ),
            )
            if probe.returncode == 0 and probe.stdout.strip():
                first_range = probe.stdout.strip().split(",", 1)[0]
                first_cpu = first_range.split("-", 1)[0]
                if first_cpu.isdigit():
                    return image_id, first_cpu
    pytest.skip(
        "no already-local Linux Python 3.9+ image is available; images are never pulled"
    )


@pytest.fixture(scope="module")
def docker_runtime() -> DockerRuntime:
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("Docker CLI is unavailable")
    try:
        info = _docker_json(executable, "info", "--format={{json .}}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker daemon is unavailable: {type(exc).__name__}")

    required_true = (
        "MemoryLimit",
        "SwapLimit",
        "CpuCfsPeriod",
        "CpuCfsQuota",
        "CPUSet",
        "PidsLimit",
    )
    missing = [name for name in required_true if info.get(name) is not True]
    if info.get("OSType") != "linux":
        pytest.skip("Docker is not using Linux containers")
    if str(info.get("CgroupVersion")) != "2":
        pytest.skip("Docker is not using cgroup v2")
    if missing:
        pytest.skip("Docker lacks required controls: " + ", ".join(missing))
    if not isinstance(info.get("NCPU"), int) or int(info["NCPU"]) < 1:
        pytest.skip("Docker did not report an available CPU")
    if not isinstance(info.get("MemTotal"), int) or int(info["MemTotal"]) < 256 * _MIB:
        pytest.skip("Docker reports too little memory for isolated synthetic probes")

    context_result = _docker(executable, "context", "show")
    if context_result.returncode != 0 or not context_result.stdout.strip():
        pytest.skip("Docker context identity is unavailable")
    daemon_source = str(info.get("ID", ""))
    if not daemon_source:
        pytest.skip("Docker daemon identity is unavailable")

    image_id, cpuset_cpu = _local_python_image(executable)
    return DockerRuntime(
        executable=executable,
        image_id=image_id,
        daemon_id=hashlib.sha256(daemon_source.encode("utf-8")).hexdigest(),
        context=context_result.stdout.strip(),
        total_memory_bytes=int(info["MemTotal"]),
        cpuset_cpu=cpuset_cpu,
    )


def _capabilities(runtime: DockerRuntime) -> dict[str, object]:
    return {
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
        "total_memory_bytes": runtime.total_memory_bytes,
        "available_swap_bytes": 0,
        "available_cpuset_cpus": runtime.cpuset_cpu,
        "daemon_id": runtime.daemon_id,
        "docker_context": runtime.context,
        "captured_at_unix_ns": time.time_ns(),
    }


def _profile(runtime: DockerRuntime, **overrides: object) -> ResourceProfile:
    values: dict[str, object] = {
        "wall_time_seconds": 4.0,
        "artifact_grace_seconds": 0.25,
        "memory_bytes": 96 * _MIB,
        "memory_swap_bytes": 96 * _MIB,
        "cpuset_cpus": runtime.cpuset_cpu,
        "cpu_period_us": 100_000,
        "cpu_quota_us": 100_000,
        "pids_limit": 64,
    }
    values.update(overrides)
    return ResourceProfile(**values)


def _controller(
    runtime: DockerRuntime,
    profile: ResourceProfile,
    supervisor_sha256: str,
    executor: RecordingExecutor | None = None,
) -> DockerCgroupV2Controller:
    def current_capabilities() -> dict[str, object]:
        return _capabilities(runtime)

    return DockerCgroupV2Controller(
        profile,
        current_capabilities(),
        supervisor_sha256=supervisor_sha256,
        executor=executor or RecordingExecutor(),
        capability_evidence_provider=current_capabilities,
        docker_executable=runtime.executable,
    )


def _python_argv(source: str) -> tuple[str, ...]:
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return ("python3", "-c", f"import base64;exec(base64.b64decode('{encoded}'))")


def _invocation(
    tmp_path: Path,
    runtime: DockerRuntime,
    argv: tuple[str, ...],
    *,
    artifact_relative_path: str = "solution.json",
    input_mounts: tuple[tuple[str, str], ...] = (),
) -> tuple[SolverInvocation, str]:
    run_directory = (tmp_path / f"run-{uuid.uuid4().hex}").resolve()
    run_directory.mkdir()
    supervisor = (tmp_path / f"supervisor-{uuid.uuid4().hex}.py").resolve()
    supervisor.write_bytes(_SUPERVISOR_SOURCE)
    supervisor.chmod(0o755)
    supervisor_sha256 = hashlib.sha256(_SUPERVISOR_SOURCE).hexdigest()
    invocation = SolverInvocation(
        run_id=f"docker-int-{uuid.uuid4().hex[:16]}",
        solver="synthetic-python",
        image=runtime.image_id,
        argv=argv,
        host_run_directory=str(run_directory),
        input_mounts=input_mounts,
        binary_mounts=((str(supervisor), TRUSTED_SUPERVISOR_ENTRYPOINT),),
        artifact_relative_path=artifact_relative_path,
    )
    return invocation, supervisor_sha256


def _container_absent(runtime: DockerRuntime, name: str) -> bool:
    result = _docker(runtime.executable, "inspect", "--type=container", name)
    return result.returncode == 1 and "No such container" in result.stderr


def _force_remove(runtime: DockerRuntime, name: str) -> None:
    _docker(runtime.executable, "rm", "--force", name)


def _execute_and_assert_cleanup(
    runtime: DockerRuntime,
    controller: DockerCgroupV2Controller,
    invocation: SolverInvocation,
):
    name = controller.container_name(invocation)
    try:
        observation = controller.execute(invocation)
        absent = _container_absent(runtime, name)
    finally:
        _force_remove(runtime, name)
    assert absent, f"controller left synthetic container {name!r} behind"
    assert observation.cleanup_complete
    assert observation.residual_processes == 0
    return observation


def test_unmodified_docker_29_absence_response_proves_real_cleanup(
    tmp_path: Path, docker_runtime: DockerRuntime
) -> None:
    invocation, supervisor_sha256 = _invocation(
        tmp_path,
        docker_runtime,
        _python_argv("import pathlib; pathlib.Path('/run/planora/done').touch()"),
    )
    executor = RecordingExecutor()
    controller = _controller(
        docker_runtime,
        _profile(docker_runtime),
        supervisor_sha256,
        executor,
    )
    name = controller.container_name(invocation)
    try:
        observation = controller.execute(invocation)
        absent = _container_absent(docker_runtime, name)
    finally:
        _force_remove(docker_runtime, name)

    assert observation.cleanup_complete
    assert absent
    assert any(outcome.absence_verified for outcome in controller.last_cleanup_outcomes)


def test_wall_timeout_kills_descendants_and_removes_container(
    tmp_path: Path, docker_runtime: DockerRuntime
) -> None:
    workload = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path('/run/planora/child.pid').write_text(str(child.pid)); "
        "time.sleep(60)"
    )
    invocation, supervisor_sha256 = _invocation(
        tmp_path, docker_runtime, _python_argv(workload)
    )
    profile = _profile(
        docker_runtime,
        wall_time_seconds=0.75,
        artifact_grace_seconds=0.1,
    )
    controller = _controller(docker_runtime, profile, supervisor_sha256)
    name = controller.container_name(invocation)
    started = time.monotonic()
    try:
        with pytest.raises(ResourceControllerError, match="outer host deadline"):
            controller.execute(invocation)
        absent = _container_absent(docker_runtime, name)
    finally:
        _force_remove(docker_runtime, name)

    assert (Path(invocation.host_run_directory) / "child.pid").is_file()
    assert absent, "timed-out container and its descendant cgroup were not removed"
    assert time.monotonic() - started < 8.0
    assert any(
        outcome.operation == "kill-before-inspect"
        for outcome in controller.last_cleanup_outcomes
    )
    assert any(outcome.absence_verified for outcome in controller.last_cleanup_outcomes)


def test_oom_is_observed_rejected_and_cleaned_up(
    tmp_path: Path, docker_runtime: DockerRuntime
) -> None:
    workload = """
import json
import pathlib

limits = {
    'memory_max': pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip(),
    'memory_swap_max': pathlib.Path('/sys/fs/cgroup/memory.swap.max').read_text().strip(),
}
pathlib.Path('/run/planora/memory-limits.json').write_text(json.dumps(limits))
data = bytearray(512 * 1024 * 1024)
print(len(data))
"""
    invocation, supervisor_sha256 = _invocation(
        tmp_path, docker_runtime, _python_argv(workload)
    )
    profile = _profile(
        docker_runtime,
        wall_time_seconds=6.0,
        memory_bytes=48 * _MIB,
        memory_swap_bytes=48 * _MIB,
    )
    executor = RecordingExecutor()
    controller = _controller(docker_runtime, profile, supervisor_sha256, executor)
    name = controller.container_name(invocation)
    try:
        with pytest.raises(ResourceControllerError, match="docker start failed"):
            controller.execute(invocation)
        absent = _container_absent(docker_runtime, name)
    finally:
        _force_remove(docker_runtime, name)

    exited_states = [
        inspection.get("State")
        for inspection in executor.inspections
        if isinstance(inspection.get("State"), dict)
        and inspection["State"].get("Status") == "exited"
    ]
    assert exited_states, "Docker never exposed a final exited state"
    assert any(state.get("OOMKilled") is True for state in exited_states)
    limits = json.loads(
        (Path(invocation.host_run_directory) / "memory-limits.json").read_text()
    )
    assert limits == {
        "memory_max": str(48 * _MIB),
        "memory_swap_max": "0",
    }
    assert absent, "OOM-killed synthetic container was not removed"
    assert any(outcome.absence_verified for outcome in controller.last_cleanup_outcomes)


def test_cpu_quota_is_effective_and_records_throttling(
    tmp_path: Path, docker_runtime: DockerRuntime
) -> None:
    workload = """
import json
import pathlib
import time

def counters():
    values = {}
    for line in pathlib.Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines():
        key, value = line.split()
        values[key] = int(value)
    return values

before = counters()
deadline = time.monotonic() + 1.25
value = 1
while time.monotonic() < deadline:
    value = (value * 1103515245 + 12345) & 0x7fffffff
after = counters()
payload = {
    'cpu_max': pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
    'cpuset': pathlib.Path('/sys/fs/cgroup/cpuset.cpus.effective').read_text().strip(),
    'nr_periods_delta': after['nr_periods'] - before['nr_periods'],
    'nr_throttled_delta': after['nr_throttled'] - before['nr_throttled'],
    'throttled_usec_delta': after['throttled_usec'] - before['throttled_usec'],
    'sentinel': value,
}
pathlib.Path('/run/planora/solution.json').write_text(json.dumps(payload))
"""
    invocation, supervisor_sha256 = _invocation(
        tmp_path, docker_runtime, _python_argv(workload)
    )
    profile = _profile(
        docker_runtime,
        wall_time_seconds=5.0,
        cpu_period_us=100_000,
        cpu_quota_us=25_000,
    )
    controller = _controller(docker_runtime, profile, supervisor_sha256)

    _execute_and_assert_cleanup(docker_runtime, controller, invocation)

    payload = json.loads(
        (Path(invocation.host_run_directory) / "solution.json").read_text()
    )
    assert payload["cpu_max"] == "25000 100000"
    assert payload["cpuset"] == docker_runtime.cpuset_cpu
    assert payload["nr_periods_delta"] >= 8
    assert payload["nr_throttled_delta"] > 0
    assert payload["throttled_usec_delta"] > 0


def test_read_only_root_and_input_mounts_preserve_sources(
    tmp_path: Path, docker_runtime: DockerRuntime
) -> None:
    input_file = (tmp_path / "case.txt").resolve()
    input_file.write_bytes(b"immutable-input")
    workload = """
import json
import pathlib

attempts = {}
for target in (
    '/inputs/case.txt',
    '/opt/planora/itc2019-container-supervisor',
    '/etc/planora-write-test',
):
    try:
        pathlib.Path(target).write_bytes(b'tampered')
        attempts[target] = {'wrote': True}
    except OSError as exc:
        attempts[target] = {'wrote': False, 'errno': exc.errno}
pathlib.Path('/run/planora/solution.json').write_text(json.dumps(attempts))
"""
    invocation, supervisor_sha256 = _invocation(
        tmp_path,
        docker_runtime,
        _python_argv(workload),
        input_mounts=((str(input_file), "/inputs/case.txt"),),
    )
    supervisor_source = Path(invocation.binary_mounts[0][0])
    controller = _controller(
        docker_runtime, _profile(docker_runtime), supervisor_sha256
    )

    _execute_and_assert_cleanup(docker_runtime, controller, invocation)

    attempts = json.loads(
        (Path(invocation.host_run_directory) / "solution.json").read_text()
    )
    assert all(result["wrote"] is False for result in attempts.values())
    assert input_file.read_bytes() == b"immutable-input"
    assert supervisor_source.read_bytes() == _SUPERVISOR_SOURCE
    assert (
        hashlib.sha256(supervisor_source.read_bytes()).hexdigest() == supervisor_sha256
    )


def test_container_artifact_capture_and_concurrent_mutation_fail_closed(
    tmp_path: Path,
    docker_runtime: DockerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workload = (
        "import pathlib; "
        "pathlib.Path('/run/planora/solution.bin').write_bytes(b'A' * (4 * 1024 * 1024))"
    )
    invocation, supervisor_sha256 = _invocation(
        tmp_path,
        docker_runtime,
        _python_argv(workload),
        artifact_relative_path="solution.bin",
    )
    controller = _controller(
        docker_runtime, _profile(docker_runtime), supervisor_sha256
    )
    _execute_and_assert_cleanup(docker_runtime, controller, invocation)

    filesystem = LocalFileSystem()
    run_directory = filesystem.canonical_directory(invocation.host_run_directory)
    stable = filesystem.read_artifact(run_directory, invocation.artifact_relative_path)
    assert stable.size_bytes == 4 * _MIB
    assert stable.sha256 == hashlib.sha256(b"A" * (4 * _MIB)).hexdigest()

    artifact = Path(run_directory) / invocation.artifact_relative_path
    first_read = threading.Event()
    mutation_done = threading.Event()
    mutation_error: list[BaseException] = []
    original_read = resource_controller.os.read
    first_call = True

    def mutator() -> None:
        if not first_read.wait(5.0):
            mutation_error.append(TimeoutError("artifact hashing never started"))
            mutation_done.set()
            return
        try:
            with open(artifact, "r+b", buffering=0) as output:
                output.seek(0)
                output.write(b"B")
                output.flush()
                os.fsync(output.fileno())
        except BaseException as exc:
            mutation_error.append(exc)
        finally:
            mutation_done.set()

    def synchronized_read(descriptor: int, size: int) -> bytes:
        nonlocal first_call
        chunk = original_read(descriptor, size)
        if first_call and chunk:
            first_call = False
            first_read.set()
            if not mutation_done.wait(5.0):
                raise TimeoutError("artifact mutator did not complete")
        return chunk

    writer = threading.Thread(target=mutator, name="artifact-mutator", daemon=True)
    writer.start()
    monkeypatch.setattr(resource_controller.os, "read", synchronized_read)
    with pytest.raises(ResourceControllerError, match="modified while hashing"):
        filesystem.read_artifact(run_directory, invocation.artifact_relative_path)
    writer.join(timeout=1.0)
    if mutation_error:
        pytest.skip(
            "host filesystem cannot expose a deterministic concurrent write: "
            f"{type(mutation_error[0]).__name__}"
        )
    assert artifact.read_bytes()[:1] == b"B"


def test_competitor_harness_executes_synthetic_run_only_through_controller(
    tmp_path: Path,
    docker_runtime: DockerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = (input_root / "synthetic.xml").resolve()
    instance.write_text("synthetic-input", encoding="utf-8")
    supervisor = (tmp_path / "integrated-supervisor.py").resolve()
    supervisor.write_bytes(_SUPERVISOR_SOURCE)
    supervisor.chmod(0o755)
    supervisor_sha256 = hashlib.sha256(_SUPERVISOR_SOURCE).hexdigest()
    profile = _profile(docker_runtime)
    controller = _controller(docker_runtime, profile, supervisor_sha256)
    source = (
        "import pathlib; "
        "pathlib.Path('{output}').write_text("
        "pathlib.Path('{input}').read_text())"
    )
    binding = {
        "mode": "evidence-only-controller",
        "config_path": str((tmp_path / "controller.json").resolve()),
        "config_sha256": "1" * 64,
        "controller_version": resource_controller.CONTROLLER_VERSION,
        "controller_source_sha256": "2" * 64,
        "profile": profile.to_canonical_dict(),
        "profile_sha256": profile.sha256,
        "capability_evidence": controller.capability_evidence,
        "capability_sha256": controller.capability_sha256,
        "capability_refresh": None,
        "capability_refresh_sha256": None,
        "preflight_capability_snapshot": controller.capability_evidence,
        "preflight_capability_snapshot_sha256": controller.capability_sha256,
        "post_exit_cgroup_probe": None,
        "post_exit_cgroup_probe_sha256": None,
        "supervisor_path": str(supervisor),
        "supervisor_sha256": supervisor_sha256,
        "solver_images": {"planora": docker_runtime.image_id},
        "solver_argv": {"planora": ["python3", "-c", source]},
        "solver_argv_sha256": "3" * 64,
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
        "claim_grade_ready": False,
        "execution_admission_ready": False,
        "claim_evidence_set_sha256": None,
        "readiness_blocker": "trusted evidence remains incomplete",
    }
    runtime = competitor_harness.ClaimGradeControllerRuntime(
        controller=controller,
        manifest_binding=binding,
        supervisor_path=supervisor,
        solver_argv_templates={"planora": ("python3", "-c", source)},
    )
    identity = competitor_harness._run_identity(
        "synthetic", "planora", 17, 1, seeds=[17], repetitions=1
    )
    monkeypatch.setattr(
        competitor_harness,
        "_score",
        lambda *_args: {"feasible": True, "objective": {"total": 0}},
    )
    monkeypatch.setattr(
        competitor_harness,
        "_run_one",
        lambda *args, **kwargs: pytest.fail("legacy host launcher was reached"),
    )

    row = competitor_harness._run_one_controller(
        runtime,
        "planora",
        identity=identity,
        case="synthetic",
        instance_path=instance,
        root=tmp_path / "matrix",
        seed=17,
        repetition=1,
        seconds=profile.wall_time_seconds,
        cpu=int(docker_runtime.cpuset_cpu),
        resume_binding_sha256="4" * 64,
    )

    assert row["execution_mode"] == "evidence-only-controller"
    assert row["output_sha256"] == hashlib.sha256(b"synthetic-input").hexdigest()
    evidence = json.loads(
        Path(row["resource_evidence_path"]).read_text(encoding="utf-8")
    )
    assert evidence["execution"]["cleanup_complete"] is True
    assert evidence["claim_grade_ready"] is False
    assert _container_absent(
        docker_runtime,
        controller.container_name(
            competitor_harness._controller_invocation(
                runtime,
                identity=identity,
                solver="planora",
                instance_path=instance,
                run_dir=Path(row["output_path"]).parent,
                seed=17,
                seconds=profile.wall_time_seconds,
                capability_snapshot_sha256=controller.capability_sha256,
            )
        ),
    )
