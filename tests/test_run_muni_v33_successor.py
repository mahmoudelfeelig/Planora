from __future__ import annotations

import ast
import errno
import importlib.util
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO / "scripts/build_muni_v33_successor.py"
RUNNER_PATH = REPO / "scripts/run_muni_v33_canonical_tests.ps1"
AUTH_PATH = (
    REPO
    / "output/diagnostic-receipts"
    / "muni-fspsx-v33-canonical-tests-authorization-20260828T141639Z.receipt.json"
)
RUN_ID = "2339df35f57e441a8f92bd1f890fa68f"
V33_PREFIX = "muni-fspsx-v33-canonical-readonly-tests-2339df35f57e441a8f92bd1f890fa68f."


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_muni_v33_successor", BUILDER_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder():
    return load_builder()


@pytest.fixture(scope="module")
def rendered(builder):
    return builder.render_runner(
        BUILDER_PATH.stat().st_size,
        builder.sha256(BUILDER_PATH),
        Path(__file__).stat().st_size,
        builder.sha256(Path(__file__)),
    )


def resource_python(builder) -> str:
    block = builder.RESOURCE_MONITOR_BLOCK
    return block.split("@'\n", 1)[1].rsplit("\n'@", 1)[0]


def policy_namespace(builder):
    tree = ast.parse(resource_python(builder))
    names = {
        "nsid",
        "monitor_ancestry",
        "minimal_infrastructure",
        "infrastructure_ident",
        "freeze_infrastructure",
        "resolve_namespace_pair",
        "mark_namespace_states",
        "require_exact_namespace",
        "ident",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in nodes} == names
    namespace = {
        "os": os,
        "re": re,
        "watcher_pid": 20,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), "<policy>", "exec"), namespace
    )
    return namespace


def row(
    pid: int,
    ppid: int,
    uid: int,
    comm: str,
    argv: list[str],
) -> dict[str, object]:
    return {
        "pid": pid,
        "ppid": ppid,
        "pgrp": pid,
        "session": 1,
        "starttime": pid * 100,
        "uid": uid,
        "comm": comm,
        "argv": argv,
        "mnt_ns": None,
        "pid_ns": None,
        "namespace_state": "UNRESOLVED",
        "exe": [1, pid],
    }


def base_table(extra: dict[str, object] | None = None) -> dict[int, dict[str, object]]:
    init = row(1, 0, 0, "init(Ubuntu)", ["/init"])
    init["pgrp"] = 0
    init["session"] = 0
    init["exe"] = None
    rows = {
        1: init,
        10: row(10, 1, 1000, "python3", ["monitor"]),
        20: row(20, 1, 1000, "python3", ["watcher"]),
    }
    if extra is not None:
        rows[int(extra["pid"])] = extra
    return rows


def exact_stat(path: str):
    inode = 101 if path.endswith("/mnt") else 202
    return SimpleNamespace(st_dev=7, st_ino=inode)


def test_v32_pin_partition_is_exact_and_unique(builder):
    assert len(builder.PINS) == 28
    assert len({item["path"] for item in builder.PINS}) == 28
    assert len(builder.V32_SOURCES) == 4
    assert len(builder.V32_PROVENANCE) == 4
    assert len(builder.V32_ARTIFACTS) == 20
    assert len(builder.V32_EXPECTED_ABSENT_SUFFIXES) == 13


def test_v32_contract_authenticates_exact_failure(builder):
    contract = builder.V32_FAILURE_CONTRACT
    assert contract["artifact_count"] == 20
    assert contract["carried_predecessor_pin_count"] == 61
    assert contract["direct_source_provenance_artifact_pin_count"] == 28
    assert contract["failure"]["resource_launch_attempted"] is True
    assert contract["failure"]["canonical_launch_attempted"] is False
    assert contract["snapshot"]["inventory"]["sha256"] == (
        "0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3"
    )


