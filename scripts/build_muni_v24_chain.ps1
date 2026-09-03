param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$muniRepositoryRoot = Split-Path -Parent $PSScriptRoot
$muniV23Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v23"
$muniV24Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v24"
$muniRepositoryWsl = "/mnt/d/Stuff/Projects/Sites/Planora"
$muniV23Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v23"
$muniV24Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v24"
$muniUtf8NoBom = [System.Text.UTF8Encoding]::new($false)

$muniFinalSharedCoreHash = "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d"
$muniParentBuilderHash = "c52265500d9dd112f0ed73e3e89c45e965c122eb54bc530624f9c6c7e7151d87"
$muniParentManifestHash = "291643f45c93c31199e4b3294eb1edcc36d867abc760653375e3833dbea9d905"
$muniParentCertificateHash = "114dcaf09b3eca05add37cdc7bb26aa35320118d17610f009a09690c2154679f"
$muniParentCanonicalTestsReceiptHash = "14582ae93ce730d669b7fc57283d8935215385e7ea08182a0463aca0d9bb0017"
$muniParentProbeReceiptHash = "070dea2afc4d590e1e0e4e3f25e35f9f0bbb218a5acbf71acd4de38fb2af1837"
$muniParentProbeStdoutHash = "16f9526163cbd6e123980d3fdb86e67cd95034e6bebf0690f209ef67507d6259"
$muniEmptySha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

$muniParentBuilderPath = Join-Path $muniRepositoryRoot "scripts\build_muni_v23_chain.ps1"
$muniParentManifestPath = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-freeze-manifest.json"
$muniParentCertificatePath = Join-Path $muniV23Root "planora-muni-fspsx-frontier-v23-certificate.json"
$muniParentCanonicalTestsReceiptPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\muni-fspsx-v23-canonical-readonly-tests-20260827T021800Z.receipt.json"
$muniParentProbeReceiptPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.receipt.json"
$muniParentProbeStdoutPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.stdout.json"
$muniParentProbeStderrPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.stderr.log"

function Get-MuniSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-MuniUtf8([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText($Path, $Value, $muniUtf8NoBom)
}

function Assert-MuniPinnedFile([string]$Path, [string]$ExpectedHash, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Pinned $Label is absent: $Path"
    }
    $observed = Get-MuniSha256 $Path
    if ($observed -ne $ExpectedHash) {
        throw "Pinned $Label drift: expected $ExpectedHash observed $observed"
    }
}

function Copy-MuniArtifact([string]$SourceName, [string]$DestinationName) {
    [System.IO.File]::Copy(
        (Join-Path $muniV23Root $SourceName),
        (Join-Path $muniV24Root $DestinationName)
    )
}

