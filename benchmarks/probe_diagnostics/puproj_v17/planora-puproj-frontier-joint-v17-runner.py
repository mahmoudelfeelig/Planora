#!/usr/bin/env python3
"""Sealed fresh official-input-only PU-PROJ runner.

Official execution is possible only from a supervisor-captured sealed memfd.
No checkpoint, incumbent placement, or competitor hint is admitted. A complete
solution is publishable only after local and sealed generic validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import base64
import csv
import ctypes
import errno
import fcntl
from hashlib import sha256
import importlib.abc
import importlib.util
import io
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import resource
import signal
import stat
import subprocess
import sys
import time
import types
from typing import Any, Mapping
from xml.etree import ElementTree
import uuid


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
EXPECTED_CLASS_COUNT = 8_813
EXPECTED_STUDENT_COUNT = 38_437
COOPERATIVE_DEADLINE_SECONDS = 300.0
RUNNER_RSS_CEILING_KIB = 1_400_000
GENERIC_REPORT_POST_CHILD_TEST_HOOK = None
CAPTURE_MANIFEST_ENV = "PUPROJ_FRONTIER_V17_CAPTURE_MANIFEST"
OUTPUT_BINDING_ENV = "PUPROJ_FRONTIER_V17_OUTPUT_BINDING"
RUNTIME_BUNDLE_ENV = "PUPROJ_FRONTIER_V17_RUNTIME_BUNDLE"
PYCACHE_PREFIX_ENV = "PUPROJ_FRONTIER_V17_PYCACHE_PREFIX"
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)
OUTPUT_SOLUTION = "solution.xml"
OUTPUT_REPORT = "runner-report.json"
AT_FDCWD = -100
RENAME_NOREPLACE = 1
LIBC = ctypes.CDLL(None, use_errno=True)
SYSTEM_PYTHON_ROOT = Path("/usr/lib/python3.12")
SYSTEM_PYTHON_OWNER_UID = 65_534
EXPECTED_STDLIB_MANIFEST_SHA256 = (
    "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327"
)
EXPECTED_STDLIB_MANIFEST_FILES = 619
EXPECTED_ARGPARSE_PATH = SYSTEM_PYTHON_ROOT / "argparse.py"
EXPECTED_ARGPARSE_SHA256 = (
    "29395feb61bc376ca4ff9d44069af8d914ec2a1f25a4bd7978f6e2afef5bc07f"
)
EXPECTED_SYSTEM_SYS_PATH = (
    "/usr/lib/python312.zip",
    "/usr/lib/python3.12",
    "/usr/lib/python3.12/lib-dynload",
)

EXPECTED_HASHES = {
    "full_instance": "2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42",
    "semantic": "5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f",
    "preprocessing": "b98b6d56bcbdedaf491ac91194c9eef8997f624ab81c7f52e3a647c174994644",
    "room": "ff16e0a6045bffa7402748c537213c727918afddd35d92513ba4133972753ca6",
    "benchmarks_init": "be6f5557e4565d1de24b4ced5a56a610fd935fc8320f1ffe5014255a59e3b84a",
    "benchmarks_corpus": "74d23c0940713b8a40a9f789d4c0ece7402e5d9b81514587d3015d497d4112b3",
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
    "generic_validator": "dec76fcfbdc384135a0f2e1f134d1a0e31d73cdd520164a11fcaa1bb679d3dd3",
    "python_binary": "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273",
    "stdlib_manifest": EXPECTED_STDLIB_MANIFEST_SHA256,
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


def _parse_stdlib_manifest(raw: bytes) -> dict[str, str]:
    if sha256(raw).hexdigest() != EXPECTED_STDLIB_MANIFEST_SHA256:
        raise RuntimeError("stdlib manifest SHA-256 rejected")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise RuntimeError("stdlib manifest canonical newline contract rejected")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise RuntimeError("stdlib manifest must be ASCII") from error
    hashes: dict[str, str] = {}
    paths: list[str] = []
    for line in lines:
        digest, separator, raw_path = line.partition("  ")
        path = PurePosixPath(raw_path)
        if (
            separator != "  "
            or len(digest) != 64
            or digest != digest.lower()
            or any(character not in "0123456789abcdef" for character in digest)
            or not path.is_absolute()
            or path.as_posix() != raw_path
            or not raw_path.startswith(f"{SYSTEM_PYTHON_ROOT.as_posix()}/")
            or ".." in path.parts
            or path.suffix in {".pyc", ".pyo"}
            or raw_path in hashes
        ):
            raise RuntimeError(f"stdlib manifest row rejected: {line!r}")
        hashes[raw_path] = digest
        paths.append(raw_path)
    if (
        len(hashes) != EXPECTED_STDLIB_MANIFEST_FILES
        or paths != sorted(paths)
        or "/usr/lib/python3.12/importlib/resources/abc.py" not in hashes
    ):
        raise RuntimeError("stdlib manifest cardinality/order/closure rejected")
    return hashes


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


def _hash_admitted_system_python_file(
    path: Path, manifest_hashes: Mapping[str, str]
) -> dict[str, Any]:
    raw_path = str(path)
    try:
        relative = path.relative_to(SYSTEM_PYTHON_ROOT)
    except ValueError as error:
        raise RuntimeError(
            f"system Python path outside frozen root: {raw_path}"
        ) from error
    if not relative.parts or ".." in relative.parts or path.suffix in {".pyc", ".pyo"}:
        raise RuntimeError(f"live Python bytecode/arbitrary path rejected: {raw_path}")
    if os.path.realpath(raw_path) != raw_path:
        raise RuntimeError(f"system Python symlink path rejected: {raw_path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"system Python ownership/mode drift: {raw_path}")
        raw = _pread_all(descriptor, maximum_bytes=64 << 20)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        _stable_identity(before) != _stable_identity(after)
        or not stat.S_ISREG(after.st_mode)
        or int(after.st_uid) != SYSTEM_PYTHON_OWNER_UID
        or stat.S_IMODE(after.st_mode) & 0o022
    ):
        raise RuntimeError(f"system Python ownership/mode drift: {raw_path}")
    observed = sha256(raw).hexdigest()
    expected = manifest_hashes.get(raw_path)
    if expected is None or observed != expected:
        raise RuntimeError(
            f"unpinned or mutated system Python file rejected: {raw_path}"
        )
    if not os.statvfs(path).f_flag & getattr(os, "ST_RDONLY", 1):
        raise RuntimeError("system Python filesystem is no longer read-only")
    parent = path.parent
    while True:
        row = os.lstat(parent)
        if (
            not stat.S_ISDIR(row.st_mode)
            or int(row.st_uid) != SYSTEM_PYTHON_OWNER_UID
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise RuntimeError(f"system Python parent trust rejected: {parent}")
        if parent == Path("/"):
            break
        parent = parent.parent
    return {
        "path": raw_path,
        "sha256": observed,
        "size": len(raw),
        "identity": list(_stable_identity(after)),
        "owner_uid": int(after.st_uid),
        "root": str(SYSTEM_PYTHON_ROOT),
        "read_only_filesystem": True,
    }


def _admit_sealed_capture_module_origin(
    module: types.ModuleType,
    raw_path: str,
    capture_evidence: Mapping[str, Any],
    admitted_labels: set[str],
) -> dict[str, str]:
    if raw_path.startswith("/"):
        raise RuntimeError("absolute path passed as sealed capture module origin")
    if not raw_path.startswith("<sealed:"):
        raise RuntimeError(
            f"arbitrary relative Python module path rejected: {raw_path}"
        )
    if not raw_path.endswith(">"):
        raise RuntimeError(f"malformed sealed capture module origin: {raw_path}")
    binding = raw_path[len("<sealed:") : -1]
    if binding.count(":") != 1:
        raise RuntimeError(f"malformed sealed capture module origin: {raw_path}")
    label, digest = binding.split(":", 1)
    if (
        not label
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in label)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError(f"malformed sealed capture module origin: {raw_path}")
    evidence = capture_evidence.get(label)
    if not isinstance(evidence, Mapping):
        raise RuntimeError(f"unknown sealed capture label rejected: {label}")
    if getattr(module, "__captured_sha256__", None) != digest:
        raise RuntimeError(f"sealed capture origin hash mismatch: {label}")
    if evidence.get("label") != label:
        raise RuntimeError(f"sealed capture replay label mismatch: {label}")
    if evidence.get("sha256") != digest:
        raise RuntimeError(f"sealed capture replay hash mismatch: {label}")
    seals = evidence.get("seals")
    if (
        type(seals) is not int
        or seals & REQUIRED_SEALS != REQUIRED_SEALS
        or evidence.get("required_seals") != REQUIRED_SEALS
        or evidence.get("transport") != "sealed_memfd"
    ):
        raise RuntimeError(f"unsealed capture origin rejected: {label}")
    if label in admitted_labels:
        raise RuntimeError(f"duplicate sealed capture origin rejected: {label}")
    admitted_labels.add(label)
    return {
        "label": label,
        "sha256": digest,
        "origin": raw_path,
        "transport": "supervisor_sealed_capture_replay",
    }


def verify_system_python_provenance(
    *,
    phase: str,
    stdlib_manifest_raw: bytes,
    capture_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_hashes = _parse_stdlib_manifest(stdlib_manifest_raw)
    runtime_binding = json.loads(os.environ.get(RUNTIME_BUNDLE_ENV, "null"))
    output_binding = json.loads(os.environ.get(OUTPUT_BINDING_ENV, "null"))
    expected_prefix = os.environ.get(PYCACHE_PREFIX_ENV)
    if not isinstance(runtime_binding, dict) or not isinstance(output_binding, dict):
        raise RuntimeError(
            "runtime/output binding missing for system Python provenance"
        )
    root_fd = runtime_binding.get("root_fd")
    run_fd = output_binding.get("fd")
    if type(root_fd) is not int or type(run_fd) is not int:
        raise RuntimeError("runtime/output descriptor binding rejected")
    run_row = os.fstat(run_fd)
    expected_prefix_from_output = str(
        Path(str(output_binding.get("path"))) / ".pycache-v17"
    )
    if (
        expected_prefix != expected_prefix_from_output
        or sys.pycache_prefix != expected_prefix
        or Path(expected_prefix).exists()
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or tuple(sys.path) != (f"/proc/self/fd/{root_fd}", *EXPECTED_SYSTEM_SYS_PATH)
        or (
            int(run_row.st_dev),
            int(run_row.st_ino),
            stat.S_IMODE(run_row.st_mode),
            int(run_row.st_uid),
        )
        != tuple(output_binding.get(key) for key in ("device", "inode", "mode", "uid"))
    ):
        raise RuntimeError("runner private-pycache/sys.path/output binding rejected")
    if getattr(argparse, "__file__", None) != str(EXPECTED_ARGPARSE_PATH):
        raise RuntimeError("real frozen argparse module was not loaded")
    rows: dict[str, dict[str, Any]] = {}
    sealed_capture_rows: list[dict[str, str]] = []
    sealed_capture_labels: set[str] = set()
    for module in tuple(sys.modules.values()):
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        if raw_path.startswith(("<sealed-runtime:", "/proc/self/fd/")):
            continue
        if not raw_path.startswith("/"):
            sealed_capture_rows.append(
                _admit_sealed_capture_module_origin(
                    module,
                    raw_path,
                    capture_evidence,
                    sealed_capture_labels,
                )
            )
            continue
        row = _hash_admitted_system_python_file(Path(raw_path), manifest_hashes)
        previous = rows.get(raw_path)
        if previous is not None and previous != row:
            raise RuntimeError("duplicate system Python module identity drift")
        rows[raw_path] = row
    if (
        rows.get(str(EXPECTED_ARGPARSE_PATH), {}).get("sha256")
        != EXPECTED_ARGPARSE_SHA256
    ):
        raise RuntimeError("frozen argparse SHA-256 drift")
    ordered = [rows[path] for path in sorted(rows)]
    ordered_sealed = sorted(sealed_capture_rows, key=lambda row: row["label"])
    return {
        "phase": phase,
        "system_python_root": str(SYSTEM_PYTHON_ROOT),
        "system_python_owner_uid": SYSTEM_PYTHON_OWNER_UID,
        "argparse_path": str(EXPECTED_ARGPARSE_PATH),
        "argparse_sha256": EXPECTED_ARGPARSE_SHA256,
        "private_pycache_prefix": expected_prefix,
        "live_pyc_rejected": True,
        "rows": ordered,
        "row_count": len(ordered),
        "stdlib_manifest_sha256": EXPECTED_STDLIB_MANIFEST_SHA256,
        "stdlib_manifest_file_count": len(manifest_hashes),
        "stdlib_manifest_transport": "supervisor_sealed_capture_replay",
        "sealed_capture_origins": ordered_sealed,
        "sealed_capture_origin_count": len(ordered_sealed),
        "imported_subset_sha256": sha256(
            json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "imported_subset_file_count": len(ordered),
    }


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
    maximum = 128 << 20 if label == "full_instance" else 32 << 20
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
    if (
        evidence.get("seals") != seals
        or evidence.get("required_seals") != REQUIRED_SEALS
    ):
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
    *, include_official: bool = True
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    raw = os.environ.get(CAPTURE_MANIFEST_ENV)
    if raw is None:
        raise RuntimeError("sealed capture manifest is missing")
    manifest = json.loads(raw)
    expected_labels = (
        EXPECTED_CAPTURE_LABELS
        if include_official
        else EXPECTED_CAPTURE_LABELS - {"full_instance"}
    )
    if not isinstance(manifest, dict) or frozenset(manifest) != expected_labels:
        raise RuntimeError("sealed capture manifest labels rejected")
    payloads: dict[str, bytes] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for label in sorted(manifest):
        row = manifest[label]
        if not isinstance(row, dict):
            raise RuntimeError(f"capture {label} evidence rejected")
        payloads[label], evidence[label] = _capture_replay(label, row)
    _parse_stdlib_manifest(payloads["stdlib_manifest"])
    executed = globals().get("__captured_sha256__")
    if executed != evidence["runner"]["sha256"]:
        raise RuntimeError("executed runner bytes differ from sealed runner capture")
    if (
        globals().get("__runner_loader_protocol__")
        != "planora.puproj.frontier-v17-runner-loader.v1"
    ):
        raise RuntimeError("runner loader protocol rejected")
    return payloads, evidence


def _resource_guard(deadline: float, phase: str) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"cooperative deadline reached during {phase}")
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if peak >= RUNNER_RSS_CEILING_KIB:
        raise MemoryError(f"runner RSS ceiling reached during {phase}")


def _execute_module(name: str, label: str, payload: bytes) -> types.ModuleType:
    digest = sha256(payload).hexdigest()
    filename = f"<sealed:{label}:{digest}>"
    module = types.ModuleType(name)
    module.__file__ = filename
    module.__package__ = "benchmarks"
    module.__cached__ = None
    module.__captured_sha256__ = digest
    sys.modules[name] = module
    exec(compile(payload, filename, "exec", dont_inherit=True), module.__dict__)
    return module


class _CapturedSourceLoader(importlib.abc.Loader):
    def __init__(self, name: str, label: str, source: bytes, package: bool = False):
        self.name = name
        self.label = label
        self.source = source
        self.package = package

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        digest = sha256(self.source).hexdigest()
        module.__file__ = f"<sealed:{self.label}:{digest}>"
        module.__cached__ = None
        module.__captured_sha256__ = digest
        if self.package:
            module.__path__ = []
        exec(compile(self.source, module.__file__, "exec", dont_inherit=True), module.__dict__)


class _CapturedSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, rows: Mapping[str, tuple[str, bytes, bool]]):
        self.rows = dict(rows)

    def find_spec(self, fullname, path=None, target=None):
        del path, target
        row = self.rows.get(fullname)
        if row is None:
            return None
        label, source, package = row
        return importlib.util.spec_from_loader(
            fullname,
            _CapturedSourceLoader(fullname, label, source, package),
            is_package=package,
        )


def load_exact_runtime(payloads: Mapping[str, bytes]) -> dict[str, types.ModuleType]:
    rows: dict[str, tuple[str, bytes, bool]] = {
        "benchmarks": ("benchmarks_init", payloads["benchmarks_init"], True),
        "benchmarks.corpus": ("benchmarks_corpus", payloads["benchmarks_corpus"], False),
        "benchmarks.itc2019": ("semantic", payloads["semantic"], False),
        "benchmarks.itc2019_preprocessing": (
            "preprocessing", payloads["preprocessing"], False
        ),
        "benchmarks.itc2019_room_oracle": ("room", payloads["room"], False),
    }
    for label in EXPECTED_HASHES:
        if label.startswith("itc2019_"):
            rows[f"benchmarks.{label}"] = (label, payloads[label], False)
    sys.meta_path.insert(0, _CapturedSourceFinder(rows))
    import benchmarks.itc2019 as semantic
    return {
        "semantic": semantic,
    }


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
        or sum(row[1] for row in entries.values()) != EXPECTED_RUNTIME_BUNDLE_BYTES
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
    if binding.get("protocol") != "planora.puproj.frontier-v17-sealed-runtime.v1":
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
        manifest.get("schema") != "planora.puproj.frontier-v17-sealed-runtime.v1"
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
        raw = _pread_all(int(self.entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES)
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

    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> Any:
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
            return importlib.util.spec_from_loader(fullname, loader, is_package=True)
        if module_relative in self.bundle.entries_by_path:
            entry = self.bundle.entries_by_path[module_relative]
            loader = _SealedSourceLoader(
                fullname, module_relative, entry, self.bundle, False
            )
            return importlib.util.spec_from_loader(fullname, loader, is_package=False)
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            relative = stem + suffix
            entry = self.bundle.entries_by_path.get(relative)
            if entry is None:
                continue
            exact_path = f"/proc/self/fd/{entry['fd']}"
            loader = importlib.machinery.ExtensionFileLoader(fullname, exact_path)
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
                f"sealed native dependency closure failed: {first}: {failures[first]}"
            )
        pending = following
    bundle.native_handles = handles
    sys.meta_path.insert(0, _SealedRuntimeFinder(bundle))
    preloaded_paths = sorted(str(row["relative_path"]) for row in native_dependencies)
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
    stdlib_manifest_raw: bytes,
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
        if not raw_path.startswith(("/usr/", "/lib/", "/lib64/")):
            raise RuntimeError(
                f"Python module outside admitted system roots: {raw_path}"
            )
        if raw_path.endswith((".pyc", ".pyo")):
            raise RuntimeError(f"system Python bytecode execution rejected: {raw_path}")
        system_module_paths.add(raw_path)
    system_module_rows: list[dict[str, Any]] = []
    for raw_path in sorted(system_module_paths):
        descriptor = os.open(raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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
    strict_python = verify_system_python_provenance(
        phase=phase,
        stdlib_manifest_raw=stdlib_manifest_raw,
        capture_evidence=capture_evidence,
    )
    strict_legacy_rows = [
        {key: row[key] for key in ("path", "sha256", "size", "identity")}
        for row in strict_python["rows"]
    ]
    if strict_legacy_rows != system_module_rows:
        raise RuntimeError("system Python provenance views disagreed")
    return {
        "phase": phase,
        "sealed_package_mappings": sorted(sealed_mapped),
        "sealed_python_mapped": python_mapped,
        "system_runtime": system_rows,
        "system_python_modules": system_module_rows,
        "strict_system_python_provenance": strict_python,
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
    start_modules = {row["path"]: row for row in start["system_python_modules"]}
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
        "new_post_import_python_modules": sorted(set(end_modules) - set(start_modules)),
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
            payload = _pread_all(int(entry["fd"]), maximum_bytes=MAX_RUNTIME_FILE_BYTES)
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
            relative = (
                path.absolute()
                .relative_to(Path(f"/proc/self/fd/{bundle.root_fd}"))
                .as_posix()
            )
        except (OSError, ValueError):
            if "site-packages" in path.parts or "dist-packages" in path.parts:
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
            "unexpected site-packages runtime: " + ",".join(sorted(unexpected))
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
    identity = (
        int(row.st_dev),
        int(row.st_ino),
        stat.S_IMODE(row.st_mode),
        int(row.st_uid),
    )
    expected = tuple(binding.get(key) for key in ("device", "inode", "mode", "uid"))
    if (
        identity != expected
        or not stat.S_ISDIR(row.st_mode)
        or identity[2:] != (0o700, os.getuid())
    ):
        raise RuntimeError("output directory descriptor contract rejected")
    named = os.lstat(path)
    if (
        named.st_dev,
        named.st_ino,
        stat.S_IMODE(named.st_mode),
        named.st_uid,
    ) != identity:
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
    order = tuple(
        name
        for name in (OUTPUT_SOLUTION, OUTPUT_REPORT)
        if name in payloads
    )
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


@dataclass(slots=True)
class PreparedRun:
    modules: dict[str, types.ModuleType]
    problem: Any
    runtime: dict[str, Any]
    runtime_bundle: RuntimeBundleAdmission
    runtime_install: dict[str, Any]
    executing_python: dict[str, Any]
    system_runtime_start: dict[str, Any]
    system_runtime_after_import: dict[str, Any]
    system_runtime_import_comparison: dict[str, Any]


def prepare_run(
    payloads: Mapping[str, bytes],
    capture_evidence: Mapping[str, Any],
    runtime_bundle: RuntimeBundleAdmission,
    executing_python: dict[str, Any],
    system_runtime_start: dict[str, Any],
    runtime_install: dict[str, Any],
    *,
    deadline: float,
) -> PreparedRun:
    modules = load_exact_runtime(payloads)
    semantic = modules["semantic"]
    problem = semantic.parse_itc2019_xml(
        Path(
            f"/proc/self/fd/{json.loads(os.environ[CAPTURE_MANIFEST_ENV])['full_instance']['fd']}"
        )
    )
    class_ids = tuple(row.id for row in problem.classes)
    if (
        len(class_ids) != EXPECTED_CLASS_COUNT
        or len(set(class_ids)) != EXPECTED_CLASS_COUNT
    ):
        raise RuntimeError("official problem class cardinality rejected")
    student_ids = tuple(row.id for row in problem.students)
    if len(student_ids) != EXPECTED_STUDENT_COUNT or len(set(student_ids)) != EXPECTED_STUDENT_COUNT:
        raise RuntimeError("official problem student cardinality rejected")
    runtime = verify_loaded_runtime(payloads, runtime_bundle)
    system_runtime_after_import = mapped_runtime_snapshot(
        runtime_bundle,
        capture_evidence,
        payloads["stdlib_manifest"],
        phase="after_third_party_import",
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
    _resource_guard(deadline, "captured runtime admission")
    return PreparedRun(
        modules,
        problem,
        runtime,
        runtime_bundle,
        runtime_install,
        executing_python,
        system_runtime_start,
        system_runtime_after_import,
        system_runtime_import_comparison,
    )


def _serialize_solution(problem, placements, student_classes) -> bytes:
    by_class = {placement.class_id: placement for placement in placements}
    students_by_class: dict[str, list[str]] = {}
    for student_id, class_ids in student_classes.items():
        for class_id in class_ids:
            students_by_class.setdefault(class_id, []).append(student_id)
    root = ElementTree.Element(
        "solution", {"name": problem.name, "technique": "planora-puproj-v17-fresh"}
    )
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


GENERIC_VALIDATOR_BOOTSTRAP = r'''
import fcntl,hashlib,importlib.abc,importlib.util,json,os,pathlib,stat,sys
ALL=0x0F
def read(fd):
 size=os.fstat(fd).st_size; out=[]; off=0
 while off<size:
  part=os.pread(fd,min(1<<20,size-off),off)
  if not part: raise RuntimeError("short sealed validator read")
  out.append(part); off+=len(part)
 return b"".join(out)
rows=json.loads(sys.argv[1]); sources={}
for name,row in rows.items():
 fd=int(row["fd"]); raw=read(fd); digest=hashlib.sha256(raw).hexdigest()
 if fcntl.fcntl(fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or digest!=row["sha256"]: raise RuntimeError("sealed validator source drift")
 sources[name]=(raw,digest,name=="benchmarks")
class L(importlib.abc.Loader):
 def __init__(self,n,b,h,p): self.n=n; self.b=b; self.h=h; self.p=p
 def create_module(self,s): return None
 def exec_module(self,m):
  m.__file__="sealed:puproj-v17-validator:"+self.n; m.__captured_sha256__=self.h
  if self.p: m.__path__=[]
  exec(compile(self.b,m.__file__,"exec"),m.__dict__)
class F(importlib.abc.MetaPathFinder):
 def find_spec(self,n,path=None,target=None):
  if n not in sources: return None
  b,h,p=sources[n]; return importlib.util.spec_from_loader(n,L(n,b,h,p),is_package=p)
root_fd=int(sys.argv[2]); manifest_fd=int(sys.argv[3]); manifest_expected=sys.argv[4]
manifest_raw=read(manifest_fd)
if fcntl.fcntl(manifest_fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or hashlib.sha256(manifest_raw).hexdigest()!=manifest_expected: raise RuntimeError("validator runtime manifest drift")
manifest=json.loads(manifest_raw); admitted={(int(r["device"]),int(r["inode"])) for r in manifest["entries"]}
root=os.fstat(root_fd)
if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode)!=0o500: raise RuntimeError("validator runtime root rejected")
sys.path.insert(0,f"/proc/self/fd/{root_fd}"); sys.meta_path.insert(0,F())
validator_fd=int(sys.argv[5]); validator_expected=sys.argv[6]; validator=read(validator_fd)
if fcntl.fcntl(validator_fd,getattr(fcntl,"F_GET_SEALS",1034))&ALL!=ALL or hashlib.sha256(validator).hexdigest()!=validator_expected: raise RuntimeError("validator program drift")
stdlib=json.loads(sys.argv[7]); forwarded=sys.argv[8:]; sys.argv=["sealed:puproj-v17-generic-validator",*forwarded]
scope={"__name__":"__main__","__file__":"sealed:puproj-v17-generic-validator","__package__":None}
try: exec(compile(validator,"sealed:puproj-v17-generic-validator","exec"),scope)
except SystemExit as exc: exit_code=0 if exc.code is None else int(exc.code)
unexpected=[]
for module in tuple(sys.modules.values()):
 raw=getattr(module,"__file__",None)
 if not isinstance(raw,str) or raw.startswith(("sealed:","<frozen ","<sealed-runtime:")): continue
 if raw.startswith("/proc/self/fd/"):
  try: row=os.stat(raw)
  except OSError: unexpected.append(raw); continue
  if (int(row.st_dev),int(row.st_ino)) not in admitted: unexpected.append(raw)
  continue
 resolved=os.path.realpath(raw)
 if resolved not in stdlib: unexpected.append(raw); continue
 fd=os.open(resolved,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); value=read(fd); os.close(fd)
 if hashlib.sha256(value).hexdigest()!=stdlib[resolved]: unexpected.append(raw)
if unexpected or "argparse" not in sys.modules: raise RuntimeError("validator runtime provenance rejected:"+",".join(sorted(set(unexpected))))
raise SystemExit(exit_code)
'''


def consume_exclusive_report_fd(
    run_fd: int,
    report_name: str,
    report_fd: int,
    report_created: os.stat_result,
    *,
    maximum_bytes: int = 4 << 20,
) -> bytes:
    """Read only the retained report FD after binding its live name."""

    retained = os.fstat(report_fd)
    named = os.stat(report_name, dir_fd=run_fd, follow_symlinks=False)
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
    report_bytes = _pread_all(report_fd, maximum_bytes=maximum_bytes)
    if int(retained.st_size) != len(report_bytes):
        raise RuntimeError("generic report size contract rejected")
    os.unlink(report_name, dir_fd=run_fd)
    return report_bytes


def _generic_validation(
    prepared: PreparedRun,
    payloads: Mapping[str, bytes],
    capture_evidence: Mapping[str, Any],
    xml_bytes: bytes,
) -> dict[str, Any]:
    del prepared
    stdlib_manifest_hashes = _parse_stdlib_manifest(payloads["stdlib_manifest"])
    instance_fd = int(capture_evidence["full_instance"]["fd"])
    python_fd = int(capture_evidence["python_binary"]["fd"])
    validator_fd = int(capture_evidence["generic_validator"]["fd"])
    bundle = verify_runtime_bundle(load_capture_manifest()[0])
    solution_fd = os.memfd_create(
        "puproj-v17-generic-solution", getattr(os, "MFD_ALLOW_SEALING", 2)
    )
    run_binding = json.loads(os.environ[OUTPUT_BINDING_ENV])
    run_fd = int(run_binding["fd"])
    report_name = f".generic-validation-{uuid.uuid4().hex}.json"
    report_fd = os.open(
        report_name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o400,
        dir_fd=run_fd,
    )
    report_created = os.fstat(report_fd)
    source_rows = {
        "benchmarks": capture_evidence["benchmarks_init"],
        "benchmarks.itc2019": capture_evidence["semantic"],
    }
    pass_fds = {
        instance_fd, python_fd, validator_fd, solution_fd, run_fd, report_fd,
        bundle.root_fd, bundle.manifest_fd,
        *(int(row["fd"]) for row in source_rows.values()),
        *(int(row["fd"]) for row in bundle.entries_by_path.values()),
    }
    try:
        os.write(solution_fd, xml_bytes)
        os.fchmod(solution_fd, 0o400)
        fcntl.fcntl(solution_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        command = [
            f"/proc/self/fd/{python_fd}", "-I", "-S", "-B", "-c",
            GENERIC_VALIDATOR_BOOTSTRAP,
            json.dumps(source_rows, sort_keys=True), str(bundle.root_fd),
            str(bundle.manifest_fd), bundle.manifest_sha256,
            str(validator_fd), EXPECTED_HASHES["generic_validator"],
            json.dumps(stdlib_manifest_hashes, sort_keys=True),
            "--instance", f"/proc/self/fd/{instance_fd}",
            "--solution", f"/proc/self/fd/{solution_fd}",
            "--instance-fd", str(instance_fd), "--solution-fd", str(solution_fd),
            "--expected-instance-sha256", EXPECTED_HASHES["full_instance"],
            "--expected-solution-sha256", sha256(xml_bytes).hexdigest(),
            "--report-fd", str(report_fd),
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=tuple(sorted(pass_fds)),
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "TMPDIR": f"/proc/self/fd/{run_fd}"},
            timeout=30.0,
            check=False,
        )
        hook = GENERIC_REPORT_POST_CHILD_TEST_HOOK
        if hook is not None:
            hook(run_fd, report_name, report_fd)
        report_bytes = consume_exclusive_report_fd(
            run_fd, report_name, report_fd, report_created
        )
        result = json.loads(report_bytes)
    finally:
        try:
            named = os.stat(report_name, dir_fd=run_fd, follow_symlinks=False)
        except FileNotFoundError:
            named = None
        retained = os.fstat(report_fd)
        if named is not None and (named.st_dev, named.st_ino) == (
            retained.st_dev,
            retained.st_ino,
        ):
            os.unlink(report_name, dir_fd=run_fd)
        os.close(report_fd)
        os.close(solution_fd)
    if completed.returncode != 0 or result.get("status") != "COMPLETE_VALID":
        raise RuntimeError("fresh isolated sealed generic validation rejected")
    result["fresh_process_exit_code"] = completed.returncode
    result["fresh_process_isolated"] = True
    result["report_transport"] = "parent_openat_exclusive_retained_fd"
    result["runtime_manifest_sha256"] = bundle.manifest_sha256
    result["process_group_inherited_for_supervisor_union_cleanup"] = True
    return result


def run_frontier() -> tuple[int, dict[str, Any]]:
    started = time.monotonic()
    deadline = started + COOPERATIVE_DEADLINE_SECONDS
    payloads, capture_evidence = load_capture_manifest()
    executing_python = verify_executing_python(payloads, capture_evidence)
    runtime_bundle = verify_runtime_bundle(payloads)
    system_runtime_start = mapped_runtime_snapshot(
        runtime_bundle,
        capture_evidence,
        payloads["stdlib_manifest"],
        phase="before_third_party_import",
    )
    runtime_install = install_sealed_runtime(runtime_bundle)
    prepared = prepare_run(
        payloads,
        capture_evidence,
        runtime_bundle,
        executing_python,
        system_runtime_start,
        runtime_install,
        deadline=deadline,
    )
    semantic = prepared.modules["semantic"]
    stopped: dict[str, int | None] = {"signal": None}
    def receive(signum, _frame):
        stopped["signal"] = int(signum)
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, receive)
    _resource_guard(deadline, "fresh solve admission")
    result = semantic.solve_itc2019_native(
        prepared.problem,
        time_limit_seconds=max(0.001, deadline - time.monotonic() - 20.0),
        workers=1,
        random_seed=109,
        max_pair_matrix_cells=30_000_000,
        max_group_table_rows=2_000_000,
        max_joint_student_conjunctions=2_000_000,
        max_sparse_room_constraints=30_000_000,
        formulation="auto",
    )
    _resource_guard(deadline, "fresh solve return")
    base = {
        "schema": "planora.pu-proj.frontier-joint-v17.fresh-report.v1",
        "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        "checkpoint_or_incumbent_accessed": False,
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
        "expected_class_count": EXPECTED_CLASS_COUNT,
        "expected_student_count": EXPECTED_STUDENT_COUNT,
        "captured_inputs": dict(capture_evidence),
        "fresh_result": {
            key: value for key, value in asdict(result).items()
            if key not in {"placements", "student_classes"}
        },
    }
    if not result.is_feasible or stopped["signal"] is not None:
        report = {
            **base,
            "status": "CONTROLLED_UNKNOWN",
            "admissible_as_solution": False,
            "complete_timetable": False,
            "official_solution_xml_published": False,
        }
        replay_payloads, replay_evidence = load_capture_manifest()
        report["final_runtime_bundle_replay"] = verify_runtime_bundle(replay_payloads).evidence
        report["final_capture_replay"] = replay_evidence
        publication = publish_bundle({OUTPUT_REPORT: _json_bytes(report)})
        return 3, {
            "schema": "planora.pu-proj.frontier-joint-v17-runner.v1",
            "status": "CONTROLLED_UNKNOWN_PUBLISHED",
            "publication": publication,
            "admissible_as_solution": False,
            "official_solution_xml_published": False,
            "elapsed_seconds": time.monotonic() - started,
        }
    placements = tuple(result.placements)
    students = result.student_classes
    if len(placements) != EXPECTED_CLASS_COUNT or len(students) != EXPECTED_STUDENT_COUNT:
        raise RuntimeError("fresh solution cardinality rejected")
    semantic_errors = tuple(semantic.validate_itc2019_solution(prepared.problem, placements, students))
    if semantic_errors:
        raise RuntimeError("fresh semantic validation rejected: " + semantic_errors[0])
    xml_bytes = _serialize_solution(prepared.problem, placements, students)
    solution_fd = os.memfd_create("puproj-v17-local-solution", getattr(os, "MFD_ALLOW_SEALING", 2))
    try:
        os.write(solution_fd, xml_bytes)
        os.fchmod(solution_fd, 0o400)
        fcntl.fcntl(solution_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        parsed = semantic.parse_itc2019_solution(Path(f"/proc/self/fd/{solution_fd}"))
        document_errors = tuple(semantic.validate_itc2019_solution_document(prepared.problem, parsed))
    finally:
        os.close(solution_fd)
    if document_errors:
        raise RuntimeError("fresh document validation rejected: " + document_errors[0])
    generic = _generic_validation(prepared, payloads, capture_evidence, xml_bytes)
    report = {
        **base,
        "status": "COMPLETE_VALID",
        "admissible_as_solution": True,
        "complete_timetable": True,
        "official_solution_xml_published": True,
        "class_count": len(placements),
        "student_count": len(students),
        "local_semantic_errors": [],
        "local_document_errors": [],
        "generic_validation": generic,
    }
    replay_payloads, replay_evidence = load_capture_manifest()
    final_bundle = verify_runtime_bundle(replay_payloads)
    final_loaded_runtime = verify_loaded_runtime(replay_payloads, runtime_bundle)
    final_maps = mapped_runtime_snapshot(
        runtime_bundle,
        capture_evidence,
        replay_payloads["stdlib_manifest"],
        phase="final_feasible",
    )
    if not set(runtime_install["native_dependency_paths"]).issubset(
        set(final_maps["sealed_package_mappings"])
    ):
        raise RuntimeError("sealed native mapping disappeared before publication")
    report["final_system_runtime"] = final_maps
    report["final_system_runtime_comparison"] = compare_system_runtime_snapshots(
        system_runtime_start, final_maps
    )
    report["post_import_system_runtime_final_comparison"] = (
        compare_system_runtime_snapshots(
            prepared.system_runtime_after_import, final_maps
        )
    )
    report["final_loaded_runtime_replay"] = final_loaded_runtime
    report["final_runtime_bundle_replay"] = final_bundle.evidence
    report["final_capture_replay"] = replay_evidence
    _resource_guard(deadline, "final capture replay")
    report["final_capture_replay"] = replay_evidence
    report_bytes = _json_bytes(report)
    publication = publish_bundle(
        {
            OUTPUT_SOLUTION: xml_bytes,
            OUTPUT_REPORT: report_bytes,
        }
    )
    _resource_guard(deadline, "post-publication acceptance")
    return 0, {
        "schema": "planora.pu-proj.frontier-joint-v17-runner.v1",
        "status": "COMPLETE_VALID_PUBLISHED",
        "class_count": EXPECTED_CLASS_COUNT,
        "student_count": EXPECTED_STUDENT_COUNT,
        "admissible_as_solution": True,
        "official_solution_xml_published": True,
        "publication": publication,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }


def self_test() -> dict[str, Any]:
    if OUTPUT_REPORT != "runner-report.json":
        raise AssertionError("report-last publication name drifted")
    return {
        "status": "PASS",
        "expected_class_count": EXPECTED_CLASS_COUNT,
        "expected_student_count": EXPECTED_STUDENT_COUNT,
        "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        "checkpoint_or_incumbent_accessed": False,
        "cooperative_deadline_seconds": COOPERATIVE_DEADLINE_SECONDS,
        "runner_rss_ceiling_kib": RUNNER_RSS_CEILING_KIB,
        "publication": "private_dirfd_transaction_report_last",
        "admissible_as_solution": "only_after_local_and_generic_validation",
        "official_instance_opened": False,
        "solver_execution_started": False,
        "official_solution_xml_published": False,
    }


def run_sealed_import_probe() -> dict[str, Any]:
    started = time.monotonic()
    payloads, capture_evidence = load_capture_manifest(include_official=False)
    if "full_instance" in payloads or "full_instance" in capture_evidence:
        raise RuntimeError("probe official-input capture rejected")
    executing_python = verify_executing_python(payloads, capture_evidence)
    runtime_bundle = verify_runtime_bundle(payloads)
    system_runtime_start = mapped_runtime_snapshot(
        runtime_bundle,
        capture_evidence,
        payloads["stdlib_manifest"],
        phase="probe_before_third_party_import",
    )
    runtime_install = install_sealed_runtime(runtime_bundle)
    load_exact_runtime(payloads)
    imported: list[dict[str, str]] = []
    for label in sorted(EXPECTED_HASHES):
        if not label.startswith("itc2019_"):
            continue
        module = importlib.import_module(f"benchmarks.{label}")
        imported.append(
            {
                "module": f"benchmarks.{label}",
                "sha256": str(getattr(module, "__captured_sha256__", "")),
            }
        )
    runtime = verify_loaded_runtime(payloads, runtime_bundle)
    system_runtime_end = mapped_runtime_snapshot(
        runtime_bundle,
        capture_evidence,
        payloads["stdlib_manifest"],
        phase="probe_after_third_party_import",
    )
    comparison = compare_system_runtime_snapshots(
        system_runtime_start, system_runtime_end
    )
    return {
        "schema": "planora.puproj.frontier-joint-v17-sealed-import-probe-child.v1",
        "status": "PASS",
        "elapsed_seconds": time.monotonic() - started,
        "executing_python": executing_python,
        "runtime_bundle": runtime_bundle.evidence,
        "runtime_install": runtime_install,
        "loaded_runtime": runtime,
        "system_runtime_comparison": comparison,
        "imported_planora_modules": imported,
        "imported_planora_module_count": len(imported),
        "official_instance_opened": False,
        "checkpoint_or_incumbent_opened": False,
        "solver_execution_started": False,
        "solver_child_process_started": False,
        "probe_child_process_started": True,
        "solve_call_count": 0,
        "official_solution_xml_published": False,
    }


def main() -> int:
    if not isinstance(globals().get("__captured_sha256__"), str):
        raise SystemExit("direct PU-PROJ v17 runner execution rejected")
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-frontier", action="store_true")
    parser.add_argument("--allow-official-input", action="store_true")
    parser.add_argument("--allow-solver", action="store_true")
    parser.add_argument("--allow-publication", action="store_true")
    parser.add_argument("--sealed-import-probe", action="store_true")
    args = parser.parse_args()
    if args.sealed_import_probe:
        if any(
            (
                args.execute_frontier,
                args.allow_official_input,
                args.allow_solver,
                args.allow_publication,
            )
        ):
            raise SystemExit("probe rejects solve/publication gates")
        result = run_sealed_import_probe()
        result["runner_sha256_start"] = globals()["__captured_sha256__"]
        result["runner_sha256_end"] = globals()["__captured_sha256__"]
        result["runner_hash_stable"] = True
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        return 0
    if not all(
        (
            args.execute_frontier,
            args.allow_official_input,
            args.allow_solver,
            args.allow_publication,
        )
    ):
        raise SystemExit("all irreversible PU-PROJ fresh-solve gates are required")
    exit_code, result = run_frontier()
    result["runner_sha256_start"] = globals()["__captured_sha256__"]
    result["runner_sha256_end"] = globals()["__captured_sha256__"]
    result["runner_hash_stable"] = True
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
