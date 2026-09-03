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
RUN_ID = "4dc45edcd74446909290afadd5d3ecf0"
V31_RUN_ID = "5f2d84640f40404a82dd180d7043d9c5"
BUILDER = REPO / "scripts/build_muni_v32_successor.py"
RUNNER = REPO / "scripts/run_muni_v32_canonical_tests.ps1"
AUTH = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v32-canonical-tests-authorization-20260828T130114Z.receipt.json"
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
    "-CanonicalMonitorContractSelfTest",
    "-RejectionPromotionSelfTest",
    "-ReadinessPredicateSelfTest",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("muni_v32_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ps_executables() -> list[Path]:
    ps5 = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    pwsh = shutil.which("pwsh")
    assert ps5.is_file(), "Windows PowerShell 5.1 is required"
    assert pwsh, "PowerShell 7 is required"
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


def complete_predecessor_pins(builder: ModuleType) -> list[dict[str, Any]]:
    rejection = json.loads(
        (REPO / builder.V31_ARTIFACTS["rejection"]["path"]).read_text("utf-8")
    )
    carried = rejection["predecessor_evidence"]["runtime"]["validated_pins"]
    direct = [
        *builder.V31_SOURCES.values(),
        *builder.V31_PROVENANCE.values(),
        *builder.V31_ARTIFACTS.values(),
    ]
    assert len(carried) == 41
    assert len(direct) == 20
    return [*carried, *direct]


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


def test_all_61_predecessor_pins_are_unique_and_exact() -> None:
    builder = load_builder()
    assert len(builder.V31_SOURCES) == 4
    assert len(builder.V31_PROVENANCE) == 2
    assert len(builder.V31_ARTIFACTS) == 14
    pins = complete_predecessor_pins(builder)
    assert len(pins) == 61
    assert len({pin["path"] for pin in pins}) == 61
    assert 41 + len(builder.V31_SOURCES) + len(builder.V31_ARTIFACTS) == 59
    assert 59 + len(builder.V31_PROVENANCE) == 61
    for expected in pins:
        observed = windows_pin(REPO / expected["path"])
        assert observed["size"] == expected["size"]
        assert observed["sha256"] == expected["sha256"]
        assert observed["file_id"] == expected["file_id"]
        assert observed["last_write_utc_ticks"] == expected["last_write_utc_ticks"]


def test_v31_consumed_failure_is_authenticated_before_any_launch() -> None:
    builder = load_builder()
    contract = builder.V31_FAILURE_CONTRACT
    artifacts = builder.V31_ARTIFACTS
    claim = json.loads((REPO / artifacts["claim"]["path"]).read_text("utf-8"))
    rejection = json.loads((REPO / artifacts["rejection"]["path"]).read_text("utf-8"))
    release = json.loads(
        (REPO / artifacts["heavy_lock_release"]["path"]).read_text("utf-8")
    )
    lock = json.loads((REPO / artifacts["heavy_lock"]["path"]).read_text("utf-8"))
    assert claim["run_id"] == V31_RUN_ID
    assert claim["failure_consumes_authorization"] is True
    assert claim["status"] == (
        "CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS"
    )
    assert rejection["status"] == contract["failure"]["status"]
    assert rejection["failure"] == contract["failure"]["message"]
    assert rejection["claim_publication_complete"] is True
    assert rejection["claim_publication_phase"] == "durably_published"
    assert rejection["pass_receipt_present"] is False
    assert rejection["pass_shutdown_seal_absent"] is True
    assert rejection["snapshot_retained_for_forensics"] is True
    assert rejection["predecessor_rejection_replay"]["status"] == "REPLAYED"
    assert rejection["predecessor_rejection_replay"]["errors"] == []
    lifecycle = rejection["lifecycle"]
    assert lifecycle["staging_exited"] is True
    assert lifecycle["watcher_ready"] is True
    assert lifecycle["preinventory_started"] is True
    for flag in (
        "resource_launch_attempted",
        "canonical_launch_attempted",
        "canonical_started",
        "canonical_exited",
    ):
        assert lifecycle[flag] is False
    assert release["decision"] == "REJECTED"
    assert release["same_handle_verified"] is True
    assert release["delete_on_close"] is True
    assert release["lock_path_absent"] is True
    assert release["lock_sha256"] == lock["lock_sha256"]
    assert contract["failure"]["polluted_output_count"] == 254
    assert contract["failure"]["polluted_first_type"] == "System.Boolean"
    assert contract["failure"]["polluted_timeout_index"] == 4
    assert contract["failure"]["polluted_bwrap_index"] == 8
    assert contract["failure"]["canonical_suite_executed"] is False


def test_v31_exact_artifacts_absences_and_nested_evidence_hashes() -> None:
    builder = load_builder()
    contract = builder.V31_FAILURE_CONTRACT
    assert builder.V31_EXPECTED_ABSENT_SUFFIXES == [
        "receipt.json",
        "pass-publication-shutdown-seal.json",
        "rejection-emergency.json",
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
        "retained-v30-snapshot-terminal-custody.json",
    ]
    assert len(set(builder.V31_EXPECTED_ABSENT_SUFFIXES)) == 17
    present = sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / "output/diagnostic-receipts").glob(
            f"muni-fspsx-v31-canonical-readonly-tests-{V31_RUN_ID}.*"
        )
        if path.is_file()
    )
    assert present == sorted(pin["path"] for pin in builder.V31_ARTIFACTS.values())
    assert len(present) == contract["artifact_count"] == 14
    for suffix in builder.V31_EXPECTED_ABSENT_SUFFIXES:
        assert not (REPO / f"{builder.V31_PREFIX}.{suffix}").exists()
    rejection = json.loads(
        (REPO / builder.V31_ARTIFACTS["rejection"]["path"]).read_text("utf-8")
    )
    custody = json.loads(
        (REPO / builder.V31_ARTIFACTS["predecessor_custody"]["path"]).read_text("utf-8")
    )
    predecessor = rejection["predecessor_evidence"]
    assert predecessor["status"] == ("VALIDATED_EXACT_V28_V29_V30_PREDECESSOR_CUSTODY")
    assert len(predecessor["runtime"]["validated_pins"]) == 41
    assert (
        rejection["predecessor_evidence_sha256"]
        == (contract["post_rejection_predecessor_evidence_sha256"])
    )
    assert (
        custody["predecessor_evidence_sha256"]
        == (contract["initial_predecessor_evidence_sha256"])
    )
    stage = json.loads(
        (REPO / builder.V31_ARTIFACTS["staging_inventory"]["path"]).read_text("utf-8")
    )
    pre = json.loads(
        (REPO / builder.V31_ARTIFACTS["pre_inventory"]["path"]).read_text("utf-8")
    )
    assert stage == pre
    assert stage["root"] == contract["snapshot"]["root"]
    assert stage["file_count"] == contract["snapshot"]["files"] == 3146
    assert stage["directory_count"] == contract["snapshot"]["directories"] == 368
    assert stage["total_bytes"] == contract["snapshot"]["bytes"] == 190_900_047


