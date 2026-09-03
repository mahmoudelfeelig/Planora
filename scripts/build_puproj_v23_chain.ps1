param()

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$v22Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v22"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v23"
$v22EvidenceRoot = Join-Path $repositoryRoot "output\official-solves\pu-proj-fal19-v22-2ef32306a20f483e9482fcd1c81c695a"

if (Test-Path -LiteralPath $targetRoot) {
    throw "Refusing to overwrite existing PU-PROJ v23 chain: $targetRoot"
}
New-Item -ItemType Directory -Path $targetRoot | Out-Null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-Sha256([string]$Path, [string]$Expected) {
    $actual = Get-Sha256 $Path
    if ($actual -ne $Expected) {
        throw "Frozen parent hash mismatch for ${Path}: expected ${Expected}, observed ${actual}"
    }
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

$v22Manifest = Join-Path $v22Root "planora-puproj-frontier-joint-v22-freeze.json"
$v22RunnerReport = Join-Path $v22EvidenceRoot "runner-report.json"
$v22ResultReceipt = Join-Path $v22EvidenceRoot "result-receipt.json"
Assert-Sha256 $v22Manifest "fedf9e51de0e7b9eaf1d48d50ff5dc4ddbaaadca6becf63ddafc4590c8d80fb1"
Assert-Sha256 $v22RunnerReport "d8f64fd52d5e904c41e856c1f243ca367d5d19ea2a2b47a4ef789b4f96e61640"
Assert-Sha256 $v22ResultReceipt "88ee411fea29d459fc9284578e9c74f2e949c3772d8e55f5a053e9189ecdf5e2"

$report = Get-Content -Raw -LiteralPath $v22RunnerReport | ConvertFrom-Json
if (
    [double]$report.fresh_result.model_build_seconds -ne 258.94884728099714 -or
    [double]$report.fresh_result.solver_wall_time_seconds -ne 0.0 -or
    [int]$report.fresh_result.branches -ne 0 -or
    [int]$report.fresh_result.raw_cartesian_domain_values -ne 1937292 -or
    [int]$report.resource_observations.fresh_solve_return.historical_peak_rss_kib -ne 1525052 -or
    [int]$report.memory_release_after_solve.after_rss_kib -ne 632900
) {
    throw "PU-PROJ v22 model-build evidence does not match the v23 optimization premise"
}

$decomposedPath = Join-Path $repositoryRoot "benchmarks\itc2019_decomposed.py"
$decomposedTestPath = Join-Path $repositoryRoot "tests\test_itc2019_decomposed_extended_budget.py"
$decomposedHash = Get-Sha256 $decomposedPath
$decomposedTestHash = Get-Sha256 $decomposedTestPath
$v22DecomposedHash = "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05"

$runnerName = "planora-puproj-frontier-joint-v23-runner.py"
$runnerPath = Join-Path $targetRoot $runnerName
Write-Replaced `
    (Join-Path $v22Root "planora-puproj-frontier-joint-v22-runner.py") `
    $runnerPath `
    @{
        $v22DecomposedHash = $decomposedHash
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorName = "planora-puproj-frontier-joint-v23-supervisor.py"
$supervisorPath = Join-Path $targetRoot $supervisorName
Write-Replaced `
    (Join-Path $v22Root "planora-puproj-frontier-joint-v22-supervisor.py") `
    $supervisorPath `
    @{
        "PU-PROJ v22 control plane with bounded live-RSS finalization." = "PU-PROJ v23 control plane with bounded decomposed model construction."
        "benchmarks/probe_diagnostics/puproj_v22" = "benchmarks/probe_diagnostics/puproj_v23"
        "planora-puproj-frontier-joint-v22-runner.py" = $runnerName
        "4b18f5de8da5593cb6c9c4201ae11395c4888734ee0dfd6db54213a2b0db2538" = $runnerHash
        $v22DecomposedHash = $decomposedHash
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherName = "planora-puproj-frontier-joint-v23-launcher.py"
$launcherPath = Join-Path $targetRoot $launcherName
Write-Replaced `
    (Join-Path $v22Root "planora-puproj-frontier-joint-v22-launcher.py") `
    $launcherPath `
    @{
        "Sealed v22 launcher for bounded live-RSS PU-PROJ finalization." = "Sealed v23 launcher for bounded PU-PROJ model construction."
        "benchmarks/probe_diagnostics/puproj_v22" = "benchmarks/probe_diagnostics/puproj_v23"
        "planora-puproj-frontier-joint-v22-supervisor.py" = $supervisorName
        "1a097fdbd3cf6728f243cfb864136a402e7af5a5313f2c35a941b3e302198323" = $supervisorHash
    }
$launcherHash = Get-Sha256 $launcherPath

$genericName = "planora-puproj-frontier-joint-v19-generic-validator.py"
$stdlibName = "planora-puproj-frontier-joint-v19-stdlib.sha256"
$genericPath = Join-Path $targetRoot $genericName
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::Copy((Join-Path $v22Root $genericName), $genericPath)
[System.IO.File]::Copy((Join-Path $v22Root $stdlibName), $stdlibPath)

$testName = "planora-puproj-frontier-joint-v23-windows-static-tests.py"
$testPath = Join-Path $targetRoot $testName
$testSource = @'
#!/usr/bin/env python3
"""Windows-safe, no-solver verification for the PU-PROJ v23 chain."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import sys
import tracemalloc

from ortools.sat.python import cp_model


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).resolve().parent
MANIFEST = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-freeze.json"
RUNNER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-runner.py"
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-supervisor.py"
LAUNCHER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-launcher.py"
DECOMPOSED = ROOT / "benchmarks/itc2019_decomposed.py"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"missing literal assignment {name} in {path.name}")


def literal_dict_value(path: Path, assignment: str, key: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == assignment for target in node.targets):
            continue
        assert isinstance(node.value, ast.Dict)
        for key_node, value_node in zip(node.value.keys, node.value.values, strict=True):
            if ast.literal_eval(key_node) == key:
                return ast.literal_eval(value_node)
    raise AssertionError(f"missing literal dictionary value {assignment}[{key!r}] in {path.name}")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["verdict"] == "GO_FOR_WINDOWS_STATIC_REVIEW_ONLY_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
    assert manifest["verification"]["sealed_import_probe"] == "NOT_RUN"
    assert manifest["verification"]["official_solution_published"] is False
    assert manifest["verification"]["official_launch_authorized"] is False

    controls = manifest["control_plane"]
    assert digest(RUNNER) == controls["runner"]["sha256"]
    assert digest(SUPERVISOR) == controls["supervisor"]["sha256"]
    assert digest(LAUNCHER) == controls["launcher"]["sha256"]
    assert literal_assignment(SUPERVISOR, "EXPECTED_RUNNER_SHA256") == digest(RUNNER)
    assert literal_assignment(LAUNCHER, "EXPECTED_SUPERVISOR_SHA256") == digest(SUPERVISOR)
    assert digest(DECOMPOSED) == manifest["source_closure"]["itc2019_decomposed_sha256"]
    assert literal_dict_value(RUNNER, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)
    assert literal_dict_value(SUPERVISOR, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)

    for source in (RUNNER, SUPERVISOR, LAUNCHER, DECOMPOSED, Path(__file__)):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")

    expected_caps = {
        "PROCESS_GROUP_RSS_LIMIT_KIB": 1_550_000,
        "PROCESS_GROUP_VMSWAP_LIMIT_KIB": 131_072,
        "WHOLE_LAUNCH_MEMORY_LIMIT_KIB": 1_600_000,
        "RUNTIME_MIN_MEM_AVAILABLE_KIB": 450_000,
        "ADDRESS_SPACE_CAP_BYTES": 2_800_000_000,
        "CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS": 300.0,
        "SUPERVISOR_HARD_WALL_SECONDS": 330.0,
    }
    for name, expected in expected_caps.items():
        assert literal_assignment(SUPERVISOR, name) == expected

    sys.path.insert(0, str(ROOT))
    from benchmarks.itc2019_decomposed import (
        _BoundedPredicateCache,
        _add_streamed_forbidden_assignments,
        _build_compact_allowed_option_masks,
        _iter_forbidden_option_pairs,
    )

    first_size = 17
    second_size = 19
    predicate = lambda first, second: (first * 7 + second * 5) % 11 not in {0, 3}
    legacy_rows = tuple(
        sum(1 << second for second in range(second_size) if predicate(first, second))
        for first in range(first_size)
    )
    compact_rows = _build_compact_allowed_option_masks(
        first_size,
        second_size,
        predicate,
        deadline=1.0,
        clock=lambda: 0.0,
    )
    assert compact_rows == legacy_rows

    legacy_forbidden = [
        (first, second)
        for first, allowed in enumerate(legacy_rows)
        for second in range(second_size)
        if not allowed & (1 << second)
    ]
    streamed_forbidden = _iter_forbidden_option_pairs(
        compact_rows,
        second_size,
        deadline=1.0,
        clock=lambda: 0.0,
    )

    def model_text(forbidden, streamed: bool) -> str:
        model = cp_model.CpModel()
        first = model.new_int_var(0, first_size - 1, "first")
        second = model.new_int_var(0, second_size - 1, "second")
        if streamed:
            _add_streamed_forbidden_assignments(model, (first, second), forbidden)
        else:
            model.add_forbidden_assignments((first, second), forbidden)
        return str(model.proto)

    assert model_text(streamed_forbidden, True) == model_text(legacy_forbidden, False)

    empty_model = cp_model.CpModel()
    empty_first = empty_model.new_int_var(0, 2, "empty_first")
    empty_second = empty_model.new_int_var(0, 3, "empty_second")
    assert _add_streamed_forbidden_assignments(
        empty_model, (empty_first, empty_second), iter(())
    ) is True
    legacy_empty_model = cp_model.CpModel()
    legacy_empty_first = legacy_empty_model.new_int_var(0, 2, "empty_first")
    legacy_empty_second = legacy_empty_model.new_int_var(0, 3, "empty_second")
    legacy_empty_model.add_forbidden_assignments(
        (legacy_empty_first, legacy_empty_second), []
    )
    assert str(empty_model.proto) == str(legacy_empty_model.proto)

    cache = _BoundedPredicateCache(max_entries=5)
    for value in range(50):
        assert cache.resolve(value, lambda value=value: value % 2 == 0) is (value % 2 == 0)
        assert len(cache) <= 5

    tracemalloc.start()
    try:
        large_rows = _build_compact_allowed_option_masks(
            512,
            512,
            lambda first, second: (first + second) % 3 == 0,
            deadline=1.0,
            clock=lambda: 0.0,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(large_rows) == 512
    assert peak < 1_000_000

    try:
        _build_compact_allowed_option_masks(
            1,
            1,
            lambda _first, _second: True,
            deadline=0.0,
            clock=lambda: 0.0,
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("expired compact construction did not fail closed")

    print("PU-PROJ v23 Windows-safe static tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@
[System.IO.File]::WriteAllText($testPath, $testSource, $utf8NoBom)
$testHash = Get-Sha256 $testPath

$manifestName = "planora-puproj-frontier-joint-v23-freeze.json"
$manifestPath = Join-Path $targetRoot $manifestName
$manifest = [ordered]@{
    schema = "planora.pu-proj.frontier-joint-v23-freeze.v1"
    created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    native_bootstrap_protocol = "planora.native-sealed-python-bootstrap.v1"
    verdict = "GO_FOR_WINDOWS_STATIC_REVIEW_ONLY_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
    scope = "PU-PROJ v23 semantics-preserving bounded decomposed model construction under unchanged v22 caps"
    parent = [ordered]@{
        v22_manifest_sha256 = Get-Sha256 $v22Manifest
        v22_launch_id = "2ef32306a20f483e9482fcd1c81c695a"
        v22_runner_report_sha256 = Get-Sha256 $v22RunnerReport
        v22_result_receipt_sha256 = Get-Sha256 $v22ResultReceipt
        v22_status = [string]$report.status
    }
    evidence_premise = [ordered]@{
        model_build_seconds = [double]$report.fresh_result.model_build_seconds
        solver_wall_time_seconds = [double]$report.fresh_result.solver_wall_time_seconds
        branches = [int]$report.fresh_result.branches
        raw_cartesian_domain_values = [int]$report.fresh_result.raw_cartesian_domain_values
        peak_process_group_rss_kib = [int]$report.resource_observations.fresh_solve_return.historical_peak_rss_kib
        post_solve_trim_rss_kib = [int]$report.memory_release_after_solve.after_rss_kib
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
        supervisor = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$supervisorName"; size = (Get-Item $supervisorPath).Length; sha256 = $supervisorHash }
        launcher = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$launcherName"; size = (Get-Item $launcherPath).Length; sha256 = $launcherHash }
        runner = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$runnerName"; size = (Get-Item $runnerPath).Length; sha256 = $runnerHash }
        focused_tests = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$testName"; size = (Get-Item $testPath).Length; sha256 = $testHash }
    }
    reused_runtime = [ordered]@{
        bootstrap = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v19/planora-puproj-frontier-joint-v19-bootstrap"; sha256 = "a4230de58dd5cca9e2e5e4c85cab40b669a354c3c960068d6a54ec094d0e64de" }
        generic_validator = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$genericName"; sha256 = Get-Sha256 $genericPath }
        stdlib_manifest = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v23/$stdlibName"; sha256 = Get-Sha256 $stdlibPath }
    }
    source_closure = [ordered]@{
        itc2019_decomposed_sha256 = $decomposedHash
        decomposed_focused_test_sha256 = $decomposedTestHash
        itc2019_sparse_joint_sha256 = "2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2"
        itc2019_violation_lns_sha256 = "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343"
    }
    model_build_intervention = [ordered]@{
        semantics_changed = $false
        exact_constraint_order_changed = $false
        scalar_time_pair_cache_max_entries = 65536
        compatibility_storage = "one integer bit-mask per first-domain row"
        matrix_cell_cache = "disabled while compact matrix rows are constructed"
        forbidden_table_transport = "streamed directly into the final OR-Tools repeated scalar protobuf field"
        duplicate_python_forbidden_tuple_list = $false
        cartesian_deadline_check_interval = 4096
        fail_closed_on_deadline = $true
        outer_memory_caps_changed = $false
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
        decomposed_focused_tests = "17_PASS"
        windows_static_chain_tests = "PENDING"
        python_ast_and_compile = "PENDING"
        ruff = "PENDING"
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

$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
& $python $testPath
if ($LASTEXITCODE -ne 0) {
    throw "PU-PROJ v23 Windows-safe static tests failed with exit code $LASTEXITCODE"
}
& $python -m ruff check `
    $decomposedPath `
    $decomposedTestPath `
    $runnerPath `
    $supervisorPath `
    $launcherPath `
    $testPath
if ($LASTEXITCODE -ne 0) {
    throw "PU-PROJ v23 Ruff verification failed with exit code $LASTEXITCODE"
}
$manifest.verification.windows_static_chain_tests = "PASS"
$manifest.verification.python_ast_and_compile = "PASS"
$manifest.verification.ruff = "PASS"
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
    itc2019_decomposed_sha256 = $decomposedHash
    decomposed_focused_test_sha256 = $decomposedTestHash
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 5
