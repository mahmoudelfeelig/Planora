param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$muniRepositoryRoot = Split-Path -Parent $PSScriptRoot
$muniV22Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v22"
$muniV23Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v23"
$muniRepositoryWsl = "/mnt/d/Stuff/Projects/Sites/Planora"
$muniV23Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v23"
$muniUtf8NoBom = [System.Text.UTF8Encoding]::new($false)

$muniParentManifestHash = "d639ae4ce4523f8be6ddd1b432f018699c434f24125a26ab5b438e7beaf5e84c"
$muniParentCertificateHash = "aef63263c65d8cf7a9f2b4abc85d200353266426a14074ed5909ab2b26dbe4a7"

function Get-MuniSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-MuniUtf8([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText($Path, $Value, $muniUtf8NoBom)
}

function Copy-MuniArtifact([string]$SourceName, [string]$DestinationName) {
    [System.IO.File]::Copy(
        (Join-Path $muniV22Root $SourceName),
        (Join-Path $muniV23Root $DestinationName)
    )
}

function Convert-MuniV22Text(
    [string]$SourceName,
    [string]$DestinationName,
    [hashtable]$HashReplacements,
    [scriptblock]$AdditionalTransform = $null
) {
    $sourcePath = Join-Path $muniV22Root $SourceName
    $destinationPath = Join-Path $muniV23Root $DestinationName
    $text = [System.IO.File]::ReadAllText($sourcePath, $muniUtf8NoBom)

    if (-not (
        $text.Contains("muni_v22") -or
        $text.Contains("frontier-v22") -or
        $text.Contains("MUNI-FSPSX v22")
    )) {
        throw "Expected v22 identity token absent from $sourceName"
    }
    $text = $text.Replace("muni_v22", "muni_v23")
    $text = $text.Replace("frontier-v22", "frontier-v23")
    $text = $text.Replace("MUNI-FSPSX v22", "MUNI-FSPSX v23")
    $text = $text.Replace("MUNI v22", "MUNI v23")
    $text = $text.Replace("MUNI_V22", "MUNI_V23")
    $text = $text.Replace("V22", "V23")
    $text = $text.Replace("v22", "v23")

    foreach ($entry in $HashReplacements.GetEnumerator()) {
        $oldHash = [string]$entry.Key
        $newHash = [string]$entry.Value
        if ($text.Contains($oldHash)) {
            $text = $text.Replace($oldHash, $newHash)
        }
    }
    if ($null -ne $AdditionalTransform) {
        $text = & $AdditionalTransform $text
    }
    if ($text.Contains("muni_v22") -or $text.Contains("frontier-v22")) {
        throw "Stale v22 current-chain identifier remains in $DestinationName"
    }
    Write-MuniUtf8 $destinationPath $text
}

function New-MuniBwrapArgv(
    [string]$HostOutputRoot,
    [string]$InlinePayload,
    [string]$BootstrapHash,
    [string]$InlineHash,
    [string]$Mode,
    [string]$LauncherHash,
    [string]$SupervisorHash,
    [string]$ManifestHash
) {
    $argv = @(
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--ro-bind", "/", "/",
        "--bind", $HostOutputRoot, "/tmp",
        "--dev", "/dev",
        "--proc", "/proc",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8",
        "--setenv", "TZ", "UTC",
        "--cap-drop", "ALL",
        "--chdir", $muniRepositoryWsl,
        "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $InlinePayload,
        "--inline-trust-v1",
        "$muniV23Wsl/planora-muni-fspsx-frontier-v23-bootstrap.py",
        $BootstrapHash,
        $InlineHash,
        $Mode,
        "--expected-launcher-sha256", $LauncherHash,
        "--expected-supervisor-sha256", $SupervisorHash,
        "--expected-manifest-sha256", $ManifestHash
    )
    if ($argv.Count -ne 48) {
        throw "Contained bwrap contract must contain exactly 48 elements; observed $($argv.Count)"
    }
    return ,$argv
}

function Get-MuniNulArgvSha256([object[]]$Argv) {
    $payload = [System.Text.Encoding]::UTF8.GetBytes(
        (($Argv | ForEach-Object { [string]$_ }) -join [char]0) + [char]0
    )
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($hasher.ComputeHash($payload))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $muniV22Root -PathType Container)) {
    throw "MUNI v22 parent chain is absent: $muniV22Root"
}
if (Test-Path -LiteralPath $muniV23Root) {
    throw "Refusing to overwrite an existing MUNI v23 chain: $muniV23Root"
}

