#!/usr/bin/env python3
"""Frozen source-only MUNI-FSPSX v17 frontier diagnostic runner.

This entrypoint is inert without the supervisor launch bindings.  It performs
a fresh Planora-only solve from the sealed official input, never reads resume
progress or component checkpoints, and requires local semantic/document plus
fresh isolated generic validation before final XML/report publication.
"""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
from dataclasses import asdict
from dataclasses import dataclass
import errno
import fcntl
from hashlib import sha256
import importlib
import importlib.abc
import importlib.util
import io
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import resource
import secrets
import signal
import stat
import subprocess
import sys
import time
import types
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree


EXPECTED_INSTANCE_SHA256 = (
    "151664dfc27f377e5048cf0bf8ad48fac350c46a7db6ca7181fed6d1933960b6"
)
EXPECTED_PROGRESS_SHA256 = (
    "5cf7e3450ff96d79b3a5dbac1baa784a585b777397603d379a91513ada35cedf"
)
EXPECTED_OPEN_CLASSES = 152
EXPECTED_FIXED_CLASSES = 1471
EXPECTED_PLACEMENTS = 1623
EXPECTED_STUDENTS = 1152
GROUP_TIME_ROW_CAP = 2_000_000
PAIR_PLACEMENT_CELL_CAP = 30_000_000
FINALIZATION_RESERVE_SECONDS = 25.0
ALL_SEALS = 0x0F
REQUIRED_SEALS = ALL_SEALS
SEALED_RUNNER_EVIDENCE = globals().get("__planora_runner_evidence__")
SEALED_STDLIB_EVIDENCE = globals().get("__planora_stdlib_evidence__")
SEALED_SOURCE_EVIDENCE = globals().get("__planora_source_evidence__")
CAPTURE_MANIFEST_ENV = "MUNI_FSPSX_FRONTIER_V10_CAPTURE_MANIFEST"
RUNTIME_BUNDLE_ENV = "MUNI_FSPSX_FRONTIER_V10_RUNTIME_BUNDLE"
RUNNER_LOADER_PROTOCOL = "planora.muni-fspsx.frontier-v17-runner-loader.v1"
MAX_RUNTIME_BUNDLE_FILES = 6_000
MAX_RUNTIME_BUNDLE_BYTES = 512 << 20
MAX_RUNTIME_FILE_BYTES = 128 << 20
RUNNER_RSS_CEILING_KIB = 700_000
GENERIC_REPORT_POST_CHILD_TEST_HOOK = None
STDLIB_ROOTS = (Path("/usr/lib/python3.12").resolve(),)
STDLIB_EXPECTED_UID = 65534
STDLIB_EXPECTED_GID = 65534
MAX_STDLIB_MODULE_BYTES = 32 << 20
EXPECTED_HASHES = {
    "instance": EXPECTED_INSTANCE_SHA256,
    "fairness_certificate": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
    "benchmarks": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "semantic": "5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f",
    "preprocessing": "b98b6d56bcbdedaf491ac91194c9eef8997f624ab81c7f52e3a647c174994644",
    "frontier": "ade6b42c3baa08a53454db3842b0c4f3cd2e2738c6eb0c54108f419a148d7793",
    "room_oracle": "ff16e0a6045bffa7402748c537213c727918afddd35d92513ba4133972753ca6",
    "itc2019_compact_joint": "427264334276fb48ce5b54c151a42d4a85b75055c0bea96f47a928b1fe28362a",
    "itc2019_corpus": "1c83f9f26362d0c8c06d1d9bcabc2b015ac4e09216fdd91df1eaa7255933c621",
    "itc2019_decomposed": "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63",
    "itc2019_decomposed_quality": "534622d096728ff4e4e9b53fd8d58ec3827ec09540d4c95a3e3dcad271c7f78b",
    "itc2019_factorized": "a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf",
    "itc2019_generalized_occurrences": "7ed4224c0f338f9f983a358babb5dfdb6b90d5026383283cd0d805aef733d85f",
    "itc2019_global_components": "c2d158dc9434f8da4f3e9478b1526face365702cf317fd14e693af75769e7f11",
    "itc2019_global_quality": "397d308a4fb368aaab96db1789394e1b9f289a8f6b8d87b9ce5b4a569f8ccc7f",
    "itc2019_grouped_calendar": "37b82b7f01fb47a655bb76ae0d6734315b00bf58ec7ebf28c66bb701c00a6ee5",
    "itc2019_resource_seed": "8d497bc609ec5b717b0d9e2b77406e89c45c6eaef378148c0bebadd6a429d665",
    "itc2019_sparse_joint": "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe",
    "itc2019_structural": "db4ac0adbfe38f1b618b2e8f7a5a9e5a613000a62034017819cca2c20640d024",
    "itc2019_violation_lns": "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b",
    "generic_validator": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "python_binary": "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273",
    "stdlib_manifest": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "runtime_ortools_record": "4175009141f97e2dc7e4f453d67cb3fee6034f1f9df269e67a9b2abb3bd70a10",
    "runtime_numpy_record": "6cc44a275ff3c9b440a33271c7038b98622fd58fd68a2cabd931932a1741fb81",
    "runtime_pandas_record": "c65f6019e7d8089476318471d636a54a231254e1a9b009db093b9877fe12f0b6",
    "runtime_dateutil_record": "0c26b4b1542dbd1ebd8d2babdd501aed583d6ada9595517f936f00fe4ff9d254",
    "runtime_six_record": "d834e846ba51c0e7371968d0b5a0cdebdaa2f9ea2f0447a40b594fa96ca5d89f",
    "runtime_absl_record": "526b41384f796af7d02a92ec84d1a8e7a2f3fd42880a349e91c96723f780a216",
    "runtime_immutabledict_record": "32fa24e0bd6e8481bd654ce6e020dcd9466d0d6b63e71c4588bbd25749257ec6",
    "runtime_protobuf_record": "6f8088dd0fb04edc0b64983a573b4d91c7374d1b0fc8546035cc6b2635aaec46",
    "runtime_typing_extensions_record": "02f70a4ed6f81c3298a0024ca9dcc6807360938d388360ce3b768243f719cdce",
}
RUNTIME_RECORD_LABELS = {
    "ortools": "runtime_ortools_record",
    "numpy": "runtime_numpy_record",
    "pandas": "runtime_pandas_record",
    "dateutil": "runtime_dateutil_record",
    "six": "runtime_six_record",
    "absl": "runtime_absl_record",
    "immutabledict": "runtime_immutabledict_record",
    "google": "runtime_protobuf_record",
    "typing_extensions": "runtime_typing_extensions_record",
}
EXPECTED_CAPTURE_LABELS = frozenset({"runner", *EXPECTED_HASHES})
PROBE_CAPTURE_LABELS = EXPECTED_CAPTURE_LABELS - {"instance"}
SEALED_SOURCE_MODULE_LABELS = {
    "benchmarks": "benchmarks",
    "benchmarks.itc2019": "semantic",
    "benchmarks.itc2019_preprocessing": "preprocessing",
    "benchmarks.itc2019_frontier_joint": "frontier",
    "benchmarks.itc2019_room_oracle": "room_oracle",
    **{
        f"benchmarks.{name}": name
        for name in (
            "itc2019_compact_joint",
            "itc2019_corpus",
            "itc2019_decomposed",
            "itc2019_decomposed_quality",
            "itc2019_factorized",
            "itc2019_generalized_occurrences",
            "itc2019_global_components",
            "itc2019_global_quality",
            "itc2019_grouped_calendar",
            "itc2019_resource_seed",
            "itc2019_sparse_joint",
            "itc2019_structural",
            "itc2019_violation_lns",
        )
    },
}


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


def _capture_replay(
    label: str, evidence: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    descriptor = evidence.get("fd")
    if type(descriptor) is not int or descriptor < 3:
        raise RuntimeError(f"capture {label} descriptor rejected")
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"capture {label} is not regular")
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    if seals & REQUIRED_SEALS != REQUIRED_SEALS:
        raise RuntimeError(f"capture {label} is not sealed")
    maximum = 128 << 20 if label == "instance" else 32 << 20
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


