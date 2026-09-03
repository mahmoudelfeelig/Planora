param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedSelfHash,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedGateReviewHash
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($ExpectedSelfHash -cnotmatch '^[0-9a-f]{64}$' -or
    $ExpectedGateReviewHash -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Expected gate hashes must be lowercase 64-character SHA-256 values'
}

$env:COLUMNS = '32768'
$env:LINES = '1000'
$env:WSLENV = 'COLUMNS:LINES'

$repoRoot = 'D:\Stuff\Projects\Sites\Planora'
$runner = Join-Path $repoRoot 'scripts\run_muni_v33_canonical_tests.ps1'
$primaryReviewPath = Join-Path $repoRoot 'output\diagnostic-receipts\muni-fspsx-v33-independent-review-20260828T180735Z.receipt.json'
$gateReviewPath = Join-Path $repoRoot 'output\diagnostic-receipts\muni-fspsx-v33-terminal-gate-independent-review-20260828T181500Z.receipt.json'
$powershell5 = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$runId = '2339df35f57e441a8f92bd1f890fa68f'
$expectedRunnerHash = '1899d5c5e89e886181e951dbaf38b7671c640c9aa01d2d21d6d68863048fb0fb'
$expectedAuthorizationHash = '683809b26400464fdb2fff4559fd1953854b09c18fdef1f2d198ea280e80e9c5'
$expectedPrimaryReviewHash = 'cbc777f2ed798fc41d1d54503d48746f859f2b2367fd09b53f433bf42786b45d'
$expectedV30InventoryHash = 'b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb'
$expectedV31InventoryHash = 'e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d'
$expectedV32InventoryHash = '0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3'
$v30Root = '/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01'
$v31Root = '/tmp/planora-muni-v31-canonical-tests-5f2d84640f40404a82dd180d7043d9c5'
$v32Root = '/tmp/planora-muni-v32-canonical-tests-4dc45edcd74446909290afadd5d3ecf0'
$strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
$evidenceGuards = @()
$heldGuards = @()

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

function Get-OuterRelativePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Guarded path is outside repository: $Path"
    }
    return $full.Substring($prefix.Length).Replace('\', '/')
}

function Get-OuterBytesSha256([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-OuterStringSha256([string]$Value) {
    return Get-OuterBytesSha256 ($strictUtf8.GetBytes($Value))
}

function Read-OuterGuardBytes([object]$Guard) {
    $stream = $Guard.Stream
    if ($stream.Length -lt 0 -or $stream.Length -gt [int]::MaxValue) {
        throw "Guarded file length rejected: $($Guard.Pin.path)"
    }
    $original = $stream.Position
    try {
        [void]$stream.Seek(0, [IO.SeekOrigin]::Begin)
        $bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) {
                throw "Guarded same-handle read ended early: $($Guard.Pin.path)"
            }
            $offset += $read
        }
        if ($stream.ReadByte() -ne -1) {
            throw "Guarded same-handle read observed trailing growth: $($Guard.Pin.path)"
        }
        return ,$bytes
    }
    finally {
        [void]$stream.Seek($original, [IO.SeekOrigin]::Begin)
    }
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
        (Get-OuterFileId $full) -cne [string]$pin.file_id) {
        throw "Guarded path identity rejected: $($pin.path)"
    }
    $heldHash = Get-OuterBytesSha256 (Read-OuterGuardBytes $Guard)
    if ($heldHash -cne [string]$pin.sha256) {
        throw "Guarded same-handle bytes rejected: $($pin.path)"
    }
}