def test_rendered_successor_has_fresh_identity_and_89_pins(rendered):
    assert RUN_ID in rendered
    assert "muni-fspsx-v33-canonical" in rendered
    assert "predecessorPins.Count-ne89" in rendered
    assert "VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY" in rendered
    assert "complete_v28_v29_v30_v31_v32_predecessor_pin_count']=89" in rendered
    assert "Assert-PinnedFile" not in rendered
    assert (
        rendered.count(
            "[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value"
        )
        >= 3
    )
    assert (
        "status='EXACT_V28_V29_V30_V31_V32_CUSTODY_VALIDATED_BEFORE_V33_LOCK'"
        in rendered
    )
    assert (
        "status='EXACT_V28_V29_V30_V31_CUSTODY_VALIDATED_BEFORE_V33_LOCK'"
        not in rendered
    )
    assert "throw'nlink'" not in rendered
    assert "throw 'nlink'" in rendered
    assert rendered.count("function Get-ExpectedAuthorizationJson(") == 1
    assert rendered.count("function Get-ObsoleteV12AuthorizationJson(") == 1
    assert "fixed_infra=" not in rendered
    assert "row['comm'] in fixed_infra" not in rendered


def test_prelock_custody_is_replayed_before_shared_lock_creation(rendered):
    write_index = rendered.index("Write-NewUtf8 $predecessorCustodyFile")
    guard_index = rendered.index("$predecessorCustodyGuard=New-Object IO.FileStream")
    byte_replay_index = rendered.index(
        "Pre-lock predecessor custody exact byte replay rejected"
    )
    document_replay_index = rendered.index(
        "Assert-ExactCanonicalJsonDocumentReplay $custodyRaw"
    )
    parse_index = rendered.index("$custodyReplay=$custodyRaw|ConvertFrom-Json")
    replay_index = rendered.index("Pre-lock predecessor custody replay rejected")
    hash_index = rendered.index(
        "$predecessorCustodyHash=Get-BytesSha256 $custodyObservedBytes", replay_index
    )
    lock_index = rendered.index(
        "$lockStream=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::CreateNew"
    )
    assert (
        write_index
        < guard_index
        < byte_replay_index
        < document_replay_index
        < parse_index
        < replay_index
        < hash_index
        < lock_index
    )
    assert "$custodyPins.Count-ne89" in rendered
    assert "@($custodyPins.path|Sort-Object -Unique).Count-ne89" in rendered
    assert "$custodyPredecessorRawHash-cne$predecessorEvidenceHash" in rendered
    assert "$custodyV31RawHash-cne$v31FailureEvidenceHash" in rendered
    assert "$custodyV32RawHash-cne$v32FailureEvidenceHash" in rendered
    assert rendered.count("function Get-RawTopLevelJsonObjectPropertyTokenHash(") == 1
    assert (
        "$custodyPredecessorRawHash=Get-RawTopLevelJsonObjectPropertyTokenHash"
        in rendered
    )
    assert "$custodyV31RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash" in rendered
    assert "$custodyV32RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash" in rendered
    assert "top_level_raw_json_shadow_replay='PASS'" in rendered
    assert "Raw top-level JSON escaped property name rejected" in rendered
    assert "Raw top-level JSON duplicate property name rejected" in rendered
    assert "v31_failure_\\u0065vidence" in rendered
    assert "$escapedAliasRejected" in rendered
    assert "$caseAliasRejected" in rendered
    assert "function Assert-ExactCanonicalJsonDocumentReplay(" in rendered
    assert "whole_document_canonical_json_replay='PASS'" in rendered
    assert "$singleQuotedAlias" in rendered
    assert "$unquotedAlias" in rendered
    assert "$commentedAlias" in rendered
    assert "$nonCanonicalWholeDocumentRejected-ne3" in rendered
    assert "$predecessorCustodyGuard=New-Object IO.FileStream" in rendered
    assert "Pre-lock predecessor custody exact byte replay rejected" in rendered
    assert "$predecessorCustodyHash=Get-BytesSha256 $custodyObservedBytes" in rendered
    assert "Get-Sha256 $predecessorCustodyFile" not in rendered
    assert "$predecessorCustodyGuard.Dispose()" in rendered


def test_rendered_successor_has_one_production_launch(rendered):
    assert (
        rendered.count(
            "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess"
        )
        == 1
    )
    assert (
        rendered.count(
            "canonical_token_sha256=$canonicalMonitorContract.token_sha256;"
            "readiness_self_test=$false}"
        )
        == 1
    )
    assert rendered.count("readiness_self_test=$true") == 1