$muniV22ManifestPath = Join-Path $muniV22Root "planora-muni-fspsx-frontier-v22-freeze-manifest.json"
$muniV22CertificatePath = Join-Path $muniV22Root "planora-muni-fspsx-frontier-v22-certificate.json"
if ((Get-MuniSha256 $muniV22ManifestPath) -ne $muniParentManifestHash) {
    throw "MUNI v22 parent manifest drift"
}
if ((Get-MuniSha256 $muniV22CertificatePath) -ne $muniParentCertificateHash) {
    throw "MUNI v22 parent certificate drift"
}

$muniV22Snapshot = [ordered]@{}
foreach ($file in Get-ChildItem -LiteralPath $muniV22Root -File | Sort-Object Name) {
    $muniV22Snapshot[$file.Name] = Get-MuniSha256 $file.FullName
}

$muniSourcePaths = [ordered]@{
    itc2019_decomposed = Join-Path $muniRepositoryRoot "benchmarks\itc2019_decomposed.py"
    itc2019_sparse_joint = Join-Path $muniRepositoryRoot "benchmarks\itc2019_sparse_joint.py"
    itc2019_violation_lns = Join-Path $muniRepositoryRoot "benchmarks\itc2019_violation_lns.py"
    test_violation_lns = Join-Path $muniRepositoryRoot "tests\test_itc2019_violation_lns.py"
}
$muniSourceHashes = [ordered]@{}
foreach ($entry in $muniSourcePaths.GetEnumerator()) {
    $muniSourceHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniHashReplacements = @{
    "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" = $muniSourceHashes.itc2019_decomposed
    "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" = $muniSourceHashes.itc2019_sparse_joint
    "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" = $muniSourceHashes.itc2019_violation_lns
    "a738894d4393d8d5bf8a240f493fa92e2e12e820cd885b40518e13cc0d91efdb" = $muniSourceHashes.test_violation_lns
}

New-Item -ItemType Directory -Path $muniV23Root | Out-Null

Copy-MuniArtifact "planora_muni_v22_benchmarks_stub.py" "planora_muni_v23_benchmarks_stub.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v22-generic-validator.py" "planora-muni-fspsx-frontier-v23-generic-validator.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v22-minimal-tcb.sha256" "planora-muni-fspsx-frontier-v23-minimal-tcb.sha256"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v22-stdlib.sha256" "planora-muni-fspsx-frontier-v23-stdlib.sha256"
Copy-MuniArtifact "planora-muni-fspsx-v35-derivation-audit-v1.json" "planora-muni-fspsx-v35-derivation-audit-v1.json"

Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-runner.py" `
    "planora-muni-fspsx-frontier-v23-runner.py" `
    $muniHashReplacements
Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-supervisor.py" `
    "planora-muni-fspsx-frontier-v23-supervisor.py" `
    $muniHashReplacements
Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-bootstrap.py" `
    "planora-muni-fspsx-frontier-v23-bootstrap.py" `
    $muniHashReplacements
Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-inline-trust-root.txt" `
    "planora-muni-fspsx-frontier-v23-inline-trust-root.txt" `
    $muniHashReplacements
Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-launcher.sh" `
    "planora-muni-fspsx-frontier-v23-launcher.sh" `
    $muniHashReplacements

$muniTestTransform = {
    param([string]$Text)
    $needle = @'
    def test_real_chain_reaches_probe_admission_without_opening_inputs(self) -> None:
        available = supervisor.host_sample()["mem_available_kib"]
'@
    $replacement = @'
    def test_real_chain_reaches_probe_admission_without_opening_inputs(self) -> None:
        if os.environ.get("PLANORA_MUNI_V23_SKIP_HEAVY") == "1":
            self.skipTest("real sealed chain admission disabled by test contract")
        available = supervisor.host_sample()["mem_available_kib"]
'@
    if (-not $Text.Contains($needle)) {
        throw "Expected real-chain admission test seam absent from transformed v23 tests"
    }
    $Text = $Text.Replace($needle, $replacement)

    $classNeedle = "class StaticContractTests(unittest.TestCase):`n"
    $parentTest = @'
class StaticContractTests(unittest.TestCase):
    def test_direct_v22_parent_and_exact_bwrap_contract(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v23-freeze-manifest.json").read_bytes()
        )
        parent = manifest["parent_chain"]
        self.assertEqual(parent["version"], "v22")
        self.assertEqual(
            parent["freeze_manifest_sha256"],
            "d639ae4ce4523f8be6ddd1b432f018699c434f24125a26ab5b438e7beaf5e84c",
        )
        self.assertEqual(
            parent["implementation_certificate_sha256"],
            "aef63263c65d8cf7a9f2b4abc85d200353266426a14074ed5909ab2b26dbe4a7",
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v23-certificate.json").read_bytes()
        )
        for label in ("sealed_import_probe", "official_launch"):
            contract = certificate["contained_bwrap_contract"][label]
            argv = contract["argv"]
            self.assertEqual(len(argv), 48)
            encoded = ("\0".join(argv) + "\0").encode("utf-8")
            self.assertEqual(sha256(encoded).hexdigest(), contract["argv_nul_sha256"])

'@
    if (-not $Text.Contains($classNeedle)) {
        throw "Static contract class seam absent from transformed v23 tests"
    }
    return $Text.Replace($classNeedle, $parentTest)
}
Convert-MuniV22Text `
    "planora-muni-fspsx-frontier-v22-tests.py" `
    "planora-muni-fspsx-frontier-v23-tests.py" `
    $muniHashReplacements `
    $muniTestTransform

