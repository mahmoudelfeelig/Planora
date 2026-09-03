from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "5f2d84640f40404a82dd180d7043d9c5"
V30_RUN_ID = "e358bc6417224fe6a329ad3775853f01"
BUILDER = REPO / "scripts/build_muni_v31_successor.py"
RUNNER = REPO / "scripts/run_muni_v31_canonical_tests.ps1"
AUTH = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v31-canonical-tests-authorization-20260828T113225Z.receipt.json"
)
ARCHIVE = REPO / (
    "output/diagnostic-receipts/"
    "retained-stale-planora-shared-heavy-wsl-v28-"
    "e7cf1df162074402994a9d0ad763c824.lock.json"
)
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"
SAFE_SWITCHES = {
    "-EmitExpectedAuthorization",
    "-StaticSelfTest",
    "-ReadinessPredicateSelfTest",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("muni_v31_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ps_executables() -> list[Path]:
    ps5 = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    pwsh = shutil.which("pwsh")
    assert ps5.is_file(), "Windows PowerShell 5.1 is required"
    assert pwsh, "PowerShell 7 is required for the independent parser/runtime gate"
    return [ps5, Path(pwsh)]


def invoke_runner(executable: Path, switch: str) -> subprocess.CompletedProcess[str]:
    assert switch in SAFE_SWITCHES
    return subprocess.run(
        [
            str(executable),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUNNER),
            switch,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=180,
    )


def windows_pin(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["fsutil.exe", "file", "queryfileid", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"File ID is 0x([0-9a-fA-F]{32})", result.stdout)
    assert match
    return {
        "path": path,
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "file_id": match.group(1).lower(),
        "last_write_utc_ticks": (path.stat().st_mtime_ns // 100 + 621355968000000000),
    }


def direct_and_carried_pins(builder: ModuleType) -> list[dict[str, Any]]:
    rejection = json.loads(
        (REPO / builder.V30_ARTIFACTS["rejection"]["path"]).read_text(encoding="utf-8")
    )
    prior = rejection["predecessor_evidence"]["runtime"]["validated_pins"]
    direct = [*builder.V30_SOURCES.values(), *builder.V30_ARTIFACTS.values()]
    assert len(prior) == 25
    assert len(direct) == 16
    return [*prior, *direct]


def embedded_sources() -> dict[str, str]:
    source = RUNNER.read_text(encoding="utf-8")
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"\$(?P<name>[A-Za-z][A-Za-z0-9]*Source)\s*=\s*@'\n"
            r"(?P<body>.*?)\n'@",
            source,
            re.DOTALL,
        )
    }


def test_all_41_predecessor_pins_are_unique_and_exact() -> None:
    builder = load_builder()
    pins = direct_and_carried_pins(builder)
    assert len(pins) == 41
    assert len({pin["path"] for pin in pins}) == 41
    assert builder.ARCHIVE_PIN in pins[:25]
    for expected in pins:
        observed = windows_pin(REPO / expected["path"])
        assert observed["size"] == expected["size"]
        assert observed["sha256"] == expected["sha256"]
        assert observed["file_id"] == expected["file_id"]
        assert observed["last_write_utc_ticks"] == expected["last_write_utc_ticks"]


def test_v30_failure_is_consumed_after_ready_before_canonical_launch() -> None:
    builder = load_builder()
    artifacts = builder.V30_ARTIFACTS
    claim = json.loads((REPO / artifacts["claim"]["path"]).read_text("utf-8"))
    rejection = json.loads((REPO / artifacts["rejection"]["path"]).read_text("utf-8"))
    release = json.loads(
        (REPO / artifacts["heavy_lock_release"]["path"]).read_text("utf-8")
    )
    lock_evidence = json.loads(
        (REPO / artifacts["heavy_lock"]["path"]).read_text("utf-8")
    )
    authorization = json.loads(
        (REPO / builder.V30_SOURCES["authorization"]["path"]).read_text("utf-8")
    )
    assert claim["run_id"] == V30_RUN_ID
    assert claim["failure_consumes_authorization"] is True
    assert claim["status"] == (
        "CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS"
    )
    assert rejection["status"] == "REJECTED_AUTHORIZATION_CONSUMED"
    assert rejection["claim_publication_phase"] == "durably_published"
    assert rejection["claim_publication_complete"] is True
    assert rejection["failure"] == (
        "A positional parameter cannot be found that accepts argument '0'.; "
        "watcher_stop=Watcher wrapper rejected: exit=1"
    )
    assert rejection["pass_receipt_present"] is False
    assert rejection["pass_shutdown_seal_absent"] is True
    assert rejection["acceptance_commitment_sha256"] == ""
    assert rejection["snapshot_retained_for_forensics"] is True
    assert rejection["predecessor_rejection_replay"]["status"] == "REPLAYED"
    assert rejection["predecessor_rejection_replay"]["errors"] == []
    assert release["decision"] == "REJECTED"
    assert release["same_handle_verified"] is True
    assert release["delete_on_close"] is True
    assert release["lock_path_absent"] is True
    assert release["lock_sha256"] == lock_evidence["lock_sha256"]
    assert authorization["automatic_retry_authorized"] is False
    assert builder.PREDECESSOR_CONTRACT["v30"]["failure"] == {
        "status": "REJECTED_AUTHORIZATION_CONSUMED",
        "phase": (
            "after_staging_ready_before_preinventory_"
            "resource_monitor_and_canonical_launch"
        ),
        "primary_root_cause": (
            "PowerShell_TestPath_command_mode_binding_of_"
            "empty_error_length_as_positional_argument_0"
        ),
        "secondary_failure": (
            "abort_control_watcher_stopped_before_cleanup_authorization"
        ),
        "canonical_suite_executed": False,
        "automatic_retry_authorized": False,
    }


def test_v30_staging_and_watcher_evidence_prove_exact_failure_phase() -> None:
    builder = load_builder()
    artifacts = builder.V30_ARTIFACTS
    rows = [
        json.loads(line)
        for line in (REPO / artifacts["watch_log"]["path"])
        .read_text("utf-8")
        .splitlines()
    ]
    kinds = [row["kind"] for row in rows]
    assert len(rows) == 203
    assert kinds[0] == "ARMED"
    assert kinds.count("STAGING_EVENT") == 201
    assert kinds[-1] == "READY"
    assert not {"CLEANUP_AUTHORIZED", "CLEANED", "DONE"}.intersection(kinds)
    ready = rows[-1]
    assert ready["file_count"] == 3146
    assert ready["staging_event_count"] == 201
    assert ready["inventory_sha256"] == artifacts["staging_inventory"]["sha256"]
    assert ready["parent_watch_loss_events"] == 0
    assert ready["parent_watch_active"] is True
    assert ready["all_nlink_one"] is True
    assert ready["device_inode_frozen"] is True
    inventory = json.loads(
        (REPO / artifacts["staging_inventory"]["path"]).read_text("utf-8")
    )
    assert inventory["file_count"] == 3146
    assert inventory["directory_count"] == 368
    assert inventory["total_bytes"] == 190_900_047
    assert all(
        row["nlink"] == 1 and row["mode"] == "0400" for row in inventory["files"]
    )
    assert all(
        row["mode"] == ("0700" if row["path"] == "." else "0500")
        for row in inventory["directories"]
    )
    assert "watcher stopped before cleanup authorization" in (
        REPO / artifacts["watch_error"]["path"]
    ).read_text("utf-8")
    assert "watcher stopped before cleanup authorization" in (
        REPO / artifacts["watch_wrapper_stderr"]["path"]
    ).read_text("utf-8")
    assert (REPO / artifacts["watch_wrapper_stdout"]["path"]).read_bytes() == b""
    stop = json.loads((REPO / artifacts["watch_stop"]["path"]).read_text("utf-8"))
    assert stop["schema"] == "planora.muni-v30.watcher-abort-control.v1"


def test_v30_exact_artifact_inventory_absences_and_nested_hashes() -> None:
    builder = load_builder()
    contract = builder.PREDECESSOR_CONTRACT["v30"]
    present = sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / "output/diagnostic-receipts").glob(
            f"muni-fspsx-v30-canonical-readonly-tests-{V30_RUN_ID}.*"
        )
        if path.is_file()
    )
    expected = sorted(pin["path"] for pin in builder.V30_ARTIFACTS.values())
    assert present == expected
    for suffix in builder.V30_EXPECTED_ABSENT_SUFFIXES:
        assert not (REPO / f"{builder.V30_PREFIX}.{suffix}").exists()
    rejection = json.loads(
        (REPO / builder.V30_ARTIFACTS["rejection"]["path"]).read_text("utf-8")
    )
    custody = json.loads(
        (REPO / builder.V30_ARTIFACTS["predecessor_custody"]["path"]).read_text("utf-8")
    )
    prior = rejection["predecessor_evidence"]
    assert prior["schema"] == contract["embedded_evidence_schema"]
    assert prior["status"] == "VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY"
    assert prior["rejection_replay"]["status"] == "REPLAYED"
    assert prior["rejection_replay"]["errors"] == []
    assert len(prior["runtime"]["validated_pins"]) == 25
    assert (
        canonical_hash(prior) == contract["post_rejection_predecessor_evidence_sha256"]
    )
    assert (
        canonical_hash(custody["predecessor_evidence"])
        == contract["initial_custody_predecessor_evidence_sha256"]
    )
    assert (
        rejection["predecessor_custody_sha256"]
        == builder.V30_ARTIFACTS["predecessor_custody"]["sha256"]
    )