def load_capture_manifest(
    expected_labels: frozenset[str] = EXPECTED_CAPTURE_LABELS,
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    raw = os.environ.get(CAPTURE_MANIFEST_ENV)
    if raw is None:
        raise RuntimeError("sealed capture manifest is missing")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or frozenset(manifest) != expected_labels:
        raise RuntimeError("sealed capture manifest labels rejected")
    payloads: dict[str, bytes] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for label in sorted(manifest):
        row = manifest[label]
        if not isinstance(row, dict):
            raise RuntimeError(f"capture {label} evidence rejected")
        payloads[label], evidence[label] = _capture_replay(label, row)
    executed = globals().get("__captured_sha256__")
    if executed != evidence["runner"]["sha256"]:
        raise RuntimeError("executed runner bytes differ from sealed runner capture")
    if globals().get("__runner_loader_protocol__") != "planora.muni-fspsx.frontier-v17-runner-loader.v1":
        raise RuntimeError("runner loader protocol rejected")
    return payloads, evidence


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
    return entries, sorted(excluded)


def verify_runtime_bundle(
    payloads: Mapping[str, bytes],
) -> RuntimeBundleAdmission:
    raw_binding = os.environ.get(RUNTIME_BUNDLE_ENV)
    if raw_binding is None:
        raise RuntimeError("sealed runtime bundle binding missing")
    binding = json.loads(raw_binding)
    if binding.get("protocol") != "planora.muni-fspsx.frontier-v17-sealed-runtime.v1":
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
        != "planora.muni-fspsx.frontier-v17-sealed-runtime.v1"
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
        return (
            f"<sealed-runtime:{self.relative}:{self.entry['sha256']}>"
        )

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
        import importlib.machinery
        import importlib.util

        stem = fullname.replace(".", "/")
        package_relative = f"{stem}/__init__.py"
        module_relative = f"{stem}.py"
        if package_relative in self.bundle.entries_by_path:
            entry = self.bundle.entries_by_path[package_relative]
            loader = _SealedSourceLoader(
                fullname, package_relative, entry, self.bundle, True
            )
            return importlib.util.spec_from_loader(
                fullname, loader, is_package=True
            )
        if module_relative in self.bundle.entries_by_path:
            entry = self.bundle.entries_by_path[module_relative]
            loader = _SealedSourceLoader(
                fullname, module_relative, entry, self.bundle, False
            )
            return importlib.util.spec_from_loader(
                fullname, loader, is_package=False
            )
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            relative = stem + suffix
            entry = self.bundle.entries_by_path.get(relative)
            if entry is None:
                continue
            exact_path = f"/proc/self/fd/{entry['fd']}"
            loader = importlib.machinery.ExtensionFileLoader(
                fullname, exact_path
            )
            return importlib.util.spec_from_file_location(
                fullname, exact_path, loader=loader
            )
        prefix = stem + "/"
        if any(path.startswith(prefix) for path in self.bundle.entries_by_path):
            spec = importlib.machinery.ModuleSpec(
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
    system_paths: set[str] = set()
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
            if not decoded_path.startswith(("/usr/", "/lib/", "/lib64/")):
                raise RuntimeError(
                    f"mapped runtime outside admitted system roots: {decoded_path}"
                )
            system_paths.add(decoded_path)
        elif mapped_path.startswith("/"):
            raise RuntimeError(f"deleted mapped runtime rejected: {mapped_path}")
    if unbound_memfds or not python_mapped:
        raise RuntimeError("mapped memfd runtime identity was not admitted")
    system_rows: list[dict[str, Any]] = []
    for raw_path in sorted(system_paths):
        path = Path(raw_path)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            raw = _pread_all(descriptor, maximum_bytes=256 << 20)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if _stable_identity(before) != _stable_identity(after):
            raise RuntimeError("mapped system runtime drift")
        system_rows.append(
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
    return {
        "start_file_count": len(start_rows),
        "end_file_count": len(end_rows),
        "start_subset_stable": True,
        "new_post_import_files": sorted(set(end_rows) - set(start_rows)),
        "boundary": "trusted_system_runtime_observed_and_hashed_not_sealed",
    }


def _stdlib_manifest_rows(payloads: Mapping[str, bytes]) -> dict[str, str]:
    raw = payloads.get("stdlib_manifest")
    if raw is None or sha256(raw).hexdigest() != EXPECTED_HASHES["stdlib_manifest"]:
        raise RuntimeError("sealed stdlib manifest admission failed")
    rows: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        fields = line.split("  ", 1)
        if len(fields) != 2:
            raise RuntimeError("malformed stdlib manifest row")
        digest, path = fields
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not path.startswith("/usr/lib/python3.12/")
            or path in rows
        ):
            raise RuntimeError("invalid stdlib manifest row")
        rows[path] = digest
    if not rows:
        raise RuntimeError("stdlib manifest is empty")
    return rows


def _stdlib_root_is_read_only() -> bool:
    with open("/proc/self/mountinfo", encoding="utf-8") as handle:
        for line in handle:
            before_separator = line.split(" - ", 1)[0].split()
            if (
                len(before_separator) >= 6
                and before_separator[4] == "/"
                and "ro" in before_separator[5].split(",")
            ):
                return True
    return False


def _verify_stdlib_ancestor_chain(resolved: Path) -> None:
    current = resolved
    while True:
        observed = current.stat(follow_symlinks=False)
        if (
            int(observed.st_uid) != STDLIB_EXPECTED_UID
            or int(observed.st_gid) != STDLIB_EXPECTED_GID
            or stat.S_IMODE(observed.st_mode) & 0o022
        ):
            raise RuntimeError(f"stdlib ownership/permissions rejected: {current}")
        if current == Path("/"):
            return
        current = current.parent


def _stdlib_module_evidence(
    raw_path: str, allowed_hashes: Mapping[str, str]
) -> dict[str, Any]:
    """Admit one live stdlib file against the frozen exact-hash manifest."""

    try:
        resolved = Path(raw_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"stdlib module path cannot be resolved: {raw_path}") from exc
    if not any(resolved.is_relative_to(root) for root in STDLIB_ROOTS):
        raise RuntimeError(f"Python module outside admitted stdlib roots: {raw_path}")
    if resolved.suffix == ".pyc":
        raise RuntimeError(f"stdlib pyc execution rejected: {raw_path}")
    expected_hash = allowed_hashes.get(str(resolved))
    if expected_hash is None:
        raise RuntimeError(f"stdlib module absent from frozen manifest: {resolved}")
    _verify_stdlib_ancestor_chain(resolved)
    descriptor = os.open(
        resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"stdlib module is not regular: {resolved}")
        raw = _pread_all(descriptor, maximum_bytes=MAX_STDLIB_MODULE_BYTES)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_clock = (int(before.st_mtime_ns), int(before.st_ctime_ns))
    after_clock = (int(after.st_mtime_ns), int(after.st_ctime_ns))
    if before_clock != after_clock:
        raise RuntimeError(f"stdlib module mutation clock changed: {resolved}")
    observed_hash = sha256(raw).hexdigest()
    if observed_hash != expected_hash:
        raise RuntimeError(f"stdlib module hash absent from frozen closure: {resolved}")
    return {
        "path": str(resolved),
        "sha256": observed_hash,
        "size": len(raw),
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "boundary": "freeze_pinned_read_only_system_file",
    }


def compare_stdlib_module_snapshots(
    start: Mapping[str, Any], end: Mapping[str, Any]
) -> dict[str, Any]:
    start_rows = {row["path"]: row for row in start["stdlib_files"]}
    end_rows = {row["path"]: row for row in end["stdlib_files"]}
    for path, row in start_rows.items():
        if end_rows.get(path) != row:
            raise RuntimeError(f"admitted stdlib module changed: {path}")
    return {
        "start_file_count": len(start_rows),
        "end_file_count": len(end_rows),
        "start_subset_stable": True,
        "new_post_admission_files": sorted(set(end_rows) - set(start_rows)),
        "boundary": "stdlib_observed_and_hashed_not_sealed",
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
    if not _stdlib_root_is_read_only():
        raise RuntimeError("stdlib backing filesystem is not read-only")
    allowed_stdlib_hashes = _stdlib_manifest_rows(payloads)
    loaded: list[dict[str, Any]] = []
    unexpected: set[str] = set()
    stdlib_by_path: dict[str, dict[str, Any]] = {}
    sealed_source_names = set(SEALED_SOURCE_MODULE_LABELS)
    for module_name, module in tuple(sys.modules.items()):
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        if raw_path.startswith("<frozen "):
            continue
        if raw_path.startswith("sealed:v10:"):
            if module_name not in sealed_source_names:
                unexpected.add(raw_path)
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
            try:
                row = _stdlib_module_evidence(raw_path, allowed_stdlib_hashes)
            except RuntimeError:
                unexpected.add(raw_path)
            else:
                existing = stdlib_by_path.get(row["path"])
                if existing is not None:
                    if {
                        key: value
                        for key, value in existing.items()
                        if key != "module_names"
                    } != row:
                        raise RuntimeError(
                            f"conflicting stdlib provenance: {row['path']}"
                        )
                    existing["module_names"] = sorted(
                        {*existing["module_names"], module_name}
                    )
                else:
                    row["module_names"] = [module_name]
                    stdlib_by_path[row["path"]] = row
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
        raise RuntimeError("unexpected site-packages runtime: " + ",".join(sorted(unexpected)))
    loaded.sort(key=lambda row: row["path"])
    stdlib_files = sorted(stdlib_by_path.values(), key=lambda row: row["path"])
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
        "stdlib_roots": [str(root) for root in STDLIB_ROOTS],
        "stdlib_files": stdlib_files,
        "stdlib_file_count": len(stdlib_files),
        "stdlib_manifest_sha256": sha256(
            json.dumps(
                stdlib_files, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "stdlib_boundary": "freeze_pinned_read_only_system_files",
    }


def runtime_closure_replay(
    *,
    payloads: Mapping[str, bytes],
    capture_evidence: Mapping[str, Mapping[str, Any]],
    bundle: RuntimeBundleAdmission,
    system_start: Mapping[str, Any],
    stdlib_start: Mapping[str, Any],
    phase: str,
) -> dict[str, Any]:
    """Fail closed on capture, bundle, module, executable, and map drift."""

    capture_end: dict[str, dict[str, Any]] = {}
    for label in sorted(capture_evidence):
        replayed, row = _capture_replay(label, capture_evidence[label])
        if replayed != payloads[label]:
            raise RuntimeError(f"capture payload drift during {phase}: {label}")
        capture_end[label] = row
    replayed_bundle = verify_runtime_bundle(payloads)
    if replayed_bundle.manifest_sha256 != bundle.manifest_sha256:
        raise RuntimeError(f"runtime manifest drift during {phase}")
    executing_python = verify_executing_python(payloads, capture_evidence)
    loaded = verify_loaded_runtime(payloads, replayed_bundle)
    stdlib_comparison = compare_stdlib_module_snapshots(stdlib_start, loaded)
    mapped = mapped_runtime_snapshot(
        replayed_bundle, capture_evidence, phase=phase
    )
    system_comparison = compare_system_runtime_snapshots(system_start, mapped)
    return {
        "phase": phase,
        "capture_count": len(capture_end),
        "capture_sha256": sha256(
            json.dumps(capture_end, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "runtime_bundle": replayed_bundle.evidence,
        "executing_python": executing_python,
        "loaded_runtime": loaded,
        "stdlib_comparison": stdlib_comparison,
        "mapped_runtime": mapped,
        "system_runtime_comparison": system_comparison,
    }


class _SealedLoader(importlib.abc.Loader):
    def __init__(self, fullname: str, source: bytes, digest: str, package: bool):
        self.fullname = fullname
        self.source = source
        self.digest = digest
        self.package = package

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        module.__file__ = f"sealed:v10:{self.fullname}"
        module.__planora_source_sha256__ = self.digest
        if self.package:
            module.__path__ = []
        exec(compile(self.source, module.__file__, "exec"), module.__dict__)


class _SealedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, sources: Mapping[str, tuple[bytes, str, bool]]):
        self.sources = dict(sources)

    def find_spec(self, fullname, path=None, target=None):
        del path, target
        row = self.sources.get(fullname)
        if row is None:
            return None
        source, digest, package = row
        return importlib.util.spec_from_loader(
            fullname,
            _SealedLoader(fullname, source, digest, package),
            is_package=package,
        )


def _read_fd(fd: int) -> bytes:
    observed = os.fstat(fd)
    parts: list[bytes] = []
    offset = 0
    while offset < observed.st_size:
        part = os.pread(fd, min(1 << 20, observed.st_size - offset), offset)
        if not part:
            raise RuntimeError("short sealed descriptor read")
        parts.append(part)
        offset += len(part)
    return b"".join(parts)


def _sealed_bytes(row: Mapping[str, object], label: str) -> bytes:
    fd = row.get("fd")
    expected = row.get("sha256")
    if type(fd) is not int or not isinstance(expected, str):
        raise RuntimeError(f"invalid sealed evidence for {label}")
    seals = int(fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)))
    value = _read_fd(fd)
    if seals & ALL_SEALS != ALL_SEALS or sha256(value).hexdigest() != expected:
        raise RuntimeError(f"sealed evidence drift for {label}")
    return value


def install_sealed_sources() -> dict[str, bytes]:
    if not isinstance(SEALED_RUNNER_EVIDENCE, Mapping):
        raise RuntimeError("runner was not executed from sealed captured bytes")
    _sealed_bytes(SEALED_RUNNER_EVIDENCE, "runner")
    if (
        not isinstance(SEALED_STDLIB_EVIDENCE, Mapping)
        or SEALED_STDLIB_EVIDENCE.get("pre_runner_admitted") is not True
        or SEALED_STDLIB_EVIDENCE.get("sha256")
        != EXPECTED_HASHES["stdlib_manifest"]
    ):
        raise RuntimeError("stdlib was not admitted before runner execution")
    if not isinstance(SEALED_SOURCE_EVIDENCE, Mapping):
        raise RuntimeError("sealed source evidence is absent")
    sources: dict[str, tuple[bytes, str, bool]] = {}
    raw: dict[str, bytes] = {}
    for module_name, label in SEALED_SOURCE_MODULE_LABELS.items():
        package = module_name == "benchmarks"
        row = SEALED_SOURCE_EVIDENCE.get(module_name)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"missing sealed module {module_name}")
        value = _sealed_bytes(row, label)
        digest = sha256(value).hexdigest()
        sources[module_name] = (value, digest, package)
        raw[module_name] = value
    sys.meta_path.insert(0, _SealedFinder(sources))
    return raw


def _identity(observed: os.stat_result) -> dict[str, int]:
    return {
        "device": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "uid": int(observed.st_uid),
        "mode": stat.S_IMODE(observed.st_mode),
        "size": int(observed.st_size),
        "nlink": int(observed.st_nlink),
    }


def _verify_run_directory(
    path: Path, directory_fd: int, expected: Mapping[str, int]
) -> None:
    """Bind the inherited directory FD and its live name to one identity."""

    observed = os.fstat(directory_fd)
    actual = _identity(observed)
    for key in ("device", "inode", "uid", "mode"):
        if actual[key] != int(expected[key]):
            raise RuntimeError("bound run directory identity drift")
    if not stat.S_ISDIR(observed.st_mode) or actual["mode"] != 0o700:
        raise RuntimeError("run directory is not private")
    try:
        named = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("run directory name detached from bound FD") from exc
    if stat.S_ISLNK(named.st_mode) or _identity(named) != actual:
        raise RuntimeError("run directory name no longer matches bound FD")


def _read_run_file(
    directory_fd: int, name: str, *, maximum_bytes: int = 128 << 20
) -> tuple[bytes, dict[str, int]]:
    if Path(name).name != name:
        raise RuntimeError("run artifact name rejected")
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"run artifact is not regular: {name}")
        value = _pread_all(descriptor, maximum_bytes=maximum_bytes)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after):
        raise RuntimeError(f"run artifact identity drift: {name}")
    return value, _identity(after)


