$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = 'D:\Stuff\Projects\Sites\Planora'
$runner = Join-Path $repoRoot 'scripts\run_muni_v31_canonical_tests.ps1'
$reviewPath = Join-Path $repoRoot 'output\diagnostic-receipts\muni-fspsx-v31-independent-review-20260828T-final.receipt.json'
$powershell5 = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedRunnerHash = 'ee8fcdd6cb1fdc03e9e7ac9eb792746239afbb8f9c818fc216427e8dbdd3b71c'
$expectedAuthorizationHash = '8b1530c6afb5ef0dd0e1469ab69d798e91c70fe2070956517a6f164ec8c4d6ff'
$expectedReviewHash = 'ce446aa17a55b7e4fc4259cde8916b1205bcd4a5fe9065dfb778810a63bec1ed'
$expectedV30InventoryHash = 'b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb'
$v31RunId = '5f2d84640f40404a82dd180d7043d9c5'
$v30Root = '/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01'
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
    if ($review.schema -cne 'planora.muni-v31.independent-review.v1' -or
        $review.status -cne 'GO' -or
        $review.run_id -cne $v31RunId -or
        $review.verdict -cne 'GO_FOR_EXACTLY_ONE_DEFAULT_ONE_SHOT_SUBJECT_TO_ALL_LIVE_TERMINAL_GATES' -or
        -not [bool]$review.terminal_live_gates_required -or
        @($review.blockers).Count -ne 0 -or
        [bool]$review.review_scope.quartet_edits_performed -or
        [bool]$review.review_scope.wsl_execution_performed -or
        [bool]$review.review_scope.default_runner_execution_performed -or
        [bool]$review.review_scope.canonical_execution_performed) {
        throw 'Independent review receipt semantics rejected'
    }
}

function Assert-FreshV31State {
    $leaf = (Split-Path -Leaf $prefix) + '.'
    $existing = @(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force | Where-Object {
        $_.Name.IndexOf($leaf, [StringComparison]::Ordinal) -eq 0
    })
    if ($existing.Count -ne 0) {
        throw "Fresh v31 artifact namespace rejected: $($existing.Count) entries"
    }
    if (Test-Path -LiteralPath $sharedLockPath) {
        throw 'Shared heavy lock present'
    }
    [void](Assert-V28V29V30PassEvidenceAbsent 'outer_terminal_gate')
}

function Assert-V31RootAbsent {
    $lines = @(Invoke-WslText @('-d', 'Ubuntu', '--exec', 'test', '!', '-e', $root) 'v31 root absence gate')
    if ($lines.Count -ne 0) {
        throw 'V31 root absence command emitted output'
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

function Invoke-RetainedSnapshotChild {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powershell5
    $startInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runner -RetainedV30SnapshotSelfTest"
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'Retained snapshot child start failed'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(300000)) {
            try { $process.Kill() } catch {}
            throw 'Retained snapshot child deadline exceeded'
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $stderr.Length -ne 0) {
            throw "Retained snapshot child rejected: exit=$($process.ExitCode) stderr=$stderr"
        }
    }
    finally {
        $process.Dispose()
    }
    $trimmed = $stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.IndexOf("`n", [StringComparison]::Ordinal) -ge 0) {
        throw 'Retained snapshot child output grammar rejected'
    }
    $result = $trimmed | ConvertFrom-Json
    if ($result.schema -cne 'planora.muni-v31.retained-v30-snapshot-self-test.v1' -or
        $result.status -cne 'PASS' -or
        $result.run_id -cne $v31RunId -or
        $result.runner_sha256 -cne $expectedRunnerHash -or
        $result.authorization_sha256 -cne $expectedAuthorizationHash -or
        [bool]$result.canonical_suite_executed -or
        [bool]$result.shared_lock_used -or
        [bool]$result.claim_created -or
        [bool]$result.v31_artifacts_created -or
        $result.replay.status -cne 'EXACT_RETAINED_V30_SNAPSHOT_REPLAY' -or
        $result.replay.phase -cne 'isolated_nonconsuming_preflight' -or
        $result.replay.root -cne $v30Root -or
        $result.replay.files -ne 3146 -or
        $result.replay.directories -ne 368 -or
        $result.replay.bytes -ne 190900047 -or
        $result.replay.inventory_sha256 -cne $expectedV30InventoryHash -or
        -not [bool]$result.replay.all_nlink_one) {
        throw 'Retained snapshot child evidence rejected'
    }
    return $result
}

