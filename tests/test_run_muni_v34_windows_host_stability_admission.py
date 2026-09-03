from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/run_muni_v34_windows_host_stability_admission.ps1"
ADMISSION_ID = "a5329b8ce4d7458ea26cb4351bb551fe"
RUN_ID = "3c3ed012febd407da5202423b2a67d32"
RECEIPT_DIRECTORY = REPO / "output/diagnostic-receipts"
PREFIX = RECEIPT_DIRECTORY / f"muni-fspsx-v34-windows-host-stability-{ADMISSION_ID}"
RUNTIME_ARTIFACTS = (
    Path(f"{PREFIX}.authority-intent.json"),
    Path(f"{PREFIX}.intent.json"),
    Path(f"{PREFIX}.capture.json"),
    Path(f"{PREFIX}.receipt.pending.json"),
    Path(f"{PREFIX}.receipt.json"),
    Path(f"{PREFIX}.rejection.pending.json"),
    Path(f"{PREFIX}.rejection.json"),
    Path(f"{PREFIX}.serialization-lock.evidence.json"),
    RECEIPT_DIRECTORY / "planora-shared-heavy-wsl.lock",
)
INDEPENDENT_REVIEW = Path(f"{PREFIX}.independent-review.receipt.json")
AUTHORIZATION = Path(f"{PREFIX}.authorization.receipt.json")


def powershells() -> list[Path]:
    ps5 = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    pwsh = shutil.which("pwsh")
    assert ps5.is_file()
    assert pwsh
    return [ps5, Path(pwsh)]


