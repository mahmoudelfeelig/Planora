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
GATE = REPO / "scripts/run_muni_v33_terminal_gate_once.ps1"
RUN_ID = "2339df35f57e441a8f92bd1f890fa68f"
RUNNER = REPO / "scripts/run_muni_v33_canonical_tests.ps1"
AUTH = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-canonical-tests-authorization-20260828T141639Z.receipt.json"
)
PRIMARY_REVIEW = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-independent-review-20260828T180735Z.receipt.json"
)
GATE_REVIEW = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-terminal-gate-independent-review-20260828T181500Z.receipt.json"
)
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"
V33_PREFIX = f"muni-fspsx-v33-canonical-readonly-tests-{RUN_ID}."
ZERO_EVIDENCE = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v32-canonical-readonly-tests-"
    "4dc45edcd74446909290afadd5d3ecf0.mutation-watch.wrapper.stdout.log"
)


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
        "$a=[System.Management.Automation.Language.Parser]::ParseFile("
        "$p,[ref]$t,[ref]$e);"
        "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1};"
        "$c=@($a.FindAll({param($n)"
        "$n-is[System.Management.Automation.Language.CommandAst]},$true));"
        "$d=@($c|Where-Object{$null-eq$_.GetCommandName()});"
        '"PARSE_OK commands=$($c.Count) dynamic=$($d.Count)"'
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
    assert result.stdout.startswith("PARSE_OK commands=")


