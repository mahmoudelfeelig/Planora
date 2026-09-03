from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
V30_RUN_ID = "e358bc6417224fe6a329ad3775853f01"
RUN_ID = "5f2d84640f40404a82dd180d7043d9c5"
CREATED_AT = "2026-08-28T11:32:25Z"
V30_RUNNER = REPO / "scripts/run_muni_v30_canonical_tests.ps1"
V31_RUNNER = REPO / "scripts/run_muni_v31_canonical_tests.ps1"
V31_TESTS = REPO / "tests/test_run_muni_v31_successor.py"
V31_AUTH = (
    REPO
    / "output/diagnostic-receipts/muni-fspsx-v31-canonical-tests-authorization-20260828T113225Z.receipt.json"
)


def pin(
    path: str,
    size: int,
    sha256: str,
    file_id: str,
    last_write_utc_ticks: int,
) -> dict[str, Any]:
    return {
        "path": path,
        "size": size,
        "sha256": sha256,
        "file_id": file_id,
        "last_write_utc_ticks": last_write_utc_ticks,
    }


V30_SOURCES = {
    "builder": pin(
        "scripts/build_muni_v30_successor.py",
        59_115,
        "c33cafd5260b79365ce434c086cf4e31c4333c904480b7ae445f15970201cb25",
        "0000000000000000000800000017268d",
        639235114557704531,
    ),
    "runner": pin(
        "scripts/run_muni_v30_canonical_tests.ps1",
        212_901,
        "3552bc86402bd26163c641d0870b4b2a4f6e1022a49301c862ee834d28230810",
        "000000000000000000080000001726aa",
        639235117535489382,
    ),
    "tests": pin(
        "tests/test_run_muni_v30_successor.py",
        17_533,
        "a0f7cad0ff955827f061a5f6228a45e1f8b9c09b22fa378318f4aea3793c621e",
        "000000000000000000080000001726a1",
        639235114675599150,
    ),
    "authorization": pin(
        "output/diagnostic-receipts/muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z.receipt.json",
        17_850,
        "5f21980b76f0360bbcbb0ecb3c7fc81633641852e422ddf3f6306acc826d399f",
        "000000000000000000080000001726b2",
        639235117542764197,
    ),
}

V30_PREFIX = (
    f"output/diagnostic-receipts/muni-fspsx-v30-canonical-readonly-tests-{V30_RUN_ID}"
)
V30_ARTIFACTS = {
    "claim": pin(
        f"{V30_PREFIX}.claim.json",
        541,
        "65719aa85b7fc5ee1bd48c7bfecf68ba2d6c47d8565c0b98acd7b4288fa5955c",
        "0000000000000000000700000012fe2d",
        639235129226154803,
    ),
    "heavy_lock_release": pin(
        f"{V30_PREFIX}.heavy-lock-release.json",
        430,
        "ad40c6361d38cc6b6fca5a8a9fc20f5a230436037f8f8a71bd51235d557b4245",
        "0000000000000000001a0000001722e5",
        639235130180429575,
    ),
    "heavy_lock": pin(
        f"{V30_PREFIX}.heavy-lock.json",
        1_324,
        "e76ee020f3b75fb10fb5c1e430db7b1d5e53f3df44322c7b916946421f95744b",
        "0000000000000000000d0000001723c3",
        639235129264467013,
    ),
    "watch_error": pin(
        f"{V30_PREFIX}.mutation-watch.error.log",
        179,
        "608ec8ead061d977f88c3aafe366cc8f51a2851e095590b9947dc3b1403c503d",
        "0000000000000000000b0000001723c5",
        639235130152733354,
    ),
    "watch_log": pin(
        f"{V30_PREFIX}.mutation-watch.jsonl",
        44_633,
        "49e98b88d6a129820277a53fdf14ed13521c071c6ff477dad722befe52ccb50c",
        "0000000000000000000b0000001723c4",
        639235130152653339,
    ),
    "watch_stop": pin(
        f"{V30_PREFIX}.mutation-watch.stop",
        146,
        "7e217ef84b6a92de3c924c80fad83d544935d55339365714bdd1bfb5687b3be9",
        "0000000000000000000c000000172662",
        639235130127480349,
    ),
    "watch_wrapper_stderr": pin(
        f"{V30_PREFIX}.mutation-watch.wrapper.stderr.log",
        218,
        "7e860067f2756a2196e9396d05307695fd14197d1a22029e70cc3e55f3ce1d84",
        "00000000000000000008000000172665",
        639235130153168577,
    ),
    "watch_wrapper_stdout": pin(
        f"{V30_PREFIX}.mutation-watch.wrapper.stdout.log",
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "00000000000000000011000000172664",
        639235130153138589,
    ),
    "predecessor_custody": pin(
        f"{V30_PREFIX}.predecessor-custody.json",
        77_234,
        "f6dde4858d4d2c94b17fb4817b4d59ce7645d5307e006c79c0629761f349e5e7",
        "0000000000000000000e000000170b4f",
        639235129264186964,
    ),
    "rejection": pin(
        f"{V30_PREFIX}.rejection.json",
        168_404,
        "6b3aac7af507b2b1eda25cb964dc8bec50efe47dec4dd637fb0f67e7bd122f29",
        "00000000000000000009000000172666",
        639235130180330840,
    ),
    "staging_inventory": pin(
        f"{V30_PREFIX}.staging-inventory.json",
        847_188,
        "b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb",
        "0000000000000000000c00000017265f",
        639235130126899778,
    ),
    "static_evidence": pin(
        f"{V30_PREFIX}.static-adversarial.json",
        2_091,
        "328227028682cc630c9feb91f62f567b4b6074336f3651a26ecc22f155236f21",
        "00000000000000000010000000165432",
        639235129262404529,
    ),
}

ARCHIVE_PIN = pin(
    "output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json",
    370,
    "dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98",
    "0000000000000000000c000000172456",
    639235031172129106,
)

V30_EXPECTED_ABSENT_SUFFIXES = [
    "receipt.json",
    "pass-publication-shutdown-seal.json",
    "rejection-emergency.json",
    "pre-inventory.json",
    "post-inventory.json",
    "plan.json",
    "stdout.log",
    "stderr.log",
    "exit-code.txt",
    "acceptance-commitment.json",
    "cleanup.json",
    "mutation-watch.cleanup.json",
    "resource-exclusivity.jsonl",
    "resource-exclusivity.error.log",
    "resource-exclusivity.stop",
    "resource-exclusivity.wrapper.stdout.log",
    "resource-exclusivity.wrapper.stderr.log",
]

PREDECESSOR_CONTRACT = {
    "schema": "planora.muni-v31.v28-v30-predecessor-custody-contract.v1",
    "v28": {
        "archive": ARCHIVE_PIN,
        "pass_receipt": "output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json",
        "pass_seal": "output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json",
    },
    "v29": {
        "pass_receipt": "output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.receipt.json",
        "pass_seal": "output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.pass-publication-shutdown-seal.json",
    },
    "v30": {
        "run_id": V30_RUN_ID,
        "sources": V30_SOURCES,
        "artifacts": V30_ARTIFACTS,
        "carrier": V30_ARTIFACTS["rejection"],
        "embedded_evidence_schema": "planora.muni-v30.complete-v28-v29-predecessor-evidence.v1",
        "post_rejection_predecessor_evidence_sha256": "79e94da51f8ada746828f1563344f933b1ebdae639a8d3de19d36c97086dae46",
        "initial_custody_predecessor_evidence_sha256": "253f009ff4c92d222f71853fa52c847990bafe5b1c37e682a1a33a7fcbe77ce5",
        "failure": {
            "status": "REJECTED_AUTHORIZATION_CONSUMED",
            "phase": "after_staging_ready_before_preinventory_resource_monitor_and_canonical_launch",
            "primary_root_cause": "PowerShell_TestPath_command_mode_binding_of_empty_error_length_as_positional_argument_0",
            "secondary_failure": "abort_control_watcher_stopped_before_cleanup_authorization",
            "canonical_suite_executed": False,
            "automatic_retry_authorized": False,
        },
        "snapshot": {
            "root": f"/tmp/planora-muni-v30-canonical-tests-{V30_RUN_ID}",
            "inventory": V30_ARTIFACTS["staging_inventory"],
            "files": 3_146,
            "directories": 368,
            "bytes": 190_900_047,
            "retained_for_forensics": True,
            "must_not_be_reused_or_deleted_by_v31": True,
        },
        "expected_absent_suffixes": V30_EXPECTED_ABSENT_SUFFIXES,
        "pass_receipt": f"{V30_PREFIX}.receipt.json",
        "pass_seal": f"{V30_PREFIX}.pass-publication-shutdown-seal.json",
    },
    "shared_lock": "output/diagnostic-receipts/planora-shared-heavy-wsl.lock",
    "required_pre_acquisition_state": "archive_exact_shared_lock_absent_v28_v29_v30_pass_absent_41_pins_exact",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"anchor count {count}, expected 1: {old[:160]!r}")
    return text.replace(old, new, 1)