$muniPaths = [ordered]@{
    bootstrap = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-bootstrap.py"
    inline_trust_payload = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-inline-trust-root.txt"
    launcher = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-launcher.sh"
    supervisor = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-supervisor.py"
    runner = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-runner.py"
    v23_adversarial_tests = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-tests.py"
    generic_validator = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-generic-validator.py"
    stdlib_manifest = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-stdlib.sha256"
    minimal_tcb_manifest = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-minimal-tcb.sha256"
    benchmarks = Join-Path $muniV23Root "planora_muni_v23_benchmarks_stub.py"
    staged_audit_copy = Join-Path $muniV23Root "planora-muni-fspsx-v35-derivation-audit-v1.json"
}
$muniArtifactHashes = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $muniArtifactHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniManifestText = [System.IO.File]::ReadAllText($muniV22ManifestPath, $muniUtf8NoBom)
$muniManifestText = $muniManifestText.Replace("muni_v22", "muni_v23")
$muniManifestText = $muniManifestText.Replace("frontier-v22", "frontier-v23")
$muniManifestText = $muniManifestText.Replace("V22", "V23")
$muniManifestText = $muniManifestText.Replace("v22", "v23")
foreach ($entry in $muniHashReplacements.GetEnumerator()) {
    $muniManifestText = $muniManifestText.Replace([string]$entry.Key, [string]$entry.Value)
}
$muniManifest = $muniManifestText | ConvertFrom-Json

$muniManifest.code_review_certificate_path = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-certificate.json"
$muniManifest.created_for = "v23-current-source-fresh-freeze-before-one-retained-no-solver-probe"
foreach ($name in @(
    "v12_preservation", "v13_preservation", "v14_preservation",
    "v17_preservation", "v18_preservation", "v19_preservation",
    "v20_preservation", "v21_preservation"
)) {
    $muniManifest.PSObject.Properties.Remove($name)
}

$muniFilePathByLabel = @{
    bootstrap = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-bootstrap.py"
    inline_trust_payload = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-inline-trust-root.txt"
    launcher = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-launcher.sh"
    supervisor = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-supervisor.py"
    runner = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-runner.py"
    v23_adversarial_tests = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-tests.py"
    generic_validator = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-generic-validator.py"
    stdlib_manifest = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-stdlib.sha256"
    minimal_tcb_manifest = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-minimal-tcb.sha256"
    benchmarks = "$muniV23Wsl/planora_muni_v23_benchmarks_stub.py"
}
foreach ($row in $muniManifest.files) {
    $label = [string]$row.label
    if ($muniFilePathByLabel.ContainsKey($label)) {
        $row.path = $muniFilePathByLabel[$label]
        $row.sha256 = $muniArtifactHashes[$label]
    }
    if ($muniSourceHashes.Contains($label)) {
        $row.sha256 = $muniSourceHashes[$label]
    }
}