@pytest.mark.parametrize("executable", ps_executables(), ids=lambda path: path.name)
def test_exact_guard_reader_hashes_zero_length_evidence(executable: Path) -> None:
    escaped_gate = str(GATE).replace("'", "''")
    escaped_zero = str(ZERO_EVIDENCE).replace("'", "''")
    command = (
        f"$gate='{escaped_gate}';$zero='{escaped_zero}';"
        "$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile("
        "$gate,[ref]$t,[ref]$e);if($e.Count){exit 1};"
        "foreach($name in @('Get-OuterBytesSha256','Read-OuterGuardBytes')){"
        "$f=@($a.FindAll({param($n)"
        "$n-is[Management.Automation.Language.FunctionDefinitionAst]-and"
        "$n.Name-ceq$name},$true));if($f.Count-ne1){exit 2};"
        "Invoke-Expression $f[0].Extent.Text};"
        "$s=New-Object IO.FileStream($zero,[IO.FileMode]::Open,"
        "[IO.FileAccess]::Read,[IO.FileShare]::Read);try{"
        "$g=[pscustomobject]@{Pin=[pscustomobject]@{path='zero'};Stream=$s};"
        "$b=Read-OuterGuardBytes $g;$h=Get-OuterBytesSha256 $b;"
        "if($b.GetType().FullName-cne'System.Byte[]'-or$b.Length-ne0-or"
        "$h-cne'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'"
        "){exit 3};'ZERO_GUARD_OK'}finally{$s.Dispose()}"
    )
    result = subprocess.run(
        [str(executable), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.strip() == "ZERO_GUARD_OK"


def test_runtime_hash_parameters_are_mandatory_and_not_embedded() -> None:
    source = GATE.read_text("utf-8")
    assert source.count("[Parameter(Mandatory = $true)]") == 2
    assert source.count("[ValidatePattern('^[0-9a-f]{64}$')]") == 2
    assert "[string]$ExpectedSelfHash" in source
    assert "[string]$ExpectedGateReviewHash" in source
    assert "$ExpectedSelfHash -cnotmatch '^[0-9a-f]{64}$'" in source
    assert "$ExpectedGateReviewHash -cnotmatch '^[0-9a-f]{64}$'" in source
    assert str(GATE_REVIEW.relative_to(REPO)).replace("/", "\\") in source
    assert sha256(GATE) not in source
    assert "$expectedSelfHash =" not in source
    assert "$expectedGateReviewHash =" not in source


def test_gate_pins_exact_successor_and_primary_review() -> None:
    review = json.loads(PRIMARY_REVIEW.read_text("utf-8"))
    assert review["schema"] == "planora.muni-v33.independent-review.v1"
    assert review["status"] == "GO"
    assert review["run_id"] == RUN_ID
    assert review["blockers"] == []
    assert review["predecessor_observations"]["validated_pin_count"] == 89
    assert review["predecessor_observations"]["guardable_ordinary_pin_count"] == 88
    assert review["predecessor_observations"]["archive_replay_only_pin_count"] == 1
    assert review["fresh_state_observations"]["v33_run_artifact_count"] == 0
    assert review["fresh_state_observations"]["shared_lock_present"] is False
    for expected in review["frozen_quartet"].values():
        assert windows_pin(REPO / expected["path"]) == expected

    source = GATE.read_text("utf-8")
    assert f"$expectedRunnerHash = '{sha256(RUNNER)}'" in source
    assert f"$expectedAuthorizationHash = '{sha256(AUTH)}'" in source
    assert f"$expectedPrimaryReviewHash = '{sha256(PRIMARY_REVIEW)}'" in source
    primary_pin = windows_pin(PRIMARY_REVIEW)
    for key in ("size", "sha256", "file_id", "last_write_utc_ticks"):
        value = primary_pin[key]
        rendered = (
            f"{key} = '{value}'" if isinstance(value, str) else f"{key} = {value}"
        )
        assert rendered in source


def test_primary_review_semantics_are_materially_replayed() -> None:
    source = GATE.read_text("utf-8")
    required = (
        "carried_through_v31_pin_count -ne 61",
        "direct_v32_source_provenance_artifact_pin_count -ne 28",
        "guardable_ordinary_pin_count -ne 88",
        "archive_replay_only_pin_count -ne 1",
        "v32_present_artifact_count -ne 20",
        "v32_expected_absent_artifact_count -ne 13",
        "v32_resource_launch_attempted",
        "v32_canonical_launch_attempted",
        "complete_predecessor_evidence_bound_to_plan_pass_ordinary_rejection_emergency_rejection_and_seal",
        "whole_document_predecessor_custody_exact_byte_replayed_from_held_guard",
        "predecessor_custody_guard_held_through_pass_or_rejection_publication",
        "retained_v30_v31_v32_initial_post_cleanup_rejection_and_final_replays_bound",
        "terminal_archived_lock_guard_held_through_final_seal_flush",
        "final_seal_create_only_durable_and_last_fallible_operation",
        "stable_log_reader_restrictive_read_share_guard",
        "stable_log_reader_same_held_handle_exact_prefix_replay",
        "stable_log_reader_integrity_failures_terminal_and_outside_retry_catches",
        "three_authenticated_resource_monitor_readiness_children",
        "first_two_readiness_children_minimum_separation_seconds -ne 5",
    )
    for marker in required:
        assert marker in source


def test_all_95_streams_use_restrictive_same_handle_guards() -> None:
    source = GATE.read_text("utf-8")
    assert "[IO.FileShare]::Read" in source
    assert "[IO.FileShare]::ReadWrite" not in source
    assert "[IO.FileShare]::Delete" not in source
    assert "Get-OuterSha256" not in source
    assert "return ,$bytes" in source
    assert "Get-OuterBytesSha256 (Read-OuterGuardBytes $Guard)" in source
    assert "$evidenceGuards.Count -ne 93" in source
    assert "$heldGuards.Count -ne 95" in source
    assert "$pins.Count -ne 89" in source
    assert "$archivePins.Count -ne 1 -or $ordinaryPins.Count -ne 88" in source
    assert source.count("Assert-GuardCensus") >= 4
    assert source.count("Assert-FinalArchivedStaleLockIdentity") == 2
    assert "Open-OuterHashGuard $PSCommandPath $ExpectedSelfHash" in source
    assert "Open-OuterHashGuard $gateReviewPath $ExpectedGateReviewHash" in source
    assert "Assert-GateReviewReceipt $gateReviewGuard $selfGuard" in source


def test_gate_review_receipt_closes_the_runtime_hash_chain() -> None:
    source = GATE.read_text("utf-8")
    assert (
        "GO_FOR_EXACTLY_ONE_TERMINAL_GATE_INVOCATION_"
        "WITH_SUPPLIED_SELF_AND_REVIEW_HASHES" in source
    )
    assert (
        "$review.primary_independent_review_sha256 -cne $expectedPrimaryReviewHash"
        in source
    )
    assert "$review.frozen_successor.runner_sha256 -cne $expectedRunnerHash" in source
    assert (
        "$review.frozen_successor.authorization_sha256 "
        "-cne $expectedAuthorizationHash" in source
    )
    assert "expected_hash_parameters_mandatory_and_lowercase_sha256" in source
    assert "same_handle_restrictive_read_guards" in source
    assert "final_exact_89_pin_array_replay" in source
    assert "no_automatic_retry" in source
    assert "Assert-PinEqual $review.frozen_gate_pair.gate $SelfGuard.Pin" in source


def test_three_authenticated_readiness_children_have_monotonic_separation() -> None:
    source = GATE.read_text("utf-8")
    calls = re.findall(
        r"\$sample([123])\s*=\s*Invoke-ResourceMonitorReadinessChild\s+([123])\s+\$readinessClock",
        source,
    )
    assert calls == [("1", "1"), ("2", "2"), ("3", "3")]
    assert source.count("-ResourceMonitorReadinessSelfTest") == 1
    assert "resource-monitor-readiness-self-test.v1" in source
    assert "$result.namespace_permission_denials -ne 0" in source
    assert "$result.admitted_infrastructure_identities -lt 1" in source
    assert (
        "$result.admitted_infrastructure_sha256 -cnotmatch '^[0-9a-f]{64}$'" in source
    )
    assert (
        "while (($readinessClock.ElapsedMilliseconds - $sample1.started_monotonic_milliseconds) -lt 5000)"
        in source
    )
    assert "$firstStartSeparation -lt 5000" in source
    first = source.index("$sample1 = Invoke-ResourceMonitorReadinessChild")
    second = source.index("$sample2 = Invoke-ResourceMonitorReadinessChild")
    retained = source.index("$retained = Invoke-RetainedSnapshotsChild")
    third = source.index("$sample3 = Invoke-ResourceMonitorReadinessChild")
    assert first < second < retained < third


def test_combined_retained_v30_v31_v32_replay_is_exact() -> None:
    source = GATE.read_text("utf-8")
    assert source.count("-RetainedPredecessorSnapshotsSelfTest") == 1
    assert "isolated_nonconsuming_v30_preflight" in source
    assert "isolated_nonconsuming_v31_preflight" in source
    assert "isolated_nonconsuming_v32_preflight" in source
    assert "$snapshot.row.files -ne 3146" in source
    assert "$snapshot.row.directories -ne 368" in source
    assert "$snapshot.row.bytes -ne 190900047" in source
    assert "b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb" in source
    assert "e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d" in source
    assert "0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3" in source
    assert "retained_v30_snapshot = $retained.v30" in source
    assert "retained_v31_snapshot = $retained.v31" in source
    assert "retained_v32_snapshot = $retained.v32" in source


def test_final_replay_is_exact_and_default_call_is_unique_and_last() -> None:
    source = GATE.read_text("utf-8")
    assert "$finalPredecessorArrayJson -cne $initialPredecessorArrayJson" in source
    assert "$finalPredecessorArrayHash -cne $initialPredecessorArrayHash" in source
    assert "Assert-FreshV33State 'outer_immediately_before_default'" in source
    assert "Assert-V33RootAbsent 'outer_immediately_before_default'" in source
    assert source.count("& $runner") == 1
    call = source.rindex("& $runner")
    count_zero = source.rindex("$defaultInvocationCount = 0", 0, call)
    check_zero = source.rindex("if ($defaultInvocationCount -ne 0)", 0, call)
    count_one = source.rindex("$defaultInvocationCount = 1", 0, call)
    finally_block = source.rindex("\nfinally {")
    assert count_zero < check_zero < count_one < call < finally_block
    assert source[count_one + len("$defaultInvocationCount = 1") : call].strip() == ""
    assert ". $runner -StaticSelfTest" in source
    assert source.count(". $runner -StaticSelfTest") == 1
    assert "automatic retry" not in source.lower()


def test_current_state_is_still_fresh_and_unconsumed() -> None:
    assert not SHARED_LOCK.exists()
    artifacts = [
        path
        for path in (REPO / "output/diagnostic-receipts").iterdir()
        if path.name.startswith(V33_PREFIX)
    ]
    assert artifacts == []


def test_future_gate_review_receipt_matches_live_gate_pair_when_present() -> None:
    if not GATE_REVIEW.exists():
        return
    review = json.loads(GATE_REVIEW.read_text("utf-8"))
    assert review["schema"] == "planora.muni-v33.terminal-gate-independent-review.v1"
    assert review["status"] == "GO"
    assert review["run_id"] == RUN_ID
    assert review["blockers"] == []
    assert review["primary_independent_review_sha256"] == sha256(PRIMARY_REVIEW)
    assert windows_pin(GATE) == review["frozen_gate_pair"]["gate"]
    assert windows_pin(Path(__file__)) == review["frozen_gate_pair"]["tests"]