def test_v31_pipeline_root_cause_and_v32_fix_are_source_exact() -> None:
    builder = load_builder()
    v31 = (REPO / builder.V31_SOURCES["runner"]["path"]).read_text("utf-8")
    v32 = RUNNER.read_text("utf-8")
    bare = r"(?m)^    Assert-CanonicalArguments \$args \$Legacy$"
    fixed = r"(?m)^    \[void\]\(Assert-CanonicalArguments \$args \$Legacy\)$"
    assert len(re.findall(bare, v31)) == 1
    assert len(re.findall(fixed, v31)) == 0
    assert len(re.findall(bare, v32)) == 0
    assert len(re.findall(fixed, v32)) == 1
    assert "if($Arguments.Count-ne253)" in v32
    assert "$Arguments[$i]-isnot[string]" in v32
    assert "$timeoutIndex-ne3-or$bwrapIndex-ne7-or$testIndex-ne248" in v32
    assert "$polluted.Count-ne254" in v32
    assert "$pollutedTimeout-ne4-or$pollutedBwrap-ne8" in v32


def test_authorization_binds_v32_and_complete_failure_custody() -> None:
    builder = load_builder()
    auth = json.loads(AUTH.read_text("utf-8"))
    assert auth["schema"] == "planora.itc2019.canonical-test-authorization.v12"
    assert auth["candidate"] == "muni_v32"
    assert auth["test_id"] == RUN_ID
    assert auth["created_at_utc"] == "2026-08-28T13:01:14Z"
    assert auth["automatic_retry_authorized"] is False
    assert auth["runner"] == {
        "path": "scripts/run_muni_v32_canonical_tests.ps1",
        "size": RUNNER.stat().st_size,
        "sha256": sha256(RUNNER),
    }
    assert auth["successor_admission"]["builder"] == {
        "path": "scripts/build_muni_v32_successor.py",
        "size": BUILDER.stat().st_size,
        "sha256": sha256(BUILDER),
    }
    assert auth["successor_admission"]["tests"] == {
        "path": "tests/test_run_muni_v32_successor.py",
        "size": Path(__file__).stat().st_size,
        "sha256": sha256(Path(__file__)),
    }
    assert auth["v31_failure_custody_contract"] == builder.V31_FAILURE_CONTRACT
    argv = auth["canonical_argv_contract"]
    assert argv == {
        "exact_string_atoms": 253,
        "timeout_index": 3,
        "bwrap_index": 7,
        "python_index": 248,
        "unsuppressed_validator_output_regression": True,
        "isolated_switch": "CanonicalMonitorContractSelfTest",
        "powershell5_and_7_required": True,
    }
    assert auth["wsl_geometry_contract"] == {
        "columns": 32768,
        "lines": 1000,
        "wslenv": "COLUMNS:LINES",
        "canonical_environment_cleared": True,
    }
    assert auth["rejection_promotion_contract"] == {
        "expected_complete_evidence_present_before_claim": True,
        "successful_replay_promoted_without_cycle": True,
        "failed_replay_summarized_without_evidence_reference": True,
        "v31_failure_hash_nonempty_on_early_rejection": True,
        "isolated_switch": "RejectionPromotionSelfTest",
        "powershell5_and_7_required": True,
    }
    evidence = auth["evidence_contract"]
    for key in (
        "complete_v28_v29_v30_v31_predecessor_evidence_bound_to_plan_pass_and_all_rejections",
        "all_61_predecessor_file_ids_and_timestamps_authorized",
        "predecessor_pins_in_protected_replay_sets",
        "v28_v29_v30_v31_pass_absence_replayed_through_final_pass_seal_publication",
        "retained_archive_validated_in_place_without_mutation",
        "retained_v30_snapshot_initial_and_terminal_replay_bound",
        "retained_v31_snapshot_initial_and_terminal_replay_bound",
        "terminal_archived_lock_identity_replay_bound_by_final_pass_seal",
        "final_pass_seal_create_only_durable_last_operation",
    ):
        assert evidence[key] is True
    retained = auth["retained_predecessor_snapshots_contract"]
    assert retained["v30_root"].endswith("e358bc6417224fe6a329ad3775853f01")
    assert retained["v31_root"] == builder.V31_FAILURE_CONTRACT["snapshot"]["root"]
    assert retained["isolated_switch"] == "RetainedPredecessorSnapshotsSelfTest"
    assert retained["read_only_identity_replay"] is True
    assert retained["initial_post_cleanup_rejection_and_final_replay_required"] is True


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_authorization_replays_exactly_under_ps5_and_ps7(executable: Path) -> None:
    result = invoke_runner(executable, "-EmitExpectedAuthorization")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == json.loads(AUTH.read_text("utf-8"))


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_canonical_monitor_contract_is_exact_under_ps5_and_ps7(
    executable: Path,
) -> None:
    result = invoke_runner(executable, "-CanonicalMonitorContractSelfTest")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "PASS"
    assert evidence["run_id"] == RUN_ID
    assert evidence["fixed"]["argument_count"] == 253
    assert evidence["fixed"]["all_arguments_strings"] is True
    assert evidence["fixed"]["timeout_index"] == 3
    assert evidence["fixed"]["bwrap_index"] == 7
    assert evidence["fixed"]["python_index"] == 248
    assert len(evidence["fixed"]["timeout_argv"]) == 250
    assert len(evidence["fixed"]["bwrap_argv"]) == 246
    assert len(evidence["fixed"]["test_argv"]) == 5
    assert evidence["fixed"]["test_argv"][0] == "/usr/bin/python3.12"
    assert evidence["v31_negative_baseline"] == {
        "count": 254,
        "first_type": "System.Boolean",
        "timeout_index": 4,
        "bwrap_index": 8,
        "contract_rejected": True,
        "rejection": "Canonical argument count rejected: 254",
    }
    assert evidence["process_start_info_render"] == (
        "EXACT_JOINED_SAFE_ATOMS_NOT_STARTED"
    )
    assert evidence["wsl_executed"] is False
    assert evidence["canonical_suite_executed"] is False
    assert evidence["shared_lock_used"] is False


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_static_self_test_validates_complete_custody_without_wsl(
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
        "61_EXACT_IDENTITY_PINS_V28_V29_V30_V31_PLUS_QUADRUPLE_PASS_ABSENCE_VALIDATED"
    )
    assert evidence["archived_predecessor_model"]["archive_mutation_performed"] is False


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_rejection_promotion_is_acyclic_and_complete_under_ps5_and_ps7(
    executable: Path,
) -> None:
    result = invoke_runner(executable, "-RejectionPromotionSelfTest")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "PASS"
    assert evidence["early_failure"]["evidence_status"] == (
        "EXPECTED_UNVALIDATED_V28_V29_V30_V31_PREDECESSOR_CUSTODY"
    )
    assert evidence["early_failure"]["replay_status"] == "REPLAY_ERRORS_RECORDED"
    assert evidence["early_failure"]["json_serialized"] is True
    assert evidence["successful_replay"]["evidence_status"] == (
        "VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY"
    )
    assert evidence["successful_replay"]["replay_status"] == "REPLAYED"
    assert evidence["successful_replay"]["validated_pin_count"] == 61
    assert evidence["successful_replay"]["json_serialized"] is True
    for branch in (evidence["early_failure"], evidence["successful_replay"]):
        assert re.fullmatch(r"[0-9a-f]{64}", branch["v31_failure_evidence_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", branch["predecessor_evidence_sha256"])
    assert evidence["wsl_executed"] is False
    assert evidence["canonical_suite_executed"] is False
    assert evidence["shared_lock_used"] is False
    assert evidence["claim_created"] is False
    assert evidence["v32_artifacts_created"] is False


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


def test_retained_snapshot_switch_is_combined_nonconsuming_and_preclaim() -> None:
    source = RUNNER.read_text("utf-8")
    first_line = source.splitlines()[0]
    assert "[switch]$RetainedPredecessorSnapshotsSelfTest" in first_line
    branch_start = source.index("if($RetainedPredecessorSnapshotsSelfTest){")
    branch_end = source.index("if($LogBridgeSelfTest){", branch_start)
    branch = source[branch_start:branch_end]
    assert "isolated_nonconsuming_v30_preflight" in branch
    assert "isolated_nonconsuming_v31_preflight" in branch
    assert "Invoke-RetainedV30SnapshotVerifier" in branch
    assert "Invoke-RetainedV31SnapshotVerifier" in branch
    assert "$existingAfter=@(" in branch
    assert "Retained predecessor snapshot self-test created v32 evidence" in branch
    assert "Test-Path -LiteralPath $claimFile" in branch
    assert "Get-AuthorizationState" in branch
    assert "Shared heavy lock present" in branch
    assert "Fresh v32 artifact namespace is not empty" in branch
    assert "canonical_suite_executed=$false" in branch
    assert "shared_lock_used=$false" in branch
    assert "claim_created=$false" in branch
    assert "Write-NewUtf8" not in branch
    assert "[IO.FileMode]::CreateNew" not in branch
    assert branch_end < source.rindex("$claimPublicationStarted=$true")


def test_both_retained_snapshots_are_replayed_and_bound_on_every_terminal_path() -> (
    None
):
    source = RUNNER.read_text("utf-8")
    v30_initial = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier 'initial_after_v32_lock'"
    )
    v31_initial = source.rindex(
        "Invoke-RetainedV31SnapshotVerifier 'initial_after_v32_lock'"
    )
    v30_post = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier "
        "'post_cleanup_while_v32_lock_held_before_final_census'"
    )
    v31_post = source.rindex(
        "Invoke-RetainedV31SnapshotVerifier "
        "'post_cleanup_while_v32_lock_held_before_final_census'"
    )
    receipt = source.rindex("Write-NewUtf8 $receiptFile $receiptJson")
    v30_final = source.rindex(
        "Invoke-RetainedV30SnapshotVerifier "
        "'terminal_immediately_before_archive_guard_and_final_seal'"
    )
    v31_final = source.rindex(
        "Invoke-RetainedV31SnapshotVerifier "
        "'terminal_immediately_before_archive_guard_and_final_seal'"
    )
    seal = source.rindex("Write-FinalPassSeal $passSealFile")
    assert v30_initial < v31_initial < v30_post < v31_post < receipt
    assert receipt < v30_final < v31_final < seal
    assert "Get-NonThrowingRetainedV30SnapshotReplay 'rejection_" in source
    assert "Get-NonThrowingRetainedV31SnapshotReplay 'rejection_" in source
    for variable in (
        "$retainedV30SnapshotCustodyFile",
        "$retainedV30SnapshotTerminalCustodyFile",
        "$retainedV31SnapshotCustodyFile",
        "$retainedV31SnapshotTerminalCustodyFile",
    ):
        reserved = source[source.index("$reserved=@(") :]
        reserved = reserved[: reserved.index("foreach($p in $reserved)")]
        assert variable in reserved
    pre_acceptance = source[source.index("$preAcceptancePins=@(") :]
    pre_acceptance = pre_acceptance[: pre_acceptance.index("$acceptance=")]
    assert "$retainedV30SnapshotCustodyFile" in pre_acceptance
    assert "$retainedV31SnapshotCustodyFile" in pre_acceptance
    protected = source[source.index("$protectedPins=@(") :]
    protected = protected[: protected.index("Assert-ProtectedEvidenceReplay")]
    assert "$retainedV30SnapshotTerminalCustodyPin" in protected
    assert "$retainedV31SnapshotTerminalCustodyPin" in protected
    seal_start = source.rindex("$seal=[ordered]@{")
    seal_object = source[seal_start:seal]
    assert "retained_v30_snapshot_final_replay=" in seal_object
    assert "retained_v31_snapshot_final_replay=" in seal_object
    assert "retained_v31_snapshot_custody_sha256=" in seal_object
    assert "retained_v31_snapshot_terminal_custody_sha256=" in seal_object
    receipt_start = source.rindex("$receipt=[ordered]@{")
    receipt_end = source.rindex("$receiptJson=")
    receipt_object = source[receipt_start:receipt_end]
    assert "$receipt['retained_v31_snapshot_custody_sha256']=" in receipt_object
    assert "$receipt['retained_v31_snapshot_custody_pin']=" in receipt_object
    assert (
        "$receipt['retained_v31_snapshot_terminal_custody_sha256']=" in receipt_object
    )
    assert "$receipt['retained_v31_snapshot_terminal_custody_pin']=" in receipt_object
    normal = source.rindex("schema='planora.muni-v32.overall-rejection.v6'")
    emergency = source.rindex("schema='planora.muni-v32.emergency-rejection.v3'")
    for region in (source[normal:emergency], source[emergency:]):
        assert "predecessor_evidence=$predecessorEvidence" in region
        assert "retained_v30_snapshot_rejection_replay=" in region
        assert "retained_v31_snapshot_rejection_replay=" in region
        assert "retained_v31_snapshot_custody_pin=" in region


