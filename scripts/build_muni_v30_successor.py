from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
V29_RUN_ID = "ca79220da7db46b6996fe1f05785dde7"
RUN_ID = "e358bc6417224fe6a329ad3775853f01"
CREATED_AT = "2026-08-28T10:14:48Z"
V29_RUNNER = REPO / "scripts/run_muni_v29_canonical_tests.ps1"
V30_RUNNER = REPO / "scripts/run_muni_v30_canonical_tests.ps1"
V30_TESTS = REPO / "tests/test_run_muni_v30_successor.py"
V30_AUTH = (
    REPO
    / "output/diagnostic-receipts/muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z.receipt.json"
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


V29_SOURCES = {
    "builder": pin(
        "scripts/build_muni_v29_successor.py",
        65_112,
        "ec1cf8b79dc57d322f7f79a359bf378471a311122e40c92b7da3c7407d241208",
        "00000000000000000009000000172458",
        639235075700468377,
    ),
    "runner": pin(
        "scripts/run_muni_v29_canonical_tests.ps1",
        206_139,
        "c6dab5988cdd8f0a41061ab8d2fd6a7f33a68fe40b4e52815b846ce4fefa93b2",
        "0000000000000000000900000017245e",
        639235077051249998,
    ),
    "tests": pin(
        "tests/test_run_muni_v29_successor.py",
        14_889,
        "4bbb2726b7d0adb4751423e153421ff3b8707482e5dbc92790e7919440446705",
        "00000000000000000009000000172459",
        639235075402265092,
    ),
    "authorization": pin(
        "output/diagnostic-receipts/muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json",
        14_101,
        "dfc87e6f55f0c19c308ecc0a2b7effd9341ceaf9eadac034f09ca56773375233",
        "0000000000000000000c00000017245b",
        639235077058307759,
    ),
}

V29_PREFIX = (
    f"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-{V29_RUN_ID}"
)
V29_ARTIFACTS = {
    "claim": pin(
        f"{V29_PREFIX}.claim.json",
        541,
        "8d9118d11fbb2b43dee08962abaab995782331fd2d289473e7df9d794e39d9aa",
        "0000000000000000000b00000017263f",
        639235086848838432,
    ),
    "heavy_lock_release": pin(
        f"{V29_PREFIX}.heavy-lock-release.json",
        460,
        "0e01c49c6dfd34c13209ef40cd166d07ebefd4b22cedcd80de68f88f37af6a26",
        "0000000000000000000a000000172642",
        639235086944440014,
    ),
    "heavy_lock": pin(
        f"{V29_PREFIX}.heavy-lock.json",
        1_642,
        "ec27396012ef78c235931ef356f9f95a429fef75a4e7096a55bcaabf2ffaf503",
        "00000000000000000009000000172643",
        639235086875573576,
    ),
    "watch_error": pin(
        f"{V29_PREFIX}.mutation-watch.error.log",
        129,
        "8db6fba9adec989417d4f452bfab33911d83f66377347d0661d9035dfc6e4dec",
        "0000000000000000000a000000172645",
        639235086936166608,
    ),
    "watch_log": pin(
        f"{V29_PREFIX}.mutation-watch.jsonl",
        239,
        "e72977bad3da18e17202b3f1c0ea9f537145f7b9f36486c9ea97d44d70bde290",
        "0000000000000000000a000000172644",
        639235086935127141,
    ),
    "watch_stop": pin(
        f"{V29_PREFIX}.mutation-watch.stop",
        146,
        "2eaeae4e1f591219a4cdc93429ae695fb0f8e03e7e17625dc623d873545bc071",
        "0000000000000000000b000000172646",
        639235086935744482,
    ),
    "watch_wrapper_stderr": pin(
        f"{V29_PREFIX}.mutation-watch.wrapper.stderr.log",
        168,
        "ef92522da12d329a46fcd93e2aee0dbf0fde00be6a9d11e714cc0531bae71a4f",
        "0000000000000000000a000000172648",
        639235086936643843,
    ),
    "watch_wrapper_stdout": pin(
        f"{V29_PREFIX}.mutation-watch.wrapper.stdout.log",
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "00000000000000000008000000172647",
        639235086936623289,
    ),
    "rejection": pin(
        f"{V29_PREFIX}.rejection.json",
        15_496,
        "8d41c0131c3f7faf34591943acd11e41215e8fe511ddb0c8cab9c4466120856b",
        "00000000000000000008000000172649",
        639235086944311433,
    ),
    "stale_lock_reconciliation": pin(
        f"{V29_PREFIX}.stale-lock-reconciliation.json",
        26_456,
        "009735b8f561a24509b758d9026f5cd96d8e30b1b3a3e89ecd1513e432e89c7a",
        "0000000000000000000a000000172641",
        639235086873841528,
    ),
    "static_evidence": pin(
        f"{V29_PREFIX}.static-adversarial.json",
        2_875,
        "34c39b634835a746b479ee569126044fde2f3656f4f9e3d3761b7b84a4bf26bb",
        "0000000000000000000a000000172640",
        639235086870151804,
    ),
}

ARCHIVE_PIN = pin(
    "output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json",
    370,
    "dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98",
    "0000000000000000000c000000172456",
    639235031172129106,
)

PREDECESSOR_CONTRACT = {
    "schema": "planora.muni-v30.v28-v29-predecessor-custody-contract.v1",
    "v28": {
        "carrier": V29_ARTIFACTS["rejection"],
        "embedded_evidence_schema": "planora.muni-v29.complete-v28-predecessor-evidence.v1",
        "embedded_evidence_sha256": "1f4dca36e66fb41be3c39ed4d559106e278e1263e86b170fb9609701666923e6",
        "reconciliation_sha256": V29_ARTIFACTS["stale_lock_reconciliation"]["sha256"],
        "archive": ARCHIVE_PIN,
        "pass_receipt": "output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json",
        "pass_seal": "output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json",
    },
    "v29": {
        "run_id": V29_RUN_ID,
        "sources": V29_SOURCES,
        "artifacts": V29_ARTIFACTS,
        "failure": {
            "status": "REJECTED_AUTHORIZATION_CONSUMED",
            "phase": "before_staging_and_before_canonical_launch",
            "primary_root_cause": "host_ReadAllText_sharing_violation_against_lifetime_open_WSL_mutation_log",
            "secondary_failure": "abort_control_caused_watcher_stopped_before_staging_completed",
            "canonical_suite_executed": False,
            "automatic_retry_authorized": False,
        },
        "pass_receipt": f"{V29_PREFIX}.receipt.json",
        "pass_seal": f"{V29_PREFIX}.pass-publication-shutdown-seal.json",
    },
    "shared_lock": "output/diagnostic-receipts/planora-shared-heavy-wsl.lock",
    "required_pre_acquisition_state": "archive_exact_shared_lock_absent_v28_v29_pass_absent",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"anchor count {count}, expected 1: {old[:140]!r}")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"start anchor missing: {start[:140]!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end anchor missing: {end[:140]!r}")
    return text[:start_index] + replacement + text[end_index:]