def publish_no_replace(
    path: Path,
    value: bytes,
    *,
    run_directory: Path,
    run_directory_fd: int,
    run_identity: Mapping[str, int],
    mode: int = 0o400,
) -> dict[str, object]:
    """Descriptor-bound, fsynced publication that cannot replace a target."""

    _verify_run_directory(run_directory, run_directory_fd, run_identity)
    if path.parent != run_directory or Path(path.name).name != path.name:
        raise RuntimeError("publication escaped run directory")
    directory_fd = os.dup(run_directory_fd)
    temporary = f".{path.name}.partial-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"refusing existing publication: {path}")
        descriptor = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
            dir_fd=directory_fd,
        )
        view = memoryview(value)
        offset = 0
        while offset < len(view):
            offset += os.write(descriptor, view[offset:])
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        source_identity = _identity(os.fstat(descriptor))
        if _read_fd(descriptor) != value:
            raise RuntimeError("publication descriptor bytes changed")
        _verify_run_directory(run_directory, directory_fd, run_identity)
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"publication target appeared: {path}")
        os.link(
            f"/proc/self/fd/{descriptor}",
            path.name,
            dst_dir_fd=directory_fd,
            follow_symlinks=True,
        )
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        _verify_run_directory(run_directory, directory_fd, run_identity)
        final_fd = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            final = _read_fd(final_fd)
            final_identity = _identity(os.fstat(final_fd))
        finally:
            os.close(final_fd)
        if final != value or any(
            final_identity[key] != source_identity[key]
            for key in ("device", "inode", "uid", "mode", "size")
        ) or final_identity["nlink"] != 1:
            raise RuntimeError("published artifact differs from captured descriptor")
        return {
            "path": str(path),
            "sha256": sha256(value).hexdigest(),
            "identity": final_identity,
        }
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def stage_no_replace(
    path: Path,
    value: bytes,
    *,
    run_directory: Path,
    run_directory_fd: int,
    run_identity: Mapping[str, int],
    mode: int = 0o400,
) -> dict[str, object]:
    _verify_run_directory(run_directory, run_directory_fd, run_identity)
    if path.parent != run_directory or Path(path.name).name != path.name:
        raise RuntimeError("staging escaped run directory")
    fd = os.open(
        path.name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
        dir_fd=run_directory_fd,
    )
    try:
        view = memoryview(value)
        offset = 0
        while offset < len(view):
            offset += os.write(fd, view[offset:])
        os.fchmod(fd, mode)
        os.fsync(fd)
        identity = _identity(os.fstat(fd))
    finally:
        os.close(fd)
    _verify_run_directory(run_directory, run_directory_fd, run_identity)
    return {"path": str(path), "sha256": sha256(value).hexdigest(), "identity": identity}