function Convert-MuniV23Text(
    [string]$SourceName,
    [string]$DestinationName,
    [hashtable]$HashReplacements,
    [scriptblock]$AdditionalTransform = $null
) {
    $sourcePath = Join-Path $muniV23Root $SourceName
    $destinationPath = Join-Path $muniV24Root $DestinationName
    $text = [System.IO.File]::ReadAllText($sourcePath, $muniUtf8NoBom)

    if (-not (
        $text.Contains("muni_v23") -or
        $text.Contains("frontier-v23") -or
        $text.Contains("MUNI-FSPSX v23")
    )) {
        throw "Expected v23 identity token absent from $SourceName"
    }
    $text = $text.Replace("muni_v23", "muni_v24")
    $text = $text.Replace("frontier-v23", "frontier-v24")
    $text = $text.Replace("MUNI-FSPSX v23", "MUNI-FSPSX v24")
    $text = $text.Replace("MUNI v23", "MUNI v24")
    $text = $text.Replace("MUNI_V23", "MUNI_V24")
    $text = $text.Replace("V23", "V24")
    $text = $text.Replace("v23", "v24")

    foreach ($entry in $HashReplacements.GetEnumerator()) {
        if ($text.Contains([string]$entry.Key)) {
            $text = $text.Replace([string]$entry.Key, [string]$entry.Value)
        }
    }
    if ($null -ne $AdditionalTransform) {
        $text = & $AdditionalTransform $text
    }
    if ($text.Contains("muni_v23") -or $text.Contains("frontier-v23")) {
        throw "Stale v23 current-chain identifier remains in $DestinationName"
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
        "$muniV24Wsl/planora-muni-fspsx-frontier-v24-bootstrap.py",
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

if (-not (Test-Path -LiteralPath $muniV23Root -PathType Container)) {
    throw "MUNI v23 parent chain is absent: $muniV23Root"
}
if (Test-Path -LiteralPath $muniV24Root) {
    throw "Refusing to overwrite an existing MUNI v24 chain: $muniV24Root"
}

Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v23 builder"
Assert-MuniPinnedFile $muniParentManifestPath $muniParentManifestHash "MUNI v23 freeze manifest"
Assert-MuniPinnedFile $muniParentCertificatePath $muniParentCertificateHash "MUNI v23 certificate"
Assert-MuniPinnedFile $muniParentCanonicalTestsReceiptPath $muniParentCanonicalTestsReceiptHash "MUNI v23 canonical test receipt"
Assert-MuniPinnedFile $muniParentProbeReceiptPath $muniParentProbeReceiptHash "MUNI v23 rejected probe receipt"
Assert-MuniPinnedFile $muniParentProbeStdoutPath $muniParentProbeStdoutHash "MUNI v23 rejected probe stdout"
Assert-MuniPinnedFile $muniParentProbeStderrPath $muniEmptySha256 "MUNI v23 rejected probe stderr"

$muniParentProbeReceipt = Get-Content -LiteralPath $muniParentProbeReceiptPath -Raw | ConvertFrom-Json
if ($muniParentProbeReceipt.decision -ne "REJECTED_FAIL_CLOSED_SOURCE_PIN_DRIFT") {
    throw "MUNI v23 probe receipt decision is not the expected fail-closed rejection"
}
if ($muniParentProbeReceipt.probe_id -ne "492e7d9acc434363b37e222289e8e554") {
    throw "MUNI v23 probe receipt ID drift"
}
if ($muniParentProbeReceipt.envelope.child_started -ne $false) {
    throw "MUNI v23 rejected probe unexpectedly records a child start"
}
foreach ($field in @("official_instance_opened", "progress_or_checkpoint_opened", "solver_execution_started", "solution_published")) {
    if ($muniParentProbeReceipt.safety.$field -ne $false) {
        throw "MUNI v23 rejected probe safety field is not false: $field"
    }
}
if ($muniParentProbeReceipt.source_drift.post_exit_sha256_while_pu_optimization_still_active -ne $muniFinalSharedCoreHash) {
    throw "MUNI v23 rejection evidence does not bind the final shared core hash"
}

$muniV23Snapshot = [ordered]@{}
foreach ($file in Get-ChildItem -LiteralPath $muniV23Root -File | Sort-Object Name) {
    $muniV23Snapshot[$file.Name] = [ordered]@{
        size_bytes = $file.Length
        sha256 = Get-MuniSha256 $file.FullName
    }
}

$muniParentManifest = Get-Content -LiteralPath $muniParentManifestPath -Raw | ConvertFrom-Json
$muniSourcePaths = [ordered]@{}
$muniSourceHashes = [ordered]@{}
$muniHashReplacements = @{}
foreach ($row in $muniParentManifest.files) {
    $path = [string]$row.path
    $isRepositorySource = (
        ($path.StartsWith("$muniRepositoryWsl/benchmarks/") -or $path.StartsWith("$muniRepositoryWsl/tests/")) -and
        (-not $path.StartsWith("$muniV23Wsl/")) -and
        $path.EndsWith(".py")
    )
    if (-not $isRepositorySource) {
        continue
    }
    $label = [string]$row.label
    $relativePath = $path.Substring($muniRepositoryWsl.Length + 1).Replace("/", "\")
    $windowsPath = Join-Path $muniRepositoryRoot $relativePath
    if (-not (Test-Path -LiteralPath $windowsPath -PathType Leaf)) {
        throw "MUNI v24 source-closure path is absent: $windowsPath"
    }
    $currentHash = Get-MuniSha256 $windowsPath
    $muniSourcePaths[$label] = $windowsPath
    $muniSourceHashes[$label] = $currentHash
    $muniHashReplacements[[string]$row.sha256] = $currentHash
}
if ($muniSourceHashes.itc2019_decomposed -ne $muniFinalSharedCoreHash) {
    throw "Final shared core drift: expected $muniFinalSharedCoreHash observed $($muniSourceHashes.itc2019_decomposed)"
}

New-Item -ItemType Directory -Path $muniV24Root | Out-Null

Copy-MuniArtifact "planora_muni_v23_benchmarks_stub.py" "planora_muni_v24_benchmarks_stub.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v23-generic-validator.py" "planora-muni-fspsx-frontier-v24-generic-validator.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v23-minimal-tcb.sha256" "planora-muni-fspsx-frontier-v24-minimal-tcb.sha256"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v23-stdlib.sha256" "planora-muni-fspsx-frontier-v24-stdlib.sha256"
Copy-MuniArtifact "planora-muni-fspsx-v35-derivation-audit-v1.json" "planora-muni-fspsx-v35-derivation-audit-v1.json"

Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-runner.py" `
    "planora-muni-fspsx-frontier-v24-runner.py" `
    $muniHashReplacements
Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-supervisor.py" `
    "planora-muni-fspsx-frontier-v24-supervisor.py" `
    $muniHashReplacements
Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-bootstrap.py" `
    "planora-muni-fspsx-frontier-v24-bootstrap.py" `
    $muniHashReplacements
Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-inline-trust-root.txt" `
    "planora-muni-fspsx-frontier-v24-inline-trust-root.txt" `
    $muniHashReplacements
Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-launcher.sh" `
    "planora-muni-fspsx-frontier-v24-launcher.sh" `
    $muniHashReplacements

$muniTestTransform = {
    param([string]$Text)

    $Text = $Text.Replace(
        "test_direct_v22_parent_and_exact_bwrap_contract",
        "test_direct_v23_parent_and_exact_bwrap_contract"
    )
    $Text = $Text.Replace(
        'self.assertEqual(parent["version"], "v22")',
        'self.assertEqual(parent["version"], "v23")'
    )
    $Text = $Text.Replace(
        "d639ae4ce4523f8be6ddd1b432f018699c434f24125a26ab5b438e7beaf5e84c",
        $muniParentManifestHash
    )
    $Text = $Text.Replace(
        "aef63263c65d8cf7a9f2b4abc85d200353266426a14074ed5909ab2b26dbe4a7",
        $muniParentCertificateHash
    )

    $classNeedle = "class StaticContractTests(unittest.TestCase):`n"
    $contractTests = @'
class StaticContractTests(unittest.TestCase):
    def test_v24_final_core_rejection_evidence_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v24-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v24-certificate.json").read_bytes()
        )
        self.assertEqual(
            certificate["current_source_hashes"]["itc2019_decomposed"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v23")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "c52265500d9dd112f0ed73e3e89c45e965c122eb54bc530624f9c6c7e7151d87",
        )
        rejection = certificate["parent_v23_rejection_evidence"]
        self.assertEqual(rejection["decision"], "REJECTED_FAIL_CLOSED_SOURCE_PIN_DRIFT")
        self.assertEqual(rejection["probe_id"], "492e7d9acc434363b37e222289e8e554")
        self.assertFalse(rejection["child_started"])
        self.assertFalse(rejection["official_instance_opened"])
        self.assertFalse(rejection["solver_execution_started"])
        self.assertEqual(
            rejection["receipt_sha256"],
            "070dea2afc4d590e1e0e4e3f25e35f9f0bbb218a5acbf71acd4de38fb2af1837",
        )
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_REVIEW")
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])

    def test_v24_preserves_v23_caps_and_mode_separation(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v24-certificate.json").read_bytes()
        )
        resource = certificate["resource_contract"]
        self.assertEqual(resource["launch_memavailable_floor_kib"], 1_900_000)
        self.assertEqual(resource["runtime_memavailable_floor_kib"], 650_000)
        self.assertEqual(resource["process_group_memory_cap_kib"], 700_000)
        self.assertEqual(resource["whole_launch_memory_cap_kib"], 700_000)
        self.assertEqual(resource["runner_seconds"], 600.0)
        self.assertEqual(resource["supervisor_wall_seconds"], 630.0)
        self.assertEqual(resource["sealed_import_probe_wall_seconds"], 180.0)
        self.assertEqual(resource["probe_outer_timeout_seconds"], 210)
        self.assertEqual(resource["official_outer_timeout_seconds"], 660)
        probe = certificate["contained_bwrap_contract"]["sealed_import_probe"]
        launch = certificate["contained_bwrap_contract"]["official_launch"]
        self.assertEqual(len(probe["argv"]), 48)
        self.assertEqual(len(launch["argv"]), 48)
        self.assertNotEqual(probe["argv_nul_sha256"], launch["argv_nul_sha256"])
        self.assertIn("--sealed-import-probe", probe["argv"])
        self.assertNotIn("--launch", probe["argv"])
        self.assertIn("--launch", launch["argv"])
        self.assertNotIn("--sealed-import-probe", launch["argv"])
        probe_text = "\0".join(probe["argv"])
        for forbidden in ("muni-fspsx-fal17.xml", "progress.json", "checkpoint", "--resume"):
            self.assertNotIn(forbidden, probe_text)

'@
    if (-not $Text.Contains($classNeedle)) {
        throw "Static contract class seam absent from transformed v24 tests"
    }
    return $Text.Replace($classNeedle, $contractTests)
}
Convert-MuniV23Text `
    "planora-muni-fspsx-frontier-v23-tests.py" `
    "planora-muni-fspsx-frontier-v24-tests.py" `
    $muniHashReplacements `
    $muniTestTransform