def test_complete_predecessor_evidence_is_bound_to_plan_receipt_and_rejections() -> (
    None
):
    source = RUNNER.read_text("utf-8")
    assert "Get-ValidatedCompletePredecessorEvidence $true" in source
    assert "$predecessorEvidence=New-ExpectedCompletePredecessorEvidence" in source
    assert "$predecessorEvidence=New-ExpectedCombinedPredecessorEvidence" not in source
    assert "$predecessorPins.Count-ne61" in source
    assert "Assert-V28V29V30V31PassEvidenceAbsent" in source
    assert "$plan['predecessor_evidence']=$predecessorEvidence" in source
    assert "$receipt['predecessor_evidence']=$predecessorEvidence" in source
    assert (
        "$plan['v31_failure_evidence']=$predecessorEvidence.v31_failure_evidence"
        in source
    )
    assert (
        "$receipt['v31_failure_evidence']=$predecessorEvidence.v31_failure_evidence"
        in source
    )
    assert "complete-v28-v29-v30-v31-predecessor-evidence.v1" in source
    assert "nested_predecessor_hashes" in source
    assert "v31_failure_evidence_sha256" in source
    assert "EXACT_V28_V29_V30_V31_CUSTODY_VALIDATED_BEFORE_V32_LOCK" in source
    assert "EXACT_V28_V29_V30_CUSTODY_VALIDATED_BEFORE_V32_LOCK" not in source
    assert (
        "Get-NonThrowingCompletePredecessorReplay $predecessorEvidence "
        "$staleArchivePin" in source
    )
    assert "Complete predecessor rejection replay promotion rejected" in source
    assert "validated_pin_count=61" in source
    helper_start = source.index("function Get-NonThrowingCompletePredecessorReplay")
    helper_end = source.index("\nfunction ", helper_start + 1)
    replay_helper = source[helper_start:helper_end]
    assert "evidence=$null" in replay_helper
    assert "evidence=$Evidence" not in replay_helper
    resolver_start = source.index(
        "function Resolve-CompletePredecessorRejectionEvidence"
    )
    resolver_end = source.index("\nfunction ", resolver_start + 1)
    resolver = source[resolver_start:resolver_end]
    assert "$e['rejection_replay']=$r" in resolver
    assert "throw" not in resolver