def admit_group_table_size(domain_sizes: Sequence[int], limit: int) -> int:
    """Return an exact Cartesian size; the cap itself is admitted, cap+1 is not."""

    if limit <= 0 or any(type(size) is not int or size <= 0 for size in domain_sizes):
        raise ValueError("group table sizes and limit must be positive integers")
    total = math.prod(domain_sizes)
    if total > limit:
        raise OverflowError(f"group_time_row_limit:{total}>{limit}")
    return total


def audit_group_rows(context, limit: int) -> int:
    total = 0
    for distribution in context.distributions:
        if not distribution.required or distribution.base in {
            "SameStart", "SameTime", "DifferentTime", "SameDays",
            "DifferentDays", "SameWeeks", "DifferentWeeks", "SameRoom",
            "DifferentRoom", "Overlap", "NotOverlap", "SameAttendees",
            "Precedence", "WorkDay", "MinGap",
        }:
            continue
        addition = admit_group_table_size(
            tuple(len(context.class_for(cid).times) for cid in distribution.class_ids),
            limit,
        )
        if total + addition > limit:
            raise OverflowError(f"group_time_row_limit:{total + addition}>{limit}")
        total += addition
    return total


def serialize_solution(problem, placements, student_classes) -> bytes:
    by_class = {placement.class_id: placement for placement in placements}
    students_by_class: dict[str, list[str]] = {}
    for student_id, class_ids in student_classes.items():
        for class_id in class_ids:
            students_by_class.setdefault(class_id, []).append(student_id)
    root = ElementTree.Element("solution", {"name": problem.name, "technique": "planora-v10"})
    for class_id in sorted(by_class):
        placement = by_class[class_id]
        attributes = {
            "id": class_id,
            "days": placement.days,
            "start": str(placement.start),
            "weeks": placement.weeks,
        }
        if placement.room_id is not None:
            attributes["room"] = placement.room_id
        element = ElementTree.SubElement(root, "class", attributes)
        for student_id in sorted(students_by_class.get(class_id, ())):
            ElementTree.SubElement(element, "student", {"id": student_id})
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


