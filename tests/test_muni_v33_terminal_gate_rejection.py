from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "2339df35f57e441a8f92bd1f890fa68f"
RECEIPT = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-terminal-gate-rejection-20260830T000900Z.receipt.json"
)
GATE = REPO / "scripts/run_muni_v33_terminal_gate_once.ps1"
RUNNER = REPO / "scripts/run_muni_v33_canonical_tests.ps1"
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"
V33_PREFIX = f"muni-fspsx-v33-canonical-readonly-tests-{RUN_ID}."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "path": path.relative_to(REPO).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "file_id": match.group(1).lower(),
        "last_write_utc_ticks": (path.stat().st_mtime_ns // 100 + 621355968000000000),
    }


def load_strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_or_case_alias(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        seen: set[str] = set()
        for key, value in pairs:
            folded = key.casefold()
            assert folded not in seen, f"duplicate or case-alias JSON key: {key}"
            seen.add(folded)
            result[key] = value
        return result

    return json.loads(
        path.read_text("utf-8"), object_pairs_hook=reject_duplicate_or_case_alias
    )


def test_rejection_receipt_is_strict_and_classifies_only_the_gate_attempt() -> None:
    raw = RECEIPT.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    receipt = load_strict_json(RECEIPT)
    assert receipt["schema"] == "planora.muni-v33.terminal-gate-rejection.v1"
    assert receipt["status"] == "REJECTED_TERMINAL_GATE_INVOCATION_CONSUMED"
    assert receipt["candidate"] == "muni_v33"
    assert receipt["run_id"] == RUN_ID
    assert receipt["decision"] == "NO_RETRY_BUILD_NEW_SUCCESSOR"
    assert receipt["automatic_retry_authorized"] is False
    assert receipt["receipt_publication_blockers"] == []
    assert receipt["successor_admission_blockers"] == [
        "authenticated_v33_root_reconciliation_pending",
        "host_wsl_storage_stability_not_established",
    ]


def test_failure_is_the_exact_precanonical_wsl_cold_start_timeout() -> None:
    receipt = load_strict_json(RECEIPT)
    failure = receipt["failure"]
    assert failure["phase"] == "outer_before_authenticated_live_gates"
    assert failure["operation"] == "Assert-V33RootAbsent"
    assert (
        failure["context"] == "v33 root absence outer_before_authenticated_live_gates"
    )
    assert failure["wsl_exit_code"] == -1
    assert failure["host_process_exit_code"] == 1
    assert failure["wsl_error_code"] == (
        "Wsl/Service/CreateInstance/HCS_E_CONNECTION_TIMEOUT"
    )
    assert failure["classification"] == "HOST_WSL_INFRASTRUCTURE_COLD_START_TIMEOUT"
    assert failure["canonical_solver_or_test_failure"] is False
    assert "response was not received" in failure["normalized_message"]


def test_lifecycle_proves_default_claim_and_canonical_were_never_attempted() -> None:
    receipt = load_strict_json(RECEIPT)
    lifecycle = receipt["lifecycle"]
    assert lifecycle == {
        "terminal_gate_invocation_attempted": True,
        "gate_self_and_review_guards_accepted": True,
        "successor_and_primary_review_guards_accepted": True,
        "runner_static_self_test_completed": True,
        "initial_authorization_state_replayed": True,
        "complete_predecessor_pins_validated": 89,
        "ordinary_predecessor_guards_held": 88,
        "total_held_guards": 95,
        "retained_v28_archive_replayed": True,
        "fresh_v33_artifact_and_lock_state_validated": True,
        "v33_root_absence_check_attempted": True,
        "v33_root_absence_verified": False,
        "resource_readiness_children_started": 0,
        "retained_snapshot_child_started": False,
        "final_predefault_replay_reached": False,
        "outer_pass_envelope_emitted": False,
        "default_invocation_counter_set": False,
        "default_runner_invocation_attempted": False,
        "atomic_claim_creation_attempted": False,
        "shared_lock_acquisition_attempted": False,
        "resource_monitor_launch_attempted": False,
        "canonical_launch_attempted": False,
        "canonical_suite_executed": False,
        "pass_publication_attempted": False,
    }
    post = receipt["post_failure_state"]
    assert post["canonical_namespace_artifact_count"] == 0
    assert post["claim_present"] is False
    assert post["pass_receipt_present"] is False
    assert post["pass_seal_present"] is False
    assert post["runner_rejection_present"] is False
    assert post["runner_emergency_rejection_present"] is False
    assert post["shared_lock_present"] is False
    assert post["v33_root_state"] == "UNKNOWN_WSL_DISTRIBUTION_DID_NOT_START"


def test_source_order_independently_supports_the_recorded_lifecycle() -> None:
    gate = GATE.read_text("utf-8")
    runner = RUNNER.read_text("utf-8")
    gate_order = [
        "Assert-GateReviewReceipt $gateReviewGuard $selfGuard",
        ". $runner -StaticSelfTest",
        "$authorizationState = Get-AuthorizationState",
        "$predecessor = Get-ValidatedCompletePredecessorEvidence $true",
        "Assert-GuardCensus",
        "Assert-FreshV33State 'outer_before_authenticated_live_gates'",
        "Assert-V33RootAbsent 'outer_before_authenticated_live_gates'",
        "$sample1 = Invoke-ResourceMonitorReadinessChild",
        "& $runner",
    ]
    indices: list[int] = []
    cursor = 0
    for witness in gate_order:
        index = gate.index(witness, cursor)
        indices.append(index)
        cursor = index + len(witness)
    assert indices == sorted(indices)
    static_start = runner.index("if($StaticSelfTest){")
    static_return = runner.index("    return\n}", static_start)
    claim_attempt = runner.index("$claimPublicationStarted=$true", static_return)
    assert static_start < static_return < claim_attempt


def test_all_preexisting_evidence_pins_still_match_exact_live_files() -> None:
    receipt = load_strict_json(RECEIPT)
    for pin in receipt["evidence_pins"].values():
        assert windows_pin(REPO / pin["path"]) == pin


def test_custody_test_is_self_pinned_and_namespace_remains_unconsumed() -> None:
    receipt = load_strict_json(RECEIPT)
    assert windows_pin(Path(__file__)) == receipt["custody_test_pin"]
    artifacts = [
        path
        for path in (REPO / "output/diagnostic-receipts").iterdir()
        if path.name.startswith(V33_PREFIX)
    ]
    assert artifacts == []
    assert not SHARED_LOCK.exists()


def test_post_failure_host_observation_does_not_overclaim_root_absence() -> None:
    receipt = load_strict_json(RECEIPT)
    observation = receipt["post_failure_host_observation"]
    assert observation["wsl_service_status"] == "Running"
    assert observation["vmcompute_service_status"] == "Running"
    assert observation["default_distribution"] == "Ubuntu"
    assert observation["ubuntu_state"] == "Stopped"
    assert observation["docker_desktop_state"] == "Running"
    assert observation["wsl_list_exit_code"] == 0
    assert observation["ubuntu_was_started_for_diagnosis"] is False
    assert observation["wsl_or_docker_was_restarted"] is False
    assert observation["root_absence_inference_permitted"] is False


def test_successor_contract_requires_exact_reconciliation_and_full_custody() -> None:
    receipt = load_strict_json(RECEIPT)
    requirements = receipt["successor_requirements"]
    assert requirements[
        "require_authenticated_v33_root_absence_or_exact_read_only_custody_before_v34_admission"
    ]
    assert requirements["bind_all_rejection_receipt_evidence_pins_and_custody_test"]
    assert requirements["bind_this_rejection_receipt_and_its_independent_review"]
    assert requirements[
        "require_authenticated_ubuntu_cold_start_readiness_before_one_shot_authority"
    ]
    assert requirements["automatic_retry_forbidden"]
