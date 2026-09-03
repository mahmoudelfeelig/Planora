$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$env:COLUMNS = '32768'
$env:LINES = '1000'
$env:WSLENV = 'COLUMNS:LINES'

$repoRoot = 'D:\Stuff\Projects\Sites\Planora'
$runner = Join-Path $repoRoot 'scripts\run_muni_v32_canonical_tests.ps1'
$reviewPath = Join-Path $repoRoot 'output\diagnostic-receipts\muni-fspsx-v32-independent-review-20260828T135032Z.receipt.json'
$powershell5 = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedRunnerHash = '9af9e31ec1820183cc216f5b67beaea9836e9f547116e43658505af2f5c6543c'
$expectedAuthorizationHash = 'e60478a0f9bc8bad4a7c49123a5f9da353e608ed472191579232df2732b65d51'
$expectedReviewHash = '75147c5ed140c55ea4395e852cce3a73371c632ea481c61efe7317c354f87e2d'
$expectedV30InventoryHash = 'b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb'
$expectedV31InventoryHash = 'e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d'
$v32RunId = '4dc45edcd74446909290afadd5d3ecf0'
$v30Root = '/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01'
$v31Root = '/tmp/planora-muni-v31-canonical-tests-5f2d84640f40404a82dd180d7043d9c5'
$guards = @()