$muniManifest.inline_trust_root.bootstrap_sha256 = $muniArtifactHashes.bootstrap
$muniManifest.inline_trust_root.inline_payload_sha256 = $muniArtifactHashes.inline_trust_payload
$muniManifest.stdlib_trust_boundary.minimal_tcb_manifest_path = $muniFilePathByLabel.minimal_tcb_manifest
$muniManifest.verification = [ordered]@{
    build_manifest_rows_replayed = $true
    bash_syntax = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
    python_compile = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
    lightweight_tests = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
    heavy_tests_skipped_by_explicit_contract = $true
    sealed_import_probe = "NOT_RUN"
    official_input_opened = $false
    progress_or_checkpoint_opened = $false
    solver_run = $false
}
$muniManifest | Add-Member -NotePropertyName parent_chain -NotePropertyValue ([ordered]@{
    version = "v22"
    root = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/muni_v22"
    freeze_manifest_sha256 = $muniParentManifestHash
    implementation_certificate_sha256 = $muniParentCertificateHash
    inherited_historical_claims_reconstructed = $false
})

$muniSymbolicArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" "{INLINE_TRUST_PAYLOAD}" "{BOOTSTRAP_SHA256}" `
    "{INLINE_TRUST_SHA256}" "{EXECUTION_MODE}" "{LAUNCHER_SHA256}" `
    "{SUPERVISOR_SHA256}" "{FREEZE_MANIFEST_SHA256}"
$muniManifest | Add-Member -NotePropertyName outer_bwrap_contract -NotePropertyValue ([ordered]@{
    schema = "planora.muni-fspsx.frontier-v23.bwrap-argv.v1"
    contained_argv_count = 48
    argv_shape = $muniSymbolicArgv
    probe_outer_timeout_seconds = 210
    official_outer_timeout_seconds = 660
    host_output_root_is_fresh_private_and_bound_as_tmp = $true
})

$muniManifestPath = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-freeze-manifest.json"
Write-MuniUtf8 $muniManifestPath (($muniManifest | ConvertTo-Json -Depth 20) + "`n")
$muniManifestHash = Get-MuniSha256 $muniManifestPath