def test_live_writer_uses_handle_length_without_drvfs_size_equality(rendered):
    assert "$length=[long]$stream.Length" in rendered
    assert (
        "if($length-gt[int]::MaxValue){throw [IO.InvalidDataException]::new("
        '"$Label log length rejected")}' in rendered
    )
    assert "$length-ne$before.size" not in rendered
    assert "$length-ne$before.size-or$length-gt[ int ]::MaxValue" not in rendered


def test_rendered_resource_monitor_program_parses(builder):
    ast.parse(resource_python(builder))


def test_all_embedded_python_programs_parse(rendered):
    programs = re.findall(r"(?ms)^\$[A-Za-z0-9]+Source = @'\n(.*?)\n'@$", rendered)
    assert len(programs) >= 9
    for program in programs:
        ast.parse(program)


def test_exact_namespace_pair_is_recorded(builder):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 1000, "python3", ["candidate"])
    table = ns["mark_namespace_states"](base_table(candidate), 10, exact_stat)
    assert table[30]["namespace_state"] == "EXACT"
    assert table[30]["mnt_ns"] == [7, 101]
    assert table[30]["pid_ns"] == [7, 202]
    assert table[1]["namespace_state"] == "EXACT"
    assert table[10]["namespace_state"] == "NOT_REQUIRED_MONITOR_ANCESTRY"
    assert table[20]["namespace_state"] == "NOT_REQUIRED_WATCHER_IDENTITY"


def test_exact_infrastructure_is_exempt_only_after_namespace_permission_denial(builder):
    ns = policy_namespace(builder)
    attempted: list[str] = []

    def denied(path: str):
        if path.startswith("/proc/1/"):
            attempted.append(path)
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    frozen: dict[int, list[object]] = {}
    table = ns["mark_namespace_states"](base_table(), 10, denied, frozen)
    assert attempted == ["/proc/1/ns/mnt"]
    assert table[1]["namespace_state"] == "NOT_REQUIRED_TRUSTED_INFRASTRUCTURE"
    assert frozen[1][4] == 100

    drifted = base_table()
    drifted[1]["starttime"] = 101
    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["mark_namespace_states"](drifted, 10, denied, frozen)


