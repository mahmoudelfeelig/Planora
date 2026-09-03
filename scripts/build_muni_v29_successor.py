from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
V28_RUNNER = REPO / "scripts/run_muni_v28_canonical_tests.ps1"
V29_RUNNER = REPO / "scripts/run_muni_v29_canonical_tests.ps1"
V29_AUTH = (
    REPO
    / "output/diagnostic-receipts/muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json"
)
V29_TESTS = REPO / "tests/test_run_muni_v29_successor.py"

RUN_ID = "ca79220da7db46b6996fe1f05785dde7"
V28_RUN_ID = "e7cf1df162074402994a9d0ad763c824"
V28_RUNNER_SHA256 = "fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"replacement anchor count {count}, expected 1: {old[:120]!r}"
        )
    return text.replace(old, new, 1)


def assert_pin(path: Path, size: int, sha256: str) -> None:
    if path.stat().st_size != size or digest(path) != sha256:
        raise RuntimeError(f"pinned predecessor drift: {path}")


def render_runner(
    builder_size: int, builder_sha256: str, tests_size: int, tests_sha256: str
) -> str:
    assert_pin(V28_RUNNER, 161_962, V28_RUNNER_SHA256)
    source = V28_RUNNER.read_text(encoding="utf-8")
    lines = source.splitlines()
    lines[0] = "param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization)"
    lines[9] = f"$runId = '{RUN_ID}'"
    lines[10] = '$root = "/tmp/planora-muni-v29-canonical-tests-$runId"'
    lines[12] = "$runnerRelative = 'scripts/run_muni_v29_canonical_tests.ps1'"
    lines[13] = (
        "$runnerPath = Join-Path $repo 'scripts\\run_muni_v29_canonical_tests.ps1'"
    )
    lines[14] = (
        "$authorizationRelative = 'output/diagnostic-receipts/muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json'"
    )
    lines[15] = (
        "$authorizationPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json'"
    )
    lines[21] = (
        '$prefix = Join-Path $repo "output\\diagnostic-receipts\\muni-fspsx-v29-canonical-readonly-tests-$runId"'
    )
    lines[22] = (
        '$prefixWsl = "$repoWsl/output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-$runId"'
    )
    source = "\n".join(lines) + "\n"
    source = source.replace("planora.muni-v28.", "planora.muni-v29.")
    source = source.replace("candidate='muni_v28'", "candidate='muni_v29'")
    source = source.replace(
        f"/tmp/planora-muni-v28-canonical-tests-{V28_RUN_ID}",
        f"/tmp/planora-muni-v29-canonical-tests-{RUN_ID}",
    )
    source = replace_once(
        source,
        "function Get-Sha256([string]$Path){return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()}",
        "function Get-Sha256([string]$Path){$s=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete));$sha=[Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($s))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose();$s.Dispose()}}",
    )
    source = replace_once(
        source,
        "function Write-NewUtf8([string]$Path,[string]$Value){Write-NewBytes $Path $utf8.GetBytes($Value)}",
        "function Write-NewUtf8([string]$Path,[string]$Value){Write-NewBytes $Path $utf8.GetBytes($Value)}\n"
        'function Write-FinalPassSeal([string]$Path,[string]$Value,[IO.FileStream]$ArchiveGuard){$expectedArchiveBytes=$utf8.GetBytes(\'{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}\');if($null-eq$ArchiveGuard-or[IO.Path]::GetFullPath($ArchiveGuard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){throw \'Final archived-lock guard rejected\'};[void](Assert-HeldStreamBytes $ArchiveGuard $expectedArchiveBytes \'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98\' \'Final archived stale lock guard\');$bytes=$utf8.GetBytes($Value);$stream=$null;$durablyFlushed=$false;try{$stream=New-Object IO.FileStream($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true);$durablyFlushed=$true}finally{if($null-ne$stream){if($durablyFlushed){try{$stream.Dispose()}catch{}}else{$stream.Dispose()}};if($null-ne$ArchiveGuard){if($durablyFlushed){try{$ArchiveGuard.Dispose()}catch{}}else{$ArchiveGuard.Dispose()}}}}',
    )

    top_injection = f"""
$successorBuilderPath = Join-Path $repo 'scripts\\build_muni_v29_successor.py'
$admissionTestsPath = Join-Path $repo 'tests\\test_run_muni_v29_successor.py'
$v28RunnerPath = Join-Path $repo 'scripts\\run_muni_v28_canonical_tests.ps1'
$v28AuthorizationPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-tests-authorization-20260827T045149Z.receipt.json'
$v28ClaimPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.claim.json'
$v28RejectionPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.rejection.json'
$v28StaticPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.static-adversarial.json'
$v28ReceiptPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.receipt.json'
$v28PassSealPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.pass-publication-shutdown-seal.json'
$staleArchiveRelative = 'output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-{V28_RUN_ID}.lock.json'
$staleArchivePath = Join-Path $repo 'output\\diagnostic-receipts\\retained-stale-planora-shared-heavy-wsl-v28-{V28_RUN_ID}.lock.json'
$staleReconciliationFile = "$prefix.stale-lock-reconciliation.json"
""".strip()
    source = replace_once(
        source,
        "$sharedLockPath = Join-Path $repo 'output\\diagnostic-receipts\\planora-shared-heavy-wsl.lock'\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
        "$sharedLockPath = Join-Path $repo 'output\\diagnostic-receipts\\planora-shared-heavy-wsl.lock'\n"
        + top_injection
        + "\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
    )

    auth_function = f"""
function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){{
    $closure=$snapshotContractJson|ConvertFrom-Json
    $o=[ordered]@{{
        schema='planora.itc2019.canonical-test-authorization.v9';created_at_utc='2026-08-28T08:45:12Z';instance='muni-fspsx-fal17';candidate='muni_v29';test_id=$runId
        decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_PINNED_V28_STALE_LOCK_RECONCILIATION';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false
        runner=[ordered]@{{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash}}
        successor_admission=[ordered]@{{builder=[ordered]@{{path='scripts/build_muni_v29_successor.py';size={builder_size};sha256='{builder_sha256}'}};tests=[ordered]@{{path='tests/test_run_muni_v29_successor.py';size={tests_size};sha256='{tests_sha256}'}}}}
        pinned_v28_files=[ordered]@{{
            builder=[ordered]@{{path='scripts/build_muni_v28_chain.ps1';size=44779;sha256='bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'}}
            tests=[ordered]@{{path=$testsRelative;size=178441;sha256='f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'}}
            certificate=[ordered]@{{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-certificate.json';size=31261;sha256='7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'}}
            freeze_manifest=[ordered]@{{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-freeze-manifest.json';size=33749;sha256='f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'}}
            runner=[ordered]@{{path='scripts/run_muni_v28_canonical_tests.ps1';size=161962;sha256='{V28_RUNNER_SHA256}'}}
            authorization=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-tests-authorization-20260827T045149Z.receipt.json';size=8024;sha256='1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'}}
            claim=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.claim.json';size=541;sha256='f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4'}}
            rejection=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.rejection.json';size=1081;sha256='2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41'}}
            static_evidence=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.static-adversarial.json';size=2019;sha256='93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf'}}
            retained_lock=[ordered]@{{path='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';size=370;sha256='dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'}}
        }}
        predecessor_failure=[ordered]@{{run_id='{V28_RUN_ID}';status='REJECTED_AUTHORIZATION_CONSUMED';claim_sha256='f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4';rejection_sha256='2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41';static_evidence_sha256='93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf';pass_receipt_absent=$true;shutdown_seal_absent=$true;root_cause='held_lock_path_reopened_for_hash_caused_self_sharing_violation_before_canonical_tests'}}
        stale_lock_reconciliation=[ordered]@{{authorized_exactly_once=$true;source='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';source_size=370;source_sha256='dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98';owner_pid=1140;owner_pid_policy='must_be_absent_at_two_guarded_observations_any_reuse_rejected';no_live_handle_proof='FileShareNone_exclusive_probe_then_identity_replay';atomic_retention='same_directory_FileMove_while_FileShareDelete_handle_held';archive=$staleArchiveRelative;delete_authorized=$false;mismatch_or_race='REJECT';output=$($staleReconciliationFile.Substring($repo.Length+1).Replace('\\','/'))}}
        snapshot_closure=$closure
        heavy_gate=[ordered]@{{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;continuous_monitor='target_100ms_with_authenticated_monotonic_sequence_and_750ms_maximum_gap';census='fail_closed_allow_live_proven_ancestry_or_previously_frozen_descendant_identity_in_exact_launch_namespace_plus_minimal_infrastructure_reject_hostile_siblings';target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval';pinned_subprocess_sites=16;descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'}}
        launch_contract=[ordered]@{{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';watcher_lifetime='ARMED_before_staging_lossless_events_through_final_census_same_handle_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown';staged_identity='device_inode_nlink_mode_size_sha256_frozen_and_replayed';host_root=$root;explicit_snapshot_ro_bind='/snapshot';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;environment_cleared=$true;capabilities_dropped=$true;gnu_timeout=[ordered]@{{term_seconds=600;kill_after_seconds=15}};host_wsl_deadline_seconds=$hostDeadlineSeconds;canonical_execute_sites=1}}
        canonical_contract=[ordered]@{{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';strict_stderr_grammar=$true;exact_skip_identities=[ordered]@{{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}}}}
        evidence_contract=[ordered]@{{atomic_claim='claim_attempt_marked_before_CreateNew_inside_outer_rejection_try_default_fail_closed_claim_v2_before_preflight';any_failure_consumes_authorization=$true;predecessor_failure_and_exact_stale_lock_bound=$true;complete_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true;predecessor_live_pins_in_protected_replay_sets=$true;predecessor_pass_absence_replayed_through_final_pass_seal_publication=$true;stale_lock_reconciliation_output_and_archive_identity_bound=$true;authoritative_archive_pin_never_resampled=$true;terminal_archived_lock_identity_replay_bound_by_final_pass_seal=$true;terminal_archived_lock_read_guard_held_through_final_pass_seal_flush=$true;final_pass_seal_create_only_durable_last_operation=$true;new_lock_verified_only_through_held_handle=$true;new_lock_release='same_handle_stable_bytes_then_DeleteOnClose';all_file_nlinks_and_device_inode_retained=$true;exact_staged_file_and_directory_set=$true;plan_and_receipt_bind_runner_authorization_snapshot_predecessor_and_reconciliation=$true;pass_receipt_requires_post_publication_authenticated_watcher_shutdown_seal=$true;watcher_active_through_pass_publication=$true;claim_constructor_write_flush_and_immediate_failures_require_durable_rejection=$true;emergency_rejection_fallback_create_only=$true}}
    }}
    return($o|ConvertTo-Json -Depth 30 -Compress)
}}

if($EmitExpectedAuthorization){{
    $runnerItem=Get-Item -LiteralPath $runnerPath
    [Console]::Out.WriteLine((Get-ExpectedAuthorizationJson $runnerItem.Length (Get-Sha256 $runnerPath)))
    return
}}
""".strip()
    source = replace_once(
        source,
        "function Get-AuthorizationState{",
        auth_function + "\n\nfunction Get-AuthorizationState{",
    )

    lock_functions = f"""
function Get-BytesSha256([byte[]]$Bytes){{
    $sha=[Security.Cryptography.SHA256]::Create();try{{return([BitConverter]::ToString($sha.ComputeHash($Bytes))-replace'-','').ToLowerInvariant()}}finally{{$sha.Dispose()}}
}}
function Read-HeldStreamExact([IO.FileStream]$Stream,[int]$ExpectedLength){{
    if($null-eq$Stream-or-not$Stream.CanRead-or-not$Stream.CanSeek){{throw 'Held stream is not readable and seekable'}}
    $original=$Stream.Position;try{{[void]$Stream.Seek(0,[IO.SeekOrigin]::Begin);$bytes=New-Object byte[] $ExpectedLength;$offset=0;while($offset-lt$ExpectedLength){{$count=$Stream.Read($bytes,$offset,$ExpectedLength-$offset);if($count-le0){{throw 'Held stream ended before expected length'}};$offset+=$count}};if($Stream.ReadByte()-ne-1){{throw 'Held stream exceeds expected length'}};return ,$bytes}}finally{{[void]$Stream.Seek($original,[IO.SeekOrigin]::Begin)}}
}}
function Assert-HeldStreamBytes([IO.FileStream]$Stream,[byte[]]$ExpectedBytes,[string]$ExpectedHash,[string]$Context){{
    [byte[]]$actual=Read-HeldStreamExact $Stream $ExpectedBytes.Length;$actualHash=Get-BytesSha256 $actual
    if($actualHash-cne$ExpectedHash-or$actual.Length-ne$ExpectedBytes.Length){{throw "$Context held-byte replay rejected"}}
    return $actualHash
}}
function Assert-HeldLockPath([IO.FileStream]$Stream,[byte[]]$ExpectedBytes,[string]$ExpectedHash){{
    $full=[IO.Path]::GetFullPath($sharedLockPath);if([IO.Path]::GetFullPath($Stream.Name)-cne$full){{throw 'Held lock stream path rejected'}}
    $item=Get-Item -LiteralPath $sharedLockPath;if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$item.PSIsContainer-or$item.Length-ne$ExpectedBytes.Length-or$Stream.Length-ne$ExpectedBytes.Length){{throw 'Held lock path identity rejected'}}
    return(Assert-HeldStreamBytes $Stream $ExpectedBytes $ExpectedHash 'Shared heavy lock')
}}
function Assert-OwnerPidAbsent([int]$OwnerPid,[string]$Phase){{
    if($OwnerPid-le0-or$OwnerPid-eq$PID){{throw "Stale owner PID safeguard rejected: $Phase"}}
    $existing=$null;try{{$existing=[Diagnostics.Process]::GetProcessById($OwnerPid)}}catch [ArgumentException]{{}}
    if($null-ne$existing){{try{{$name=$existing.ProcessName}}catch{{$name='unreadable'}};try{{$started=$existing.StartTime.ToUniversalTime().ToString('o')}}catch{{$started='unreadable'}};try{{$existing.Dispose()}}catch{{}};throw "Stale owner PID exists and is rejected regardless of identity: pid=$OwnerPid name=$name start=$started phase=$Phase"}}
    return [ordered]@{{phase=$Phase;pid=$OwnerPid;absent=$true;observed_at_utc=[DateTime]::UtcNow.ToString('o');reuse_policy='any_existing_pid_rejected_regardless_process_name_or_start_time'}}
}}
function Assert-V28StaleLockRecord([object]$Record){{
    if($Record.schema-cne'planora.shared-heavy-wsl-lock.v1'-or$Record.run_id-cne'{V28_RUN_ID}'-or$Record.authorization_sha256-cne'1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'-or$Record.runner_sha256-cne'{V28_RUNNER_SHA256}'-or$Record.mechanism-cne'FileMode.CreateNew_held_open'-or[int]$Record.owner_pid-ne1140){{throw 'Pinned v28 stale-lock schema/binding rejected'}}
    return $true
}}
function New-ExpectedV28PredecessorEvidence{{
    return [ordered]@{{
        schema='planora.muni-v29.complete-v28-predecessor-evidence.v1';run_id='{V28_RUN_ID}';status='EXPECTED_UNVALIDATED'
        authorized_files=[ordered]@{{
            builder=[ordered]@{{path='scripts/build_muni_v28_chain.ps1';size=44779;sha256='bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'}}
            tests=[ordered]@{{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-tests.py';size=178441;sha256='f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'}}
            certificate=[ordered]@{{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-certificate.json';size=31261;sha256='7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'}}
            freeze_manifest=[ordered]@{{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-freeze-manifest.json';size=33749;sha256='f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'}}
            runner=[ordered]@{{path='scripts/run_muni_v28_canonical_tests.ps1';size=161962;sha256='{V28_RUNNER_SHA256}'}}
            authorization=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-tests-authorization-20260827T045149Z.receipt.json';size=8024;sha256='1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'}}
            claim=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.claim.json';size=541;sha256='f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4'}}
            rejection=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.rejection.json';size=1081;sha256='2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41'}}
            static_evidence=[ordered]@{{path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.static-adversarial.json';size=2019;sha256='93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf'}}
            retained_lock=[ordered]@{{path='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';size=370;sha256='dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'}}
        }}
        failure_semantics=[ordered]@{{status='REJECTED_AUTHORIZATION_CONSUMED';root_cause='held_lock_path_reopened_for_hash_caused_self_sharing_violation_before_canonical_tests';claim_status='CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS';claim_failure_consumes_authorization=$true;claim_sha256='f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4';rejection_sha256='2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41';static_evidence_sha256='93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf'}}
        pass_evidence=[ordered]@{{receipt_path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.receipt.json';shutdown_seal_path='output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.pass-publication-shutdown-seal.json';receipt_absent_required=$true;shutdown_seal_absent_required=$true}}
        runtime=[ordered]@{{validation_phase='not_started';live_file_pins=$null;retained_lock_source_pin=$null;retained_lock_archive_pin=$null;stale_lock_reconciliation_sha256='';validation_errors=@()}}
    }}
}}
function Assert-V28PassEvidenceAbsent([string]$Phase){{
    $receiptAbsent=-not(Test-Path -LiteralPath $v28ReceiptPath);$sealAbsent=-not(Test-Path -LiteralPath $v28PassSealPath)
    if(-not$receiptAbsent-or-not$sealAbsent){{throw "v28 PASS evidence unexpectedly exists: $Phase"}}
    return [ordered]@{{phase=$Phase;receipt_absent=$receiptAbsent;shutdown_seal_absent=$sealAbsent;observed_at_utc=[DateTime]::UtcNow.ToString('o')}}
}}
function Get-ValidatedV28PredecessorEvidence{{
    $e=New-ExpectedV28PredecessorEvidence
    foreach($entry in $e.authorized_files.GetEnumerator()){{$pin=$entry.Value;Assert-LocalPin (Join-Path $repo ($pin.path.Replace('/','\\'))) ([long]$pin.size) ([string]$pin.sha256)}}
    $claim=[IO.File]::ReadAllText($v28ClaimPath,$utf8)|ConvertFrom-Json;$rejection=[IO.File]::ReadAllText($v28RejectionPath,$utf8)|ConvertFrom-Json;$static=[IO.File]::ReadAllText($v28StaticPath,$utf8)|ConvertFrom-Json
    if($claim.run_id-cne'{V28_RUN_ID}'-or$claim.status-cne$e.failure_semantics.claim_status-or-not[bool]$claim.failure_consumes_authorization-or$rejection.run_id-cne'{V28_RUN_ID}'-or$rejection.status-cne$e.failure_semantics.status-or$rejection.claim_sha256-cne$e.failure_semantics.claim_sha256-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$static.run_id-cne'{V28_RUN_ID}'-or$static.runner_sha256-cne'{V28_RUNNER_SHA256}'-or$static.authorization_sha256-cne'1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'){{throw 'Pinned v28 consumed-failure semantics rejected'}}
    $live=[ordered]@{{builder=(Get-LocalEvidencePin $builderPath);tests=(Get-LocalEvidencePin $testsPath);certificate=(Get-LocalEvidencePin $certificatePath);freeze_manifest=(Get-LocalEvidencePin $manifestPath);runner=(Get-LocalEvidencePin $v28RunnerPath);authorization=(Get-LocalEvidencePin $v28AuthorizationPath);claim=(Get-LocalEvidencePin $v28ClaimPath);rejection=(Get-LocalEvidencePin $v28RejectionPath);static_evidence=(Get-LocalEvidencePin $v28StaticPath)}}
    $e.status='VALIDATED_BEFORE_STALE_LOCK_RECONCILIATION';$e.runtime.validation_phase='before_stale_lock_reconciliation';$e.runtime.live_file_pins=$live;$e.runtime.retained_lock_source_pin=Get-LocalEvidencePin $sharedLockPath;$e.runtime['pass_absence_before_reconciliation']=Assert-V28PassEvidenceAbsent 'before_stale_lock_reconciliation'
    return $e
}}
function New-StaleArchivePinFromSource([object]$SourcePin){{
    if($null-eq$SourcePin-or$SourcePin.path-cne'output/diagnostic-receipts/planora-shared-heavy-wsl.lock'-or[long]$SourcePin.size-ne370-or$SourcePin.sha256-cne'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'){{throw 'Pinned v28 stale-lock source pin rejected'}}
    return [ordered]@{{path=$staleArchiveRelative;size=[long]$SourcePin.size;sha256=[string]$SourcePin.sha256;file_id=[string]$SourcePin.file_id;last_write_utc_ticks=[long]$SourcePin.last_write_utc_ticks}}
}}
function Assert-RetainedArchivePin([string]$Path,[object]$ExpectedPin,[byte[]]$ExpectedBytes,[string]$ExpectedHash,[string]$Phase){{
    $full=[IO.Path]::GetFullPath($Path);$relative=$full.Replace($repo+'\\','').Replace('\\','/');if($ExpectedPin.path-cne$relative-or[long]$ExpectedPin.size-ne$ExpectedBytes.Length-or$ExpectedPin.sha256-cne$ExpectedHash){{throw "Retained archive expected pin rejected: $Phase"}}
    [void](Assert-LocalEvidencePin $ExpectedPin);$probe=New-Object IO.FileStream($full,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{{if([IO.Path]::GetFullPath($probe.Name)-cne$full){{throw "Retained archive stream path rejected: $Phase"}};$item=Get-Item -LiteralPath $full;if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$item.PSIsContainer-or$item.Length-ne$ExpectedBytes.Length-or$probe.Length-ne$ExpectedBytes.Length){{throw "Retained archive path identity rejected: $Phase"}};[void](Assert-HeldStreamBytes $probe $ExpectedBytes $ExpectedHash "Retained archive $Phase")}}finally{{$probe.Dispose()}}
    [void](Assert-LocalEvidencePin $ExpectedPin);return [ordered]@{{phase=$Phase;status='IDENTITY_AND_EXCLUSIVE_SAME_HANDLE_BYTES_REPLAYED';archive_pin=$ExpectedPin;observed_at_utc=[DateTime]::UtcNow.ToString('o')}}
}}
function Assert-FinalArchivedStaleLockIdentity([object]$ExpectedPin,[string]$Phase,[bool]$RequireSharedLockAbsent){{
    $bytes=$utf8.GetBytes('{{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"{V28_RUN_ID}","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"{V28_RUNNER_SHA256}","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}}')
    $result=Assert-RetainedArchivePin $staleArchivePath $ExpectedPin $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' $Phase
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){{throw "Shared heavy lock unexpectedly present during archived-lock terminal replay: $Phase"}}
    $result['shared_lock_absence_required']=$RequireSharedLockAbsent;$result['shared_lock_absent']=(-not(Test-Path -LiteralPath $sharedLockPath));$result['v28_pass_absence']=Assert-V28PassEvidenceAbsent $Phase;return $result
}}
function Open-TerminalArchivedStaleLockGuard([object]$ExpectedPin,[string]$Phase){{
    $preGuardReplay=Assert-FinalArchivedStaleLockIdentity $ExpectedPin $Phase $true;$bytes=$utf8.GetBytes('{{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"{V28_RUN_ID}","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"{V28_RUNNER_SHA256}","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}}');$guard=$null
    try{{
        $guard=New-Object IO.FileStream($staleArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);if([IO.Path]::GetFullPath($guard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){{throw 'Terminal archived-lock guard path rejected'}};[void](Assert-HeldStreamBytes $guard $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Terminal archived stale lock guard');[void](Assert-LocalEvidencePin $ExpectedPin);if(Test-Path -LiteralPath $sharedLockPath){{throw 'Shared heavy lock unexpectedly present while terminal archive guard held'}};$passAbsence=Assert-V28PassEvidenceAbsent ($Phase+'_guard_held')
        $evidence=[ordered]@{{schema='planora.muni-v29.terminal-archived-lock-guard.v1';phase=$Phase;status='IDENTITY_REPLAYED_AND_READ_GUARD_HELD_THROUGH_FINAL_PASS_FLUSH';archive_pin=$ExpectedPin;pre_guard_replay=$preGuardReplay;guard_access='Read';guard_share='Read_only_blocks_write_and_delete';same_handle_bytes_replayed=$true;shared_lock_absent=$true;v28_pass_absence=$passAbsence;acquired_at_utc=[DateTime]::UtcNow.ToString('o')}};return [pscustomobject]@{{Stream=$guard;Evidence=$evidence}}
    }}catch{{if($null-ne$guard){{$guard.Dispose()}};throw}}
}}
function Get-V28PredecessorPinArray([object]$Evidence,[object]$ArchivePin){{
    if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_AFTER_STALE_LOCK_RECONCILIATION'-or$null-eq$ArchivePin){{throw 'Complete predecessor evidence is not replay-ready'}}
    $pins=@();foreach($name in @('builder','tests','certificate','freeze_manifest','runner','authorization','claim','rejection','static_evidence')){{$pin=$Evidence.runtime.live_file_pins[$name];if($null-eq$pin){{throw "Complete predecessor pin missing: $name"}};$pins+=,$pin}};$pins+=,$ArchivePin;return $pins
}}
function Get-NonThrowingV28RejectionReplay([object]$Evidence,[object]$ArchivePin){{
    $errors=@();$observed=[ordered]@{{}};$expected=if($null-ne$Evidence){{$Evidence}}else{{New-ExpectedV28PredecessorEvidence}}
    foreach($name in @('builder','tests','certificate','freeze_manifest','runner','authorization','claim','rejection','static_evidence')){{$entry=$expected.authorized_files[$name];try{{$pin=Get-LocalEvidencePin (Join-Path $repo ($entry.path.Replace('/','\\')));if([long]$pin.size-ne[long]$entry.size-or$pin.sha256-cne$entry.sha256){{throw 'size/hash mismatch'}};$observed[$name]=$pin}}catch{{$errors+="$name`: $($_.Exception.Message)"}}}}
    $retained=$null;try{{if(Test-Path -LiteralPath $staleArchivePath){{if($null-eq$ArchivePin){{$candidate=Get-LocalEvidencePin $staleArchivePath;if([long]$candidate.size-ne370-or$candidate.sha256-cne'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'){{throw 'untrusted archive size/hash mismatch'}};$retained=[ordered]@{{status='ARCHIVE_PRESENT_WITHOUT_AUTHORITATIVE_SOURCE_IDENTITY';archive_pin=$candidate}}}}else{{$retained=Assert-FinalArchivedStaleLockIdentity $ArchivePin 'rejection_replay' $false}}}}elseif(Test-Path -LiteralPath $sharedLockPath){{$candidate=Get-LocalEvidencePin $sharedLockPath;$entry=$expected.authorized_files.retained_lock;if([long]$candidate.size-ne[long]$entry.size-or$candidate.sha256-cne$entry.sha256){{throw 'retained source lock mismatch'}};$retained=[ordered]@{{status='SOURCE_LOCK_RETAINED';source_pin=$candidate}}}}else{{throw 'retained source and archive are both absent'}}}}catch{{$errors+="retained_lock`: $($_.Exception.Message)"}}
    $pass=[ordered]@{{receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));shutdown_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}};if(-not$pass.receipt_absent-or-not$pass.shutdown_seal_absent){{$errors+='v28 PASS evidence unexpectedly exists'}}
    return [ordered]@{{phase='rejection_publication';status=$(if($errors.Count-eq0){{'REPLAYED'}}else{{'REPLAY_ERRORS_RECORDED'}});live_file_pins=$observed;retained_lock=$retained;pass_evidence=$pass;errors=@($errors)}}
}}
function Invoke-LockSelfReadRegressionModel{{
    $oldPath=Join-Path ([IO.Path]::GetTempPath()) ("planora-v28-self-read-"+[Guid]::NewGuid().ToString('N')+'.lock');$newPath=Join-Path ([IO.Path]::GetTempPath()) ("planora-v29-same-handle-"+[Guid]::NewGuid().ToString('N')+'.lock');$moveSource=Join-Path $repo ("tmp\\planora-v29-stale-source-"+[Guid]::NewGuid().ToString('N')+'.lock');$moveTarget=$moveSource+'.retained';$replacement=$moveSource+'.replacement';$bytes=$utf8.GetBytes('{{"lock":"regression"}}');$expected=Get-BytesSha256 $bytes;$oldFailure=$false;$replacementRejected=$false
    $old=New-Object IO.FileStream($oldPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);try{{$old.Write($bytes,0,$bytes.Length);$old.Flush($true);try{{[void](Get-Sha256 $oldPath)}}catch{{$oldFailure=$true}};if((Assert-HeldStreamBytes $old $bytes $expected 'v28 regression')-cne$expected){{throw 'v28 held-handle witness rejected'}}}}finally{{$old.Dispose();if(Test-Path -LiteralPath $oldPath){{Remove-Item -LiteralPath $oldPath -Force}}}}
    if(-not$oldFailure){{throw 'v28 path-reopen self-sharing failure was not reproduced'}}
    $successor=New-Object IO.FileStream($newPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose);try{{$successor.Write($bytes,0,$bytes.Length);$successor.Flush($true);if((Assert-HeldStreamBytes $successor $bytes $expected 'v29 successor')-cne$expected){{throw 'v29 same-handle witness rejected'}}}}finally{{$successor.Dispose()}}
    if(Test-Path -LiteralPath $newPath){{throw 'v29 DeleteOnClose witness rejected'}}
    try{{
        [IO.File]::WriteAllBytes($moveSource,$bytes);$sourcePin=Get-LocalEvidencePin $moveSource;$targetRelative=([IO.Path]::GetFullPath($moveTarget)).Replace($repo+'\\','').Replace('\\','/');$targetPin=[ordered]@{{path=$targetRelative;size=$sourcePin.size;sha256=$sourcePin.sha256;file_id=$sourcePin.file_id;last_write_utc_ticks=$sourcePin.last_write_utc_ticks}}
        $move=New-Object IO.FileStream($moveSource,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Delete);try{{[void](Assert-HeldStreamBytes $move $bytes $expected 'stale archive move witness');[IO.File]::Move($moveSource,$moveTarget);[void](Assert-HeldStreamBytes $move $bytes $expected 'retained stale archive witness');if((Test-Path -LiteralPath $moveSource)-or(-not(Test-Path -LiteralPath $moveTarget))){{throw 'Held stale archive move state rejected'}}}}finally{{$move.Dispose()}}
        [void](Assert-RetainedArchivePin $moveTarget $targetPin $bytes $expected 'static_original_archive');[IO.File]::WriteAllBytes($replacement,$bytes);Remove-Item -LiteralPath $moveTarget -Force;[IO.File]::Move($replacement,$moveTarget)
        try{{[void](Assert-LocalEvidencePin $targetPin)}}catch{{$replacementRejected=$true}};if(-not$replacementRejected){{throw 'Identical-byte retained archive replacement was not rejected'}}
    }}finally{{foreach($p in @($moveSource,$moveTarget,$replacement)){{if(Test-Path -LiteralPath $p){{Remove-Item -LiteralPath $p -Force}}}}}}
    return [ordered]@{{v28_path_reopen_self_sharing_failure='REPRODUCED';v29_same_handle_seek_read_hash='PASS';v29_delete_on_close='PASS';stale_lock_atomic_move_while_held='PASS';identical_bytes_archive_replacement_rejected='PASS'}}
}}
function Invoke-StaleLockAdversarialModel{{
    $good=[pscustomobject]@{{schema='planora.shared-heavy-wsl-lock.v1';run_id='{V28_RUN_ID}';authorization_sha256='1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d';runner_sha256='{V28_RUNNER_SHA256}';mechanism='FileMode.CreateNew_held_open';owner_pid=1140}}
    [void](Assert-V28StaleLockRecord $good);$mutations=0;foreach($name in @('schema','run_id','authorization_sha256','runner_sha256','mechanism','owner_pid')){{$copy=$good.PSObject.Copy();if($name-ceq'owner_pid'){{$copy.$name=1141}}else{{$copy.$name='mutated'}};$bad=$false;try{{[void](Assert-V28StaleLockRecord $copy)}}catch{{$bad=$true}};if(-not$bad){{throw "Stale-lock mutation accepted: $name"}};$mutations++}}
    return [ordered]@{{exact_record='PASS';mutations_rejected=$mutations;path_mismatch_policy='REJECT';identity_race_policy='REJECT';live_pid_policy='REJECT';archive_delete_authorized=$false}}
}}
function Reconcile-PinnedV28StaleLock([object]$PredecessorEvidence){{
    if($null-eq$PredecessorEvidence-or$PredecessorEvidence.status-cne'VALIDATED_BEFORE_STALE_LOCK_RECONCILIATION'){{throw 'Complete predecessor evidence is not reconciliation-ready'}}
    $resolvedRepo=(Resolve-Path -LiteralPath $repo).ProviderPath.TrimEnd('\\');$resolvedLock=(Resolve-Path -LiteralPath $sharedLockPath).ProviderPath
    if(-not$resolvedLock.StartsWith($resolvedRepo+'\\',[StringComparison]::OrdinalIgnoreCase)-or[IO.Path]::GetFullPath($resolvedLock)-cne[IO.Path]::GetFullPath($sharedLockPath)){{throw 'Pinned stale-lock resolved path escaped repository or drifted'}}
    if(Test-Path -LiteralPath $staleArchivePath){{throw 'Pinned stale-lock archive already exists'}}
    Assert-LocalPin $v28RunnerPath 161962 '{V28_RUNNER_SHA256}';Assert-LocalPin $v28AuthorizationPath 8024 '1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d';Assert-LocalPin $v28ClaimPath 541 'f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4';Assert-LocalPin $v28RejectionPath 1081 '2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41';Assert-LocalPin $v28StaticPath 2019 '93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf';Assert-LocalPin $sharedLockPath 370 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'
    if((Test-Path -LiteralPath $v28ReceiptPath)-or(Test-Path -LiteralPath $v28PassSealPath)){{throw 'v28 PASS evidence unexpectedly exists'}}
    $claim=[IO.File]::ReadAllText($v28ClaimPath,$utf8)|ConvertFrom-Json;$rejection=[IO.File]::ReadAllText($v28RejectionPath,$utf8)|ConvertFrom-Json;$static=[IO.File]::ReadAllText($v28StaticPath,$utf8)|ConvertFrom-Json
    if($claim.run_id-cne'{V28_RUN_ID}'-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.failure_consumes_authorization-or$rejection.run_id-cne'{V28_RUN_ID}'-or$rejection.status-cne'REJECTED_AUTHORIZATION_CONSUMED'-or$rejection.claim_sha256-cne'f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4'-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$static.run_id-cne'{V28_RUN_ID}'-or$static.runner_sha256-cne'{V28_RUNNER_SHA256}'-or$static.authorization_sha256-cne'1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'){{throw 'Pinned v28 consumed-failure semantics rejected'}}
    $expectedBytes=[IO.File]::ReadAllBytes($sharedLockPath);if($expectedBytes.Length-ne370-or(Get-BytesSha256 $expectedBytes)-cne'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'){{throw 'Pinned stale-lock initial byte replay rejected'}};$record=$utf8.GetString($expectedBytes)|ConvertFrom-Json;[void](Assert-V28StaleLockRecord $record)
    $pidBefore=Assert-OwnerPidAbsent 1140 'before_exclusive_probe';$beforePin=$PredecessorEvidence.runtime.retained_lock_source_pin;[void](Assert-LocalEvidencePin $beforePin)
    $probe=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);try{{[void](Assert-HeldLockPath $probe $expectedBytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98')}}finally{{$probe.Dispose()}}
    $afterProbePin=Get-LocalEvidencePin $sharedLockPath;if((ConvertTo-JsonTokenStream ($beforePin|ConvertTo-Json -Depth 5 -Compress))-cne(ConvertTo-JsonTokenStream ($afterProbePin|ConvertTo-Json -Depth 5 -Compress))){{throw 'Pinned stale-lock identity drift across exclusive probe'}}
    $moveHandle=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Delete);try{{[void](Assert-HeldLockPath $moveHandle $expectedBytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98');$pidAtMove=Assert-OwnerPidAbsent 1140 'immediately_before_atomic_archive';[IO.File]::Move($sharedLockPath,$staleArchivePath);[void](Assert-HeldStreamBytes $moveHandle $expectedBytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Archived stale lock');if((Test-Path -LiteralPath $sharedLockPath)-or(-not(Test-Path -LiteralPath $staleArchivePath))){{throw 'Pinned stale-lock atomic archive state rejected'}}}}finally{{$moveHandle.Dispose()}}
    $archivePin=New-StaleArchivePinFromSource $beforePin;$archiveReplay=Assert-FinalArchivedStaleLockIdentity $archivePin 'immediately_after_atomic_archive' $true
    $row=[ordered]@{{schema='planora.muni-v29.stale-lock-reconciliation.v2';status='PINNED_V28_STALE_LOCK_ATOMICALLY_RETAINED';run_id=$runId;predecessor_run_id='{V28_RUN_ID}';source='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';source_sha256='dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98';source_pin=$beforePin;archive=$staleArchiveRelative;archive_pin=$archivePin;archive_identity_replay=$archiveReplay;owner_pid=1140;owner_pid_observations=@($pidBefore,$pidAtMove);no_live_handle_proof='FileShareNone_exclusive_probe_passed';atomic_archive='same_directory_FileMove_while_FileShareDelete_handle_held';predecessor_evidence_before_reconciliation=$PredecessorEvidence;delete_performed=$false;reconciled_at_utc=[DateTime]::UtcNow.ToString('o')}}
    Write-NewUtf8 $staleReconciliationFile ($row|ConvertTo-Json -Depth 12);return $row
}}
""".strip()
    source = replace_once(
        source,
        "function Release-HeavyLock([IO.FileStream]$Stream",
        lock_functions + "\n\nfunction Release-HeavyLock([IO.FileStream]$Stream",
    )

    old_release = """function Release-HeavyLock([IO.FileStream]$Stream,[string]$ExpectedHash,[string]$Decision,[string]$AcceptanceHash,[string]$CleanupHash){
    if($null-eq$Stream){return};$Stream.Dispose();$i=Get-Item -LiteralPath $sharedLockPath
    if(($i.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or(Get-Sha256 $sharedLockPath)-cne$ExpectedHash){throw 'Shared heavy lock drift before release'}
    Remove-Item -LiteralPath $sharedLockPath -Force
    $row=[ordered]@{schema='planora.shared-heavy-wsl-lock-release.v2';run_id=$runId;decision=$Decision;lock_sha256=$ExpectedHash;acceptance_commitment_sha256=$AcceptanceHash;cleanup_sha256=$CleanupHash;released_at_utc=[DateTime]::UtcNow.ToString('o');lock_path_absent=(-not(Test-Path -LiteralPath $sharedLockPath))}
    Write-NewUtf8 $lockReleaseFile ($row|ConvertTo-Json -Depth 6)
}"""
    new_release = """function Release-HeavyLock([IO.FileStream]$Stream,[string]$ExpectedHash,[string]$Decision,[string]$AcceptanceHash,[string]$CleanupHash){
    if($null-eq$Stream){return};$expectedBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress));[void](Assert-HeldLockPath $Stream $expectedBytes $ExpectedHash);$Stream.Flush($true);$Stream.Dispose()
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock DeleteOnClose release rejected'}
    $row=[ordered]@{schema='planora.shared-heavy-wsl-lock-release.v3';run_id=$runId;decision=$Decision;lock_sha256=$ExpectedHash;same_handle_verified=$true;delete_on_close=$true;acceptance_commitment_sha256=$AcceptanceHash;cleanup_sha256=$CleanupHash;released_at_utc=[DateTime]::UtcNow.ToString('o');lock_path_absent=$true}
    Write-NewUtf8 $lockReleaseFile ($row|ConvertTo-Json -Depth 6)
}"""
    source = replace_once(source, old_release, new_release)

    source = replace_once(
        source,
        "$checks=Invoke-LocalStaticAdversarialChecks",
        "$checks=Invoke-LocalStaticAdversarialChecks\n    $lockRegression=Invoke-LockSelfReadRegressionModel\n    $staleModel=Invoke-StaleLockAdversarialModel",
    )
    source = replace_once(
        source,
        "function Assert-FinalizationReady([object]$State){\n    foreach($name in @('canonical_exited','watcher_exited','watcher_clean','resource_monitor_exited','resource_monitor_clean','snapshot_absent','shared_lock_absent','cleanup_evidence_present','lock_release_evidence_present','acceptance_commitment_present','postflight_census_clean','final_evidence_replayed','pass_receipt_present','pass_shutdown_seal_present')){if(-not[bool]$State.$name){throw \"Finalization prerequisite rejected: $name\"}}\n    return $true\n}",
        "function Assert-FinalizationReady([object]$State){\n    foreach($name in @('canonical_exited','watcher_exited','watcher_clean','resource_monitor_exited','resource_monitor_clean','snapshot_absent','shared_lock_absent','cleanup_evidence_present','lock_release_evidence_present','acceptance_commitment_present','postflight_census_clean','final_evidence_replayed','pass_receipt_present','final_pass_seal_absent_before_publication')){if(-not[bool]$State.$name){throw \"Finalization prerequisite rejected: $name\"}}\n    return $true\n}",
    )
    source = replace_once(
        source,
        "pass_receipt_present=$true;pass_shutdown_seal_present=$true",
        "pass_receipt_present=$true;final_pass_seal_absent_before_publication=$true",
    )
    source = replace_once(
        source,
        "wsl_executed=$false}",
        "lock_regression=$lockRegression;stale_lock_model=$staleModel;wsl_executed=$false}",
    )
    source = replace_once(
        source,
        "$lockStream=$null;$lockHash=''",
        "$lockStream=$null;$lockHash='';$lockBody=$null;$staleReconciliationHash='';$staleArchivePin=$null;$predecessorEvidence=New-ExpectedV28PredecessorEvidence;$predecessorEvidenceHash='';$predecessorPins=@();$archiveReplayAtPass=$null;$archiveReplayBeforeFinalization=$null;$archiveReplayTerminal=$null;$terminalArchiveGuard=$null",
    )
    source = replace_once(
        source,
        "$rejectionFile,$rejectionEmergencyFile)",
        "$rejectionFile,$rejectionEmergencyFile,$staleReconciliationFile,$staleArchivePath)",
    )

    old_lock_block = """    $auth=Get-AuthorizationState;$runnerHash=$auth.runner_sha256;$authorizationHash=$auth.authorization_sha256
    Assert-LocalPin $builderPath 44779 'bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'
    Assert-LocalPin $testsPath 178441 'f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'
    Assert-LocalPin $certificatePath 31261 '7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'
    Assert-LocalPin $manifestPath 33749 'f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'
    $legacy=@(Get-LegacyRows)
    $static=Invoke-LocalStaticAdversarialChecks
    Write-NewUtf8 $staticEvidenceFile (([ordered]@{run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;legacy_rows=$legacy.Count;checks=$static}|ConvertTo-Json -Depth 10))

    $lockBody=[ordered]@{schema='planora.shared-heavy-wsl-lock.v1';run_id=$runId;authorization_sha256=$authorizationHash;runner_sha256=$runnerHash;created_at_utc=[DateTime]::UtcNow.ToString('o');mechanism='FileMode.CreateNew_held_open';owner_pid=$PID}
    $lockBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress))
    $lockStream=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
    $lockStream.Write($lockBytes,0,$lockBytes.Length);$lockStream.Flush($true);$lockHash=Get-Sha256 $sharedLockPath
    Write-NewUtf8 $lockEvidenceFile (([ordered]@{lock=$lockBody;lock_sha256=$lockHash;held_open=$true}|ConvertTo-Json -Depth 8))"""
    new_lock_block = f"""    $auth=Get-AuthorizationState;$runnerHash=$auth.runner_sha256;$authorizationHash=$auth.authorization_sha256
    Assert-LocalPin $builderPath 44779 'bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'
    Assert-LocalPin $successorBuilderPath {builder_size} '{builder_sha256}'
    Assert-LocalPin $admissionTestsPath {tests_size} '{tests_sha256}'
    Assert-LocalPin $testsPath 178441 'f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'
    Assert-LocalPin $certificatePath 31261 '7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'
    Assert-LocalPin $manifestPath 33749 'f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'
    $predecessorEvidence=Get-ValidatedV28PredecessorEvidence
    $legacy=@(Get-LegacyRows);$static=Invoke-LocalStaticAdversarialChecks;$lockRegression=Invoke-LockSelfReadRegressionModel;$staleModel=Invoke-StaleLockAdversarialModel
    Write-NewUtf8 $staticEvidenceFile (([ordered]@{{run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;legacy_rows=$legacy.Count;checks=$static;lock_regression=$lockRegression;stale_lock_model=$staleModel}}|ConvertTo-Json -Depth 10))

    $staleReconciliation=Reconcile-PinnedV28StaleLock $predecessorEvidence;$staleReconciliationHash=Get-Sha256 $staleReconciliationFile;$staleArchivePin=$staleReconciliation.archive_pin;$expectedArchivePin=New-StaleArchivePinFromSource $predecessorEvidence.runtime.retained_lock_source_pin
    if((ConvertTo-JsonTokenStream ($staleArchivePin|ConvertTo-Json -Depth 6 -Compress))-cne(ConvertTo-JsonTokenStream ($expectedArchivePin|ConvertTo-Json -Depth 6 -Compress))){{throw 'Reconciliation returned a non-authoritative stale archive pin'}};[void](Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'after_reconciliation_return' $true)
    $predecessorEvidence.status='VALIDATED_AFTER_STALE_LOCK_RECONCILIATION';$predecessorEvidence.runtime.validation_phase='after_stale_lock_reconciliation';$predecessorEvidence.runtime.retained_lock_archive_pin=$staleArchivePin;$predecessorEvidence.runtime.stale_lock_reconciliation_sha256=$staleReconciliationHash;$predecessorEvidence.runtime['source_absent_after_atomic_archive']=(-not(Test-Path -LiteralPath $sharedLockPath));$predecessorEvidence.runtime['pass_absence_after_reconciliation']=Assert-V28PassEvidenceAbsent 'after_stale_lock_reconciliation';$predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 18 -Compress));$predecessorPins=@(Get-V28PredecessorPinArray $predecessorEvidence $staleArchivePin)
    $lockBody=[ordered]@{{schema='planora.shared-heavy-wsl-lock.v2';run_id=$runId;authorization_sha256=$authorizationHash;runner_sha256=$runnerHash;stale_lock_reconciliation_sha256=$staleReconciliationHash;created_at_utc=[DateTime]::UtcNow.ToString('o');mechanism='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';owner_pid=$PID}}
    $lockBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress));$lockHash=Get-BytesSha256 $lockBytes
    $lockStream=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose)
    $lockStream.Write($lockBytes,0,$lockBytes.Length);$lockStream.Flush($true);[void](Assert-HeldLockPath $lockStream $lockBytes $lockHash)
    Write-NewUtf8 $lockEvidenceFile (([ordered]@{{lock=$lockBody;lock_sha256=$lockHash;held_open=$true;same_handle_verified=$true;delete_on_close=$true;stale_lock_reconciliation_sha256=$staleReconciliationHash;stale_archive_pin=$staleArchivePin;predecessor_evidence_sha256=$predecessorEvidenceHash}}|ConvertTo-Json -Depth 10))"""
    source = replace_once(source, old_lock_block, new_lock_block)

    source = replace_once(
        source,
        "$preAcceptancePins=@(@($runnerPath,$authorizationPath,$claimFile,$lockEvidenceFile,",
        "$preAcceptancePins=@($predecessorPins)+@(@($runnerPath,$authorizationPath,$claimFile,$staleReconciliationFile,$lockEvidenceFile,",
    )
    source = replace_once(
        source,
        "Write-NewUtf8 $planFile",
        "$plan['predecessor_v28_evidence']=$predecessorEvidence;$plan['predecessor_v28_evidence_sha256']=$predecessorEvidenceHash;$plan['stale_lock_reconciliation']=[ordered]@{sha256=$staleReconciliationHash;archive_pin=$staleArchivePin};$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'\n    Write-NewUtf8 $planFile",
    )
    source = replace_once(
        source,
        "$receiptJson=$receipt|ConvertTo-Json",
        "$archiveReplayAtPass=Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'immediately_before_pass_receipt_publication' $true;$receipt['predecessor_v28_evidence']=$predecessorEvidence;$receipt['predecessor_v28_evidence_sha256']=$predecessorEvidenceHash;$receipt['predecessor_pass_absence_at_publication']=$archiveReplayAtPass.v28_pass_absence;$receipt['stale_lock_reconciliation_sha256']=$staleReconciliationHash;$receipt['stale_lock_archive_pin']=$staleArchivePin;$receipt['stale_lock_archive_identity_replay']=$archiveReplayAtPass;$receipt['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'\n    $receiptJson=$receipt|ConvertTo-Json",
    )
    old_seal_tail = """    $seal=[ordered]@{schema='planora.muni-v29.pass-publication-shutdown-seal.v1';status='PASS_FOR_FRESH_INDEPENDENT_EVIDENCE_REVIEW_ONLY';run_id=$runId;pass_receipt_sha256=$receiptHash;watcher_shutdown_control_sha256=$watchStopHash;watcher_log_sha256=(Get-Sha256 $watchLogFile);watcher_wrapper_stdout_sha256=(Get-Sha256 $watchWrapperOutFile);watcher_wrapper_stderr_sha256=(Get-Sha256 $watchWrapperErrFile);cleanup_evidence_sha256=$cleanupHash;post_publication_protected_replay_sha256=$postPublicationReplayHash;parent_watch_active_through_pass_publication=$watchSummary.done.parent_watch_active;parent_watch_loss_events=$watchSummary.done.parent_watch_loss_events;root_absent_at_bound_shutdown=$watchSummary.done.root_absent;protected_through_pass_publication=$watchSummary.done.protected_through_pass_publication;final_evidence_replay=$finalReplay;evidence_pins=$finalPins;sealed_at_utc=[DateTime]::UtcNow.ToString('o')}
    $sealJson=$seal|ConvertTo-Json -Depth 22;Write-NewUtf8 $passSealFile $sealJson;if((ConvertTo-JsonTokenStream ([IO.File]::ReadAllText($passSealFile,$utf8)))-cne(ConvertTo-JsonTokenStream $sealJson)){throw 'PASS shutdown seal immediate semantic replay rejected'};$sealPin=Get-LocalEvidencePin $passSealFile;[void](Assert-LocalEvidencePin $sealPin)
    $finalState=[ordered]@{canonical_exited=$true;watcher_exited=$true;watcher_clean=$true;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=[bool]$watchSummary.done.root_absent;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));cleanup_evidence_present=(Test-Path -LiteralPath $cleanupFile);lock_release_evidence_present=(Test-Path -LiteralPath $lockReleaseFile);acceptance_commitment_present=(Test-Path -LiteralPath $acceptanceFile);postflight_census_clean=(@($finalCensus.rejected_workloads).Count-eq0);final_evidence_replayed=$true;pass_receipt_present=(Test-Path -LiteralPath $receiptFile);pass_shutdown_seal_present=(Test-Path -LiteralPath $passSealFile)}
    [void](Assert-FinalizationReady ([pscustomobject]$finalState));if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Post-seal self-pin replay rejected'};[void](Assert-LocalEvidencePin (Get-LocalEvidencePin $receiptFile));[void](Assert-LocalEvidencePin $sealPin);$decision='PASS'"""
    new_seal_tail = """    $archiveReplayBeforeFinalization=Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'after_final_evidence_replay_before_finalization' $true
    $finalState=[ordered]@{canonical_exited=$true;watcher_exited=$true;watcher_clean=$true;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=[bool]$watchSummary.done.root_absent;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));cleanup_evidence_present=(Test-Path -LiteralPath $cleanupFile);lock_release_evidence_present=(Test-Path -LiteralPath $lockReleaseFile);acceptance_commitment_present=(Test-Path -LiteralPath $acceptanceFile);postflight_census_clean=(@($finalCensus.rejected_workloads).Count-eq0);final_evidence_replayed=$true;pass_receipt_present=(Test-Path -LiteralPath $receiptFile);final_pass_seal_absent_before_publication=(-not(Test-Path -LiteralPath $passSealFile))}
    [void](Assert-FinalizationReady ([pscustomobject]$finalState));if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Pre-final-seal self-pin replay rejected'};$receiptPin=Get-LocalEvidencePin $receiptFile;[void](Assert-LocalEvidencePin $receiptPin)
    $watchLogHash=Get-Sha256 $watchLogFile;$watchWrapperOutHash=Get-Sha256 $watchWrapperOutFile;$watchWrapperErrHash=Get-Sha256 $watchWrapperErrFile;$sealedAtUtc=[DateTime]::UtcNow.ToString('o')
    $terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard $staleArchivePin 'terminal_before_create_only_final_pass_seal';$archiveReplayTerminal=$terminalArchiveGuard.Evidence
    $seal=[ordered]@{schema='planora.muni-v29.pass-publication-shutdown-seal.v2';status='PASS_FOR_FRESH_INDEPENDENT_EVIDENCE_REVIEW_ONLY';run_id=$runId;publication_mechanism='FileMode.CreateNew_write_FlushTrue_as_last_fallible_operation_with_archived_lock_read_guard';pass_receipt_sha256=$receiptHash;pass_receipt_pin=$receiptPin;watcher_shutdown_control_sha256=$watchStopHash;watcher_log_sha256=$watchLogHash;watcher_wrapper_stdout_sha256=$watchWrapperOutHash;watcher_wrapper_stderr_sha256=$watchWrapperErrHash;cleanup_evidence_sha256=$cleanupHash;post_publication_protected_replay_sha256=$postPublicationReplayHash;parent_watch_active_through_pass_publication=$watchSummary.done.parent_watch_active;parent_watch_loss_events=$watchSummary.done.parent_watch_loss_events;root_absent_at_bound_shutdown=$watchSummary.done.root_absent;protected_through_pass_publication=$watchSummary.done.protected_through_pass_publication;finalization_prerequisites=$finalState;final_evidence_replay=$finalReplay;evidence_pins=$finalPins;predecessor_v28_evidence=$predecessorEvidence;predecessor_v28_evidence_sha256=$predecessorEvidenceHash;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=$archiveReplayBeforeFinalization;terminal_stale_lock_archive_identity_replay=$archiveReplayTerminal;sealed_at_utc=$sealedAtUtc}
    $sealJson=$seal|ConvertTo-Json -Depth 22
    Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream"""
    source = replace_once(source, old_seal_tail, new_seal_tail)
    source = replace_once(
        source,
        "catch{\n    $failure=$_.Exception.Message",
        "catch{\n    $failure=$_.Exception.Message\n    if($null-ne$terminalArchiveGuard){try{$terminalArchiveGuard.Stream.Dispose()}catch{};$terminalArchiveGuard=$null}",
    )
    source = replace_once(
        source,
        "        $rejectEvidence=[ordered]@{schema='planora.muni-v29.overall-rejection.v4';",
        "        if($null-eq$staleArchivePin-and(Test-Path -LiteralPath $staleArchivePath)-and$null-ne$predecessorEvidence.runtime.retained_lock_source_pin){try{$staleArchivePin=New-StaleArchivePinFromSource $predecessorEvidence.runtime.retained_lock_source_pin}catch{$failure+=\"; archived_pin_recovery=$($_.Exception.Message)\"}};$predecessorRejectionReplay=$null;try{$predecessorRejectionReplay=Get-NonThrowingV28RejectionReplay $predecessorEvidence $staleArchivePin}catch{$predecessorRejectionReplay=[ordered]@{phase='rejection_publication';status='REPLAY_HELPER_FAILED';errors=@($_.Exception.Message)}};$predecessorEvidence['rejection_replay']=$predecessorRejectionReplay;$predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 18 -Compress))\n        $rejectEvidence=[ordered]@{schema='planora.muni-v29.overall-rejection.v5';",
    )
    source = replace_once(
        source,
        ";acceptance_commitment_sha256=$(if(Test-Path -LiteralPath $acceptanceFile){Get-Sha256 $acceptanceFile}else{''});snapshot_root=",
        ";acceptance_commitment_sha256=$(if(Test-Path -LiteralPath $acceptanceFile){Get-Sha256 $acceptanceFile}else{''});predecessor_v28_evidence=$predecessorEvidence;predecessor_v28_evidence_sha256=$predecessorEvidenceHash;stale_lock_reconciliation_sha256=$staleReconciliationHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;snapshot_root=",
    )
    source = replace_once(
        source,
        ";original_failure=$failure;recorded_at_utc=",
        ";original_failure=$failure;predecessor_v28_evidence=$predecessorEvidence;predecessor_v28_evidence_sha256=$predecessorEvidenceHash;stale_lock_reconciliation_sha256=$staleReconciliationHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;recorded_at_utc=",
    )
    source = replace_once(
        source,
        "Write-NewUtf8 $rejectionFile ($rejectEvidence|ConvertTo-Json -Depth 10 -Compress)",
        "Write-NewUtf8 $rejectionFile ($rejectEvidence|ConvertTo-Json -Depth 22 -Compress)",
    )
    source = replace_once(
        source,
        "Write-NewUtf8 $rejectionEmergencyFile ($emergency|ConvertTo-Json -Depth 8 -Compress)",
        "Write-NewUtf8 $rejectionEmergencyFile ($emergency|ConvertTo-Json -Depth 22 -Compress)",
    )
    source = replace_once(
        source,
        "'/mnt/c/mnt/d/Stuff/Projects/Sites/Planora')){if($source-cnotmatch",
        "'/mnt/c/mnt/d/Stuff/Projects/Sites/Planora','planora.muni-v29.complete-v28-predecessor-evidence.v1','Get-NonThrowingV28RejectionReplay','terminal_before_create_only_final_pass_seal','pass-publication-shutdown-seal.v2','Open-TerminalArchivedStaleLockGuard','Read_only_blocks_write_and_delete','Write-FinalPassSeal')){if($source-cnotmatch",
    )
    source = replace_once(
        source,
        "$sealWriteIndex=$source.LastIndexOf('Write-NewUtf8 $passSealFile',[StringComparison]::Ordinal);if(",
        "$sealWriteIndex=$source.LastIndexOf('Write-FinalPassSeal $passSealFile',[StringComparison]::Ordinal);$terminalArchiveIndex=$source.LastIndexOf('terminal_before_create_only_final_pass_seal',[StringComparison]::Ordinal);if(",
    )
    source = replace_once(
        source,
        "-or$sealWriteIndex-le$finalReplayIndex){throw 'Watcher census/lock/replay/PASS-publication/shutdown-seal order rejected'",
        "-or$terminalArchiveIndex-le$finalReplayIndex-or$sealWriteIndex-le$terminalArchiveIndex){throw 'Watcher census/lock/replay/PASS-publication/archive-terminal/create-only-final-seal order rejected'",
    )
    source = replace_once(
        source,
        "final_semantic_identity_hash_replay='PASS';alternate_host_routes_masked=",
        "final_semantic_identity_hash_replay='PASS';complete_predecessor_evidence_binding='PASS';authoritative_archived_lock_terminal_replay='PASS';alternate_host_routes_masked=",
    )
    source = replace_once(
        source,
        "    $staleModel=Invoke-StaleLockAdversarialModel\n    $boundary=",
        "    $staleModel=Invoke-StaleLockAdversarialModel\n    $predecessorModel=Get-ValidatedV28PredecessorEvidence;if($predecessorModel.authorized_files.Count-ne10-or$predecessorModel.runtime.live_file_pins.Count-ne9-or$predecessorModel.runtime.retained_lock_source_pin.sha256-cne'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'-or-not$predecessorModel.runtime.pass_absence_before_reconciliation.receipt_absent-or-not$predecessorModel.runtime.pass_absence_before_reconciliation.shutdown_seal_absent){throw 'Complete predecessor static model rejected'}\n    $boundary=",
    )
    source = replace_once(
        source,
        "stale_lock_model=$staleModel;wsl_executed=",
        "stale_lock_model=$staleModel;predecessor_evidence_model='10_AUTHORIZED_9_LIVE_PLUS_RETAINED_LOCK_AND_PASS_ABSENCE_VALIDATED';wsl_executed=",
    )
    return source