function Open-OuterGuard([object]$Pin, [string]$Role) {
    $full = [IO.Path]::GetFullPath((Join-Path $repoRoot ($Pin.path.Replace('/', '\'))))
    $stream = New-Object IO.FileStream(
        $full,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    $guard = [pscustomobject]@{ Pin = $Pin; Stream = $stream; Role = $Role }
    try {
        Assert-OuterGuardPin $guard
        return $guard
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Open-OuterHashGuard([string]$Path, [string]$ExpectedHash, [string]$Role) {
    $full = [IO.Path]::GetFullPath($Path)
    $stream = New-Object IO.FileStream(
        $full,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        $item = Get-Item -LiteralPath $full
        if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "Guarded hash path type rejected: $Path"
        }
        $pin = [pscustomobject]@{
            path = Get-OuterRelativePath $full
            size = [long]$item.Length
            sha256 = $ExpectedHash
            file_id = Get-OuterFileId $full
            last_write_utc_ticks = [long]$item.LastWriteTimeUtc.Ticks
        }
        $guard = [pscustomobject]@{ Pin = $pin; Stream = $stream; Role = $Role }
        Assert-OuterGuardPin $guard
        return $guard
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Read-OuterGuardUtf8([object]$Guard) {
    return $strictUtf8.GetString((Read-OuterGuardBytes $Guard))
}

function Assert-PinEqual([object]$Observed, [object]$Expected, [string]$Label) {
    if ($Observed.path -cne $Expected.path -or
        [long]$Observed.size -ne [long]$Expected.size -or
        $Observed.sha256 -cne $Expected.sha256 -or
        $Observed.file_id -cne $Expected.file_id -or
        [long]$Observed.last_write_utc_ticks -ne [long]$Expected.last_write_utc_ticks) {
        throw "$Label exact pin rejected"
    }
}

function Assert-PrimaryReviewReceipt([object]$Guard, [object[]]$Quartet) {
    Assert-OuterGuardPin $Guard
    $review = (Read-OuterGuardUtf8 $Guard) | ConvertFrom-Json
    if ($review.schema -cne 'planora.muni-v33.independent-review.v1' -or
        $review.status -cne 'GO' -or
        $review.candidate -cne 'muni_v33' -or
        $review.run_id -cne $runId -or
        $review.verdict -cne 'GO_FOR_EXACTLY_ONE_DEFAULT_ONE_SHOT_SUBJECT_TO_ALL_LIVE_TERMINAL_GATES' -or
        -not [bool]$review.terminal_live_gates_required -or
        @($review.reviewer_tasks).Count -ne 2 -or
        @($review.blockers).Count -ne 0 -or
        [bool]$review.review_scope.quartet_edits_performed_by_reviewers -or
        [bool]$review.review_scope.nonconsuming_wsl_self_tests_performed_by_reviewers -or
        [bool]$review.review_scope.default_runner_execution_performed -or
        [bool]$review.review_scope.canonical_execution_performed -or
        [bool]$review.review_scope.heavy_execution_performed -or
        $review.predecessor_observations.validated_pin_count -ne 89 -or
        $review.predecessor_observations.unique_pin_path_count -ne 89 -or
        -not [bool]$review.predecessor_observations.all_exact_size_sha256_file_id_and_last_write_utc_ticks -or
        $review.predecessor_observations.carried_through_v31_pin_count -ne 61 -or
        $review.predecessor_observations.direct_v32_source_provenance_artifact_pin_count -ne 28 -or
        $review.predecessor_observations.guardable_ordinary_pin_count -ne 88 -or
        $review.predecessor_observations.archive_replay_only_pin_count -ne 1 -or
        -not [bool]$review.predecessor_observations.quintuple_pass_absence_validated_by_both_static_engines -or
        $review.predecessor_observations.v32_present_artifact_count -ne 20 -or
        $review.predecessor_observations.v32_expected_absent_artifact_count -ne 13 -or
        -not [bool]$review.predecessor_observations.v32_failure_claim_durably_published -or
        -not [bool]$review.predecessor_observations.v32_resource_launch_attempted -or
        [bool]$review.predecessor_observations.v32_canonical_launch_attempted -or
        [bool]$review.predecessor_observations.v32_canonical_suite_executed -or
        $review.fresh_state_observations.v33_run_artifact_count -ne 0 -or
        [bool]$review.fresh_state_observations.shared_lock_present -or
        $review.fresh_state_observations.retained_v28_archive_size -ne 370 -or
        $review.fresh_state_observations.retained_v28_archive_sha256 -cne 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' -or
        $review.source_contract_observations.canonical_launch_site_count -ne 1 -or
        [bool]$review.source_contract_observations.automatic_retry_authorized -or
        -not [bool]$review.source_contract_observations.complete_predecessor_evidence_bound_to_plan_pass_ordinary_rejection_emergency_rejection_and_seal -or
        -not [bool]$review.source_contract_observations.whole_document_predecessor_custody_exact_byte_replayed_from_held_guard -or
        -not [bool]$review.source_contract_observations.predecessor_custody_guard_held_through_pass_or_rejection_publication -or
        -not [bool]$review.source_contract_observations.retained_v30_v31_v32_initial_post_cleanup_rejection_and_final_replays_bound -or
        -not [bool]$review.source_contract_observations.terminal_archived_lock_guard_held_through_final_seal_flush -or
        -not [bool]$review.source_contract_observations.final_seal_create_only_durable_and_last_fallible_operation -or
        -not [bool]$review.source_contract_observations.stable_log_reader_restrictive_read_share_guard -or
        -not [bool]$review.source_contract_observations.stable_log_reader_same_held_handle_exact_prefix_replay -or
        -not [bool]$review.source_contract_observations.stable_log_reader_integrity_failures_terminal_and_outside_retry_catches -or
        $review.live_gate_remaining.protected_evidence_guard_count -ne 93 -or
        $review.live_gate_remaining.archive_replay_only_pin_count -ne 1 -or
        -not [bool]$review.live_gate_remaining.three_authenticated_resource_monitor_readiness_children -or
        $review.live_gate_remaining.first_two_readiness_children_minimum_separation_seconds -ne 5 -or
        -not [bool]$review.live_gate_remaining.terminal_gate_self_hash_guard -or
        -not [bool]$review.live_gate_remaining.terminal_gate_review_hash_guard -or
        -not [bool]$review.live_gate_remaining.exactly_one_argument_free_default_invocation) {
        throw 'Primary independent review receipt semantics rejected'
    }

    $reviewPins = @(
        $review.frozen_quartet.builder,
        $review.frozen_quartet.runner,
        $review.frozen_quartet.tests,
        $review.frozen_quartet.authorization
    )
    if ($reviewPins.Count -ne 4 -or @($reviewPins.path | Sort-Object -Unique).Count -ne 4) {
        throw 'Primary review frozen quartet cardinality rejected'
    }
    foreach ($expectedPin in $Quartet) {
        $matches = @($reviewPins | Where-Object { $_.path -ceq $expectedPin.path })
        if ($matches.Count -ne 1) {
            throw "Primary review quartet path rejected: $($expectedPin.path)"
        }
        Assert-PinEqual $matches[0] $expectedPin "Primary review quartet $($expectedPin.path)"
    }
}

function Assert-GateReviewReceipt([object]$Guard, [object]$SelfGuard) {
    Assert-OuterGuardPin $Guard
    $review = (Read-OuterGuardUtf8 $Guard) | ConvertFrom-Json
    if ($review.schema -cne 'planora.muni-v33.terminal-gate-independent-review.v1' -or
        $review.status -cne 'GO' -or
        $review.candidate -cne 'muni_v33' -or
        $review.run_id -cne $runId -or
        $review.verdict -cne 'GO_FOR_EXACTLY_ONE_TERMINAL_GATE_INVOCATION_WITH_SUPPLIED_SELF_AND_REVIEW_HASHES' -or
        @($review.reviewer_tasks).Count -lt 2 -or
        @($review.blockers).Count -ne 0 -or
        $review.primary_independent_review_sha256 -cne $expectedPrimaryReviewHash -or
        $review.frozen_successor.runner_sha256 -cne $expectedRunnerHash -or
        $review.frozen_successor.authorization_sha256 -cne $expectedAuthorizationHash -or
        [bool]$review.review_scope.files_edited_by_reviewers -or
        [bool]$review.review_scope.wsl_execution_performed -or
        [bool]$review.review_scope.default_runner_execution_performed -or
        [bool]$review.review_scope.canonical_execution_performed -or
        $review.independent_checks.dot_sourced_static_self_test_calls -ne 1 -or
        $review.independent_checks.argument_free_default_calls -ne 1 -or
        -not [bool]$review.independent_checks.default_call_is_final_try_operation -or
        $review.independent_checks.complete_predecessor_pins -ne 89 -or
        $review.independent_checks.ordinary_predecessor_read_guards -ne 88 -or
        $review.independent_checks.exclusively_replayed_v28_archive_pins -ne 1 -or
        $review.independent_checks.quartet_and_primary_review_read_guards -ne 5 -or
        $review.independent_checks.gate_self_and_review_read_guards -ne 2 -or
        $review.independent_checks.protected_evidence_read_guards -ne 93 -or
        $review.independent_checks.total_unique_held_read_guards -ne 95 -or
        $review.independent_checks.resource_monitor_readiness_children -ne 3 -or
        $review.independent_checks.minimum_first_start_separation_milliseconds -lt 5000 -or
        -not [bool]$review.independent_checks.expected_hash_parameters_mandatory_and_lowercase_sha256 -or
        -not [bool]$review.independent_checks.same_handle_restrictive_read_guards -or
        -not [bool]$review.independent_checks.final_exact_89_pin_array_replay -or
        -not [bool]$review.independent_checks.no_automatic_retry -or
        -not [bool]$review.independent_checks.combined_retained_v30_v31_v32_replay_bound -or
        $review.fresh_state.v33_run_artifact_count -ne 0 -or
        [bool]$review.fresh_state.shared_lock_present) {
        throw 'Terminal gate independent review receipt semantics rejected'
    }
    Assert-PinEqual $review.frozen_gate_pair.gate $SelfGuard.Pin 'Terminal gate review self pin'
    if ($review.frozen_gate_pair.tests.path -cne 'tests/test_run_muni_v33_terminal_gate_once.py' -or
        [long]$review.frozen_gate_pair.tests.size -lt 1 -or
        $review.frozen_gate_pair.tests.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $review.frozen_gate_pair.tests.file_id -cnotmatch '^[0-9a-f]{32}$' -or
        [long]$review.frozen_gate_pair.tests.last_write_utc_ticks -lt 1) {
        throw 'Terminal gate review test pin rejected'
    }
}

function Assert-GuardCensus {
    if ($evidenceGuards.Count -ne 93 -or
        @($evidenceGuards.Pin.path | Sort-Object -Unique).Count -ne 93 -or
        $heldGuards.Count -ne 95 -or
        @($heldGuards.Pin.path | Sort-Object -Unique).Count -ne 95) {
        throw 'Terminal gate held-stream census rejected'
    }
    foreach ($guard in $heldGuards) {
        Assert-OuterGuardPin $guard
    }
}

function Assert-FreshV33State([string]$Phase) {
    $leaf = (Split-Path -Leaf $prefix) + '.'
    $existing = @(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force | Where-Object {
        $_.Name.IndexOf($leaf, [StringComparison]::Ordinal) -eq 0
    })
    if ($existing.Count -ne 0) {
        throw "Fresh v33 artifact namespace rejected at ${Phase}: $($existing.Count) entries"
    }
    if (Test-Path -LiteralPath $sharedLockPath) {
        throw "Shared heavy lock present at $Phase"
    }
    return Assert-V28V29V30V31V32PassEvidenceAbsent $Phase
}

function Assert-V33RootAbsent([string]$Phase) {
    $lines = @(Invoke-WslText @('-d', 'Ubuntu', '--exec', 'test', '!', '-e', $root) "v33 root absence $Phase")
    if ($lines.Count -ne 0) {
        throw "V33 root absence command emitted output at $Phase"
    }
}

function Invoke-ResourceMonitorReadinessChild([int]$Number, [Diagnostics.Stopwatch]$Clock) {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powershell5
    $startInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -ResourceMonitorReadinessSelfTest"
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Resource readiness child $Number start failed"
        }
        $startedMonotonic = [long]$Clock.ElapsedMilliseconds
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(300000)) {
            try { $process.Kill() } catch {}
            throw "Resource readiness child $Number deadline exceeded"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $stderr.Length -ne 0) {
            throw "Resource readiness child $Number rejected: exit=$($process.ExitCode) stderr=$stderr"
        }
    }
    finally {
        $process.Dispose()
    }
    $trimmed = $stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.IndexOf("`n", [StringComparison]::Ordinal) -ge 0) {
        throw "Resource readiness child $Number output grammar rejected"
    }
    $result = $trimmed | ConvertFrom-Json
    if ($result.schema -cne 'planora.muni-v33.resource-monitor-readiness-self-test.v1' -or
        $result.status -cne 'PASS' -or
        $result.run_id -cne $runId -or
        $result.runner_sha256 -cne $expectedRunnerHash -or
        $result.authorization_sha256 -cne $expectedAuthorizationHash -or
        $result.rows -ne 3 -or
        $result.namespace_permission_denials -ne 0 -or
        $result.admitted_infrastructure_identities -lt 1 -or
        $result.admitted_infrastructure_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [bool]$result.canonical_seen -or
        [bool]$result.canonical_suite_executed -or
        [bool]$result.shared_lock_used -or
        [bool]$result.claim_created -or
        [bool]$result.v33_artifacts_created -or
        -not [bool]$result.wsl_executed) {
        throw "Resource readiness child $Number evidence rejected"
    }
    return [ordered]@{
        sample = $Number
        started_monotonic_milliseconds = $startedMonotonic
        completed_monotonic_milliseconds = [long]$Clock.ElapsedMilliseconds
        evidence = $result
    }
}

function Invoke-RetainedSnapshotsChild {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powershell5
    $startInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -RetainedPredecessorSnapshotsSelfTest"
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'Retained predecessor snapshots child start failed'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(600000)) {
            try { $process.Kill() } catch {}
            throw 'Retained predecessor snapshots child deadline exceeded'
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $stderr.Length -ne 0) {
            throw "Retained predecessor snapshots child rejected: exit=$($process.ExitCode) stderr=$stderr"
        }
    }
    finally {
        $process.Dispose()
    }
    $trimmed = $stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.IndexOf("`n", [StringComparison]::Ordinal) -ge 0) {
        throw 'Retained predecessor snapshots child output grammar rejected'
    }
    $result = $trimmed | ConvertFrom-Json
    if ($result.schema -cne 'planora.muni-v33.retained-predecessor-snapshots-self-test.v1' -or
        $result.status -cne 'PASS' -or
        $result.run_id -cne $runId -or
        $result.runner_sha256 -cne $expectedRunnerHash -or
        $result.authorization_sha256 -cne $expectedAuthorizationHash -or
        [bool]$result.canonical_suite_executed -or
        [bool]$result.shared_lock_used -or
        [bool]$result.claim_created -or
        [bool]$result.v33_artifacts_created) {
        throw 'Retained predecessor snapshots child envelope rejected'
    }
    $snapshots = @(
        [pscustomobject]@{ row = $result.v30; root = $v30Root; phase = 'isolated_nonconsuming_v30_preflight'; hash = $expectedV30InventoryHash },
        [pscustomobject]@{ row = $result.v31; root = $v31Root; phase = 'isolated_nonconsuming_v31_preflight'; hash = $expectedV31InventoryHash },
        [pscustomobject]@{ row = $result.v32; root = $v32Root; phase = 'isolated_nonconsuming_v32_preflight'; hash = $expectedV32InventoryHash }
    )
    foreach ($snapshot in $snapshots) {
        if ($snapshot.row.schema -cne 'planora.muni-v33.retained-snapshot-replay.v1' -or
            $snapshot.row.status -cne 'EXACT_RETAINED_SNAPSHOT_REPLAY' -or
            $snapshot.row.phase -cne $snapshot.phase -or
            $snapshot.row.root -cne $snapshot.root -or
            $snapshot.row.files -ne 3146 -or
            $snapshot.row.directories -ne 368 -or
            $snapshot.row.bytes -ne 190900047 -or
            $snapshot.row.inventory_sha256 -cne $snapshot.hash -or
            -not [bool]$snapshot.row.all_nlink_one) {
            throw "Retained predecessor snapshot evidence rejected: $($snapshot.phase)"
        }
    }
    return $result
}

$quartet = @(
    [pscustomobject]@{ path = 'scripts/build_muni_v33_successor.py'; size = 127349; sha256 = '288aec154b156a8a6a55523e31466188c1bc60c1f289751799d07c59ebd380d3'; file_id = '0000000000000000000500000017c563'; last_write_utc_ticks = 639235358848477442 },
    [pscustomobject]@{ path = 'scripts/run_muni_v33_canonical_tests.ps1'; size = 350383; sha256 = '1899d5c5e89e886181e951dbaf38b7671c640c9aa01d2d21d6d68863048fb0fb'; file_id = '0000000000000000000500000017be8f'; last_write_utc_ticks = 639235359747884240 },
    [pscustomobject]@{ path = 'tests/test_run_muni_v33_successor.py'; size = 29488; sha256 = 'aed35db03be4e10f13d5705a0ef5b7624373a31d682fd3ac59400467f911243c'; file_id = '0000000000000000000200000017c56a'; last_write_utc_ticks = 639235358907779204 },
    [pscustomobject]@{ path = 'output/diagnostic-receipts/muni-fspsx-v33-canonical-tests-authorization-20260828T141639Z.receipt.json'; size = 45158; sha256 = '683809b26400464fdb2fff4559fd1953854b09c18fdef1f2d198ea280e80e9c5'; file_id = '0000000000000000000200000017c56d'; last_write_utc_ticks = 639235359756600098 }
)
$primaryReviewPin = [pscustomobject]@{
    path = 'output/diagnostic-receipts/muni-fspsx-v33-independent-review-20260828T180735Z.receipt.json'
    size = 10665
    sha256 = 'cbc777f2ed798fc41d1d54503d48746f859f2b2367fd09b53f433bf42786b45d'
    file_id = '0000000000000000004b00000017c594'
    last_write_utc_ticks = 639235373506139804
}

try {
    $selfGuard = Open-OuterHashGuard $PSCommandPath $ExpectedSelfHash 'terminal_gate_self'
    $heldGuards += ,$selfGuard
    $gateReviewGuard = Open-OuterHashGuard $gateReviewPath $ExpectedGateReviewHash 'terminal_gate_review'
    $heldGuards += ,$gateReviewGuard
    Assert-GateReviewReceipt $gateReviewGuard $selfGuard

    foreach ($pin in @($quartet) + @($primaryReviewPin)) {
        $guard = Open-OuterGuard $pin 'protected_successor_evidence'
        $evidenceGuards += ,$guard
        $heldGuards += ,$guard
    }
    $primaryReviewGuard = @($evidenceGuards | Where-Object { $_.Pin.path -ceq $primaryReviewPin.path })
    if ($primaryReviewGuard.Count -ne 1) {
        throw 'Primary review guard cardinality rejected'
    }
    Assert-PrimaryReviewReceipt $primaryReviewGuard[0] $quartet

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
        throw 'Initial authorization state hash rejected'
    }
    $predecessor = Get-ValidatedCompletePredecessorEvidence $true
    $pins = @(Get-CompletePredecessorPinArray $predecessor)
    if ($pins.Count -ne 89 -or @($pins.path | Sort-Object -Unique).Count -ne 89) {
        throw 'Complete predecessor pin cardinality rejected'
    }
    $archivePins = @($pins | Where-Object { $_.path -ceq $staleArchiveRelative })
    $ordinaryPins = @($pins | Where-Object { $_.path -cne $staleArchiveRelative })
    if ($archivePins.Count -ne 1 -or $ordinaryPins.Count -ne 88) {
        throw 'Archived versus guardable predecessor partition rejected'
    }
    $initialPredecessorArrayJson = $pins | ConvertTo-Json -Depth 10 -Compress
    $initialPredecessorArrayHash = Get-OuterStringSha256 $initialPredecessorArrayJson
    foreach ($pin in $ordinaryPins) {
        $guard = Open-OuterGuard $pin 'protected_predecessor_evidence'
        $evidenceGuards += ,$guard
        $heldGuards += ,$guard
    }
    Assert-GuardCensus
    [void](Get-ValidatedCompletePredecessorEvidence $true)
    [void](Assert-FinalArchivedStaleLockIdentity $archivePins[0] 'outer_before_authenticated_live_gates' $true)
    [void](Assert-FreshV33State 'outer_before_authenticated_live_gates')
    Assert-V33RootAbsent 'outer_before_authenticated_live_gates'

    $readinessClock = [Diagnostics.Stopwatch]::StartNew()
    $sample1 = Invoke-ResourceMonitorReadinessChild 1 $readinessClock
    while (($readinessClock.ElapsedMilliseconds - $sample1.started_monotonic_milliseconds) -lt 5000) {
        $remaining = 5000 - ($readinessClock.ElapsedMilliseconds - $sample1.started_monotonic_milliseconds)
        Start-Sleep -Milliseconds ([Math]::Min(100, [Math]::Max(1, $remaining)))
    }
    $sample2 = Invoke-ResourceMonitorReadinessChild 2 $readinessClock
    $firstStartSeparation = [long]$sample2.started_monotonic_milliseconds - [long]$sample1.started_monotonic_milliseconds
    if ($firstStartSeparation -lt 5000) {
        throw 'First two resource readiness child starts were not separated by 5000 monotonic milliseconds'
    }

    $retained = Invoke-RetainedSnapshotsChild
    $sample3 = Invoke-ResourceMonitorReadinessChild 3 $readinessClock

    $finalAuthorizationState = Get-AuthorizationState
    if ($finalAuthorizationState.runner_sha256 -cne $expectedRunnerHash -or
        $finalAuthorizationState.authorization_sha256 -cne $expectedAuthorizationHash) {
        throw 'Final authorization state hash rejected'
    }
    $finalPredecessor = Get-ValidatedCompletePredecessorEvidence $true
    $finalPins = @(Get-CompletePredecessorPinArray $finalPredecessor)
    $finalPredecessorArrayJson = $finalPins | ConvertTo-Json -Depth 10 -Compress
    $finalPredecessorArrayHash = Get-OuterStringSha256 $finalPredecessorArrayJson
    if ($finalPins.Count -ne 89 -or
        @($finalPins.path | Sort-Object -Unique).Count -ne 89 -or
        $finalPredecessorArrayJson -cne $initialPredecessorArrayJson -or
        $finalPredecessorArrayHash -cne $initialPredecessorArrayHash) {
        throw 'Final complete predecessor exact array/hash replay rejected'
    }
    $finalArchivePins = @($finalPins | Where-Object { $_.path -ceq $staleArchiveRelative })
    $finalOrdinaryPins = @($finalPins | Where-Object { $_.path -cne $staleArchiveRelative })
    if ($finalArchivePins.Count -ne 1 -or $finalOrdinaryPins.Count -ne 88) {
        throw 'Final predecessor partition rejected'
    }
    Assert-GuardCensus
    Assert-PrimaryReviewReceipt $primaryReviewGuard[0] $quartet
    Assert-GateReviewReceipt $gateReviewGuard $selfGuard
    [void](Assert-FinalArchivedStaleLockIdentity $finalArchivePins[0] 'outer_immediately_before_default' $true)
    $finalPassAbsence = Assert-FreshV33State 'outer_immediately_before_default'
    Assert-V33RootAbsent 'outer_immediately_before_default'
    Assert-GuardCensus
    if (-not $finalPassAbsence.v28_receipt_absent -or
        -not $finalPassAbsence.v28_seal_absent -or
        -not $finalPassAbsence.v29_receipt_absent -or
        -not $finalPassAbsence.v29_seal_absent -or
        -not $finalPassAbsence.v30_receipt_absent -or
        -not $finalPassAbsence.v30_seal_absent -or
        -not $finalPassAbsence.v31_receipt_absent -or
        -not $finalPassAbsence.v31_seal_absent -or
        -not $finalPassAbsence.v32_receipt_absent -or
        -not $finalPassAbsence.v32_seal_absent) {
        throw 'Final predecessor PASS absence replay rejected'
    }

    [Console]::Out.WriteLine(([ordered]@{
        schema = 'planora.muni-v33.outer-terminal-live-gate.v1'
        status = 'PASS_IMMEDIATELY_BEFORE_EXACTLY_ONE_DEFAULT_INVOCATION'
        run_id = $runId
        held_streams = $heldGuards.Count
        protected_evidence_guards = $evidenceGuards.Count
        guarded_successor_and_primary_review_paths = 5
        guarded_predecessor_paths = $finalOrdinaryPins.Count
        unguarded_exclusively_replayed_archive_paths = $finalArchivePins.Count
        terminal_gate_sha256 = $ExpectedSelfHash
        terminal_gate_review_sha256 = $ExpectedGateReviewHash
        runner_sha256 = $finalAuthorizationState.runner_sha256
        authorization_sha256 = $finalAuthorizationState.authorization_sha256
        primary_independent_review_sha256 = $expectedPrimaryReviewHash
        predecessor_pin_array_sha256 = $finalPredecessorArrayHash
        resource_monitor_readiness_samples = @($sample1, $sample2, $sample3)
        first_two_child_start_separation_milliseconds = $firstStartSeparation
        retained_v30_snapshot = $retained.v30
        retained_v31_snapshot = $retained.v31
        retained_v32_snapshot = $retained.v32
        v33_artifacts = 0
        shared_lock_present = $false
        default_invocation_count = 0
    } | ConvertTo-Json -Depth 10 -Compress))

    $defaultInvocationCount = 0
    if ($defaultInvocationCount -ne 0) {
        throw 'Default v33 invocation already attempted'
    }
    $defaultInvocationCount = 1
    & $runner
}
finally {
    foreach ($guard in $heldGuards) {
        try { $guard.Stream.Dispose() } catch {}
    }
}
