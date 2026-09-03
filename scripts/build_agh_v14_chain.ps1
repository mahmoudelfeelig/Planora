param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$baseBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v12_chain.ps1"
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v13_chain.ps1"
$v12Root = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v12"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v13"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v14"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$expectedBaseBuilderSha256 = "e5955fb1e90eeb16d2938d56d1216e485356ebd07e419760b72d9c4748b8416f"
$expectedParentBuilderSha256 = "61e740f31e3eb9db4ea5f77cacb252e6379c05e4db527abf4536d9ea708c9c33"
$expectedParentFreezeSha256 = "f0d6fa120c7e96801fa80f248efcaaa98a89ac88eb0b649bf279b46f4d3a9278"
$expectedV12FreezeSha256 = "aa05feb5bf4570262b865e5a9fe745843db318ba49c4c3f2e8d519002c936fea"
$v12FrozenCoreSha256 = "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05"
$v12FrozenCoreSizeBytes = 132226
$parentFrozenCoreSha256 = "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d"
$parentFrozenCoreSizeBytes = 135881
$finalCoreSha256 = "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf"
$finalCoreSizeBytes = 135880
$focusedTestSha256 = "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d"
$focusedTestSizeBytes = 7138
$coreRelativePath = "benchmarks/itc2019_decomposed.py"
$focusedTestRelativePath = "tests/test_itc2019_decomposed_extended_budget.py"

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, $utf8NoBom)
}

function Write-Utf8([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Convert-ParentVersion([string]$Text) {
    $Text = $Text.Replace("NativeV13", "NativeV14")
    $Text = $Text.Replace("NATIVE_V13", "NATIVE_V14")
    $Text = $Text.Replace("native_v13", "native_v14")
    $Text = $Text.Replace("native-v13", "native-v14")
    $Text = $Text.Replace("aghfal17-v13", "aghfal17-v14")
    $Text = $Text.Replace("AGH-FAL17 v13", "AGH-FAL17 v14")
    $Text = $Text.Replace("agh-v13", "agh-v14")
    $Text = $Text.Replace("agh_v13", "agh_v14")
    return $Text
}

function Get-CanonicalArgvSha256([object[]]$Argv) {
    $values = @($Argv | ForEach-Object { [string]$_ })
    foreach ($value in $values) {
        if ($value.Contains([char]0)) {
            throw "Canonical argv contains NUL"
        }
    }
    $raw = $utf8NoBom.GetBytes([string]::Join([char]0, $values))
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($digest.ComputeHash($raw))).ToLowerInvariant()
    }
    finally {
        $digest.Dispose()
    }
}

function Get-DirectorySnapshot([string]$Root) {
    $snapshot = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = [System.IO.Path]::GetRelativePath($Root, $_.FullName).Replace("\", "/")
            $snapshot[$relative] = [ordered]@{
                size_bytes = $_.Length
                sha256 = Get-Sha256 $_.FullName
            }
        }
    return $snapshot
}

function Assert-SnapshotsEqual([hashtable]$Before, [hashtable]$After, [string]$Label) {
    $beforeJson = $Before | ConvertTo-Json -Depth 6 -Compress
    $afterJson = $After | ConvertTo-Json -Depth 6 -Compress
    if ($beforeJson -cne $afterJson) {
        throw "$Label changed while building AGH v14"
    }
}

foreach ($required in @($baseBuilderPath, $parentBuilderPath, $v12Root, $parentRoot)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required AGH v14 derivation input is missing: $required"
    }
}
if ((Get-Sha256 $baseBuilderPath) -ne $expectedBaseBuilderSha256) {
    throw "AGH v12 base builder evidence drifted"
}
if ((Get-Sha256 $parentBuilderPath) -ne $expectedParentBuilderSha256) {
    throw "AGH v13 parent builder evidence drifted"
}

$v12FreezePath = Join-Path $v12Root "agent-aghfal17-native-v12-review-freeze.json"
$parentFreezePath = Join-Path $parentRoot "agent-aghfal17-native-v13-review-freeze.json"
if ((Get-Sha256 $v12FreezePath) -ne $expectedV12FreezeSha256) {
    throw "AGH v12 review-freeze evidence drifted"
}
if ((Get-Sha256 $parentFreezePath) -ne $expectedParentFreezeSha256) {
    throw "AGH v13 review-freeze evidence drifted"
}