def test_authorization_binds_v31_and_all_new_contracts() -> None:
    builder = load_builder()
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    assert auth["schema"] == "planora.itc2019.canonical-test-authorization.v11"
    assert auth["candidate"] == "muni_v31"
    assert auth["test_id"] == RUN_ID
    assert auth["created_at_utc"] == "2026-08-28T11:32:25Z"
    assert auth["automatic_retry_authorized"] is False
    assert auth["runner"] == {
        "path": "scripts/run_muni_v31_canonical_tests.ps1",
        "size": RUNNER.stat().st_size,
        "sha256": sha256(RUNNER),
    }
    assert auth["successor_admission"]["builder"] == {
        "path": "scripts/build_muni_v31_successor.py",
        "size": BUILDER.stat().st_size,
        "sha256": sha256(BUILDER),
    }
    assert auth["successor_admission"]["tests"] == {
        "path": "tests/test_run_muni_v31_successor.py",
        "size": Path(__file__).stat().st_size,
        "sha256": sha256(Path(__file__)),
    }
    assert auth["predecessor_custody_contract"] == builder.PREDECESSOR_CONTRACT
    readiness = auth["readiness_binding_contract"]
    assert readiness["shared_predicate"] == "Test-NonEmptyEvidenceFile"
    assert readiness["watcher_and_resource_call_sites"] is True
    assert readiness["missing_empty_nonempty_runtime_regression"] is True
    assert readiness["legacy_empty_file_binding_failure_reproduced"] is True
    assert readiness["operator_shaped_command_arguments_rejected"] is True
    assert readiness["isolated_switch"] == "ReadinessPredicateSelfTest"
    assert (
        auth["log_bridge_contract"][
            "writer_exit_visibility_race_retried_within_existing_three_second_deadline"
        ]
        is True
    )
    retained = auth["retained_v30_snapshot_contract"]
    assert retained["root"] == builder.PREDECESSOR_CONTRACT["v30"]["snapshot"]["root"]
    assert retained["isolated_switch"] == "RetainedV30SnapshotSelfTest"
    assert retained["initial_and_terminal_read_only_replay_required"] is True
    assert retained["post_cleanup_replay_while_v31_lock_held"] is True
    assert retained["terminal_replay_immediately_before_final_archive_guard"] is True
    assert retained["descriptor_open_nofollow_identity_replay"] is True
    evidence = auth["evidence_contract"]
    for key in (
        "complete_v28_v29_v30_predecessor_evidence_bound_to_plan_pass_and_all_rejections",
        "all_41_predecessor_file_ids_and_timestamps_authorized",
        "predecessor_pins_in_protected_replay_sets",
        "v28_v29_v30_pass_absence_replayed_through_final_pass_seal_publication",
        "retained_archive_validated_in_place_without_mutation",
        "retained_v30_snapshot_initial_and_terminal_replay_bound",
        "terminal_archived_lock_identity_replay_bound_by_final_pass_seal",
        "terminal_archived_lock_read_guard_held_through_final_pass_seal_flush",
        "final_pass_seal_create_only_durable_last_operation",
        "rejection_lifecycle_fields_required",
    ):
        assert evidence[key] is True
    source = RUNNER.read_text(encoding="utf-8")
    dynamic_builder_pin = (
        "Assert-LocalPin $successorBuilderPath "
        "([long]$auth.authorization.successor_admission.builder.size) "
        "([string]$auth.authorization.successor_admission.builder.sha256)"
    )
    dynamic_tests_pin = (
        "Assert-LocalPin $admissionTestsPath "
        "([long]$auth.authorization.successor_admission.tests.size) "
        "([string]$auth.authorization.successor_admission.tests.sha256)"
    )
    assert source.count(dynamic_builder_pin) == 2
    assert source.count(dynamic_tests_pin) == 2
    assert "Assert-LocalPin $successorBuilderPath 59115" not in source
    assert "Assert-LocalPin $admissionTestsPath 17533" not in source


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_authorization_replays_exactly_under_ps5_and_ps7(executable: Path) -> None:
    result = invoke_runner(executable, "-EmitExpectedAuthorization")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == json.loads(AUTH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_readiness_regression_runs_in_isolation_under_ps5_and_ps7(
    executable: Path,
) -> None:
    result = invoke_runner(executable, "-ReadinessPredicateSelfTest")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "PASS"
    assert evidence["canonical_suite_executed"] is False
    assert evidence["shared_lock_used"] is False
    assert evidence["wsl_executed"] is False
    binding = evidence["binding"]
    assert binding["status"] == (
        "MISSING_EMPTY_NONEMPTY_LEGACY_FAILURE_AND_BOTH_PRODUCTION_CALL_SITES_PASS"
    )
    assert binding["legacy_empty_binding_failure_reproduced"] is True
    assert binding["production_call_sites"] == 2
    assert binding["operator_shaped_arguments_absent"] is True


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_static_self_test_is_nonwsl_and_validates_complete_custody(
    executable: Path,
) -> None:
    result = invoke_runner(executable, "-StaticSelfTest")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    evidence = json.loads(result.stdout)
    assert evidence["canonical_suite_executed"] is False
    assert evidence["wsl_executed"] is False
    assert evidence["frozen_closure"] == "PASS"
    assert evidence["predecessor_evidence_model"] == (
        "41_EXACT_IDENTITY_PINS_V28_V29_V30_PLUS_TRIPLE_PASS_ABSENCE_VALIDATED"
    )
    assert (
        evidence["powershell_readiness_binding"][
            "legacy_empty_binding_failure_reproduced"
        ]
        is True
    )
    assert evidence["archived_predecessor_model"]["archive_mutation_performed"] is False


def test_readiness_call_sites_are_grouped_and_command_binding_safe() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert source.count("function Test-NonEmptyEvidenceFile") == 1
    assert source.count("if(Test-NonEmptyEvidenceFile $watchErrorFile)") == 1
    assert source.count("if(Test-NonEmptyEvidenceFile $resourceErrorFile)") == 1
    assert "$watchErrorFile-and(" not in source
    assert "$resourceErrorFile-and(" not in source
    helper = source[source.index("function Test-NonEmptyEvidenceFile") :]
    helper = helper[: helper.index("function Get-ObsoleteV3AuthorizationJson")]
    assert "-PathType Leaf" in helper
    assert "((Get-Item -LiteralPath $Path).Length -ne 0)" in helper
    assert "Legacy empty-file readiness expression did not reproduce" in helper


def test_log_reader_retries_the_writer_exit_visibility_race() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    reader = source[source.index("function Read-StableUtf8Log") :]
    reader = reader[: reader.index("function Get-WatcherLogState")]
    assert "$writerSupplied=($null-ne$WriterProcess)" in reader
    assert reader.count("$writerSupplied-and[DateTime]::UtcNow-lt$deadline") == 4
    assert "$wasLive-and[DateTime]::UtcNow-lt$deadline" not in reader
    assert "AddSeconds(3)" in reader


def test_embedded_programs_parse_and_retained_verifier_is_read_only() -> None:
    programs = embedded_sources()
    assert len(programs) == 8
    for program in programs.values():
        ast.parse(program)
    retained = programs["retainedV30SnapshotVerifierSource"]
    for required in (
        "os.fwalk",
        "os.O_NOFOLLOW",
        "os.fstat",
        "file_identity",
        "dir_identity",
        "current!=expected",
        "st_dev",
        "st_ino",
        "st_nlink",
    ):
        assert required in retained
    for forbidden in (
        "os.unlink",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "shutil",
        ".write(",
        ".truncate(",
    ):
        assert forbidden not in retained


def test_retained_snapshot_switch_is_nonconsuming_and_preclaim() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "[switch]$RetainedV30SnapshotSelfTest" in source.splitlines()[0]
    branch_start = source.index("if($RetainedV30SnapshotSelfTest){")
    branch_end = source.index("if($LogBridgeSelfTest){", branch_start)
    branch = source[branch_start:branch_end]
    assert (
        "Invoke-RetainedV30SnapshotVerifier 'isolated_nonconsuming_preflight'" in branch
    )
    assert "Get-AuthorizationState" in branch
    assert "Shared heavy lock present" in branch
    assert "Fresh v31 artifact namespace is not empty" in branch
    assert "canonical_suite_executed=$false" in branch
    assert "shared_lock_used=$false" in branch
    assert "claim_created=$false" in branch
    assert "Write-NewUtf8" not in branch
    assert "[IO.FileMode]::CreateNew" not in branch
    assert branch_end < source.rindex("$claimPublicationStarted=$true")


def test_retained_snapshot_custody_and_success_ordering() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    custody = source.rindex("Write-NewUtf8 $predecessorCustodyFile")
    acquire = source.rindex("$lockStream=New-Object IO.FileStream($sharedLockPath")
    same_handle = source.rindex("Assert-HeldLockPath $lockStream $lockBytes $lockHash")
    initial = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier 'initial_after_v31_lock'"
    )
    initial_write = source.rindex("Write-NewUtf8 $retainedV30SnapshotCustodyFile")
    lock_write = source.rindex("Write-NewUtf8 $lockEvidenceFile")
    staging = source.rindex("$stageResult=Invoke-SafeStdinProcess")
    canonical = source.rindex("$canonicalLaunchAttempted=$true")
    cleanup = source.rindex("$cleanResult=Invoke-SafeStdinProcess")
    post_cleanup = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier "
        "'post_cleanup_while_v31_lock_held_before_final_census'"
    )
    post_cleanup_write = source.rindex(
        "Write-NewUtf8 $retainedV30SnapshotTerminalCustodyFile"
    )
    census = source.rindex("$after=[ordered]")
    release = source.rindex(
        "Release-HeavyLock $lockStream $lockHash 'ACCEPTED_PENDING_FINALIZATION'"
    )
    receipt = source.rindex("Write-NewUtf8 $receiptFile $receiptJson")
    final_replay = source.rindex("$finalReplay=Assert-FinalEvidenceReplay")
    terminal_snapshot = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier "
        "'terminal_immediately_before_archive_guard_and_final_seal'"
    )
    archive_guard = source.rindex(
        "$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard"
    )
    seal = source.rindex("Write-FinalPassSeal $passSealFile")
    assert (
        custody
        < acquire
        < same_handle
        < initial
        < initial_write
        < lock_write
        < staging
        < canonical
        < cleanup
        < post_cleanup
        < post_cleanup_write
        < census
        < release
        < receipt
        < final_replay
        < terminal_snapshot
        < archive_guard
        < seal
    )
    reserved = source[source.index("$reserved=@(") :]
    reserved = reserved[: reserved.index("foreach($p in $reserved)")]
    assert "$retainedV30SnapshotCustodyFile" in reserved
    assert "$retainedV30SnapshotTerminalCustodyFile" in reserved
    cleanup_source = embedded_sources()["cleanupSource"]
    assert "prefix='/tmp/planora-muni-v31-canonical-tests-'" in cleanup_source
    assert "prefix='/tmp/planora-muni-v30-canonical-tests-'" not in cleanup_source
    assert (
        "$retainedV30SnapshotCustodyFile"
        in source[source.index("$preAcceptancePins=@(") :]
    )
    assert (
        "$retainedV30SnapshotTerminalCustodyPin"
        in source[source.index("$protectedPins=@(") :]
    )


