#!/usr/bin/env python3
"""Emit canonical AGH v18 successor freeze or invocation JSON.

This Windows-safe builder performs retained no-follow, single-link,
identity-bound reads. It never launches WSL, the probe, a child, or a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "benchmarks/probe_diagnostics/agh_v18"
OLD_FREEZE = CHAIN / "agent-aghfal17-native-v18-review-freeze.json"
OLD_INVOCATIONS = CHAIN / "agent-aghfal17-native-v18-invocations.json"
PREDECESSOR_RECEIPT = ROOT / (
    "output/diagnostic-receipts/agh-fal17-v18-canonical-probe-"
    "441fc45c4497c945b5e897dae57834d3.result-receipt.json"
)

RUN_ID = "5b9fc547835ff866f1f52811a467d213"
CREATED = "2026-08-27T08:24:08Z"
FREEZE_NAME = (
    "agent-aghfal17-native-v18-successor-review-freeze-20260827T082408Z-5b9fc547.json"
)
INVOCATIONS_NAME = (
    "agent-aghfal17-native-v18-successor-invocations-20260827T082408Z-5b9fc547.json"
)
AUTHORIZATION_NAME = (
    "agent-aghfal17-native-v18-probe-authorization-20260827T082408Z-5b9fc547.json"
)
WRAPPER = ROOT / "scripts/run_agh_v18_canonical_probe_5b9fc547.py"
OLD_FREEZE_SHA256 = "261f01c01e1931ff8db1e51d4c1774df06e1b79448880ea9ab59b24fd67c99c8"
OLD_INVOCATIONS_SHA256 = (
    "a72fe1d867a05cdf49f8ea5c45af60f80573d5a6fc94a7359df93369939a29d7"
)
PREDECESSOR_RECEIPT_SHA256 = (
    "a835fb830fba949a30ad3a369082013ee366ea74c3d34255278649cabeb64b3d"
)
OLD_SOURCE_SHA256 = "a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf"
NEW_SOURCE_SHA256 = "959be9e028773492538c4a541892955d37c5cdeb02cfaa762d8b9ce3fff48f02"
OLD_LAUNCHER_PATH = "/tmp/agent-aghfal17-native-v18-launcher.sh"
NEW_LAUNCHER_PATH = "/tmp/agent-aghfal17-native-v18-launcher-5b9fc547.sh"
OLD_LAUNCHER_SHA256 = "8ddb40f336a92d8b3c78cf6b1cb611dd5fc2ff1b691dad9f9b743a321e1e7aeb"
RUNNER_SHA256 = "4fccaaae750a26475214d888bd6a67c0efeec781309590886f8b42e3002bb752"
SUPERVISOR_SHA256 = "df6604025812858768b9e334729419afb99b096b0b6274d5bd9eace6a36d7481"
NEW_LAUNCHER_SHA256 = "7527f8542ea1d37143b39ac3923db3ef8e29800d4c3d012b84d506f6de204ea2"

ALLOCATION_ARTIFACTS = {
    "outer-controller-sealed": "outer_controller",
    "minimal-tcb-loader-sealed": "minimal_tcb_manifest",
    "bootstrap-source-sealed": "bootstrap",
    "launcher-source-sealed": "launcher",
    "runner-capture-sealed": "runner",
    "stdlib-manifest-capture-sealed": "stdlib_manifest",
    "generic-validator-capture-sealed": "generic_validator",
    "minimal-tcb-supervisor-capture-sealed": "minimal_tcb_manifest",
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def argv_digest(argv: list[str]) -> str:
    if any(type(value) is not str or "\0" in value for value in argv):
        raise RuntimeError("canonical argv rejected")
    return digest("\0".join(argv).encode("utf-8"))


def identity(row: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(row.st_dev),
        int(row.st_ino),
        int(row.st_size),
        stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode),
        int(row.st_nlink),
    )


def capture(path: Path, expected_sha256: str | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError(f"capture rejected: {path}")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            if hasattr(os, "pread"):
                block = os.pread(
                    descriptor, min(1 << 20, before.st_size - offset), offset
                )
            else:
                os.lseek(descriptor, offset, os.SEEK_SET)
                block = os.read(descriptor, min(1 << 20, before.st_size - offset))
            if not block:
                raise RuntimeError(f"capture ended early: {path}")
            chunks.append(block)
            offset += len(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if identity(before) != identity(after) or identity(after) != identity(named):
        raise RuntimeError(f"capture identity drift: {path}")
    if expected_sha256 is not None and digest(raw) != expected_sha256:
        raise RuntimeError(f"capture digest drift: {path}")
    return raw


def captured_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    value = json.loads(capture(path, expected_sha256))
    if type(value) is not dict:
        raise RuntimeError(f"captured JSON object rejected: {path}")
    return value


def replace_exact(argv: list[str], old: str, new: str, count: int) -> list[str]:
    if argv.count(old) != count:
        raise RuntimeError(f"predecessor argv binding count rejected: {old}")
    return [new if value == old else value for value in argv]


def _bound_allocation(
    allocation: dict[str, Any], freeze: dict[str, Any], freeze_size: int
) -> dict[str, Any]:
    allocation_id = allocation["allocation_id"]
    if allocation_id == "freeze-manifest-sealed":
        return {
            "allocation_id": allocation_id,
            "binding_key": "canonical_probe_successor.freeze_manifest",
            "binding_table": "self",
            "sha256_bound_externally": True,
            "size_bytes": freeze_size,
            "source": f"/tmp/{FREEZE_NAME}",
        }
    artifact_label = ALLOCATION_ARTIFACTS.get(allocation_id)
    if artifact_label is not None:
        row = freeze["artifacts"][artifact_label]
        return {
            "allocation_id": allocation_id,
            "binding_key": artifact_label,
            "binding_table": "artifacts",
            **row,
            "source": row["path"],
        }
    if allocation_id == "bash-binary-sealed":
        row = freeze["runtime_pins"]["bash"]
        return {
            "allocation_id": allocation_id,
            "binding_key": "bash",
            "binding_table": "runtime_pins",
            **row,
            "source": row["path"],
        }
    if allocation_id == "python-binary-capture-sealed":
        row = freeze["runtime_pins"]["python"]
        return {
            "allocation_id": allocation_id,
            "binding_key": "python",
            "binding_table": "runtime_pins",
            **row,
            "source": row["path"],
        }
    if allocation_id == "runtime-bundle-sealed-files":
        return {
            "allocation_id": allocation_id,
            "binding_key": "runtime_bundle_bytes",
            "binding_table": "runtime_pins",
            "derived_aggregate": True,
            "size_bytes": freeze["runtime_pins"]["runtime_bundle_bytes"],
            "source": "frozen-runtime-record-closure",
        }
    if allocation_id == "official-input-capture-sealed":
        row = freeze["official_input"]
        return {
            "allocation_id": allocation_id,
            "binding_key": "official_input",
            "binding_table": "official_input",
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "source": row["path"],
        }

    source = allocation["source"]
    for key, row in freeze["runtime_records"].items():
        if source == row["path"] or allocation_id == f"{key}-capture-sealed":
            return {
                "allocation_id": allocation_id,
                "binding_key": key,
                "binding_table": "runtime_records",
                **row,
                "source": row["path"],
            }
    if source in freeze["source_closure"]:
        row = freeze["source_closure"][source]
        return {
            "allocation_id": allocation_id,
            "binding_key": source,
            "binding_table": "source_closure",
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "source": source,
        }
    raise RuntimeError(f"unbound sealed allocation rejected: {allocation_id}")


def refresh_sealed_storage_contract(freeze: dict[str, Any], freeze_size: int) -> None:
    contract = freeze["sealed_storage_contract"]
    for mode in ("launch", "probe"):
        mode_contract = contract[mode]
        allocations = [
            _bound_allocation(row, freeze, freeze_size)
            for row in mode_contract["allocations"]
        ]
        mode_contract["allocations"] = allocations
        reserved_bytes = sum(row["size_bytes"] for row in allocations)
        mode_contract["derived_reserved_bytes"] = reserved_bytes
        mode_contract["derived_reserved_kib_ceiling"] = (reserved_bytes + 1023) // 1024
    contract["cross_table_binding"] = {
        "all_nonaggregate_nonself_rows_bind_exact_path_size_sha256": True,
        "freeze_manifest_self_size_is_canonical_fixed_point": True,
        "freeze_manifest_sha256_is_bound_by_invocations": True,
        "runtime_bundle_is_derived_from_runtime_pins": True,
        "stale_predecessor_rows_rejected": True,
    }


def build_freeze() -> dict[str, Any]:
    freeze = captured_json(OLD_FREEZE, OLD_FREEZE_SHA256)
    predecessor_raw = capture(PREDECESSOR_RECEIPT, PREDECESSOR_RECEIPT_SHA256)
    predecessor = json.loads(predecessor_raw)
    if (
        type(predecessor) is not dict
        or predecessor.get("status") != "NO_GO"
        or predecessor.get("child_exit_code") is not None
        or predecessor.get("authorization_consumed") is not True
    ):
        raise RuntimeError("predecessor receipt semantics rejected")

    for label, row in freeze["artifacts"].items():
        predecessor_path = CHAIN / PurePosixPath(row["path"]).name
        raw = capture(predecessor_path, row["sha256"])
        if len(raw) != row["size_bytes"]:
            raise RuntimeError(f"predecessor artifact size drift: {label}")

    for relative, row in freeze["source_closure"].items():
        raw = capture(ROOT / relative)
        row["size_bytes"] = len(raw)
        row["sha256"] = digest(raw)

    for row in freeze["runtime_records"].values():
        raw = capture(ROOT / row["path"])
        row["size_bytes"] = len(raw)
        row["sha256"] = digest(raw)

    successor_artifacts = {
        "runner": (
            "agent-aghfal17-native-v18-runner-5b9fc547.py",
            RUNNER_SHA256,
        ),
        "supervisor": (
            "agent-aghfal17-native-v18-supervisor-5b9fc547.py",
            SUPERVISOR_SHA256,
        ),
        "launcher": (
            "agent-aghfal17-native-v18-launcher-5b9fc547.sh",
            NEW_LAUNCHER_SHA256,
        ),
    }
    for label, (name, expected_sha256) in successor_artifacts.items():
        raw = capture(CHAIN / name, expected_sha256)
        freeze["artifacts"][label] = {
            "path": f"/tmp/{name}",
            "size_bytes": len(raw),
            "sha256": digest(raw),
        }

    for mode in ("probe", "launch"):
        command = freeze["commands"][mode]["argv"]
        command = replace_exact(command, OLD_LAUNCHER_PATH, NEW_LAUNCHER_PATH, 1)
        command = replace_exact(command, OLD_LAUNCHER_SHA256, NEW_LAUNCHER_SHA256, 1)
        freeze["commands"][mode]["argv"] = command
        freeze["commands"][mode]["canonical_argv_sha256"] = argv_digest(command)

    freeze["created_utc"] = CREATED
    freeze["status"] = "READY_FOR_FRESH_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_EXECUTION"
    freeze["scope"] = (
        "AGH-FAL17 v18 canonical-probe successor with the complete Planora "
        "source and dependency-record closure refreshed from retained live "
        "bytes; no WSL, probe, resource gate, official input, solver, or child "
        "execution used"
    )
    verification = freeze["verification"]
    verification["live_workspace_source_closure_replay"] = (
        "ALL_16_ROWS_REFRESHED_FROM_NO_FOLLOW_SINGLE_LINK_IDENTITY_BOUND_LIVE_CAPTURES"
    )
    verification["live_dependency_record_closure_replay"] = (
        "ALL_10_ROWS_REFRESHED_FROM_NO_FOLLOW_SINGLE_LINK_IDENTITY_BOUND_LIVE_CAPTURES"
    )
    verification["probe_run_authorized"] = False
    verification["official_launch_authorized"] = False
    verification["official_input_opened"] = False
    verification["solver_started"] = False
    freeze["canonical_probe_successor"] = {
        "run_id": RUN_ID,
        "created_at_utc": CREATED,
        "decision": "FRESH_STATIC_REVIEW_REQUIRED_EXECUTION_NO_GO",
        "predecessor_run_id": "441fc45c4497c945b5e897dae57834d3",
        "predecessor_result_receipt": {
            "path": (
                "output/diagnostic-receipts/agh-fal17-v18-canonical-probe-"
                "441fc45c4497c945b5e897dae57834d3.result-receipt.json"
            ),
            "size_bytes": len(predecessor_raw),
            "sha256": PREDECESSOR_RECEIPT_SHA256,
            "status": "NO_GO",
            "child_exit_code": None,
            "authorization_consumed": True,
        },
        "predecessor_failure": {
            "boundary": "verify_frozen_dependency_closure",
            "failed_before": [
                "resource_gate",
                "snapshot",
                "official_input",
                "solver",
                "child_process",
            ],
            "relative_path": "benchmarks/itc2019_factorized.py",
            "frozen_expected": {
                "size_bytes": 97255,
                "sha256": OLD_SOURCE_SHA256,
            },
            "reviewed_live": {
                "size_bytes": freeze["source_closure"][
                    "benchmarks/itc2019_factorized.py"
                ]["size_bytes"],
                "sha256": freeze["source_closure"]["benchmarks/itc2019_factorized.py"][
                    "sha256"
                ],
            },
        },
        "refresh_contract": {
            "source_closure_rows_recomputed": len(freeze["source_closure"]),
            "dependency_record_rows_recomputed": len(freeze["runtime_records"]),
            "captured_bytes_only": True,
            "no_follow": True,
            "single_link_required": True,
            "identity_checked_before_after_and_by_name": True,
            "recursive_ordinal_key_sorted_compact_utf8_lf": True,
        },
        "derived_code_contract": {
            "runner_exact_predecessor_transform": [
                "replace_planora_itc2019_factorized_sha256"
            ],
            "supervisor_exact_predecessor_transform": [
                "replace_successor_runner_path",
                "replace_successor_runner_sha256",
                "replace_planora_itc2019_factorized_sha256",
            ],
            "launcher_exact_predecessor_transform": [
                "replace_successor_supervisor_path",
                "replace_successor_supervisor_sha256",
            ],
            "validated_solver_semantics_changed": False,
            "probe_mode_changed": False,
            "checkpoint_or_incumbent_routes_added": False,
        },
        "execution_authorized": False,
    }
    freeze_size = 0
    for _ in range(16):
        refresh_sealed_storage_contract(freeze, freeze_size)
        candidate_size = len(canonical_bytes(freeze))
        if candidate_size == freeze_size:
            break
        freeze_size = candidate_size
    else:
        raise RuntimeError("canonical freeze self-size fixed point rejected")
    return freeze


def build_invocations(freeze_raw: bytes) -> dict[str, Any]:
    invocations = captured_json(OLD_INVOCATIONS, OLD_INVOCATIONS_SHA256)
    freeze_hash = digest(freeze_raw)
    old_freeze_path = "/tmp/agent-aghfal17-native-v18-review-freeze.json"
    new_freeze_path = f"/tmp/{FREEZE_NAME}"
    for mode in ("probe", "launch"):
        argv = invocations[mode]["argv"]
        argv = replace_exact(argv, old_freeze_path, new_freeze_path, 1)
        argv = replace_exact(argv, OLD_FREEZE_SHA256, freeze_hash, 2)
        argv = replace_exact(argv, OLD_LAUNCHER_PATH, NEW_LAUNCHER_PATH, 1)
        argv = replace_exact(argv, OLD_LAUNCHER_SHA256, NEW_LAUNCHER_SHA256, 1)
        invocations[mode]["argv"] = argv
        invocations[mode]["canonical_argv_sha256"] = argv_digest(argv)
    invocations["freeze_manifest"] = {
        "path": new_freeze_path,
        "sha256": freeze_hash,
    }
    invocations["canonical_probe_successor"] = {
        "run_id": RUN_ID,
        "created_at_utc": CREATED,
        "predecessor_invocations_sha256": OLD_INVOCATIONS_SHA256,
        "predecessor_freeze_sha256": OLD_FREEZE_SHA256,
        "source_closure_refreshed": True,
        "execution_authorized": False,
    }
    return invocations


def build_authorization() -> dict[str, Any]:
    wrapper_raw = capture(WRAPPER)
    spec = importlib.util.spec_from_file_location(
        "agh_v18_probe_successor_authorization_source", WRAPPER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("wrapper import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    authorization = dict(module.AUTHORIZATION_BINDING)
    authorization["execution_wrapper"] = {
        "path": "scripts/run_agh_v18_canonical_probe_5b9fc547.py",
        "wsl_path": module.WRAPPER_WSL,
        "size_bytes": len(wrapper_raw),
        "sha256": digest(wrapper_raw),
    }
    return authorization


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", choices=("freeze", "invocations", "authorization"))
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the selected artifact to its fixed successor path",
    )
    args = parser.parse_args()
    if args.artifact == "authorization":
        raw = canonical_bytes(build_authorization())
    else:
        freeze_raw = canonical_bytes(build_freeze())
        raw = (
            freeze_raw
            if args.artifact == "freeze"
            else canonical_bytes(build_invocations(freeze_raw))
        )
    if args.write:
        targets = {
            "freeze": CHAIN / FREEZE_NAME,
            "invocations": CHAIN / INVOCATIONS_NAME,
            "authorization": CHAIN / AUTHORIZATION_NAME,
        }
        targets[args.artifact].write_bytes(raw)
    else:
        sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