$muniInlinePayload = [System.IO.File]::ReadAllText($muniPaths.inline_trust_payload, $muniUtf8NoBom)
$muniProbeArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" $muniInlinePayload $muniArtifactHashes.bootstrap `
    $muniArtifactHashes.inline_trust_payload "--sealed-import-probe" `
    $muniArtifactHashes.launcher $muniArtifactHashes.supervisor $muniManifestHash
$muniOfficialArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" $muniInlinePayload $muniArtifactHashes.bootstrap `
    $muniArtifactHashes.inline_trust_payload "--launch" `
    $muniArtifactHashes.launcher $muniArtifactHashes.supervisor $muniManifestHash

$muniCertificateFiles = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $name = Split-Path -Leaf $entry.Value
    $path = if ($entry.Key -eq "staged_audit_copy") {
        "$muniV23Wsl/$name"
    }
    else {
        "$muniV23Wsl/$name"
    }
    $muniCertificateFiles[$path] = $muniArtifactHashes[$entry.Key]
}
$muniCertificateFiles["$muniV23Wsl/planora-muni-fspsx-frontier-v23-freeze-manifest.json"] = $muniManifestHash

$muniCertificate = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v23.implementation-certificate.v1"
    status = "GO_FOR_ONE_RETAINED_BOUNDED_DIAGNOSTIC_SEALED_IMPORT_PROBE_NO_GO_FOR_OFFICIAL_LAUNCH"
    diagnostic_launch_status = "READY_FOR_ONE_RETAINED_BOUNDED_SEALED_IMPORT_PROBE"
    official_launch_status = "NO_GO_PENDING_RETAINED_PROBE_AND_INDEPENDENT_AUTHORIZATION"
    canonical_certificate_path = "$muniV23Wsl/planora-muni-fspsx-frontier-v23-certificate.json"
    scope = "fresh v23 chain over current Planora source hashes; no official input, progress, checkpoint, memory probe, sealed import probe, or solver was opened or run by the builder"
    parent_chain = [ordered]@{
        version = "v22"
        freeze_manifest_sha256 = $muniParentManifestHash
        implementation_certificate_sha256 = $muniParentCertificateHash
        inherited_historical_claims_reconstructed = $false
    }
    files = $muniCertificateFiles
    current_source_hashes = $muniSourceHashes
    resource_contract = [ordered]@{
        launch_memavailable_floor_kib = 1900000
        runtime_memavailable_floor_kib = 650000
        process_group_memory_cap_kib = 700000
        whole_launch_memory_cap_kib = 700000
        runner_seconds = 600.0
        supervisor_wall_seconds = 630.0
        sealed_import_probe_wall_seconds = 180.0
        probe_outer_timeout_seconds = 210
        official_outer_timeout_seconds = 660
        host_swap_counters_kill_enabled = $false
    }
    contained_bwrap_contract = [ordered]@{
        schema = "planora.muni-fspsx.frontier-v23.bwrap-argv.v1"
        host_output_root_token = "{HOST_OUTPUT_ROOT}"
        sealed_import_probe = [ordered]@{
            argv_count = $muniProbeArgv.Count
            argv_nul_sha256 = Get-MuniNulArgvSha256 $muniProbeArgv
            argv = $muniProbeArgv
        }
        official_launch = [ordered]@{
            argv_count = $muniOfficialArgv.Count
            argv_nul_sha256 = Get-MuniNulArgvSha256 $muniOfficialArgv
            argv = $muniOfficialArgv
        }
    }
    implementation_verification = [ordered]@{
        builder_source_hash_stability = "PASS"
        parent_v22_manifest_and_certificate = "PASS"
        v22_files_modified = $false
        manifest_file_rows_replayed_by_builder = "PASS"
        exact_bwrap_argv_count = "PASS_48_PROBE_48_OFFICIAL"
        python_compile = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
        bash_syntax = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
        v23_tests = "PENDING_EXTERNAL_LIGHTWEIGHT_VERIFICATION"
        heavy_work_skipped = $true
        official_input_opened = $false
        solver_run = $false
    }
}
$muniCertificatePath = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-certificate.json"
Write-MuniUtf8 $muniCertificatePath (($muniCertificate | ConvertTo-Json -Depth 25) + "`n")

$muniManifestRows = @{}
foreach ($row in $muniManifest.files) {
    $muniManifestRows[[string]$row.label] = $row
}
foreach ($entry in $muniFilePathByLabel.GetEnumerator()) {
    $label = [string]$entry.Key
    if (-not $muniManifestRows.ContainsKey($label)) {
        throw "Generated manifest is missing chain row: $label"
    }
    if ($muniManifestRows[$label].sha256 -ne $muniArtifactHashes[$label]) {
        throw "Generated manifest hash replay failed: $label"
    }
}
foreach ($entry in $muniSourceHashes.GetEnumerator()) {
    if ($muniManifestRows[$entry.Key].sha256 -ne $entry.Value) {
        throw "Generated manifest source hash replay failed: $($entry.Key)"
    }
    if ((Get-MuniSha256 $muniSourcePaths[$entry.Key]) -ne $entry.Value) {
        throw "Source changed during MUNI v23 construction: $($entry.Key)"
    }
}
foreach ($file in Get-ChildItem -LiteralPath $muniV22Root -File | Sort-Object Name) {
    if (-not $muniV22Snapshot.Contains($file.Name)) {
        throw "MUNI v22 file set changed during construction"
    }
    if ((Get-MuniSha256 $file.FullName) -ne $muniV22Snapshot[$file.Name]) {
        throw "MUNI v22 artifact changed during construction: $($file.Name)"
    }
}

[ordered]@{
    target = $muniV23Root
    manifest_sha256 = $muniManifestHash
    certificate_sha256 = Get-MuniSha256 $muniCertificatePath
    contained_probe_argv_count = $muniProbeArgv.Count
    contained_probe_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniProbeArgv
    contained_official_argv_count = $muniOfficialArgv.Count
    contained_official_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniOfficialArgv
    current_source_hashes = $muniSourceHashes
    official_input_opened = $false
    solver_run = $false
} | ConvertTo-Json -Depth 6