def test_predecessor_snapshot_lifecycle_and_seal_bind_all_terminal_paths() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "planora.muni-v30.complete-v28-v29-predecessor-evidence.v1" in source
    assert "planora.muni-v31.complete-v28-v29-v30-predecessor-evidence.v1" in source
    assert "$predecessorPins.Count-ne41" in source
    assert "$preAcceptancePins=@($predecessorPins)+@(" in source
    assert "$plan['predecessor_evidence']=$predecessorEvidence" in source
    assert "$receipt['predecessor_evidence']=$predecessorEvidence" in source
    assert "Assert-V28V29V30PassEvidenceAbsent" in source
    assert "nested_predecessor_hashes" in source
    normal = source.rindex("schema='planora.muni-v31.overall-rejection.v6'")
    emergency = source.rindex("schema='planora.muni-v31.emergency-rejection.v3'")
    for region in (source[normal:emergency], source[emergency:]):
        assert "lifecycle=" in region
        assert "predecessor_evidence=$predecessorEvidence" in region
        assert "retained_v30_snapshot_custody_pin=" in region
        assert "retained_v30_snapshot_terminal_custody_pin=" in region
        assert "retained_v30_snapshot_rejection_replay=" in region
    seal_start = source.rindex("$seal=[ordered]@{")
    seal_call = source.rindex(
        "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream"
    )
    seal_object = source[seal_start:seal_call]
    assert "retained_v30_snapshot_custody_sha256=" in seal_object
    assert "retained_v30_snapshot_terminal_custody_sha256=" in seal_object
    assert "retained_v30_snapshot_final_replay=" in seal_object