VALIDATOR_BOOTSTRAP = r'''
import ctypes, fcntl, hashlib, importlib.abc, importlib.machinery, importlib.util, json, os, pathlib, stat, sys
ALL=0x0F
def read(fd):
    size=os.fstat(fd).st_size; out=[]; off=0
    while off<size:
        part=os.pread(fd,min(1<<20,size-off),off)
        if not part: raise RuntimeError("short validator descriptor read")
        out.append(part); off+=len(part)
    return b"".join(out)
stdlib_fd=int(sys.argv[1]); stdlib_expected=sys.argv[2]; stdlib_raw=read(stdlib_fd)
if fcntl.fcntl(stdlib_fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or hashlib.sha256(stdlib_raw).hexdigest()!=stdlib_expected: raise RuntimeError("sealed validator stdlib manifest drift")
stdlib={}
for line in stdlib_raw.decode("utf-8").splitlines():
    h,path=line.split("  ",1)
    if len(h)!=64 or not path.startswith("/usr/lib/python3.12/") or path in stdlib: raise RuntimeError("validator stdlib manifest row rejected")
    stdlib[path]=h
root_mount=False
for line in open("/proc/self/mountinfo",encoding="utf-8"):
    pre=line.split(" - ",1)[0].split()
    if len(pre)>=6 and pre[4]=="/" and "ro" in pre[5].split(","): root_mount=True
if not root_mount: raise RuntimeError("validator stdlib filesystem is not frozen read-only")
def admit_stdlib(path):
    resolved=os.path.realpath(path)
    if resolved!=path or resolved not in stdlib: raise RuntimeError("validator unbound stdlib module: "+path)
    current=resolved
    while True:
        row=os.stat(current,follow_symlinks=False)
        if row.st_uid!=65534 or row.st_gid!=65534 or stat.S_IMODE(row.st_mode)&0o022: raise RuntimeError("validator stdlib ownership/permissions rejected: "+current)
        if current=="/": break
        current=os.path.dirname(current)
    fd=os.open(resolved,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
    try: before=os.fstat(fd); b=read(fd); after=os.fstat(fd)
    finally: os.close(fd)
    if not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or hashlib.sha256(b).hexdigest()!=stdlib[resolved]: raise RuntimeError("validator stdlib file admission rejected: "+resolved)
    return (hashlib.sha256(b).hexdigest(),len(b),after.st_dev,after.st_ino,after.st_mtime_ns,after.st_ctime_ns)
for module in tuple(sys.modules.values()):
    raw=getattr(module,"__file__",None)
    if isinstance(raw,str) and not raw.startswith("<frozen "): admit_stdlib(raw)
class L(importlib.abc.Loader):
    def __init__(self,n,b,h,p): self.n=n; self.b=b; self.h=h; self.p=p
    def create_module(self,s): return None
    def exec_module(self,m):
        m.__file__="sealed:validation:"+self.n; m.__planora_source_sha256__=self.h
        if self.p: m.__path__=[]
        exec(compile(self.b,m.__file__,"exec"),m.__dict__)
class F(importlib.abc.MetaPathFinder):
    def __init__(self,d): self.d=d
    def find_spec(self,n,path=None,target=None):
        if n not in self.d: return None
        b,h,p=self.d[n]; return importlib.util.spec_from_loader(n,L(n,b,h,p),is_package=p)
runtime_root_fd=int(sys.argv[3]); runtime_manifest_fd=int(sys.argv[4]); runtime_manifest_sha=sys.argv[5]
runtime_manifest_raw=read(runtime_manifest_fd)
if fcntl.fcntl(runtime_manifest_fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or hashlib.sha256(runtime_manifest_raw).hexdigest()!=runtime_manifest_sha: raise RuntimeError("sealed validator runtime manifest drift")
runtime_manifest=json.loads(runtime_manifest_raw); entries=runtime_manifest["entries"]
runtime_by_identity={(os.major(int(r["device"])),os.minor(int(r["device"])),int(r["inode"])):r["relative_path"] for r in entries}
runtime_entries={r["relative_path"]:r for r in entries}; runtime_paths=set(runtime_entries); sys.dont_write_bytecode=True
class RL(importlib.abc.Loader):
    def __init__(self,n,rel,row,pkg): self.n=n; self.rel=rel; self.row=row; self.pkg=pkg
    def create_module(self,s): return None
    def is_package(self,n): return self.pkg
    def get_filename(self,n): return f"<sealed-runtime-validation:{self.rel}:{self.row['sha256']}>"
    def get_code(self,n):
        b=read(int(self.row["fd"])); h=hashlib.sha256(b).hexdigest()
        if h!=self.row["sha256"] or len(b)!=self.row["size"]: raise ImportError("sealed validator runtime drift")
        return compile(b,self.get_filename(n),"exec",dont_inherit=True)
    def get_data(self,path):
        prefix=f"/proc/self/fd/{runtime_root_fd}/"
        if not path.startswith(prefix): raise OSError("sealed validator data path rejected")
        rel=path.removeprefix(prefix); row=runtime_entries.get(rel)
        if row is None: raise OSError("sealed validator data absent")
        return read(int(row["fd"]))
    def exec_module(self,m):
        m.__file__=self.get_filename(self.n); m.__cached__=None
        if self.pkg: m.__path__=[f"/proc/self/fd/{runtime_root_fd}/{pathlib.PurePosixPath(self.rel).parent.as_posix()}"]
        exec(self.get_code(self.n),m.__dict__)
class RF(importlib.abc.MetaPathFinder):
    def find_spec(self,n,path=None,target=None):
        stem=n.replace(".","/"); pkg=stem+"/__init__.py"; mod=stem+".py"
        if pkg in runtime_entries: return importlib.util.spec_from_loader(n,RL(n,pkg,runtime_entries[pkg],True),is_package=True)
        if mod in runtime_entries: return importlib.util.spec_from_loader(n,RL(n,mod,runtime_entries[mod],False),is_package=False)
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            rel=stem+suffix; row=runtime_entries.get(rel)
            if row is not None:
                exact=f"/proc/self/fd/{row['fd']}"; loader=importlib.machinery.ExtensionFileLoader(n,exact)
                return importlib.util.spec_from_file_location(n,exact,loader=loader)
        prefix=stem+"/"
        if any(rel.startswith(prefix) for rel in runtime_paths):
            spec=importlib.machinery.ModuleSpec(n,loader=None,is_package=True); spec.submodule_search_locations=[f"/proc/self/fd/{runtime_root_fd}/{stem}"]; return spec
        return None
native=[r for rel,r in sorted(runtime_entries.items()) if ".so" in pathlib.PurePosixPath(rel).name and (pathlib.PurePosixPath(rel).name.startswith("lib") or any(p.endswith(".libs") for p in pathlib.PurePosixPath(rel).parts))]
pending=list(native); handles=[]
while pending:
    following=[]; progressed=False
    for row in pending:
        try: handles.append(ctypes.CDLL(f"/proc/self/fd/{row['fd']}",mode=os.RTLD_NOW|os.RTLD_GLOBAL)); progressed=True
        except OSError: following.append(row)
    if following and not progressed: raise RuntimeError("sealed validator native dependency closure failed")
    pending=following
sys.meta_path.insert(0,RF())
rows=json.loads(sys.argv[6]); sources={}
for name,row in rows.items():
    fd=int(row["fd"]); b=read(fd); h=hashlib.sha256(b).hexdigest()
    if fcntl.fcntl(fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or h!=row["sha256"]: raise RuntimeError("sealed validation source drift")
    sources[name]=(b,h,name=="benchmarks")
sys.meta_path.insert(0,F(sources))
validator_fd=int(sys.argv[7]); validator_sha=sys.argv[8]; source=read(validator_fd)
if fcntl.fcntl(validator_fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or hashlib.sha256(source).hexdigest()!=validator_sha: raise RuntimeError("sealed validator drift")
sys.argv=["sealed:generic-validator",*sys.argv[9:]]
scope={"__name__":"__main__","__package__":None,"__file__":"sealed:generic-validator"}
exit_code=0
try:
    exec(compile(source,"sealed:generic-validator","exec"),scope)
except SystemExit as exc:
    exit_code=0 if exc.code is None else int(exc.code)
unexpected=[]; stdlib_rows={}
for module_name,module in tuple(sys.modules.items()):
    raw=getattr(module,"__file__",None)
    if not isinstance(raw,str): continue
    if raw.startswith(("sealed:validation:","<frozen ")): continue
    if raw.startswith("<sealed-runtime-validation:"):
        rel=raw.split(":",2)[1]
        if rel not in runtime_paths: unexpected.append(raw)
        continue
    if raw.startswith("/proc/self/fd/"):
        try: observed=os.stat(raw); key=(os.major(observed.st_dev),os.minor(observed.st_dev),observed.st_ino)
        except OSError: unexpected.append(raw); continue
        if key not in runtime_by_identity: unexpected.append(raw)
        continue
    if raw.startswith(f"/proc/self/fd/{runtime_root_fd}/"):
        rel=raw.removeprefix(f"/proc/self/fd/{runtime_root_fd}/")
        if rel not in runtime_paths: unexpected.append(raw)
        continue
    try: resolved=pathlib.Path(raw).resolve(strict=True); evidence=admit_stdlib(str(resolved))
    except (OSError,RuntimeError,ValueError): unexpected.append(raw); continue
    previous=stdlib_rows.get(str(resolved))
    if previous is not None and previous[0]!=evidence: raise RuntimeError("validator conflicting stdlib provenance")
    names=set() if previous is None else set(previous[1]); names.add(module_name); stdlib_rows[str(resolved)]=(evidence,tuple(sorted(names)))
if unexpected: raise RuntimeError("validator unexpected package runtime: "+",".join(sorted(set(unexpected))))
stdlib_manifest_sha256=hashlib.sha256(json.dumps(stdlib_rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
if not stdlib_rows or "argparse" not in sys.modules: raise RuntimeError("validator stdlib closure incomplete")
python_stat=os.stat("/proc/self/exe"); python_key=(os.major(python_stat.st_dev),os.minor(python_stat.st_dev),python_stat.st_ino)
for line in pathlib.Path("/proc/self/maps").read_text().splitlines():
    fields=line.split(None,5)
    if len(fields)<5: continue
    major,minor=fields[3].split(":",1); key=(int(major,16),int(minor,16),int(fields[4])); mapped=fields[5] if len(fields)==6 else ""
    if key in runtime_by_identity or key==python_key: continue
    if mapped.startswith("/memfd:"): raise RuntimeError("validator unbound mapped memfd")
    if mapped.startswith("/"):
        decoded=mapped.replace("\\040"," ")
        if decoded.endswith(" (deleted)") or not decoded.startswith(("/usr/","/lib/","/lib64/")): raise RuntimeError("validator mapped runtime outside system boundary: "+decoded)
        fd=os.open(decoded,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); before=os.fstat(fd); raw=read(fd); after=os.fstat(fd); os.close(fd)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise RuntimeError("validator system mapping drift")
raise SystemExit(exit_code)
'''


