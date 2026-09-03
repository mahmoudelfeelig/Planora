from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "ca79220da7db46b6996fe1f05785dde7"
V28_RUN_ID = "e7cf1df162074402994a9d0ad763c824"
RUNNER = REPO / "scripts/run_muni_v29_canonical_tests.ps1"
BUILDER = REPO / "scripts/build_muni_v29_successor.py"
AUTH = (
    REPO
    / "output/diagnostic-receipts/muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json"
)
V28_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"
STALE_ARCHIVE = (
    REPO
    / f"output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-{V28_RUN_ID}.lock.json"
)
V28_PINS = {
    "builder": (
        "scripts/build_muni_v28_chain.ps1",
        44_779,
        "bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d",
    ),
    "tests": (
        "benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-tests.py",
        178_441,
        "f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab",
    ),
    "certificate": (
        "benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-certificate.json",
        31_261,
        "7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432",
    ),
    "freeze_manifest": (
        "benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-freeze-manifest.json",
        33_749,
        "f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6",
    ),
    "runner": (
        "scripts/run_muni_v28_canonical_tests.ps1",
        161_962,
        "fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60",
    ),
    "authorization": (
        "output/diagnostic-receipts/muni-fspsx-v28-canonical-tests-authorization-20260827T045149Z.receipt.json",
        8_024,
        "1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d",
    ),
    "claim": (
        f"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.claim.json",
        541,
        "f0ba301e63ba7e96938dabd3473106114d3b29ac2ad2090222609e8cbc1432e4",
    ),
    "rejection": (
        f"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.rejection.json",
        1_081,
        "2ecfb0ba960173f5662dd423e7fd1c72ace10f6c281bdd50e3dcef130179ee41",
    ),
    "static_evidence": (
        f"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}.static-adversarial.json",
        2_019,
        "93724cbeb1a76d199424309fee2a57df139bf70234ec93d8fc4fbbd6d5be7adf",
    ),
    "retained_lock": (
        "output/diagnostic-receipts/planora-shared-heavy-wsl.lock",
        370,
        "dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ps_executables() -> list[Path]:
    result = [Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")]
    pwsh = shutil.which("pwsh")
    if pwsh:
        result.append(Path(pwsh))
    return result


def invoke_static(executable: Path, switch: str) -> subprocess.CompletedProcess[str]:
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
        timeout=90,
    )


def test_authoritative_v28_failure_evidence_is_unchanged() -> None:
    for relative, size, expected_hash in V28_PINS.values():
        path = REPO / relative
        assert path.stat().st_size == size
        assert sha256(path) == expected_hash


def test_v28_failure_semantics_are_exact() -> None:
    prefix = (
        REPO
        / f"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-{V28_RUN_ID}"
    )
    rejection = json.loads(
        prefix.with_suffix(".rejection.json").read_text(encoding="utf-8")
    )
    assert rejection["status"] == "REJECTED_AUTHORIZATION_CONSUMED"
    assert rejection["pass_receipt_present"] is False
    assert rejection["pass_shutdown_seal_absent"] is True
    assert "being used by another process" in rejection["failure"]
    assert not prefix.with_suffix(".receipt.json").exists()
    assert not Path(str(prefix) + ".pass-publication-shutdown-seal.json").exists()


def test_authorization_binds_successor_and_predecessor() -> None:
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    assert auth["schema"] == "planora.itc2019.canonical-test-authorization.v9"
    assert auth["candidate"] == "muni_v29"
    assert auth["test_id"] == RUN_ID
    assert auth["runner"] == {
        "path": "scripts/run_muni_v29_canonical_tests.ps1",
        "size": RUNNER.stat().st_size,
        "sha256": sha256(RUNNER),
    }
    assert auth["successor_admission"]["builder"]["sha256"] == sha256(BUILDER)
    assert auth["successor_admission"]["tests"]["sha256"] == sha256(Path(__file__))
    assert set(auth["pinned_v28_files"]) == set(V28_PINS)
    for name, (relative, size, expected_hash) in V28_PINS.items():
        assert auth["pinned_v28_files"][name] == {
            "path": relative,
            "size": size,
            "sha256": expected_hash,
        }
    predecessor = auth["predecessor_failure"]
    assert predecessor["run_id"] == V28_RUN_ID
    assert predecessor["status"] == "REJECTED_AUTHORIZATION_CONSUMED"
    assert predecessor["pass_receipt_absent"] is True
    assert predecessor["shutdown_seal_absent"] is True
    reconciliation = auth["stale_lock_reconciliation"]
    assert reconciliation["source_sha256"] == sha256(V28_LOCK)
    assert reconciliation["owner_pid"] == 1140
    assert reconciliation["delete_authorized"] is False
    assert reconciliation["mismatch_or_race"] == "REJECT"
    assert auth["heavy_gate"]["lock_mode"] == (
        "CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash"
    )
    evidence_contract = auth["evidence_contract"]
    assert (
        evidence_contract[
            "complete_predecessor_evidence_bound_to_plan_pass_and_all_rejections"
        ]
        is True
    )
    assert evidence_contract["predecessor_live_pins_in_protected_replay_sets"] is True
    assert (
        evidence_contract[
            "predecessor_pass_absence_replayed_through_final_pass_seal_publication"
        ]
        is True
    )
    assert evidence_contract["authoritative_archive_pin_never_resampled"] is True
    assert (
        evidence_contract[
            "terminal_archived_lock_identity_replay_bound_by_final_pass_seal"
        ]
        is True
    )
    assert (
        evidence_contract[
            "terminal_archived_lock_read_guard_held_through_final_pass_seal_flush"
        ]
        is True
    )
    assert (
        evidence_contract["final_pass_seal_create_only_durable_last_operation"] is True
    )


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_emit_expected_authorization_replays_exactly(executable: Path) -> None:
    result = invoke_static(executable, "-EmitExpectedAuthorization")
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert json.loads(result.stdout) == json.loads(AUTH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_static_self_test_preserves_closure_and_reproduces_lock_bug(
    executable: Path,
) -> None:
    result = invoke_static(executable, "-StaticSelfTest")
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["canonical_suite_executed"] is False
    assert evidence["wsl_executed"] is False
    assert evidence["legacy_rows"] == 48
    assert evidence["frozen_closure"] == "PASS"
    assert json.loads(AUTH.read_text(encoding="utf-8"))["canonical_contract"] == {
        "unique_tests": 119,
        "expected_passes": 117,
        "expected_skips": 2,
        "expected_failures": 0,
        "expected_errors": 0,
        "identity_result_digest": "d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa",
        "strict_stderr_grammar": True,
        "exact_skip_identities": {
            "__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages": "heavy sealed-runtime import probe disabled by test contract",
            "__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs": "real sealed chain admission disabled by test contract",
        },
    }
    regression = evidence["lock_regression"]
    assert regression["v28_path_reopen_self_sharing_failure"] == "REPRODUCED"
    assert regression["v29_same_handle_seek_read_hash"] == "PASS"
    assert regression["v29_delete_on_close"] == "PASS"
    assert regression["stale_lock_atomic_move_while_held"] == "PASS"
    assert regression["identical_bytes_archive_replacement_rejected"] == "PASS"
    assert evidence["stale_lock_model"]["mutations_rejected"] == 6
    assert evidence["predecessor_evidence_model"] == (
        "10_AUTHORIZED_9_LIVE_PLUS_RETAINED_LOCK_AND_PASS_ABSENCE_VALIDATED"
    )


def test_runner_uses_only_same_handle_for_live_lock_bytes() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    acquire = source.rindex("$lockStream=New-Object IO.FileStream($sharedLockPath")
    release = source.rindex("Release-HeavyLock $lockStream $lockHash")
    live_region = source[acquire:release]
    assert "[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose" in live_region
    assert "Assert-HeldLockPath $lockStream $lockBytes $lockHash" in live_region
    assert "Get-Sha256 $sharedLockPath" not in live_region
    assert "Get-Content -LiteralPath $sharedLockPath" not in live_region
    assert source.index("Reconcile-PinnedV28StaleLock") < acquire
    assert "[IO.File]::Move($sharedLockPath,$staleArchivePath)" in source
    assert "$staleArchivePin=$staleReconciliation.archive_pin" in source
    assert "$staleArchivePin=Get-LocalEvidencePin $staleArchivePath" not in source


def test_complete_predecessor_bundle_is_bound_to_every_terminal_receipt() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "schema='planora.muni-v29.complete-v28-predecessor-evidence.v1'" in source
    assert "$preAcceptancePins=@($predecessorPins)+@(" in source
    assert "$plan['predecessor_v28_evidence']=$predecessorEvidence" in source
    assert "$receipt['predecessor_v28_evidence']=$predecessorEvidence" in source
    assert "predecessor_v28_evidence=$predecessorEvidence" in source
    assert "schema='planora.muni-v29.overall-rejection.v5'" in source
    assert "schema='planora.muni-v29.emergency-rejection.v2'" in source
    normal_rejection = source.rindex("schema='planora.muni-v29.overall-rejection.v5'")
    emergency_rejection = source.rindex(
        "schema='planora.muni-v29.emergency-rejection.v2'"
    )
    assert (
        "predecessor_v28_evidence=$predecessorEvidence"
        in source[normal_rejection:emergency_rejection]
    )
    assert (
        "predecessor_v28_evidence=$predecessorEvidence" in source[emergency_rejection:]
    )
    assert "Get-NonThrowingV28RejectionReplay" in source[normal_rejection - 1000 :]


def test_archive_identity_is_replayed_before_create_only_final_pass_seal() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    final_replay = source.rindex("$finalReplay=Assert-FinalEvidenceReplay")
    terminal_replay = source.rindex(
        "$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard "
        "$staleArchivePin 'terminal_before_create_only_final_pass_seal'"
    )
    seal_write = source.rindex(
        "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream"
    )
    catch = source.index("\n}\ncatch{", seal_write)
    assert final_replay < terminal_replay < seal_write < catch
    terminal_region = source[terminal_replay:seal_write]
    assert terminal_region.count("Open-TerminalArchivedStaleLockGuard") == 1
    assert (
        source[
            seal_write
            + len(
                "Write-FinalPassSeal $passSealFile $sealJson "
                "$terminalArchiveGuard.Stream"
            ) : catch
        ].strip()
        == ""
    )
    assert "Write-NewUtf8 $passSealFile" not in source
    assert "$decision='PASS'" not in source
    assert "schema='planora.muni-v29.pass-publication-shutdown-seal.v2'" in source
    assert (
        "publication_mechanism='FileMode.CreateNew_write_FlushTrue_as_last_fallible_operation_with_archived_lock_read_guard'"
        in source
    )
    writer = source[source.index("function Write-FinalPassSeal") :]
    writer = writer[: writer.index("\nfunction ", 1)]
    assert "[IO.FileMode]::CreateNew" in writer
    assert "$stream.Flush($true);$durablyFlushed=$true" in writer
    assert "Assert-HeldStreamBytes $ArchiveGuard" in writer
    guard = source[source.index("function Open-TerminalArchivedStaleLockGuard") :]
    guard = guard[: guard.index("\nfunction ", 1)]
    assert "[IO.FileAccess]::Read,[IO.FileShare]::Read" in guard
    assert "guard_share='Read_only_blocks_write_and_delete'" in guard
    assert "Assert-V28PassEvidenceAbsent" in source
    assert "Assert-LocalEvidencePin $ExpectedPin" in source


def test_all_embedded_python_programs_parse() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    matches = re.findall(
        r"\$[A-Za-z][A-Za-z0-9]*Source\s*=\s*@'\n(.*?)\n'@", source, re.DOTALL
    )
    assert len(matches) == 5
    for program in matches:
        ast.parse(program)


def test_fresh_run_is_unconsumed_and_stale_lock_not_reconciled_by_static_tests() -> (
    None
):
    prefix = f"muni-fspsx-v29-canonical-readonly-tests-{RUN_ID}"
    artifacts = list((REPO / "output/diagnostic-receipts").glob(prefix + ".*"))
    assert artifacts == []
    assert V28_LOCK.exists()
    assert not STALE_ARCHIVE.exists()


def test_builder_is_deterministic_and_static_only() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert "wsl.exe" not in source.lower()
    before = (RUNNER.read_bytes(), AUTH.read_bytes())
    result = subprocess.run(
        [str(REPO / ".venv/Scripts/python.exe"), "-B", str(BUILDER)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert (RUNNER.read_bytes(), AUTH.read_bytes()) == before
    summary = json.loads(result.stdout)
    assert summary["run_id"] == RUN_ID
    assert summary["wsl_executed"] is False
    assert summary["canonical_suite_executed"] is False