def test_lock_archive_and_final_seal_remain_fail_closed() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    custody = source.rindex("Write-NewUtf8 $predecessorCustodyFile")
    acquire = source.rindex("$lockStream=New-Object IO.FileStream($sharedLockPath")
    release = source.rindex(
        "Release-HeavyLock $lockStream $lockHash 'ACCEPTED_PENDING_FINALIZATION'"
    )
    assert custody < acquire < release
    lock_region = source[acquire:release]
    assert "[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose" in lock_region
    assert "Assert-HeldLockPath $lockStream $lockBytes $lockHash" in lock_region
    assert "Get-Sha256 $sharedLockPath" not in lock_region
    final_replay = source.rindex("$finalReplay=Assert-FinalEvidenceReplay")
    guard = source.rindex("$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard")
    seal = source.rindex(
        "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream"
    )
    catch = source.index("\n}\ncatch{", seal)
    assert final_replay < guard < seal < catch
    assert (
        source[
            seal
            + len(
                "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream"
            ) : catch
        ].strip()
        == ""
    )
    writer = source[source.index("function Write-FinalPassSeal") :]
    writer = writer[: writer.index("\nfunction ", 1)]
    assert "[IO.FileMode]::CreateNew" in writer
    assert "$stream.Flush($true);$durablyFlushed=$true" in writer
    terminal = source[source.index("function Open-TerminalArchivedStaleLockGuard") :]
    terminal = terminal[: terminal.index("\nfunction ", 1)]
    assert "[IO.FileAccess]::Read,[IO.FileShare]::Read" in terminal
    assert "Assert-V28V29V30PassEvidenceAbsent" in terminal