$muniPaths = [ordered]@{
    bootstrap = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-bootstrap.py"
    inline_trust_payload = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-inline-trust-root.txt"
    launcher = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-launcher.sh"
    supervisor = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-supervisor.py"
    runner = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-runner.py"
    v24_adversarial_tests = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-tests.py"
    generic_validator = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-generic-validator.py"
    stdlib_manifest = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-stdlib.sha256"
    minimal_tcb_manifest = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-minimal-tcb.sha256"
    benchmarks = Join-Path $muniV24Root "planora_muni_v24_benchmarks_stub.py"
    staged_audit_copy = Join-Path $muniV24Root "planora-muni-fspsx-v35-derivation-audit-v1.json"
}
$muniArtifactHashes = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $muniArtifactHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniManifestText = [System.IO.File]::ReadAllText($muniParentManifestPath, $muniUtf8NoBom)
$muniManifestText = $muniManifestText.Replace("muni_v23", "muni_v24")
$muniManifestText = $muniManifestText.Replace("frontier-v23", "frontier-v24")
$muniManifestText = $muniManifestText.Replace("V23", "V24")
$muniManifestText = $muniManifestText.Replace("v23", "v24")
foreach ($entry in $muniHashReplacements.GetEnumerator()) {
    $muniManifestText = $muniManifestText.Replace([string]$entry.Key, [string]$entry.Value)
}
$muniManifest = $muniManifestText | ConvertFrom-Json

