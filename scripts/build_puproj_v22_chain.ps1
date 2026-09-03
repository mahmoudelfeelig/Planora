param()

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$v19Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v19"
$v21Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v21"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v22"

if (Test-Path -LiteralPath $targetRoot) {
    throw "Refusing to overwrite existing PU-PROJ v22 chain: $targetRoot"
}
New-Item -ItemType Directory -Path $targetRoot | Out-Null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-Replaced(
    [string]$Source,
    [string]$Destination,
    [hashtable]$Replacements
) {
    $text = [System.IO.File]::ReadAllText($Source, $utf8NoBom)
    foreach ($entry in $Replacements.GetEnumerator()) {
        $needle = [string]$entry.Key
        $replacement = [string]$entry.Value
        $count = ([regex]::Matches($text, [regex]::Escape($needle))).Count
        if ($count -ne 1) {
            throw "Expected exactly one source token in ${Source}, observed ${count}: $needle"
        }
        $text = $text.Replace($needle, $replacement)
    }
    [System.IO.File]::WriteAllText($Destination, $text, $utf8NoBom)
}

$modulePaths = @{
    itc2019_decomposed = Join-Path $repositoryRoot "benchmarks\itc2019_decomposed.py"
    itc2019_sparse_joint = Join-Path $repositoryRoot "benchmarks\itc2019_sparse_joint.py"
    itc2019_violation_lns = Join-Path $repositoryRoot "benchmarks\itc2019_violation_lns.py"
}
$moduleHashes = @{}
foreach ($entry in $modulePaths.GetEnumerator()) {
    $moduleHashes[$entry.Key] = Get-Sha256 $entry.Value
}

$runnerName = "planora-puproj-frontier-joint-v22-runner.py"
$runnerPath = Join-Path $targetRoot $runnerName
$oldGuard = @'
def _resource_guard(deadline: float, phase: str) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"cooperative deadline reached during {phase}")
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if peak >= RUNNER_RSS_CEILING_KIB:
        raise MemoryError(f"runner RSS ceiling reached during {phase}")
'@
$newGuard = @'
def _lightweight_result_telemetry(result: Any) -> dict[str, Any]:
    telemetry: dict[str, Any] = {}
    for field in fields(result):
        if field.name in {"placements", "student_classes"}:
            continue
        value = getattr(result, field.name)
        if is_dataclass(value):
            value = {nested.name: getattr(value, nested.name) for nested in fields(value)}
        telemetry[field.name] = value
    return telemetry


def _parse_self_status_rss_kib(raw: str) -> int:
    rows = [line.split() for line in raw.splitlines() if line.startswith("VmRSS:")]
    if len(rows) != 1:
        raise RuntimeError("self VmRSS telemetry is missing or ambiguous")
    row = rows[0]
    if len(row) != 3 or row[0] != "VmRSS:" or row[2] != "kB" or not row[1].isdigit():
        raise RuntimeError("self VmRSS telemetry is malformed")
    return int(row[1])


def _current_self_rss_kib() -> int:
    try:
        raw = Path("/proc/self/status").read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("self VmRSS telemetry is unavailable") from exc
    return _parse_self_status_rss_kib(raw)


def _release_unused_heap() -> dict[str, int]:
    before = _current_self_rss_kib()
    collected = int(gc.collect())
    malloc_trim = getattr(LIBC, "malloc_trim", None)
    if malloc_trim is None:
        raise RuntimeError("malloc_trim is unavailable in the frozen runtime")
    malloc_trim.argtypes = [ctypes.c_size_t]
    malloc_trim.restype = ctypes.c_int
    trim_result = int(malloc_trim(0))
    after = _current_self_rss_kib()
    return {
        "before_rss_kib": before,
        "after_rss_kib": after,
        "released_rss_kib": max(0, before - after),
        "gc_collected": collected,
        "malloc_trim_result": trim_result,
    }


def _resource_guard(deadline: float, phase: str) -> dict[str, int | str]:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"cooperative deadline reached during {phase}")
    current = _current_self_rss_kib()
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if current >= RUNNER_RSS_CEILING_KIB:
        raise MemoryError(
            f"runner live RSS ceiling reached during {phase}: "
            f"current={current} limit={RUNNER_RSS_CEILING_KIB}"
        )
    return {
        "metric": "proc_self_status_VmRSS",
        "current_rss_kib": current,
        "historical_peak_rss_kib": peak,
        "limit_kib": RUNNER_RSS_CEILING_KIB,
    }