def test_fresh_v31_has_zero_run_artifacts_and_preserves_v30() -> None:
    builder = load_builder()
    prefix = f"muni-fspsx-v31-canonical-readonly-tests-{RUN_ID}"
    assert list((REPO / "output/diagnostic-receipts").glob(prefix + ".*")) == []
    assert not SHARED_LOCK.exists()
    assert ARCHIVE.exists()
    for pin in builder.V30_ARTIFACTS.values():
        assert (REPO / pin["path"]).is_file()
    for suffix in builder.V30_EXPECTED_ABSENT_SUFFIXES:
        assert not (REPO / f"{builder.V30_PREFIX}.{suffix}").exists()


def test_builder_is_deterministic_nonwsl_and_preserves_predecessors() -> None:
    builder = load_builder()
    pins = direct_and_carried_pins(builder)
    before_predecessors = {pin["path"]: windows_pin(REPO / pin["path"]) for pin in pins}
    before = RUNNER.read_bytes(), AUTH.read_bytes()
    source = BUILDER.read_text(encoding="utf-8")
    assert "wsl.exe" not in source.lower()
    result = subprocess.run(
        [sys.executable, "-B", str(BUILDER)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert (RUNNER.read_bytes(), AUTH.read_bytes()) == before
    after_predecessors = {pin["path"]: windows_pin(REPO / pin["path"]) for pin in pins}
    assert after_predecessors == before_predecessors
    summary = json.loads(result.stdout)
    assert summary["status"] == "MUNI_V31_SUCCESSOR_GENERATED_STATIC_ONLY"
    assert summary["run_id"] == RUN_ID
    assert summary["wsl_executed"] is False
    assert summary["log_bridge_executed"] is False
    assert summary["readiness_self_test_executed"] is False
    assert summary["retained_snapshot_verifier_executed"] is False
    assert summary["canonical_suite_executed"] is False
    prefix = f"muni-fspsx-v31-canonical-readonly-tests-{RUN_ID}"
    assert list((REPO / "output/diagnostic-receipts").glob(prefix + ".*")) == []
    assert not SHARED_LOCK.exists()