def token_stream(value: str) -> str:
    return json.dumps(json.loads(value), separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    assert_pin(V29_TESTS, V29_TESTS.stat().st_size, digest(V29_TESTS))
    builder_size = Path(__file__).stat().st_size
    builder_sha256 = digest(Path(__file__))
    tests_size = V29_TESTS.stat().st_size
    tests_sha256 = digest(V29_TESTS)
    runner = render_runner(builder_size, builder_sha256, tests_size, tests_sha256)
    V29_RUNNER.write_text(runner, encoding="utf-8", newline="\n")

    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V29_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"authorization emission failed with {result.returncode}: {result.stderr}"
        )
    if result.stderr:
        raise RuntimeError(f"authorization emission wrote stderr: {result.stderr}")
    authorization = result.stdout.strip()
    json.loads(authorization)
    V29_AUTH.write_text(authorization + "\n", encoding="utf-8", newline="\n")

    replay = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V29_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )
    if token_stream(replay.stdout) != token_stream(
        V29_AUTH.read_text(encoding="utf-8")
    ):
        raise RuntimeError("authorization replay mismatch")

    print(
        json.dumps(
            {
                "status": "MUNI_V29_SUCCESSOR_GENERATED_STATIC_ONLY",
                "run_id": RUN_ID,
                "runner": {
                    "size": V29_RUNNER.stat().st_size,
                    "sha256": digest(V29_RUNNER),
                },
                "authorization": {
                    "size": V29_AUTH.stat().st_size,
                    "sha256": digest(V29_AUTH),
                },
                "builder": {"size": builder_size, "sha256": builder_sha256},
                "tests": {"size": tests_size, "sha256": tests_sha256},
                "wsl_executed": False,
                "canonical_suite_executed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