def consume_exclusive_report_fd(
    run_directory_fd: int,
    report_name: str,
    report_fd: int,
    report_created: os.stat_result,
    *,
    maximum_bytes: int = 4 << 20,
) -> bytes:
    """Read only the retained report FD after binding its live name."""

    retained = os.fstat(report_fd)
    named = os.stat(report_name, dir_fd=run_directory_fd, follow_symlinks=False)
    stable_keys = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink")
    if (
        not stat.S_ISREG(retained.st_mode)
        or stat.S_IMODE(retained.st_mode) != 0o400
        or retained.st_nlink != 1
        or any(getattr(retained, key) != getattr(named, key) for key in stable_keys)
        or any(
            getattr(report_created, key) != getattr(retained, key)
            for key in stable_keys
        )
    ):
        raise RuntimeError("generic report retained-FD/name identity drift")
    report_bytes = _read_fd(report_fd)
    if len(report_bytes) > maximum_bytes or int(retained.st_size) != len(report_bytes):
        raise RuntimeError("generic report size contract rejected")
    os.unlink(report_name, dir_fd=run_directory_fd)
    return report_bytes


def fresh_generic_validation(
    *,
    python: Path,
    instance_fd: int,
    candidate_path: Path,
    candidate_sha: str,
    report_path: Path,
    run_directory_fd: int,
    validator_evidence: Mapping[str, object],
    bundle: RuntimeBundleAdmission,
    capture_evidence: Mapping[str, Mapping[str, Any]],
) -> tuple[int, dict[str, object]]:
    del python
    if not isinstance(SEALED_SOURCE_EVIDENCE, Mapping):
        raise RuntimeError("sealed source evidence absent")
    rows = {
        name: SEALED_SOURCE_EVIDENCE[name]
        for name in ("benchmarks", "benchmarks.itc2019")
    }
    python_fd = int(capture_evidence["python_binary"]["fd"])
    stdlib_fd = int(capture_evidence["stdlib_manifest"]["fd"])
    report_fd = os.open(
        report_path.name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o400,
        dir_fd=run_directory_fd,
    )
    report_created = os.fstat(report_fd)
    fds = [
        python_fd,
        stdlib_fd,
        bundle.root_fd,
        bundle.manifest_fd,
        instance_fd,
        int(validator_evidence["fd"]),
        run_directory_fd,
        report_fd,
        *(int(row["fd"]) for row in bundle.entries_by_path.values()),
    ] + [
        int(row["fd"]) for row in rows.values()
    ]
    command = [
        f"/proc/self/fd/{python_fd}",
        "-I",
        "-S",
        "-B",
        "-c",
        VALIDATOR_BOOTSTRAP,
        str(stdlib_fd),
        EXPECTED_HASHES["stdlib_manifest"],
        str(bundle.root_fd),
        str(bundle.manifest_fd),
        bundle.manifest_sha256,
        json.dumps(rows, sort_keys=True),
        str(validator_evidence["fd"]),
        str(validator_evidence["sha256"]),
        "--instance",
        f"/proc/self/fd/{instance_fd}",
        "--solution",
        f"/proc/self/fd/{run_directory_fd}/{candidate_path.name}",
        "--report-fd",
        str(report_fd),
        "--expected-instance-sha256",
        EXPECTED_INSTANCE_SHA256,
        "--expected-solution-sha256",
        candidate_sha,
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=tuple(fds),
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TZ": "UTC",
                "TMPDIR": f"/proc/self/fd/{run_directory_fd}",
            },
            check=False,
            timeout=20.0,
        )
        hook = GENERIC_REPORT_POST_CHILD_TEST_HOOK
        if hook is not None:
            hook(run_directory_fd, report_path.name, report_fd)
        report_bytes = consume_exclusive_report_fd(
            run_directory_fd, report_path.name, report_fd, report_created
        )
        payload = json.loads(report_bytes)
        payload["fresh_process_exit_code"] = completed.returncode
        payload["fresh_process_isolated"] = True
        payload["report_transport"] = "parent_openat_exclusive_retained_fd"
        return completed.returncode, payload
    finally:
        try:
            named = os.stat(
                report_path.name, dir_fd=run_directory_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            named = None
        retained = os.fstat(report_fd)
        if named is not None and (named.st_dev, named.st_ino) == (
            retained.st_dev,
            retained.st_ino,
        ):
            os.unlink(report_path.name, dir_fd=run_directory_fd)
        os.close(report_fd)


def _controlled_unknown(status: str) -> bool:
    return status in {
        "UNKNOWN",
        "DEADLINE_EXCEEDED",
        "RESOURCE_LIMIT",
        "UNSUPPORTED_MODEL_SCALE",
        "INFEASIBLE",
    }


def _rejected_v35_run(args: argparse.Namespace) -> int:
    del args
    raise RuntimeError(
        "v35 and component-checkpoint modes are provenance-unproven; "
        "official-input-only fresh mode is required"
    )


def validate_fairness_exclusion_certificate(
    value: bytes,
) -> dict[str, Any]:
    if sha256(value).hexdigest() != EXPECTED_HASHES["fairness_certificate"]:
        raise RuntimeError("fairness exclusion certificate hash drift")
    payload = json.loads(value)
    if (
        not isinstance(payload, dict)
        or payload.get("verdict") != "NO_GO_UNPROVEN"
        or not isinstance(payload.get("target"), dict)
        or payload["target"].get("progress_sha256")
        != EXPECTED_PROGRESS_SHA256
        or not isinstance(payload.get("component_checkpoint"), dict)
        or payload["component_checkpoint"].get("checkpoint_sha256")
        != "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80"
        or payload["component_checkpoint"].get(
            "transitive_imports_bound_by_producer_report"
        )
        is not False
        or payload["component_checkpoint"].get(
            "safe_restart_without_fresh_sealed_replay"
        )
        is not False
        or not isinstance(payload.get("fairness"), dict)
        or payload["fairness"].get("derivation_admissible") is not False
        or payload["fairness"].get(
            "competitor_or_external_schedule_absence_fully_proven_for_recursive_lineage"
        )
        is not False
    ):
        raise RuntimeError("fairness exclusion certificate verdict rejected")
    return {
        "certificate_sha256": EXPECTED_HASHES["fairness_certificate"],
        "verdict": "NO_GO_UNPROVEN",
        "excluded_progress_sha256": EXPECTED_PROGRESS_SHA256,
        "excluded_component_checkpoint_sha256": (
            "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80"
        ),
        "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        "progress_runtime_accessed": False,
        "component_checkpoint_runtime_accessed": False,
    }


def write_sealed_import_probe_report(
    report_fd: int,
    expected_identity: tuple[int, int, int],
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Publish the probe result only through the inherited retained FD."""

    before = os.fstat(report_fd)
    actual = (int(before.st_dev), int(before.st_ino), int(before.st_uid))
    if (
        report_fd < 3
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or int(before.st_nlink) != 1
        or actual != expected_identity
        or int(before.st_size) != 0
    ):
        raise RuntimeError("probe report inherited descriptor binding rejected")
    value = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    if len(value) > 4 << 20:
        raise RuntimeError("probe report exceeds bound")
    view = memoryview(value)
    while view:
        written = os.write(report_fd, view)
        if written <= 0:
            raise RuntimeError("probe report descriptor stopped accepting bytes")
        view = view[written:]
    os.fchmod(report_fd, 0o400)
    os.fsync(report_fd)
    after = os.fstat(report_fd)
    if (
        (int(after.st_dev), int(after.st_ino), int(after.st_uid)) != actual
        or stat.S_IMODE(after.st_mode) != 0o400
        or int(after.st_nlink) != 1
        or _read_fd(report_fd) != value
    ):
        raise RuntimeError("probe report final descriptor replay rejected")
    return {"sha256": sha256(value).hexdigest(), "size": len(value)}


def run_sealed_import_probe(args: argparse.Namespace) -> int:
    """Import the sealed Planora and native closure without input or solving."""

    payloads, capture_evidence = load_capture_manifest(PROBE_CAPTURE_LABELS)
    executing_python = verify_executing_python(payloads, capture_evidence)
    bundle = verify_runtime_bundle(payloads)
    pre_maps = mapped_runtime_snapshot(
        bundle, capture_evidence, phase="probe-pre-import"
    )
    runtime_install = install_sealed_runtime(bundle)
    sealed_sources = install_sealed_sources()
    imported = []
    for module_name in (
        "benchmarks.itc2019",
        "benchmarks.itc2019_preprocessing",
        "benchmarks.itc2019_frontier_joint",
        "benchmarks.itc2019_room_oracle",
        *sorted(name for name in SEALED_SOURCE_MODULE_LABELS if name.startswith("benchmarks.itc2019_")),
        "numpy",
        "pandas",
        "ortools.sat.python.cp_model",
        "google.protobuf",
        "absl",
        "immutabledict",
    ):
        importlib.import_module(module_name)
        imported.append(module_name)
    runtime_after = verify_loaded_runtime(payloads, bundle)
    post_maps = mapped_runtime_snapshot(
        bundle, capture_evidence, phase="probe-post-import"
    )
    source_rows = [
        {"module": name, "sha256": sha256(value).hexdigest()}
        for name, value in sorted(sealed_sources.items())
    ]
    payload = {
        "schema": "planora.muni-fspsx.frontier-v17.sealed-import-probe-child.v1",
        "status": "PASS",
        "input_mode": "NONE",
        "official_input_opened": False,
        "progress_opened": False,
        "checkpoint_opened": False,
        "solve_called": False,
        "imported_modules": imported,
        "executing_python": executing_python,
        "runtime_install": runtime_install,
        "loaded_runtime": runtime_after,
        "pre_import_maps": pre_maps,
        "post_import_maps": post_maps,
        "system_runtime_comparison": compare_system_runtime_snapshots(
            pre_maps, post_maps
        ),
        "planora_source_manifest_sha256": sha256(
            json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    write_sealed_import_probe_report(
        args.probe_report_fd,
        (args.probe_report_device, args.probe_report_inode, args.probe_report_uid),
        payload,
    )
    return 0


def run(args: argparse.Namespace) -> int:
    """Run one fresh, official-input-only Planora solve with no resume state."""

    payloads, capture_evidence = load_capture_manifest()
    executing_python = verify_executing_python(payloads, capture_evidence)
    bundle = verify_runtime_bundle(payloads)
    runtime_pre_maps = mapped_runtime_snapshot(
        bundle, capture_evidence, phase="pre-third-party-import"
    )
    runtime_install = install_sealed_runtime(bundle)
    sealed_sources = install_sealed_sources()
    from benchmarks.itc2019 import (
        parse_itc2019_solution,
        parse_itc2019_xml,
        score_itc2019_solution,
        solve_itc2019_native,
        validate_itc2019_solution,
        validate_itc2019_solution_document,
    )

    runtime_after_import = verify_loaded_runtime(payloads, bundle)
    runtime_import_maps = mapped_runtime_snapshot(
        bundle, capture_evidence, phase="post-third-party-import"
    )
    runtime_admission = {
        "executing_python": executing_python,
        "sealed_runtime_bundle": bundle.evidence,
        "runtime_install": runtime_install,
        "loaded_runtime": runtime_after_import,
        "pre_import_maps": runtime_pre_maps,
        "post_import_maps": runtime_import_maps,
        "system_runtime_comparison": compare_system_runtime_snapshots(
            runtime_pre_maps, runtime_import_maps
        ),
        "stdlib_boundary": "freeze_pinned_read_only_system_files",
        "residual_system_boundary": "observed_and_hashed_not_sealed",
    }
    certificate_row = SEALED_SOURCE_EVIDENCE.get("fairness_certificate")
    if not isinstance(certificate_row, Mapping):
        raise RuntimeError("sealed fairness exclusion certificate absent")
    fairness_exclusion = validate_fairness_exclusion_certificate(
        _sealed_bytes(certificate_row, "fairness_certificate")
    )

    run_directory = args.run_directory
    run_directory_fd = args.run_directory_fd
    run_identity = {
        "device": args.run_device,
        "inode": args.run_inode,
        "uid": args.run_uid,
        "mode": 0o700,
    }
    _verify_run_directory(run_directory, run_directory_fd, run_identity)
    partial_path = run_directory / "partial-checkpoint.json"
    output_path = run_directory / "solution.xml"
    report_path = run_directory / "runner-report.json"
    for path in (partial_path, output_path, report_path):
        try:
            os.stat(path.name, dir_fd=run_directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise FileExistsError("runner publication path already exists")

    stop = {"signal": None}

    def receive(signum, _frame) -> None:
        stop["signal"] = int(signum)

    for signum in (
        signal.SIGINT,
        signal.SIGTERM,
        getattr(signal, "SIGHUP", signal.SIGTERM),
    ):
        signal.signal(signum, receive)

    instance_row = SEALED_SOURCE_EVIDENCE["instance"]
    instance_bytes = _sealed_bytes(instance_row, "instance")
    if sha256(instance_bytes).hexdigest() != EXPECTED_INSTANCE_SHA256:
        raise RuntimeError("official instance hash drift")
    problem = parse_itc2019_xml(f"/proc/self/fd/{instance_row['fd']}")
    if len(problem.classes) != EXPECTED_PLACEMENTS:
        raise RuntimeError("official instance class cardinality drift")
    if len(problem.students) != EXPECTED_STUDENTS:
        raise RuntimeError("official instance student cardinality drift")

    source_rows = [
        {
            "module": module,
            "sha256": sha256(sealed_sources[module]).hexdigest(),
        }
        for module in sorted(sealed_sources)
    ]
    source_manifest_sha256 = sha256(
        json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    partial_payload = {
        "schema": "planora.muni-fspsx.frontier-v17.fresh-partial.v1",
        "status": "FRESH_SOLVE_NOT_YET_ADMISSIBLE",
        "admissible_as_solution": False,
        "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
        "lineage": {
            "instance_sha256": EXPECTED_INSTANCE_SHA256,
            "runner_sha256": args.runner_sha256,
            "supervisor_sha256": args.supervisor_sha256,
            "planora_source_manifest_sha256": source_manifest_sha256,
            "unsolved_classes": EXPECTED_PLACEMENTS,
            "unsolved_students": EXPECTED_STUDENTS,
        },
        "fairness_exclusion": fairness_exclusion,
        "runtime_lineage": {
            "python_binary_sha256": EXPECTED_HASHES["python_binary"],
            "runtime_manifest_sha256": bundle.manifest_sha256,
            "loaded_manifest_sha256": runtime_after_import[
                "loaded_manifest_sha256"
            ],
            "stdlib_manifest_sha256": runtime_after_import[
                "stdlib_manifest_sha256"
            ],
            "residual_system_boundary": "observed_and_hashed_not_sealed",
        },
    }
    partial_bytes = (
        json.dumps(partial_payload, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode()
    partial_evidence = publish_no_replace(
        partial_path,
        partial_bytes,
        run_directory=run_directory,
        run_directory_fd=run_directory_fd,
        run_identity=run_identity,
    )

    def controlled_unknown(payload: dict[str, Any]) -> int:
        payload["schema"] = (
            "planora.muni-fspsx.frontier-v17.controlled-unknown.v1"
        )
        payload["status"] = "CONTROLLED_UNKNOWN"
        payload["admissible_as_solution"] = False
        payload["solver_input_mode"] = "OFFICIAL_INPUT_ONLY_FRESH"
        payload["competitor_schedule_or_result_used"] = False
        payload["competitor_placement_or_hint_used"] = False
        payload["fairness_exclusion"] = fairness_exclusion
        payload["partial"] = partial_evidence
        payload["runtime_closure"] = runtime_closure_replay(
            payloads=payloads,
            capture_evidence=capture_evidence,
            bundle=bundle,
            system_start=runtime_import_maps,
            stdlib_start=runtime_after_import,
            phase="controlled-unknown-pre-exit",
        )
        print(
            json.dumps(
                payload, sort_keys=True, default=str, allow_nan=False
            ),
            flush=True,
        )
        return 3

    deadline = args.absolute_deadline_monotonic
    remaining = deadline - time.monotonic() - FINALIZATION_RESERVE_SECONDS
    if stop["signal"] is not None or remaining <= 0:
        return controlled_unknown({"reason": "fresh_budget_or_signal_before_solve"})
    fresh = solve_itc2019_native(
        problem,
        time_limit_seconds=remaining,
        workers=1,
        random_seed=271,
        max_pair_matrix_cells=PAIR_PLACEMENT_CELL_CAP,
        max_group_table_rows=GROUP_TIME_ROW_CAP,
        max_joint_student_conjunctions=2_000_000,
        max_sparse_room_constraints=30_000_000,
        formulation="auto",
    )
    fresh_payload = fresh.to_dict()
    if not fresh.is_feasible:
        if not _controlled_unknown(fresh.status):
            raise RuntimeError(f"fresh Planora solve failed: {fresh.status}")
        return controlled_unknown(
            {"reason": "fresh_solve_no_result", "fresh_solve": fresh_payload}
        )
    if stop["signal"] is not None or time.monotonic() >= deadline:
        return controlled_unknown(
            {"reason": "signal_or_deadline_after_fresh_solve", "fresh_solve": fresh_payload}
        )
    semantic_errors = tuple(
        validate_itc2019_solution(
            problem, fresh.placements, fresh.student_classes
        )
    )
    if semantic_errors:
        raise RuntimeError("semantic validation failed: " + semantic_errors[0])
    if (
        len(fresh.placements) != EXPECTED_PLACEMENTS
        or len(fresh.student_classes) != EXPECTED_STUDENTS
    ):
        raise RuntimeError("fresh solution cardinality drift")
    xml_bytes = serialize_solution(
        problem, fresh.placements, fresh.student_classes
    )
    candidate_path = run_directory / f".candidate-{secrets.token_hex(8)}.xml"
    generic_report_path = run_directory / f".generic-{secrets.token_hex(8)}.json"
    stage = stage_no_replace(
        candidate_path,
        xml_bytes,
        run_directory=run_directory,
        run_directory_fd=run_directory_fd,
        run_identity=run_identity,
    )
    try:
        parsed = parse_itc2019_solution(
            f"/proc/self/fd/{run_directory_fd}/{candidate_path.name}"
        )
        document_errors = tuple(
            validate_itc2019_solution_document(problem, parsed)
        )
        if document_errors:
            raise RuntimeError("document validation failed: " + document_errors[0])
        if (
            len(parsed.placements) != EXPECTED_PLACEMENTS
            or len(parsed.student_classes) != EXPECTED_STUDENTS
        ):
            raise RuntimeError("parsed fresh solution cardinality drift")
        validator_evidence = SEALED_SOURCE_EVIDENCE["generic_validator"]
        exit_code, generic = fresh_generic_validation(
            python=args.python,
            instance_fd=int(instance_row["fd"]),
            candidate_path=candidate_path,
            candidate_sha=str(stage["sha256"]),
            report_path=generic_report_path,
            run_directory_fd=run_directory_fd,
            validator_evidence=validator_evidence,
            bundle=bundle,
            capture_evidence=capture_evidence,
        )
        if exit_code != 0 or generic.get("status") != "COMPLETE_VALID":
            raise RuntimeError("fresh generic validation failed")
        if (
            generic.get("instance_sha256") != EXPECTED_INSTANCE_SHA256
            or generic.get("solution_sha256") != stage["sha256"]
            or generic.get("validator_sha256")
            != EXPECTED_HASHES["semantic"]
        ):
            raise RuntimeError("fresh generic validation lineage drift")
        runtime_closure = runtime_closure_replay(
            payloads=payloads,
            capture_evidence=capture_evidence,
            bundle=bundle,
            system_start=runtime_import_maps,
            stdlib_start=runtime_after_import,
            phase="complete-pre-publication",
        )
        if stop["signal"] is not None or time.monotonic() >= deadline:
            return controlled_unknown(
                {"reason": "signal_or_deadline_during_final_closure"}
            )
        score = score_itc2019_solution(
            problem, fresh.placements, fresh.student_classes
        )
        report = {
            "schema": "planora.muni-fspsx.frontier-v17.fresh-complete.v1",
            "status": "COMPLETE_VALID",
            "admissible_as_solution": True,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "instance_sha256": EXPECTED_INSTANCE_SHA256,
            "planora_source_manifest_sha256": source_manifest_sha256,
            "placements": len(fresh.placements),
            "students": len(fresh.student_classes),
            "fresh_solve": fresh_payload,
            "fresh_generic_validation": generic,
            "semantic_errors": [],
            "document_errors": [],
            "cardinality_errors": [],
            "score": score.to_dict(),
            "partial_checkpoint": partial_evidence,
            "fairness_exclusion": fairness_exclusion,
            "runtime_admission": runtime_admission,
            "runtime_closure": runtime_closure,
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
        }
        output_evidence = publish_no_replace(
            output_path,
            xml_bytes,
            run_directory=run_directory,
            run_directory_fd=run_directory_fd,
            run_identity=run_identity,
        )
        report["output"] = output_evidence
        report_bytes = (
            json.dumps(
                report, indent=2, sort_keys=True, default=str, allow_nan=False
            )
            + "\n"
        ).encode()
        report_evidence = publish_no_replace(
            report_path,
            report_bytes,
            run_directory=run_directory,
            run_directory_fd=run_directory_fd,
            run_identity=run_identity,
        )
        print(
            json.dumps(
                {
                    "schema": "planora.muni-fspsx.frontier-v17.runner-result.v1",
                    "status": "COMPLETE_VALID",
                    "admissible_as_solution": True,
                    "competitor_schedule_or_result_used": False,
                    "competitor_placement_or_hint_used": False,
                    "output": output_evidence,
                    "report": report_evidence,
                },
                sort_keys=True,
                allow_nan=False,
            ),
            flush=True,
        )
        return 0
    finally:
        for path in (candidate_path, generic_report_path):
            try:
                os.unlink(path.name, dir_fd=run_directory_fd)
            except FileNotFoundError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--launch", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--sealed-import-probe", action="store_true")
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--run-directory-fd", type=int)
    parser.add_argument("--run-device", type=int)
    parser.add_argument("--run-inode", type=int)
    parser.add_argument("--run-uid", type=int)
    parser.add_argument("--runner-sha256")
    parser.add_argument("--supervisor-sha256")
    parser.add_argument("--absolute-deadline-monotonic", type=float)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--probe-report-fd", type=int)
    parser.add_argument("--probe-report-device", type=int)
    parser.add_argument("--probe-report-inode", type=int)
    parser.add_argument("--probe-report-uid", type=int)
    args = parser.parse_args(argv)
    if args.sealed_import_probe:
        required_probe = (
            args.probe_report_fd,
            args.probe_report_device,
            args.probe_report_inode,
            args.probe_report_uid,
        )
        if any(value is None for value in required_probe):
            parser.error("--sealed-import-probe requires retained report bindings")
        if args.probe_report_fd < 3:
            parser.error("--probe-report-fd must be inherited")
        return run_sealed_import_probe(args)
    if not args.launch:
        print(json.dumps({
            "schema": "planora.muni-fspsx.frontier-v17.runner-gate.v1",
            "status": "NOT_LAUNCHED",
            "children_started": False,
            "artifacts_written": False,
            "required_flag": "--launch",
        }, sort_keys=True))
        return 0
    required = (
        args.run_directory, args.run_directory_fd,
        args.run_device, args.run_inode, args.run_uid,
        args.runner_sha256, args.supervisor_sha256,
        args.absolute_deadline_monotonic, args.python,
    )
    if any(value is None for value in required):
        parser.error("--launch requires complete supervisor bindings")
    if args.run_directory_fd < 3:
        parser.error("--run-directory-fd must be an inherited descriptor")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
