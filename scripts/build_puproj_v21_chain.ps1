param()

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$v19Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v19"
$v20Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v20"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\puproj_v21"

if (Test-Path -LiteralPath $targetRoot) {
    throw "Refusing to overwrite existing PU-PROJ v21 chain: $targetRoot"
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
        if (-not $text.Contains([string]$entry.Key)) {
            throw "Expected source token was absent from ${Source}: $($entry.Key)"
        }
        $text = $text.Replace([string]$entry.Key, [string]$entry.Value)
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

$runnerName = "planora-puproj-frontier-joint-v21-runner.py"
$runnerPath = Join-Path $targetRoot $runnerName
Write-Replaced `
    (Join-Path $v19Root "planora-puproj-frontier-joint-v19-runner.py") `
    $runnerPath `
    @{
        "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" = $moduleHashes.itc2019_decomposed
        "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" = $moduleHashes.itc2019_sparse_joint
        "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" = $moduleHashes.itc2019_violation_lns
    }
$runnerHash = Get-Sha256 $runnerPath

[System.IO.File]::Copy(
    (Join-Path $v19Root "planora-puproj-frontier-joint-v19-generic-validator.py"),
    (Join-Path $targetRoot "planora-puproj-frontier-joint-v19-generic-validator.py")
)
[System.IO.File]::Copy(
    (Join-Path $v19Root "planora-puproj-frontier-joint-v19-stdlib.sha256"),
    (Join-Path $targetRoot "planora-puproj-frontier-joint-v19-stdlib.sha256")
)

$supervisorName = "planora-puproj-frontier-joint-v21-supervisor.py"
$supervisorPath = Join-Path $targetRoot $supervisorName
Write-Replaced `
    (Join-Path $v20Root "planora-puproj-frontier-joint-v20-supervisor.py") `
    $supervisorPath `
    @{
        "PU-PROJ v20 control plane over the frozen v19 solver/runtime closure." = "PU-PROJ v21 control plane over the memory-bounded solver closure."
        'ARTIFACT_ROOT = ROOT / "benchmarks/probe_diagnostics/puproj_v19"' = 'ARTIFACT_ROOT = ROOT / "benchmarks/probe_diagnostics/puproj_v21"'
        "planora-puproj-frontier-joint-v19-runner.py" = $runnerName
        "43772c50e4804a56fc995542c1fbe61bef66e9e360eae7d7c24aeda8f0023548" = $runnerHash
        "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" = $moduleHashes.itc2019_decomposed
        "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" = $moduleHashes.itc2019_sparse_joint
        "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" = $moduleHashes.itc2019_violation_lns
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherName = "planora-puproj-frontier-joint-v21-launcher.py"
$launcherPath = Join-Path $targetRoot $launcherName
Write-Replaced `
    (Join-Path $v20Root "planora-puproj-frontier-joint-v20-launcher.py") `
    $launcherPath `
    @{
        "Sealed v20 launcher for the revised PU-PROJ resource control plane." = "Sealed v21 launcher for the memory-bounded PU-PROJ solver chain."
        "benchmarks/probe_diagnostics/puproj_v20" = "benchmarks/probe_diagnostics/puproj_v21"
        "planora-puproj-frontier-joint-v20-supervisor.py" = $supervisorName
        "2b9b1c797f26b472eee66fd82a674e85b3951828307fdc653aa5878fe6db6e09" = $supervisorHash
    }
$launcherHash = Get-Sha256 $launcherPath

$genericPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v19-generic-validator.py"
$stdlibPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v19-stdlib.sha256"
$testSparse = Join-Path $repositoryRoot "tests\test_itc2019_sparse_joint.py"
$testViolation = Join-Path $repositoryRoot "tests\test_itc2019_violation_lns.py"
$manifestPath = Join-Path $targetRoot "planora-puproj-frontier-joint-v21-freeze.json"
$manifest = [ordered]@{
    schema = "planora.pu-proj.frontier-joint-v21-freeze.v1"
    created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    native_bootstrap_protocol = "planora.native-sealed-python-bootstrap.v1"
    verdict = "GO_FOR_SEALED_IMPORT_PROBE_NO_GO_FOR_OFFICIAL_LAUNCH"
    scope = "PU-PROJ v21 memory-bounded sparse admission, decomposed pressure representation, and optional student-pair tail admission"
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
        supervisor = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v21/$supervisorName"; size = (Get-Item $supervisorPath).Length; sha256 = $supervisorHash }
        launcher = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v21/$launcherName"; size = (Get-Item $launcherPath).Length; sha256 = $launcherHash }
        runner = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v21/$runnerName"; size = (Get-Item $runnerPath).Length; sha256 = $runnerHash }
    }
    reused_runtime = [ordered]@{
        bootstrap = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v19/planora-puproj-frontier-joint-v19-bootstrap"; sha256 = "a4230de58dd5cca9e2e5e4c85cab40b669a354c3c960068d6a54ec094d0e64de" }
        generic_validator = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v21/planora-puproj-frontier-joint-v19-generic-validator.py"; sha256 = (Get-Sha256 $genericPath) }
        stdlib_manifest = [ordered]@{ path = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v21/planora-puproj-frontier-joint-v19-stdlib.sha256"; sha256 = (Get-Sha256 $stdlibPath) }
    }
    source_closure = [ordered]@{
        itc2019_decomposed_sha256 = $moduleHashes.itc2019_decomposed
        itc2019_sparse_joint_sha256 = $moduleHashes.itc2019_sparse_joint
        itc2019_violation_lns_sha256 = $moduleHashes.itc2019_violation_lns
        sparse_joint_test_sha256 = (Get-Sha256 $testSparse)
        violation_lns_test_sha256 = (Get-Sha256 $testViolation)
    }
    memory_interventions = [ordered]@{
        sparse_admission = "count-only before placement materialization"
        decomposed_pressure = "integer coarse-slot masks"
        supported_rooms = "interned immutable room tuples"
        rooted_tail = "streaming pair-visit gate before optional rooted call"
        rooted_pair_visit_cap = 200000
        pu_structural_pair_visit_lower_bound = 919749
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
        focused_tests = "148_PASS"
        complete_lightweight_itc2019 = "450_PASS_2_EXPECTED_SKIP"
        ruff = "PASS"
        sealed_import_probe = "NOT_RUN"
        official_solution_published = $false
        official_launch_authorized = $false
    }
}
[System.IO.File]::WriteAllText(
    $manifestPath,
    (($manifest | ConvertTo-Json -Depth 8) + "`n"),
    $utf8NoBom
)

[ordered]@{
    target = $targetRoot
    runner_sha256 = $runnerHash
    supervisor_sha256 = $supervisorHash
    launcher_sha256 = $launcherHash
    manifest_sha256 = Get-Sha256 $manifestPath
    source_closure = $moduleHashes
} | ConvertTo-Json -Depth 4
