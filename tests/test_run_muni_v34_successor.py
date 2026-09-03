from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "scripts/build_muni_v34_successor.py"


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_muni_v34_successor", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    return load_builder()


@pytest.fixture(scope="module")
def snapshot(builder: ModuleType) -> dict[str, object]:
    return builder.load_input_snapshot()


def powershells() -> list[Path]:
    ps5 = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    pwsh = shutil.which("pwsh")
    assert ps5.is_file()
    assert pwsh
    return [ps5, Path(pwsh)]


def test_exact_core_union_is_100_ordinary_99_archive_1(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    contract = snapshot["core"]
    assert contract["historic_rows"] == 89
    assert contract["v33_rejection_rows"] == 12
    assert contract["raw_rows"] == 101
    assert contract["unique_rows"] == 100
    assert contract["ordinary_read_guards"] == 99
    assert contract["archive_replay_only"] == 1
    assert contract["single_overlap"] == builder.RETAINED_ARCHIVE
    paths = [pin["path"] for pin in contract["rows"]]
    assert len(paths) == len(set(paths)) == 100
    assert len(contract["rows_sha256"]) == 64
    assert contract["rows_canonical_sha256"] == builder.CORE_ROWS_CANONICAL_SHA256
    assert len(contract["v33_direct_rows"]) == 12


def test_v33_gate_rejection_is_bound_without_execution_overclaim(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    contract = snapshot["core"]
    rejection = contract["v33_rejection"]
    review = contract["v33_rejection_review"]
    assert rejection["status"] == "REJECTED_TERMINAL_GATE_INVOCATION_CONSUMED"
    assert rejection["decision"] == "NO_RETRY_BUILD_NEW_SUCCESSOR"
    assert rejection["post_failure_state"]["v33_root_state"] == (
        "UNKNOWN_WSL_DISTRIBUTION_DID_NOT_START"
    )
    assert rejection["authorization_disposition"][
        "terminal_gate_invocation_authority_exhausted"
    ]
    assert not rejection["authorization_disposition"][
        "runner_default_authorization_claim_consumed"
    ]
    assert rejection["authorization_disposition"][
        "runner_authorization_must_not_be_reused"
    ]
    assert review["status"] == "GO_FOR_EXACT_V33_REJECTION_CUSTODY"
    assert review["successor_admission_status"] == (
        "NO_GO_ACTIVE_HOST_WSL_STORAGE_INSTABILITY"
    )
    assert review["frozen_rejection_pair"]["receipt"]["sha256"] == (
        builder.V33_REJECTION_SHA256
    )
    assert review["frozen_rejection_pair"]["custody_test"]["sha256"] == (
        builder.V33_CUSTODY_TEST_SHA256
    )


def test_draft_manifest_is_explicit_no_go_and_has_no_claim_grade(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    manifest = builder.draft_manifest(snapshot)
    assert manifest["status"] == "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING"
    assert manifest["run_id"] == "3c3ed012febd407da5202423b2a67d32"
    assert manifest["build_ready"] is False
    assert manifest["claim_grade_ready"] is False
    assert manifest["performance_claims_authorized"] is False
    assert manifest["core_predecessor_paths"] == 100
    assert manifest["ordinary_predecessor_read_guards"] == 99
    assert manifest["archive_replay_only_paths"] == 1
    assert manifest["core_predecessor_rows_sha256"] == snapshot["core"]["rows_sha256"]
    assert manifest["core_predecessor_rows_canonical_sha256"] == (
        builder.CORE_ROWS_CANONICAL_SHA256
    )
    assert manifest["v33_rejection_receipt_sha256"] == builder.V33_REJECTION_SHA256
    assert manifest["v33_rejection_review_sha256"] == builder.FORENSIC_REVIEW_SHA256
    assert manifest["operational_predecessor_contract_embedded"] is True
    assert manifest["future_direct_host_readiness_pins"] == 2
    assert manifest["authorization_schema_target"].endswith(".v14")
    assert manifest["expected_final_protected_guards"] == 106
    assert manifest["expected_final_total_guards"] == 108
    assert manifest["automatic_retry_authorized"] is False
    assert manifest["wsl_executed"] is False
    assert manifest["canonical_suite_executed"] is False
    assert manifest["final_artifacts_written"] is False


def test_draft_requires_both_future_host_receipts(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    expected_state = {
        builder.HOST_READINESS.relative_to(REPO).as_posix(): False,
        builder.HOST_READINESS_REVIEW.relative_to(REPO).as_posix(): False,
    }
    assert snapshot["future_host_path_exists"] == expected_state
    manifest = builder.draft_manifest(snapshot)
    assert manifest["missing_host_paths"] == [
        builder.HOST_READINESS.relative_to(REPO).as_posix(),
        builder.HOST_READINESS_REVIEW.relative_to(REPO).as_posix(),
    ]
    assert not builder.HOST_READINESS.exists()
    assert not builder.HOST_READINESS_REVIEW.exists()


def test_manifest_and_render_share_one_frozen_future_host_snapshot(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    simulated = copy.deepcopy(snapshot)
    host_receipt = builder.HOST_READINESS.relative_to(REPO).as_posix()
    simulated["future_host_path_exists"][host_receipt] = True
    manifest = builder.draft_manifest(simulated)
    rendered = builder.render_draft_runner(simulated)
    embedded = builder.extract_contract(rendered, "v34DraftContractJson")
    assert manifest == embedded
    assert manifest["missing_host_paths"] == [
        builder.HOST_READINESS_REVIEW.relative_to(REPO).as_posix()
    ]


def test_snapshot_replay_rejects_future_host_path_state_drift(
    builder: ModuleType,
    snapshot: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulated = copy.deepcopy(snapshot)
    host_receipt = builder.HOST_READINESS.relative_to(REPO).as_posix()
    simulated["future_host_path_exists"][host_receipt] = True
    monkeypatch.setattr(builder, "assert_live_pin", lambda _pin: None)
    with pytest.raises(
        RuntimeError,
        match="future host-readiness path state changed after draft render",
    ):
        builder.assert_input_snapshot_unchanged(simulated)


def test_draft_render_is_deterministic_scoped_and_fail_closed(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    first = builder.render_draft_runner(snapshot)
    second = builder.render_draft_runner(snapshot)
    assert first == second
    assert builder.RUN_ID in first
    assert builder.V33_RUN_ID in first
    assert "HostReadinessBindingSelfTest" in first
    assert "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING" in first
    barrier = first.index("throw 'MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING'")
    for unsafe in (
        "if($EmitExpectedAuthorization)",
        "if($LogBridgeSelfTest)",
        "if($ResourceMonitorReadinessSelfTest)",
        "$lockStream=$null;",
        "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess",
    ):
        assert barrier < first.index(unsafe)
    assert (
        first.count(
            "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess"
        )
        == 1
    )
    assert "automatic_retry_authorized=$true" not in first
    cleanup = first.split("$cleanupSource = @'", 1)[1].split("'@", 1)[0]
    assert "/tmp/planora-muni-v33-canonical-tests-" not in cleanup
    expected_authorization = builder.V34_AUTH.relative_to(REPO).as_posix()
    assert "PENDING" not in expected_authorization
    assert expected_authorization.replace("/", "\\") in first


def test_rendered_runtime_binds_all_v33_rejection_and_core_evidence(
    builder: ModuleType, snapshot: dict[str, object]
) -> None:
    rendered = builder.render_draft_runner(snapshot)
    core = snapshot["core"]
    contract = builder.extract_contract(
        rendered, "v33TerminalGateRejectionContractJson"
    )
    assert contract["direct_rows"] == core["v33_direct_rows"]
    assert contract["direct_rows_count"] == 12
    assert contract["unique_addition_count"] == 11
    assert contract["historic_base_count"] == 89
    assert contract["complete_unique_count"] == 100
    assert contract["complete_rows_sha256"] == core["rows_sha256"]
    assert contract["complete_rows_canonical_sha256"] == (
        builder.CORE_ROWS_CANONICAL_SHA256
    )
    assert contract["rejection_pin"]["sha256"] == builder.V33_REJECTION_SHA256
    assert contract["custody_test_pin"]["sha256"] == builder.V33_CUSTODY_TEST_SHA256
    assert contract["independent_review_pin"]["sha256"] == (
        builder.FORENSIC_REVIEW_SHA256
    )
    required = (
        "function Get-ValidatedV33TerminalGateRejectionEvidence",
        "function Get-ValidatedThroughV32PredecessorEvidence",
        "function Get-ValidatedCompletePredecessorEvidence",
        "VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY",
        "Assert-V28V29V30V31V32V33PassEvidenceAbsent",
        "predecessorPins.Count-ne100",
    )
    for marker in required:
        assert marker in rendered
    assert rendered.count("v33_terminal_gate_rejection_evidence_sha256") >= 8
    assert "$plan['v33_terminal_gate_rejection_evidence']" in rendered
    assert "$receipt['v33_terminal_gate_rejection_evidence']" in rendered
    assert "v33_terminal_gate_rejection_evidence=" in rendered
    assert "EXACT_V28_V29_V30_V31_V32_V33_CUSTODY_VALIDATED_BEFORE_V34_LOCK" in rendered
    assert "$custodyPins.Count-ne100" in rendered
    assert "@($success.evidence.runtime.validated_pins).Count-ne100" in rendered
    assert "$success.replay.validated_pin_count-ne100" in rendered
    assert "planora.itc2019.canonical-test-authorization.v13" not in rendered
    assert (
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_"
        "AUTHENTICATED_V32_NAMESPACE_PERMISSION_FAILURE" not in rendered
    )
    assert "canonical-test-authorization.v14-draft-blocked" in rendered
    assert "DRAFT_NO_GO_HOST_READINESS_AND_INDEPENDENT_REVIEW_PENDING" in rendered
    assert "all_100_predecessor_file_ids_and_timestamps_draft_bound" in rendered
    assert (
        "v28_v29_v30_v31_v32_v33_pass_absence_replayed_through_final_"
        "pass_seal_publication" in rendered
    )
    assert rendered.count("Count-ne89") == 3
    assert rendered.count("Count-eq89") == 1


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_rendered_draft_parses_in_both_powershells(
    builder: ModuleType,
    snapshot: dict[str, object],
    tmp_path: Path,
    powershell: Path,
) -> None:
    draft = tmp_path / "run_muni_v34_draft.ps1"
    draft.write_text(
        builder.render_draft_runner(snapshot), encoding="utf-8", newline="\n"
    )
    escaped = str(draft).replace("'", "''")
    command = (
        f"$p='{escaped}';$t=$null;$e=$null;"
        "$a=[System.Management.Automation.Language.Parser]::ParseFile("
        "$p,[ref]$t,[ref]$e);"
        "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1};"
        "$c=@($a.FindAll({param($n)"
        "$n-is[System.Management.Automation.Language.CommandAst]},$true));"
        '"PARSE_OK commands=$($c.Count)"'
    )
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
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
def test_host_binding_self_test_is_local_and_nonconsuming(
    builder: ModuleType,
    snapshot: dict[str, object],
    tmp_path: Path,
    powershell: Path,
) -> None:
    draft = tmp_path / "run_muni_v34_draft.ps1"
    draft.write_text(
        builder.render_draft_runner(snapshot), encoding="utf-8", newline="\n"
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(draft),
            "-HostReadinessBindingSelfTest",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    rows = result.stdout.strip().splitlines()
    assert len(rows) == 1
    manifest = json.loads(rows[0])
    assert manifest["status"] == "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING"
    assert manifest["wsl_executed"] is False
    assert manifest["canonical_suite_executed"] is False
    assert manifest["final_artifacts_written"] is False


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_predecessor_binding_self_test_replays_exact_100_without_wsl_or_writes(
    builder: ModuleType,
    snapshot: dict[str, object],
    tmp_path: Path,
    powershell: Path,
) -> None:
    draft = tmp_path / "run_muni_v34_draft.ps1"
    draft.write_text(
        builder.render_draft_runner(snapshot), encoding="utf-8", newline="\n"
    )
    base = [
        str(powershell),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(draft),
    ]
    result = subprocess.run(
        [*base, "-PredecessorBindingSelfTest"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    row = json.loads(result.stdout)
    assert row["status"] == "PASS"
    assert row["validated_pins"] == row["unique_pins"] == 100
    assert row["v33_direct_rows"] == 12
    assert row["v33_unique_additions"] == 11
    assert row["complete_rows_sha256"] == snapshot["core"]["rows_sha256"]
    assert row["shared_lock_absent"] is True
    assert row["wsl_executed"] is False
    assert row["canonical_suite_executed"] is False
    assert row["artifacts_written"] is False
    namespace = REPO / "output/diagnostic-receipts"
    assert not list(
        namespace.glob(f"muni-fspsx-v34-canonical-readonly-tests-{builder.RUN_ID}.*")
    )
    assert not any(
        path.exists()
        for path in (builder.V34_RUNNER, builder.V34_AUTH, builder.V34_GATE)
    )
    mixed = subprocess.run(
        [
            *base,
            "-PredecessorBindingSelfTest",
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert mixed.returncode != 0
    assert mixed.stdout == ""
    assert "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING" in mixed.stderr
    assert not builder.SHARED_LOCK.exists()
    assert not list(
        namespace.glob(f"muni-fspsx-v34-canonical-readonly-tests-{builder.RUN_ID}.*")
    )


@pytest.mark.parametrize("powershell", powershells(), ids=lambda path: path.name)
def test_every_other_entry_mode_is_blocked_before_wsl_or_writes(
    builder: ModuleType,
    snapshot: dict[str, object],
    tmp_path: Path,
    powershell: Path,
) -> None:
    draft = tmp_path / "run_muni_v34_draft.ps1"
    draft.write_text(
        builder.render_draft_runner(snapshot), encoding="utf-8", newline="\n"
    )
    switches: tuple[str | None, ...] = (
        None,
        "-EmitExpectedAuthorization",
        "-LogBridgeSelfTest",
        "-ReadinessPredicateSelfTest",
        "-RetainedV30SnapshotSelfTest",
        "-RetainedPredecessorSnapshotsSelfTest",
        "-CanonicalMonitorContractSelfTest",
        "-RejectionPromotionSelfTest",
        "-ResourceMonitorReadinessSelfTest",
        "-StaticSelfTest",
    )
    namespace = REPO / "output/diagnostic-receipts"
    forbidden = (builder.V34_RUNNER, builder.V34_AUTH, builder.V34_GATE)
    for switch in switches:
        command = [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(draft),
        ]
        if switch is not None:
            command.append(switch)
        result = subprocess.run(
            command,
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode != 0, switch
        assert result.stdout == "", switch
        assert "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING" in result.stderr, switch
        assert not any(path.exists() for path in forbidden)
        assert not builder.SHARED_LOCK.exists()
        assert not list(
            namespace.glob(
                f"muni-fspsx-v34-canonical-readonly-tests-{builder.RUN_ID}.*"
            )
        )


def test_builder_main_reports_no_go_and_writes_no_final_artifact(
    builder: ModuleType,
) -> None:
    targets = (builder.V34_RUNNER, builder.V34_AUTH, builder.V34_GATE)
    assert not any(path.exists() for path in targets)
    result = subprocess.run(
        [sys.executable, str(BUILDER)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 3
    assert result.stderr == ""
    manifest = json.loads(result.stdout)
    assert manifest["status"] == "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING"
    assert manifest["final_artifacts_written"] is False
    assert manifest["draft_runner_bytes"] == 376_666
    assert manifest["draft_runner_sha256"] == (
        "7af3a0bf9520f167afca90d01673cc9eba4bee8665fcd076766d2b69088db0c4"
    )
    assert not any(path.exists() for path in targets)


def test_builder_has_no_wsl_or_powershell_execution_path() -> None:
    tree = ast.parse(BUILDER.read_text("utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    subprocess_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert len(subprocess_calls) == 1
    call = subprocess_calls[0]
    assert isinstance(call.args[0], ast.List)
    first = call.args[0].elts[0]
    assert isinstance(first, ast.Constant)
    assert first.value == "fsutil.exe"
    attributes = {
        node.func.attr for node in calls if isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {"write_text", "write_bytes", "open", "touch", "mkdir", "unlink"}
    )