def test_infrastructure_freeze_survives_namespace_visibility_transitions(builder):
    ns = policy_namespace(builder)
    frozen: dict[int, list[object]] = {}

    def denied(path: str):
        if path.startswith("/proc/1/ns/"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    initial = ns["mark_namespace_states"](base_table(), 10, denied, frozen)
    assert initial[1]["namespace_state"] == "NOT_REQUIRED_TRUSTED_INFRASTRUCTURE"
    assert frozen[1][4] == 100

    frozen_identity = list(frozen[1])
    unchanged_readable = ns["mark_namespace_states"](
        base_table(), 10, exact_stat, frozen
    )
    assert unchanged_readable[1]["namespace_state"] == "EXACT"
    assert frozen[1] == frozen_identity

    drifted = base_table()
    drifted[1]["starttime"] = 101
    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["mark_namespace_states"](drifted, 10, exact_stat, frozen)

    accessible_frozen: dict[int, list[object]] = {}
    accessible = ns["mark_namespace_states"](
        base_table(), 10, exact_stat, accessible_frozen
    )
    assert accessible[1]["namespace_state"] == "EXACT"
    assert accessible_frozen[1][4] == 100

    accessible_identity = list(accessible_frozen[1])
    unchanged_denied = ns["mark_namespace_states"](
        base_table(), 10, denied, accessible_frozen
    )
    assert (
        unchanged_denied[1]["namespace_state"] == "NOT_REQUIRED_TRUSTED_INFRASTRUCTURE"
    )
    assert accessible_frozen[1] == accessible_identity
    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["mark_namespace_states"](drifted, 10, denied, accessible_frozen)


def test_infrastructure_freeze_set_growth_is_bound_and_then_immutable(builder):
    ns = policy_namespace(builder)
    frozen: dict[int, list[object]] = {}
    ns["mark_namespace_states"](base_table(), 10, exact_stat, frozen)
    init_identity = list(frozen[1])

    plan9 = row(
        6,
        1,
        0,
        "init",
        [
            "plan9",
            "--control-socket",
            "6",
            "--log-level",
            "4",
            "--server-fd",
            "7",
            "--pipe-fd",
            "9",
            "--log-truncate",
        ],
    )
    plan9.update(pgrp=0, session=0, exe=None)
    ns["mark_namespace_states"](base_table(plan9), 10, exact_stat, frozen)
    assert set(frozen) == {1, 6}
    assert frozen[1] == init_identity
    assert frozen[6][4] == 600

    drifted_plan9 = dict(plan9, starttime=601)
    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["mark_namespace_states"](base_table(drifted_plan9), 10, exact_stat, frozen)


def test_frozen_infrastructure_pid_cannot_become_canonical_shaped(builder):
    ns = policy_namespace(builder)
    frozen: dict[int, list[object]] = {}
    plan9 = row(
        6,
        1,
        0,
        "init",
        [
            "plan9",
            "--control-socket",
            "6",
            "--log-level",
            "4",
            "--server-fd",
            "7",
            "--pipe-fd",
            "9",
            "--log-truncate",
        ],
    )
    plan9.update(pgrp=0, session=0, exe=None)
    ns["mark_namespace_states"](base_table(plan9), 10, exact_stat, frozen)
    assert frozen[6][4] == 600

    canonical_shaped = row(
        6,
        1,
        1000,
        "timeout",
        ["/usr/bin/timeout", "--signal=TERM", "--kill-after=15s", "600s"],
    )
    canonical_shaped["starttime"] = 601
    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["mark_namespace_states"](
            base_table(canonical_shaped), 10, exact_stat, frozen
        )


def test_sample_rejects_frozen_pid_reuse_before_canonical_seen_changes(builder):
    ns = policy_namespace(builder)
    sample_node = next(
        node
        for node in ast.parse(resource_python(builder)).body
        if isinstance(node, ast.FunctionDef) and node.name == "sample"
    )
    exec(
        compile(ast.Module(body=[sample_node], type_ignores=[]), "<sample>", "exec"),
        ns,
    )
    frozen: dict[int, list[object]] = {}
    plan9 = row(
        6,
        1,
        0,
        "init",
        [
            "plan9",
            "--control-socket",
            "6",
            "--log-level",
            "4",
            "--server-fd",
            "7",
            "--pipe-fd",
            "9",
            "--log-truncate",
        ],
    )
    plan9.update(pgrp=0, session=0, exe=None)
    ns["mark_namespace_states"](base_table(plan9), 10, exact_stat, frozen)

    timeout_argv = [
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=15s",
        "600s",
    ]
    canonical_shaped = row(6, 1, 1000, "timeout", timeout_argv)
    canonical_shaped["starttime"] = 601
    ns.update(
        seen=False,
        sequence=0,
        anchor_ns=None,
        anchor_start=None,
        anchor_uid=None,
        admitted={},
        last_monotonic_ns=None,
        maximum_observed_gap_ns=0,
        max_canonical_processes=0,
        max_gap_ns=750_000_000,
        watcher_pid=20,
        timeout_argv=timeout_argv,
        bwrap_argv=["canonical-bwrap"],
        test_argv=["canonical-test"],
        time=SimpleNamespace(monotonic_ns=lambda: 1_000_000_000),
        os=SimpleNamespace(getpid=lambda: 10),
        rows=lambda: ns["mark_namespace_states"](
            base_table(canonical_shaped), 10, exact_stat, frozen
        ),
    )

    with pytest.raises(
        RuntimeError, match="pre-admitted infrastructure PID identity drift"
    ):
        ns["sample"]()
    assert ns["seen"] is False
    assert ns["sequence"] == 0


def test_only_exact_wsl_control_process_shapes_are_pre_admitted(builder):
    ns = policy_namespace(builder)
    init = row(1, 0, 0, "init(Ubuntu)", ["/init"])
    init.update(pgrp=0, session=0, exe=None)
    plan9 = row(
        6,
        1,
        0,
        "init",
        [
            "plan9",
            "--control-socket",
            "6",
            "--log-level",
            "4",
            "--server-fd",
            "7",
            "--pipe-fd",
            "9",
            "--log-truncate",
        ],
    )
    plan9.update(pgrp=0, session=0, exe=None)
    leader = row(9, 1, 0, "SessionLeader", ["/init"])
    leader.update(pgrp=9, session=9, exe=None)
    relay = row(10, 9, 0, "Relay(11)", ["/init"])
    relay.update(pgrp=9, session=9, exe=None)
    table = {
        1: init,
        6: plan9,
        9: leader,
        10: relay,
        11: row(11, 10, 1000, "bash", ["bash"]),
    }
    assert all(ns["minimal_infrastructure"](table[pid], table) for pid in (1, 6, 9, 10))
    assert ns["minimal_infrastructure"](table[11], table) is False


@pytest.mark.parametrize(
    ("pid", "mutation"),
    [
        (1, {"exe": [9, 9]}),
        (6, {"exe": [9, 9]}),
        (9, {"ppid": 99}),
        (10, {"pgrp": 10}),
    ],
)
def test_near_match_wsl_control_shapes_do_not_receive_permission_exemption(
    builder, pid, mutation
):
    ns = policy_namespace(builder)
    table = base_table()
    candidate = row(pid, 1, 0, "init", ["/init"])
    if pid == 1:
        candidate = row(1, 0, 0, "init(Ubuntu)", ["/init"])
        candidate.update(pgrp=0, session=0, exe=None)
    elif pid == 6:
        candidate = row(
            6,
            1,
            0,
            "init",
            [
                "plan9",
                "--control-socket",
                "6",
                "--log-level",
                "4",
                "--server-fd",
                "7",
                "--pipe-fd",
                "9",
                "--log-truncate",
            ],
        )
        candidate.update(pgrp=0, session=0, exe=None)
    elif pid == 9:
        candidate = row(9, 1, 0, "SessionLeader", ["/init"])
        candidate.update(pgrp=9, session=9, exe=None)
    else:
        leader = row(9, 1, 0, "SessionLeader", ["/init"])
        leader.update(pgrp=9, session=9, exe=None)
        table[9] = leader
        table[11] = row(11, 10, 1000, "bash", ["bash"])
        candidate = row(10, 9, 0, "Relay(11)", ["/init"])
        candidate.update(pgrp=9, session=9, exe=None)
    candidate.update(mutation)
    table[pid] = candidate
    assert ns["minimal_infrastructure"](candidate, table) is False


@pytest.mark.parametrize(
    "candidate",
    [
        row(30, 1, 0, "systemd", ["/evil"]),
        row(30, 1, 0, "init", ["/evil"]),
        row(30, 1, 0, "SessionLeader", ["/evil"]),
        row(30, 1, 0, "Relay(99)", ["/init"]),
        row(
            30,
            1,
            0,
            "init",
            [
                "plan9",
                "--control-socket",
                "not-a-fd",
                "--log-level",
                "4",
                "--server-fd",
                "7",
                "--pipe-fd",
                "9",
                "--log-truncate",
            ],
        ),
    ],
)
def test_mutable_root_process_labels_do_not_bypass_namespace(builder, candidate):
    ns = policy_namespace(builder)
    assert ns["minimal_infrastructure"](candidate, base_table(candidate)) is False

    def denied(path: str):
        if path.startswith("/proc/30/ns/"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    with pytest.raises(RuntimeError, match="permission denied for relevant process"):
        ns["mark_namespace_states"](base_table(candidate), 10, denied)


@pytest.mark.parametrize(
    "comm",
    [
        "systemd",
        "systemd-journal",
        "systemd-udevd",
        "systemd-network",
        "systemd-resolve",
        "systemd-timesyn",
        "systemd-logind",
        "dbus-daemon",
        "cron",
        "rsyslogd",
        "wsl-pro-service",
        "init",
    ],
)
def test_every_legacy_allowlisted_comm_with_hostile_argv_is_rejected(builder, comm):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 0, comm, ["/evil"])
    table = base_table(candidate)
    assert ns["minimal_infrastructure"](candidate, table) is False

    def denied(path: str):
        if path.startswith("/proc/30/ns/"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    with pytest.raises(RuntimeError, match="permission denied for relevant process"):
        ns["mark_namespace_states"](table, 10, denied)


@pytest.mark.parametrize(
    "candidate",
    [
        row(30, 1, 1000, "systemd", ["/usr/lib/systemd/systemd"]),
        row(30, 1, 0, "systemd", ["/evil"]),
        row(30, 1, 0, "unknown-root", ["/evil"]),
    ],
)
def test_untrusted_permission_denial_is_explicit_rejection(builder, candidate):
    ns = policy_namespace(builder)

    def denied(path: str):
        if path.startswith("/proc/30/ns/"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    with pytest.raises(RuntimeError, match="permission denied for relevant process"):
        ns["mark_namespace_states"](base_table(candidate), 10, denied)


@pytest.mark.parametrize("denied_leaf", ["mnt", "pid"])
def test_partial_namespace_permission_denial_is_rejected(builder, denied_leaf):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 1000, "python3", ["candidate"])

    def partial(path: str):
        if path == f"/proc/30/ns/{denied_leaf}":
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return exact_stat(path)

    with pytest.raises(RuntimeError, match="permission denied for relevant process"):
        ns["mark_namespace_states"](base_table(candidate), 10, partial)


def test_non_permission_namespace_error_is_not_swallowed(builder):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 1000, "python3", ["candidate"])

    def io_error(path: str):
        if path.startswith("/proc/30/ns/"):
            raise OSError(errno.EIO, "I/O error", path)
        return exact_stat(path)

    with pytest.raises(OSError) as captured:
        ns["mark_namespace_states"](base_table(candidate), 10, io_error)
    assert captured.value.errno == errno.EIO


def test_only_vanished_namespace_row_is_removed(builder):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 1000, "python3", ["candidate"])

    def vanished(path: str):
        if path.startswith("/proc/30/ns/"):
            raise FileNotFoundError(errno.ENOENT, "gone", path)
        return exact_stat(path)

    table = ns["mark_namespace_states"](base_table(candidate), 10, vanished)
    assert 30 not in table
    assert set(table) == {1, 10, 20}