def test_v32_cleanup_can_only_target_the_fresh_v32_root() -> None:
    cleanup = embedded_sources()["cleanupSource"]
    assert "prefix='/tmp/planora-muni-v32-canonical-tests-'" in cleanup
    assert "prefix='/tmp/planora-muni-v30-canonical-tests-'" not in cleanup
    assert "prefix='/tmp/planora-muni-v31-canonical-tests-'" not in cleanup
    assert f"/tmp/planora-muni-v31-canonical-tests-{V31_RUN_ID}" not in cleanup


def test_process_environment_and_launch_contract_are_explicit() -> None:
    source = RUNNER.read_text("utf-8")
    assert (
        "$env:COLUMNS='32768';$env:LINES='1000';$env:WSLENV='COLUMNS:LINES'" in source
    )
    assert "canonical_environment_cleared=$true" in source
    assert "canonical_monitor_contract=$canonicalMonitorContract" in source
    assert "canonical_token_sha256=$canonicalMonitorContract.token_sha256" in source
    assert "Resource monitor canonical token binding rejected" in source
    resource_monitor = embedded_sources()["resourceMonitorSource"]
    assert "canonical_token_sha256=str(c['canonical_token_sha256'])" in resource_monitor
    assert (
        resource_monitor.count("'canonical_token_sha256':canonical_token_sha256") == 2
    )
    assert source.count("$canonicalLaunchAttempted=$true") == 1
    assert (
        source.count("Start-SafeLoggedProcess $wsl $canonical $stdoutFile $stderrFile")
        == 1
    )