def run_script(powershell: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def artifact_state() -> dict[Path, bool]:
    return {path: path.exists() for path in RUNTIME_ARTIFACTS}


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_script_parses_in_both_powershells(powershell: Path) -> None:
    escaped = str(SCRIPT).replace("'", "''")
    command = (
        f"$p='{escaped}';$t=$null;$e=$null;"
        "$a=[System.Management.Automation.Language.Parser]::ParseFile("
        "$p,[ref]$t,[ref]$e);"
        "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1};"
        "$commands=@($a.FindAll({param($n)"
        "$n-is[System.Management.Automation.Language.CommandAst]},$true));"
        '"PARSE_OK commands=$($commands.Count)"'
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    assert "PARSE_OK" in result.stdout


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_static_self_test_is_fixture_only_and_nonconsuming(powershell: Path) -> None:
    before = artifact_state()
    assert not any(before.values())
    result = run_script(powershell, "-StaticSelfTest")
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    rows = result.stdout.strip().splitlines()
    assert len(rows) == 1
    receipt = json.loads(rows[0])
    assert receipt["schema"] == ("planora.muni-v34.windows-host-stability-self-test.v2")
    assert receipt["status"] == "PASS"
    assert receipt["positive"]["status"] == (
        "PASS_WINDOWS_QUIET_WINDOW_ONLY_NOT_FULL_HOST_READINESS"
    )
    assert receipt["positive"]["samples"] == 3
    assert receipt["positive"]["minimum_separation_seconds"] == 450
    assert receipt["positive"]["quiet_window_seconds"] == 900
    assert receipt["positive"]["required_services_running_stable"] is True
    assert receipt["positive"]["admission_owned_serialization_lock"] is True
    assert receipt["positive"]["compressed_vhdx_blocker_cleared"] is False
    assert receipt["positive"]["ubuntu_readiness_authorized"] is False
    assert set(receipt["negative_results"]) == {
        "timing_under_900_seconds",
        "new_ntfs_141",
        "new_application_popup_26",
        "storage_warning",
        "docker_process",
        "preexisting_wsl_workload",
        "stopped_wsl_service",
        "repository_namespace_drift",
        "repository_namespace_reparse",
        "vhdx_identity_drift",
        "degraded_volume",
        "intermediate_free_space_loss",
        "canonical_artifact",
        "serialization_lock_lost",
        "process_start_monitor_dead",
        "guard_poll_gap",
        "guard_intermediate_free_space_loss",
        "authorization_boolean_type",
        "authorization_array_type",
    }
    assert set(receipt["negative_results"].values()) == {"REJECTED"}
    assert receipt["canonical_json_alias"] == "REJECTED"
    assert receipt["canonical_json_duplicate"] == "REJECTED"
    assert receipt["wsl_executed"] is False
    assert receipt["host_state_queried"] is False
    assert receipt["artifacts_written"] is False
    assert receipt["live_authorization_read"] is False
    assert artifact_state() == before


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_junction_and_drive_invocation_paths_resolve_to_one_physical_script(
    powershell: Path,
) -> None:
    script = str(SCRIPT).replace("'", "''")
    junction = (
        "C:/mnt/d/stuff/projects/sites/planora/scripts/"
        "run_muni_v34_windows_host_stability_admission.ps1"
    )
    command = (
        f". '{script}' -StaticSelfTest | Out-Null;"
        f"$drive=Get-PhysicalEvidenceIdentity '{script}';"
        f"$junction=Get-PhysicalEvidenceIdentity '{junction}';"
        "$fields=@('size','sha256','file_id','last_write_utc_ticks');"
        "foreach($field in $fields){"
        'if($drive.$field-cne$junction.$field){throw "identity mismatch: $field"}};'
        '"IDENTITY_PASS"'
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    assert result.stdout.strip().splitlines()[-1] == "IDENTITY_PASS"
    assert not any(artifact_state().values())


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
@pytest.mark.parametrize(
    "arguments",
    [(), ("-StaticSelfTest", "-InspectPreconditions"), ("-StaticSelfTest", "-Observe")],
    ids=("zero-mode", "mixed-inspect", "mixed-observe"),
)
def test_invalid_mode_census_rejects_before_any_live_or_write_path(
    powershell: Path, arguments: tuple[str, ...]
) -> None:
    before = artifact_state()
    result = run_script(powershell, *arguments)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Exactly one explicit host-stability mode is required" in result.stderr
    assert artifact_state() == before


def test_live_modes_require_cryptographically_bound_review_and_authorization() -> None:
    source = SCRIPT.read_text("utf-8")
    gate = source.index("$authorizationState = Get-GuardedAuthorizationState $modeName")
    for live_operation in (
        "$preflightStartUtc = [DateTime]::UtcNow",
        "$preflight = Get-LiveSample",
        "$ownedLock = New-SharedAdmissionLock",
        "Write-CreateOnlyUtf8Durable $intentPath",
        "Wait-GuardedUntil $target",
    ):
        assert gate < source.index(live_operation)
    assert "Open-ReadEvidenceGuard $path" in source
    assert "Assert-ExactPin $review.sources.script $pins.script" in source
    assert "Assert-ExactPin $review.sources.tests $pins.tests" in source
    assert "Assert-ExactPin $authorization.sources.script $pins.script" in source
    assert (
        "Assert-ExactPin $authorization.sources.independent_review "
        "$pins.independent_review" in source
    )
    assert "GO_FOR_EXACT_WINDOWS_HOST_STABILITY_OBSERVATION" in source
    assert "GO_FOR_EXACTLY_ONE_WINDOWS_HOST_STABILITY_AUTHORITY" in source
    assert "$authorizedModes.Count -ne 1" in source
    assert "$authorizedModes[0] -cne $Mode" in source
    assert "Assert-JsonArrayProperty $authorization 'authorized_modes'" in source
    assert "Assert-JsonBooleanProperty $authorization $name" in source
    assert "Assert-JsonArrayProperty $review 'blockers'" in source
    assert "Assert-JsonBooleanProperty $review.review_scope $name" in source
    assert "[bool]$authorization.automatic_retry_authorized" in source
    assert "[bool]$authorization.wsl_authorized" in source
    assert "[bool]$authorization.canonical_execution_authorized" in source


def test_exact_windows_quiet_window_and_forensic_channels_are_enforced() -> None:
    source = SCRIPT.read_text("utf-8")
    assert "$sampleCount = 3" in source
    assert "$sampleIntervalSeconds = 450" in source
    assert "$minimumQuietWindowSeconds = 900" in source
    assert "$continuousGuardPollMilliseconds = 2000" in source
    assert "$maximumContinuousGuardGapMilliseconds = 15000" in source
    assert "$terminalProcessStartDrainGraceMilliseconds = 5000" in source
    assert "$minimumFreeSpaceBytes = [long](64GB)" in source
    assert "$maximumFreeSpaceLossBytes = [long](1GB)" in source
    assert "foreach ($sample in @($Samples | Select-Object -Skip 1))" in source
    assert "Get-LatestEventObservation 'System' 'Ntfs' 141" in source
    assert (
        source.count("Get-LatestEventObservation 'System' 'Application Popup' 26") == 3
    )
    assert (
        "Get-LatestEventObservation 'Application' 'Application Popup' 26" not in source
    )
    assert "D:\\Docker\\wsl\\disk\\docker_data.vhdx" in source
    assert "D:\\WSL\\Ubuntu\\ext4.vhdx" in source
    for service in ("WslService", "vmcompute", "hns", "HvHost"):
        assert service in source
    assert "$matches[0].state -cne 'Running'" in source
    assert "[int]$matches[0].process_id -le 0" in source
    assert "$Volume.operational_status -cne 'OK'" in source
    assert "OK,Degraded" in source
    assert "compressed_vhdx_blocker_cleared = $false" in source
    assert "$repo = 'D:\\Stuff\\Projects\\Sites\\Planora'" in source
    assert "repository_namespace = Assert-RepositoryNamespaceIdentity" in source
    assert "Assert-RepositoryNamespaceObservationAdmissible" in source
    assert "reparse_point = [bool]" in source
    assert "wsl_workload_process_count" in source
    assert "$volume = Get-VolumeObservation" in source
    assert "volume_identity_healthy_online_writable_at_every_poll" in source


def test_serialization_and_terminal_publication_are_fail_closed() -> None:
    source = SCRIPT.read_text("utf-8")
    assert "$mutexName = 'Global\\Planora.MuniV34.WindowsHostStability'" in source
    assert "[IO.FileMode]::CreateNew" in source
    assert "[IO.FileShare]::Read" in source
    assert "[IO.FileOptions]::WriteThrough" in source
    assert "$stream.Flush($true)" in source
    assert "Shared lock same-handle replay hash mismatch" in source
    assert "$intentPublished = $true" in source
    assert "$intentGuard = Open-ReadEvidenceGuard $intentPath" in source
    assert (
        source.count(
            "Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'"
        )
        >= 4
    )
    assert "$authorityEntered = $true" in source
    authority_write = source.index(
        "Write-CreateOnlyUtf8Durable $authorityIntentPath $authorityIntentJson"
    )
    preflight = source.index("$processMonitor = Start-ProcessStartMonitor")
    assert authority_write < preflight
    assert "if ($authorityIntentWriteStarted -and -not $passPublished)" in source
    assert (
        "-not (Test-Path -LiteralPath $rejectionPath) -and "
        "-not (Test-Path -LiteralPath $rejectionPendingPath)" in source
    )
    assert "Write-CreateOnlyUtf8Durable $receiptPath" not in source
    pass_write = source.index(
        "Publish-CanonicalTerminal $receiptPendingPath $receiptPath $receiptJson"
    )
    pass_state = source.index("$passPublished = $true", pass_write)
    catch_start = source.index("\ncatch {", pass_state)
    output = source.index("[Console]::Out.WriteLine($receiptJson)", catch_start)
    assert pass_write < pass_state < catch_start < output
    assert "[IO.File]::Delete($sharedLockPath)" not in source
    assert "[IO.File]::Move($sharedLockPath, $lockEvidencePath)" not in source
    assert "partial_shared_lock_archive" not in source
    assert (
        "owned_partial_shared_lock_retained_for_authenticated_reconciliation" in source
    )
    assert "$PartialState.Value.source_pin = Get-LocalEvidencePinSharedDelete" in source
    assert "partial_lock_state = $partialLockState" in source
    assert "serialization_lock_source_pin = $sharedLockSourcePin" in source
    assert (
        "[PlanoraMuniV34AtomicFile]::RenameOpenHandle($OwnedLock.native_handle, "
        "$OwnedLock.directory_handle, $archiveLeaf)" in source
    )
    assert "OpenDirectoryBinding($receiptDirectory)" in source
    assert "FileFlagOpenReparsePoint" in source
    assert "ShareRead | ShareWrite" in source
    assert "Assert-SamePhysicalPin $livePin $archivePin" in source
    assert "NtSetInformationFile" in source
    assert "NativeFileRenameInformation = 10" in source
    assert "Remove-Item" not in source
    assert "automatic_retry_authorized = $true" not in source
    assert "Register-CimIndicationEvent" in source
    assert "SELECT * FROM Win32_ProcessStartTrace" in source
    assert "Read-ProcessStartMonitor $ProcessMonitor" in source
    assert "Get-EventSubscriber -SourceIdentifier" in source
    assert "Assert-ProcessStartMonitorHealthy" in source
    assert "Assert-ContinuousGuardTelemetry" in source
    assert "suspicious_count -ne 0" in source


def test_terminal_rename_is_the_last_fallible_publication_operation() -> None:
    source = SCRIPT.read_text("utf-8")
    start = source.index("function Publish-CanonicalTerminal")
    end = source.index("function Get-FileId", start)
    publication = source[start:end]
    replay = publication.index("Assert-HeldCanonicalReplay")
    pending_identity = publication.index(
        "$pendingIdentity = Get-HeldPhysicalEvidenceIdentity"
    )
    named_binding = publication.index(
        "$namedPendingIdentity = Get-PhysicalEvidenceIdentitySharedDelete"
    )
    binding_assertion = publication.index(
        "Assert-SamePhysicalPin $pendingIdentity $namedPendingIdentity"
    )
    result_construction = publication.index("$publication = [ordered]@{")
    stream_close = publication.index("$stream.Dispose()", result_construction)
    rename = publication.index(
        "[PlanoraMuniV34AtomicFile]::RenameOpenHandle(", stream_close
    )
    returned = publication.index("return $publication", rename)
    assert (
        replay
        < pending_identity
        < named_binding
        < binding_assertion
        < result_construction
        < stream_close
        < rename
        < returned
    )
    committed_tail = publication[rename:returned]
    assert "Get-PhysicalEvidenceIdentity" not in committed_tail
    assert "Assert-HeldCanonicalReplay" not in committed_tail
    assert "Assert-SamePhysicalPin" not in committed_tail
    assert "OpenDirectoryBinding($finalParent)" in publication
    assert "destination_directory_bound = $true" in publication


def test_capture_and_terminal_guard_dominate_pass_publication() -> None:
    source = SCRIPT.read_text("utf-8")
    guard_start = source.index("function Get-ContinuousGuardObservation")
    guard_end = source.index("function Assert-ContinuousGuardObservation", guard_start)
    guard_source = source[guard_start:guard_end]
    artifacts = guard_source.index("$artifacts = Get-CanonicalArtifactObservation")
    owned_lock = guard_source.index("$lock = Get-SharedLockObservation $OwnedLock")
    volume = guard_source.index("$volume = Get-VolumeObservation")
    namespace = guard_source.index(
        "$repositoryNamespace = Assert-RepositoryNamespaceIdentity"
    )
    process_drain = guard_source.index(
        "$processStarts = Read-ProcessStartMonitor $ProcessMonitor"
    )
    docker_census = guard_source.index("$docker = Get-DockerProcessObservation")
    endpoint = guard_source.index(
        "$completedElapsedMilliseconds = $Stopwatch.ElapsedMilliseconds"
    )
    drain_grace = guard_source.index(
        "Start-Sleep -Milliseconds $ProcessStartDrainGraceMilliseconds"
    )
    assert (
        endpoint
        < drain_grace
        < process_drain
        < docker_census
        < artifacts
        < owned_lock
        < volume
        < namespace
    )
    capture_write = source.index(
        "Write-CreateOnlyUtf8Durable $capturePath $captureJson"
    )
    terminal_guard = source.index("$terminalGuard = Get-ContinuousGuardObservation")
    terminal_replay = source.index(
        "Assert-HeldCanonicalReplay $captureGuard $captureJson 'Host-stability capture'",
        terminal_guard,
    )
    release = source.index(
        "$lockRelease = Release-SharedAdmissionLock", terminal_replay
    )
    pass_publish = source.index(
        "Publish-CanonicalTerminal $receiptPendingPath $receiptPath $receiptJson",
        release,
    )
    assert capture_write < terminal_guard < terminal_replay < release < pass_publish
    assert (
        "Assert-ContinuousGuardTelemetry @($guardRows.ToArray()) "
        "$terminalGuard.elapsed_milliseconds" in source
    )
    assert (
        "$terminalProcessStartDrainGraceMilliseconds"
        in source[terminal_guard:terminal_replay]
    )
    assert "RECONCILED_PREVALIDATED_ATOMIC_RENAME_COMMIT" not in source
    assert "committed_terminal_reconciliation" not in source
    assert "CAPTURED_NOT_PASS_UNTIL_TERMINAL_RECEIPT" in source
    assert "planora.muni-v34.windows-host-stability-admission.v3" in source


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_atomic_terminal_publication_replays_before_bound_open_handle_rename(
    powershell: Path, tmp_path: Path
) -> None:
    pending = tmp_path / f"{powershell.name}.pending.json"
    final = tmp_path / f"{powershell.name}.final.json"
    script = str(SCRIPT).replace("'", "''")
    pending_text = str(pending).replace("'", "''")
    final_text = str(final).replace("'", "''")
    fixture_json = '{"schema":"fixture","status":"PASS"}'
    command = (
        f". '{script}' -StaticSelfTest | Out-Null;"
        f"$json='{fixture_json}';"
        f"$result=Publish-CanonicalTerminal '{pending_text}' '{final_text}' "
        "$json 'Fixture terminal';"
        "if($result.status-cne'ATOMIC_CREATE_WRITE_FLUSH_REPLAY_NO_REPLACE_RENAME_COMMIT')"
        "{throw 'publication status mismatch'};"
        f"$native=Get-PhysicalEvidenceIdentitySharedDelete '{final_text}';"
        f"$ordinary=Get-PhysicalEvidenceIdentity '{final_text}';"
        "$fields=@('size','sha256','file_id','last_write_utc_ticks');"
        "foreach($field in $fields){if($native.$field-cne$ordinary.$field)"
        '{throw "identity mismatch: $field"}};'
        "foreach($field in $fields){if($result.committed_identity.$field-cne$native.$field)"
        '{throw "committed identity mismatch: $field"}};'
        '"ATOMIC_TERMINAL_PASS"'
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    assert result.stdout.strip().splitlines()[-1] == "ATOMIC_TERMINAL_PASS"
    assert not pending.exists()
    assert final.read_text("utf-8") == fixture_json


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
@pytest.mark.parametrize(
    "final_payload",
    ["sentinel", '{"schema":"fixture","status":"PASS"}'],
    ids=("different-bytes", "identical-bytes"),
)
def test_atomic_terminal_conflict_leaves_only_nonterminal_pending_evidence(
    powershell: Path, tmp_path: Path, final_payload: str
) -> None:
    pending = tmp_path / f"{powershell.name}.conflict.pending.json"
    final = tmp_path / f"{powershell.name}.conflict.final.json"
    final.write_text(final_payload, encoding="utf-8")
    script = str(SCRIPT).replace("'", "''")
    pending_text = str(pending).replace("'", "''")
    final_text = str(final).replace("'", "''")
    fixture_json = '{"schema":"fixture","status":"PASS"}'
    command = (
        f". '{script}' -StaticSelfTest | Out-Null;"
        f"$json='{fixture_json}';"
        f"Publish-CanonicalTerminal '{pending_text}' '{final_text}' "
        "$json 'Fixture conflict' | Out-Null"
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert pending.read_text("utf-8") == fixture_json
    assert final.read_text("utf-8") == final_payload


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_partial_shared_lock_is_retained_and_pinned_at_its_source(
    powershell: Path, tmp_path: Path
) -> None:
    shared = tmp_path / f"{powershell.name}.shared.lock"
    archive = tmp_path / f"{powershell.name}.archive.json"
    script = str(SCRIPT).replace("'", "''")
    directory_text = str(tmp_path).replace("'", "''")
    shared_text = str(shared).replace("'", "''")
    archive_text = str(archive).replace("'", "''")
    command = (
        f". '{script}' -StaticSelfTest | Out-Null;"
        f"$repo='{directory_text}';"
        f"$receiptDirectory='{directory_text}';"
        f"$sharedLockPath='{shared_text}';"
        f"$lockEvidencePath='{archive_text}';"
        "$admissionId='fixture';"
        "$originalPin=${function:Get-LocalEvidencePinSharedDelete};"
        "$script:probeCalls=0;"
        "function Get-LocalEvidencePinSharedDelete([string]$Path){"
        "$script:probeCalls++;"
        "if($script:probeCalls-eq 1){throw 'FORCED_POST_CREATE_FAILURE'};"
        "return & $originalPin $Path};"
        "$partial=$null;$rejected=$false;"
        "try {New-SharedAdmissionLock ([pscustomobject]@{authorization='fixture'}) "
        "([ref]$partial)|Out-Null}"
        "catch {$rejected=$true;if($_.Exception.Message-notmatch"
        "'owned_partial_shared_lock_retained'){throw}};"
        "if(-not $rejected){throw 'partial failure was accepted'};"
        "if(-not $partial.native_owner_acquired-or"
        "-not $partial.owned_partial_retained-or"
        "-not $partial.source_matches_owned_handle-or"
        "$null-eq$partial.owned_handle_identity-or"
        "$partial.acquisition_completed){throw 'partial state mismatch'};"
        f"if(-not(Test-Path -LiteralPath '{shared_text}'))"
        "{throw 'partial source lock missing'};"
        f"if(Test-Path -LiteralPath '{archive_text}')"
        "{throw 'partial lock was archived'};"
        f"$held=& $originalPin '{shared_text}';"
        "$fields=@('size','sha256','file_id','last_write_utc_ticks');"
        "foreach($field in $fields){if($partial.source_pin.$field-cne$held.$field)"
        '{throw "partial source pin mismatch: $field"}};'
        f"[IO.File]::Delete('{shared_text}');"
        '"PARTIAL_LOCK_RETENTION_PASS"'
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    assert result.stdout.strip().splitlines()[-1] == "PARTIAL_LOCK_RETENTION_PASS"
    assert not shared.exists()
    assert not archive.exists()


def test_canonical_namespace_and_pinned_source_files_remain_absent() -> None:
    assert not any(artifact_state().values())
    assert not (REPO / "scripts/run_muni_v34_canonical_tests.ps1").exists()
    assert not (REPO / "scripts/run_muni_v34_terminal_gate_once.ps1").exists()
    assert not list(
        RECEIPT_DIRECTORY.glob(f"muni-fspsx-v34-canonical-readonly-tests-{RUN_ID}*")
    )
    assert not list(
        RECEIPT_DIRECTORY.glob("muni-fspsx-v34-canonical-tests-authorization-*")
    )


def test_script_contains_no_wsl_docker_service_or_vhdx_mutation_command() -> None:
    source = SCRIPT.read_text("utf-8")
    forbidden = (
        r"(?i)\bwsl\.exe\b",
        r"(?i)\bdocker\.exe\b",
        r"(?i)\b(?:Start|Stop|Restart)-Service\b",
        r"(?i)\b(?:Mount|Dismount|Optimize|Resize)-VHD\b",
        r"(?i)\bSet-Partition\b",
        r"(?i)\bSet-Volume\b",
        r"(?i)\bcompact\.exe\b",
        r"(?i)\battrib\.exe\b",
        r"(?i)\bInvoke-Expression\b",
        r"(?i)\bStart-Process\b",
    )
    for pattern in forbidden:
        assert re.search(pattern, source) is None, pattern