def test_canonical_identity_requires_complete_exact_namespaces(builder):
    ns = policy_namespace(builder)
    candidate = row(30, 1, 1000, "python3", ["candidate"])
    with pytest.raises(RuntimeError, match="exact namespace identity required"):
        ns["require_exact_namespace"](candidate, "canonical test")
    candidate["namespace_state"] = "EXACT"
    candidate["mnt_ns"] = [7, 101]
    candidate["pid_ns"] = None
    with pytest.raises(RuntimeError, match="exact namespace identity required"):
        ns["ident"](candidate)


def test_namespace_identity_has_no_magic_link_fallback(builder):
    source = resource_python(builder)
    assert "readlink" not in source
    assert "fixed_infra" not in source
    assert "namespace identity permission denied for relevant process" in source
    assert "except PermissionError as exc" in source
    assert source.index("state=resolve_namespace_pair(row,stat_fn)") < source.index(
        "if minimal_infrastructure(row,table)"
    )
    assert "namespace_permission_denials':0" in source
    assert "pre-admitted infrastructure PID identity drift" in source
    assert "admitted_infrastructure_json" in source
    assert "admitted_infrastructure_sha256" in source
    frozen_precheck = (
        "if row['pid'] in infra_freeze:freeze_infrastructure(row,table,infra_freeze)"
    )
    assert frozen_precheck in source
    assert source.index(frozen_precheck) < source.index("if row['pid']==mine")


