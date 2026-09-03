from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "e358bc6417224fe6a329ad3775853f01"
V29_RUN_ID = "ca79220da7db46b6996fe1f05785dde7"
BUILDER = REPO / "scripts/build_muni_v30_successor.py"
RUNNER = REPO / "scripts/run_muni_v30_canonical_tests.ps1"
AUTH = (
    REPO
    / "output/diagnostic-receipts/muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z.receipt.json"
)
ARCHIVE = (
    REPO
    / "output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json"
)
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("muni_v30_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ps_executables() -> list[Path]:
    executables = [Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")]
    if pwsh := shutil.which("pwsh"):
        executables.append(Path(pwsh))
    return executables


def invoke_runner(executable: Path, switch: str) -> subprocess.CompletedProcess[str]:
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
        timeout=120,
    )


def test_all_predecessor_bytes_and_windows_identities_are_frozen() -> None:
    builder = load_builder()
    pins = [
        *builder.V29_SOURCES.values(),
        *builder.V29_ARTIFACTS.values(),
        builder.ARCHIVE_PIN,
    ]
    assert len(pins) == 16
    for expected in pins:
        path = REPO / expected["path"]
        assert path.stat().st_size == expected["size"]
        assert sha256(path) == expected["sha256"]
        result = subprocess.run(
            ["fsutil.exe", "file", "queryfileid", str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        match = re.search(r"File ID is 0x([0-9a-fA-F]{32})", result.stdout)
        assert match and match.group(1).lower() == expected["file_id"]
        ticks = path.stat().st_mtime_ns // 100 + 621355968000000000
        assert ticks == expected["last_write_utc_ticks"]


def test_v29_failure_is_consumed_precanonical_and_not_retryable() -> None:
    builder = load_builder()
    artifacts = builder.V29_ARTIFACTS
    claim = json.loads((REPO / artifacts["claim"]["path"]).read_text(encoding="utf-8"))
    rejection = json.loads(
        (REPO / artifacts["rejection"]["path"]).read_text(encoding="utf-8")
    )
    release = json.loads(
        (REPO / artifacts["heavy_lock_release"]["path"]).read_text(encoding="utf-8")
    )
    rows = [
        json.loads(line)
        for line in (REPO / artifacts["watch_log"]["path"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert claim["run_id"] == V29_RUN_ID
    assert claim["failure_consumes_authorization"] is True
    assert rejection["status"] == "REJECTED_AUTHORIZATION_CONSUMED"
    assert rejection["pass_receipt_present"] is False
    assert rejection["pass_shutdown_seal_absent"] is True
    assert "ReadAllText" in rejection["failure"]
    assert "being used by another process" in rejection["failure"]
    assert "watcher_stop=Watcher wrapper rejected" in rejection["failure"]
    assert release["decision"] == "REJECTED"
    assert release["same_handle_verified"] is True
    assert release["lock_path_absent"] is True
    assert [row["kind"] for row in rows] == ["ARMED"]
    assert not (REPO / builder.PREDECESSOR_CONTRACT["v29"]["pass_receipt"]).exists()
    assert not (REPO / builder.PREDECESSOR_CONTRACT["v29"]["pass_seal"]).exists()


def test_v29_rejection_carries_exact_v28_identity_bundle() -> None:
    builder = load_builder()
    rejection = json.loads(
        (REPO / builder.V29_ARTIFACTS["rejection"]["path"]).read_text(encoding="utf-8")
    )
    evidence = rejection["predecessor_v28_evidence"]
    canonical = json.dumps(evidence, separators=(",", ":"), ensure_ascii=False)
    assert (
        evidence["schema"]
        == builder.PREDECESSOR_CONTRACT["v28"]["embedded_evidence_schema"]
    )
    assert (
        hashlib.sha256(canonical.encode()).hexdigest()
        == builder.PREDECESSOR_CONTRACT["v28"]["embedded_evidence_sha256"]
    )
    assert (
        rejection["predecessor_v28_evidence_sha256"]
        == hashlib.sha256(canonical.encode()).hexdigest()
    )
    assert len(evidence["runtime"]["live_file_pins"]) == 9
    assert evidence["runtime"]["retained_lock_archive_pin"] == builder.ARCHIVE_PIN
    assert (
        evidence["runtime"]["stale_lock_reconciliation_sha256"]
        == builder.V29_ARTIFACTS["stale_lock_reconciliation"]["sha256"]
    )


def test_authorization_binds_successor_logs_and_complete_predecessor() -> None:
    builder = load_builder()
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    assert auth["schema"] == "planora.itc2019.canonical-test-authorization.v10"
    assert auth["candidate"] == "muni_v30"
    assert auth["test_id"] == RUN_ID
    assert auth["created_at_utc"] == "2026-08-28T10:14:48Z"
    assert auth["automatic_retry_authorized"] is False
    assert auth["runner"] == {
        "path": "scripts/run_muni_v30_canonical_tests.ps1",
        "size": RUNNER.stat().st_size,
        "sha256": sha256(RUNNER),
    }
    assert auth["successor_admission"]["builder"] == {
        "path": "scripts/build_muni_v30_successor.py",
        "size": BUILDER.stat().st_size,
        "sha256": sha256(BUILDER),
    }
    assert auth["successor_admission"]["tests"] == {
        "path": "tests/test_run_muni_v30_successor.py",
        "size": Path(__file__).stat().st_size,
        "sha256": sha256(Path(__file__)),
    }
    assert auth["predecessor_custody_contract"] == builder.PREDECESSOR_CONTRACT
    bridge = auth["log_bridge_contract"]
    assert bridge["watcher_and_resource_monitor_both_fixed"] is True
    assert bridge["legacy_lifetime_open_negative_baseline_required"] is True
    assert bridge["isolated_switch"] == "LogBridgeSelfTest"
    evidence = auth["evidence_contract"]
    assert (
        evidence[
            "complete_v28_v29_predecessor_evidence_bound_to_plan_pass_and_all_rejections"
        ]
        is True
    )
    assert evidence["all_predecessor_file_ids_and_timestamps_authorized"] is True
    assert evidence["retained_archive_validated_in_place_without_mutation"] is True
    assert (
        evidence["v28_v29_pass_absence_replayed_through_final_pass_seal_publication"]
        is True
    )
    assert evidence["final_pass_seal_create_only_durable_last_operation"] is True


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_expected_authorization_replays_exactly(executable: Path) -> None:
    result = invoke_runner(executable, "-EmitExpectedAuthorization")
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert json.loads(result.stdout) == json.loads(AUTH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_static_self_test_is_non_wsl_and_validates_combined_custody(
    executable: Path,
) -> None:
    result = invoke_runner(executable, "-StaticSelfTest")
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["canonical_suite_executed"] is False
    assert evidence["wsl_executed"] is False
    assert evidence["legacy_rows"] == 48
    assert evidence["frozen_closure"] == "PASS"
    assert evidence["predecessor_evidence_model"] == (
        "25_EXACT_IDENTITY_PINS_V28_V29_PLUS_DUAL_PASS_ABSENCE_VALIDATED"
    )
    assert evidence["cross_boundary_log_protocol"] == (
        "SHORT_LIVED_IDENTITY_CHECKED_APPEND_AND_STABLE_HOST_READ"
    )
    assert evidence["archived_predecessor_model"]["archive_mutation_performed"] is False


def embedded_sources() -> dict[str, str]:
    source = RUNNER.read_text(encoding="utf-8")
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"\$(?P<name>[A-Za-z][A-Za-z0-9]*Source)\s*=\s*@'\n(?P<body>.*?)\n'@",
            source,
            re.DOTALL,
        )
    }


def test_all_embedded_python_programs_parse() -> None:
    programs = embedded_sources()
    assert len(programs) == 7
    for program in programs.values():
        ast.parse(program)


def test_watcher_and_resource_logs_use_short_lived_identity_checked_append() -> None:
    programs = embedded_sources()
    for name in ("watcherSource", "resourceMonitorSource"):
        program = programs[name]
        assert "def reserve(path):" in program
        assert "os.O_CREAT|os.O_EXCL" in program
        assert "finally: os.close(fd)" in program
        assert "os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC" in program
        assert "os.O_NOFOLLOW" in program
        assert "os.fsync(fd)" in program
        assert "linked_after=os.lstat(path)" in program
        assert "publish_error(traceback.format_exc())" in program
        assert "log=open(" not in program
        assert "log.close()" not in program
        assert "error=open(" not in program
    assert (
        "def emit(row): append_bytes(log_path,log_identity,encode(row))"
        in programs["watcherSource"]
    )
    assert "append_bytes(log_path,log_identity" in programs["resourceMonitorSource"]


def test_host_log_reader_is_stable_bounded_and_writer_aware() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    region = source[source.index("if(-not('PlanoraV30NativeFileIdentity'") :]
    region = region[: region.index("function Get-WatcherLogState")]
    assert "AddSeconds(3)" in region
    assert "Text.UTF8Encoding($false,$true)" in region
    assert "PlanoraV30NativeFileIdentity" in region
    assert "GetFileInformationByHandle" in region
    assert "Get-HeldFileIdentity $stream $Label" in region
    assert "Get-HeldFileIdentity $probe ($Label+' path replay')" in region
    assert "[IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete" in region
    assert "$after.size-ne$before.size" in region
    assert "$pathIdentity.index-ne$before.index" in region
    assert "incomplete framing" in region
    assert "Test-WriterProcessLive $WriterProcess" in region
    assert "Get-WatcherRows $Watcher.Process" in source
    assert "Get-ResourceMonitorRows $Monitor.Process" in source
    assert "[IO.File]::ReadAllText($watchLogFile" not in source
    assert "[IO.File]::ReadAllText($resourceLogFile" not in source


def test_log_bridge_switch_is_real_isolated_and_noncanonical() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "[switch]$LogBridgeSelfTest" in source.splitlines()[0]
    branch = source[source.index("if($LogBridgeSelfTest){") :]
    branch = branch[: branch.index("if($StaticSelfTest){")]
    assert "$legacyLogBridgeSource" in branch
    assert "$fixedLogBridgeSource" in branch
    assert "Legacy lifetime-open DrvFS sharing failure was not reproduced" in branch
    assert "Read-StableUtf8Log" in branch
    assert "Fixed bridge did not overlap at least three stable host reads" in branch
    assert "rows=$rows.Count;samples=12;duplicates=0" in branch
    assert "canonical_suite_executed=$false" in branch
    assert "shared_lock_used=$false" in branch
    assert "Start-SafeLoggedProcess" not in branch
    assert "$sharedLockPath" not in branch


def test_archive_is_validated_in_place_and_cleanup_accepts_only_v30_root() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert ARCHIVE.exists()
    assert not SHARED_LOCK.exists()
    assert "Reconcile-PinnedV28StaleLock" not in source
    assert "[IO.File]::Move($sharedLockPath,$staleArchivePath)" not in source
    assert '$predecessorCustodyFile = "$prefix.predecessor-custody.json"' in source
    reserved = source[
        source.index("$reserved=@(") : source.index(
            "foreach($p in $reserved)", source.index("$reserved=@(")
        )
    ]
    assert "$predecessorCustodyFile" in reserved
    assert "$staleArchivePath" not in reserved
    cleanup = embedded_sources()["cleanupSource"]
    assert "prefix='/tmp/planora-muni-v30-canonical-tests-'" in cleanup
    assert "prefix='/tmp/planora-muni-v28-canonical-tests-'" not in cleanup


def test_combined_predecessor_is_bound_to_every_terminal_path() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert (
        "schema='planora.muni-v30.complete-v28-v29-predecessor-evidence.v1'" in source
    )
    assert "$predecessorPins.Count-ne25" in source
    assert "$preAcceptancePins=@($predecessorPins)+@(" in source
    assert "$plan['predecessor_evidence']=$predecessorEvidence" in source
    assert "$receipt['predecessor_evidence']=$predecessorEvidence" in source
    assert "$receipt['predecessor_custody_pin']=Get-LocalEvidencePin" in source
    assert "predecessor_evidence=$predecessorEvidence" in source
    assert "schema='planora.muni-v30.overall-rejection.v6'" in source
    assert "schema='planora.muni-v30.emergency-rejection.v3'" in source
    normal = source.rindex("schema='planora.muni-v30.overall-rejection.v6'")
    emergency = source.rindex("schema='planora.muni-v30.emergency-rejection.v3'")
    assert "predecessor_evidence=$predecessorEvidence" in source[normal:emergency]
    assert "predecessor_evidence=$predecessorEvidence" in source[emergency:]
    assert "Get-NonThrowingCombinedPredecessorReplay" in source[normal - 1200 :]
    assert "Assert-V28V29PassEvidenceAbsent" in source
    assert "$archiveReplayAtPass.v28_pass_absence" not in source
    assert "$archiveReplayAtPass.predecessor_pass_absence" in source


def test_new_lock_is_same_handle_only_and_custody_precedes_acquisition() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    custody = source.rindex("Write-NewUtf8 $predecessorCustodyFile")
    acquire = source.rindex("$lockStream=New-Object IO.FileStream($sharedLockPath")
    release = source.rindex("Release-HeavyLock $lockStream $lockHash")
    assert custody < acquire < release
    region = source[acquire:release]
    assert "[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose" in region
    assert "Assert-HeldLockPath $lockStream $lockBytes $lockHash" in region
    assert "Get-Sha256 $sharedLockPath" not in region
    assert "Get-Content -LiteralPath $sharedLockPath" not in region


def test_create_only_final_seal_is_last_fallible_success_operation() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    final_replay = source.rindex("$finalReplay=Assert-FinalEvidenceReplay")
    guard = source.rindex(
        "$terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard "
        "$staleArchivePin 'terminal_before_create_only_final_pass_seal'"
    )
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
    assert "Write-NewUtf8 $passSealFile" not in source
    writer = source[source.index("function Write-FinalPassSeal") :]
    writer = writer[: writer.index("\nfunction ", 1)]
    assert "[IO.FileMode]::CreateNew" in writer
    assert "$stream.Flush($true);$durablyFlushed=$true" in writer
    terminal = source[source.index("function Open-TerminalArchivedStaleLockGuard") :]
    terminal = terminal[: terminal.index("\nfunction ", 1)]
    assert "Assert-V28V29PassEvidenceAbsent" in terminal
    assert "[IO.FileAccess]::Read,[IO.FileShare]::Read" in terminal
    seal_object = source[source.rindex("$seal=[ordered]@{") : seal]
    assert "predecessor_custody_sha256=$predecessorCustodyHash" in seal_object


def test_fresh_v30_is_unconsumed() -> None:
    prefix = f"muni-fspsx-v30-canonical-readonly-tests-{RUN_ID}"
    artifacts = list((REPO / "output/diagnostic-receipts").glob(prefix + ".*"))
    assert artifacts == []
    assert not SHARED_LOCK.exists()
    assert ARCHIVE.exists()


def test_builder_is_deterministic_and_does_not_invoke_wsl() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert "wsl.exe" not in source.lower()
    before = RUNNER.read_bytes(), AUTH.read_bytes()
    result = subprocess.run(
        [str(REPO / ".venv/Scripts/python.exe"), "-B", str(BUILDER)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (RUNNER.read_bytes(), AUTH.read_bytes()) == before
    summary = json.loads(result.stdout)
    assert summary["run_id"] == RUN_ID
    assert summary["wsl_executed"] is False
    assert summary["log_bridge_executed"] is False
    assert summary["canonical_suite_executed"] is False