$corePath = Join-Path $repositoryRoot ($coreRelativePath -replace '/', '\')
$focusedTestPath = Join-Path $repositoryRoot ($focusedTestRelativePath -replace '/', '\')
if ((Get-Sha256 $corePath) -ne $finalCoreSha256) {
    throw "Final shared core hash does not match the authorized AGH v14 input"
}
if ((Get-Item -LiteralPath $corePath).Length -ne $finalCoreSizeBytes) {
    throw "Final shared core size does not match the authorized AGH v14 input"
}
if ((Get-Sha256 $focusedTestPath) -ne $focusedTestSha256) {
    throw "Focused shared-core regression test hash does not match the AGH v14 input"
}
if ((Get-Item -LiteralPath $focusedTestPath).Length -ne $focusedTestSizeBytes) {
    throw "Focused shared-core regression test size does not match the AGH v14 input"
}

$v12Freeze = Get-Content -Raw -LiteralPath $v12FreezePath | ConvertFrom-Json -AsHashtable
$parentFreeze = Get-Content -Raw -LiteralPath $parentFreezePath | ConvertFrom-Json -AsHashtable
if (
    $v12Freeze.source_closure[$coreRelativePath].sha256 -ne $v12FrozenCoreSha256 -or
    [long]$v12Freeze.source_closure[$coreRelativePath].size_bytes -ne $v12FrozenCoreSizeBytes
) {
    throw "AGH v12 source-drift NO-GO context no longer replays"
}
if (
    $parentFreeze.source_closure[$coreRelativePath].sha256 -ne $parentFrozenCoreSha256 -or
    [long]$parentFreeze.source_closure[$coreRelativePath].size_bytes -ne $parentFrozenCoreSizeBytes
) {
    throw "AGH v13 source-drift NO-GO context no longer replays"
}

$baseBuilderBefore = Get-Sha256 $baseBuilderPath
$parentBuilderBefore = Get-Sha256 $parentBuilderPath
$v12SnapshotBefore = Get-DirectorySnapshot $v12Root
$parentSnapshotBefore = Get-DirectorySnapshot $parentRoot

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existingTargetFiles = @(Get-ChildItem -LiteralPath $targetRoot -File -Force)
if ($existingTargetFiles.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v14 chain without -Force"
}

$outerV13 = Join-Path $parentRoot "agent-aghfal17-native-v13-outer-controller.py"
$testsV13 = Join-Path $parentRoot "agent-aghfal17-native-v13-tests.py"
$outerV14 = Join-Path $targetRoot "agent-aghfal17-native-v14-outer-controller.py"
$testsV14 = Join-Path $targetRoot "agent-aghfal17-native-v14-tests.py"
Write-Utf8 $outerV14 (Convert-ParentVersion (Read-Utf8 $outerV13))
$testsText = Convert-ParentVersion (Read-Utf8 $testsV13)
$testsText = $testsText.Replace(
    "def test_no_v11_protocol_tokens_in_active_v12_artifacts(self) -> None:",
    "def test_no_v13_protocol_tokens_in_active_v14_artifacts(self) -> None:"
)
$testsText = $testsText.Replace(
    'self.assertNotIn("native-v11", path.read_text(encoding="utf-8"), path.name)',
    'self.assertNotIn("native-v13", path.read_text(encoding="utf-8"), path.name)'
)
$testsText = $testsText.Replace(
    'self.assertNotIn("NATIVE_V11", path.read_text(encoding="utf-8"), path.name)',
    'self.assertNotIn("NATIVE_V13", path.read_text(encoding="utf-8"), path.name)'
)
$testsInsertionMarker = "@unittest.skipUnless(`n    os.name == `"posix`""
if (-not $testsText.Contains($testsInsertionMarker)) {
    throw "AGH v14 focused freeze-test insertion marker is absent"
}
$additionalTests = @'
class V14FreezeReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        cls.invocations = json.loads(INVOCATIONS_PATH.read_text(encoding="utf-8"))

    def test_v14_is_review_ready_but_execution_unauthorized(self) -> None:
        self.assertEqual(
            self.freeze["status"],
            "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH",
        )
        verification = self.freeze["verification"]
        self.assertFalse(verification["probe_run_authorized"])
        self.assertFalse(verification["official_launch_authorized"])
        self.assertFalse(verification["official_input_opened"])
        self.assertFalse(verification["solver_started"])
        self.assertFalse(self.invocations["authorization"]["probe_run"])
        self.assertFalse(self.invocations["authorization"]["official_launch"])

    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
        closure = self.freeze["source_closure"]
        self.assertEqual(
            closure["benchmarks/itc2019_decomposed.py"]["sha256"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        self.assertEqual(
            closure["tests/test_itc2019_decomposed_extended_budget.py"]["sha256"],
            "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
        )

    def test_v12_and_v13_source_drift_no_go_context_is_retained(self) -> None:
        context = self.freeze["predecessor_source_drift_no_go"]
        self.assertEqual(context["v12"]["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(context["v13"]["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["v12"]["frozen_source"]["sha256"],
            "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05",
        )
        self.assertEqual(
            context["v13"]["frozen_source"]["sha256"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            context["v13"]["reviewed_current_source"]["sha256"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )


'@
$testsText = $testsText.Replace($testsInsertionMarker, $additionalTests + $testsInsertionMarker)
Write-Utf8 $testsV14 $testsText

# Reuse the stable v12 generator mechanics while sourcing every active control
# artifact from corrected v13. Exact v13 pins force complete regeneration and
# prevent a superficially versioned chain from retaining stale dependencies.
$template = Read-Utf8 $baseBuilderPath
$template = $template.Replace("V12", "__AGH_V14_UPPER__")
$template = $template.Replace("V11", "V13")
$template = $template.Replace("__AGH_V14_UPPER__", "V14")
$template = $template.Replace("v12", "__agh_v14_lower__")
$template = $template.Replace("v11", "v13")
$template = $template.Replace("__agh_v14_lower__", "v14")
$template = $template.Replace("NativeV12", "NativeV14")
$template = $template.Replace("NativeV11", "NativeV13")
$template = $template.Replace(
    '$repositoryRoot = Split-Path -Parent $PSScriptRoot',
    '$repositoryRoot = $v14RepositoryRoot'
)

$pinReplacements = [ordered]@{
    "5a64e57fb81d088e97dd6f471657b9a5599d31e9fbf014dce2b31f3fd0bf09b6" = "acd7ad619da2de36baf5a2c40160077b9e6eced9504687d8b563c08c7b693a89"
    "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" = $parentFrozenCoreSha256
    "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" = "2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2"
    "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" = "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343"
    "785cf5b950653894d82e9f118f4373faf1f68ef605c3a19bab67c996ffad4cb1" = "2f900764a4bf9a1e5090cdf53bfbcaedee0a51c50fadaf2f6825bfaca84fcb2f"
    "19ca8fbe7c699ee454b90352577d0e6995a592059cd241aeb8ea6d8484f5437f" = "acd7ad619da2de36baf5a2c40160077b9e6eced9504687d8b563c08c7b693a89"
    "0ff6364de655f1972cedf94072e707b3caad0bfa345b4ee856b1c40e8eeb80eb" = "0815dad7ce1d163bd33018642e1332097b1f15211b7f30a8d1faa719858268b2"
}
foreach ($entry in $pinReplacements.GetEnumerator()) {
    if (-not $template.Contains($entry.Key)) {
        throw "AGH v12 base-builder template pin is absent: $($entry.Key)"
    }
    $template = $template.Replace($entry.Key, [string]$entry.Value)
}

# Corrected v13 already carries these containment-preserving transformations.
$template = $template.Replace(
    '$text = Replace-Required $text "SUPERVISOR_HARD_WALL_SECONDS = 1_800.0" "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "inner cleanup wall reservation"',
    '$text = Replace-Required $text "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "inner cleanup wall preservation"'
)
$template = $template.Replace(
    '$text = Replace-Required $text "for descriptor in (bootstrap_fd, launcher_fd, bash_fd, harness_fd):" "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "bootstrap inherited descriptors"',
    '$text = Replace-Required $text "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "bootstrap inherited descriptor preservation"'
)

$v14RepositoryRoot = $repositoryRoot
$generated = & ([scriptblock]::Create($template)) -Force:$Force

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v14-review-freeze.json"
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v14-invocations.json"
$freeze = Get-Content -Raw -LiteralPath $freezePath | ConvertFrom-Json -AsHashtable
$oldFreezeHash = Get-Sha256 $freezePath

$freeze.status = "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
$freeze.scope = "AGH-FAL17 v14 corrected containment chain frozen against the final shared core and focused regression; official input never opened by this builder"
$freeze.source_closure[$focusedTestRelativePath] = [ordered]@{
    size_bytes = $focusedTestSizeBytes
    sha256 = $focusedTestSha256
    role = "focused_semantics_and_bounded_streaming_regression"
}
$freeze.predecessor_source_drift_no_go = [ordered]@{
    v12 = [ordered]@{
        verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
        reason = "SOURCE_CLOSURE_DRIFT"
        builder = [ordered]@{ path = "scripts/build_agh_v12_chain.ps1"; sha256 = $expectedBaseBuilderSha256 }
        freeze = [ordered]@{ path = "benchmarks/probe_diagnostics/agh_v12/agent-aghfal17-native-v12-review-freeze.json"; sha256 = $expectedV12FreezeSha256 }
        frozen_source = [ordered]@{ path = $coreRelativePath; size_bytes = $v12FrozenCoreSizeBytes; sha256 = $v12FrozenCoreSha256 }
        reviewed_current_source = [ordered]@{ path = $coreRelativePath; size_bytes = $parentFrozenCoreSizeBytes; sha256 = $parentFrozenCoreSha256 }
        required_resolution = "regenerate_complete_chain_then_obtain_fresh_independent_review"
    }
    v13 = [ordered]@{
        verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
        reason = "SOURCE_CLOSURE_DRIFT_AFTER_SHARED_CORE_EMPTY_TABLE_SEMANTICS_FIX"
        builder = [ordered]@{ path = "scripts/build_agh_v13_chain.ps1"; sha256 = $expectedParentBuilderSha256 }
        freeze = [ordered]@{ path = "benchmarks/probe_diagnostics/agh_v13/agent-aghfal17-native-v13-review-freeze.json"; sha256 = $expectedParentFreezeSha256 }
        frozen_source = [ordered]@{ path = $coreRelativePath; size_bytes = $parentFrozenCoreSizeBytes; sha256 = $parentFrozenCoreSha256 }
        reviewed_current_source = [ordered]@{ path = $coreRelativePath; size_bytes = $finalCoreSizeBytes; sha256 = $finalCoreSha256 }
        focused_regression = [ordered]@{ path = $focusedTestRelativePath; size_bytes = $focusedTestSizeBytes; sha256 = $focusedTestSha256 }
        required_resolution = "regenerate_complete_chain_against_final_shared_core_then_obtain_fresh_independent_review"
    }
    v14_resolution = "complete_chain_regenerated_from_corrected_v13_containment_against_final_shared_core_and_focused_regression"
}
$freeze.verification.static_checks = "NOT_RUN_BY_BUILDER_REQUIRES_FRESH_WINDOWS_SAFE_REPLAY"
$freeze.verification.linux_adversarial_tests = "NOT_RUN"
$freeze.verification.sealed_import_probe = "NOT_RUN"
$freeze.verification.official_input_opened = $false
$freeze.verification.solver_started = $false
$freeze.verification.probe_run_authorized = $false
$freeze.verification.official_launch_authorized = $false

$freezeRows = @(
    $freeze.sealed_storage_contract.probe.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
) + @(
    $freeze.sealed_storage_contract.launch.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
)
if ($freezeRows.Count -ne 2) {
    throw "AGH v14 freeze manifest allocation rows are incomplete"
}

$freezeText = $null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $candidate = ($freeze | ConvertTo-Json -Depth 20) + "`n"
    $candidateSize = $utf8NoBom.GetByteCount($candidate)
    $sizes = @($freezeRows | ForEach-Object { [long]$_.size_bytes } | Select-Object -Unique)
    if ($sizes.Count -eq 1 -and $sizes[0] -eq $candidateSize) {
        $freezeText = $candidate
        break
    }
    foreach ($row in $freezeRows) {
        $row.size_bytes = $candidateSize
    }
}
if ($null -eq $freezeText) {
    throw "AGH v14 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $freezeText
if ((Get-Item -LiteralPath $freezePath).Length -ne [long]$freezeRows[0].size_bytes) {
    throw "AGH v14 freeze manifest sealed-size contract drifted"
}
$freezeHash = Get-Sha256 $freezePath

$invocations = Get-Content -Raw -LiteralPath $invocationsPath | ConvertFrom-Json -AsHashtable
if ($invocations.freeze_manifest.sha256 -ne $oldFreezeHash) {
    throw "Generated AGH v14 invocation did not bind the pre-evidence freeze"
}
$invocations.freeze_manifest.sha256 = $freezeHash
foreach ($mode in @("probe", "launch")) {
    $replacementCount = 0
    $updatedArgv = @(
        $invocations[$mode].argv | ForEach-Object {
            if ([string]$_ -eq $oldFreezeHash) {
                $replacementCount++
                $freezeHash
            }
            else {
                [string]$_
            }
        }
    )
    if ($replacementCount -ne 2) {
        throw "AGH v14 $mode invocation freeze binding count drifted: $replacementCount"
    }
    $invocations[$mode].argv = $updatedArgv
    $invocations[$mode].canonical_argv_sha256 = Get-CanonicalArgvSha256 $updatedArgv
}
$invocations.authorization.probe_run = $false
$invocations.authorization.official_launch = $false
$invocations.authorization.official_input_opened_by_builder = $false
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 20) + "`n")