$quartet = @(
    [pscustomobject]@{ path = 'scripts/build_muni_v31_successor.py'; size = 69258; sha256 = 'c08338a076d08336f704e4fe364cdd15ba78904bbc9b4cdc2a96d262e493079e'; file_id = '0000000000000000000900000017267f'; last_write_utc_ticks = 639235163968391371 },
    [pscustomobject]@{ path = 'scripts/run_muni_v31_canonical_tests.ps1'; size = 238063; sha256 = 'ee8fcdd6cb1fdc03e9e7ac9eb792746239afbb8f9c818fc216427e8dbdd3b71c'; file_id = '0000000000000000000400000017be91'; last_write_utc_ticks = 639235164588218285 },
    [pscustomobject]@{ path = 'tests/test_run_muni_v31_successor.py'; size = 27636; sha256 = 'be3eb15ba49c3c9b0a5ed0c6d579ab0e83775dc054ff3e9e65ffdef48be5c9fb'; file_id = '0000000000000000000200000017be40'; last_write_utc_ticks = 639235164237482474 },
    [pscustomobject]@{ path = 'output/diagnostic-receipts/muni-fspsx-v31-canonical-tests-authorization-20260828T113225Z.receipt.json'; size = 20872; sha256 = '8b1530c6afb5ef0dd0e1469ab69d798e91c70fe2070956517a6f164ec8c4d6ff'; file_id = '0000000000000000000300000017be92'; last_write_utc_ticks = 639235164595640475 }
)
$reviewPin = [pscustomobject]@{ path = 'output/diagnostic-receipts/muni-fspsx-v31-independent-review-20260828T-final.receipt.json'; size = 5988; sha256 = 'ce446aa17a55b7e4fc4259cde8916b1205bcd4a5fe9065dfb778810a63bec1ed'; file_id = '0000000000000000000400000017be5c'; last_write_utc_ticks = 639235169407805911 }

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
    $predecessor = Get-ValidatedCombinedPredecessorEvidence $true
    $pins = @(Get-CombinedPredecessorPinArray $predecessor)
    if ($pins.Count -ne 41 -or @($pins.path | Sort-Object -Unique).Count -ne 41) {
        throw 'Combined predecessor pin cardinality rejected'
    }
    $archivePins = @($pins | Where-Object { $_.path -ceq $staleArchiveRelative })
    $ordinaryPins = @($pins | Where-Object { $_.path -cne $staleArchiveRelative })
    if ($archivePins.Count -ne 1 -or $ordinaryPins.Count -ne 40) {
        throw 'Archived versus guardable predecessor partition rejected'
    }
    foreach ($pin in $ordinaryPins) {
        $guards += ,(Open-OuterGuard $pin)
    }
    if ($guards.Count -ne 45 -or @($guards.Pin.path | Sort-Object -Unique).Count -ne 45) {
        throw 'Outer read-guard census rejected'
    }
    foreach ($guard in $guards) {
        Assert-OuterGuardPin $guard
    }
    $predecessor = Get-ValidatedCombinedPredecessorEvidence $true
    [void](Assert-FinalArchivedStaleLockIdentity $archivePins[0] 'outer_before_live_samples' $true)
    Assert-FreshV31State
    Assert-V31RootAbsent

    $sample1 = Get-CleanLiveSample 1
    $separation = [Diagnostics.Stopwatch]::StartNew()
    Start-Sleep -Seconds 5
    $sample2 = Get-CleanLiveSample 2
    if ($separation.ElapsedMilliseconds -lt 5000) {
        throw 'Outer memory sample separation rejected'
    }

    $retained = Invoke-RetainedSnapshotChild
    $sample3 = Get-CleanLiveSample 3
    Assert-V31RootAbsent
    Assert-FreshV31State
    foreach ($guard in $guards) {
        Assert-OuterGuardPin $guard
    }
    $authorizationState = Get-AuthorizationState
    if ($authorizationState.runner_sha256 -cne $expectedRunnerHash -or
        $authorizationState.authorization_sha256 -cne $expectedAuthorizationHash) {
        throw 'Final authorization state hash rejected'
    }
    $finalPredecessor = Get-ValidatedCombinedPredecessorEvidence $true
    if (@(Get-CombinedPredecessorPinArray $finalPredecessor).Count -ne 41) {
        throw 'Final predecessor replay count rejected'
    }
    [void](Assert-FinalArchivedStaleLockIdentity $archivePins[0] 'outer_immediately_before_default' $true)
    Assert-ReviewReceipt
    Assert-FreshV31State
    Assert-V31RootAbsent

    [Console]::Out.WriteLine(([ordered]@{
        schema = 'planora.muni-v31.outer-terminal-live-gate.v1'
        status = 'PASS_IMMEDIATELY_BEFORE_EXACTLY_ONE_DEFAULT_INVOCATION'
        run_id = $v31RunId
        guarded_paths = $guards.Count
        guarded_predecessor_paths = $ordinaryPins.Count
        unguarded_exclusively_replayed_archive_paths = $archivePins.Count
        runner_sha256 = $authorizationState.runner_sha256
        authorization_sha256 = $authorizationState.authorization_sha256
        independent_review_sha256 = $expectedReviewHash
        sample1 = $sample1
        sample2 = $sample2
        sample_separation_milliseconds = $separation.ElapsedMilliseconds
        retained_snapshot = $retained.replay
        final_sample = $sample3
        v31_artifacts = 0
        shared_lock_present = $false
        default_invocation_count = 0
    } | ConvertTo-Json -Depth 8 -Compress))

    $defaultInvocationCount = 0
    if ($defaultInvocationCount -ne 0) {
        throw 'Default v31 invocation already attempted'
    }
    $defaultInvocationCount = 1
    & $runner
}
finally {
    foreach ($guard in $guards) {
        try { $guard.Stream.Dispose() } catch {}
    }
}
