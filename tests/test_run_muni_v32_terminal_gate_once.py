from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts/run_muni_v32_terminal_gate_once.ps1"
RUN_ID = "4dc45edcd74446909290afadd5d3ecf0"
RUNNER = REPO / "scripts/run_muni_v32_canonical_tests.ps1"
AUTH = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v32-canonical-tests-authorization-20260828T130114Z.receipt.json"
)
REVIEW = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v32-independent-review-20260828T135032Z.receipt.json"
)
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"


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


def ps_executables() -> list[Path]:
    ps5 = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    pwsh = shutil.which("pwsh")
    assert ps5.is_file()
    assert pwsh
    return [ps5, Path(pwsh)]


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_terminal_gate_parses_without_execution(executable: Path) -> None:
    escaped = str(GATE).replace("'", "''")
    command = (
        f"$p='{escaped}';$t=$null;$e=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        "$p,[ref]$t,[ref]$e);"
        "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1};"
        '"PARSE_OK $($t.Count)"'
    )
    result = subprocess.run(
        [
            str(executable),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("PARSE_OK ")


def test_terminal_gate_pins_the_exact_reviewed_quartet_and_review_receipt() -> None:
    review = json.loads(REVIEW.read_text("utf-8"))
    assert review["status"] == "GO"
    assert review["run_id"] == RUN_ID
    assert review["blockers"] == []
    assert review["fresh_state_observations"]["v32_run_artifact_count"] == 0
    assert review["fresh_state_observations"]["shared_lock_present"] is False
    for expected in review["frozen_quartet"].values():
        observed = windows_pin(REPO / expected["path"])
        assert observed == expected
    source = GATE.read_text("utf-8")
    assert f"$expectedRunnerHash = '{sha256(RUNNER)}'" in source
    assert f"$expectedAuthorizationHash = '{sha256(AUTH)}'" in source
    assert f"$expectedReviewHash = '{sha256(REVIEW)}'" in source
    review_pin = windows_pin(REVIEW)
    for key in ("size", "sha256", "file_id", "last_write_utc_ticks"):
        assert f"{key} = {review_pin[key]}" in source or (
            isinstance(review_pin[key], str)
            and f"{key} = '{review_pin[key]}'" in source
        )


def test_terminal_gate_holds_the_complete_guard_partition() -> None:
    source = GATE.read_text("utf-8")
    assert "Get-ValidatedCompletePredecessorEvidence $true" in source
    assert "Get-CompletePredecessorPinArray $predecessor" in source
    assert "$pins.Count -ne 61" in source
    assert "$archivePins.Count -ne 1 -or $ordinaryPins.Count -ne 60" in source
    assert "$guards.Count -ne 65" in source
    assert "@($guards.Pin.path | Sort-Object -Unique).Count -ne 65" in source
    assert source.count("foreach ($guard in $guards)") == 3
    assert source.count("Assert-OuterGuardPin $guard") == 3
    assert "Assert-FinalArchivedStaleLockIdentity $archivePins[0]" in source
    assert source.count("Assert-FinalArchivedStaleLockIdentity $archivePins[0]") == 2


def test_live_gate_is_fail_closed_and_retained_replay_is_combined() -> None:
    source = GATE.read_text("utf-8")
    assert "$ErrorActionPreference = 'Stop'" in source
    assert "$env:COLUMNS = '32768'" in source
    assert "$env:LINES = '1000'" in source
    assert "$env:WSLENV = 'COLUMNS:LINES'" in source
    assert "-RetainedPredecessorSnapshotsSelfTest" in source
    assert "isolated_nonconsuming_v30_preflight" in source
    assert "isolated_nonconsuming_v31_preflight" in source
    assert "$result.v30.inventory_sha256 -cne $expectedV30InventoryHash" in source
    assert "$result.v31.inventory_sha256 -cne $expectedV31InventoryHash" in source
    assert "[bool]$result.claim_created" in source
    assert "[bool]$result.v32_artifacts_created" in source
    assert source.count("Assert-FreshV32State") == 4
    assert source.count("Assert-V32RootAbsent") == 4
    assert "Start-Sleep -Seconds 5" in source
    assert "$separation.ElapsedMilliseconds -lt 5000" in source
    assert "$memory -lt 1900000" in source
    assert "@($census.rejected_workloads).Count -ne 0" in source


def test_exactly_one_default_invocation_is_last_inside_the_guarded_try() -> None:
    source = GATE.read_text("utf-8")
    assert source.count("& $runner") == 1
    call = source.rindex("& $runner")
    count_zero = source.rindex("$defaultInvocationCount = 0", 0, call)
    check_zero = source.rindex("if ($defaultInvocationCount -ne 0)", 0, call)
    count_one = source.rindex("$defaultInvocationCount = 1", 0, call)
    finally_block = source.rindex("\nfinally {")
    assert count_zero < check_zero < count_one < call < finally_block
    between = source[count_one + len("$defaultInvocationCount = 1") : call]
    assert between.strip() == ""
    guarded_try = source.index("\ntry {")
    assert guarded_try < call < finally_block
    assert "automatic retry" not in source.lower()
    assert not SHARED_LOCK.exists()
    prefix = f"muni-fspsx-v32-canonical-readonly-tests-{RUN_ID}."
    artifacts = [
        path
        for path in (REPO / "output/diagnostic-receipts").iterdir()
        if path.name.startswith(prefix)
    ]
    assert artifacts == []