def replace_exact_count(text: str, old: str, new: str, expected: int) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"anchor count {count}, expected {expected}: {old[:160]!r}")
    return text.replace(old, new)


def replace_region(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"start anchor missing: {start[:160]!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end anchor missing: {end[:160]!r}")
    return text[:start_index] + replacement + text[end_index:]


def assert_pin(expected: dict[str, Any]) -> None:
    path = REPO / expected["path"]
    if path.stat().st_size != expected["size"] or sha256(path) != expected["sha256"]:
        raise RuntimeError(f"pinned v30 predecessor drift: {path}")
    if os.name != "nt":
        return
    result = subprocess.run(
        ["fsutil.exe", "file", "queryfileid", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"File ID is 0x([0-9a-fA-F]{32})", result.stdout)
    ticks = int(path.stat().st_mtime_ns // 100) + 621355968000000000
    if (
        not match
        or match.group(1).lower() != expected["file_id"]
        or ticks != expected["last_write_utc_ticks"]
    ):
        raise RuntimeError(f"pinned v30 predecessor identity drift: {path}")


def ps_contract_json() -> str:
    return json.dumps(PREDECESSOR_CONTRACT, separators=(",", ":"), sort_keys=False)


def render_authorization_function(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    template = r"""function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){
    $closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json
    $o=[ordered]@{
        schema='planora.itc2019.canonical-test-authorization.v11';created_at_utc='__CREATED_AT__';instance='muni-fspsx-fal17';candidate='muni_v31';test_id=$runId
        decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V30_PREINVENTORY_BINDING_FAILURE';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false
        runner=[ordered]@{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash}
        successor_admission=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v31_successor.py';size=__BUILDER_SIZE__;sha256='__BUILDER_HASH__'};tests=[ordered]@{path='tests/test_run_muni_v31_successor.py';size=__TESTS_SIZE__;sha256='__TESTS_HASH__'}}
        predecessor_custody_contract=$predecessor
        snapshot_closure=$closure
        log_bridge_contract=[ordered]@{writer='create_only_reserve_close_then_identity_checked_short_lived_append_fsync';reader='bounded_explicit_FileStream_stable_identity_length_terminal_LF_UTF8_JSON';writer_exit_visibility_race_retried_within_existing_three_second_deadline=$true;watcher_and_resource_monitor_both_fixed=$true;legacy_lifetime_open_negative_baseline_required=$true;isolated_switch='LogBridgeSelfTest';canonical_suite_executed_by_bridge_test=$false}
        readiness_binding_contract=[ordered]@{shared_predicate='Test-NonEmptyEvidenceFile';watcher_and_resource_call_sites=$true;missing_empty_nonempty_runtime_regression=$true;legacy_empty_file_binding_failure_reproduced=$true;operator_shaped_command_arguments_rejected=$true;isolated_switch='ReadinessPredicateSelfTest';static_self_test_both_powershell_engines_required=$true}
        retained_v30_snapshot_contract=[ordered]@{root=$predecessor.v30.snapshot.root;inventory=$predecessor.v30.snapshot.inventory;isolated_switch='RetainedV30SnapshotSelfTest';initial_and_terminal_read_only_replay_required=$true;post_cleanup_replay_while_v31_lock_held=$true;terminal_replay_immediately_before_final_archive_guard=$true;descriptor_open_nofollow_identity_replay=$true;v31_cleanup_must_not_target_v30=$true}
        heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;continuous_monitor='target_100ms_with_authenticated_monotonic_sequence_and_750ms_maximum_gap';census='fail_closed_allow_live_proven_ancestry_or_previously_frozen_descendant_identity_in_exact_launch_namespace_plus_minimal_infrastructure_reject_hostile_siblings';target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval';pinned_subprocess_sites=16;descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'}
        launch_contract=[ordered]@{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';watcher_lifetime='ARMED_before_staging_lossless_events_through_final_census_same_handle_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown';staged_identity='device_inode_nlink_mode_size_sha256_frozen_and_replayed';host_root=$root;explicit_snapshot_ro_bind='/snapshot';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;environment_cleared=$true;capabilities_dropped=$true;gnu_timeout=[ordered]@{term_seconds=600;kill_after_seconds=15};host_wsl_deadline_seconds=$hostDeadlineSeconds;canonical_execute_sites=1}
        canonical_contract=[ordered]@{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';strict_stderr_grammar=$true;exact_skip_identities=[ordered]@{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}}
        evidence_contract=[ordered]@{atomic_claim='claim_attempt_marked_before_CreateNew_inside_outer_rejection_try_default_fail_closed_claim_v2_before_preflight';any_failure_consumes_authorization=$true;complete_v28_v29_v30_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true;all_41_predecessor_file_ids_and_timestamps_authorized=$true;predecessor_pins_in_protected_replay_sets=$true;v28_v29_v30_pass_absence_replayed_through_final_pass_seal_publication=$true;retained_archive_validated_in_place_without_mutation=$true;retained_v30_snapshot_initial_and_terminal_replay_bound=$true;terminal_archived_lock_identity_replay_bound_by_final_pass_seal=$true;terminal_archived_lock_read_guard_held_through_final_pass_seal_flush=$true;final_pass_seal_create_only_durable_last_operation=$true;new_lock_verified_only_through_held_handle=$true;new_lock_release='same_handle_stable_bytes_then_DeleteOnClose';all_file_nlinks_and_device_inode_retained=$true;exact_staged_file_and_directory_set=$true;plan_and_receipt_bind_runner_authorization_snapshot_predecessor_and_custody=$true;pass_receipt_requires_post_publication_authenticated_watcher_shutdown_seal=$true;watcher_active_through_pass_publication=$true;claim_constructor_write_flush_and_immediate_failures_require_durable_rejection=$true;emergency_rejection_fallback_create_only=$true;rejection_lifecycle_fields_required=$true}
    }
    return($o|ConvertTo-Json -Depth 60 -Compress)
}

"""
    return (
        template.replace("__CREATED_AT__", CREATED_AT)
        .replace("__BUILDER_SIZE__", str(builder_size))
        .replace("__BUILDER_HASH__", builder_hash)
        .replace("__TESTS_SIZE__", str(tests_size))
        .replace("__TESTS_HASH__", tests_hash)
    )


PREDECESSOR_FUNCTIONS = r"""function New-ExpectedCombinedPredecessorEvidence{
    $contract=$predecessorContractJson|ConvertFrom-Json
    return [ordered]@{schema='planora.muni-v31.complete-v28-v29-v30-predecessor-evidence.v1';status='EXPECTED_UNVALIDATED';contract=$contract;prior_evidence=$null;v30_evidence=$null;runtime=[ordered]@{validation_phase='not_started';validated_pins=@();pass_absence=$null;shared_lock_absent=$null}}
}
function Assert-V28V29V30PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));v30_receipt_absent=(-not(Test-Path -LiteralPath $v30ReceiptPath));v30_seal_absent=(-not(Test-Path -LiteralPath $v30PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    if(-not$result.v28_receipt_absent-or-not$result.v28_seal_absent-or-not$result.v29_receipt_absent-or-not$result.v29_seal_absent-or-not$result.v30_receipt_absent-or-not$result.v30_seal_absent){throw "v28/v29/v30 PASS evidence unexpectedly exists: $Phase"};return $result
}
function Assert-RetainedArchivePin([string]$Path,[object]$ExpectedPin,[byte[]]$ExpectedBytes,[string]$ExpectedHash,[string]$Phase){
    $full=[IO.Path]::GetFullPath($Path);$relative=$full.Replace($repo+'\','').Replace('\','/');if($ExpectedPin.path-cne$relative-or[long]$ExpectedPin.size-ne$ExpectedBytes.Length-or$ExpectedPin.sha256-cne$ExpectedHash){throw "Retained archive expected pin rejected: $Phase"}
    [void](Assert-LocalEvidencePin $ExpectedPin);$probe=New-Object IO.FileStream($full,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{if([IO.Path]::GetFullPath($probe.Name)-cne$full){throw "Retained archive stream path rejected: $Phase"};$item=Get-Item -LiteralPath $full;if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$item.PSIsContainer-or$item.Length-ne$ExpectedBytes.Length-or$probe.Length-ne$ExpectedBytes.Length){throw "Retained archive path identity rejected: $Phase"};[void](Assert-HeldStreamBytes $probe $ExpectedBytes $ExpectedHash "Retained archive $Phase")}finally{$probe.Dispose()}
    [void](Assert-LocalEvidencePin $ExpectedPin);return [ordered]@{phase=$Phase;status='IDENTITY_AND_EXCLUSIVE_SAME_HANDLE_BYTES_REPLAYED';archive_pin=$ExpectedPin;observed_at_utc=[DateTime]::UtcNow.ToString('o')}
}
function Assert-FinalArchivedStaleLockIdentity([object]$ExpectedPin,[string]$Phase,[bool]$RequireSharedLockAbsent){
    $bytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}')
    $result=Assert-RetainedArchivePin $staleArchivePath $ExpectedPin $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' $Phase
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw "Shared heavy lock unexpectedly present during archived-lock replay: $Phase"};$result['shared_lock_absence_required']=$RequireSharedLockAbsent;$result['shared_lock_absent']=(-not(Test-Path -LiteralPath $sharedLockPath));$result['predecessor_pass_absence']=Assert-V28V29V30PassEvidenceAbsent $Phase;return $result
}
function Open-TerminalArchivedStaleLockGuard([object]$ExpectedPin,[string]$Phase){
    $preGuardReplay=Assert-FinalArchivedStaleLockIdentity $ExpectedPin $Phase $true;$bytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}');$guard=$null
    try{$guard=New-Object IO.FileStream($staleArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);if([IO.Path]::GetFullPath($guard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){throw 'Terminal archived-lock guard path rejected'};[void](Assert-HeldStreamBytes $guard $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Terminal archived stale lock guard');[void](Assert-LocalEvidencePin $ExpectedPin);if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock unexpectedly present while terminal archive guard held'};$passAbsence=Assert-V28V29V30PassEvidenceAbsent ($Phase+'_guard_held');$evidence=[ordered]@{schema='planora.muni-v31.terminal-archived-lock-guard.v1';phase=$Phase;status='IDENTITY_REPLAYED_AND_READ_GUARD_HELD_THROUGH_FINAL_PASS_FLUSH';archive_pin=$ExpectedPin;pre_guard_replay=$preGuardReplay;guard_access='Read';guard_share='Read_only_blocks_write_and_delete';same_handle_bytes_replayed=$true;shared_lock_absent=$true;predecessor_pass_absence=$passAbsence;acquired_at_utc=[DateTime]::UtcNow.ToString('o')};return [pscustomobject]@{Stream=$guard;Evidence=$evidence}}catch{if($null-ne$guard){$guard.Dispose()};throw}
}
function Get-RawJsonObjectPropertyTokenHash([string]$Json,[string]$PropertyName){
    $key='"'+$PropertyName+'"';$keyIndex=$Json.IndexOf($key,[StringComparison]::Ordinal);if($keyIndex-lt0){throw "Raw JSON property missing: $PropertyName"};$i=$keyIndex+$key.Length
    while($i-lt$Json.Length-and[char]::IsWhiteSpace($Json[$i])){$i++};if($i-ge$Json.Length-or$Json[$i]-ne':'){throw "Raw JSON property colon missing: $PropertyName"};$i++;while($i-lt$Json.Length-and[char]::IsWhiteSpace($Json[$i])){$i++};if($i-ge$Json.Length-or$Json[$i]-ne'{'){throw "Raw JSON object missing: $PropertyName"}
    $start=$i;$depth=0;$inside=$false;$escaped=$false
    for(;$i-lt$Json.Length;$i++){$ch=$Json[$i];if($inside){if($escaped){$escaped=$false}elseif($ch-eq'\'){$escaped=$true}elseif($ch-eq'"'){$inside=$false};continue};if($ch-eq'"'){$inside=$true;continue};if($ch-eq'{'){$depth++;continue};if($ch-eq'}'){$depth--;if($depth-eq0){$raw=$Json.Substring($start,$i-$start+1);return Get-Utf8StringSha256 (ConvertTo-JsonTokenStream $raw)};if($depth-lt0){break}}}
    throw "Raw JSON object unterminated: $PropertyName"
}
function Get-ValidatedCombinedPredecessorEvidence([bool]$RequireSharedLockAbsent){
    $e=New-ExpectedCombinedPredecessorEvidence;$c=$e.contract;$pins=@()
    foreach($group in @($c.v30.sources,$c.v30.artifacts)){foreach($property in $group.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}}
    $rejectionRaw=[IO.File]::ReadAllText($v30RejectionPath,$utf8);$rejection=$rejectionRaw|ConvertFrom-Json;$claim=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.claim.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$release=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.heavy_lock_release.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$lockEvidence=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.heavy_lock.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$authorization=[IO.File]::ReadAllText((Join-Path $repo $c.v30.sources.authorization.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$custodyRaw=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.predecessor_custody.path.Replace('/','\')),$utf8);$custody=$custodyRaw|ConvertFrom-Json;$stage=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.staging_inventory.path.Replace('/','\')),$utf8)|ConvertFrom-Json
    $expectedV30Artifacts=@($c.v30.artifacts.PSObject.Properties|ForEach-Object{[IO.Path]::GetFullPath((Join-Path $repo $_.Value.path.Replace('/','\')))}|Sort-Object);$v30Parent=Split-Path -Parent $v30Prefix;$v30Leaf=(Split-Path -Leaf $v30Prefix)+'.';$observedV30Entries=@(Get-ChildItem -LiteralPath $v30Parent -Force|Where-Object{$_.Name.IndexOf($v30Leaf,[StringComparison]::Ordinal)-eq0});if(@($observedV30Entries|Where-Object{$_.PSIsContainer}).Count-ne0){throw 'v30 prefixed directory rejected'};$observedV30Artifacts=@($observedV30Entries|ForEach-Object{$_.FullName}|Sort-Object)
    if($observedV30Entries.Count-ne12-or(ConvertTo-JsonTokenStream ($observedV30Artifacts|ConvertTo-Json -Compress))-cne(ConvertTo-JsonTokenStream ($expectedV30Artifacts|ConvertTo-Json -Compress))){throw 'v30 exact artifact inventory rejected'}
    if($claim.run_id-cne$c.v30.run_id-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.failure_consumes_authorization){throw 'v30 claim semantics rejected'}
    $expectedFailure="A positional parameter cannot be found that accepts argument '0'.; watcher_stop=Watcher wrapper rejected: exit=1";if($rejection.run_id-cne$c.v30.run_id-or$rejection.status-cne'REJECTED_AUTHORIZATION_CONSUMED'-or-not[bool]$rejection.claim_publication_complete-or$rejection.claim_publication_phase-cne'durably_published'-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$rejection.acceptance_commitment_sha256-cne''-or$rejection.failure-cne$expectedFailure-or-not[bool]$rejection.snapshot_retained_for_forensics-or$rejection.predecessor_rejection_replay.status-cne'REPLAYED'-or@($rejection.predecessor_rejection_replay.errors).Count-ne0){throw 'v30 consumed binding-failure semantics rejected'}
    if($lockEvidence.lock.run_id-cne$c.v30.run_id-or-not[bool]$lockEvidence.held_open-or-not[bool]$lockEvidence.same_handle_verified-or-not[bool]$lockEvidence.delete_on_close-or$release.run_id-cne$c.v30.run_id-or$release.decision-cne'REJECTED'-or-not[bool]$release.same_handle_verified-or-not[bool]$release.delete_on_close-or-not[bool]$release.lock_path_absent-or$release.lock_sha256-cne$lockEvidence.lock_sha256){throw 'v30 lock release semantics rejected'}
    if($authorization.schema-cne'planora.itc2019.canonical-test-authorization.v10'-or$authorization.test_id-cne$c.v30.run_id-or$authorization.candidate-cne'muni_v30'-or[bool]$authorization.automatic_retry_authorized-or$authorization.runner.sha256-cne$c.v30.sources.runner.sha256-or$authorization.successor_admission.builder.sha256-cne$c.v30.sources.builder.sha256-or$authorization.successor_admission.tests.sha256-cne$c.v30.sources.tests.sha256){throw 'v30 authorization binding rejected'}
    $initialHash=Get-RawJsonObjectPropertyTokenHash $custodyRaw 'predecessor_evidence';if($custody.run_id-cne$c.v30.run_id-or$custody.status-cne'EXACT_V28_V29_CUSTODY_VALIDATED_BEFORE_V30_LOCK'-or-not[bool]$custody.shared_lock_absent-or$custody.predecessor_evidence_sha256-cne$c.v30.initial_custody_predecessor_evidence_sha256-or$initialHash-cne$c.v30.initial_custody_predecessor_evidence_sha256-or$rejection.predecessor_custody_sha256-cne$c.v30.artifacts.predecessor_custody.sha256){throw 'v30 predecessor custody rejected'}
    if($stage.schema-cne'planora.muni-v30.snapshot-inventory.v1'-or$stage.root-cne$c.v30.snapshot.root-or$stage.file_count-ne$c.v30.snapshot.files-or$stage.directory_count-ne$c.v30.snapshot.directories-or$stage.total_bytes-ne$c.v30.snapshot.bytes-or@($stage.files|Where-Object{$_.nlink-ne1-or$_.mode-cne'0400'-or$_.type-cne'regular file'}).Count-ne0-or@($stage.directories|Where-Object{($_.path-ceq'.'-and$_.mode-cne'0700')-or($_.path-cne'.'-and$_.mode-cne'0500')}).Count-ne0){throw 'v30 retained staging inventory semantics rejected'}
    $watchRaw=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.watch_log.path.Replace('/','\')),$utf8);$watchRows=@($watchRaw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($watchRows.Count-ne203-or$watchRows[0].kind-cne'ARMED'-or$watchRows[-1].kind-cne'READY'-or$watchRows[-1].file_count-ne$c.v30.snapshot.files-or$watchRows[-1].staging_event_count-ne201-or$watchRows[-1].inventory_sha256-cne$c.v30.artifacts.staging_inventory.sha256-or@($watchRows|Where-Object{$_.kind-ceq'STAGING_EVENT'}).Count-ne201){throw 'v30 watcher READY grammar rejected'}
    if(-not[bool]$watchRows[-1].all_nlink_one-or-not[bool]$watchRows[-1].device_inode_frozen-or-not[bool]$watchRows[-1].parent_watch_active-or$watchRows[-1].parent_watch_loss_events-ne0-or-not[bool]$watchRows[-1].watch_started_before_staging-or@($watchRows|Where-Object{$_.kind-cin@('CLEANUP_AUTHORIZED','CLEANED','DONE')}).Count-ne0){throw 'v30 watcher failure-phase semantics rejected'}
    $watchError=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.watch_error.path.Replace('/','\')),$utf8);$watchWrapperError=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.watch_wrapper_stderr.path.Replace('/','\')),$utf8);$watchStop=[IO.File]::ReadAllText((Join-Path $repo $c.v30.artifacts.watch_stop.path.Replace('/','\')),$utf8)|ConvertFrom-Json;if($watchError-cnotmatch'watcher stopped before cleanup authorization'-or$watchWrapperError-cnotmatch'watcher stopped before cleanup authorization'-or$watchStop.schema-cne'planora.muni-v30.watcher-abort-control.v1'-or(Get-Item -LiteralPath (Join-Path $repo $c.v30.artifacts.watch_wrapper_stdout.path.Replace('/','\'))).Length-ne0){throw 'v30 watcher terminal artifact shape rejected'}
    foreach($suffix in $c.v30.expected_absent_suffixes){if(Test-Path -LiteralPath ($v30Prefix+'.'+$suffix)){throw "Unexpected v30 post-readiness artifact exists: $suffix"}}
    $prior=$rejection.predecessor_evidence;$postHash=Get-RawJsonObjectPropertyTokenHash $rejectionRaw 'predecessor_evidence';if($prior.schema-cne$c.v30.embedded_evidence_schema-or$prior.status-cne'VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY'-or$rejection.predecessor_evidence_sha256-cne$c.v30.post_rejection_predecessor_evidence_sha256-or$postHash-cne$c.v30.post_rejection_predecessor_evidence_sha256-or$prior.rejection_replay.status-cne'REPLAYED'-or@($prior.rejection_replay.errors).Count-ne0){throw 'v30 carried v28/v29 evidence rejected'}
    $priorPins=@($prior.runtime.validated_pins);if($priorPins.Count-ne25-or@($priorPins.path|Sort-Object -Unique).Count-ne25){throw 'v30 carried predecessor pin cardinality rejected'};foreach($pin in $priorPins){[void](Assert-LocalEvidencePin $pin);$pins+=,$pin}
    if($pins.Count-ne41-or@($pins.path|Sort-Object -Unique).Count-ne41){throw 'v31 combined predecessor pin cardinality rejected'}
    [void](Assert-FinalArchivedStaleLockIdentity $c.v28.archive 'combined_predecessor_validation' $RequireSharedLockAbsent);$pass=Assert-V28V29V30PassEvidenceAbsent 'combined_predecessor_validation'
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw 'Shared lock present before v31 acquisition'}
    $e.status='VALIDATED_EXACT_V28_V29_V30_PREDECESSOR_CUSTODY';$e.prior_evidence=$prior;$e.v30_evidence=[ordered]@{run_id=$c.v30.run_id;authorization=$authorization;claim=$claim;rejection=[ordered]@{pin=$c.v30.artifacts.rejection;status=$rejection.status;failure=$rejection.failure;predecessor_evidence_sha256=$rejection.predecessor_evidence_sha256;snapshot_retained_for_forensics=$rejection.snapshot_retained_for_forensics};nested_predecessor_hashes=[ordered]@{initial_custody=$initialHash;post_rejection=$postHash};lock_evidence=$lockEvidence;lock_release=$release;custody=$custody;staging_inventory_pin=$c.v30.artifacts.staging_inventory;failure=$c.v30.failure};$e.runtime.validation_phase=$(if($RequireSharedLockAbsent){'before_v31_lock_acquisition'}else{'rejection_replay'});$e.runtime.validated_pins=$pins;$e.runtime.pass_absence=$pass;$e.runtime.shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));return $e
}
function Get-CombinedPredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_PREDECESSOR_CUSTODY'){throw 'Combined predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCombinedPredecessorReplay([object]$Evidence,[object]$ArchivePin){try{$replayed=Get-ValidatedCombinedPredecessorEvidence $false;return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=$replayed;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$Evidence;errors=@($_.Exception.Message)}}}
"""


READINESS_HELPER = r"""function Test-NonEmptyEvidenceFile([string]$Path){
    return ((Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-Item -LiteralPath $Path).Length -ne 0))
}
function Invoke-ReadinessPredicateRegression{
    $dir=Join-Path ([IO.Path]::GetTempPath()) ('planora-v31-readiness-'+[Guid]::NewGuid().ToString('N'));$missing=Join-Path $dir 'missing.log';$empty=Join-Path $dir 'empty.log'
    [void](New-Item -ItemType Directory -Path $dir)
    try{
        if(Test-NonEmptyEvidenceFile $missing){throw 'Missing readiness evidence was reported nonempty'}
        $stream=New-Object IO.FileStream($empty,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$stream.Flush($true)}finally{$stream.Dispose()}
        if(Test-NonEmptyEvidenceFile $empty){throw 'Empty readiness evidence was reported nonempty'}
        $legacyExpression='if(Test-Path -LiteralPath $empty-'+'and(Get-Item -LiteralPath $empty).Length-'+'ne0){}';$legacyBindingFailure=$false
        try{& ([scriptblock]::Create($legacyExpression))}catch{if($_.FullyQualifiedErrorId-cnotmatch'PositionalParameterNotFound'-or$_.Exception.Message-cnotmatch"argument '0'"){throw "Legacy readiness failure changed: $($_.Exception.Message)"};$legacyBindingFailure=$true}
        if(-not$legacyBindingFailure){throw 'Legacy empty-file readiness expression did not reproduce the positional binder failure'}
        [IO.File]::WriteAllBytes($empty,[byte[]]@(1));if(-not(Test-NonEmptyEvidenceFile $empty)){throw 'Nonempty readiness evidence was not detected'}
        $source=[IO.File]::ReadAllText($runnerPath,$utf8);$forbidden=@(('$watchErrorFile-'+'and('),('$resourceErrorFile-'+'and('))
        foreach($value in $forbidden){if($source.IndexOf($value,[StringComparison]::Ordinal)-ge0){throw "Operator-shaped command argument survived: $value"}}
        if(([regex]::Matches($source,'if\(Test-NonEmptyEvidenceFile \$(watchErrorFile|resourceErrorFile)\)')).Count-ne2){throw 'Readiness predicate production call-site cardinality rejected'}
        return [ordered]@{status='MISSING_EMPTY_NONEMPTY_LEGACY_FAILURE_AND_BOTH_PRODUCTION_CALL_SITES_PASS';missing_is_nonempty=$false;empty_is_nonempty=$false;nonempty_is_nonempty=$true;legacy_empty_binding_failure_reproduced=$legacyBindingFailure;production_call_sites=2;operator_shaped_arguments_absent=$true}
    }finally{if(Test-Path -LiteralPath $empty){Remove-Item -LiteralPath $empty -Force};if(Test-Path -LiteralPath $dir){Remove-Item -LiteralPath $dir -Force}}
}

"""


RETAINED_SNAPSHOT_SOURCE = r"""$retainedV30SnapshotVerifierSource = @'
import hashlib,json,os,stat,sys
c=json.loads(__import__('base64').b64decode(sys.argv[1]));root=c['root'];expected_path=c['expected'];phase=c['phase']
def file_identity(s): return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size)
def dir_identity(s): return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink)
before=os.lstat(expected_path)
if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_nlink!=1: raise RuntimeError('retained expected inventory type rejected')
fd=os.open(expected_path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
try:
 opened=os.fstat(fd)
 if file_identity(opened)!=file_identity(before): raise RuntimeError('retained expected inventory open identity rejected')
 chunks=[]
 while True:
  chunk=os.read(fd,1<<20)
  if not chunk: break
  chunks.append(chunk)
 final_opened=os.fstat(fd)
finally: os.close(fd)
after=os.lstat(expected_path);raw=b''.join(chunks)
if file_identity(before)!=file_identity(final_opened) or file_identity(before)!=file_identity(after): raise RuntimeError('retained expected inventory identity drift')
if len(raw)!=c['expected_size'] or hashlib.sha256(raw).hexdigest()!=c['expected_sha256']: raise RuntimeError('retained expected inventory pin rejected')
expected=json.loads(raw);dirs=[];files=[];total=0
for current,names,leaves,dirfd in os.fwalk(root,topdown=True,follow_symlinks=False):
 names.sort();rel=os.path.relpath(current,root).replace(os.sep,'/');linked=os.lstat(current);opened_dir=os.fstat(dirfd);mode=stat.S_IMODE(opened_dir.st_mode)
 if dir_identity(linked)!=dir_identity(opened_dir) or not stat.S_ISDIR(opened_dir.st_mode) or stat.S_ISLNK(linked.st_mode) or mode!=(0o700 if rel=='.' else 0o500): raise RuntimeError('retained directory rejected: '+rel)
 dirs.append({'path':rel,'mode':format(mode,'04o'),'device':opened_dir.st_dev,'inode':opened_dir.st_ino,'nlink':opened_dir.st_nlink})
 for name in names:
  child=os.stat(name,dir_fd=dirfd,follow_symlinks=False)
  if not stat.S_ISDIR(child.st_mode) or stat.S_ISLNK(child.st_mode): raise RuntimeError('retained child directory rejected: '+name)
 for name in sorted(leaves):
  r=(name if rel=='.' else rel+'/'+name);before_file=os.stat(name,dir_fd=dirfd,follow_symlinks=False)
  if not stat.S_ISREG(before_file.st_mode) or stat.S_ISLNK(before_file.st_mode) or stat.S_IMODE(before_file.st_mode)!=0o400 or before_file.st_nlink!=1: raise RuntimeError('retained file rejected: '+r)
  childfd=os.open(name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=dirfd);h=hashlib.sha256()
  try:
   opened_file=os.fstat(childfd)
   if file_identity(opened_file)!=file_identity(before_file): raise RuntimeError('retained file open identity rejected: '+r)
   while True:
     b=os.read(childfd,1<<20)
     if not b: break
     h.update(b)
   final_file=os.fstat(childfd)
  finally: os.close(childfd)
  after_file=os.stat(name,dir_fd=dirfd,follow_symlinks=False)
  if file_identity(before_file)!=file_identity(final_file) or file_identity(before_file)!=file_identity(after_file): raise RuntimeError('retained file identity drift: '+r)
  files.append({'path':r,'type':'regular file','mode':'0400','device':before_file.st_dev,'inode':before_file.st_ino,'nlink':1,'size':before_file.st_size,'sha256':h.hexdigest()});total+=before_file.st_size
 linked_after=os.lstat(current)
 if dir_identity(linked)!=dir_identity(linked_after): raise RuntimeError('retained directory identity drift: '+rel)
current={'schema':expected['schema'],'root':root,'directory_count':len(dirs),'file_count':len(files),'total_bytes':total,'directories':sorted(dirs,key=lambda x:x['path']),'files':sorted(files,key=lambda x:x['path'])}
current_raw=json.dumps(current,sort_keys=True,separators=(',',':')).encode()
if current!=expected or hashlib.sha256(current_raw).hexdigest()!=c['expected_sha256']: raise RuntimeError('retained v30 snapshot identity replay rejected')
print(json.dumps({'schema':'planora.muni-v31.retained-v30-snapshot-replay.v1','status':'EXACT_RETAINED_V30_SNAPSHOT_REPLAY','phase':phase,'root':root,'files':len(files),'directories':len(dirs),'bytes':total,'inventory_sha256':hashlib.sha256(current_raw).hexdigest(),'all_nlink_one':all(x['nlink']==1 for x in files)},sort_keys=True,separators=(',',':')))
'@

"""


def render_runner(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    for expected in [*V30_SOURCES.values(), *V30_ARTIFACTS.values(), ARCHIVE_PIN]:
        assert_pin(expected)

    source = V30_RUNNER.read_text(encoding="utf-8")
    source = source.replace(V30_RUN_ID, RUN_ID)
    source = source.replace("v30", "v31").replace("V30", "V31")
    source = replace_exact_count(source, "20260828T101448Z", "20260828T113225Z", 2)
    source = replace_exact_count(
        source,
        "complete-v28-v29-predecessor-evidence.v1",
        "complete-v28-v29-v30-predecessor-evidence.v1",
        3,
    )
    source = replace_once(
        source,
        "EXACT_V28_V29_CUSTODY_VALIDATED_BEFORE_V31_LOCK",
        "EXACT_V28_V29_V30_CUSTODY_VALIDATED_BEFORE_V31_LOCK",
    )
    source = replace_once(
        source,
        "if($predecessorPins.Count-ne25){throw 'Combined predecessor pin cardinality rejected'}",
        "if($predecessorPins.Count-ne41){throw 'Combined predecessor pin cardinality rejected'}",
    )
    source = replace_once(
        source,
        "param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization,[switch]$LogBridgeSelfTest)",
        "param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization,[switch]$LogBridgeSelfTest,[switch]$ReadinessPredicateSelfTest,[switch]$RetainedV30SnapshotSelfTest)",
    )

    top_start = (
        "$successorBuilderPath = Join-Path $repo 'scripts\\build_muni_v31_successor.py'"
    )
    top_end = "$utf8 = New-Object System.Text.UTF8Encoding($false)"
    top = r"""$successorBuilderPath = Join-Path $repo 'scripts\build_muni_v31_successor.py'
$admissionTestsPath = Join-Path $repo 'tests\test_run_muni_v31_successor.py'
$v28ReceiptPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json'
$v28PassSealPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json'
$v29ReceiptPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.receipt.json'
$v29PassSealPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.pass-publication-shutdown-seal.json'
$v30Prefix = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v30-canonical-readonly-tests-e358bc6417224fe6a329ad3775853f01'
$v30ReceiptPath = $v30Prefix+'.receipt.json'
$v30PassSealPath = $v30Prefix+'.pass-publication-shutdown-seal.json'
$v30RejectionPath = $v30Prefix+'.rejection.json'
$v30SnapshotRoot = '/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01'
$v30StagingInventoryWsl = '/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/muni-fspsx-v30-canonical-readonly-tests-e358bc6417224fe6a329ad3775853f01.staging-inventory.json'
$staleArchiveRelative = 'output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json'
$staleArchivePath = Join-Path $repo 'output\diagnostic-receipts\retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json'
$predecessorCustodyFile = "$prefix.predecessor-custody.json"
$retainedV30SnapshotCustodyFile = "$prefix.retained-v30-snapshot-custody.json"
$retainedV30SnapshotTerminalCustodyFile = "$prefix.retained-v30-snapshot-terminal-custody.json"
$predecessorContractJson = @'
__CONTRACT__
'@
""".replace("__CONTRACT__", ps_contract_json())
    source = replace_region(source, top_start, top_end, top)

    auth_start = source.rfind("function Get-ExpectedAuthorizationJson")
    auth_end = source.find("if($EmitExpectedAuthorization){", auth_start)
    if auth_start < 0 or auth_end < 0:
        raise RuntimeError("effective authorization block not found")
    source = (
        source[:auth_start]
        + render_authorization_function(
            builder_size, builder_hash, tests_size, tests_hash
        )
        + source[auth_end:]
    )

    predecessor_start = "function New-ExpectedCombinedPredecessorEvidence"
    predecessor_end = "function Invoke-LockSelfReadRegressionModel"
    source = replace_region(
        source, predecessor_start, predecessor_end, PREDECESSOR_FUNCTIONS
    )

    source = replace_once(
        source,
        "function Get-ObsoleteV3AuthorizationJson",
        READINESS_HELPER + "function Get-ObsoleteV3AuthorizationJson",
    )
    source = replace_once(
        source,
        "$inventorySource = @'",
        RETAINED_SNAPSHOT_SOURCE + "$inventorySource = @'",
    )

    source = replace_once(
        source,
        "if(Test-Path -LiteralPath $watchErrorFile-and(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Mutation watcher emitted readiness error'}",
        "if(Test-NonEmptyEvidenceFile $watchErrorFile){throw 'Mutation watcher emitted readiness error'}",
    )
    source = replace_once(
        source,
        "if(Test-Path -LiteralPath $resourceErrorFile-and(Get-Item -LiteralPath $resourceErrorFile).Length-ne0){throw 'Resource monitor emitted readiness error'}",
        "if(Test-NonEmptyEvidenceFile $resourceErrorFile){throw 'Resource monitor emitted readiness error'}",
    )
    source = replace_once(
        source,
        "$deadline=[DateTime]::UtcNow.AddSeconds(3);$strictUtf8=New-Object Text.UTF8Encoding($false,$true)",
        "$deadline=[DateTime]::UtcNow.AddSeconds(3);$strictUtf8=New-Object Text.UTF8Encoding($false,$true);$writerSupplied=($null-ne$WriterProcess)",
    )
    source = replace_once(
        source,
        "if(-not(Test-Path -LiteralPath $Path)){if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};return ''}",
        "if(-not(Test-Path -LiteralPath $Path)){if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};return ''}",
    )
    source = replace_once(
        source,
        "catch [Text.DecoderFallbackException]{throw \"$Label log UTF-8 rejected\"}catch [IO.InvalidDataException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline-and$_.Exception.Message-clike'*incomplete framing*'){Start-Sleep -Milliseconds 10;continue};throw}catch [IO.IOException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}",
        "catch [Text.DecoderFallbackException]{throw \"$Label log UTF-8 rejected\"}catch [IO.InvalidDataException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline-and$_.Exception.Message-clike'*incomplete framing*'){Start-Sleep -Milliseconds 10;continue};throw}catch [IO.IOException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}",
    )
    source = replace_once(
        source,
        "if($LogBridgeSelfTest){",
        r"""if($ReadinessPredicateSelfTest){
    $auth=Get-AuthorizationState;$binding=Invoke-ReadinessPredicateRegression
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v31.readiness-predicate-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;binding=$binding;canonical_suite_executed=$false;shared_lock_used=$false;wsl_executed=$false}|ConvertTo-Json -Depth 8 -Compress));return
}
if($RetainedV30SnapshotSelfTest){
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock present before retained v30 snapshot self-test'};$leaf=(Split-Path -Leaf $prefix)+'.';$existing=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($existing.Count-ne0){throw 'Fresh v31 artifact namespace is not empty before retained snapshot self-test'}
    $auth=Get-AuthorizationState;$replay=Invoke-RetainedV30SnapshotVerifier 'isolated_nonconsuming_preflight';if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock appeared during retained v30 snapshot self-test'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v31.retained-v30-snapshot-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;replay=$replay;canonical_suite_executed=$false;shared_lock_used=$false;claim_created=$false;v31_artifacts_created=$false}|ConvertTo-Json -Depth 8 -Compress));return
}
if($LogBridgeSelfTest){""",
    )

    invoke_inventory_anchor = (
        "function Invoke-Inventory([string]$OutputPath,[string]$OutputWsl){"
    )
    invoke_inventory_index = source.index(invoke_inventory_anchor)
    stop_watcher_index = source.index("function Stop-Watcher", invoke_inventory_index)
    inventory_region = source[invoke_inventory_index:stop_watcher_index]
    retained_function = r"""function Invoke-BoundedSafeStdinProcess([string]$FileName,[string[]]$Tokens,[string]$Payload,[string]$Context,[int]$DeadlineSeconds){
    $handle=Start-SafeStdinProcess $FileName $Tokens $Payload
    try{if(-not$handle.Process.WaitForExit($DeadlineSeconds*1000)){try{Stop-CanonicalProcess $handle}catch{};throw "$Context deadline exceeded: $DeadlineSeconds seconds"};if(-not$handle.OutTask.Wait(15000)-or-not$handle.ErrTask.Wait(15000)){throw "$Context stream drain deadline exceeded"};$stdout=$handle.OutTask.GetAwaiter().GetResult();$stderr=$handle.ErrTask.GetAwaiter().GetResult();if($handle.Process.ExitCode-ne0){throw "$Context failed with exit $($handle.Process.ExitCode): $stderr"};return [ordered]@{exit_code=$handle.Process.ExitCode;stdout=$stdout;stderr=$stderr}}finally{$handle.Process.Dispose()}
}
function Invoke-RetainedV30SnapshotVerifier([string]$Phase){
    $cfg=[ordered]@{root=$v30SnapshotRoot;expected=$v30StagingInventoryWsl;expected_size=847188;expected_sha256='b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb';phase=$Phase};$result=Invoke-BoundedSafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $cfg)) $retainedV30SnapshotVerifierSource "retained v30 snapshot $Phase" 180
    $lines=@($result.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($lines.Count-ne1-or$result.stderr.Length-ne0){throw "Retained v30 snapshot verifier output rejected: $Phase"};$row=$lines[0]|ConvertFrom-Json
    if($row.schema-cne'planora.muni-v31.retained-v30-snapshot-replay.v1'-or$row.status-cne'EXACT_RETAINED_V30_SNAPSHOT_REPLAY'-or$row.phase-cne$Phase-or$row.root-cne$v30SnapshotRoot-or$row.files-ne3146-or$row.directories-ne368-or$row.bytes-ne190900047-or$row.inventory_sha256-cne'b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb'-or-not[bool]$row.all_nlink_one){throw "Retained v30 snapshot replay semantics rejected: $Phase"};return $row
}
function Get-NonThrowingRetainedV30SnapshotReplay([string]$Phase){try{return [ordered]@{phase=$Phase;status='REPLAYED';evidence=(Invoke-RetainedV30SnapshotVerifier $Phase);errors=@()}}catch{return [ordered]@{phase=$Phase;status='REPLAY_ERRORS_RECORDED';evidence=$null;errors=@($_.Exception.Message)}}}

"""
    source = (
        source[:invoke_inventory_index]
        + inventory_region
        + retained_function
        + source[stop_watcher_index:]
    )

    source = replace_once(
        source,
        "$predecessorModel=Get-ValidatedCombinedPredecessorEvidence $true;if(@($predecessorModel.runtime.validated_pins).Count-ne25-or@($predecessorModel.contract.v29.sources.PSObject.Properties).Count-ne4-or@($predecessorModel.contract.v29.artifacts.PSObject.Properties).Count-ne11-or-not$predecessorModel.runtime.pass_absence.v28_receipt_absent-or-not$predecessorModel.runtime.pass_absence.v29_receipt_absent){throw 'Complete combined predecessor static model rejected'}",
        "Assert-LocalPin $successorBuilderPath ([long]$auth.authorization.successor_admission.builder.size) ([string]$auth.authorization.successor_admission.builder.sha256);Assert-LocalPin $admissionTestsPath ([long]$auth.authorization.successor_admission.tests.size) ([string]$auth.authorization.successor_admission.tests.sha256);$predecessorModel=Get-ValidatedCombinedPredecessorEvidence $true;if(@($predecessorModel.runtime.validated_pins).Count-ne41-or@($predecessorModel.contract.v30.sources.PSObject.Properties).Count-ne4-or@($predecessorModel.contract.v30.artifacts.PSObject.Properties).Count-ne12-or-not$predecessorModel.runtime.pass_absence.v28_receipt_absent-or-not$predecessorModel.runtime.pass_absence.v29_receipt_absent-or-not$predecessorModel.runtime.pass_absence.v30_receipt_absent){throw 'Complete combined predecessor static model rejected'};$readinessBinding=Invoke-ReadinessPredicateRegression",
    )
    source = replace_once(
        source,
        "predecessor_evidence_model='25_EXACT_IDENTITY_PINS_V28_V29_PLUS_DUAL_PASS_ABSENCE_VALIDATED';wsl_executed=$false",
        "predecessor_evidence_model='41_EXACT_IDENTITY_PINS_V28_V29_V30_PLUS_TRIPLE_PASS_ABSENCE_VALIDATED';powershell_readiness_binding=$readinessBinding;wsl_executed=$false",
    )
    source = replace_once(
        source,
        "$reserved=@($lockEvidenceFile,$lockReleaseFile,$stagingInventoryFile",
        "$reserved=@($retainedV30SnapshotCustodyFile,$retainedV30SnapshotTerminalCustodyFile,$lockEvidenceFile,$lockReleaseFile,$stagingInventoryFile",
    )
    source = replace_once(
        source,
        "Assert-LocalPin $successorBuilderPath 59115 'c33cafd5260b79365ce434c086cf4e31c4333c904480b7ae445f15970201cb25'\n    Assert-LocalPin $admissionTestsPath 17533 'a0f7cad0ff955827f061a5f6228a45e1f8b9c09b22fa378318f4aea3793c621e'",
        "Assert-LocalPin $successorBuilderPath ([long]$auth.authorization.successor_admission.builder.size) ([string]$auth.authorization.successor_admission.builder.sha256)\n    Assert-LocalPin $admissionTestsPath ([long]$auth.authorization.successor_admission.tests.size) ([string]$auth.authorization.successor_admission.tests.sha256)",
    )
    source = replace_once(
        source,
        "$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash=''",
        "$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash='';$retainedV30SnapshotCustodyHash='';$retainedV30SnapshotTerminalCustodyHash='';$retainedV30SnapshotCustodyPin=$null;$retainedV30SnapshotTerminalCustodyPin=$null;$retainedV30FinalReplay=$null;$retainedV30RejectionReplay=$null;$stagingExited=$false;$watcherReady=$false;$preInventoryStarted=$false;$resourceLaunchAttempted=$false;$canonicalLaunchAttempted=$false;$canonicalStarted=$false;$canonicalExited=$false",
    )

    lock_evidence_old = (
        "Write-NewUtf8 $lockEvidenceFile (([ordered]@{lock=$lockBody;"
        "lock_sha256=$lockHash;held_open=$true;same_handle_verified=$true;"
        "delete_on_close=$true;predecessor_custody_sha256=$predecessorCustodyHash;"
        "stale_archive_pin=$staleArchivePin;predecessor_evidence_sha256=$predecessorEvidenceHash}"
        "|ConvertTo-Json -Depth 12))"
    )
    lock_evidence_new = r"""$retainedV30Initial=Invoke-RetainedV30SnapshotVerifier 'initial_after_v31_lock';$retainedV30SnapshotCustody=[ordered]@{schema='planora.muni-v31.retained-v30-snapshot-custody.v1';status='EXACT_RETAINED_V30_SNAPSHOT_VALIDATED_WHILE_V31_LOCK_HELD';run_id=$runId;replay=$retainedV30Initial;source_inventory_pin=$predecessorEvidence.contract.v30.snapshot.inventory;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV30SnapshotCustodyFile ($retainedV30SnapshotCustody|ConvertTo-Json -Depth 12);$retainedV30SnapshotCustodyHash=Get-Sha256 $retainedV30SnapshotCustodyFile;$retainedV30SnapshotCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotCustodyFile
    Write-NewUtf8 $lockEvidenceFile (([ordered]@{lock=$lockBody;lock_sha256=$lockHash;held_open=$true;same_handle_verified=$true;delete_on_close=$true;predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=$retainedV30SnapshotCustodyHash;retained_v30_snapshot_custody_pin=$retainedV30SnapshotCustodyPin;stale_archive_pin=$staleArchivePin;predecessor_evidence_sha256=$predecessorEvidenceHash}|ConvertTo-Json -Depth 12))"""
    source = replace_once(source, lock_evidence_old, lock_evidence_new)

    source = replace_once(
        source,
        "$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
        "$plan['retained_v30_snapshot_custody']=[ordered]@{sha256=$retainedV30SnapshotCustodyHash;pin=$retainedV30SnapshotCustodyPin};$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
    )
    source = replace_once(
        source,
        "$preAcceptancePins=@($predecessorPins)+@(@($runnerPath",
        "$preAcceptancePins=@($predecessorPins)+@(@($runnerPath,$retainedV30SnapshotCustodyFile",
    )

    source = replace_once(
        source,
        "$stageResult=Invoke-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $stageCfg)) $stagingSource 'immutable snapshot staging'",
        "$stageResult=Invoke-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $stageCfg)) $stagingSource 'immutable snapshot staging';$stagingExited=$true",
    )
    source = replace_once(
        source,
        "$ready=Assert-WatcherLiveReady $watcher $stagingHash $stageSummary.files;break",
        "$ready=Assert-WatcherLiveReady $watcher $stagingHash $stageSummary.files;$watcherReady=$true;break",
    )
    source = replace_once(
        source,
        "$pre=Invoke-Inventory $preInventoryFile",
        "$preInventoryStarted=$true;$pre=Invoke-Inventory $preInventoryFile",
    )
    source = replace_once(
        source,
        "$resourceMonitor=Start-SafeStdinProcess $wsl",
        "$resourceLaunchAttempted=$true;$resourceMonitor=Start-SafeStdinProcess $wsl",
    )
    source = replace_once(
        source,
        "$executionHandle=Start-SafeLoggedProcess $wsl $canonical $stdoutFile $stderrFile",
        "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess $wsl $canonical $stdoutFile $stderrFile;$canonicalStarted=$true",
    )
    source = replace_once(
        source,
        "$execution=Complete-SafeLoggedProcess $executionHandle;$executionHandle=$null",
        "$execution=Complete-SafeLoggedProcess $executionHandle;$executionHandle=$null;$canonicalExited=$true",
    )

    protected_old = (
        "$protectedPins=@($preAcceptancePins)+@((Get-LocalEvidencePin $acceptanceFile),"
        "(Get-LocalEvidencePin $cleanupFile),(Get-LocalEvidencePin $watchCleanupFile))"
    )
    protected_new = r"""$retainedV30Terminal=Invoke-RetainedV30SnapshotVerifier 'post_cleanup_while_v31_lock_held_before_final_census';$retainedV30SnapshotTerminalCustody=[ordered]@{schema='planora.muni-v31.retained-v30-snapshot-terminal-custody.v1';status='EXACT_RETAINED_V30_SNAPSHOT_REPLAYED_AFTER_V31_CLEANUP_WHILE_LOCK_HELD';run_id=$runId;initial_custody_sha256=$retainedV30SnapshotCustodyHash;replay=$retainedV30Terminal;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV30SnapshotTerminalCustodyFile ($retainedV30SnapshotTerminalCustody|ConvertTo-Json -Depth 12);$retainedV30SnapshotTerminalCustodyHash=Get-Sha256 $retainedV30SnapshotTerminalCustodyFile;$retainedV30SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotTerminalCustodyFile
    $protectedPins=@($preAcceptancePins)+@((Get-LocalEvidencePin $acceptanceFile),(Get-LocalEvidencePin $cleanupFile),(Get-LocalEvidencePin $watchCleanupFile),$retainedV30SnapshotTerminalCustodyPin)"""
    source = replace_once(source, protected_old, protected_new)

    source = replace_once(
        source,
        "$receipt['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
        "$receipt['retained_v30_snapshot_custody_sha256']=$retainedV30SnapshotCustodyHash;$receipt['retained_v30_snapshot_terminal_custody_sha256']=$retainedV30SnapshotTerminalCustodyHash;$receipt['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
    )
    source = replace_once(
        source,
        "$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard $staleArchivePin 'terminal_before_create_only_final_pass_seal'",
        "$retainedV30FinalReplay=Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard $staleArchivePin 'terminal_before_create_only_final_pass_seal'",
    )
    source = replace_once(
        source,
        "predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=",
        "predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=$retainedV30SnapshotCustodyHash;retained_v30_snapshot_terminal_custody_sha256=$retainedV30SnapshotTerminalCustodyHash;retained_v30_snapshot_final_replay=$retainedV30FinalReplay;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=",
    )

    lifecycle = "[ordered]@{staging_exited=$stagingExited;watcher_ready=$watcherReady;preinventory_started=$preInventoryStarted;resource_launch_attempted=$resourceLaunchAttempted;canonical_launch_attempted=$canonicalLaunchAttempted;canonical_started=$canonicalStarted;canonical_exited=$canonicalExited;retained_v30_initial_custody_published=($null-ne$retainedV30SnapshotCustodyPin);retained_v30_post_cleanup_custody_published=($null-ne$retainedV30SnapshotTerminalCustodyPin);retained_v30_final_replay_completed=($null-ne$retainedV30FinalReplay)}"
    source = replace_once(
        source,
        "$predecessorRejectionReplay=$null;try{",
        "$retainedV30RejectionReplay=Get-NonThrowingRetainedV30SnapshotReplay 'rejection_before_optional_v31_lock_release';$predecessorRejectionReplay=$null;try{",
    )
    source = replace_once(
        source,
        "failure=$failure;claim_publication_started=$claimPublicationStarted",
        f"failure=$failure;lifecycle={lifecycle};claim_publication_started=$claimPublicationStarted",
    )
    source = replace_once(
        source,
        "predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;snapshot_root=$root",
        "predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=$retainedV30SnapshotCustodyHash;retained_v30_snapshot_custody_pin=$retainedV30SnapshotCustodyPin;retained_v30_snapshot_terminal_custody_sha256=$retainedV30SnapshotTerminalCustodyHash;retained_v30_snapshot_terminal_custody_pin=$retainedV30SnapshotTerminalCustodyPin;retained_v30_snapshot_final_replay=$retainedV30FinalReplay;retained_v30_snapshot_rejection_replay=$retainedV30RejectionReplay;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;snapshot_root=$root",
    )
    source = replace_once(
        source,
        "original_failure=$failure;predecessor_evidence=$predecessorEvidence",
        f"original_failure=$failure;lifecycle={lifecycle};predecessor_evidence=$predecessorEvidence",
    )
    source = replace_once(
        source,
        "predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;recorded_at_utc=",
        "predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=$retainedV30SnapshotCustodyHash;retained_v30_snapshot_custody_pin=$retainedV30SnapshotCustodyPin;retained_v30_snapshot_terminal_custody_sha256=$retainedV30SnapshotTerminalCustodyHash;retained_v30_snapshot_terminal_custody_pin=$retainedV30SnapshotTerminalCustodyPin;retained_v30_snapshot_final_replay=$retainedV30FinalReplay;retained_v30_snapshot_rejection_replay=$retainedV30RejectionReplay;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;recorded_at_utc=",
    )

    source = source.replace("ConvertTo-Json -Depth 42", "ConvertTo-Json -Depth 70")
    source = source.replace(
        "$plan|ConvertTo-Json -Depth 15", "$plan|ConvertTo-Json -Depth 70"
    )
    source = source.replace(
        "$receipt|ConvertTo-Json -Depth 22", "$receipt|ConvertTo-Json -Depth 70"
    )
    source = source.replace(
        "$seal|ConvertTo-Json -Depth 22", "$seal|ConvertTo-Json -Depth 70"
    )
    source = source.replace(
        "$predecessorEvidence|ConvertTo-Json -Depth 18",
        "$predecessorEvidence|ConvertTo-Json -Depth 70",
    )
    source = source.replace(
        "$rejectEvidence|ConvertTo-Json -Depth 22",
        "$rejectEvidence|ConvertTo-Json -Depth 70",
    )
    source = source.replace(
        "$emergency|ConvertTo-Json -Depth 22", "$emergency|ConvertTo-Json -Depth 70"
    )

    required = (
        "planora.muni-v31.complete-v28-v29-v30-predecessor-evidence.v1",
        "Test-NonEmptyEvidenceFile $watchErrorFile",
        "Test-NonEmptyEvidenceFile $resourceErrorFile",
        "Invoke-ReadinessPredicateRegression",
        "if($ReadinessPredicateSelfTest){",
        "if($RetainedV30SnapshotSelfTest){",
        "$writerSupplied=($null-ne$WriterProcess)",
        "Invoke-RetainedV30SnapshotVerifier 'initial_after_v31_lock'",
        "Invoke-RetainedV30SnapshotVerifier 'post_cleanup_while_v31_lock_held_before_final_census'",
        "Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal'",
        "$predecessorPins.Count-ne41",
        "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream",
    )
    for marker in required:
        if marker not in source:
            raise RuntimeError(f"v31 required marker missing: {marker}")
    for forbidden in (
        "if(Test-Path -LiteralPath $watchErrorFile-and(Get-Item -LiteralPath $watchErrorFile).Length-ne0)",
        "if(Test-Path -LiteralPath $resourceErrorFile-and(Get-Item -LiteralPath $resourceErrorFile).Length-ne0)",
        "/tmp/planora-muni-v30-canonical-tests-'\nif not root.startswith(prefix)",
    ):
        if forbidden in source:
            raise RuntimeError(f"v31 forbidden marker survived: {forbidden}")
    if "prefix='/tmp/planora-muni-v31-canonical-tests-'" not in source:
        raise RuntimeError("v31 cleanup prefix missing")
    for expected in [*V30_SOURCES.values(), *V30_ARTIFACTS.values(), ARCHIVE_PIN]:
        if expected["path"] not in source:
            raise RuntimeError(f"v30 predecessor path not embedded: {expected['path']}")
    if PREDECESSOR_CONTRACT["v30"]["snapshot"]["root"] not in source:
        raise RuntimeError("retained v30 snapshot root not embedded")
    return source


def token_stream(value: str) -> str:
    return json.dumps(json.loads(value), separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    builder = Path(__file__)
    builder_size = builder.stat().st_size
    builder_hash = sha256(builder)
    tests_size = V31_TESTS.stat().st_size
    tests_hash = sha256(V31_TESTS)
    runner = render_runner(builder_size, builder_hash, tests_size, tests_hash)
    V31_RUNNER.write_text(runner, encoding="utf-8", newline="\n")
    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V31_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=120,
    )
    if result.returncode != 0 or result.stderr:
        raise RuntimeError(
            f"authorization emission failed: code={result.returncode} stderr={result.stderr}"
        )
    authorization = result.stdout.strip()
    json.loads(authorization)
    V31_AUTH.write_text(authorization + "\n", encoding="utf-8", newline="\n")
    replay = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V31_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=120,
    )
    if replay.stderr or token_stream(replay.stdout) != token_stream(
        V31_AUTH.read_text(encoding="utf-8")
    ):
        raise RuntimeError("v31 authorization deterministic replay rejected")
    print(
        json.dumps(
            {
                "status": "MUNI_V31_SUCCESSOR_GENERATED_STATIC_ONLY",
                "run_id": RUN_ID,
                "builder": {"size": builder_size, "sha256": builder_hash},
                "tests": {"size": tests_size, "sha256": tests_hash},
                "runner": {
                    "size": V31_RUNNER.stat().st_size,
                    "sha256": sha256(V31_RUNNER),
                },
                "authorization": {
                    "size": V31_AUTH.stat().st_size,
                    "sha256": sha256(V31_AUTH),
                },
                "wsl_executed": False,
                "log_bridge_executed": False,
                "readiness_self_test_executed": False,
                "retained_snapshot_verifier_executed": False,
                "canonical_suite_executed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