def test_nonconsuming_live_readiness_switch_is_bound(rendered):
    assert "[switch]$ResourceMonitorReadinessSelfTest" in rendered
    assert "Invoke-ResourceMonitorReadinessSelfTest" in rendered
    assert "v33_artifacts_created=$false" in rendered
    assert "canonical_suite_executed=$false" in rendered
    assert "namespace_not_required_infrastructure_rows" in rendered
    assert "kind='READY';readiness_self_test=$false;target_interval_ms=100" in rendered
    assert rendered.count("namespace_permission_denials=0;process_rows=2") >= 4


def test_live_log_reader_accepts_only_identity_stable_monotonic_append_prefixes(
    rendered,
):
    reader = rendered.split("function Read-StableUtf8Log", 1)[1].split(
        "function Invoke-StableLogReaderStateRegression", 1
    )[0]
    assert "$stableLogReadStates=@{}" in rendered
    assert "$stableLogReadStates[$key]" in reader
    assert "$attemptLength=if($identityBound)" in reader
    assert "$attemptPrefixSha=if($identityBound)" in reader
    assert "$currentLength-lt$length" in rendered
    assert "$share=[IO.FileShare]::Read;" in reader
    assert "[IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete" not in reader
    assert "log identity changed from bound handle" in reader
    assert "log truncation below bound prefix" in reader
    assert "log prior prefix digest changed" in reader
    assert "$readHash=Get-BytePrefixSha256 $bytes $bytes.Length" in reader
    assert "[void]$stream.Seek(0,[IO.SeekOrigin]::Begin)" in reader
    assert "$replayHash-cne$readHash" in reader
    assert "log held-handle prefix replay changed" in reader
    assert "identity or truncation drift after held-handle prefix replay" in reader
    assert "log identity or truncation drift during append-prefix read" in rendered
    assert "log path identity drift" in rendered
    assert "$length-ne$before.size" not in reader
    assert "$after.size" not in reader
    assert "$pathIdentity.size" not in reader
    assert "$stream.Length-ne$length-or$after.volume" not in rendered
    assert reader.count("catch [IO.IOException]") == 2
    assert "catch [IO.IOException]{if($writerSupplied" in reader
    assert "catch [IO.InvalidDataException]" not in reader
    assert "Invoke-StableLogReaderStateRegression" in rendered
    assert "replacement='REJECTED'" in rendered
    assert "truncation='REJECTED'" in rendered
    assert "same_identity_prefix_rewrite='REJECTED'" in rendered
    assert "concurrent_rewrite_while_guarded='REJECTED_BY_SHARE'" in rendered
    assert "log_reader_state_regression=$logReaderRegression" in rendered
    assert (
        "bounded_explicit_FileStream_restrictive_read_guard_persistent_"
        "identity_monotonic_prefix_digest_terminal_LF_UTF8_JSON" in rendered
    )