def assert_pin(expected: dict[str, Any]) -> None:
    path = REPO / expected["path"]
    if path.stat().st_size != expected["size"] or sha256(path) != expected["sha256"]:
        raise RuntimeError(f"pinned predecessor drift: {path}")
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
        raise RuntimeError(f"pinned predecessor identity drift: {path}")


def ps_contract_json() -> str:
    return json.dumps(PREDECESSOR_CONTRACT, separators=(",", ":"), sort_keys=False)


def render_authorization_function(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    return f"""function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){{
    $closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json
    $o=[ordered]@{{
        schema='planora.itc2019.canonical-test-authorization.v10';created_at_utc='{CREATED_AT}';instance='muni-fspsx-fal17';candidate='muni_v30';test_id=$runId
        decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V29_PRECANONICAL_LOG_FAILURE';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false
        runner=[ordered]@{{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash}}
        successor_admission=[ordered]@{{builder=[ordered]@{{path='scripts/build_muni_v30_successor.py';size={builder_size};sha256='{builder_hash}'}};tests=[ordered]@{{path='tests/test_run_muni_v30_successor.py';size={tests_size};sha256='{tests_hash}'}}}}
        predecessor_custody_contract=$predecessor
        snapshot_closure=$closure
        log_bridge_contract=[ordered]@{{writer='create_only_reserve_close_then_identity_checked_short_lived_append_fsync';reader='bounded_explicit_FileStream_stable_identity_length_terminal_LF_UTF8_JSON';watcher_and_resource_monitor_both_fixed=$true;legacy_lifetime_open_negative_baseline_required=$true;isolated_switch='LogBridgeSelfTest';canonical_suite_executed_by_bridge_test=$false}}
        heavy_gate=[ordered]@{{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;continuous_monitor='target_100ms_with_authenticated_monotonic_sequence_and_750ms_maximum_gap';census='fail_closed_allow_live_proven_ancestry_or_previously_frozen_descendant_identity_in_exact_launch_namespace_plus_minimal_infrastructure_reject_hostile_siblings';target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval';pinned_subprocess_sites=16;descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'}}
        launch_contract=[ordered]@{{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';watcher_lifetime='ARMED_before_staging_lossless_events_through_final_census_same_handle_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown';staged_identity='device_inode_nlink_mode_size_sha256_frozen_and_replayed';host_root=$root;explicit_snapshot_ro_bind='/snapshot';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;environment_cleared=$true;capabilities_dropped=$true;gnu_timeout=[ordered]@{{term_seconds=600;kill_after_seconds=15}};host_wsl_deadline_seconds=$hostDeadlineSeconds;canonical_execute_sites=1}}
        canonical_contract=[ordered]@{{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';strict_stderr_grammar=$true;exact_skip_identities=[ordered]@{{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}}}}
        evidence_contract=[ordered]@{{atomic_claim='claim_attempt_marked_before_CreateNew_inside_outer_rejection_try_default_fail_closed_claim_v2_before_preflight';any_failure_consumes_authorization=$true;complete_v28_v29_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true;all_predecessor_file_ids_and_timestamps_authorized=$true;predecessor_pins_in_protected_replay_sets=$true;v28_v29_pass_absence_replayed_through_final_pass_seal_publication=$true;retained_archive_validated_in_place_without_mutation=$true;terminal_archived_lock_identity_replay_bound_by_final_pass_seal=$true;terminal_archived_lock_read_guard_held_through_final_pass_seal_flush=$true;final_pass_seal_create_only_durable_last_operation=$true;new_lock_verified_only_through_held_handle=$true;new_lock_release='same_handle_stable_bytes_then_DeleteOnClose';all_file_nlinks_and_device_inode_retained=$true;exact_staged_file_and_directory_set=$true;plan_and_receipt_bind_runner_authorization_snapshot_predecessor_and_custody=$true;pass_receipt_requires_post_publication_authenticated_watcher_shutdown_seal=$true;watcher_active_through_pass_publication=$true;claim_constructor_write_flush_and_immediate_failures_require_durable_rejection=$true;emergency_rejection_fallback_create_only=$true}}
    }}
    return($o|ConvertTo-Json -Depth 40 -Compress)
}}

"""


APPEND_PROTOCOL = r"""def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserved log identity rejected')
 return (s.st_dev,s.st_ino)
def append_bytes(path,identity,payload):
 deadline=time.monotonic()+2.0
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(0.01);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity: raise RuntimeError('append log identity rejected')
   offset=0
   while offset<len(payload):
    written=os.write(fd,payload[offset:])
    if written<=0: raise RuntimeError('append log short write')
    offset+=written
   os.fsync(fd);after=os.fstat(fd);linked_after=os.lstat(path)
   if not stat.S_ISREG(after.st_mode) or after.st_nlink!=1 or (after.st_dev,after.st_ino)!=identity or (linked_after.st_dev,linked_after.st_ino)!=identity: raise RuntimeError('append log identity drift')
   return
  finally: os.close(fd)
def publish_error(payload): append_bytes(error_path,error_identity,payload.encode())
"""


def render_runner(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    for expected in [*V29_SOURCES.values(), *V29_ARTIFACTS.values(), ARCHIVE_PIN]:
        assert_pin(expected)
    source = V29_RUNNER.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization)",
        "param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization,[switch]$LogBridgeSelfTest)",
    )
    for old, new in (
        (V29_RUN_ID, RUN_ID),
        (
            "scripts/run_muni_v29_canonical_tests.ps1",
            "scripts/run_muni_v30_canonical_tests.ps1",
        ),
        (
            "scripts\\run_muni_v29_canonical_tests.ps1",
            "scripts\\run_muni_v30_canonical_tests.ps1",
        ),
        ("scripts/build_muni_v29_successor.py", "scripts/build_muni_v30_successor.py"),
        (
            "scripts\\build_muni_v29_successor.py",
            "scripts\\build_muni_v30_successor.py",
        ),
        (
            "tests/test_run_muni_v29_successor.py",
            "tests/test_run_muni_v30_successor.py",
        ),
        (
            "tests\\test_run_muni_v29_successor.py",
            "tests\\test_run_muni_v30_successor.py",
        ),
        (
            "muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z",
            "muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z",
        ),
        (
            "muni-fspsx-v29-canonical-readonly-tests-",
            "muni-fspsx-v30-canonical-readonly-tests-",
        ),
        ("planora-muni-v29-canonical-tests-", "planora-muni-v30-canonical-tests-"),
        ("planora.muni-v29.", "planora.muni-v30."),
        ("candidate='muni_v29'", "candidate='muni_v30'"),
    ):
        source = source.replace(old, new)
    source = replace_once(
        source,
        "prefix='/tmp/planora-muni-v28-canonical-tests-'",
        "prefix='/tmp/planora-muni-v30-canonical-tests-'",
    )

    top_start = (
        "$successorBuilderPath = Join-Path $repo 'scripts\\build_muni_v30_successor.py'"
    )
    top_end = "$utf8 = New-Object System.Text.UTF8Encoding($false)"
    top = f"""$successorBuilderPath = Join-Path $repo 'scripts\\build_muni_v30_successor.py'
$admissionTestsPath = Join-Path $repo 'tests\\test_run_muni_v30_successor.py'
$v28ReceiptPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json'
$v28PassSealPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json'
$v29ReceiptPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v29-canonical-readonly-tests-{V29_RUN_ID}.receipt.json'
$v29PassSealPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v29-canonical-readonly-tests-{V29_RUN_ID}.pass-publication-shutdown-seal.json'
$v29RejectionPath = Join-Path $repo 'output\\diagnostic-receipts\\muni-fspsx-v29-canonical-readonly-tests-{V29_RUN_ID}.rejection.json'
$staleArchiveRelative = '{ARCHIVE_PIN["path"]}'
$staleArchivePath = Join-Path $repo '{ARCHIVE_PIN["path"].replace("/", chr(92))}'
$predecessorCustodyFile = "$prefix.predecessor-custody.json"
$predecessorContractJson = @'
{ps_contract_json()}
'@
"""
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

    watcher_init = (
        "log=open(log_path,'x',encoding='utf-8',buffering=1);"
        "error=open(error_path,'x',encoding='utf-8',buffering=1)\n"
        "def encode(row): return (json.dumps(row,sort_keys=True,separators=(',',':'))+'\\n').encode()\n"
        "def emit(row): log.buffer.write(encode(row));log.flush();os.fsync(log.fileno())"
    )
    watcher_new = (
        "log_identity=reserve(log_path);error_identity=reserve(error_path)\n"
        "def encode(row): return (json.dumps(row,sort_keys=True,separators=(',',':'))+'\\n').encode()\n"
        "def emit(row): append_bytes(log_path,log_identity,encode(row))"
    )
    source = source.replace(
        "import ctypes,hashlib,json,os,select,stat,struct,sys,time,traceback",
        "import ctypes,errno,hashlib,json,os,select,stat,struct,sys,time,traceback",
        1,
    )
    watcher_anchor = "def encode(row): return (json.dumps(row,sort_keys=True,separators=(',',':'))+'\\n').encode()"
    source = replace_once(
        source,
        watcher_init,
        APPEND_PROTOCOL + watcher_new,
    )
    legacy_tail = "except BaseException:\n error.write(traceback.format_exc());error.flush();os.fsync(error.fileno());raise\nfinally:\n log.close();error.close()"
    if source.count(legacy_tail) != 2:
        raise RuntimeError("watcher/resource legacy tail cardinality rejected")
    source = source.replace(
        legacy_tail,
        "except BaseException:\n publish_error(traceback.format_exc());raise",
        1,
    )

    resource_init = (
        "log=open(log_path,'x',encoding='utf-8',buffering=1);"
        "error=open(error_path,'x',encoding='utf-8',buffering=1)\n"
        "def emit(row): log.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\\n');log.flush();os.fsync(log.fileno())"
    )
    resource_new = (
        "log_identity=reserve(log_path);error_identity=reserve(error_path)\n"
        "def emit(row): append_bytes(log_path,log_identity,(json.dumps(row,sort_keys=True,separators=(',',':'))+'\\n').encode())"
    )
    source = source.replace(
        "import hashlib,json,os,stat,sys,time,traceback",
        "import errno,hashlib,json,os,stat,sys,time,traceback",
        1,
    )
    source = replace_once(source, resource_init, APPEND_PROTOCOL + resource_new)
    source = replace_once(
        source,
        legacy_tail,
        "except BaseException:\n publish_error(traceback.format_exc());raise",
    )

    stable_reader = r"""if(-not('PlanoraV30NativeFileIdentity'-as[type])){
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
[StructLayout(LayoutKind.Sequential)]
public struct PlanoraV30FileInformation {
 public uint FileAttributes;
 public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
 public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
 public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
 public uint VolumeSerialNumber;
 public uint FileSizeHigh;
 public uint FileSizeLow;
 public uint NumberOfLinks;
 public uint FileIndexHigh;
 public uint FileIndexLow;
}
public static class PlanoraV30NativeFileIdentity {
 [DllImport("kernel32.dll", SetLastError=true)]
 public static extern bool GetFileInformationByHandle(SafeFileHandle handle, out PlanoraV30FileInformation information);
}
"@
}
function Get-HeldFileIdentity([IO.FileStream]$Stream,[string]$Label){
    $information=New-Object PlanoraV30FileInformation;if(-not[PlanoraV30NativeFileIdentity]::GetFileInformationByHandle($Stream.SafeFileHandle,[ref]$information)){$code=[Runtime.InteropServices.Marshal]::GetLastWin32Error();throw [IO.IOException]::new("$Label GetFileInformationByHandle failed: $code")}
    $index=([uint64]$information.FileIndexHigh*4294967296)+[uint64]$information.FileIndexLow;$size=([uint64]$information.FileSizeHigh*4294967296)+[uint64]$information.FileSizeLow
    if(($information.FileAttributes-band0x10)-ne0-or($information.FileAttributes-band0x400)-ne0-or$information.NumberOfLinks-ne1){throw [IO.InvalidDataException]::new("$Label handle type, reparse, or nlink rejected")}
    return [ordered]@{volume=[uint32]$information.VolumeSerialNumber;index=$index;size=$size;links=[uint32]$information.NumberOfLinks}
}
function Test-WriterProcessLive([object]$WriterProcess){if($null-eq$WriterProcess){return $false};try{return(-not$WriterProcess.HasExited)}catch{return $false}}
function Read-StableUtf8Log([string]$Path,[string]$Label,[object]$WriterProcess){
    $deadline=[DateTime]::UtcNow.AddSeconds(3);$strictUtf8=New-Object Text.UTF8Encoding($false,$true)
    while($true){
        $wasLive=Test-WriterProcessLive $WriterProcess
        try{
            if(-not(Test-Path -LiteralPath $Path)){if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};return ''}
            $share=[IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete;$stream=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share)
            try{$before=Get-HeldFileIdentity $stream $Label;$length=$stream.Length;if($length-ne$before.size-or$length-gt[ int ]::MaxValue){throw [IO.InvalidDataException]::new("$Label log length rejected")};$bytes=New-Object byte[] ([int]$length);$offset=0;while($offset-lt$bytes.Length){$count=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($count-le0){throw [IO.IOException]::new("$Label log short read")};$offset+=$count};$after=Get-HeldFileIdentity $stream $Label;if($stream.Length-ne$length-or$after.volume-ne$before.volume-or$after.index-ne$before.index-or$after.size-ne$before.size){throw [IO.IOException]::new("$Label log identity or length drift during read")};$probe=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share);try{$pathIdentity=Get-HeldFileIdentity $probe ($Label+' path replay');if($pathIdentity.volume-ne$before.volume-or$pathIdentity.index-ne$before.index){throw [IO.IOException]::new("$Label log path identity drift")}}finally{$probe.Dispose()}}finally{$stream.Dispose()}
            $raw=$strictUtf8.GetString($bytes);if($raw.Length-ne0-and($raw.Contains("`r")-or-not$raw.EndsWith("`n",[StringComparison]::Ordinal))){throw [IO.InvalidDataException]::new("$Label log incomplete framing")};return $raw
        }catch [Text.DecoderFallbackException]{throw "$Label log UTF-8 rejected"}catch [IO.InvalidDataException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline-and$_.Exception.Message-clike'*incomplete framing*'){Start-Sleep -Milliseconds 10;continue};throw}catch [IO.IOException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}
    }
}
"""
    source = replace_once(
        source,
        "function Get-WatcherLogState{\n    if(-not(Test-Path -LiteralPath $watchLogFile)){return [ordered]@{lines=@();rows=@()}}\n    $raw=[IO.File]::ReadAllText($watchLogFile,$utf8);if($raw.Length-eq0){return [ordered]@{lines=@();rows=@()}}",
        stable_reader
        + "function Get-WatcherLogState([object]$WriterProcess=$null){\n    $raw=Read-StableUtf8Log $watchLogFile 'Watcher' $WriterProcess;if($raw.Length-eq0){return [ordered]@{lines=@();rows=@()}}",
    )
    source = replace_once(
        source,
        "function Get-WatcherRows{return @((Get-WatcherLogState).rows)}",
        "function Get-WatcherRows([object]$WriterProcess=$null){return @((Get-WatcherLogState $WriterProcess).rows)}",
    )
    source = replace_once(
        source,
        ";$rows=@(Get-WatcherRows)\n    if($rows.Count-lt1",
        ";$rows=@(Get-WatcherRows $Watcher.Process)\n    if($rows.Count-lt1",
    )
    source = replace_once(
        source,
        "function Assert-WatcherHistory([string]$ExpectedInventoryHash,",
        "function Assert-WatcherHistory([object]$WriterProcess,[string]$ExpectedInventoryHash,",
    )
    source = replace_once(
        source,
        "$state=Get-WatcherLogState;$rows=@($state.rows)",
        "$state=Get-WatcherLogState $WriterProcess;$rows=@($state.rows)",
    )
    source = source.replace(
        "return (Assert-WatcherHistory $ExpectedInventoryHash",
        "return (Assert-WatcherHistory $Watcher.Process $ExpectedInventoryHash",
    )
    source = source.replace(
        "return Assert-WatcherHistory $ExpectedInventoryHash",
        "return Assert-WatcherHistory $Watcher.Process $ExpectedInventoryHash",
    )
    source = replace_once(
        source,
        "$summary=Assert-WatcherHistory $ExpectedInventoryHash",
        "$summary=Assert-WatcherHistory $null $ExpectedInventoryHash",
    )
    source = source.replace(
        "@(Get-WatcherRows);if($armedRows",
        "@(Get-WatcherRows $watcher.Process);if($armedRows",
    )
    source = source.replace(
        "$lines=@(Get-WatcherRows);if(@($lines",
        "$lines=@(Get-WatcherRows $watcher.Process);if(@($lines",
    )

    source = replace_once(
        source,
        "function Get-ResourceMonitorRows{\n    if(-not(Test-Path -LiteralPath $resourceLogFile)){return @()};$raw=[IO.File]::ReadAllText($resourceLogFile,$utf8)",
        "function Get-ResourceMonitorRows([object]$WriterProcess=$null){\n    $raw=Read-StableUtf8Log $resourceLogFile 'Resource monitor' $WriterProcess",
    )
    source = replace_once(
        source,
        "$rows=@(Get-ResourceMonitorRows);$cadence=Assert-ResourceCadenceRows $rows $false",
        "$rows=@(Get-ResourceMonitorRows $Monitor.Process);$cadence=Assert-ResourceCadenceRows $rows $false",
    )

    predecessor_functions = r"""function New-ExpectedCombinedPredecessorEvidence{
    $contract=$predecessorContractJson|ConvertFrom-Json
    return [ordered]@{schema='planora.muni-v30.complete-v28-v29-predecessor-evidence.v1';status='EXPECTED_UNVALIDATED';contract=$contract;v28_evidence=$null;v29_evidence=$null;runtime=[ordered]@{validation_phase='not_started';validated_pins=@();pass_absence=$null;shared_lock_absent=$null}}
}
function Assert-V28V29PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    if(-not$result.v28_receipt_absent-or-not$result.v28_seal_absent-or-not$result.v29_receipt_absent-or-not$result.v29_seal_absent){throw "v28/v29 PASS evidence unexpectedly exists: $Phase"};return $result
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
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw "Shared heavy lock unexpectedly present during archived-lock replay: $Phase"};$result['shared_lock_absence_required']=$RequireSharedLockAbsent;$result['shared_lock_absent']=(-not(Test-Path -LiteralPath $sharedLockPath));$result['predecessor_pass_absence']=Assert-V28V29PassEvidenceAbsent $Phase;return $result
}
function Open-TerminalArchivedStaleLockGuard([object]$ExpectedPin,[string]$Phase){
    $preGuardReplay=Assert-FinalArchivedStaleLockIdentity $ExpectedPin $Phase $true;$bytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}');$guard=$null
    try{$guard=New-Object IO.FileStream($staleArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);if([IO.Path]::GetFullPath($guard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){throw 'Terminal archived-lock guard path rejected'};[void](Assert-HeldStreamBytes $guard $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Terminal archived stale lock guard');[void](Assert-LocalEvidencePin $ExpectedPin);if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock unexpectedly present while terminal archive guard held'};$passAbsence=Assert-V28V29PassEvidenceAbsent ($Phase+'_guard_held');$evidence=[ordered]@{schema='planora.muni-v30.terminal-archived-lock-guard.v1';phase=$Phase;status='IDENTITY_REPLAYED_AND_READ_GUARD_HELD_THROUGH_FINAL_PASS_FLUSH';archive_pin=$ExpectedPin;pre_guard_replay=$preGuardReplay;guard_access='Read';guard_share='Read_only_blocks_write_and_delete';same_handle_bytes_replayed=$true;shared_lock_absent=$true;predecessor_pass_absence=$passAbsence;acquired_at_utc=[DateTime]::UtcNow.ToString('o')};return [pscustomobject]@{Stream=$guard;Evidence=$evidence}}catch{if($null-ne$guard){$guard.Dispose()};throw}
}
function Get-ValidatedCombinedPredecessorEvidence([bool]$RequireSharedLockAbsent){
    $e=New-ExpectedCombinedPredecessorEvidence;$c=$e.contract;$pins=@()
    foreach($group in @($c.v29.sources,$c.v29.artifacts)){foreach($property in $group.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}}
    $rejection=[IO.File]::ReadAllText($v29RejectionPath,$utf8)|ConvertFrom-Json;$claim=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.claim.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$release=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.heavy_lock_release.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$authorization=[IO.File]::ReadAllText((Join-Path $repo $c.v29.sources.authorization.path.Replace('/','\')),$utf8)|ConvertFrom-Json
    if($claim.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.failure_consumes_authorization){throw 'v29 claim semantics rejected'}
    if($rejection.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$rejection.status-cne'REJECTED_AUTHORIZATION_CONSUMED'-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$rejection.failure-cnotmatch'ReadAllText'-or$rejection.failure-cnotmatch'being used by another process'-or$rejection.failure-cnotmatch'watcher_stop=Watcher wrapper rejected'){throw 'v29 consumed failure semantics rejected'}
    if($release.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$release.decision-cne'REJECTED'-or-not[bool]$release.same_handle_verified-or-not[bool]$release.delete_on_close-or-not[bool]$release.lock_path_absent){throw 'v29 lock release semantics rejected'}
    if($authorization.test_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$authorization.candidate-cne'muni_v29'-or[bool]$authorization.automatic_retry_authorized-or$authorization.runner.sha256-cne$c.v29.sources.runner.sha256-or$authorization.successor_admission.builder.sha256-cne$c.v29.sources.builder.sha256-or$authorization.successor_admission.tests.sha256-cne$c.v29.sources.tests.sha256){throw 'v29 authorization binding rejected'}
    $watchRaw=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.watch_log.path.Replace('/','\')),$utf8);$watchRows=@($watchRaw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($watchRows.Count-ne1-or$watchRows[0].kind-cne'ARMED'-or-not$watchRows[0].root_absent){throw 'v29 pre-staging watcher evidence rejected'}
    if((Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_error.path.Replace('/','\'))).Length-eq0-or(Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_wrapper_stderr.path.Replace('/','\'))).Length-eq0-or(Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_wrapper_stdout.path.Replace('/','\'))).Length-ne0){throw 'v29 watcher terminal artifact shape rejected'}
    $embedded=$rejection.predecessor_v28_evidence;$embeddedJson=$embedded|ConvertTo-Json -Depth 35 -Compress;$embeddedHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream $embeddedJson)
    if($embedded.schema-cne$c.v28.embedded_evidence_schema-or$rejection.predecessor_v28_evidence_sha256-cne$c.v28.embedded_evidence_sha256-or$embedded.status-cne'VALIDATED_AFTER_STALE_LOCK_RECONCILIATION'-or$embedded.runtime.stale_lock_reconciliation_sha256-cne$c.v28.reconciliation_sha256){throw 'v28 carried predecessor evidence rejected'}
    foreach($property in $embedded.runtime.live_file_pins.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}
    if((ConvertTo-JsonTokenStream ($embedded.runtime.retained_lock_archive_pin|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.v28.archive|ConvertTo-Json -Depth 8 -Compress))){throw 'v28 carried archive identity rejected'}
    [void](Assert-FinalArchivedStaleLockIdentity $c.v28.archive 'combined_predecessor_validation' $RequireSharedLockAbsent);$pins+=,$c.v28.archive;$pass=Assert-V28V29PassEvidenceAbsent 'combined_predecessor_validation'
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw 'Shared lock present before v30 acquisition'}
    $e.status='VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY';$e.v28_evidence=$embedded;$e.v29_evidence=[ordered]@{run_id=$c.v29.run_id;authorization=$authorization;claim=$claim;rejection=$rejection;lock_release=$release;failure=$c.v29.failure};$e.runtime.validation_phase=$(if($RequireSharedLockAbsent){'before_v30_lock_acquisition'}else{'rejection_replay'});$e.runtime.validated_pins=$pins;$e.runtime.pass_absence=$pass;$e.runtime.shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));return $e
}
function Get-CombinedPredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY'){throw 'Combined predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCombinedPredecessorReplay([object]$Evidence,[object]$ArchivePin){try{$replayed=Get-ValidatedCombinedPredecessorEvidence $false;return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=$replayed;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$Evidence;errors=@($_.Exception.Message)}}}
"""
    source = replace_region(
        source,
        "function Assert-V28StaleLockRecord",
        "function Invoke-LockSelfReadRegressionModel",
        predecessor_functions,
    )
    stale_model = r"""function Invoke-StaleLockAdversarialModel{
    $contract=$predecessorContractJson|ConvertFrom-Json;[void](Assert-LocalEvidencePin $contract.v28.archive);$raw=[IO.File]::ReadAllText($staleArchivePath,$utf8)|ConvertFrom-Json
    if($raw.schema-cne'planora.shared-heavy-wsl-lock.v1'-or$raw.run_id-cne'e7cf1df162074402994a9d0ad763c824'-or$raw.authorization_sha256-cne'1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'-or$raw.runner_sha256-cne'fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60'-or$raw.owner_pid-ne1140){throw 'Retained v28 archive record rejected'}
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared lock unexpectedly present in archive model'};return [ordered]@{archive_exact_identity='PASS';archive_record='PASS';shared_lock_absent='PASS';archive_mutation_performed=$false}
}

"""
    source = replace_region(
        source,
        "function Invoke-StaleLockAdversarialModel",
        "function Release-HeavyLock",
        stale_model,
    )

    state_line_start = "$lockStream=$null;"
    state_line_end = "\ntry{\n"
    old_state_start = source.find(state_line_start, source.find("if($StaticSelfTest)"))
    old_state_end = source.find(state_line_end, old_state_start)
    if old_state_start < 0 or old_state_end < 0:
        raise RuntimeError("main state line not found")
    state = "$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash='';$staleArchivePin=$null;$predecessorEvidence=New-ExpectedCombinedPredecessorEvidence;$predecessorEvidenceHash='';$predecessorPins=@();$archiveReplayAtPass=$null;$archiveReplayBeforeFinalization=$null;$archiveReplayTerminal=$null;$terminalArchiveGuard=$null;$watcher=$null;$resourceMonitor=$null;$executionHandle=$null;$claimStream=$null;$claimPublicationStarted=$false;$claimCreateReturned=$false;$claimPublicationComplete=$false;$claimPublicationPhase='before_create';$snapshotCreated=$false;$snapshotDeleted=$false;$acceptanceHash='';$cleanupHash='';$decision='REJECTED';$runnerHash='';$authorizationHash=''"
    source = source[:old_state_start] + state + source[old_state_end:]

    source = source.replace("$staleReconciliationFile", "$predecessorCustodyFile")
    source = source.replace("$staleReconciliationHash", "$predecessorCustodyHash")
    source = source.replace(
        "stale_lock_reconciliation_sha256", "predecessor_custody_sha256"
    )
    source = source.replace("predecessor_v28_evidence", "predecessor_evidence")
    source = source.replace(
        "Get-NonThrowingV28RejectionReplay", "Get-NonThrowingCombinedPredecessorReplay"
    )
    source = replace_once(
        source,
        ",$predecessorCustodyFile,$staleArchivePath)",
        ",$predecessorCustodyFile)",
    )

    main_start = source.find(
        "    $auth=Get-AuthorizationState;", source.find("\ntry{\n", old_state_start)
    )
    main_end = source.find("\n\n    $sample1=", main_start)
    if main_start < 0 or main_end < 0:
        raise RuntimeError("main predecessor/lock block not found")
    main_block = f"""    $auth=Get-AuthorizationState;$runnerHash=$auth.runner_sha256;$authorizationHash=$auth.authorization_sha256
    Assert-LocalPin $successorBuilderPath {builder_size} '{builder_hash}'
    Assert-LocalPin $admissionTestsPath {tests_size} '{tests_hash}'
    $predecessorEvidence=Get-ValidatedCombinedPredecessorEvidence $true;$staleArchivePin=$predecessorEvidence.contract.v28.archive;$predecessorPins=@(Get-CombinedPredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne25){{throw 'Combined predecessor pin cardinality rejected'}}
    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress))
    $legacy=@(Get-LegacyRows);$static=Invoke-LocalStaticAdversarialChecks;$lockRegression=Invoke-LockSelfReadRegressionModel;$staleModel=Invoke-StaleLockAdversarialModel
    Write-NewUtf8 $staticEvidenceFile (([ordered]@{{run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;legacy_rows=$legacy.Count;checks=$static;lock_regression=$lockRegression;archived_predecessor_model=$staleModel;log_protocol='create_close_short_lived_identity_checked_append_plus_stable_host_reader'}}|ConvertTo-Json -Depth 12))
    $custody=[ordered]@{{schema='planora.muni-v30.predecessor-custody.v1';status='EXACT_V28_V29_CUSTODY_VALIDATED_BEFORE_V30_LOCK';run_id=$runId;predecessor_evidence=$predecessorEvidence;predecessor_evidence_sha256=$predecessorEvidenceHash;archive_identity_replay=(Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'before_predecessor_custody_publication' $true);shared_lock_absent=$true;created_at_utc=[DateTime]::UtcNow.ToString('o')}};Write-NewUtf8 $predecessorCustodyFile ($custody|ConvertTo-Json -Depth 42);$predecessorCustodyHash=Get-Sha256 $predecessorCustodyFile
    if(Test-Path -LiteralPath $sharedLockPath){{throw 'Shared lock appeared before v30 acquisition'}}
    $lockBody=[ordered]@{{schema='planora.shared-heavy-wsl-lock.v2';run_id=$runId;authorization_sha256=$authorizationHash;runner_sha256=$runnerHash;predecessor_custody_sha256=$predecessorCustodyHash;created_at_utc=[DateTime]::UtcNow.ToString('o');mechanism='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';owner_pid=$PID}}
    $lockBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress));$lockHash=Get-BytesSha256 $lockBytes
    $lockStream=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose)
    $lockStream.Write($lockBytes,0,$lockBytes.Length);$lockStream.Flush($true);[void](Assert-HeldLockPath $lockStream $lockBytes $lockHash)
    Write-NewUtf8 $lockEvidenceFile (([ordered]@{{lock=$lockBody;lock_sha256=$lockHash;held_open=$true;same_handle_verified=$true;delete_on_close=$true;predecessor_custody_sha256=$predecessorCustodyHash;stale_archive_pin=$staleArchivePin;predecessor_evidence_sha256=$predecessorEvidenceHash}}|ConvertTo-Json -Depth 12))"""
    source = source[:main_start] + main_block + source[main_end:]

    source = replace_once(
        source,
        "$plan['predecessor_evidence']=$predecessorEvidence;$plan['predecessor_evidence_sha256']=$predecessorEvidenceHash;$plan['stale_lock_reconciliation']=[ordered]@{sha256=$predecessorCustodyHash;archive_pin=$staleArchivePin};$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
        "$plan['predecessor_evidence']=$predecessorEvidence;$plan['predecessor_evidence_sha256']=$predecessorEvidenceHash;$plan['predecessor_custody']=[ordered]@{sha256=$predecessorCustodyHash;pin=(Get-LocalEvidencePin $predecessorCustodyFile);archive_pin=$staleArchivePin};$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'",
    )
    source = source.replace(
        "$archiveReplayAtPass.v28_pass_absence",
        "$archiveReplayAtPass.predecessor_pass_absence",
    )
    source = source.replace(
        "$receipt['predecessor_custody_sha256']=$predecessorCustodyHash;$receipt['stale_lock_archive_pin']",
        "$receipt['predecessor_custody_sha256']=$predecessorCustodyHash;$receipt['predecessor_custody_pin']=Get-LocalEvidencePin $predecessorCustodyFile;$receipt['stale_lock_archive_pin']",
    )
    source = source.replace(
        "schema='planora.muni-v30.overall-rejection.v5'",
        "schema='planora.muni-v30.overall-rejection.v6'",
    )
    source = source.replace(
        "schema='planora.muni-v30.emergency-rejection.v2'",
        "schema='planora.muni-v30.emergency-rejection.v3'",
    )
    recovery = 'if($null-eq$staleArchivePin-and(Test-Path -LiteralPath $staleArchivePath)-and$null-ne$predecessorEvidence.runtime.retained_lock_source_pin){try{$staleArchivePin=New-StaleArchivePinFromSource $predecessorEvidence.runtime.retained_lock_source_pin}catch{$failure+="; archived_pin_recovery=$($_.Exception.Message)"}};'
    source = source.replace(recovery, "")
    source = source.replace(
        "planora.muni-v30.complete-v28-predecessor-evidence.v1",
        "planora.muni-v30.complete-v28-v29-predecessor-evidence.v1",
    )

    bridge_sources = r"""
$legacyLogBridgeSource = @'
import json,os,sys,time
c=json.loads(__import__('base64').b64decode(sys.argv[1]));log=open(c['log'],'x',encoding='utf-8',buffering=1);log.write('{"kind":"LEGACY_OPEN"}\n');log.flush();os.fsync(log.fileno());fd=os.open(c['ready'],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
try:
 while not os.path.exists(c['stop']): time.sleep(0.01)
finally: log.close()
'@
$fixedLogBridgeSource = @'
import errno,hashlib,json,os,stat,sys,time
c=json.loads(__import__('base64').b64decode(sys.argv[1]));path=c['log']
def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserve rejected')
 return (s.st_dev,s.st_ino)
identity=reserve(path);encoded=[]
def emit(row):
 payload=(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode();deadline=time.monotonic()+2
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(.005);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity or before.st_nlink!=1: raise RuntimeError('identity rejected')
   offset=0
   while offset<len(payload):
    count=os.write(fd,payload[offset:]);offset+=count
   os.fsync(fd);after=os.fstat(fd)
   if (after.st_dev,after.st_ino)!=identity or after.st_nlink!=1: raise RuntimeError('identity drift')
  finally: os.close(fd)
  encoded.append(payload);return
emit({'kind':'READY','rows':12})
for sequence in range(1,13): emit({'kind':'SAMPLE','sequence':sequence,'payload':'bridge'});time.sleep(.4)
emit({'kind':'DONE','prior_sha256':hashlib.sha256(b''.join(encoded)).hexdigest(),'samples':12})
'@
"""
    source = replace_once(
        source, "$cleanupSource = @'", bridge_sources + "$cleanupSource = @'"
    )
    bridge_branch = r"""if($LogBridgeSelfTest){
    $auth=Get-AuthorizationState;$name='muni-v30-log-bridge-'+[Guid]::NewGuid().ToString('N');$dir=Join-Path $repo ('tmp\'+$name);$dirWsl=$repoWsl+'/tmp/'+$name
    if(-not(Test-Path -LiteralPath (Join-Path $repo 'tmp'))){[void](New-Item -ItemType Directory -Path (Join-Path $repo 'tmp'))};[void](New-Item -ItemType Directory -Path $dir)
    $legacy=$null;$fixed=$null;$legacyFailure=$false;$stableReads=0
    try{
        $legacyCfg=[ordered]@{log=$dirWsl+'/legacy.jsonl';ready=$dirWsl+'/legacy.ready';stop=$dirWsl+'/legacy.stop'};$legacy=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $legacyCfg)) $legacyLogBridgeSource;$deadline=[DateTime]::UtcNow.AddSeconds(10);while(-not(Test-Path -LiteralPath (Join-Path $dir 'legacy.ready'))-and[DateTime]::UtcNow-lt$deadline){if($legacy.Process.HasExited){throw 'Legacy bridge writer exited early'};Start-Sleep -Milliseconds 10};if(-not(Test-Path -LiteralPath (Join-Path $dir 'legacy.ready'))){throw 'Legacy bridge ready deadline'}
        try{[void][IO.File]::ReadAllText((Join-Path $dir 'legacy.jsonl'),$utf8)}catch [IO.IOException]{$legacyFailure=$true};if(-not$legacyFailure){throw 'Legacy lifetime-open DrvFS sharing failure was not reproduced'};Write-NewAscii (Join-Path $dir 'legacy.stop') "stop`n";if(-not$legacy.Process.WaitForExit(10000)){throw 'Legacy bridge stop deadline'};$legacyOut=$legacy.OutTask.GetAwaiter().GetResult();$legacyErr=$legacy.ErrTask.GetAwaiter().GetResult();if($legacy.Process.ExitCode-ne0-or$legacyOut.Length-ne0-or$legacyErr.Length-ne0){throw 'Legacy bridge wrapper rejected'};$legacy.Process.Dispose();$legacy=$null
        $fixedCfg=[ordered]@{log=$dirWsl+'/fixed.jsonl'};$fixed=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $fixedCfg)) $fixedLogBridgeSource;$raw='';while(-not$fixed.Process.HasExited){$raw=Read-StableUtf8Log (Join-Path $dir 'fixed.jsonl') 'Bridge fixed' $fixed.Process;if($raw.Length-ne0){$stableReads++};Start-Sleep -Milliseconds 2};if(-not$fixed.OutTask.Wait(10000)-or-not$fixed.ErrTask.Wait(10000)){throw 'Fixed bridge stream drain deadline'};$fixedOut=$fixed.OutTask.GetAwaiter().GetResult();$fixedErr=$fixed.ErrTask.GetAwaiter().GetResult();if($fixed.Process.ExitCode-ne0-or$fixedOut.Length-ne0-or$fixedErr.Length-ne0){throw 'Fixed bridge wrapper rejected'};$fixed.Process.Dispose();$fixed=$null;$raw=Read-StableUtf8Log (Join-Path $dir 'fixed.jsonl') 'Bridge fixed final' $null;$lines=@($raw.Substring(0,$raw.Length-1).Split("`n"));$rows=@($lines|ForEach-Object{$_|ConvertFrom-Json});if($rows.Count-ne14-or$rows[0].kind-cne'READY'-or$rows[-1].kind-cne'DONE'-or$rows[-1].samples-ne12){throw 'Fixed bridge row grammar rejected'};for($i=1;$i-le12;$i++){if($rows[$i].kind-cne'SAMPLE'-or$rows[$i].sequence-ne$i){throw 'Fixed bridge sequence rejected'}};$prior=($lines[0..12]|ForEach-Object{$_+"`n"})-join'';if((Get-Utf8StringSha256 $prior)-cne$rows[-1].prior_sha256){throw 'Fixed bridge digest rejected'}
        if($stableReads-lt3){throw 'Fixed bridge did not overlap at least three stable host reads'};[Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v30.log-bridge-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;legacy_lifetime_open_sharing_failure='REPRODUCED';short_lived_append_stable_reads=$stableReads;rows=$rows.Count;samples=12;duplicates=0;canonical_suite_executed=$false;shared_lock_used=$false}|ConvertTo-Json -Compress));return
    }finally{if($null-ne$legacy){try{$legacy.Process.Kill()}catch{};try{$legacy.Process.Dispose()}catch{}};if($null-ne$fixed){try{$fixed.Process.Kill()}catch{};try{$fixed.Process.Dispose()}catch{}};if(Test-Path -LiteralPath $dir){Remove-Item -LiteralPath $dir -Recurse -Force}}
}

"""
    source = replace_once(
        source, "if($StaticSelfTest){", bridge_branch + "if($StaticSelfTest){"
    )

    source = source.replace(
        "$predecessorModel=Get-ValidatedV28PredecessorEvidence;if($predecessorModel.authorized_files.Count-ne10-or$predecessorModel.runtime.live_file_pins.Count-ne9-or$predecessorModel.runtime.retained_lock_source_pin.sha256-cne'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98'-or-not$predecessorModel.runtime.pass_absence_before_reconciliation.receipt_absent-or-not$predecessorModel.runtime.pass_absence_before_reconciliation.shutdown_seal_absent){throw 'Complete predecessor static model rejected'}",
        "$predecessorModel=Get-ValidatedCombinedPredecessorEvidence $true;if(@($predecessorModel.runtime.validated_pins).Count-ne25-or@($predecessorModel.contract.v29.sources.PSObject.Properties).Count-ne4-or@($predecessorModel.contract.v29.artifacts.PSObject.Properties).Count-ne11-or-not$predecessorModel.runtime.pass_absence.v28_receipt_absent-or-not$predecessorModel.runtime.pass_absence.v29_receipt_absent){throw 'Complete combined predecessor static model rejected'}",
    )
    source = source.replace(
        "predecessor_evidence_model='10_AUTHORIZED_9_LIVE_PLUS_RETAINED_LOCK_AND_PASS_ABSENCE_VALIDATED'",
        "predecessor_evidence_model='25_EXACT_IDENTITY_PINS_V28_V29_PLUS_DUAL_PASS_ABSENCE_VALIDATED'",
    )
    source = source.replace(
        "stale_lock_model=$staleModel",
        "archived_predecessor_model=$staleModel",
    )
    source = source.replace(
        "'Get-NonThrowingCombinedPredecessorReplay','terminal_before_create_only_final_pass_seal'",
        "'Get-NonThrowingCombinedPredecessorReplay','complete-v28-v29-predecessor-evidence.v1','Read-StableUtf8Log','short_lived_append','LogBridgeSelfTest','terminal_before_create_only_final_pass_seal'",
    )
    source = source.replace(
        "complete_predecessor_evidence_binding='PASS'",
        "complete_predecessor_evidence_binding='PASS';cross_boundary_log_protocol='SHORT_LIVED_IDENTITY_CHECKED_APPEND_AND_STABLE_HOST_READ'",
    )
    source = replace_once(
        source,
        "predecessor_evidence_sha256=$predecessorEvidenceHash;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=",
        "predecessor_evidence_sha256=$predecessorEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=",
    )
    source = source.replace(
        "$embedded=$rejection.predecessor_evidence;",
        "$embedded=$rejection.predecessor_v28_evidence;",
    )
    source = source.replace(
        "$rejection.predecessor_evidence_sha256-cne$c.v28.embedded_evidence_sha256",
        "$rejection.predecessor_v28_evidence_sha256-cne$c.v28.embedded_evidence_sha256",
    )
    source = source.replace(
        "$embedded.runtime.predecessor_custody_sha256-cne$c.v28.reconciliation_sha256",
        "$embedded.runtime.stale_lock_reconciliation_sha256-cne$c.v28.reconciliation_sha256",
    )
    if "log=open(log_path,'x'" in source or "log.close();error.close()" in source:
        raise RuntimeError("lifetime-open writer survived v30 transformation")
    if (
        "Reconcile-PinnedV28StaleLock" in source
        or "[IO.File]::Move($sharedLockPath,$staleArchivePath)" in source
    ):
        raise RuntimeError("stale-lock mutation survived v30 transformation")
    return source


