param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v12_chain.ps1"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v12"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v13"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$expectedParentBuilderSha256 = "e5955fb1e90eeb16d2938d56d1216e485356ebd07e419760b72d9c4748b8416f"
$expectedParentFreezeSha256 = "aa05feb5bf4570262b865e5a9fe745843db318ba49c4c3f2e8d519002c936fea"
$parentDriftedCoreSha256 = "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05"
$parentDriftedCoreSizeBytes = 132226
$finalCoreSha256 = "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d"
$finalCoreSizeBytes = 135881
$coreRelativePath = "benchmarks/itc2019_decomposed.py"

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
    $Text = $Text.Replace("NativeV12", "NativeV13")
    $Text = $Text.Replace("NATIVE_V12", "NATIVE_V13")
    $Text = $Text.Replace("native_v12", "native_v13")
    $Text = $Text.Replace("native-v12", "native-v13")
    $Text = $Text.Replace("aghfal17-v12", "aghfal17-v13")
    $Text = $Text.Replace("AGH-FAL17 v12", "AGH-FAL17 v13")
    $Text = $Text.Replace("agh-v12", "agh-v13")
    $Text = $Text.Replace("agh_v12", "agh_v13")
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
        throw "$Label changed while building AGH v13"
    }
}

if (-not (Test-Path -LiteralPath $parentBuilderPath)) {
    throw "AGH v12 builder is missing: $parentBuilderPath"
}
if (-not (Test-Path -LiteralPath $parentRoot)) {
    throw "AGH v12 parent chain is missing: $parentRoot"
}
if ((Get-Sha256 $parentBuilderPath) -ne $expectedParentBuilderSha256) {
    throw "AGH v12 builder evidence drifted"
}

$parentFreezePath = Join-Path $parentRoot "agent-aghfal17-native-v12-review-freeze.json"
if ((Get-Sha256 $parentFreezePath) -ne $expectedParentFreezeSha256) {
    throw "AGH v12 review-freeze evidence drifted"
}