def test_retained_v32_snapshot_is_bound_in_all_terminal_paths(rendered):
    assert rendered.count("Invoke-RetainedV32SnapshotVerifier") >= 6
    assert "retained_v32_snapshot_rejection_replay" in rendered
    assert "retained_v32_snapshot_final_replay" in rendered
    assert "retained-v32-snapshot-terminal-custody.json" in rendered
    cleanup_match = re.search(r"(?s)\$cleanupSource = @'\r?\n(.*?)\r?\n'@", rendered)
    assert cleanup_match is not None
    cleanup = cleanup_match.group(1)
    assert "/tmp/planora-muni-v30-canonical-tests-" not in cleanup
    assert "/tmp/planora-muni-v31-canonical-tests-" not in cleanup
    assert "/tmp/planora-muni-v32-canonical-tests-" not in cleanup


def test_stored_runner_is_deterministic_when_present(rendered):
    if RUNNER_PATH.exists():
        assert RUNNER_PATH.read_text(encoding="utf-8") == rendered


def test_stored_authorization_is_v13_when_present(builder):
    if not AUTH_PATH.exists() or not RUNNER_PATH.exists():
        pytest.skip("successor has not been generated yet")
    authorization = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    assert authorization["schema"] == "planora.itc2019.canonical-test-authorization.v13"
    assert authorization["test_id"] == RUN_ID
    assert authorization["runner"]["sha256"] == builder.sha256(RUNNER_PATH)
    assert (
        authorization["evidence_contract"][
            "complete_v28_v29_v30_v31_v32_predecessor_pin_count"
        ]
        == 89
    )


def test_fresh_v33_namespace_and_shared_lock_are_absent():
    receipts = REPO / "output/diagnostic-receipts"
    artifacts = [
        path for path in receipts.iterdir() if path.name.startswith(V33_PREFIX)
    ]
    assert artifacts == []
    assert not (receipts / "planora-shared-heavy-wsl.lock").exists()