function Get-OuterSha256([string]$Path) {
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-OuterFileId([string]$Path) {
    $fsutil = Join-Path $env:SystemRoot 'System32\fsutil.exe'
    $lines = @(& $fsutil file queryfileid ([IO.Path]::GetFullPath($Path)) 2>&1)
    $exitCode = $LASTEXITCODE
    $text = $lines -join "`n"
    if ($exitCode -ne 0 -or $text -cnotmatch '(?m)^File ID is 0x([0-9a-fA-F]{32})\r?$') {
        throw "File identity query rejected: $Path"
    }
    return $Matches[1].ToLowerInvariant()
}

function Assert-OuterGuardPin([object]$Guard) {
    $pin = $Guard.Pin
    $stream = $Guard.Stream
    $full = [IO.Path]::GetFullPath((Join-Path $repoRoot ($pin.path.Replace('/', '\'))))
    $item = Get-Item -LiteralPath $full
    if ([IO.Path]::GetFullPath($stream.Name) -cne $full -or
        $item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or
        $item.Length -ne [long]$pin.size -or
        $stream.Length -ne [long]$pin.size -or
        $item.LastWriteTimeUtc.Ticks -ne [long]$pin.last_write_utc_ticks -or
        (Get-OuterFileId $full) -cne [string]$pin.file_id -or
        (Get-OuterSha256 $full) -cne [string]$pin.sha256) {
        throw "Guarded path identity rejected: $($pin.path)"
    }
    $original = $stream.Position
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        [void]$stream.Seek(0, [IO.SeekOrigin]::Begin)
        $heldHash = ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        [void]$stream.Seek($original, [IO.SeekOrigin]::Begin)
    }
    if ($heldHash -cne [string]$pin.sha256) {
        throw "Guarded same-handle bytes rejected: $($pin.path)"
    }
}

function Open-OuterGuard([object]$Pin) {
    $full = [IO.Path]::GetFullPath((Join-Path $repoRoot ($Pin.path.Replace('/', '\'))))
    $stream = New-Object IO.FileStream($full, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $guard = [pscustomobject]@{ Pin = $Pin; Stream = $stream }
    try {
        Assert-OuterGuardPin $guard
        return $guard
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Assert-ReviewReceipt {
    if ((Get-OuterSha256 $reviewPath) -cne $expectedReviewHash) {
        throw 'Independent review receipt hash rejected'
    }
    $review = [IO.File]::ReadAllText($reviewPath, (New-Object Text.UTF8Encoding($false))) | ConvertFrom-Json
    if ($review.schema -cne 'planora.muni-v32.independent-review.v1' -or
        $review.status -cne 'GO' -or
        $review.run_id -cne $v32RunId -or
        $review.verdict -cne 'GO_FOR_EXACTLY_ONE_DEFAULT_ONE_SHOT_SUBJECT_TO_ALL_LIVE_TERMINAL_GATES' -or
        -not [bool]$review.terminal_live_gates_required -or
        @($review.reviewer_tasks).Count -ne 2 -or
        @($review.blockers).Count -ne 0 -or
        [bool]$review.review_scope.quartet_edits_performed -or
        [bool]$review.review_scope.wsl_execution_performed -or
        [bool]$review.review_scope.default_runner_execution_performed -or
        [bool]$review.review_scope.canonical_execution_performed -or
        [bool]$review.review_scope.retained_v30_snapshot_path_touched -or
        [bool]$review.review_scope.retained_v31_snapshot_path_touched -or
        $review.predecessor_observations.validated_pin_count -ne 61 -or
        $review.predecessor_observations.v31_present_artifact_count -ne 14 -or
        $review.predecessor_observations.v31_expected_absent_artifact_count -ne 17 -or
        $review.fresh_state_observations.v32_run_artifact_count -ne 0 -or
        [bool]$review.fresh_state_observations.shared_lock_present) {
        throw 'Independent review receipt semantics rejected'
    }
    $reviewPins = @(
        $review.frozen_quartet.builder,
        $review.frozen_quartet.runner,
        $review.frozen_quartet.tests,
        $review.frozen_quartet.authorization
    )
    if ($reviewPins.Count -ne 4 -or
        @($reviewPins.path | Sort-Object -Unique).Count -ne 4 -or
        $review.frozen_quartet.runner.sha256 -cne $expectedRunnerHash -or
        $review.frozen_quartet.authorization.sha256 -cne $expectedAuthorizationHash) {
        throw 'Independent review frozen quartet rejected'
    }
}

function Assert-FreshV32State {
    $leaf = (Split-Path -Leaf $prefix) + '.'
    $existing = @(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force | Where-Object {
        $_.Name.IndexOf($leaf, [StringComparison]::Ordinal) -eq 0
    })
    if ($existing.Count -ne 0) {
        throw "Fresh v32 artifact namespace rejected: $($existing.Count) entries"
    }
    if (Test-Path -LiteralPath $sharedLockPath) {
        throw 'Shared heavy lock present'
    }
    [void](Assert-V28V29V30V31PassEvidenceAbsent 'outer_terminal_gate')
}

function Assert-V32RootAbsent {
    $lines = @(Invoke-WslText @('-d', 'Ubuntu', '--exec', 'test', '!', '-e', $root) 'v32 root absence gate')
    if ($lines.Count -ne 0) {
        throw 'V32 root absence command emitted output'
    }
}

function Get-CleanLiveSample([int]$Number) {
    $memory = Get-MemAvailable
    $census = Get-WslProcessCensus
    if ($memory -lt 1900000 -or @($census.rejected_workloads).Count -ne 0) {
        throw "Live resource sample rejected: $Number"
    }
    return [ordered]@{
        sample = $Number
        at_utc = [DateTime]::UtcNow.ToString('o')
        memavailable_kib = $memory
        census_rows = @($census.rows).Count
        rejected_workloads = @($census.rejected_workloads).Count
    }
}

function Invoke-RetainedSnapshotsChild {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powershell5
    $startInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runner -RetainedPredecessorSnapshotsSelfTest"
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'Retained snapshots child start failed'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(300000)) {
            try { $process.Kill() } catch {}
            throw 'Retained snapshots child deadline exceeded'
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $stderr.Length -ne 0) {
            throw "Retained snapshots child rejected: exit=$($process.ExitCode) stderr=$stderr"
        }
    }
    finally {
        $process.Dispose()
    }
    $trimmed = $stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.IndexOf("`n", [StringComparison]::Ordinal) -ge 0) {
        throw 'Retained snapshots child output grammar rejected'
    }
    $result = $trimmed | ConvertFrom-Json
    if ($result.schema -cne 'planora.muni-v32.retained-predecessor-snapshots-self-test.v1' -or
        $result.status -cne 'PASS' -or
        $result.run_id -cne $v32RunId -or
        $result.runner_sha256 -cne $expectedRunnerHash -or
        $result.authorization_sha256 -cne $expectedAuthorizationHash -or
        [bool]$result.canonical_suite_executed -or
        [bool]$result.shared_lock_used -or
        [bool]$result.claim_created -or
        [bool]$result.v32_artifacts_created -or
        $result.v30.schema -cne 'planora.muni-v32.retained-snapshot-replay.v1' -or
        $result.v30.status -cne 'EXACT_RETAINED_SNAPSHOT_REPLAY' -or
        $result.v30.phase -cne 'isolated_nonconsuming_v30_preflight' -or
        $result.v30.root -cne $v30Root -or
        $result.v30.files -ne 3146 -or
        $result.v30.directories -ne 368 -or
        $result.v30.bytes -ne 190900047 -or
        $result.v30.inventory_sha256 -cne $expectedV30InventoryHash -or
        -not [bool]$result.v30.all_nlink_one -or
        $result.v31.schema -cne 'planora.muni-v32.retained-snapshot-replay.v1' -or
        $result.v31.status -cne 'EXACT_RETAINED_SNAPSHOT_REPLAY' -or
        $result.v31.phase -cne 'isolated_nonconsuming_v31_preflight' -or
        $result.v31.root -cne $v31Root -or
        $result.v31.files -ne 3146 -or
        $result.v31.directories -ne 368 -or
        $result.v31.bytes -ne 190900047 -or
        $result.v31.inventory_sha256 -cne $expectedV31InventoryHash -or
        -not [bool]$result.v31.all_nlink_one) {
        throw 'Retained snapshots child evidence rejected'
    }
    return $result
}

$quartet = @(
    [pscustomobject]@{ path = 'scripts/build_muni_v32_successor.py'; size = 67244; sha256 = '0f40634fd7521318b375225a60bc3d1a935bc0a952915f5a3a0857c7d827ba9a'; file_id = '0000000000000000000300000017c009'; last_write_utc_ticks = 639235212275291720 },
    [pscustomobject]@{ path = 'scripts/run_muni_v32_canonical_tests.ps1'; size = 279918; sha256 = '9af9e31ec1820183cc216f5b67beaea9836e9f547116e43658505af2f5c6543c'; file_id = '0000000000000000000600000017c00b'; last_write_utc_ticks = 639235213445549061 },
    [pscustomobject]@{ path = 'tests/test_run_muni_v32_successor.py'; size = 28634; sha256 = '2875be0c8c64d48ff2fe5557b3a7e1e7f43ebd14232a226ac078cb0e0a96e693'; file_id = '0000000000000000000200000017c00d'; last_write_utc_ticks = 639235212434722970 },
    [pscustomobject]@{ path = 'output/diagnostic-receipts/muni-fspsx-v32-canonical-tests-authorization-20260828T130114Z.receipt.json'; size = 32075; sha256 = 'e60478a0f9bc8bad4a7c49123a5f9da353e608ed472191579232df2732b65d51'; file_id = '0000000000000000000400000017c010'; last_write_utc_ticks = 639235213453536795 }
)
$reviewPin = [pscustomobject]@{ path = 'output/diagnostic-receipts/muni-fspsx-v32-independent-review-20260828T135032Z.receipt.json'; size = 7206; sha256 = '75147c5ed140c55ea4395e852cce3a73371c632ea481c61efe7317c354f87e2d'; file_id = '0000000000000000000200000017c4e2'; last_write_utc_ticks = 639235218865814146 }

try {
    foreach ($pin in @($quartet) + @($reviewPin)) {
        $guards += ,(Open-OuterGuard $pin)
    }
    Assert-ReviewReceipt

    $savedConsoleOut = [Console]::Out
    try {
        [Console]::SetOut([IO.TextWriter]::Null)
        . $runner -StaticSelfTest
    }
    finally {
        [Console]::SetOut($savedConsoleOut)
    }

    $authorizationState = Get-AuthorizationState
    if ($authorizationState.runner_sha256 -cne $expectedRunnerHash -or
        $authorizationState.authorization_sha256 -cne $expectedAuthorizationHash) {
        throw 'Authorization state hash rejected'
    }
    $predecessor = Get-ValidatedCompletePredecessorEvidence $true
    $pins = @(Get-CompletePredecessorPinArray $predecessor)
    if ($pins.Count -ne 61 -or @($pins.path | Sort-Object -Unique).Count -ne 61) {
        throw 'Complete predecessor pin cardinality rejected'
    }
    $archivePins = @($pins | Where-Object { $_.path -ceq $staleArchiveRelative })
    $ordinaryPins = @($pins | Where-Object { $_.path -cne $staleArchiveRelative })
    if ($archivePins.Count -ne 1 -or $ordinaryPins.Count -ne 60) {
        throw 'Archived versus guardable predecessor partition rejected'
    }
    foreach ($pin in $ordinaryPins) {
        $guards += ,(Open-OuterGuard $pin)
    }
    if ($guards.Count -ne 65 -or @($guards.Pin.path | Sort-Object -Unique).Count -ne 65) {
        throw 'Outer read-guard census rejected'
    }
    foreach ($guard in $guards) {
        Assert-OuterGuardPin $guard
    }
    $predecessor = Get-ValidatedCompletePredecessorEvidence $true
    [void](Assert-FinalArchivedStaleLockIdentity $archivePins[0] 'outer_before_live_samples' $true)
    Assert-FreshV32State
    Assert-V32RootAbsent

    $sample1 = Get-CleanLiveSample 1
    $separation = [Diagnostics.Stopwatch]::StartNew()
    Start-Sleep -Seconds 5
    $sample2 = Get-CleanLiveSample 2
    if ($separation.ElapsedMilliseconds -lt 5000) {
        throw 'Outer memory sample separation rejected'
    }

    $retained = Invoke-RetainedSnapshotsChild
    $sample3 = Get-CleanLiveSample 3
    Assert-V32RootAbsent
    Assert-FreshV32State
    foreach ($guard in $guards) {
        Assert-OuterGuardPin $guard
    }
    $authorizationState = Get-AuthorizationState
    if ($authorizationState.runner_sha256 -cne $expectedRunnerHash -or
        $authorizationState.authorization_sha256 -cne $expectedAuthorizationHash) {
        throw 'Final authorization state hash rejected'
    }
    $finalPredecessor = Get-ValidatedCompletePredecessorEvidence $true
    if (@(Get-CompletePredecessorPinArray $finalPredecessor).Count -ne 61) {
        throw 'Final predecessor replay count rejected'
    }
    [void](Assert-FinalArchivedStaleLockIdentity $archivePins[0] 'outer_immediately_before_default' $true)
    Assert-ReviewReceipt
    Assert-FreshV32State
    Assert-V32RootAbsent

    [Console]::Out.WriteLine(([ordered]@{
        schema = 'planora.muni-v32.outer-terminal-live-gate.v1'
        status = 'PASS_IMMEDIATELY_BEFORE_EXACTLY_ONE_DEFAULT_INVOCATION'
        run_id = $v32RunId
        guarded_paths = $guards.Count
        guarded_predecessor_paths = $ordinaryPins.Count
        unguarded_exclusively_replayed_archive_paths = $archivePins.Count
        runner_sha256 = $authorizationState.runner_sha256
        authorization_sha256 = $authorizationState.authorization_sha256
        independent_review_sha256 = $expectedReviewHash
        sample1 = $sample1
        sample2 = $sample2
        sample_separation_milliseconds = $separation.ElapsedMilliseconds
        retained_v30_snapshot = $retained.v30
        retained_v31_snapshot = $retained.v31
        final_sample = $sample3
        v32_artifacts = 0
        shared_lock_present = $false
        default_invocation_count = 0
    } | ConvertTo-Json -Depth 8 -Compress))

    $defaultInvocationCount = 0
    if ($defaultInvocationCount -ne 0) {
        throw 'Default v32 invocation already attempted'
    }
    $defaultInvocationCount = 1
    & $runner
}
finally {
    foreach ($guard in $guards) {
        try { $guard.Stream.Dispose() } catch {}
    }
}