if ((Get-Sha256 $baseBuilderPath) -ne $baseBuilderBefore) {
    throw "AGH v12 builder changed while building AGH v14"
}
if ((Get-Sha256 $parentBuilderPath) -ne $parentBuilderBefore) {
    throw "AGH v13 builder changed while building AGH v14"
}
Assert-SnapshotsEqual $v12SnapshotBefore (Get-DirectorySnapshot $v12Root) "AGH v12 chain"
Assert-SnapshotsEqual $parentSnapshotBefore (Get-DirectorySnapshot $parentRoot) "AGH v13 chain"

$finalFreeze = Get-Content -Raw -LiteralPath $freezePath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.source_closure[$coreRelativePath].sha256 -ne $finalCoreSha256) {
    throw "AGH v14 final shared core pin is incoherent"
}
if ($finalFreeze.source_closure[$focusedTestRelativePath].sha256 -ne $focusedTestSha256) {
    throw "AGH v14 focused regression pin is incoherent"
}
if ($finalFreeze.resource_contract.process_generation_vmrss_plus_vmswap_limit_kib -ne 368640) {
    throw "AGH v14 generation cap drifted"
}
if ($finalFreeze.resource_contract.whole_launch_process_plus_sealed_plus_report_limit_kib -ne 614400) {
    throw "AGH v14 whole-launch cap drifted"
}
if ($finalFreeze.resource_contract.initial_memavailable_floor_kib -ne 1900000) {
    throw "AGH v14 initial memory floor drifted"
}
if ($finalFreeze.resource_contract.runtime_memavailable_floor_kib -ne 900000) {
    throw "AGH v14 runtime memory floor drifted"
}
if ($finalFreeze.resource_contract.exact_identity -ne "pid_plus_starttime_plus_pidfd") {
    throw "AGH v14 process-generation identity drifted"
}
if ($finalFreeze.resource_contract.final_zero_snapshots_required -ne 2) {
    throw "AGH v14 stable-zero requirement drifted"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v14 probe and launch command digests unexpectedly match"
}
if ($finalFreeze.verification.probe_run_authorized -or $finalFreeze.verification.official_launch_authorized) {
    throw "AGH v14 execution authorization unexpectedly enabled"
}

$artifactRows = [ordered]@{}
Get-ChildItem -LiteralPath $targetRoot -File | Sort-Object Name | ForEach-Object {
    $artifactRows[$_.Name] = [ordered]@{
        size_bytes = $_.Length
        sha256 = Get-Sha256 $_.FullName
    }
}

[ordered]@{
    target = $targetRoot
    status = $finalFreeze.status
    v12_immutable = $true
    v13_immutable = $true
    final_shared_core_sha256 = $finalCoreSha256
    focused_regression_sha256 = $focusedTestSha256
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 8