$muniManifest.code_review_certificate_path = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-certificate.json"
$muniManifest.created_for = "v24-final-shared-core-freeze-pending-independent-review"
$muniManifest.PSObject.Properties.Remove("parent_chain")
$muniManifest.PSObject.Properties.Remove("outer_bwrap_contract")

$muniFilePathByLabel = @{
    bootstrap = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-bootstrap.py"
    inline_trust_payload = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-inline-trust-root.txt"
    launcher = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-launcher.sh"
    supervisor = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-supervisor.py"
    runner = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-runner.py"
    v24_adversarial_tests = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-tests.py"
    generic_validator = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-generic-validator.py"
    stdlib_manifest = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-stdlib.sha256"
    minimal_tcb_manifest = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-minimal-tcb.sha256"
    benchmarks = "$muniV24Wsl/planora_muni_v24_benchmarks_stub.py"
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
    powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    bash_syntax = "PENDING_CANONICAL_READ_ONLY_ENVIRONMENT"
    python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    canonical_read_only_tests = "NOT_RUN"
    sealed_import_probe = "NOT_RUN"
    official_input_opened = $false
    progress_or_checkpoint_opened = $false
    solver_run = $false
}
$muniManifest | Add-Member -NotePropertyName parent_chain -NotePropertyValue ([ordered]@{
    version = "v23"
    root = $muniV23Wsl
    builder_sha256 = $muniParentBuilderHash
    freeze_manifest_sha256 = $muniParentManifestHash
    implementation_certificate_sha256 = $muniParentCertificateHash
    inherited_historical_claims_reconstructed = $false
})
$muniManifest | Add-Member -NotePropertyName parent_v23_rejection_evidence -NotePropertyValue ([ordered]@{
    probe_id = "492e7d9acc434363b37e222289e8e554"
    decision = "REJECTED_FAIL_CLOSED_SOURCE_PIN_DRIFT"
    receipt_path = "output/diagnostic-receipts/muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.receipt.json"
    receipt_sha256 = $muniParentProbeReceiptHash
    stdout_sha256 = $muniParentProbeStdoutHash
    stderr_sha256 = $muniEmptySha256
    canonical_read_only_tests_receipt_sha256 = $muniParentCanonicalTestsReceiptHash
    child_started = $false
    official_instance_opened = $false
    progress_or_checkpoint_opened = $false
    solver_execution_started = $false
    solution_published = $false
    retry_authorized = $false
})

$muniSymbolicArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" "{INLINE_TRUST_PAYLOAD}" "{BOOTSTRAP_SHA256}" `
    "{INLINE_TRUST_SHA256}" "{EXECUTION_MODE}" "{LAUNCHER_SHA256}" `
    "{SUPERVISOR_SHA256}" "{FREEZE_MANIFEST_SHA256}"
$muniManifest | Add-Member -NotePropertyName outer_bwrap_contract -NotePropertyValue ([ordered]@{
    schema = "planora.muni-fspsx.frontier-v24.bwrap-argv.v1"
    contained_argv_count = 48
    argv_shape = $muniSymbolicArgv
    probe_outer_timeout_seconds = 210
    official_outer_timeout_seconds = 660
    host_output_root_is_fresh_private_and_bound_as_tmp = $true
})

$muniManifestPath = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-freeze-manifest.json"
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
    $muniCertificateFiles["$muniV24Wsl/$name"] = $muniArtifactHashes[$entry.Key]
}
$muniCertificateFiles["$muniV24Wsl/planora-muni-fspsx-frontier-v24-freeze-manifest.json"] = $muniManifestHash

$muniRejectionEvidence = [ordered]@{
    probe_id = "492e7d9acc434363b37e222289e8e554"
    decision = "REJECTED_FAIL_CLOSED_SOURCE_PIN_DRIFT"
    receipt_path = "output/diagnostic-receipts/muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.receipt.json"
    receipt_sha256 = $muniParentProbeReceiptHash
    stdout_path = "output/diagnostic-receipts/muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.stdout.json"
    stdout_sha256 = $muniParentProbeStdoutHash
    stderr_path = "output/diagnostic-receipts/muni-fspsx-v23-sealed-import-probe-20260827T022117Z-492e7d9acc434363b37e222289e8e554.stderr.log"
    stderr_sha256 = $muniEmptySha256
    canonical_read_only_tests_receipt_path = "output/diagnostic-receipts/muni-fspsx-v23-canonical-readonly-tests-20260827T021800Z.receipt.json"
    canonical_read_only_tests_receipt_sha256 = $muniParentCanonicalTestsReceiptHash
    expected_source_sha256 = "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05"
    observed_during_probe_sha256 = "f8148d54a352b2b1769ef58b3d82008be660016b2d7168553c94a5941a8fdb43"
    final_shared_core_sha256 = $muniFinalSharedCoreHash
    child_started = $false
    official_instance_opened = $false
    progress_or_checkpoint_opened = $false
    solver_execution_started = $false
    solution_published = $false
    automatic_probe_retry_authorized = $false
}

$muniCertificate = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v24.implementation-certificate.v1"
    status = "NO_GO_PENDING_INDEPENDENT_REVIEW"
    diagnostic_launch_status = "NO_GO_PENDING_INDEPENDENT_REVIEW"
    official_launch_status = "NO_GO_PENDING_RETAINED_PROBE_AND_INDEPENDENT_AUTHORIZATION"
    authorization = [ordered]@{
        retained_probe_authorized = $false
        official_launch_authorized = $false
        authorization_requires_new_external_review = $true
        inherited_v23_authorization = $false
    }
    canonical_certificate_path = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-certificate.json"
    scope = "fresh v24 chain over final current Planora source closure; no WSL, official input, progress, checkpoint, canonical read-only suite, retained probe, or solver was opened or run by the builder"
    parent_chain = [ordered]@{
        version = "v23"
        builder_sha256 = $muniParentBuilderHash
        freeze_manifest_sha256 = $muniParentManifestHash
        implementation_certificate_sha256 = $muniParentCertificateHash
        inherited_historical_claims_reconstructed = $false
    }
    parent_v23_rejection_evidence = $muniRejectionEvidence
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
        schema = "planora.muni-fspsx.frontier-v24.bwrap-argv.v1"
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
        parent_v23_builder_manifest_certificate = "PASS"
        parent_v23_rejection_evidence = "PASS"
        v23_files_modified = $false
        manifest_file_rows_replayed_by_builder = "PASS"
        full_repository_source_closure_replayed_by_builder = "PASS"
        exact_bwrap_argv_count = "PASS_48_PROBE_48_OFFICIAL"
        probe_and_official_argv_distinct = "PASS"
        powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        v24_windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        canonical_read_only_tests = "NOT_RUN"
        retained_probe = "NOT_RUN"
        heavy_work_skipped = $true
        official_input_opened = $false
        solver_run = $false
    }
}
$muniCertificatePath = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-certificate.json"
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
    if (-not $muniManifestRows.ContainsKey($entry.Key)) {
        throw "Generated manifest is missing source row: $($entry.Key)"
    }
    if ($muniManifestRows[$entry.Key].sha256 -ne $entry.Value) {
        throw "Generated manifest source hash replay failed: $($entry.Key)"
    }
    if ((Get-MuniSha256 $muniSourcePaths[$entry.Key]) -ne $entry.Value) {
        throw "Source changed during MUNI v24 construction: $($entry.Key)"
    }
}

foreach ($file in Get-ChildItem -LiteralPath $muniV23Root -File | Sort-Object Name) {
    if (-not $muniV23Snapshot.Contains($file.Name)) {
        throw "MUNI v23 file set changed during v24 construction"
    }
    $snapshot = $muniV23Snapshot[$file.Name]
    if ($file.Length -ne $snapshot.size_bytes -or (Get-MuniSha256 $file.FullName) -ne $snapshot.sha256) {
        throw "MUNI v23 artifact changed during v24 construction: $($file.Name)"
    }
}
if ((Get-ChildItem -LiteralPath $muniV23Root -File).Count -ne $muniV23Snapshot.Count) {
    throw "MUNI v23 file set changed during v24 construction"
}
Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v23 builder after construction"
Assert-MuniPinnedFile $muniParentProbeReceiptPath $muniParentProbeReceiptHash "MUNI v23 rejected probe receipt after construction"
Assert-MuniPinnedFile $muniParentProbeStdoutPath $muniParentProbeStdoutHash "MUNI v23 rejected probe stdout after construction"
Assert-MuniPinnedFile $muniParentProbeStderrPath $muniEmptySha256 "MUNI v23 rejected probe stderr after construction"

[ordered]@{
    target = $muniV24Root
    manifest_sha256 = $muniManifestHash
    certificate_sha256 = Get-MuniSha256 $muniCertificatePath
    contained_probe_argv_count = $muniProbeArgv.Count
    contained_probe_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniProbeArgv
    contained_official_argv_count = $muniOfficialArgv.Count
    contained_official_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniOfficialArgv
    current_source_hashes = $muniSourceHashes
    parent_v23_rejection_receipt_sha256 = $muniParentProbeReceiptHash
    retained_probe_authorized = $false
    official_launch_authorized = $false
    official_input_opened = $false
    solver_run = $false
} | ConvertTo-Json -Depth 8