'@
Write-Replaced `
    (Join-Path $v21Root "planora-puproj-frontier-joint-v21-runner.py") `
    $runnerPath `
    @{
        "from dataclasses import asdict, dataclass" = "from dataclasses import dataclass, fields, is_dataclass"
        "import fcntl`nfrom hashlib import sha256" = "import fcntl`nimport gc`nfrom hashlib import sha256"
        $oldGuard = $newGuard
        '    _resource_guard(deadline, "fresh solve return")' = @'
    memory_release_after_solve = _release_unused_heap()
    solve_return_resource = _resource_guard(deadline, "fresh solve return")
'@
        '        "runtime_compile_warnings": prepared.compile_warnings,' = @'
        "runtime_compile_warnings": prepared.compile_warnings,
        "memory_release_after_solve": memory_release_after_solve,
        "resource_observations": {
            "fresh_solve_return": solve_return_resource,
        },
'@
        @'
        "fresh_result": {
            key: value for key, value in asdict(result).items()
            if key not in {"placements", "student_classes"}
        },
'@ = @'
        "fresh_result": _lightweight_result_telemetry(result),
'@
        '    _resource_guard(deadline, "final capture replay")' = @'
    report["resource_observations"]["final_capture_replay"] = _resource_guard(
        deadline, "final capture replay"
    )
'@
        '    _resource_guard(deadline, "post-publication acceptance")' = @'
    post_publication_resource = _resource_guard(
        deadline, "post-publication acceptance"
    )
'@
        '        "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),' = @'
        "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "post_publication_resource": post_publication_resource,
'@
    }
$runnerHash = Get-Sha256 $runnerPath

[System.IO.File]::Copy(
    (Join-Path $v21Root "planora-puproj-frontier-joint-v19-generic-validator.py"),
    (Join-Path $targetRoot "planora-puproj-frontier-joint-v19-generic-validator.py")
)
[System.IO.File]::Copy(
    (Join-Path $v21Root "planora-puproj-frontier-joint-v19-stdlib.sha256"),
    (Join-Path $targetRoot "planora-puproj-frontier-joint-v19-stdlib.sha256")
)

$supervisorName = "planora-puproj-frontier-joint-v22-supervisor.py"
$supervisorPath = Join-Path $targetRoot $supervisorName
Write-Replaced `
    (Join-Path $v21Root "planora-puproj-frontier-joint-v21-supervisor.py") `
    $supervisorPath `
    @{
        "PU-PROJ v21 control plane over the memory-bounded solver closure." = "PU-PROJ v22 control plane with bounded live-RSS finalization."
        "benchmarks/probe_diagnostics/puproj_v21" = "benchmarks/probe_diagnostics/puproj_v22"
        "planora-puproj-frontier-joint-v21-runner.py" = $runnerName
        "ef2fdc7d68167f421eab3d3544969795ed18e78b02f2b7fff9b5db9aa4374e05" = $runnerHash
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherName = "planora-puproj-frontier-joint-v22-launcher.py"
$launcherPath = Join-Path $targetRoot $launcherName
Write-Replaced `
    (Join-Path $v21Root "planora-puproj-frontier-joint-v21-launcher.py") `
    $launcherPath `
    @{
        "Sealed v21 launcher for the memory-bounded PU-PROJ solver chain." = "Sealed v22 launcher for bounded live-RSS PU-PROJ finalization."
        "benchmarks/probe_diagnostics/puproj_v21" = "benchmarks/probe_diagnostics/puproj_v22"
        "planora-puproj-frontier-joint-v21-supervisor.py" = $supervisorName
        "2fee18265d421b1d7c2a81b867bce4175ff0b657e0d6cb6f52a3f87701e8ca19" = $supervisorHash
    }
$launcherHash = Get-Sha256 $launcherPath

$testName = "planora-puproj-frontier-joint-v22-tests.py"
$testPath = Join-Path $targetRoot $testName
$testSource = @'
#!/usr/bin/env python3
"""Focused no-solver checks for PU-PROJ v22 live-RSS finalization."""

from __future__ import annotations

import ast
import ctypes
from dataclasses import dataclass, fields, is_dataclass
import gc
from pathlib import Path
import resource
from types import SimpleNamespace
import time
from typing import Any


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
RUNNER = ROOT / "benchmarks/probe_diagnostics/puproj_v22/planora-puproj-frontier-joint-v22-runner.py"