def token_stream(value: str) -> str:
    return json.dumps(json.loads(value), separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    builder = Path(__file__)
    builder_size = builder.stat().st_size
    builder_hash = sha256(builder)
    tests_size = V30_TESTS.stat().st_size
    tests_hash = sha256(V30_TESTS)
    runner = render_runner(builder_size, builder_hash, tests_size, tests_hash)
    V30_RUNNER.write_text(runner, encoding="utf-8", newline="\n")
    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V30_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=90,
    )
    if result.returncode != 0 or result.stderr:
        raise RuntimeError(
            f"authorization emission failed: code={result.returncode} stderr={result.stderr}"
        )
    authorization = result.stdout.strip()
    json.loads(authorization)
    V30_AUTH.write_text(authorization + "\n", encoding="utf-8", newline="\n")
    replay = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V30_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=90,
    )
    if replay.stderr or token_stream(replay.stdout) != token_stream(
        V30_AUTH.read_text(encoding="utf-8")
    ):
        raise RuntimeError("authorization deterministic replay rejected")
    print(
        json.dumps(
            {
                "status": "MUNI_V30_SUCCESSOR_GENERATED_STATIC_ONLY",
                "run_id": RUN_ID,
                "builder": {"size": builder_size, "sha256": builder_hash},
                "tests": {"size": tests_size, "sha256": tests_hash},
                "runner": {
                    "size": V30_RUNNER.stat().st_size,
                    "sha256": sha256(V30_RUNNER),
                },
                "authorization": {
                    "size": V30_AUTH.stat().st_size,
                    "sha256": sha256(V30_AUTH),
                },
                "wsl_executed": False,
                "log_bridge_executed": False,
                "canonical_suite_executed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
