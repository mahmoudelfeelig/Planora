#!/usr/bin/env python3
"""Official-input-only AGH-FAL17 native solve runner v10."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import base64
import csv
import ctypes
import errno
import fcntl
from hashlib import sha256
import importlib
from importlib import machinery as _importlib_machinery
from importlib import util as _importlib_util
import io
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import resource
import stat
import sys
import time
import types
from typing import Any, Mapping
import uuid


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
EXPECTED_CLASS_COUNT = 5_081
COOPERATIVE_DEADLINE_SECONDS = 1_680.0
RUNNER_RSS_CEILING_KIB = 384 * 1024
CAPTURE_MANIFEST_ENV = "AGHFAL_NATIVE_V10_CAPTURE_MANIFEST"
OUTPUT_BINDING_ENV = "AGHFAL_NATIVE_V10_OUTPUT_BINDING"
RUNTIME_BUNDLE_ENV = "AGHFAL_NATIVE_V10_RUNTIME_BUNDLE"
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
)
OUTPUT_XML = "solution.xml"
OUTPUT_REPORT = "completion-report.json"
RENAME_NOREPLACE = 1
LIBC = ctypes.CDLL(None, use_errno=True)

EXPECTED_HASHES = {
    "official_instance": "bae3363ed68e895280cd33bc20686bf396932f532c2b197f7b863f4167437528",
    "generic_validator": "5a64e57fb81d088e97dd6f471657b9a5599d31e9fbf014dce2b31f3fd0bf09b6",
    "stdlib_manifest": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "minimal_tcb_manifest": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "planora_benchmarks_init": "be6f5557e4565d1de24b4ced5a56a610fd935fc8320f1ffe5014255a59e3b84a",
    "planora_benchmarks_corpus": "74d23c0940713b8a40a9f789d4c0ece7402e5d9b81514587d3015d497d4112b3",
    "planora_itc2019": "5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f",
    "planora_itc2019_compact_joint": "427264334276fb48ce5b54c151a42d4a85b75055c0bea96f47a928b1fe28362a",
    "planora_itc2019_decomposed": "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63",
    "planora_itc2019_decomposed_quality": "534622d096728ff4e4e9b53fd8d58ec3827ec09540d4c95a3e3dcad271c7f78b",
    "planora_itc2019_factorized": "a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf",
    "planora_itc2019_generalized_occurrences": "7ed4224c0f338f9f983a358babb5dfdb6b90d5026383283cd0d805aef733d85f",
    "planora_itc2019_global_components": "c2d158dc9434f8da4f3e9478b1526face365702cf317fd14e693af75769e7f11",
    "planora_itc2019_global_quality": "397d308a4fb368aaab96db1789394e1b9f289a8f6b8d87b9ce5b4a569f8ccc7f",
    "planora_itc2019_grouped_calendar": "37b82b7f01fb47a655bb76ae0d6734315b00bf58ec7ebf28c66bb701c00a6ee5",
    "planora_itc2019_resource_seed": "8d497bc609ec5b717b0d9e2b77406e89c45c6eaef378148c0bebadd6a429d665",
    "planora_itc2019_sparse_joint": "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe",
    "planora_itc2019_structural": "db4ac0adbfe38f1b618b2e8f7a5a9e5a613000a62034017819cca2c20640d024",
    "planora_itc2019_violation_lns": "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b",
    "python_binary": "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273",
    "runtime_ortools_record": "4175009141f97e2dc7e4f453d67cb3fee6034f1f9df269e67a9b2abb3bd70a10",
    "runtime_numpy_record": "6cc44a275ff3c9b440a33271c7038b98622fd58fd68a2cabd931932a1741fb81",
    "runtime_pandas_record": "c65f6019e7d8089476318471d636a54a231254e1a9b009db093b9877fe12f0b6",
    "runtime_dateutil_record": "0c26b4b1542dbd1ebd8d2babdd501aed583d6ada9595517f936f00fe4ff9d254",
    "runtime_six_record": "d834e846ba51c0e7371968d0b5a0cdebdaa2f9ea2f0447a40b594fa96ca5d89f",
    "runtime_lxml_record": "aebff199cfc81d017be51e09b0c0fb1be49e5ddff0f7e777b3cc56b27f8cd07d",
    "runtime_absl_record": "526b41384f796af7d02a92ec84d1a8e7a2f3fd42880a349e91c96723f780a216",
    "runtime_immutabledict_record": "32fa24e0bd6e8481bd654ce6e020dcd9466d0d6b63e71c4588bbd25749257ec6",
    "runtime_protobuf_record": "6f8088dd0fb04edc0b64983a573b4d91c7374d1b0fc8546035cc6b2635aaec46",
    "runtime_typing_extensions_record": "02f70a4ed6f81c3298a0024ca9dcc6807360938d388360ce3b768243f719cdce",
}
PLANORA_MODULE_LABELS = {
    "benchmarks": "planora_benchmarks_init",
    "benchmarks.corpus": "planora_benchmarks_corpus",
    "benchmarks.itc2019": "planora_itc2019",
    "benchmarks.itc2019_compact_joint": "planora_itc2019_compact_joint",
    "benchmarks.itc2019_decomposed": "planora_itc2019_decomposed",
    "benchmarks.itc2019_decomposed_quality": "planora_itc2019_decomposed_quality",
    "benchmarks.itc2019_factorized": "planora_itc2019_factorized",
    "benchmarks.itc2019_generalized_occurrences": "planora_itc2019_generalized_occurrences",
    "benchmarks.itc2019_global_components": "planora_itc2019_global_components",
    "benchmarks.itc2019_global_quality": "planora_itc2019_global_quality",
    "benchmarks.itc2019_grouped_calendar": "planora_itc2019_grouped_calendar",
    "benchmarks.itc2019_resource_seed": "planora_itc2019_resource_seed",
    "benchmarks.itc2019_sparse_joint": "planora_itc2019_sparse_joint",
    "benchmarks.itc2019_structural": "planora_itc2019_structural",
    "benchmarks.itc2019_violation_lns": "planora_itc2019_violation_lns",
}
EXPECTED_CAPTURE_LABELS = frozenset({"runner", *EXPECTED_HASHES})
RUNTIME_RECORD_LABELS = {
    "ortools": "runtime_ortools_record",
    "numpy": "runtime_numpy_record",
    "pandas": "runtime_pandas_record",
    "dateutil": "runtime_dateutil_record",
    "six": "runtime_six_record",
    "lxml": "runtime_lxml_record",
    "absl": "runtime_absl_record",
    "immutabledict": "runtime_immutabledict_record",
    "google": "runtime_protobuf_record",
    "typing_extensions": "runtime_typing_extensions_record",
}
MAX_RUNTIME_BUNDLE_FILES = 6_000
MAX_RUNTIME_BUNDLE_BYTES = 512 << 20
MAX_RUNTIME_FILE_BYTES = 128 << 20
EXPECTED_RUNTIME_BUNDLE_FILES = 3_077
EXPECTED_RUNTIME_BUNDLE_BYTES = 191_956_270
EXPECTED_RUNTIME_EXCLUDED_ROWS = 2_098
EXPECTED_RUNTIME_RECORD_LABELS = frozenset(
    {
        "runtime_ortools_record",
        "runtime_numpy_record",
        "runtime_pandas_record",
        "runtime_dateutil_record",
        "runtime_six_record",
        "runtime_lxml_record",
        "runtime_absl_record",
        "runtime_immutabledict_record",
        "runtime_protobuf_record",
        "runtime_typing_extensions_record",
    }
)
PROBE_CAPTURE_LABELS = frozenset(
    {"runner", "python_binary", "stdlib_manifest", *EXPECTED_RUNTIME_RECORD_LABELS}
)
SYSTEM_PYTHON_STDLIB_ROOTS = (Path("/usr/lib/python3.12"),)
EXPECTED_STDLIB_FILE_COUNT = 619
EXPECTED_STDLIB_UID = 65534
EXPECTED_STDLIB_GID = 65534


def _stable_identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        int(row.st_dev),
        int(row.st_ino),
        int(row.st_size),
        stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode),
        int(row.st_uid),
        int(row.st_nlink),
    )


def _pread_all(descriptor: int, *, maximum_bytes: int) -> bytes:
    before = os.fstat(descriptor)
    if before.st_size < 0 or before.st_size > maximum_bytes:
        raise RuntimeError("captured descriptor size rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError("captured descriptor ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if _stable_identity(after) != _stable_identity(before):
        raise RuntimeError("captured descriptor identity changed while reading")
    return b"".join(chunks)


def verify_stdlib_manifest(
    payloads: Mapping[str, bytes], *, phase: str
) -> dict[str, Any]:
    raw = payloads.get("stdlib_manifest")
    if raw is None or sha256(raw).hexdigest() != EXPECTED_HASHES["stdlib_manifest"]:
        raise RuntimeError("sealed stdlib manifest missing or drifted")
    rows: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        digest, path = line.split("  ", 1)
        if (
            path in rows
            or len(digest) != 64
            or any(value not in "0123456789abcdef" for value in digest)
            or not path.startswith("/usr/lib/python3.12/")
            or os.path.realpath(path) != path
        ):
            raise RuntimeError("stdlib manifest row rejected")
        rows[path] = digest
    if len(rows) != EXPECTED_STDLIB_FILE_COUNT:
        raise RuntimeError("stdlib manifest cardinality drift")
    root_read_only = False
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split(" - ", 1)[0].split()
        if len(fields) >= 6 and fields[4] == "/" and "ro" in fields[5].split(","):
            root_read_only = True
    if not root_read_only:
        raise RuntimeError("stdlib filesystem is not read-only")
    verified_ancestors: set[str] = set()
    for path, expected in rows.items():
        current = path
        while current not in verified_ancestors:
            ownership = os.stat(current, follow_symlinks=False)
            if (
                ownership.st_uid != EXPECTED_STDLIB_UID
                or ownership.st_gid != EXPECTED_STDLIB_GID
                or stat.S_IMODE(ownership.st_mode) & 0o022
            ):
                raise RuntimeError("stdlib owner or writable ancestor rejected: " + current)
            verified_ancestors.add(current)
            if current == "/":
                break
            current = os.path.dirname(current)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            value = _pread_all(descriptor, maximum_bytes=32 << 20)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _stable_identity(before) != _stable_identity(after)
            or sha256(value).hexdigest() != expected
        ):
            raise RuntimeError("stdlib exact file admission rejected: " + path)
    loaded_paths: list[str] = []
    for module in tuple(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not isinstance(path, str) or path.startswith("<"):
            continue
        resolved = os.path.realpath(path)
        if resolved.startswith("/usr/lib/python3.12/"):
            if resolved != path or rows.get(resolved) is None:
                raise RuntimeError("loaded stdlib module outside exact manifest: " + path)
            loaded_paths.append(resolved)
    return {
        "phase": phase,
        "manifest_sha256": EXPECTED_HASHES["stdlib_manifest"],
        "file_count": len(rows),
        "loaded_module_file_count": len(set(loaded_paths)),
        "expected_uid": EXPECTED_STDLIB_UID,
        "expected_gid": EXPECTED_STDLIB_GID,
        "root_mount_read_only": True,
        "group_or_world_writable_file_or_ancestor_allowed": False,
        "exact_per_path_hashes_verified": True,
    }


def _capture_replay(
    label: str, evidence: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    if evidence.get("label") != label or evidence.get("transport") != "sealed_memfd":
        raise RuntimeError(f"capture {label} label/transport binding rejected")
    descriptor = evidence.get("fd")
    if type(descriptor) is not int or descriptor < 3:
        raise RuntimeError(f"capture {label} descriptor rejected")
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"capture {label} is not regular")
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    if seals & REQUIRED_SEALS != REQUIRED_SEALS:
        raise RuntimeError(f"capture {label} is not sealed")
    maximum = 128 << 20 if label == "official_instance" else 32 << 20
    payload = _pread_all(descriptor, maximum_bytes=maximum)
    digest = sha256(payload).hexdigest()
    expected = evidence.get("sha256")
    frozen = evidence.get("expected_sha256")
    if expected != digest or frozen != digest:
        raise RuntimeError(f"capture {label} digest mismatch")
    if label != "runner" and EXPECTED_HASHES.get(label) != digest:
        raise RuntimeError(f"capture {label} frozen pin mismatch")
    keys = ("device", "inode", "size", "file_type", "mode", "uid", "nlink")
    identity = _stable_identity(before)
    if tuple(evidence.get(key) for key in keys) != identity:
        raise RuntimeError(f"capture {label} identity binding mismatch")
    if evidence.get("seals") != seals or evidence.get("required_seals") != REQUIRED_SEALS:
        raise RuntimeError(f"capture {label} seal binding mismatch")
    return payload, {
        "label": label,
        "sha256": digest,
        "device": identity[0],
        "inode": identity[1],
        "size": identity[2],
        "file_type": identity[3],
        "mode": identity[4],
        "uid": identity[5],
        "nlink": identity[6],
        "seals": seals,
        "required_seals": REQUIRED_SEALS,
        "transport": "sealed_memfd",
    }


def _load_capture_manifest(
    expected_labels: frozenset[str],
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    raw = os.environ.get(CAPTURE_MANIFEST_ENV)
    if raw is None:
        raise RuntimeError("sealed capture manifest is missing")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or frozenset(manifest) != expected_labels:
        raise RuntimeError("sealed capture manifest labels rejected")
    descriptors: set[int] = set()
    for label, row in manifest.items():
        if not isinstance(label, str) or not isinstance(row, dict):
            raise RuntimeError("capture manifest entry rejected")
        descriptor = row.get("fd")
        if type(descriptor) is not int or descriptor in descriptors:
            raise RuntimeError("capture descriptor alias rejected")
        descriptors.add(descriptor)
    payloads: dict[str, bytes] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for label in sorted(manifest):
        row = manifest[label]
        payloads[label], evidence[label] = _capture_replay(label, row)
    executed = globals().get("__captured_sha256__")
    if executed != evidence["runner"]["sha256"]:
        raise RuntimeError("executed runner bytes differ from sealed runner capture")
    if globals().get("__runner_loader_protocol__") != "planora.aghfal17.native-v10-runner-loader.v1":
        raise RuntimeError("runner loader protocol rejected")
    return payloads, evidence


def load_capture_manifest() -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    return _load_capture_manifest(EXPECTED_CAPTURE_LABELS)


def load_probe_capture_manifest() -> tuple[
    dict[str, bytes], dict[str, dict[str, Any]]
]:
    return _load_capture_manifest(PROBE_CAPTURE_LABELS)


def _resource_guard(deadline: float, phase: str) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"cooperative deadline reached during {phase}")
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if peak >= RUNNER_RSS_CEILING_KIB:
        raise MemoryError(f"runner RSS ceiling reached during {phase}")


def _record_rows(raw: bytes) -> dict[str, tuple[str, int]]:
    rows: dict[str, tuple[str, int]] = {}
    for path, encoded, size in csv.reader(io.StringIO(raw.decode("utf-8"))):
        if not encoded.startswith("sha256=") or not size:
            continue
        digest = base64.urlsafe_b64decode(encoded.removeprefix("sha256=") + "==").hex()
        rows[path] = (digest, int(size))
    return rows


@dataclass(slots=True)
class RuntimeBundleAdmission:
    root_fd: int
    manifest_fd: int
    manifest_sha256: str
    entries_by_path: dict[str, dict[str, Any]]
    entries_by_identity: dict[tuple[int, int], dict[str, Any]]
    evidence: dict[str, Any]
    native_handles: list[Any] | None = None


def _expected_runtime_bundle_entries(
    payloads: Mapping[str, bytes],
) -> tuple[dict[str, tuple[str, int, str]], list[str]]:
    entries: dict[str, tuple[str, int, str]] = {}
    excluded: list[str] = []
    for label in sorted(RUNTIME_RECORD_LABELS.values()):
        for row in csv.reader(payloads[label].decode("utf-8").splitlines()):
            if len(row) != 3:
                raise RuntimeError(f"runtime RECORD row malformed: {label}")
            raw_path, encoded, raw_size = row
            relative = PurePosixPath(raw_path)
            if (
                not raw_path
                or relative.is_absolute()
                or ".." in relative.parts
                or "\\" in raw_path
                or relative.as_posix() != raw_path
                or not encoded.startswith("sha256=")
                or not raw_size
                or relative.suffix == ".pyc"
                or "__pycache__" in relative.parts
            ):
                excluded.append(f"{label}:{raw_path}")
                continue
            encoded_digest = encoded.removeprefix("sha256=")
            padding = "=" * (-len(encoded_digest) % 4)
            digest = base64.urlsafe_b64decode(encoded_digest + padding).hex()
            size = int(raw_size)
            if size < 0 or size > MAX_RUNTIME_FILE_BYTES:
                raise RuntimeError(f"runtime RECORD size rejected: {raw_path}")
            key = relative.as_posix()
            if key in entries:
                raise RuntimeError(f"duplicate runtime RECORD entry: {key}")
            entries[key] = (digest, size, label)
    if len(entries) > MAX_RUNTIME_BUNDLE_FILES:
        raise RuntimeError("runtime bundle file-count limit exceeded")
    if sum(row[1] for row in entries.values()) > MAX_RUNTIME_BUNDLE_BYTES:
        raise RuntimeError("runtime bundle byte limit exceeded")
    if (
        frozenset(RUNTIME_RECORD_LABELS.values()) != EXPECTED_RUNTIME_RECORD_LABELS
        or len(entries) != EXPECTED_RUNTIME_BUNDLE_FILES
        or sum(row[1] for row in entries.values())
        != EXPECTED_RUNTIME_BUNDLE_BYTES
        or len(excluded) != EXPECTED_RUNTIME_EXCLUDED_ROWS
    ):
        raise RuntimeError("frozen runtime bundle cardinality drift")
    return entries, sorted(excluded)


def verify_runtime_bundle(
    payloads: Mapping[str, bytes],
) -> RuntimeBundleAdmission:
    raw_binding = os.environ.get(RUNTIME_BUNDLE_ENV)
    if raw_binding is None:
        raise RuntimeError("sealed runtime bundle binding missing")
    binding = json.loads(raw_binding)
    if binding.get("protocol") != "planora.aghfal17.native-v10-sealed-runtime.v1":
        raise RuntimeError("sealed runtime bundle protocol rejected")
    root_fd = binding.get("root_fd")
    manifest_fd = binding.get("manifest_fd")
    if type(root_fd) is not int or type(manifest_fd) is not int:
        raise RuntimeError("sealed runtime bundle descriptors rejected")
    root_row = os.fstat(root_fd)
    root_identity = (
        int(root_row.st_dev),
        int(root_row.st_ino),
        stat.S_IMODE(root_row.st_mode),
        int(root_row.st_uid),
    )
    if (
        not stat.S_ISDIR(root_row.st_mode)
        or root_identity[2:] != (0o500, os.getuid())
        or tuple(binding.get("root_identity", ())) != root_identity
    ):
        raise RuntimeError("sealed runtime bundle root rejected")
    manifest_before = os.fstat(manifest_fd)
    manifest_seals = int(fcntl.fcntl(manifest_fd, fcntl.F_GET_SEALS))
    manifest_raw = _pread_all(manifest_fd, maximum_bytes=16 << 20)
    manifest_identity = _stable_identity(manifest_before)
    if (
        not stat.S_ISREG(manifest_before.st_mode)
        or manifest_seals & REQUIRED_SEALS != REQUIRED_SEALS
        or tuple(binding.get("manifest_identity", ())) != manifest_identity
        or binding.get("manifest_seals") != manifest_seals
        or binding.get("required_seals") != REQUIRED_SEALS
        or binding.get("manifest_size") != len(manifest_raw)
        or binding.get("manifest_sha256") != sha256(manifest_raw).hexdigest()
    ):
        raise RuntimeError("sealed runtime manifest binding rejected")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    expected, excluded = _expected_runtime_bundle_entries(payloads)
    rows = manifest.get("entries")
    if (
        manifest.get("schema")
        != "planora.aghfal17.native-v10-sealed-runtime.v1"
        or manifest.get("root_fd") != root_fd
        or tuple(manifest.get("root_identity", ())) != root_identity
        or manifest.get("excluded_record_rows") != excluded
        or manifest.get("pyc_entries_excluded") is not True
        or not isinstance(rows, list)
        or len(rows) != len(expected)
    ):
        raise RuntimeError("sealed runtime manifest contract rejected")
    entries_by_path: dict[str, dict[str, Any]] = {}
    entries_by_identity: dict[tuple[int, int], dict[str, Any]] = {}
    runtime_fds: set[int] = set()
    parent_paths: set[str] = set()
    required_keys = frozenset(
        {
            "relative_path",
            "record_label",
            "fd",
            "sha256",
            "size",
            "device",
            "inode",
            "file_type",
            "mode",
            "uid",
            "nlink",
            "seals",
            "required_seals",
            "source_identity",
        }
    )
    for row in rows:
        if not isinstance(row, dict) or frozenset(row) != required_keys:
            raise RuntimeError("sealed runtime manifest entry shape rejected")
        relative = row.get("relative_path")
        descriptor = row.get("fd")
        if (
            not isinstance(relative, str)
            or relative not in expected
            or relative in entries_by_path
            or type(descriptor) is not int
            or descriptor < 3
            or descriptor in runtime_fds
        ):
            raise RuntimeError("sealed runtime manifest entry rejected")
        expected_digest, expected_size, expected_label = expected[relative]
        before = os.fstat(descriptor)
        identity = _stable_identity(before)
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        raw = _pread_all(descriptor, maximum_bytes=MAX_RUNTIME_FILE_BYTES)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o400
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
            or row.get("record_label") != expected_label
            or row.get("sha256") != expected_digest
            or row.get("size") != expected_size
            or tuple(
                row.get(key)
                for key in (
                    "device",
                    "inode",
                    "size",
                    "file_type",
                    "mode",
                    "uid",
                    "nlink",
                )
            )
            != identity
            or row.get("seals") != seals
            or row.get("required_seals") != REQUIRED_SEALS
            or sha256(raw).hexdigest() != expected_digest
            or len(raw) != expected_size
        ):
            raise RuntimeError(f"sealed runtime entry mismatch: {relative}")
        link_row = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
        link_target = os.readlink(relative, dir_fd=root_fd)
        if (
            not stat.S_ISLNK(link_row.st_mode)
            or link_target != f"/proc/self/fd/{descriptor}"
        ):
            raise RuntimeError(f"sealed runtime link mismatch: {relative}")
        relative_parts = PurePosixPath(relative).parts
        for depth in range(1, len(relative_parts)):
            parent_paths.add(PurePosixPath(*relative_parts[:depth]).as_posix())
        runtime_fds.add(descriptor)
        entry = dict(row)
        entries_by_path[relative] = entry
        key = (identity[0], identity[1])
        if key in entries_by_identity:
            raise RuntimeError("sealed runtime descriptor identity reused")
        entries_by_identity[key] = entry
    if frozenset(entries_by_path) != frozenset(expected):
        raise RuntimeError("sealed runtime bundle completeness rejected")
    for relative in sorted(parent_paths):
        descriptor = os.open(
            relative,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            row = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o500
                or row.st_uid != os.getuid()
            ):
                raise RuntimeError("sealed runtime parent directory rejected")
        finally:
            os.close(descriptor)
    evidence = {
        "manifest_sha256": sha256(manifest_raw).hexdigest(),
        "manifest_size": len(manifest_raw),
        "file_count": len(entries_by_path),
        "total_bytes": sum(row[1] for row in expected.values()),
        "excluded_record_row_count": len(excluded),
        "root_identity": list(root_identity),
        "all_files_sealed_before_third_party_import": True,
        "pyc_entries_excluded": True,
        "transport": "read_only_symlink_tree_to_sealed_memfds",
    }
    return RuntimeBundleAdmission(
        root_fd,
        manifest_fd,
        evidence["manifest_sha256"],
        entries_by_path,
        entries_by_identity,
        evidence,
    )


class _SealedSourceLoader:
    def __init__(
        self,
        fullname: str,
        relative: str,
        entry: Mapping[str, Any],
        bundle: RuntimeBundleAdmission,
        package: bool,
    ) -> None:
        self.fullname = fullname
        self.relative = relative
        self.entry = entry
        self.bundle = bundle
        self.package = package

    def create_module(self, _spec: Any) -> None:
        return None

    def is_package(self, _fullname: str) -> bool:
        return self.package

    def get_filename(self, _fullname: str) -> str:
        return f"/proc/self/fd/{self.bundle.root_fd}/{self.relative}"

    def get_code(self, _fullname: str) -> Any:
        raw = _pread_all(
            int(self.entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES
        )
        if (
            len(raw) != self.entry["size"]
            or sha256(raw).hexdigest() != self.entry["sha256"]
        ):
            raise ImportError(f"sealed source drift: {self.relative}")
        return compile(
            raw,
            self.get_filename(self.fullname),
            "exec",
            dont_inherit=True,
        )

    def get_data(self, path: str) -> bytes:
        prefix = f"/proc/self/fd/{self.bundle.root_fd}/"
        if not path.startswith(prefix):
            raise OSError(errno.EPERM, "runtime data path outside sealed bundle")
        relative = PurePosixPath(path.removeprefix(prefix)).as_posix()
        entry = self.bundle.entries_by_path.get(relative)
        if entry is None:
            raise OSError(errno.ENOENT, "runtime data absent from sealed bundle")
        return _pread_all(int(entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES)

    def exec_module(self, module: types.ModuleType) -> None:
        module.__file__ = self.get_filename(self.fullname)
        module.__cached__ = None
        module.__sealed_runtime_sha256__ = self.entry["sha256"]
        if self.package:
            parent = PurePosixPath(self.relative).parent.as_posix()
            module.__path__ = [f"/proc/self/fd/{self.bundle.root_fd}/{parent}"]
        exec(self.get_code(self.fullname), module.__dict__)


class _SealedRuntimeFinder:
    def __init__(self, bundle: RuntimeBundleAdmission) -> None:
        self.bundle = bundle

    def find_spec(
        self, fullname: str, _path: Any = None, _target: Any = None
    ) -> Any:
        stem = fullname.replace(".", "/")
        package_relative = f"{stem}/__init__.py"
        module_relative = f"{stem}.py"
        if package_relative in self.bundle.entries_by_path:
            entry = self.bundle.entries_by_path[package_relative]
            loader = _SealedSourceLoader(
                fullname, package_relative, entry, self.bundle, True
            )
            return _importlib_util.spec_from_loader(
                fullname, loader, is_package=True
            )
        if module_relative in self.bundle.entries_by_path:
            entry = self.bundle.entries_by_path[module_relative]
            loader = _SealedSourceLoader(
                fullname, module_relative, entry, self.bundle, False
            )
            return _importlib_util.spec_from_loader(
                fullname, loader, is_package=False
            )
        for suffix in _importlib_machinery.EXTENSION_SUFFIXES:
            relative = stem + suffix
            entry = self.bundle.entries_by_path.get(relative)
            if entry is None:
                continue
            exact_path = f"/proc/self/fd/{entry['fd']}"
            loader = _importlib_machinery.ExtensionFileLoader(
                fullname, exact_path
            )
            return _importlib_util.spec_from_file_location(
                fullname, exact_path, loader=loader
            )
        prefix = stem + "/"
        if any(path.startswith(prefix) for path in self.bundle.entries_by_path):
            spec = _importlib_machinery.ModuleSpec(
                fullname, loader=None, is_package=True
            )
            spec.submodule_search_locations = [
                f"/proc/self/fd/{self.bundle.root_fd}/{stem}"
            ]
            return spec
        return None


def install_sealed_runtime(bundle: RuntimeBundleAdmission) -> dict[str, Any]:
    live_package_paths = [
        value
        for value in sys.path
        if isinstance(value, str)
        and ("site-packages" in value or "dist-packages" in value)
    ]
    if live_package_paths:
        raise RuntimeError("live package path present before sealed runtime install")
    native_dependencies = [
        row
        for relative, row in sorted(bundle.entries_by_path.items())
        if ".so" in PurePosixPath(relative).name
        and (
            PurePosixPath(relative).name.startswith("lib")
            or any(part.endswith(".libs") for part in PurePosixPath(relative).parts)
        )
    ]
    pending = list(native_dependencies)
    handles: list[Any] = []
    failures: dict[str, str] = {}
    while pending:
        progress = False
        following: list[dict[str, Any]] = []
        for row in pending:
            try:
                handle = ctypes.CDLL(
                    f"/proc/self/fd/{row['fd']}",
                    mode=os.RTLD_NOW | os.RTLD_GLOBAL,
                )
            except OSError as exc:
                failures[str(row["relative_path"])] = str(exc)
                following.append(row)
            else:
                handles.append(handle)
                failures.pop(str(row["relative_path"]), None)
                progress = True
        if not following:
            break
        if not progress:
            first = sorted(failures)[0]
            raise RuntimeError(
                f"sealed native dependency closure failed: {first}: "
                f"{failures[first]}"
            )
        pending = following
    bundle.native_handles = handles
    sys.meta_path.insert(0, _SealedRuntimeFinder(bundle))
    preloaded_paths = sorted(
        str(row["relative_path"]) for row in native_dependencies
    )
    return {
        "sealed_source_finder_installed": True,
        "native_dependency_memfds_preloaded": len(handles),
        "native_dependency_paths": preloaded_paths,
        "native_dependency_preload_failures": [],
        "live_site_packages_on_sys_path": False,
    }


def verify_executing_python(
    payloads: Mapping[str, bytes], capture_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    expected = capture_evidence["python_binary"]
    descriptor = os.open("/proc/self/exe", os.O_RDONLY)
    try:
        before = os.fstat(descriptor)
        raw = _pread_all(descriptor, maximum_bytes=32 << 20)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    expected_identity = tuple(
        expected[key]
        for key in (
            "device",
            "inode",
            "size",
            "file_type",
            "mode",
            "uid",
            "nlink",
        )
    )
    executable_row = os.stat(sys.executable)
    if (
        _stable_identity(before) != expected_identity
        or _stable_identity(after) != expected_identity
        or _stable_identity(executable_row) != expected_identity
        or raw != payloads["python_binary"]
        or sha256(raw).hexdigest() != EXPECTED_HASHES["python_binary"]
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
    ):
        raise RuntimeError("executing Python is not the admitted sealed descriptor")
    return {
        "sha256": sha256(raw).hexdigest(),
        "identity": list(expected_identity),
        "sys_executable": sys.executable,
        "proc_self_exe_bound": True,
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "dont_write_bytecode": bool(sys.dont_write_bytecode),
        "transport": "sealed_executable_memfd",
    }


def _admitted_system_python_module_path(raw_path: str) -> bool:
    path = Path(raw_path)
    return any(path.is_relative_to(root) for root in SYSTEM_PYTHON_STDLIB_ROOTS)


def mapped_runtime_snapshot(
    bundle: RuntimeBundleAdmission,
    capture_evidence: Mapping[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    sealed_identities = {
        (
            os.major(int(row["device"])),
            os.minor(int(row["device"])),
            int(row["inode"]),
        ): str(row["relative_path"])
        for row in bundle.entries_by_path.values()
    }
    python_row = capture_evidence["python_binary"]
    python_identity = (
        os.major(int(python_row["device"])),
        os.minor(int(python_row["device"])),
        int(python_row["inode"]),
    )
    sealed_mapped: set[str] = set()
    python_mapped = False
    system_paths: dict[str, tuple[int, int, int]] = {}
    unbound_memfds: set[str] = set()
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        fields = line.split(None, 5)
        if len(fields) < 5:
            continue
        major_raw, minor_raw = fields[3].split(":", 1)
        key = (int(major_raw, 16), int(minor_raw, 16), int(fields[4]))
        mapped_path = fields[5] if len(fields) == 6 else ""
        if key in sealed_identities:
            sealed_mapped.add(sealed_identities[key])
        elif key == python_identity:
            python_mapped = True
        elif mapped_path.startswith("/memfd:"):
            unbound_memfds.add(mapped_path)
        elif mapped_path.startswith("/") and not mapped_path.endswith(" (deleted)"):
            decoded_path = mapped_path.replace("\\040", " ")
            decoded_parts = Path(decoded_path).parts
            if (
                "site-packages" in decoded_parts
                or "dist-packages" in decoded_parts
            ):
                raise RuntimeError(
                    f"mapped live third-party runtime rejected: {decoded_path}"
                )
            if not decoded_path.startswith(("/usr/", "/lib/", "/lib64/")):
                raise RuntimeError(
                    f"mapped runtime outside admitted system roots: {decoded_path}"
                )
            previous_identity = system_paths.get(decoded_path)
            if previous_identity is not None and previous_identity != key:
                raise RuntimeError("mapped system path has multiple identities")
            system_paths[decoded_path] = key
        elif mapped_path.startswith("/"):
            raise RuntimeError(f"deleted mapped runtime rejected: {mapped_path}")
    if unbound_memfds or not python_mapped:
        raise RuntimeError("mapped memfd runtime identity was not admitted")
    system_rows: list[dict[str, Any]] = []
    for raw_path, mapped_identity in sorted(system_paths.items()):
        path = Path(raw_path)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            raw = _pread_all(descriptor, maximum_bytes=256 << 20)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        opened_map_identity = (
            os.major(int(after.st_dev)),
            os.minor(int(after.st_dev)),
            int(after.st_ino),
        )
        if (
            _stable_identity(before) != _stable_identity(after)
            or opened_map_identity != mapped_identity
        ):
            raise RuntimeError("mapped system runtime drift")
        system_rows.append(
            {
                "path": raw_path,
                "sha256": sha256(raw).hexdigest(),
                "size": len(raw),
                "identity": list(_stable_identity(after)),
            }
        )
    system_module_paths: set[str] = set()
    for module in tuple(sys.modules.values()):
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            continue
        if raw_path.startswith("/proc/self/fd/"):
            continue
        raw_parts = Path(raw_path).parts
        if "site-packages" in raw_parts or "dist-packages" in raw_parts:
            raise RuntimeError(
                f"live third-party Python module rejected: {raw_path}"
            )
        if not _admitted_system_python_module_path(raw_path):
            raise RuntimeError(
                f"Python module outside admitted stdlib roots: {raw_path}"
            )
        if raw_path.endswith((".pyc", ".pyo")):
            raise RuntimeError(f"system Python bytecode execution rejected: {raw_path}")
        system_module_paths.add(raw_path)
    system_module_rows: list[dict[str, Any]] = []
    for raw_path in sorted(system_module_paths):
        descriptor = os.open(
            raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            before = os.fstat(descriptor)
            raw = _pread_all(descriptor, maximum_bytes=64 << 20)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if _stable_identity(before) != _stable_identity(after):
            raise RuntimeError("system Python module drift")
        system_module_rows.append(
            {
                "path": raw_path,
                "sha256": sha256(raw).hexdigest(),
                "size": len(raw),
                "identity": list(_stable_identity(after)),
            }
        )
    return {
        "phase": phase,
        "sealed_package_mappings": sorted(sealed_mapped),
        "sealed_python_mapped": python_mapped,
        "system_runtime": system_rows,
        "system_python_modules": system_module_rows,
        "system_runtime_boundary": "observed_and_hashed_not_sealed",
    }


def compare_system_runtime_snapshots(
    start: Mapping[str, Any], end: Mapping[str, Any]
) -> dict[str, Any]:
    start_rows = {row["path"]: row for row in start["system_runtime"]}
    end_rows = {row["path"]: row for row in end["system_runtime"]}
    for path, row in start_rows.items():
        if end_rows.get(path) != row:
            raise RuntimeError(f"trusted system runtime changed: {path}")
    start_modules = {
        row["path"]: row for row in start["system_python_modules"]
    }
    end_modules = {row["path"]: row for row in end["system_python_modules"]}
    for path, row in start_modules.items():
        if end_modules.get(path) != row:
            raise RuntimeError(f"trusted system Python module changed: {path}")
    return {
        "start_file_count": len(start_rows),
        "end_file_count": len(end_rows),
        "start_subset_stable": True,
        "new_post_import_files": sorted(set(end_rows) - set(start_rows)),
        "start_python_module_count": len(start_modules),
        "end_python_module_count": len(end_modules),
        "new_post_import_python_modules": sorted(
            set(end_modules) - set(start_modules)
        ),
        "boundary": "trusted_system_runtime_observed_and_hashed_not_sealed",
    }


def verify_loaded_runtime(
    payloads: Mapping[str, bytes], bundle: RuntimeBundleAdmission
) -> dict[str, Any]:
    if not sys.dont_write_bytecode or not sys.pycache_prefix:
        raise RuntimeError("runtime pyc reads/writes were not disabled")
    records = {
        root: _record_rows(payloads[label])
        for root, label in RUNTIME_RECORD_LABELS.items()
    }
    loaded: list[dict[str, Any]] = []
    unexpected: set[str] = set()
    for module in tuple(sys.modules.values()):
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        if raw_path.startswith("<sealed-runtime:"):
            relative = raw_path.split(":", 2)[1]
            entry = bundle.entries_by_path.get(relative)
            if entry is None:
                unexpected.add(raw_path)
                continue
            loaded.append(
                {
                    "path": relative,
                    "sha256": entry["sha256"],
                    "size": entry["size"],
                    "transport": "sealed_descriptor_loader",
                }
            )
            continue
        path = Path(raw_path)
        if raw_path.startswith("/proc/self/fd/"):
            try:
                mapped = os.stat(raw_path)
            except OSError:
                unexpected.add(raw_path)
                continue
            entry = bundle.entries_by_identity.get(
                (int(mapped.st_dev), int(mapped.st_ino))
            )
            if entry is None:
                unexpected.add(raw_path)
                continue
            payload = _pread_all(
                int(entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES
            )
            observed = sha256(payload).hexdigest()
            if observed != entry["sha256"] or len(payload) != entry["size"]:
                raise RuntimeError(
                    f"sealed native runtime drift: {entry['relative_path']}"
                )
            loaded.append(
                {
                    "path": entry["relative_path"],
                    "sha256": observed,
                    "size": len(payload),
                    "transport": "sealed_native_descriptor",
                }
            )
            continue
        try:
            relative = path.absolute().relative_to(
                Path(f"/proc/self/fd/{bundle.root_fd}")
            ).as_posix()
        except (OSError, ValueError):
            if path.is_absolute() and not _admitted_system_python_module_path(
                raw_path
            ):
                unexpected.add(raw_path)
            continue
        root = relative.split("/", 1)[0].split(".", 1)[0]
        distribution_root = "dateutil" if root == "dateutil" else root
        if distribution_root not in records:
            unexpected.add(relative)
            continue
        if path.suffix == ".pyc":
            raise RuntimeError(f"runtime pyc execution rejected: {relative}")
        expected = records[distribution_root].get(relative)
        if expected is None:
            raise RuntimeError(f"runtime file absent from sealed RECORD: {relative}")
        entry = bundle.entries_by_path.get(relative)
        if entry is None:
            raise RuntimeError(f"runtime file absent from sealed bundle: {relative}")
        payload = _pread_all(int(entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES)
        observed = sha256(payload).hexdigest()
        if (observed, len(payload)) != expected:
            raise RuntimeError(f"runtime file RECORD mismatch: {relative}")
        loaded.append(
            {
                "path": relative,
                "sha256": observed,
                "size": len(payload),
                "transport": "sealed_native_descriptor",
            }
        )
    if unexpected:
        raise RuntimeError(
            "unexpected loaded module runtime: " + ",".join(sorted(unexpected))
        )
    loaded.sort(key=lambda row: row["path"])
    combined = sha256(
        json.dumps(loaded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "python_version": sys.version,
        "python_cache_tag": sys.implementation.cache_tag,
        "python_executable_realpath": os.path.realpath(sys.executable),
        "python_binary_sha256": EXPECTED_HASHES["python_binary"],
        "pyc_reads_disabled_by_private_prefix": bool(sys.pycache_prefix),
        "dont_write_bytecode": bool(sys.dont_write_bytecode),
        "sealed_record_hashes": {
            root: EXPECTED_HASHES[label]
            for root, label in RUNTIME_RECORD_LABELS.items()
        },
        "loaded_files": loaded,
        "loaded_file_count": len(loaded),
        "loaded_manifest_sha256": combined,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _output_binding() -> tuple[int, Path, tuple[int, int, int, int]]:
    raw = os.environ.get(OUTPUT_BINDING_ENV)
    if raw is None:
        raise RuntimeError("output directory binding missing")
    binding = json.loads(raw)
    descriptor = binding.get("fd")
    path_value = binding.get("path")
    if type(descriptor) is not int or descriptor < 3 or not isinstance(path_value, str):
        raise RuntimeError("output directory binding malformed")
    path = Path(path_value)
    row = os.fstat(descriptor)
    identity = (int(row.st_dev), int(row.st_ino), stat.S_IMODE(row.st_mode), int(row.st_uid))
    expected = tuple(binding.get(key) for key in ("device", "inode", "mode", "uid"))
    if identity != expected or not stat.S_ISDIR(row.st_mode) or identity[2:] != (0o700, os.getuid()):
        raise RuntimeError("output directory descriptor contract rejected")
    named = os.lstat(path)
    if (named.st_dev, named.st_ino, stat.S_IMODE(named.st_mode), named.st_uid) != identity:
        raise RuntimeError("output directory path binding rejected")
    return descriptor, path, identity


def _rename_noreplace(dirfd: int, source: str, destination: str) -> None:
    result = LIBC.renameat2(
        ctypes.c_int(dirfd),
        ctypes.c_char_p(os.fsencode(source)),
        ctypes.c_int(dirfd),
        ctypes.c_char_p(os.fsencode(destination)),
        ctypes.c_uint(RENAME_NOREPLACE),
    )
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), destination)


def _safe_unlink_identity(dirfd: int, name: str, identity: tuple[int, ...]) -> None:
    try:
        current = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if _stable_identity(current) == identity:
        os.unlink(name, dir_fd=dirfd)


def publish_bundle(payloads: Mapping[str, bytes]) -> dict[str, Any]:
    if not payloads or OUTPUT_REPORT not in payloads:
        raise RuntimeError("publication bundle must contain a report")
    order = tuple(name for name in (OUTPUT_XML, OUTPUT_REPORT) if name in payloads)
    if order[-1] != OUTPUT_REPORT or frozenset(payloads) != frozenset(order):
        raise RuntimeError("publication report must be last")
    dirfd, parent, parent_identity = _output_binding()
    pending: dict[str, tuple[str, int, tuple[int, ...]]] = {}
    admitted: dict[str, tuple[int, ...]] = {}
    try:
        for name in order:
            pending_name = f".{name}.pending-{uuid.uuid4().hex}"
            descriptor = os.open(
                pending_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o400,
                dir_fd=dirfd,
            )
            raw = payloads[name]
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise RuntimeError("pending output stopped accepting bytes")
                view = view[written:]
            os.fsync(descriptor)
            identity = _stable_identity(os.fstat(descriptor))
            pending[name] = (pending_name, descriptor, identity)
        for name in order:
            pending_name, descriptor, identity = pending[name]
            _rename_noreplace(dirfd, pending_name, name)
            admitted[name] = identity
            if _stable_identity(os.fstat(descriptor)) != identity:
                raise RuntimeError("committed output descriptor identity drift")
        os.fsync(dirfd)
        named_parent = os.lstat(parent)
        if (
            int(named_parent.st_dev),
            int(named_parent.st_ino),
            stat.S_IMODE(named_parent.st_mode),
            int(named_parent.st_uid),
        ) != parent_identity:
            raise RuntimeError("output parent final replay failed")
        result: dict[str, Any] = {}
        for name in order:
            _pending_name, descriptor, identity = pending[name]
            named = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
            exact = _pread_all(descriptor, maximum_bytes=256 << 20)
            if _stable_identity(named) != identity or exact != payloads[name]:
                raise RuntimeError("canonical output final replay failed")
            result[name] = {
                "sha256": sha256(exact).hexdigest(),
                "size": len(exact),
                "device": identity[0],
                "inode": identity[1],
                "publication_order": order.index(name) + 1,
            }
        return result
    except BaseException:
        for name, identity in admitted.items():
            _safe_unlink_identity(dirfd, name, identity)
        for name, (pending_name, _descriptor, _identity) in pending.items():
            if name not in admitted:
                try:
                    os.unlink(pending_name, dir_fd=dirfd)
                except FileNotFoundError:
                    pass
        raise
    finally:
        for _pending_name, descriptor, _identity in pending.values():
            os.close(descriptor)


class _SealedPlanoraLoader:
    def __init__(self, fullname: str, label: str, raw: bytes) -> None:
        self.fullname = fullname
        self.label = label
        self.raw = raw

    def create_module(self, _spec: Any) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        actual = sha256(self.raw).hexdigest()
        if actual != EXPECTED_HASHES[self.label]:
            raise RuntimeError(f"sealed Planora module drift: {self.fullname}")
        filename = f"<sealed-planora:{self.fullname}:{actual}>"
        module.__file__ = filename
        module.__cached__ = None
        module.__captured_sha256__ = actual
        if self.fullname == "benchmarks":
            module.__path__ = []
            module.__package__ = "benchmarks"
        exec(compile(self.raw, filename, "exec", dont_inherit=True), module.__dict__)


class _SealedPlanoraFinder:
    def __init__(self, payloads: Mapping[str, bytes]) -> None:
        self.payloads = payloads

    def find_spec(
        self, fullname: str, _path: Any = None, _target: Any = None
    ) -> Any:
        label = PLANORA_MODULE_LABELS.get(fullname)
        if label is None:
            return None
        loader = _SealedPlanoraLoader(fullname, label, self.payloads[label])
        return importlib.util.spec_from_loader(
            fullname, loader, is_package=fullname == "benchmarks"
        )


def install_sealed_planora_modules(payloads: Mapping[str, bytes]) -> dict[str, Any]:
    already_loaded = sorted(set(PLANORA_MODULE_LABELS) & set(sys.modules))
    if already_loaded:
        raise RuntimeError(
            "Planora modules loaded before sealed admission: " + ",".join(already_loaded)
        )
    sys.meta_path.insert(0, _SealedPlanoraFinder(payloads))
    return {
        "module_count": len(PLANORA_MODULE_LABELS),
        "module_hashes": {
            name: EXPECTED_HASHES[label]
            for name, label in sorted(PLANORA_MODULE_LABELS.items())
        },
        "transport": "sealed_capture_source_loader",
    }


def verify_loaded_planora_modules() -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, label in PLANORA_MODULE_LABELS.items():
        module = sys.modules.get(name)
        if module is None:
            continue
        expected = EXPECTED_HASHES[label]
        if (
            getattr(module, "__captured_sha256__", None) != expected
            or not str(getattr(module, "__file__", "")).startswith(
                f"<sealed-planora:{name}:"
            )
        ):
            raise RuntimeError(f"loaded Planora module provenance drift: {name}")
        rows[name] = expected
    if "benchmarks.itc2019" not in rows:
        raise RuntimeError("native Planora solver module was not loaded")
    return dict(sorted(rows.items()))


def _runtime_replay(
    *,
    runtime_bundle: RuntimeBundleAdmission,
    capture_evidence: Mapping[str, Any],
    runtime_install: Mapping[str, Any],
    system_runtime_start: Mapping[str, Any],
    system_runtime_after_import: Mapping[str, Any],
    phase: str,
) -> dict[str, Any]:
    replay_payloads, replay_captures = load_capture_manifest()
    final_bundle = verify_runtime_bundle(replay_payloads)
    final_loaded_runtime = verify_loaded_runtime(replay_payloads, runtime_bundle)
    final_maps = mapped_runtime_snapshot(
        runtime_bundle, capture_evidence, phase=phase
    )
    expected_native = set(runtime_install["native_dependency_paths"])
    mapped_native = set(final_maps["sealed_package_mappings"])
    if not expected_native.issubset(mapped_native):
        missing = sorted(expected_native - mapped_native)
        raise RuntimeError(
            "sealed native mapping disappeared before publication: " + missing[0]
        )
    return {
        "final_capture_replay": replay_captures,
        "final_runtime_bundle_replay": final_bundle.evidence,
        "final_loaded_runtime_replay": final_loaded_runtime,
        "final_system_runtime": final_maps,
        "final_system_runtime_comparison": compare_system_runtime_snapshots(
            system_runtime_start, final_maps
        ),
        "post_import_system_runtime_final_comparison": (
            compare_system_runtime_snapshots(system_runtime_after_import, final_maps)
        ),
    }


def execute_completion() -> tuple[int, dict[str, Any]]:
    started = time.monotonic()
    deadline = started + COOPERATIVE_DEADLINE_SECONDS
    payloads, capture_evidence = load_capture_manifest()
    stdlib_start = verify_stdlib_manifest(payloads, phase="before_native_import")
    executing_python = verify_executing_python(payloads, capture_evidence)
    runtime_bundle = verify_runtime_bundle(payloads)
    system_runtime_start = mapped_runtime_snapshot(
        runtime_bundle, capture_evidence, phase="before_third_party_import"
    )
    runtime_install = install_sealed_runtime(runtime_bundle)
    planora_install = install_sealed_planora_modules(payloads)
    native = importlib.import_module("benchmarks.itc2019")
    _resource_guard(deadline, "native module admission")
    runtime_evidence = verify_loaded_runtime(payloads, runtime_bundle)
    loaded_planora = verify_loaded_planora_modules()
    system_runtime_after_import = mapped_runtime_snapshot(
        runtime_bundle, capture_evidence, phase="after_third_party_import"
    )
    system_runtime_import_comparison = compare_system_runtime_snapshots(
        system_runtime_start, system_runtime_after_import
    )
    expected_native = set(runtime_install["native_dependency_paths"])
    mapped_native = set(system_runtime_after_import["sealed_package_mappings"])
    if not expected_native.issubset(mapped_native):
        missing = sorted(expected_native - mapped_native)
        raise RuntimeError(
            "sealed native dependency did not map from admitted inode: " + missing[0]
        )

    official_fd = int(capture_evidence["official_instance"]["fd"])
    problem = native.parse_itc2019_xml(Path(f"/proc/self/fd/{official_fd}"))
    class_ids = [klass.id for klass in problem.classes]
    if len(class_ids) != EXPECTED_CLASS_COUNT or len(set(class_ids)) != EXPECTED_CLASS_COUNT:
        raise RuntimeError("official problem class cardinality mismatch")
    actual_student_ids = {student.id for student in problem.students}
    if len(actual_student_ids) != len(problem.students):
        raise RuntimeError("official problem student IDs are not unique")
    _resource_guard(deadline, "official problem parse")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("cooperative deadline reached before native solve")
    result = native.solve_itc2019_native(
        problem,
        time_limit_seconds=remaining,
        workers=1,
        random_seed=0,
        formulation="auto",
    )
    if not result.is_feasible:
        final_runtime_evidence = _runtime_replay(
            runtime_bundle=runtime_bundle,
            capture_evidence=capture_evidence,
            runtime_install=runtime_install,
            system_runtime_start=system_runtime_start,
            system_runtime_after_import=system_runtime_after_import,
            phase="final_no_result",
        )
        return 2, {
            "schema": "planora.agh-fal17.native-v10-runner.v1",
            "status": "NO_RESULT",
            "native_status": result.status,
            "requested_formulation": "auto",
            "effective_formulation": result.effective_formulation,
            "executing_python": executing_python,
            "stdlib_start": stdlib_start,
            "stdlib_final": verify_stdlib_manifest(
                payloads, phase="final_no_result"
            ),
            "runtime_evidence": runtime_evidence,
            "sealed_runtime_bundle": runtime_bundle.evidence,
            "sealed_runtime_install": runtime_install,
            "system_runtime_start": system_runtime_start,
            "system_runtime_after_import": system_runtime_after_import,
            "system_runtime_import_comparison": system_runtime_import_comparison,
            **final_runtime_evidence,
            "official_instance_opened": True,
            "solver_execution_started": True,
            "native_validation_complete": False,
            "xml_published": False,
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
        }
    placement_ids = {placement.class_id for placement in result.placements}
    student_ids = set(result.student_classes)
    local_errors = list(
        native.validate_itc2019_solution(
            problem, result.placements, result.student_classes
        )
    )
    if (
        len(result.placements) != EXPECTED_CLASS_COUNT
        or placement_ids != set(class_ids)
        or len(result.student_classes) != len(actual_student_ids)
        or student_ids != actual_student_ids
        or local_errors
    ):
        raise RuntimeError("native result failed exact local cardinality/semantic gates")
    candidate = Path(os.environ["TMPDIR"]) / "native-v10-candidate.xml"
    native.write_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
        candidate,
        metadata={
            "source": "planora-native-v10",
            "formulation": "auto",
            "inputSha256": EXPECTED_HASHES["official_instance"],
        },
    )
    try:
        xml_bytes = candidate.read_bytes()
        parsed = native.parse_itc2019_solution(candidate)
        document_errors = native.validate_itc2019_solution_document(problem, parsed)
    finally:
        candidate.unlink(missing_ok=True)
    if document_errors:
        raise RuntimeError("serialized native result failed local document validation")
    final_runtime_evidence = _runtime_replay(
        runtime_bundle=runtime_bundle,
        capture_evidence=capture_evidence,
        runtime_install=runtime_install,
        system_runtime_start=system_runtime_start,
        system_runtime_after_import=system_runtime_after_import,
        phase="final_before_publication",
    )
    final_planora = verify_loaded_planora_modules()
    stdlib_final = verify_stdlib_manifest(
        payloads, phase="final_before_publication"
    )
    report = {
        "schema": "planora.agh-fal17.native-v10-report.v1",
        "status": "NATIVE_LOCAL_VALIDATION_PASSED_GENERIC_PENDING",
        "input_sha256": EXPECTED_HASHES["official_instance"],
        "classes": len(result.placements),
        "students": len(result.student_classes),
        "actual_problem_students": len(problem.students),
        "native_status": result.status,
        "requested_formulation": "auto",
        "effective_formulation": result.effective_formulation,
        "formulation_selection_reason": result.formulation_selection_reason,
        "objective": result.objective.to_dict() if result.objective else None,
        "local_validation_errors": local_errors,
        "local_document_validation_errors": list(document_errors),
        "isolated_generic_validation_required": True,
        "official_input_only": True,
        "checkpoint_or_certified_provenance_used": False,
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
        "executing_python": executing_python,
        "stdlib_start": stdlib_start,
        "stdlib_final": stdlib_final,
        "sealed_planora_install": planora_install,
        "loaded_planora_modules": loaded_planora,
        "final_loaded_planora_modules": final_planora,
        "runtime_evidence": runtime_evidence,
        "sealed_runtime_bundle": runtime_bundle.evidence,
        "sealed_runtime_install": runtime_install,
        "system_runtime_start": system_runtime_start,
        "system_runtime_after_import": system_runtime_after_import,
        "system_runtime_import_comparison": system_runtime_import_comparison,
        **final_runtime_evidence,
    }
    publication = publish_bundle(
        {OUTPUT_XML: xml_bytes, OUTPUT_REPORT: _json_bytes(report)}
    )
    return 0, {
        "schema": "planora.agh-fal17.native-v10-runner.v1",
        "status": "NATIVE_LOCAL_VALIDATED_GENERIC_PENDING",
        "native_status": result.status,
        "classes": len(result.placements),
        "students": len(result.student_classes),
        "publication": publication,
        "executing_python": executing_python,
        "stdlib_start": stdlib_start,
        "stdlib_final": stdlib_final,
        "runtime_evidence": runtime_evidence,
        "sealed_runtime_bundle": runtime_bundle.evidence,
        "sealed_runtime_install": runtime_install,
        "system_runtime_start": system_runtime_start,
        "system_runtime_after_import": system_runtime_after_import,
        "system_runtime_import_comparison": system_runtime_import_comparison,
        **final_runtime_evidence,
        "official_instance_opened": True,
        "solver_execution_started": True,
        "native_validation_complete": True,
        "generic_validation_complete": False,
        "xml_published": True,
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
        "elapsed_seconds": time.monotonic() - started,
    }


def self_test() -> dict[str, Any]:
    if OUTPUT_XML != "solution.xml" or OUTPUT_REPORT != "completion-report.json":
        raise AssertionError("report-last artifact contract drifted")
    if COOPERATIVE_DEADLINE_SECONDS != 1_680.0:
        raise AssertionError("cooperative deadline drifted")
    if RUNNER_RSS_CEILING_KIB != 384 * 1024:
        raise AssertionError("runner RSS ceiling drifted")
    if frozenset(RUNTIME_RECORD_LABELS.values()) != EXPECTED_RUNTIME_RECORD_LABELS:
        raise AssertionError("runtime RECORD closure drifted")
    forbidden = {
        "algorithm",
        "room_core",
        "validator",
        "matcher",
        "checkpoint",
        "certified_child",
        "certified_supervisor",
    }
    if forbidden & set(EXPECTED_HASHES):
        raise AssertionError("placement-bearing provenance label survived in v10")
    if len(PLANORA_MODULE_LABELS) != 15:
        raise AssertionError("Planora native module closure drifted")
    return {
        "status": "PASS",
        "expected_class_count": EXPECTED_CLASS_COUNT,
        "cooperative_deadline_seconds": COOPERATIVE_DEADLINE_SECONDS,
        "runner_rss_ceiling_kib": RUNNER_RSS_CEILING_KIB,
        "planora_native_module_count": len(PLANORA_MODULE_LABELS),
        "official_input_only_native_solver": True,
        "student_cardinality_source": "sealed_official_problem_students",
        "publication": "private_dirfd_transaction_report_last",
        "official_instance_opened": False,
        "solver_execution_started": False,
        "official_solution_xml_published": False,
    }


def sealed_import_probe() -> dict[str, Any]:
    payloads, captures = load_probe_capture_manifest()
    executing_python = verify_executing_python(payloads, captures)
    runtime_bundle = verify_runtime_bundle(payloads)
    start_maps = mapped_runtime_snapshot(
        runtime_bundle, captures, phase="probe_before_third_party_import"
    )
    runtime_install = install_sealed_runtime(runtime_bundle)
    module_names = (
        "ortools.sat.python.cp_model",
        "numpy",
        "pandas",
        "dateutil",
        "six",
        "lxml.etree",
        "absl",
        "immutabledict",
        "google.protobuf",
        "typing_extensions",
    )
    imported = [importlib.import_module(name).__name__ for name in module_names]
    loaded = verify_loaded_runtime(payloads, runtime_bundle)
    after_maps = mapped_runtime_snapshot(
        runtime_bundle, captures, phase="probe_after_third_party_import"
    )
    expected_native = set(runtime_install["native_dependency_paths"])
    if not expected_native.issubset(set(after_maps["sealed_package_mappings"])):
        raise RuntimeError("probe native mappings are not fully descriptor-bound")
    replay_payloads, replay_captures = load_probe_capture_manifest()
    replay_bundle = verify_runtime_bundle(replay_payloads)
    final_loaded = verify_loaded_runtime(replay_payloads, runtime_bundle)
    final_maps = mapped_runtime_snapshot(
        runtime_bundle, captures, phase="probe_final"
    )
    if not expected_native.issubset(set(final_maps["sealed_package_mappings"])):
        raise RuntimeError("probe native mapping disappeared before final replay")
    return {
        "schema": "planora.agh-fal17.native-v10-sealed-import-probe.v1",
        "status": "PASS",
        "imported_modules": imported,
        "executing_python": executing_python,
        "runtime_install": runtime_install,
        "loaded_runtime": loaded,
        "system_runtime_start": start_maps,
        "system_runtime_after_import": after_maps,
        "system_runtime_import_comparison": compare_system_runtime_snapshots(
            start_maps, after_maps
        ),
        "final_capture_replay": replay_captures,
        "final_runtime_bundle_replay": replay_bundle.evidence,
        "final_loaded_runtime_replay": final_loaded,
        "final_system_runtime": final_maps,
        "final_system_runtime_comparison": compare_system_runtime_snapshots(
            after_maps, final_maps
        ),
        "probe_child_process_started": True,
        "solver_child_process_started": False,
        "official_opened": False,
        "publication": False,
        "official_instance_opened": False,
        "solver_execution_started": False,
        "official_solution_xml_published": False,
    }


def main() -> int:
    if not isinstance(globals().get("__captured_sha256__"), str):
        raise SystemExit("direct AGH-FAL17 native v10 runner execution rejected")
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--execute-completion", action="store_true")
    modes.add_argument("--sealed-import-probe", action="store_true")
    parser.add_argument("--allow-official-input", action="store_true")
    parser.add_argument("--allow-solver", action="store_true")
    parser.add_argument("--allow-publication", action="store_true")
    args = parser.parse_args()
    permissions = (
        args.allow_official_input,
        args.allow_solver,
        args.allow_publication,
    )
    if args.sealed_import_probe:
        if any(permissions):
            raise SystemExit("sealed import probe rejects official allow flags")
        exit_code = 0
        result = sealed_import_probe()
    else:
        if permissions != (True, True, True):
            raise SystemExit("all irreversible AGH-FAL17 native gates are required")
        try:
            exit_code, result = execute_completion()
        except (TimeoutError, MemoryError) as exc:
            exit_code = 2
            result = {
                "schema": "planora.agh-fal17.native-v10-runner.v1",
                "status": "NO_RESULT",
                "phase": "bounded_runtime_guard",
                "reason": str(exc),
                "elapsed_seconds": 0.0,
                "cooperative_deadline_seconds": COOPERATIVE_DEADLINE_SECONDS,
                "official_instance_opened": True,
                "solver_execution_started": True,
                "native_validation_complete": False,
                "xml_published": False,
                "competitor_schedule_or_result_used": False,
                "competitor_placement_or_hint_used": False,
            }
    result["runner_sha256_start"] = globals()["__captured_sha256__"]
    result["runner_sha256_end"] = globals()["__captured_sha256__"]
    result["runner_hash_stable"] = True
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
