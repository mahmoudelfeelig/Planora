#!/usr/bin/env python3
"""One-shot canonical wrapper for the bounded AGH-FAL17 v18 retained probe.

This file is inert unless invoked with the exact consume flag. Importing it and
running its static self-checks never creates a claim or executes a child.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence


RUN_ID = "b06b75d9d1ff4a66b95d7afdf1896b5a"
REPOSITORY_WSL = "/mnt/d/Stuff/Projects/Sites/Planora"
REPOSITORY = Path(REPOSITORY_WSL)
CHAIN = REPOSITORY / "benchmarks/probe_diagnostics/agh_v18"
OUTPUT = REPOSITORY / "output/diagnostic-receipts"
WRAPPER = REPOSITORY / "scripts/run_agh_v18_canonical_probe.py"
WRAPPER_WSL = f"{REPOSITORY_WSL}/scripts/run_agh_v18_canonical_probe.py"
AUTHORIZATION = CHAIN / (
    "agent-aghfal17-native-v18-probe-authorization-20260827T063650Z-b06b75d9.json"
)
PREFIX = OUTPUT / f"agh-fal17-v18-canonical-probe-{RUN_ID}"
CLAIM = Path(f"{PREFIX}.claim")
CLAIM_OWNER = CLAIM / "owner.json"
PREFLIGHT = Path(f"{PREFIX}.preflight.json")
POSTFLIGHT = Path(f"{PREFIX}.postflight.json")
WATCHER = Path(f"{PREFIX}.watcher.json")
STDOUT = Path(f"{PREFIX}.stdout.json")
STDERR = Path(f"{PREFIX}.stderr.log")
EXIT_CODE = Path(f"{PREFIX}.exit-code.txt")
CHECKSUMS = Path(f"{PREFIX}.checksums.json")
RESULT_RECEIPT = Path(f"{PREFIX}.result-receipt.json")
AUTHORIZATION_SNAPSHOT = Path(f"{PREFIX}.authorization.json")
INVOCATIONS_SNAPSHOT = Path(f"{PREFIX}.invocations.json")
HEAVY_LOCK = OUTPUT / ".planora-wsl-heavy-task.lock"
HEAVY_LOCK_OWNER = Path(f"{PREFIX}.heavy-lock-owner.json")
SNAPSHOT_HOST_WSL = f"/tmp/planora-agh-fal17-v18-snapshot-{RUN_ID}"
SNAPSHOT_HOST = Path(SNAPSHOT_HOST_WSL)
SNAPSHOT_MOUNT = PurePosixPath("/snapshot")
SITE_PACKAGES_WSL = f"{REPOSITORY_WSL}/.venv/lib/python3.12/site-packages"
OFFICIAL_PARENT_WSL = (
    f"{REPOSITORY_WSL}/data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019"
)
RETAINED_OUTPUTS = (
    PREFLIGHT,
    POSTFLIGHT,
    WATCHER,
    STDOUT,
    STDERR,
    EXIT_CODE,
    CHECKSUMS,
    RESULT_RECEIPT,
    AUTHORIZATION_SNAPSHOT,
    INVOCATIONS_SNAPSHOT,
    HEAVY_LOCK_OWNER,
)

EXPLICIT_CONSUME_FLAG = "--consume-exactly-one-authorized-probe"
PROBE_TIMEOUT_SECONDS = 250
WRAPPER_GUARD_SECONDS = 260
POSTFLIGHT_ZERO_SNAPSHOTS = 2
POSTFLIGHT_INTERVAL_SECONDS = 0.25

STATIC_FAILURE_RECEIPT = (
    b'{"authorization_consumed":true,"automatic_retry_authorized":false,'
    b'"claim_marker_retained":true,'
    b'"fallback_reason":"post_claim_serialization_or_publication_failure",'
    b'"minimal_post_claim_failure_receipt":true,'
    b'"run_id":"b06b75d9d1ff4a66b95d7afdf1896b5a",'
    b'"schema":"planora.agh-fal17.native-v18-canonical-probe-result.v1",'
    b'"status":"NO_GO"}\n'
)

FROZEN_TREE: dict[str, dict[str, int | str]] = {
    "agent-aghfal17-native-v18-bootstrap.py": {
        "size_bytes": 12620,
        "sha256": "a9fb44cb5d69cd33fce8257b0e18f3ae98bc1efe63bd0a8e433034216f5931c7",
    },
    "agent-aghfal17-native-v18-derivation.json": {
        "size_bytes": 4600,
        "sha256": "e9ac3f3f6aa57cfa5d5ecc855603a7d3615652f63ee877657b4555b0b1154bbe",
    },
    "agent-aghfal17-native-v18-generic-validator.py": {
        "size_bytes": 5902,
        "sha256": "a7e45885980368d56083e321749337dcaf3fca8ef1e2a2c984181df9c5d6a89c",
    },
    "agent-aghfal17-native-v18-invocations.json": {
        "size_bytes": 19907,
        "sha256": "a72fe1d867a05cdf49f8ea5c45af60f80573d5a6fc94a7359df93369939a29d7",
    },
    "agent-aghfal17-native-v18-launcher.sh": {
        "size_bytes": 10942,
        "sha256": "8ddb40f336a92d8b3c78cf6b1cb611dd5fc2ff1b691dad9f9b743a321e1e7aeb",
    },
    "agent-aghfal17-native-v18-minimal-tcb.sha256": {
        "size_bytes": 5119,
        "sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    },
    "agent-aghfal17-native-v18-outer-controller.py": {
        "size_bytes": 50971,
        "sha256": "5c11831923d96ac2ee8e03a7560b385ba0009acf459614ea69e3d0387511e2bd",
    },
    "agent-aghfal17-native-v18-review-certificate.json": {
        "size_bytes": 1476,
        "sha256": "7b3a68fcf371ccae06db49a00756ebd5fa3df3544e40fea21802f61768b3bb0d",
    },
    "agent-aghfal17-native-v18-review-freeze.json": {
        "size_bytes": 40151,
        "sha256": "261f01c01e1931ff8db1e51d4c1774df06e1b79448880ea9ab59b24fd67c99c8",
    },
    "agent-aghfal17-native-v18-runner.py": {
        "size_bytes": 69999,
        "sha256": "24844dc75753765def9b33abed683c2855f9f329ebf2e252e697b59bdab6070f",
    },
    "agent-aghfal17-native-v18-stdlib.sha256": {
        "size_bytes": 67004,
        "sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    },
    "agent-aghfal17-native-v18-supervisor.py": {
        "size_bytes": 146570,
        "sha256": "bbb423ed711df801fad2b061ef7f3c86eb08ec8cf9daac531ebd5163a5839cbc",
    },
    "agent-aghfal17-native-v18-tests.py": {
        "size_bytes": 58449,
        "sha256": "9fcb6b78fcd20f44f1e9dec83797bc0f2f01b61b80a36a47340bec56d02f5434",
    },
}

STAGED_NAMES = (
    "agent-aghfal17-native-v18-outer-controller.py",
    "agent-aghfal17-native-v18-review-freeze.json",
    "agent-aghfal17-native-v18-invocations.json",
    "agent-aghfal17-native-v18-bootstrap.py",
    "agent-aghfal17-native-v18-launcher.sh",
    "agent-aghfal17-native-v18-supervisor.py",
    "agent-aghfal17-native-v18-runner.py",
    "agent-aghfal17-native-v18-minimal-tcb.sha256",
    "agent-aghfal17-native-v18-stdlib.sha256",
)

MASKED_DRIVE_DIRECTORIES = (
    "/mnt/d",
    "/mnt/d/Stuff",
    "/mnt/d/Stuff/Projects",
    "/mnt/d/Stuff/Projects/Sites",
    REPOSITORY_WSL,
    f"{REPOSITORY_WSL}/.venv",
    f"{REPOSITORY_WSL}/.venv/lib",
    f"{REPOSITORY_WSL}/.venv/lib/python3.12",
    f"{REPOSITORY_WSL}/data",
    f"{REPOSITORY_WSL}/data/external",
    f"{REPOSITORY_WSL}/data/external/itc2019-mpp-c33d15797686",
    f"{REPOSITORY_WSL}/data/external/itc2019-mpp-c33d15797686/raw",
    f"{REPOSITORY_WSL}/data/external/itc2019-mpp-c33d15797686/raw/data",
    f"{REPOSITORY_WSL}/data/external/itc2019-mpp-c33d15797686/raw/data/input",
    OFFICIAL_PARENT_WSL,
)

RUNTIME_ALIAS_WSL = "/opt"

AUTHORIZATION_BINDING: dict[str, Any] = {
    "schema": "planora.agh-fal17.native-v18-one-shot-probe-authorization.v1",
    "created_at_utc": "2026-08-27T06:36:50Z",
    "instance": "agh-fal17",
    "candidate": "native-v18",
    "run_id": RUN_ID,
    "decision": "AUTHORIZE_EXACTLY_ONE_BOUNDED_CANONICAL_PROBE",
    "retained_probe_authorized": True,
    "authorized_execution_count": 1,
    "official_launch_authorized": False,
    "official_input_authorized": False,
    "solver_authorized": False,
    "checkpoint_authorized": False,
    "certified_incumbent_authorized": False,
    "competitor_route_authorized": False,
    "publication_authorized": False,
    "automatic_retry_authorized": False,
    "authorization_consumption": {
        "claim_marker_path": (
            f"output/diagnostic-receipts/agh-fal17-v18-canonical-probe-{RUN_ID}.claim"
        ),
        "result_receipt_path": (
            "output/diagnostic-receipts/"
            f"agh-fal17-v18-canonical-probe-{RUN_ID}.result-receipt.json"
        ),
        "atomic_claim_primitive": "exclusive_mkdir",
        "atomic_evidence_primitive": "open_xb",
        "consume_before_preflight": True,
        "claim_retained_on_every_outcome": True,
        "receipt_create_only": True,
        "retry_prohibited": True,
    },
    "static_chain_review": {
        "verdict": "GO_FOR_INDEPENDENT_STATIC_CHAIN_REVIEW_ONLY",
        "execution_verdict_at_review": "NO_GO",
        "reviewed_builder_sha256": (
            "743f8eda9902bb70587db1d1a6868dab5d44c472c9974ba391e988579d027ed0"
        ),
        "reviewed_tree_file_count": 13,
        "windows_tests_passed": 72,
        "linux_only_tests_skipped": 1,
        "independent_checks_passed": 255,
        "python_ast_files_passed": 6,
        "powershell_ast_errors": 0,
        "ruff": "PASS",
        "wrapper_execution_review": "PENDING_SEPARATE_REVIEWER",
    },
    "frozen_tree": {
        "builder_path": "scripts/build_agh_v18_chain.ps1",
        "builder_size_bytes": 67417,
        "builder_sha256": (
            "743f8eda9902bb70587db1d1a6868dab5d44c472c9974ba391e988579d027ed0"
        ),
        "runtime_chain_file_count": 13,
        "artifacts": FROZEN_TREE,
    },
    "frozen_probe": {
        "freeze_manifest_path": (
            "benchmarks/probe_diagnostics/agh_v18/"
            "agent-aghfal17-native-v18-review-freeze.json"
        ),
        "freeze_manifest_size_bytes": 40151,
        "freeze_manifest_sha256": (
            "261f01c01e1931ff8db1e51d4c1774df06e1b79448880ea9ab59b24fd67c99c8"
        ),
        "invocations_path": (
            "benchmarks/probe_diagnostics/agh_v18/"
            "agent-aghfal17-native-v18-invocations.json"
        ),
        "invocations_size_bytes": 19907,
        "invocations_sha256": (
            "a72fe1d867a05cdf49f8ea5c45af60f80573d5a6fc94a7359df93369939a29d7"
        ),
        "outer_argv_count": 40,
        "outer_canonical_argv_sha256": (
            "f720ff7a8c7ba797c87e1ff7dbcfcc791a039b13aae9a40d797b7a9b497fbb10"
        ),
        "inner_argv_count": 29,
        "inner_canonical_argv_sha256": (
            "22c1992a3ac9955ddbc1989218611d94bd4e57178eb5a24f77b479bf670e8f7c"
        ),
        "terminal_mode": "--sealed-import-probe",
        "staged_closure_names": list(STAGED_NAMES),
    },
    "producer_checkpoint_evidence": {
        "required_key": "checkpoint_or_certified_provenance_used",
        "required_value_type": "builtins.bool",
        "required_value": False,
        "outer_payload_schema": ("planora.agh-fal17.native-v18-outer-controller.v1"),
        "outer_source_sha256": (
            "5c11831923d96ac2ee8e03a7560b385ba0009acf459614ea69e3d0387511e2bd"
        ),
        "inner_payload_schema": (
            "planora.agh-fal17.native-v18-sealed-import-supervisor.v1"
        ),
        "inner_source_sha256": (
            "bbb423ed711df801fad2b061ef7f3c86eb08ec8cf9daac531ebd5163a5839cbc"
        ),
        "supervisor_status_producers_with_owned_literal_false": 8,
        "outer_required_key_emitted": True,
        "inner_required_key_emitted": True,
        "exact_pair_required": True,
    },
    "frozen_limits": {
        "process_generation_vmrss_plus_vmswap_limit_kib": 368640,
        "whole_launch_process_plus_sealed_plus_report_limit_kib": 614400,
        "initial_memavailable_floor_kib": 1900000,
        "initial_sample_count": 2,
        "initial_sample_interval_seconds": 5,
        "runtime_memavailable_floor_kib": 900000,
        "probe_outer_wall_seconds": 240,
        "probe_inner_wall_seconds": 180,
        "process_level_timeout_seconds": PROBE_TIMEOUT_SECONDS,
        "wrapper_guard_wall_seconds": WRAPPER_GUARD_SECONDS,
        "final_zero_snapshots_required": POSTFLIGHT_ZERO_SNAPSHOTS,
    },
    "isolation_contract": {
        "root_contract": "read_only_system_root_with_private_drive_mask",
        "live_host_root_bound_read_only": True,
        "live_repository_root_bound": False,
        "live_drive_root_bound": False,
        "private_live_drive_mask": "/mnt",
        "working_directory": str(SNAPSHOT_MOUNT),
        "private_tmpfs": "/tmp",
        "private_snapshot_host_path": SNAPSHOT_HOST_WSL,
        "snapshot_mount_path": str(SNAPSHOT_MOUNT),
        "snapshot_private_exclusive_directory": True,
        "snapshot_directory_mode_before_launch": "0500",
        "snapshot_file_mode": "0400",
        "snapshot_read_only_bind": True,
        "tmp_mirrors_read_only_from_snapshot": True,
        "snapshot_cleanup_required_before_pass_receipt": True,
        "runtime_read_only_alias": RUNTIME_ALIAS_WSL,
        "runtime_read_only_source": SITE_PACKAGES_WSL,
        "repository_visible_subtree": SITE_PACKAGES_WSL,
        "repository_visible_subtree_purpose": "immutable_runtime_only",
        "official_path_is_dev_null_only": True,
        "unshare_all": True,
        "new_session": True,
        "die_with_parent": True,
        "capabilities_dropped": "ALL",
        "official_input_mask_source": "/dev/null",
        "immutable_staged_closure": True,
        "staging_create_only": True,
        "environment": {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
    },
    "watcher_contract": {
        "live_until_child_exit": True,
        "live_through_postflight": True,
        "identity": "pid_plus_starttime_ticks",
        "strict_process_level_timeout": True,
        "wrapper_monotonic_guard": True,
        "postflight_zero_snapshots": POSTFLIGHT_ZERO_SNAPSHOTS,
        "cleanup_required_before_pass_receipt": True,
        "cleanup_runs_after_every_popen_outcome": True,
        "normal_root_exit_still_terminates_tracked_descendants": True,
        "term_then_kill_then_final_wait": True,
        "shared_heavy_lock_released_before_pass_receipt": True,
        "full_dependency_closure_revalidated_postflight": True,
        "all_runtime_records_revalidated_postflight": True,
        "all_runtime_pins_revalidated_postflight": True,
    },
    "strict_result_contract": {
        "stdout": "one_canonical_json_object_plus_lf",
        "outer_schema_exact": True,
        "inner_schema_exact": True,
        "unknown_outer_keys_rejected": True,
        "unknown_inner_keys_rejected": True,
        "truthful_no_go_on_any_failed_predicate": True,
        "pass_receipt_requires_verified_cleanup": True,
        "post_claim_static_fallback_is_precomputed": True,
        "static_fallback_bypasses_json_serialization": True,
        "static_fallback_failure_boundary": [
            "exclusive_os_open_failure",
            "os_write_failure_or_short_write",
            "file_or_parent_fsync_failure",
            "os_fchmod_or_close_failure",
            "process_termination_or_uncatchable_interpreter_failure",
        ],
    },
    "rejected_predecessor": {
        "candidate": "native-v17",
        "decision": "NO_GO_REQUIRES_SUCCESSOR_CHAIN_CHECKPOINT_EVIDENCE",
        "builder_sha256": (
            "4a895136bf05d1eb621a4b5a659aac6485229a971791eb98e4e704bfa291f989"
        ),
        "freeze_manifest_sha256": (
            "1919dc785c6d1a6d3f06eb5f087faacde2d2194b890d8a0da70943ac829977c1"
        ),
        "outer_source_sha256": (
            "3fe5dba53e9c6293694779c5bec0100e46f9fbcaa19b9ef8f96531db96723a35"
        ),
        "supervisor_source_sha256": (
            "56a78bc55e2b6e324397d9e7350346382d63e1676cdda06553b40dd280c0cc89"
        ),
        "accepted_by_this_wrapper": False,
    },
    "mandatory_execution_conditions": [
        "A separate reviewer must return execution GO before this authorization is consumed.",
        "Invoke only with the exact explicit one-shot consume flag and never retry this run ID.",
        "Atomically retain the exclusive claim before preflight and retain it on every outcome.",
        "Require two passing MemAvailable and process-census samples at least five seconds apart.",
        "Mask all of /mnt with a private tmpfs before child execution; recreate only the exact read-only runtime subtree and the /dev/null official-input path, with no live repository or drive root reachable.",
        "Execute only the frozen probe argv under the process timeout and independent live watcher.",
        "Reject every official-input, solver, checkpoint, incumbent, competitor, launch, or publication route.",
        "Accept stdout only as one canonical exact-schema outer object with one exact-schema inner object.",
        "Create a PASS receipt only after child exit, process-group cleanup, snapshot cleanup, two zero snapshots, full dependency and runtime replay, stable pins, and lock release.",
        "Never authorize automatic retry, official launch, official input, solver, checkpoint, incumbent, competitor, or publication.",
    ],
}

OUTER_KEYS = {
    "breach",
    "canonical_argv_encoding",
    "canonical_argv_sha256",
    "checkpoint_or_certified_provenance_used",
    "cleanup",
    "contained_root_exit_code",
    "elapsed_seconds",
    "errors",
    "initial_host_samples",
    "initial_memavailable_floor_kib",
    "inner_payload",
    "inner_stderr",
    "inner_stdout",
    "mode",
    "numeric_process_group_signal_sent",
    "official_instance_opened",
    "outer_authoritative",
    "outer_wall_seconds",
    "peak_accounting",
    "post_exit_empty",
    "probe_child_process_started",
    "process_generation_memory_limit_kib",
    "publication",
    "root_command",
    "root_process_started",
    "runtime_memavailable_floor_kib",
    "schema",
    "sealed_controller",
    "sealed_storage",
    "solver_child_process_started",
    "status",
    "whole_launch_memory_limit_kib",
}

INNER_KEYS = {
    "breach",
    "checkpoint_or_certified_provenance_used",
    "child_exit_code",
    "child_payload",
    "errors",
    "external_launcher_attestation",
    "final_source_rehash",
    "observed_child_elapsed_seconds",
    "official_instance_opened",
    "official_opened",
    "official_solution_xml_published",
    "peak_process_group_accounting_sample",
    "peak_process_group_pids",
    "peak_process_group_rss_kib",
    "peak_process_group_vmrss_plus_vmswap_kib",
    "peak_process_group_vmswap_kib",
    "peak_whole_launch_accounting_sample",
    "peak_whole_launch_rss_kib",
    "peak_whole_launch_supervisor_in_child_group",
    "peak_whole_launch_supervisor_rss_kib",
    "peak_whole_launch_supervisor_vmswap_kib",
    "peak_whole_launch_vmrss_plus_vmswap_kib",
    "peak_whole_launch_vmswap_kib",
    "probe_accounting_source",
    "probe_child_process_started",
    "probe_hard_wall_seconds",
    "probe_numeric_pgid_accounting_rescan_used",
    "process_group_cleanup",
    "process_group_vmrss_plus_vmswap_limit_kib",
    "publication",
    "run_directory",
    "schema",
    "scratch_directory",
    "scratch_final_entries",
    "sealed_captures",
    "sealed_runtime_bundle",
    "sealed_runtime_bundle_final_replay",
    "solver_child_process_started",
    "solver_execution_started",
    "status",
    "stderr",
    "stdout",
    "stop_action",
    "successfully_reaped_zero_contributions",
    "whole_launch_vmrss_plus_vmswap_limit_kib",
}

CHILD_KEYS = {
    "executing_python",
    "final_capture_replay",
    "final_loaded_runtime_replay",
    "final_runtime_bundle_replay",
    "final_system_runtime",
    "final_system_runtime_comparison",
    "imported_modules",
    "loaded_runtime",
    "official_instance_opened",
    "official_opened",
    "official_solution_xml_published",
    "probe_child_process_started",
    "publication",
    "runtime_install",
    "schema",
    "solver_child_process_started",
    "solver_execution_started",
    "status",
    "system_runtime_after_import",
    "system_runtime_import_comparison",
    "system_runtime_start",
}

FORBIDDEN_ROUTE_TOKENS = {
    "--launch",
    "--allow-official-input",
    "--allow-solver",
    "--allow-publication",
    "--checkpoint",
    "--resume-checkpoint",
    "--load-checkpoint",
    "--certified-incumbent",
    "--competitor",
}


class ContractError(RuntimeError):
    """A fail-closed wrapper contract rejection."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def exact_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    def reject_nonstandard_constant(value: str) -> None:
        raise ContractError(f"{label} contains non-standard JSON constant {value}")

    try:
        value = json.loads(raw, parse_constant=reject_nonstandard_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ContractError(f"{label} is not one canonical JSON object plus LF")
    return value


def pinned_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    def reject_nonstandard_constant(value: str) -> None:
        raise ContractError(f"{label} contains non-standard JSON constant {value}")

    try:
        value = json.loads(raw, parse_constant=reject_nonstandard_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ContractError(f"{label} is not one pinned JSON object")
    return value


def _identity(row: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(row.st_dev),
        int(row.st_ino),
        int(row.st_size),
        stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode),
        int(row.st_nlink),
    )


def _read_at(descriptor: int, size: int, offset: int) -> bytes:
    if hasattr(os, "pread"):
        return os.pread(descriptor, size, offset)
    os.lseek(descriptor, offset, os.SEEK_SET)
    return os.read(descriptor, size)


def read_pinned(path: Path, expected: Mapping[str, int | str], label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ContractError(f"{label} is not a single-link regular file")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            block = _read_at(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise ContractError(f"{label} ended during retained read")
            chunks.append(block)
            offset += len(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if (
        _identity(before) != _identity(after)
        or _identity(after) != _identity(named)
        or len(raw) != expected["size_bytes"]
        or digest(raw) != expected["sha256"]
    ):
        raise ContractError(f"{label} identity, size, or digest drift")
    return raw


def read_single_link(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ContractError(f"{label} is not a single-link regular file")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            block = _read_at(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise ContractError(f"{label} ended during retained read")
            chunks.append(block)
            offset += len(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after) or _identity(after) != _identity(named):
        raise ContractError(f"{label} identity changed during retained read")
    return b"".join(chunks)


def write_create_only(path: Path, raw: bytes, mode: int = 0o400) -> None:
    view = memoryview(raw)
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ContractError(f"create-only write stalled: {path}")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
    if os.name != "nt":
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def low_level_static_failure_receipt(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        written = os.write(descriptor, STATIC_FAILURE_RECEIPT)
        if written != len(STATIC_FAILURE_RECEIPT):
            raise OSError("static fallback short write")
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)
    if os.name != "nt":
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def claim_once(claim: Path, owner: Path, wrapper_path: Path) -> dict[str, Any]:
    os.mkdir(claim, 0o700)
    claimed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {
        "schema": "planora.agh-fal17.native-v18-one-shot-claim.v1",
        "run_id": RUN_ID,
        "claim_marker_path": str(claim),
        "claimed_at_utc": claimed_at,
        "hostname": platform.node(),
        "wrapper_pid": os.getpid(),
        "wrapper_ppid": os.getppid(),
        "wrapper_starttime_ticks": (
            process_identity(os.getpid())[2]
            if Path("/proc/self/stat").exists()
            else None
        ),
        "wrapper_path": str(wrapper_path),
        "atomic_primitive": "exclusive_mkdir",
        "claim_retained_on_every_outcome": True,
        "retry_allowed": False,
    }
    write_create_only(owner, canonical_bytes(payload))
    os.chmod(claim, 0o500)
    return payload


def assert_retained_outputs_absent() -> None:
    existing = [str(path) for path in RETAINED_OUTPUTS if path.exists()]
    if existing:
        raise ContractError(f"retained evidence predates fresh claim: {existing}")


def validate_authorization(
    authorization: Mapping[str, Any], wrapper_raw: bytes, wrapper_path: Path
) -> None:
    if type(authorization) is not dict:
        raise ContractError("authorization must be an exact object")
    expected_keys = set(AUTHORIZATION_BINDING) | {"execution_wrapper"}
    if set(authorization) != expected_keys:
        raise ContractError("authorization keys rejected")
    without_wrapper = dict(authorization)
    wrapper = without_wrapper.pop("execution_wrapper")
    if not recursive_type_exact_equal(without_wrapper, AUTHORIZATION_BINDING):
        raise ContractError("authorization binding rejected")
    expected_wrapper = {
        "path": "scripts/run_agh_v18_canonical_probe.py",
        "wsl_path": WRAPPER_WSL,
        "size_bytes": len(wrapper_raw),
        "sha256": digest(wrapper_raw),
    }
    if (
        not recursive_type_exact_equal(wrapper, expected_wrapper)
        or wrapper_path != WRAPPER
    ):
        raise ContractError("execution wrapper identity rejected")


def recursive_type_exact_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        if set(actual) != set(expected):
            return False
        return all(
            recursive_type_exact_equal(actual[key], expected[key]) for key in expected
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            recursive_type_exact_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def canonical_argv_digest(argv: Sequence[str]) -> str:
    if any(type(value) is not str or "\0" in value for value in argv):
        raise ContractError("canonical argv element rejected")
    return digest("\0".join(argv).encode("utf-8"))


def verify_frozen_chain() -> dict[str, bytes]:
    captures = {
        name: read_pinned(CHAIN / name, row, f"v18:{name}")
        for name, row in FROZEN_TREE.items()
    }
    freeze = pinned_json_bytes(
        captures["agent-aghfal17-native-v18-review-freeze.json"], "freeze"
    )
    invocations = pinned_json_bytes(
        captures["agent-aghfal17-native-v18-invocations.json"], "invocations"
    )
    outer = invocations["probe"]["argv"]
    inner = freeze["commands"]["probe"]["argv"]
    frozen = AUTHORIZATION_BINDING["frozen_probe"]
    if (
        len(outer) != frozen["outer_argv_count"]
        or canonical_argv_digest(outer) != frozen["outer_canonical_argv_sha256"]
        or canonical_argv_digest(outer) != invocations["probe"]["canonical_argv_sha256"]
        or len(inner) != frozen["inner_argv_count"]
        or canonical_argv_digest(inner) != frozen["inner_canonical_argv_sha256"]
        or canonical_argv_digest(inner)
        != freeze["commands"]["probe"]["canonical_argv_sha256"]
        or outer[-1] != "--sealed-import-probe"
        or inner[-1] != "--sealed-import-probe"
    ):
        raise ContractError("frozen probe argv rejected")
    official_path = freeze["official_input"]["path"]
    if (
        FORBIDDEN_ROUTE_TOKENS.intersection(outer)
        or FORBIDDEN_ROUTE_TOKENS.intersection(inner)
        or official_path in outer
        or official_path in inner
    ):
        raise ContractError("forbidden execution route in frozen probe argv")
    return captures


def verify_source_closure(freeze: Mapping[str, Any]) -> int:
    source_count = 0
    for relative, row in freeze["source_closure"].items():
        read_pinned(REPOSITORY / relative, row, f"source-closure:{relative}")
        source_count += 1
    return source_count


def verify_runtime_closure(freeze: Mapping[str, Any]) -> dict[str, int]:
    record_count = 0
    for label, row in freeze["runtime_records"].items():
        read_pinned(REPOSITORY / row["path"], row, f"runtime-record:{label}")
        record_count += 1
    for label in ("python", "bash"):
        row = freeze["runtime_pins"][label]
        read_pinned(Path(row["path"]), row, f"runtime-pin:{label}")
    return {
        "runtime_record_rows": record_count,
        "runtime_pin_rows": 2,
    }


def verify_frozen_dependency_closure(freeze: Mapping[str, Any]) -> dict[str, int]:
    runtime = verify_runtime_closure(freeze)
    return {
        "source_closure_rows": verify_source_closure(freeze),
        **runtime,
    }


def postflight_revalidate() -> dict[str, Any]:
    captures = verify_frozen_chain()
    freeze = pinned_json_bytes(
        captures["agent-aghfal17-native-v18-review-freeze.json"],
        "freeze-postflight",
    )
    closure = verify_frozen_dependency_closure(freeze)
    if not all(
        digest(raw) == FROZEN_TREE[name]["sha256"] for name, raw in captures.items()
    ):
        raise ContractError("frozen chain changed during execution")
    return {
        "pins_stable_after_execution": True,
        "dependency_closure_stable_after_execution": True,
        "runtime_records_stable_after_execution": True,
        "runtime_pins_stable_after_execution": True,
        "dependency_closure": closure,
    }


def mem_available_kib() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1])
    raise ContractError("MemAvailable unavailable")


def process_topology(pid: int) -> tuple[int, int, int, int, int]:
    raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    closing = raw.rfind(")")
    if closing < 1:
        raise ContractError("malformed process stat")
    tail = raw[closing + 2 :].split()
    if len(tail) < 20:
        raise ContractError("short process stat")
    return pid, int(tail[1]), int(tail[2]), int(tail[3]), int(tail[19])


def process_identity(pid: int) -> tuple[int, int, int]:
    current, parent, _group, _session, started = process_topology(pid)
    return current, parent, started


def current_ancestry() -> set[tuple[int, int]]:
    accepted: set[tuple[int, int]] = set()
    pid = os.getpid()
    while pid > 0:
        current, parent, started = process_identity(pid)
        if (current, started) in accepted:
            raise ContractError("process ancestry cycle")
        accepted.add((current, started))
        if parent == current:
            raise ContractError("self-parent process")
        pid = parent
    return accepted


INFRASTRUCTURE = {
    "/init",
    "/usr/lib/systemd/systemd",
    "/usr/lib/systemd/systemd-journald",
    "/usr/lib/systemd/systemd-udevd",
    "/usr/lib/systemd/systemd-resolved",
    "/usr/lib/systemd/systemd-networkd",
    "/usr/bin/dbus-daemon",
    "/usr/libexec/wsl-pro-service",
    "/usr/bin/wsl-pro-service",
}


def minimal_infrastructure(
    executable: str, cmdline: bytes, uids: set[int], gids: set[int]
) -> bool:
    if executable not in INFRASTRUCTURE or uids != {0} or gids != {0}:
        return False
    argv = [value for value in cmdline.split(b"\0") if value]
    if not argv:
        return False
    if executable == "/init":
        return argv[0] == b"/init"
    if executable == "/usr/lib/systemd/systemd":
        return argv[0] in {b"/sbin/init", b"/usr/lib/systemd/systemd"} and all(
            value in {b"--system", b"--user", b"--deserialize", b"--switched-root"}
            or value.isdigit()
            for value in argv[1:]
        )
    if executable == "/usr/bin/dbus-daemon":
        return argv[0] == b"/usr/bin/dbus-daemon" and b"--system" in argv[1:]
    return argv[0].decode("utf-8", "strict") == executable


def process_census() -> dict[str, Any]:
    ancestry = current_ancestry()
    rejected: list[dict[str, Any]] = []
    inspected = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            current, _parent, started = process_identity(pid)
            executable = os.readlink(entry / "exe")
            cmdline = (entry / "cmdline").read_bytes()
            status_text = (entry / "status").read_text(encoding="ascii")
            uid_line = next(
                line for line in status_text.splitlines() if line.startswith("Uid:")
            )
            gid_line = next(
                line for line in status_text.splitlines() if line.startswith("Gid:")
            )
            uids = {int(value) for value in uid_line.split()[1:]}
            gids = {int(value) for value in gid_line.split()[1:]}
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, StopIteration, ValueError) as exc:
            raise ContractError(f"process census uncertainty for pid {pid}") from exc
        inspected += 1
        if (current, started) in ancestry:
            continue
        if minimal_infrastructure(executable, cmdline, uids, gids):
            continue
        rejected.append(
            {
                "pid": current,
                "starttime_ticks": started,
                "executable": executable,
            }
        )
    return {
        "status": "PASS" if not rejected else "NO_GO",
        "inspected_count": inspected,
        "rejected_count": len(rejected),
        "rejected": rejected,
    }


def two_sample_resource_gate(
    sample: Callable[[], int] = mem_available_kib,
    census: Callable[[], dict[str, Any]] = process_census,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    floor = int(
        AUTHORIZATION_BINDING["frozen_limits"]["initial_memavailable_floor_kib"]
    )
    interval_required = float(
        AUTHORIZATION_BINDING["frozen_limits"]["initial_sample_interval_seconds"]
    )
    started = clock()
    first = {"index": 1, "mem_available_kib": sample(), "census": census()}
    sleeper(interval_required)
    ended = clock()
    second = {"index": 2, "mem_available_kib": sample(), "census": census()}
    observed = ended - started
    passed = (
        first["mem_available_kib"] >= floor
        and second["mem_available_kib"] >= floor
        and observed >= interval_required
        and first["census"]["status"] == "PASS"
        and second["census"]["status"] == "PASS"
        and first["census"]["rejected_count"] == 0
        and second["census"]["rejected_count"] == 0
    )
    return {
        "schema": "planora.agh-fal17.native-v18-two-sample-resource-gate.v1",
        "status": "PASS" if passed else "NO_GO",
        "floor_kib": floor,
        "required_interval_seconds": interval_required,
        "observed_interval_seconds": observed,
        "samples": [first, second],
    }


def _snapshot_identity(row: os.stat_result) -> dict[str, int]:
    return {
        "device": int(row.st_dev),
        "inode": int(row.st_ino),
        "size_bytes": int(row.st_size),
        "mode": stat.S_IMODE(row.st_mode),
        "links": int(row.st_nlink),
    }


def stage_private_snapshot(
    captures: Mapping[str, bytes], snapshot: Path | None = None
) -> dict[str, Any]:
    if snapshot is None:
        snapshot = SNAPSHOT_HOST
    if set(captures).intersection(STAGED_NAMES) != set(STAGED_NAMES):
        raise ContractError("captured staged closure is incomplete")
    os.mkdir(snapshot, 0o700)
    root_before = os.stat(snapshot, follow_symlinks=False)
    if not stat.S_ISDIR(root_before.st_mode):
        raise ContractError("snapshot root is not a directory")
    rows: dict[str, dict[str, Any]] = {}
    try:
        for name in STAGED_NAMES:
            raw = captures[name]
            pin = FROZEN_TREE[name]
            if len(raw) != pin["size_bytes"] or digest(raw) != pin["sha256"]:
                raise ContractError(f"captured snapshot bytes rejected: {name}")
            destination = snapshot / name
            write_create_only(destination, raw, 0o400)
            verified = read_pinned(destination, pin, f"snapshot:{name}")
            row = os.stat(destination, follow_symlinks=False)
            mode = stat.S_IMODE(row.st_mode)
            mode_rejected = (
                mode != 0o400 if os.name != "nt" else bool(mode & stat.S_IWUSR)
            )
            if verified != raw or mode_rejected:
                raise ContractError(f"snapshot replay rejected: {name}")
            rows[name] = {
                **_snapshot_identity(row),
                "sha256": digest(verified),
            }
        if {entry.name for entry in os.scandir(snapshot)} != set(STAGED_NAMES):
            raise ContractError("snapshot contains unexpected entries")
        os.chmod(snapshot, 0o500)
        root_after = os.stat(snapshot, follow_symlinks=False)
        root_mode = stat.S_IMODE(root_after.st_mode)
        root_mode_rejected = (
            root_mode != 0o500 if os.name != "nt" else bool(root_mode & stat.S_IWUSR)
        )
        if (root_before.st_dev, root_before.st_ino) != (
            root_after.st_dev,
            root_after.st_ino,
        ) or root_mode_rejected:
            raise ContractError("snapshot root identity or mode changed")
        return {
            "host_path": str(snapshot),
            "mount_path": str(SNAPSHOT_MOUNT),
            "root_device": int(root_after.st_dev),
            "root_inode": int(root_after.st_ino),
            "root_mode": root_mode,
            "files": rows,
        }
    except BaseException:
        cleanup_private_snapshot(
            {
                "host_path": str(snapshot),
                "root_device": int(root_before.st_dev),
                "root_inode": int(root_before.st_ino),
                "files": rows,
            },
            require_complete=False,
        )
        raise


def cleanup_private_snapshot(
    expected: Mapping[str, Any], *, require_complete: bool = True
) -> bool:
    snapshot = Path(expected["host_path"])
    if snapshot != SNAPSHOT_HOST and require_complete:
        raise ContractError("snapshot cleanup target rejected")
    root = os.stat(snapshot, follow_symlinks=False)
    if not stat.S_ISDIR(root.st_mode) or (int(root.st_dev), int(root.st_ino)) != (
        expected["root_device"],
        expected["root_inode"],
    ):
        raise ContractError("snapshot cleanup root identity changed")
    os.chmod(snapshot, 0o700)
    expected_files = expected["files"]
    names = {entry.name for entry in os.scandir(snapshot)}
    if require_complete and names != set(STAGED_NAMES):
        raise ContractError("snapshot cleanup closure changed")
    if require_complete and not names.issubset(expected_files):
        raise ContractError("snapshot cleanup found an unowned entry")
    for name in sorted(names):
        path = snapshot / name
        row = os.stat(path, follow_symlinks=False)
        pinned = expected_files.get(name)
        identity_rejected = pinned is not None and (
            int(row.st_dev),
            int(row.st_ino),
        ) != (pinned["device"], pinned["inode"])
        if (
            name not in STAGED_NAMES
            or not stat.S_ISREG(row.st_mode)
            or row.st_nlink != 1
            or identity_rejected
            or (require_complete and pinned is None)
        ):
            raise ContractError(f"snapshot cleanup identity changed: {name}")
        if os.name == "nt":
            os.chmod(path, 0o600)
        path.unlink()
    snapshot.rmdir()
    return not snapshot.exists()


def host_execution_argv(
    official_path: str,
    outer_argv: Sequence[str],
    snapshot: Path | None = None,
) -> list[str]:
    snapshot_argument: Path | PurePosixPath = (
        PurePosixPath(SNAPSHOT_HOST_WSL) if snapshot is None else snapshot
    )
    if (
        canonical_argv_digest(outer_argv)
        != AUTHORIZATION_BINDING["frozen_probe"]["outer_canonical_argv_sha256"]
    ):
        raise ContractError("outer execution argv rejected")
    if PurePosixPath(official_path).parent != PurePosixPath(OFFICIAL_PARENT_WSL):
        raise ContractError("official mask destination rejected")
    command = [
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5s",
        f"{PROBE_TIMEOUT_SECONDS}s",
        "/usr/bin/bwrap",
        "--unshare-all",
        "--new-session",
        "--die-with-parent",
        "--uid",
        "0",
        "--gid",
        "0",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--ro-bind",
        str(snapshot_argument),
        str(SNAPSHOT_MOUNT),
        "--ro-bind",
        SITE_PACKAGES_WSL,
        RUNTIME_ALIAS_WSL,
        "--tmpfs",
        "/mnt",
    ]
    for directory in MASKED_DRIVE_DIRECTORIES:
        command.extend(("--dir", directory))
    command.extend(
        [
            "--ro-bind",
            RUNTIME_ALIAS_WSL,
            SITE_PACKAGES_WSL,
            "--tmpfs",
            "/tmp",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
        ]
    )
    for name in STAGED_NAMES:
        command.extend(
            (
                "--ro-bind",
                str(SNAPSHOT_MOUNT / name),
                str(PurePosixPath("/tmp") / name),
            )
        )
    command.extend(
        [
            "--ro-bind",
            "/dev/null",
            official_path,
            "--chdir",
            str(SNAPSHOT_MOUNT),
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "LC_ALL",
            "C.UTF-8",
            "--setenv",
            "TZ",
            "UTC",
            "--",
        ]
    )
    command.extend(outer_argv)
    return command


def _stat_fields(pid: int) -> tuple[int, int] | None:
    try:
        _current, parent, _group, _session, started = process_topology(pid)
    except (FileNotFoundError, ProcessLookupError):
        return None
    return parent, started


def _descendant_tracking_snapshot(
    root_pid: int, root_started: int
) -> tuple[set[tuple[int, int]], set[int]]:
    rows: dict[int, tuple[int, int, int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            _current, parent, group, _session, started = process_topology(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
        rows[pid] = (parent, group, started)
    if rows.get(root_pid, (0, 0, -1))[2] != root_started:
        return set(), set()
    admitted = {(root_pid, root_started)}
    groups = {rows[root_pid][1]}
    changed = True
    while changed:
        changed = False
        parent_pids = {pid for pid, _started in admitted}
        for pid, (parent, group, started) in rows.items():
            if parent in parent_pids and (pid, started) not in admitted:
                admitted.add((pid, started))
                groups.add(group)
                changed = True
    return admitted, groups


def _descendants(root_pid: int, root_started: int) -> set[tuple[int, int]]:
    identities, _groups = _descendant_tracking_snapshot(root_pid, root_started)
    return identities


def _alive_identities(identities: set[tuple[int, int]]) -> list[dict[str, int]]:
    alive: list[dict[str, int]] = []
    for pid, expected_started in sorted(identities):
        fields = _stat_fields(pid)
        if fields is not None and fields[1] == expected_started:
            alive.append({"pid": pid, "starttime_ticks": expected_started})
    return alive


def _alive_tracking(identities: set[tuple[int, int]]) -> list[dict[str, int]]:
    alive: list[dict[str, int]] = []
    for pid, expected_started in sorted(identities):
        try:
            current, _parent, group, session, started = process_topology(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
        if started == expected_started:
            alive.append(
                {
                    "pid": current,
                    "starttime_ticks": started,
                    "process_group": group,
                    "session": session,
                }
            )
    return alive


def _usage_kib(identities: set[tuple[int, int]]) -> tuple[int, int]:
    rss = 0
    swap = 0
    for pid, started in identities:
        fields = _stat_fields(pid)
        if fields is None or fields[1] != started:
            continue
        try:
            lines = (
                (Path("/proc") / str(pid) / "status")
                .read_text(encoding="ascii")
                .splitlines()
            )
        except FileNotFoundError:
            continue
        for line in lines:
            if line.startswith("VmRSS:"):
                rss += int(line.split()[1])
            elif line.startswith("VmSwap:"):
                swap += int(line.split()[1])
    return rss, swap


def terminate_kill_wait(
    child: subprocess.Popen[bytes],
    process_group_id: int,
    tracked_identities: set[tuple[int, int]],
    tracked_process_groups: set[int],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "process_group_id": process_group_id,
        "term_attempted": False,
        "kill_attempted": False,
        "wait_attempted": False,
        "wait_completed": False,
        "exit_code": None,
        "tracked_identity_count": len(tracked_identities),
        "tracked_process_groups": sorted(tracked_process_groups),
        "remaining_after_kill": [],
        "cleanup_complete": False,
        "errors": [],
    }

    def observe(phase: str) -> list[dict[str, int]]:
        try:
            return _alive_tracking(tracked_identities)
        except BaseException as exc:
            evidence["errors"].append(f"{phase}_observe:{type(exc).__name__}")
            return []

    def signal_targets(
        phase: str,
        signum: int,
        groups: set[int],
        identities: list[dict[str, int]],
    ) -> None:
        for group in sorted(groups):
            try:
                os.killpg(group, signum)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                evidence["errors"].append(f"{phase}_group:{group}:{type(exc).__name__}")
        for identity in identities:
            try:
                current = _alive_tracking(
                    {(identity["pid"], identity["starttime_ticks"])}
                )
                if current:
                    os.kill(identity["pid"], signum)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                evidence["errors"].append(
                    f"{phase}_pid:{identity['pid']}:{type(exc).__name__}"
                )

    term_alive = observe("term")
    term_groups = {
        row["process_group"]
        for row in term_alive
        if row["process_group"] in tracked_process_groups
    }
    term_groups.add(process_group_id)
    evidence["term_attempted"] = True
    signal_targets("term", signal.SIGTERM, term_groups, term_alive)
    try:
        evidence["wait_attempted"] = True
        evidence["exit_code"] = child.wait(timeout=5)
        evidence["wait_completed"] = True
    except subprocess.TimeoutExpired:
        pass
    except BaseException as exc:
        evidence["errors"].append(f"term_wait:{type(exc).__name__}")

    kill_alive = observe("kill")
    kill_groups = {row["process_group"] for row in kill_alive}
    if not evidence["wait_completed"]:
        kill_groups.add(process_group_id)
    evidence["kill_attempted"] = True
    signal_targets("kill", getattr(signal, "SIGKILL", 9), kill_groups, kill_alive)
    try:
        evidence["wait_attempted"] = True
        evidence["exit_code"] = child.wait()
        evidence["wait_completed"] = True
    except BaseException as exc:
        evidence["errors"].append(f"kill_wait:{type(exc).__name__}")
    remaining = observe("final")
    evidence["remaining_after_kill"] = remaining
    evidence["cleanup_complete"] = (
        evidence["wait_completed"] is True and not remaining and not evidence["errors"]
    )
    return evidence


def run_with_watcher(argv: Sequence[str]) -> dict[str, Any]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    started = time.monotonic()
    timed_out = False
    known: set[tuple[int, int]] = set()
    tracked_process_groups: set[int] = set()
    peak_rss = 0
    peak_swap = 0
    child: subprocess.Popen[bytes] | None = None
    process_group_id: int | None = None
    cleanup_evidence: dict[str, Any] | None = None
    root_pid: int | None = None
    root_started: int | None = None
    try:
        with (
            STDOUT.open("xb", buffering=0) as stdout_stream,
            STDERR.open("xb", buffering=0) as stderr_stream,
        ):
            child = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                env=environment,
                start_new_session=True,
            )
            process_group_id = child.pid
            try:
                tracked_process_groups.add(process_group_id)
                root_pid, _parent, root_started = process_identity(child.pid)
                if root_pid != process_group_id:
                    raise ContractError("watcher process-group identity rejected")
                known.add((root_pid, root_started))
                while True:
                    descendants, groups = _descendant_tracking_snapshot(
                        root_pid, root_started
                    )
                    known.update(descendants)
                    tracked_process_groups.update(groups)
                    rss, swap = _usage_kib(known)
                    peak_rss = max(peak_rss, rss)
                    peak_swap = max(peak_swap, swap)
                    if child.poll() is not None:
                        break
                    if time.monotonic() - started >= WRAPPER_GUARD_SECONDS:
                        timed_out = True
                        break
                    time.sleep(0.1)
            finally:
                cleanup_evidence = terminate_kill_wait(
                    child,
                    process_group_id,
                    known,
                    tracked_process_groups,
                )
    finally:
        for stream_path in (STDOUT, STDERR):
            if stream_path.exists():
                os.chmod(stream_path, 0o400)
    if root_pid is None or root_started is None:
        raise ContractError("watcher root identity unavailable")
    if cleanup_evidence is None:
        raise ContractError("mandatory watcher cleanup evidence unavailable")
    exit_code = cleanup_evidence["exit_code"]
    postflight: list[dict[str, Any]] = []
    for index in range(POSTFLIGHT_ZERO_SNAPSHOTS):
        alive = _alive_identities(known)
        postflight.append(
            {
                "index": index + 1,
                "status": "ZERO" if not alive else "NONZERO",
                "alive": alive,
            }
        )
        if index + 1 < POSTFLIGHT_ZERO_SNAPSHOTS:
            time.sleep(POSTFLIGHT_INTERVAL_SECONDS)
    payload = {
        "schema": "planora.agh-fal17.native-v18-live-wrapper-watcher.v1",
        "run_id": RUN_ID,
        "status": (
            "PASS"
            if exit_code == 0
            and not timed_out
            and cleanup_evidence["cleanup_complete"] is True
            and all(row["status"] == "ZERO" for row in postflight)
            else "NO_GO"
        ),
        "child_pid": root_pid,
        "child_starttime_ticks": root_started,
        "child_exit_code": exit_code,
        "process_level_timeout_seconds": PROBE_TIMEOUT_SECONDS,
        "wrapper_guard_seconds": WRAPPER_GUARD_SECONDS,
        "wrapper_guard_triggered": timed_out,
        "live_until_child_exit": True,
        "live_through_postflight": True,
        "tracked_identity_count": len(known),
        "peak_process_tree_rss_kib": peak_rss,
        "peak_process_tree_vmswap_kib": peak_swap,
        "postflight_zero_snapshots": postflight,
        "mandatory_cleanup": cleanup_evidence,
    }
    write_create_only(WATCHER, canonical_bytes(payload))
    write_create_only(EXIT_CODE, f"{exit_code}\n".encode("ascii"))
    return payload


def exact_builtin_false(payload: object, key: str) -> bool:
    return (
        type(payload) is dict
        and key in payload
        and type(payload[key]) is bool
        and payload[key] is False
    )


def evaluate_result(
    outer: Mapping[str, Any],
    watcher: Mapping[str, Any],
    preflight: Mapping[str, Any],
    postflight: Mapping[str, Any],
) -> tuple[dict[str, bool], list[str]]:
    inner = outer.get("inner_payload") if type(outer) is dict else None
    child = inner.get("child_payload") if type(inner) is dict else None
    cleanup = outer.get("cleanup") if type(outer) is dict else None
    inner_cleanup = inner.get("process_group_cleanup") if type(inner) is dict else None
    checkpoint_key = "checkpoint_or_certified_provenance_used"
    final_snapshots = (
        cleanup.get("final_discovery_snapshots") if type(cleanup) is dict else None
    )
    wrapper_snapshots = watcher.get("postflight_zero_snapshots")
    mandatory_cleanup = watcher.get("mandatory_cleanup")
    predicates = {
        "preflight_pass": preflight.get("status") == "PASS",
        "outer_keys_exact": type(outer) is dict and set(outer) == OUTER_KEYS,
        "inner_keys_exact": type(inner) is dict and set(inner) == INNER_KEYS,
        "outer_schema_exact": outer.get("schema")
        == "planora.agh-fal17.native-v18-outer-controller.v1",
        "outer_status_pass": outer.get("status") == "PASS",
        "outer_probe_mode": outer.get("mode") == "probe",
        "outer_errors_empty": outer.get("errors") == [],
        "outer_breach_absent": outer.get("breach") is None,
        "inner_schema_exact": type(inner) is dict
        and inner.get("schema")
        == "planora.agh-fal17.native-v18-sealed-import-supervisor.v1",
        "inner_status_pass": type(inner) is dict and inner.get("status") == "PASS",
        "inner_errors_empty": type(inner) is dict and inner.get("errors") == [],
        "inner_breach_absent": type(inner) is dict and inner.get("breach") is None,
        "child_keys_exact": type(child) is dict and set(child) == CHILD_KEYS,
        "child_schema_exact": type(child) is dict
        and child.get("schema")
        == "planora.agh-fal17.native-v18-sealed-import-probe.v1",
        "child_status_pass": type(child) is dict and child.get("status") == "PASS",
        "checkpoint_pair_exact_false": exact_builtin_false(outer, checkpoint_key)
        and exact_builtin_false(inner, checkpoint_key),
        "official_input_false": exact_builtin_false(outer, "official_instance_opened")
        and exact_builtin_false(inner, "official_instance_opened")
        and exact_builtin_false(inner, "official_opened"),
        "solver_false": exact_builtin_false(outer, "solver_child_process_started")
        and exact_builtin_false(inner, "solver_child_process_started")
        and exact_builtin_false(inner, "solver_execution_started"),
        "publication_false": exact_builtin_false(outer, "publication")
        and exact_builtin_false(inner, "publication")
        and exact_builtin_false(inner, "official_solution_xml_published")
        and exact_builtin_false(child, "publication")
        and exact_builtin_false(child, "official_solution_xml_published"),
        "child_no_input_or_solver": exact_builtin_false(
            child, "official_instance_opened"
        )
        and exact_builtin_false(child, "official_opened")
        and exact_builtin_false(child, "solver_child_process_started")
        and exact_builtin_false(child, "solver_execution_started"),
        "outer_cleanup_empty": type(cleanup) is dict
        and cleanup.get("empty") is True
        and cleanup.get("errors") == []
        and outer.get("post_exit_empty") is True,
        "outer_two_zero_snapshots": type(final_snapshots) is list
        and len(final_snapshots) >= 2
        and all(
            type(row) is dict and row.get("status") == "ZERO"
            for row in final_snapshots[-2:]
        ),
        "inner_cleanup_empty": type(inner_cleanup) is dict
        and inner_cleanup.get("empty") is True
        and inner_cleanup.get("errors") == [],
        "watcher_pass": watcher.get("status") == "PASS"
        and watcher.get("child_exit_code") == 0
        and watcher.get("wrapper_guard_triggered") is False
        and watcher.get("live_until_child_exit") is True
        and watcher.get("live_through_postflight") is True,
        "watcher_mandatory_cleanup": type(mandatory_cleanup) is dict
        and mandatory_cleanup.get("term_attempted") is True
        and mandatory_cleanup.get("kill_attempted") is True
        and mandatory_cleanup.get("wait_attempted") is True
        and mandatory_cleanup.get("wait_completed") is True
        and mandatory_cleanup.get("remaining_after_kill") == []
        and mandatory_cleanup.get("cleanup_complete") is True,
        "watcher_two_zero_snapshots": type(wrapper_snapshots) is list
        and len(wrapper_snapshots) == POSTFLIGHT_ZERO_SNAPSHOTS
        and all(
            type(row) is dict and row.get("status") == "ZERO" and row.get("alive") == []
            for row in wrapper_snapshots
        ),
        "no_checkpoint_incumbent_competitor_routes": preflight.get(
            "forbidden_routes_present"
        )
        is False,
        "pins_stable_after_execution": postflight.get("pins_stable_after_execution")
        is True,
        "dependency_closure_stable_after_execution": postflight.get(
            "dependency_closure_stable_after_execution"
        )
        is True,
        "runtime_records_stable_after_execution": postflight.get(
            "runtime_records_stable_after_execution"
        )
        is True,
        "runtime_pins_stable_after_execution": postflight.get(
            "runtime_pins_stable_after_execution"
        )
        is True,
        "authorization_snapshot_stable": postflight.get("authorization_snapshot_stable")
        is True,
        "wrapper_pin_stable": postflight.get("wrapper_pin_stable") is True,
        "snapshot_cleanup_verified": postflight.get("snapshot_cleanup_verified")
        is True,
        "shared_lock_release_verified": postflight.get("shared_lock_release_verified")
        is True,
    }
    errors = [f"acceptance:{name}" for name, passed in predicates.items() if not passed]
    return predicates, errors


def acquire_heavy_lock() -> dict[str, Any]:
    os.mkdir(HEAVY_LOCK, 0o700)
    row = HEAVY_LOCK.stat(follow_symlinks=False)
    payload = {
        "schema": "planora.agh-fal17.native-v18-heavy-lock-owner.v1",
        "run_id": RUN_ID,
        "path": str(HEAVY_LOCK),
        "device": int(row.st_dev),
        "inode": int(row.st_ino),
        "owner_pid": os.getpid(),
        "held_through_child_exit_and_postflight": True,
    }
    write_create_only(HEAVY_LOCK_OWNER, canonical_bytes(payload))
    return payload


def release_heavy_lock(expected: Mapping[str, Any]) -> bool:
    row = HEAVY_LOCK.stat(follow_symlinks=False)
    if (int(row.st_dev), int(row.st_ino)) != (
        expected["device"],
        expected["inode"],
    ):
        raise ContractError("shared lock identity changed")
    os.rmdir(HEAVY_LOCK)
    return not HEAVY_LOCK.exists()


def evidence_row(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path), "size_bytes": len(raw), "sha256": digest(raw)}


def _main_impl(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(EXPLICIT_CONSUME_FLAG, action="store_true")
    args = parser.parse_args(argv)
    if not getattr(args, "consume_exactly_one_authorized_probe"):
        print(
            "NO_GO: explicit one-shot authorization consumption flag is required",
            file=sys.stderr,
        )
        return 64

    claim_owner: dict[str, Any]
    try:
        claim_owner = claim_once(CLAIM, CLAIM_OWNER, WRAPPER)
    except FileExistsError:
        print(f"NO_GO: run ID already consumed: {RUN_ID}", file=sys.stderr)
        return 73

    errors: list[str] = []
    preflight_payload: dict[str, Any] = {
        "schema": "planora.agh-fal17.native-v18-canonical-probe-preflight.v1",
        "run_id": RUN_ID,
        "status": "NO_GO",
        "claim": claim_owner,
        "forbidden_routes_present": False,
    }
    watcher_payload: dict[str, Any] = {}
    outer: dict[str, Any] = {}
    lock_owner: dict[str, Any] | None = None
    snapshot_owner: dict[str, Any] | None = None
    try:
        assert_retained_outputs_absent()
        authorization_raw = read_single_link(AUTHORIZATION, "authorization")
        authorization = exact_json_bytes(authorization_raw, "authorization")
        wrapper_row = authorization.get("execution_wrapper")
        if type(wrapper_row) is not dict:
            raise ContractError("authorization wrapper row missing")
        wrapper_raw = read_pinned(WRAPPER, wrapper_row, "execution-wrapper-self")
        validate_authorization(authorization, wrapper_raw, WRAPPER)
        captures = verify_frozen_chain()
        freeze = pinned_json_bytes(
            captures["agent-aghfal17-native-v18-review-freeze.json"], "freeze"
        )
        invocations_raw = captures["agent-aghfal17-native-v18-invocations.json"]
        invocations = pinned_json_bytes(invocations_raw, "invocations-captured")
        dependency_closure = verify_frozen_dependency_closure(freeze)
        official_path = str(freeze["official_input"]["path"])
        lock_owner = acquire_heavy_lock()
        resource_gate = two_sample_resource_gate()
        if resource_gate["status"] != "PASS":
            raise ContractError("two-sample resource gate rejected")
        snapshot_owner = stage_private_snapshot(captures)
        execution_argv = host_execution_argv(
            official_path, invocations["probe"]["argv"]
        )
        if any(token in execution_argv for token in FORBIDDEN_ROUTE_TOKENS):
            raise ContractError("forbidden host execution route")
        write_create_only(AUTHORIZATION_SNAPSHOT, authorization_raw)
        write_create_only(INVOCATIONS_SNAPSHOT, invocations_raw)
        preflight_payload.update(
            {
                "status": "PASS",
                "authorization": evidence_row(AUTHORIZATION),
                "execution_wrapper": evidence_row(WRAPPER),
                "freeze_manifest": evidence_row(
                    CHAIN / "agent-aghfal17-native-v18-review-freeze.json"
                ),
                "invocations": evidence_row(
                    CHAIN / "agent-aghfal17-native-v18-invocations.json"
                ),
                "resource_gate": resource_gate,
                "host_execution_argv": execution_argv,
                "host_execution_argv_sha256": canonical_argv_digest(execution_argv),
                "immutable_staged_closure": list(STAGED_NAMES),
                "private_snapshot": snapshot_owner,
                "dependency_closure": dependency_closure,
                "official_input_mask": {
                    "source": "/dev/null",
                    "destination": official_path,
                    "read_only": True,
                },
                "automatic_retry": False,
            }
        )
        write_create_only(PREFLIGHT, canonical_bytes(preflight_payload))
        watcher_payload = run_with_watcher(execution_argv)
        outer = exact_json_bytes(STDOUT.read_bytes(), "stdout")
    except Exception as exc:  # fail-closed receipt path
        errors.append(f"wrapper:{type(exc).__name__}")
    finally:
        if snapshot_owner is not None:
            try:
                preflight_payload["snapshot_cleanup_verified"] = (
                    cleanup_private_snapshot(snapshot_owner)
                )
            except Exception as exc:
                errors.append(f"snapshot_cleanup:{type(exc).__name__}")
        if lock_owner is not None:
            try:
                preflight_payload["shared_lock_release_verified"] = release_heavy_lock(
                    lock_owner
                )
            except Exception as exc:
                errors.append(f"lock_release:{type(exc).__name__}")

    postflight_payload: dict[str, Any] = {
        "schema": "planora.agh-fal17.native-v18-canonical-probe-postflight.v1",
        "run_id": RUN_ID,
        "status": "NO_GO",
        "pins_stable_after_execution": False,
        "dependency_closure_stable_after_execution": False,
        "runtime_records_stable_after_execution": False,
        "runtime_pins_stable_after_execution": False,
        "authorization_snapshot_stable": False,
        "wrapper_pin_stable": False,
        "snapshot_cleanup_verified": preflight_payload.get(
            "snapshot_cleanup_verified", False
        ),
        "shared_lock_release_verified": preflight_payload.get(
            "shared_lock_release_verified", False
        ),
    }
    try:
        postflight_payload.update(postflight_revalidate())
        postflight_payload["authorization_snapshot_stable"] = (
            AUTHORIZATION_SNAPSHOT.exists()
            and read_single_link(AUTHORIZATION, "authorization-postflight")
            == AUTHORIZATION_SNAPSHOT.read_bytes()
        )
        if AUTHORIZATION_SNAPSHOT.exists():
            authorization_after = exact_json_bytes(
                AUTHORIZATION_SNAPSHOT.read_bytes(), "authorization snapshot"
            )
            wrapper_row = authorization_after["execution_wrapper"]
            wrapper_after = read_pinned(WRAPPER, wrapper_row, "wrapper-postflight")
            postflight_payload["wrapper_pin_stable"] = (
                digest(wrapper_after) == wrapper_row["sha256"]
            )
        postflight_payload["status"] = (
            "PASS"
            if all(
                postflight_payload[key] is True
                for key in (
                    "pins_stable_after_execution",
                    "dependency_closure_stable_after_execution",
                    "runtime_records_stable_after_execution",
                    "runtime_pins_stable_after_execution",
                    "authorization_snapshot_stable",
                    "wrapper_pin_stable",
                    "snapshot_cleanup_verified",
                    "shared_lock_release_verified",
                )
            )
            else "NO_GO"
        )
    except Exception as exc:
        errors.append(f"postflight_pins:{type(exc).__name__}")

    try:
        write_create_only(POSTFLIGHT, canonical_bytes(postflight_payload))
    except Exception as exc:
        errors.append(f"postflight_receipt:{type(exc).__name__}")

    if not PREFLIGHT.exists():
        try:
            write_create_only(PREFLIGHT, canonical_bytes(preflight_payload))
        except Exception as exc:
            errors.append(f"preflight_receipt:{type(exc).__name__}")

    predicates, acceptance_errors = evaluate_result(
        outer, watcher_payload, preflight_payload, postflight_payload
    )
    errors.extend(acceptance_errors)
    evidence_paths = {
        "authorization": AUTHORIZATION,
        "wrapper": WRAPPER,
        "claim_owner": CLAIM_OWNER,
        "preflight": PREFLIGHT,
    }
    for label, path in (
        ("watcher", WATCHER),
        ("postflight", POSTFLIGHT),
        ("stdout", STDOUT),
        ("stderr", STDERR),
        ("exit_code", EXIT_CODE),
        ("authorization_snapshot", AUTHORIZATION_SNAPSHOT),
        ("invocations_snapshot", INVOCATIONS_SNAPSHOT),
        ("heavy_lock_owner", HEAVY_LOCK_OWNER),
    ):
        if path.exists():
            evidence_paths[label] = path
    checksum_payload = {
        "schema": "planora.agh-fal17.native-v18-canonical-probe-checksums.v1",
        "run_id": RUN_ID,
        "rows": {label: evidence_row(path) for label, path in evidence_paths.items()},
    }
    checksum_raw = canonical_bytes(checksum_payload)
    try:
        write_create_only(CHECKSUMS, checksum_raw)
    except Exception as exc:
        errors.append(f"checksums:{type(exc).__name__}")

    status = "PASS" if not errors and all(predicates.values()) else "NO_GO"
    result = {
        "schema": "planora.agh-fal17.native-v18-canonical-probe-result.v1",
        "run_id": RUN_ID,
        "status": status,
        "automatic_retry_authorized": False,
        "claim_marker_retained": CLAIM.is_dir(),
        "authorization_consumed": True,
        "acceptance_predicates": predicates,
        "errors": errors,
        "execution_boundaries": {
            "official_input": False if predicates.get("official_input_false") else None,
            "solver": False if predicates.get("solver_false") else None,
            "checkpoint_or_certified_incumbent": False
            if predicates.get("checkpoint_pair_exact_false")
            else None,
            "competitor": False
            if predicates.get("no_checkpoint_incumbent_competitor_routes")
            else None,
            "publication": False if predicates.get("publication_false") else None,
        },
        "child_exit_code": watcher_payload.get("child_exit_code"),
        "outer_status": outer.get("status"),
        "watcher": watcher_payload,
        "cleanup": outer.get("cleanup"),
        "checksums": {
            "path": str(CHECKSUMS),
            "size_bytes": len(checksum_raw),
            "sha256": digest(checksum_raw),
        },
    }
    write_create_only(RESULT_RECEIPT, canonical_bytes(result))
    return 0 if status == "PASS" else 2


def write_minimal_failure_receipt(failure_type: str) -> None:
    try:
        payload = {
            "schema": "planora.agh-fal17.native-v18-canonical-probe-result.v1",
            "run_id": RUN_ID,
            "status": "NO_GO",
            "authorization_consumed": True,
            "automatic_retry_authorized": False,
            "claim_marker_retained": CLAIM.is_dir(),
            "failure_type": failure_type,
            "minimal_post_claim_failure_receipt": True,
        }
        write_create_only(RESULT_RECEIPT, canonical_bytes(payload))
    except FileExistsError:
        validate_existing_failure_receipt()
    except BaseException:
        try:
            low_level_static_failure_receipt(RESULT_RECEIPT)
        except FileExistsError:
            validate_existing_failure_receipt()


def validate_existing_failure_receipt() -> None:
    raw = read_single_link(RESULT_RECEIPT, "existing-result-receipt")
    if raw == STATIC_FAILURE_RECEIPT:
        return
    payload = pinned_json_bytes(raw, "existing-result-receipt")
    if not (
        type(payload.get("authorization_consumed")) is bool
        and payload["authorization_consumed"] is True
        and type(payload.get("automatic_retry_authorized")) is bool
        and payload["automatic_retry_authorized"] is False
        and payload.get("run_id") == RUN_ID
        and payload.get("status") == "NO_GO"
    ):
        raise OSError("existing result receipt is not a durable NO_GO receipt")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main_impl(argv)
    except BaseException as exc:
        if CLAIM.is_dir():
            write_minimal_failure_receipt(type(exc).__name__)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