$corePath = Join-Path $repositoryRoot ($coreRelativePath -replace '/', '\')
if ((Get-Sha256 $corePath) -ne $finalCoreSha256) {
    throw "Final shared core hash does not match the authorized AGH v13 input"
}
if ((Get-Item -LiteralPath $corePath).Length -ne $finalCoreSizeBytes) {
    throw "Final shared core size does not match the authorized AGH v13 input"
}

$parentFreeze = Get-Content -Raw -LiteralPath $parentFreezePath | ConvertFrom-Json -AsHashtable
$parentCore = $parentFreeze.source_closure[$coreRelativePath]
if (
    $parentCore.sha256 -ne $parentDriftedCoreSha256 -or
    [long]$parentCore.size_bytes -ne $parentDriftedCoreSizeBytes
) {
    throw "AGH v12 source-drift evidence no longer matches the reviewed NO-GO"
}

$parentBuilderBefore = Get-Sha256 $parentBuilderPath
$parentSnapshotBefore = Get-DirectorySnapshot $parentRoot

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existingTargetFiles = @(Get-ChildItem -LiteralPath $targetRoot -File -Force)
if ($existingTargetFiles.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v13 chain without -Force"
}

$outerV12 = Join-Path $parentRoot "agent-aghfal17-native-v12-outer-controller.py"
$testsV12 = Join-Path $parentRoot "agent-aghfal17-native-v12-tests.py"
$outerV13 = Join-Path $targetRoot "agent-aghfal17-native-v13-outer-controller.py"
$testsV13 = Join-Path $targetRoot "agent-aghfal17-native-v13-tests.py"
Write-Utf8 $outerV13 (Convert-ParentVersion (Read-Utf8 $outerV12))
Write-Utf8 $testsV13 (Convert-ParentVersion (Read-Utf8 $testsV12))

# Reuse the reviewed v12 generator logic as a template while advancing its
# source and target namespaces independently. Exact parent pins are replaced
# with the hashes present in the immutable v12 chain, so every downstream
# dependency is regenerated rather than copied with stale bindings.
$template = Read-Utf8 $parentBuilderPath
$template = $template.Replace("V12", "__AGH_V13_UPPER__")
$template = $template.Replace("V11", "V12")
$template = $template.Replace("__AGH_V13_UPPER__", "V13")
$template = $template.Replace("v12", "__agh_v13_lower__")
$template = $template.Replace("v11", "v12")
$template = $template.Replace("__agh_v13_lower__", "v13")
$template = $template.Replace("NativeV12", "NativeV13")
$template = $template.Replace("NativeV11", "NativeV12")
$template = $template.Replace(
    '$repositoryRoot = Split-Path -Parent $PSScriptRoot',
    '$repositoryRoot = $v13RepositoryRoot'
)

$pinReplacements = [ordered]@{
    "5a64e57fb81d088e97dd6f471657b9a5599d31e9fbf014dce2b31f3fd0bf09b6" = "9864bcc2222f3ca676f5226b46c8d832bcaf5031d9e3e90e3e272ae1c2fea742"
    "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" = $parentDriftedCoreSha256
    "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" = "2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2"
    "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" = "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343"
    "785cf5b950653894d82e9f118f4373faf1f68ef605c3a19bab67c996ffad4cb1" = "11801fd9cc5f853058f8e1c57a269efcae702237522c47c26a14f823d3e9044a"
    "19ca8fbe7c699ee454b90352577d0e6995a592059cd241aeb8ea6d8484f5437f" = "9864bcc2222f3ca676f5226b46c8d832bcaf5031d9e3e90e3e272ae1c2fea742"
    "0ff6364de655f1972cedf94072e707b3caad0bfa345b4ee856b1c40e8eeb80eb" = "3735de9d59f90bd1c8782d6f10d7b914cdbfd3765f56e88b3f589cffca468939"
}
foreach ($entry in $pinReplacements.GetEnumerator()) {
    if (-not $template.Contains($entry.Key)) {
        throw "AGH v12 builder template pin is absent: $($entry.Key)"
    }
    $template = $template.Replace($entry.Key, [string]$entry.Value)
}

# The v12 parent already contains the inner-wall reservation and probe-harness
# removal that the v12 builder originally applied to v11. Preserve and assert
# those semantics instead of trying to apply the migrations a second time.
$template = $template.Replace(
    '$text = Replace-Required $text "SUPERVISOR_HARD_WALL_SECONDS = 1_800.0" "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "inner cleanup wall reservation"',
    '$text = Replace-Required $text "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "inner cleanup wall preservation"'
)
$template = $template.Replace(
    '$text = Replace-Required $text "for descriptor in (bootstrap_fd, launcher_fd, bash_fd, harness_fd):" "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "bootstrap inherited descriptors"',
    '$text = Replace-Required $text "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "bootstrap inherited descriptor preservation"'
)

$v13RepositoryRoot = $repositoryRoot
$generated = & ([scriptblock]::Create($template)) -Force:$Force

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v13-review-freeze.json"
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v13-invocations.json"
$freeze = Get-Content -Raw -LiteralPath $freezePath | ConvertFrom-Json -AsHashtable
$oldFreezeHash = Get-Sha256 $freezePath

$freeze.status = "GO_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
$freeze.scope = "AGH-FAL17 v13 authoritative outer control plane frozen against the final shared core; official input never opened by this builder"
$freeze.parent_v12_review_no_go = [ordered]@{
    verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
    reason = "SOURCE_CLOSURE_DRIFT"
    parent_builder = [ordered]@{
        path = "scripts/build_agh_v12_chain.ps1"
        sha256 = $expectedParentBuilderSha256
    }
    parent_freeze = [ordered]@{
        path = "benchmarks/probe_diagnostics/agh_v12/agent-aghfal17-native-v12-review-freeze.json"
        sha256 = $expectedParentFreezeSha256
    }
    drifted_source = [ordered]@{
        path = $coreRelativePath
        frozen_size_bytes = $parentDriftedCoreSizeBytes
        frozen_sha256 = $parentDriftedCoreSha256
        reviewed_current_size_bytes = $finalCoreSizeBytes
        reviewed_current_sha256 = $finalCoreSha256
    }
    mandatory_resolution = "regenerate_complete_chain_from_current_source_closure_then_obtain_fresh_independent_review"
    v13_resolution = "complete_chain_regenerated_against_reviewed_current_source_hash"
}
$freeze.verification.static_checks = "NOT_RUN"
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
    throw "AGH v13 freeze manifest allocation rows are incomplete"
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
    throw "AGH v13 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $freezeText
if ((Get-Item -LiteralPath $freezePath).Length -ne [long]$freezeRows[0].size_bytes) {
    throw "AGH v13 freeze manifest sealed-size contract drifted"
}
$freezeHash = Get-Sha256 $freezePath

$invocations = Get-Content -Raw -LiteralPath $invocationsPath | ConvertFrom-Json -AsHashtable
if ($invocations.freeze_manifest.sha256 -ne $oldFreezeHash) {
    throw "Generated AGH v13 invocation did not bind the pre-evidence freeze"
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
        throw "AGH v13 $mode invocation freeze binding count drifted: $replacementCount"
    }
    $invocations[$mode].argv = $updatedArgv
    $invocations[$mode].canonical_argv_sha256 = Get-CanonicalArgvSha256 $updatedArgv
}
$invocations.authorization.probe_run = $false
$invocations.authorization.official_launch = $false
$invocations.authorization.official_input_opened_by_builder = $false
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 20) + "`n")

if ((Get-Sha256 $parentBuilderPath) -ne $parentBuilderBefore) {
    throw "AGH v12 builder changed while building AGH v13"
}
Assert-SnapshotsEqual $parentSnapshotBefore (Get-DirectorySnapshot $parentRoot) "AGH v12 chain"

$finalFreeze = Get-Content -Raw -LiteralPath $freezePath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.source_closure[$coreRelativePath].sha256 -ne $finalCoreSha256) {
    throw "AGH v13 final shared core pin is incoherent"
}
if ($finalFreeze.resource_contract.process_generation_vmrss_plus_vmswap_limit_kib -ne 368640) {
    throw "AGH v13 generation cap drifted"
}
if ($finalFreeze.resource_contract.whole_launch_process_plus_sealed_plus_report_limit_kib -ne 614400) {
    throw "AGH v13 whole-launch cap drifted"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v13 probe and launch command digests unexpectedly match"
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
    parent_v12_immutable = $true
    final_shared_core_sha256 = $finalCoreSha256
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 8