def test_fresh_v32_namespace_has_zero_artifacts_and_preserves_predecessors() -> None:
    builder = load_builder()
    prefix = f"muni-fspsx-v32-canonical-readonly-tests-{RUN_ID}"
    assert list((REPO / "output/diagnostic-receipts").glob(prefix + ".*")) == []
    assert not SHARED_LOCK.exists()
    assert ARCHIVE.exists()
    for pin in builder.V31_ARTIFACTS.values():
        assert (REPO / pin["path"]).is_file()
    for suffix in builder.V31_EXPECTED_ABSENT_SUFFIXES:
        assert not (REPO / f"{builder.V31_PREFIX}.{suffix}").exists()


def test_builder_is_deterministic_nonwsl_and_preserves_all_61_pins() -> None:
    builder = load_builder()
    pins = complete_predecessor_pins(builder)
    before_pins = {pin["path"]: windows_pin(REPO / pin["path"]) for pin in pins}
    before = RUNNER.read_bytes(), AUTH.read_bytes()
    source = BUILDER.read_text("utf-8")
    ast.parse(source)
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
    assert result.stderr == ""
    assert (RUNNER.read_bytes(), AUTH.read_bytes()) == before
    after_pins = {pin["path"]: windows_pin(REPO / pin["path"]) for pin in pins}
    assert after_pins == before_pins
    summary = json.loads(result.stdout)
    assert summary["status"] == "MUNI_V32_SUCCESSOR_GENERATED_STATIC_ONLY"
    assert summary["run_id"] == RUN_ID
    assert summary["predecessor_pins"] == 61
    assert summary["wsl_executed"] is False
    assert summary["canonical_suite_executed"] is False
    prefix = f"muni-fspsx-v32-canonical-readonly-tests-{RUN_ID}"
    assert list((REPO / "output/diagnostic-receipts").glob(prefix + ".*")) == []
    assert not SHARED_LOCK.exists()