def load_guard_namespace() -> dict[str, object]:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    names = {
        "RUNNER_RSS_CEILING_KIB",
        "_lightweight_result_telemetry",
        "_parse_self_status_rss_kib",
        "_current_self_rss_kib",
        "_release_unused_heap",
        "_resource_guard",
    }
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in names for target in targets):
                selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {
        "ctypes": ctypes,
        "fields": fields,
        "gc": gc,
        "is_dataclass": is_dataclass,
        "Path": Path,
        "resource": resource,
        "time": time,
        "Any": Any,
        "LIBC": ctypes.CDLL(None, use_errno=True),
    }
    exec(compile(module, str(RUNNER), "exec"), namespace)
    return namespace


def expect(exception_type, callback) -> None:
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"expected {exception_type.__name__}")


def main() -> int:
    namespace = load_guard_namespace()
    @dataclass
    class Objective:
        total: int

    @dataclass
    class Result:
        status: str
        placements: object
        student_classes: object
        objective: Objective

    telemetry = namespace["_lightweight_result_telemetry"](
        Result("FEASIBLE", object(), object(), Objective(7))
    )
    assert telemetry == {"status": "FEASIBLE", "objective": {"total": 7}}
    parse = namespace["_parse_self_status_rss_kib"]
    assert parse("Name:\tpython\nVmRSS:\t1399999 kB\n") == 1_399_999
    expect(RuntimeError, lambda: parse("Name:\tpython\n"))
    expect(RuntimeError, lambda: parse("VmRSS:\t1 MB\n"))
    expect(RuntimeError, lambda: parse("VmRSS:\t1 kB\nVmRSS:\t2 kB\n"))

    class FakeResource:
        RUSAGE_SELF = 0

        @staticmethod
        def getrusage(_who):
            return SimpleNamespace(ru_maxrss=1_523_728)

    namespace["resource"] = FakeResource
    namespace["_current_self_rss_kib"] = lambda: 1_350_000
    guard = namespace["_resource_guard"]
    evidence = guard(time.monotonic() + 30.0, "test below live ceiling")
    assert evidence == {
        "metric": "proc_self_status_VmRSS",
        "current_rss_kib": 1_350_000,
        "historical_peak_rss_kib": 1_523_728,
        "limit_kib": 1_400_000,
    }
    namespace["_current_self_rss_kib"] = lambda: 1_400_000
    expect(MemoryError, lambda: guard(time.monotonic() + 30.0, "test at ceiling"))
    expect(TimeoutError, lambda: guard(0.0, "expired"))

    release = namespace["_release_unused_heap"]()
    assert release["before_rss_kib"] >= 0
    assert release["after_rss_kib"] >= 0
    assert release["released_rss_kib"] == max(
        0, release["before_rss_kib"] - release["after_rss_kib"]
    )
    assert isinstance(release["gc_collected"], int)
    assert release["malloc_trim_result"] in {0, 1}

    source = RUNNER.read_text(encoding="utf-8")
    assert 'memory_release_after_solve = _release_unused_heap()' in source
    assert 'solve_return_resource = _resource_guard(deadline, "fresh solve return")' in source
    assert '"metric": "proc_self_status_VmRSS"' in source
    assert "peak >= RUNNER_RSS_CEILING_KIB" not in source
    assert "key: value for key, value in asdict(result).items()" not in source
    print("PU-PROJ v22 focused live-RSS tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@
[System.IO.File]::WriteAllText($testPath, $testSource, $utf8NoBom)
$testHash = Get-Sha256 $testPath

$genericPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v19-generic-validator.py"
$stdlibPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v19-stdlib.sha256"
$testSparse = Join-Path $repositoryRoot "tests\test_itc2019_sparse_joint.py"
$testViolation = Join-Path $repositoryRoot "tests\test_itc2019_violation_lns.py"
$v21Result = Join-Path $repositoryRoot "output\official-solves\pu-proj-fal19-v21-a87839366913408e90ad90b0b0861453\result-receipt.json"
$manifestPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v22-freeze.json"
$manifest = [ordered]@{
    schema = "planora.pu-proj.frontier-joint-v22-freeze.v1"
    created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    native_bootstrap_protocol = "planora.native-sealed-python-bootstrap.v1"
    verdict = "GO_FOR_STATIC_AND_SEALED_IMPORT_PROBE_NO_GO_FOR_OFFICIAL_LAUNCH"
    scope = "PU-PROJ v22 current-RSS finalization under unchanged authoritative outer limits"
    parent = [ordered]@{
        v21_manifest_sha256 = "916faaf7f67158d12cfb43e90bf21a690087a5866fe29afcbc0d8822d0328dc8"
        v21_failed_launch_id = "a87839366913408e90ad90b0b0861453"
        v21_result_receipt_sha256 = (Get-Sha256 $v21Result)
        v21_failure = "runner_ru_maxrss_guard_after_fresh_solve_return"
    }
    solver_input_mode = "OFFICIAL_INPUT_ONLY_FRESH"
    fairness = [ordered]@{
        official_input_sha256 = "2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42"
        expected_classes = 8813
        expected_students = 38437
        checkpoint_or_incumbent_path_configured = $false
        competitor_schedule_or_result_used = $false
        future_matched_resource_cap_kib = 1600000
    }
    control_plane = [ordered]@{
        supervisor = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/$supervisorName"; size = (Get-Item $supervisorPath).Length; sha256 = $supervisorHash }
        launcher = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/$launcherName"; size = (Get-Item $launcherPath).Length; sha256 = $launcherHash }
        runner = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/$runnerName"; size = (Get-Item $runnerPath).Length; sha256 = $runnerHash }
        focused_tests = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/$testName"; size = (Get-Item $testPath).Length; sha256 = $testHash }
    }
    reused_runtime = [ordered]@{
        bootstrap = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v19/planora-puproj-frontier-joint-v19-bootstrap"; sha256 = "a4230de58dd5cca9e2e5e4c85cab40b669a354c3c960068d6a54ec094d0e64de" }
        generic_validator = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/planora-puproj-frontier-joint-v19-generic-validator.py"; sha256 = (Get-Sha256 $genericPath) }
        stdlib_manifest = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v22/planora-puproj-frontier-joint-v19-stdlib.sha256"; sha256 = (Get-Sha256 $stdlibPath) }
    }
    source_closure = [ordered]@{
        itc2019_decomposed_sha256 = $moduleHashes.itc2019_decomposed
        itc2019_sparse_joint_sha256 = $moduleHashes.itc2019_sparse_joint
        itc2019_violation_lns_sha256 = $moduleHashes.itc2019_violation_lns
        sparse_joint_test_sha256 = (Get-Sha256 $testSparse)
        violation_lns_test_sha256 = (Get-Sha256 $testViolation)
    }
    finalization_intervention = [ordered]@{
        outer_memory_caps_changed = $false
        runner_rss_ceiling_kib = 1400000
        runner_guard_metric = "current /proc/self/status VmRSS"
        historical_peak_metric = "telemetry_only_inside_runner"
        authoritative_peak_guards = @("process_group_rss", "process_group_vmswap", "whole_launch_vmrss_plus_vmswap")
        post_solve_release = @("gc.collect", "glibc malloc_trim(0)")
        result_telemetry = "field-wise scalar extraction without recursive placement or sectioning copy"
        v21_observed_peak_process_group_rss_kib = 1523728
        v21_observed_peak_whole_launch_kib = 1590004
    }
    resource_contract = [ordered]@{
        process_group_rss_limit_kib = 1550000
        process_group_vmswap_limit_kib = 131072
        whole_launch_vmrss_plus_vmswap_limit_kib = 1600000
        runtime_memavailable_floor_kib = 450000
        address_space_cap_bytes = 2800000000
        child_deadline_seconds = 300.0
        supervisor_wall_seconds = 330.0
    }
    verification = [ordered]@{
        focused_live_rss_tests = "NOT_RUN"
        complete_lightweight_itc2019 = "450_PASS_2_EXPECTED_SKIP"
        sealed_import_probe = "NOT_RUN"
        official_solution_published = $false
        official_launch_authorized = $false
    }
}
[System.IO.File]::WriteAllText(
    $manifestPath,
    (($manifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
)

[ordered]@{
    target = $targetRoot
    runner_sha256 = $runnerHash
    supervisor_sha256 = $supervisorHash
    launcher_sha256 = $launcherHash
    tests_sha256 = $testHash
    manifest_sha256 = Get-Sha256 $manifestPath
    source_closure = $moduleHashes
} | ConvertTo-Json -Depth 5
