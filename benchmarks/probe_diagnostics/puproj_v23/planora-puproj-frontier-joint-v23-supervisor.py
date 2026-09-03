#!/usr/bin/env python3
"""PU-PROJ v23 control plane with bounded decomposed model construction."""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
from datetime import UTC, datetime
import errno
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import resource
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping
import uuid


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
ARTIFACT_ROOT = ROOT / "benchmarks/probe_diagnostics/puproj_v23"
SITE_PACKAGES = ROOT / ".venv/lib/python3.12/site-packages"
RUNNER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-runner.py"
FULL_INSTANCE = (
    ROOT
    / "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/pu-proj-fal19.xml"
)
SEMANTIC = ROOT / "benchmarks/itc2019.py"
PREPROCESSING = ROOT / "benchmarks/itc2019_preprocessing.py"
ROOM = ROOT / "benchmarks/itc2019_room_oracle.py"
BENCHMARKS_INIT = ROOT / "benchmarks/__init__.py"
BENCHMARKS_CORPUS = ROOT / "benchmarks/corpus.py"
GENERIC_VALIDATOR = (
    ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-generic-validator.py"
)
STDLIB_MANIFEST = (
    ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-stdlib.sha256"
)
PLANORA_FRESH_MODULES = {
    name: ROOT / f"benchmarks/{name}.py"
    for name in (
        "itc2019_compact_joint", "itc2019_corpus", "itc2019_decomposed",
        "itc2019_decomposed_quality", "itc2019_factorized",
        "itc2019_generalized_occurrences", "itc2019_global_components",
        "itc2019_global_quality", "itc2019_grouped_calendar",
        "itc2019_resource_seed", "itc2019_sparse_joint", "itc2019_structural",
        "itc2019_violation_lns",
    )
}
PYTHON_BINARY = Path("/usr/bin/python3.12")
RUNTIME_RECORDS = {
    "runtime_ortools_record": ROOT
    / ".venv/lib/python3.12/site-packages/ortools-9.15.6755.dist-info/RECORD",
    "runtime_numpy_record": ROOT
    / ".venv/lib/python3.12/site-packages/numpy-2.4.2.dist-info/RECORD",
    "runtime_pandas_record": ROOT
    / ".venv/lib/python3.12/site-packages/pandas-3.0.1.dist-info/RECORD",
    "runtime_dateutil_record": ROOT
    / ".venv/lib/python3.12/site-packages/python_dateutil-2.9.0.post0.dist-info/RECORD",
    "runtime_six_record": ROOT
    / ".venv/lib/python3.12/site-packages/six-1.17.0.dist-info/RECORD",
    "runtime_lxml_record": ROOT
    / ".venv/lib/python3.12/site-packages/lxml-6.1.0.dist-info/RECORD",
    "runtime_absl_record": ROOT
    / ".venv/lib/python3.12/site-packages/absl_py-2.4.0.dist-info/RECORD",
    "runtime_immutabledict_record": ROOT
    / ".venv/lib/python3.12/site-packages/immutabledict-4.3.1.dist-info/RECORD",
    "runtime_protobuf_record": ROOT
    / ".venv/lib/python3.12/site-packages/protobuf-6.33.5.dist-info/RECORD",
    "runtime_typing_extensions_record": ROOT
    / ".venv/lib/python3.12/site-packages/typing_extensions-4.15.0.dist-info/RECORD",
}

# Replaced exactly once after the runner is frozen.
EXPECTED_RUNNER_SHA256 = (
    "cbeb81184ff3df1fd10610d885acde26b1a8717c952a7d40080398d3961681b1"
)
CP_MODEL_SOURCE_PATH = "ortools/sat/python/cp_model.py"
CP_MODEL_SOURCE_SHA256 = (
    "b5f2a3ae5c418d11af23cb77a766fa10103c8bb71703dafa1ecad74823603f25"
)
CP_MODEL_COMPILE_WARNING_MESSAGE = (
    "Bitwise inversion '~' on bool is deprecated. This returns the bitwise "
    "inversion of the underlying int object and is usually not what you expect "
    "from negating a bool. Use the 'not' operator for boolean negation or "
    "~int(x) if you really want the bitwise inversion of the underlying int."
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
    "itc2019_decomposed": "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
    "itc2019_decomposed_quality": "534622d096728ff4e4e9b53fd8d58ec3827ec09540d4c95a3e3dcad271c7f78b",
    "itc2019_factorized": "a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf",
    "itc2019_generalized_occurrences": "7ed4224c0f338f9f983a358babb5dfdb6b90d5026383283cd0d805aef733d85f",
    "itc2019_global_components": "c2d158dc9434f8da4f3e9478b1526face365702cf317fd14e693af75769e7f11",
    "itc2019_global_quality": "397d308a4fb368aaab96db1789394e1b9f289a8f6b8d87b9ce5b4a569f8ccc7f",
    "itc2019_grouped_calendar": "37b82b7f01fb47a655bb76ae0d6734315b00bf58ec7ebf28c66bb701c00a6ee5",
    "itc2019_resource_seed": "8d497bc609ec5b717b0d9e2b77406e89c45c6eaef378148c0bebadd6a429d665",
    "itc2019_sparse_joint": "2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2",
    "itc2019_structural": "db4ac0adbfe38f1b618b2e8f7a5a9e5a613000a62034017819cca2c20640d024",
    "itc2019_violation_lns": "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343",
    "generic_validator": "431a6d1260dbc491c540fa3bef85f188a3728fb00a578a4f243473e56a1c8037",
    "python_binary": "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273",
    "stdlib_manifest": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
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
CAPTURE_SOURCES = {
    "runner": RUNNER,
    "full_instance": FULL_INSTANCE,
    "semantic": SEMANTIC,
    "preprocessing": PREPROCESSING,
    "room": ROOM,
    "benchmarks_init": BENCHMARKS_INIT,
    "benchmarks_corpus": BENCHMARKS_CORPUS,
    "generic_validator": GENERIC_VALIDATOR,
    **PLANORA_FRESH_MODULES,
    "python_binary": PYTHON_BINARY,
    "stdlib_manifest": STDLIB_MANIFEST,
    **RUNTIME_RECORDS,
}

CAPTURE_MANIFEST_ENV = "PUPROJ_FRONTIER_V19_CAPTURE_MANIFEST"
OUTPUT_BINDING_ENV = "PUPROJ_FRONTIER_V19_OUTPUT_BINDING"
RUNTIME_BUNDLE_ENV = "PUPROJ_FRONTIER_V19_RUNTIME_BUNDLE"
PYCACHE_PREFIX_ENV = "PUPROJ_FRONTIER_V19_PYCACHE_PREFIX"
EXTERNAL_LOADER_PROTOCOL = "planora.puproj.frontier-v19-supervisor-loader.v1"
RUNNER_LOADER_PROTOCOL = "planora.puproj.frontier-v19-runner-loader.v1"
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)
LAUNCH_MIN_MEM_AVAILABLE_KIB = 1_500_000
INITIAL_MIN_MEM_AVAILABLE_KIB = 1_900_000
RUNTIME_MIN_MEM_AVAILABLE_KIB = 450_000
PROCESS_GROUP_RSS_LIMIT_KIB = 1_550_000
PROCESS_GROUP_VMSWAP_LIMIT_KIB = 131_072
ADDRESS_SPACE_CAP_BYTES = 2_800_000_000
CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS = 300.0
SUPERVISOR_HARD_WALL_SECONDS = 330.0
PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB = 1_900_000
PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB = 600_000
PROBE_PROCESS_GROUP_RSS_LIMIT_KIB = 1_200_000
PROBE_PROCESS_GROUP_VMSWAP_LIMIT_KIB = 131_072
PROBE_WHOLE_LAUNCH_MEMORY_LIMIT_KIB = 1_300_000
PROBE_HARD_WALL_SECONDS = 180.0
PROBE_CAPTURE_MAX_BYTES = 64 << 20
PROBE_DIAGNOSTIC_TAIL_BYTES = 4 << 10
POLL_SECONDS = 0.10
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
PR_SET_PDEATHSIG = 1
PR_SET_CHILD_SUBREAPER = 36
PARENT_DEATH_SIGNAL = signal.SIGKILL
AT_FDCWD = -100
RENAME_NOREPLACE = 1
LIBC = ctypes.CDLL(None, use_errno=True)
SYSTEM_PYTHON_ROOT = Path("/usr/lib/python3.12")
SYSTEM_PYTHON_OWNER_UID = 65_534
EXPECTED_STDLIB_MANIFEST_SHA256 = EXPECTED_HASHES["stdlib_manifest"]
EXPECTED_STDLIB_MANIFEST_FILES = 619
EXPECTED_ARGPARSE_PATH = SYSTEM_PYTHON_ROOT / "argparse.py"
EXPECTED_ARGPARSE_SHA256 = (
    "29395feb61bc376ca4ff9d44069af8d914ec2a1f25a4bd7978f6e2afef5bc07f"
)
BOOTSTRAP_PYCACHE_PREFIX = Path(
    "/tmp/planora-puproj-frontier-joint-v19-bootstrap-pycache"
)
EXPECTED_SUPERVISOR_SYS_PATH = (
    "/usr/lib/python312.zip",
    "/usr/lib/python3.12",
    "/usr/lib/python3.12/lib-dynload",
)
WHOLE_LAUNCH_MEMORY_LIMIT_KIB = 1_600_000
POST_KILL_REAP_TIMEOUT_SECONDS = 5.0
POST_POPEN_ADMISSION_TEST_HOOK = None

RUNNER_FD_LOADER = r"""
import fcntl, hashlib, json, os, stat, sys
fd = int(sys.argv[1]); expected = sys.argv[2]; runtime_root_fd = int(sys.argv[3]); barrier_fd = int(sys.argv[4]); forwarded = sys.argv[5:]
if os.read(barrier_fd, 1) != b"G": raise RuntimeError("parent start barrier rejected")
os.close(barrier_fd)
required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
stable = lambda row: (int(row.st_dev), int(row.st_ino), int(row.st_size), stat.S_IFMT(row.st_mode), stat.S_IMODE(row.st_mode), int(row.st_uid), int(row.st_nlink))
before = os.fstat(fd); identity = stable(before); seals = int(fcntl.fcntl(fd, fcntl.F_GET_SEALS))
if not stat.S_ISREG(before.st_mode) or seals & required != required: raise RuntimeError("runner capture contract rejected")
parts=[]; offset=0
while offset < before.st_size:
    block=os.pread(fd,min(1<<20,before.st_size-offset),offset)
    if not block: raise RuntimeError("runner capture ended early")
    parts.append(block); offset += len(block)
after=os.fstat(fd)
if stable(after) != identity or int(fcntl.fcntl(fd, fcntl.F_GET_SEALS)) != seals: raise RuntimeError("runner capture drift")
source=b"".join(parts); actual=hashlib.sha256(source).hexdigest()
if actual != expected: raise RuntimeError("runner captured hash mismatch")
runtime_binding=json.loads(os.environ["PUPROJ_FRONTIER_V19_RUNTIME_BUNDLE"]); runtime_row=os.fstat(runtime_root_fd)
runtime_identity=(int(runtime_row.st_dev),int(runtime_row.st_ino),stat.S_IMODE(runtime_row.st_mode),int(runtime_row.st_uid))
if runtime_binding.get("root_fd") != runtime_root_fd or tuple(runtime_binding.get("root_identity",())) != runtime_identity or not stat.S_ISDIR(runtime_row.st_mode) or runtime_identity[2:] != (0o500,os.getuid()): raise RuntimeError("sealed runtime root binding rejected")
if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode: raise RuntimeError("Python isolation flags rejected")
sys.path.insert(0,f"/proc/self/fd/{runtime_root_fd}")
sys.dont_write_bytecode=True; filename=f"<sealed-puproj-frontier-v19-runner:{actual}>"; sys.argv=[filename,*forwarded]
namespace={"__name__":"__main__","__file__":filename,"__package__":None,"__cached__":None,"__captured_sha256__":actual,"__runner_loader_protocol__":"planora.puproj.frontier-v19-runner-loader.v1"}
exec(compile(source,filename,"exec",dont_inherit=True),namespace)
"""


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


def _load_named_stdlib_manifest() -> tuple[dict[str, str], dict[str, Any]]:
    parent_fd = os.open(
        STDLIB_MANIFEST.parent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor = -1
    try:
        parent_before = os.fstat(parent_fd)
        descriptor = os.open(
            STDLIB_MANIFEST.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        raw = _pread_stable(descriptor, maximum_bytes=128 << 10)
        after = os.fstat(descriptor)
        named = os.stat(
            STDLIB_MANIFEST.name, dir_fd=parent_fd, follow_symlinks=False
        )
        parent_after = os.fstat(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)
    if (
        not stat.S_ISREG(after.st_mode)
        or after.st_nlink != 1
        or _stable_identity(before) != _stable_identity(after)
        or _stable_identity(after) != _stable_identity(named)
        or (parent_before.st_dev, parent_before.st_ino)
        != (parent_after.st_dev, parent_after.st_ino)
    ):
        raise RuntimeError("stdlib manifest stable named-source contract rejected")
    hashes = _parse_stdlib_manifest(raw)
    return hashes, {
        "path": str(STDLIB_MANIFEST),
        "sha256": EXPECTED_STDLIB_MANIFEST_SHA256,
        "size": len(raw),
        "file_count": len(hashes),
        "source_identity": list(_stable_identity(after)),
        "transport": "stable_named_source_before_supervisor_sealed_capture",
    }


def _hash_stable_system_file(
    path: Path,
    manifest_hashes: Mapping[str, str],
    *,
    maximum_bytes: int = 64 << 20,
) -> dict[str, Any]:
    raw_path = str(path)
    try:
        relative = path.relative_to(SYSTEM_PYTHON_ROOT)
    except ValueError as error:
        raise RuntimeError(
            f"system Python path outside frozen root: {raw_path}"
        ) from error
    if not relative.parts or ".." in relative.parts or path.suffix in {".pyc", ".pyo"}:
        raise RuntimeError(f"system Python path rejected: {raw_path}")
    if os.path.realpath(raw_path) != raw_path:
        raise RuntimeError(f"system Python symlink path rejected: {raw_path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"system Python ownership/mode drift: {raw_path}")
        raw = _pread_stable(descriptor, maximum_bytes=maximum_bytes)
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


def verify_system_python_provenance(*, phase: str) -> dict[str, Any]:
    manifest_hashes, manifest_evidence = _load_named_stdlib_manifest()
    if (
        not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or sys.pycache_prefix != str(BOOTSTRAP_PYCACHE_PREFIX)
        or BOOTSTRAP_PYCACHE_PREFIX.exists()
        or tuple(sys.path) != EXPECTED_SUPERVISOR_SYS_PATH
    ):
        raise RuntimeError(
            "supervisor Python isolation/private-pycache contract rejected"
        )
    argparse_path = getattr(argparse, "__file__", None)
    if argparse_path != str(EXPECTED_ARGPARSE_PATH):
        raise RuntimeError("real frozen argparse module was not loaded")
    rows: dict[str, dict[str, Any]] = {}
    for module in tuple(sys.modules.values()):
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        if raw_path.startswith(("<sealed-puproj-", "<captured-puproj-")):
            continue
        if not raw_path.startswith("/"):
            raise RuntimeError(
                f"arbitrary relative Python module path rejected: {raw_path}"
            )
        row = _hash_stable_system_file(Path(raw_path), manifest_hashes)
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
    return {
        "phase": phase,
        "system_python_root": str(SYSTEM_PYTHON_ROOT),
        "system_python_owner_uid": SYSTEM_PYTHON_OWNER_UID,
        "argparse_path": str(EXPECTED_ARGPARSE_PATH),
        "argparse_sha256": EXPECTED_ARGPARSE_SHA256,
        "private_pycache_prefix": str(BOOTSTRAP_PYCACHE_PREFIX),
        "live_pyc_rejected": True,
        "rows": ordered,
        "row_count": len(ordered),
        "stdlib_manifest": manifest_evidence,
        "stdlib_manifest_sha256": EXPECTED_STDLIB_MANIFEST_SHA256,
        "stdlib_manifest_file_count": len(manifest_hashes),
        "imported_subset_sha256": sha256(
            json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "imported_subset_file_count": len(ordered),
    }


def compare_system_python_provenance(
    start: Mapping[str, Any], end: Mapping[str, Any]
) -> dict[str, Any]:
    start_rows = {row["path"]: row for row in start["rows"]}
    end_rows = {row["path"]: row for row in end["rows"]}
    for path, row in start_rows.items():
        if end_rows.get(path) != row:
            raise RuntimeError(f"supervisor system Python provenance changed: {path}")
    return {
        "start_row_count": len(start_rows),
        "end_row_count": len(end_rows),
        "start_subset_stable": True,
        "new_admitted_rows": sorted(set(end_rows) - set(start_rows)),
    }


def _expected_hash(label: str) -> str:
    return EXPECTED_RUNNER_SHA256 if label == "runner" else EXPECTED_HASHES[label]


def supervisor_execution_sha256() -> str:
    value = globals().get("__captured_sha256__")
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RuntimeError("supervisor captured execution hash missing")
    return value


def verify_current_supervisor_contract() -> tuple[int, ...]:
    binding = globals().get("__external_supervisor_binding__")
    path_value = globals().get("__external_supervisor_path__")
    if not isinstance(binding, dict) or not isinstance(path_value, str):
        raise RuntimeError("external supervisor path binding missing")
    path = Path(path_value)
    current = os.lstat(path)
    identity = (
        *_stable_identity(current),
        int(current.st_mtime_ns),
        int(current.st_ctime_ns),
    )
    keys = (
        "device",
        "inode",
        "size",
        "file_type",
        "mode",
        "uid",
        "nlink",
        "mtime_ns",
        "ctime_ns",
    )
    if tuple(binding.get(key) for key in keys) != identity:
        raise RuntimeError("supervisor current path contract drift")
    if binding.get("sha256") != supervisor_execution_sha256():
        raise RuntimeError("supervisor current hash binding drift")
    if not stat.S_ISREG(current.st_mode):
        raise RuntimeError("supervisor current path is not regular")
    sealed_fd = binding.get("sealed_fd")
    if type(sealed_fd) is not int:
        raise RuntimeError("sealed supervisor descriptor binding missing")
    sealed = os.fstat(sealed_fd)
    sealed_raw = _pread_stable(sealed_fd, maximum_bytes=1 << 20)
    sealed_seals = int(fcntl.fcntl(sealed_fd, fcntl.F_GET_SEALS))
    if (
        sealed_seals & REQUIRED_SEALS != REQUIRED_SEALS
        or binding.get("sealed_seals") != sealed_seals
        or sha256(sealed_raw).hexdigest() != supervisor_execution_sha256()
        or len(sealed_raw) != int(sealed.st_size)
    ):
        raise RuntimeError("sealed supervisor execution descriptor replay rejected")
    return identity


def verify_external_launcher_contract() -> dict[str, Any]:
    binding = globals().get("__external_launcher_binding__")
    if not isinstance(binding, dict):
        raise RuntimeError("external sealed launcher binding missing")
    descriptor = binding.get("fd")
    watch_fd = binding.get("source_watch_fd")
    path_value = binding.get("path")
    if (
        type(descriptor) is not int
        or type(watch_fd) is not int
        or not isinstance(path_value, str)
    ):
        raise RuntimeError("external sealed launcher descriptor binding rejected")
    before = os.fstat(descriptor)
    raw = _pread_stable(descriptor, maximum_bytes=1 << 20)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    source = os.lstat(path_value)
    source_identity = (
        int(source.st_dev),
        int(source.st_ino),
        int(source.st_size),
        stat.S_IFMT(source.st_mode),
        stat.S_IMODE(source.st_mode),
        int(source.st_uid),
        int(source.st_nlink),
        int(source.st_mtime_ns),
        int(source.st_ctime_ns),
    )
    try:
        mutation_events = os.read(watch_fd, 65_536)
    except BlockingIOError:
        mutation_events = b""
    if (
        seals & REQUIRED_SEALS != REQUIRED_SEALS
        or tuple(binding.get("source_identity", ())) != source_identity
        or binding.get("sha256") != sha256(raw).hexdigest()
        or binding.get("device") != int(before.st_dev)
        or binding.get("inode") != int(before.st_ino)
        or binding.get("size") != int(before.st_size)
        or binding.get("seals") != seals
        or binding.get("transport")
        != "native_bootstrap_sealed_memfd_before_launcher_execution"
        or mutation_events
    ):
        raise RuntimeError("external launcher sealed/source/mutation replay rejected")
    return {
        "path": path_value,
        "sha256": binding["sha256"],
        "source_identity": list(source_identity),
        "sealed_device": int(before.st_dev),
        "sealed_inode": int(before.st_ino),
        "sealed_size": int(before.st_size),
        "seals": seals,
        "mutation_watch_clear": True,
        "transport": binding["transport"],
        "bootstrap_sha256": binding.get("bootstrap_sha256"),
    }


def verify_external_freeze_manifest_contract() -> dict[str, Any]:
    binding = globals().get("__external_freeze_manifest_binding__")
    if not isinstance(binding, dict):
        raise RuntimeError("external freeze-manifest binding missing")
    descriptor = binding.get("fd")
    path_value = binding.get("path")
    if type(descriptor) is not int or not isinstance(path_value, str):
        raise RuntimeError("external freeze-manifest descriptor binding rejected")
    before = os.fstat(descriptor)
    raw = _pread_stable(descriptor, maximum_bytes=1 << 20)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    named = os.lstat(path_value)
    named_identity = (
        int(named.st_dev),
        int(named.st_ino),
        int(named.st_size),
        stat.S_IFMT(named.st_mode),
        stat.S_IMODE(named.st_mode),
        int(named.st_uid),
        int(named.st_nlink),
        int(named.st_mtime_ns),
        int(named.st_ctime_ns),
    )
    payload = json.loads(raw.decode("utf-8"))
    if (
        seals & REQUIRED_SEALS != REQUIRED_SEALS
        or tuple(binding.get("source_identity", ())) != named_identity
        or binding.get("sha256") != sha256(raw).hexdigest()
        or binding.get("device") != int(before.st_dev)
        or binding.get("inode") != int(before.st_ino)
        or binding.get("size") != int(before.st_size)
        or binding.get("seals") != seals
        or binding.get("transport")
        != "native_bootstrap_sealed_memfd_before_target_execution"
        or payload.get("native_bootstrap_protocol")
        != "planora.native-sealed-python-bootstrap.v1"
    ):
        raise RuntimeError("external freeze-manifest sealed/source replay rejected")
    return {
        "path": path_value,
        "sha256": binding["sha256"],
        "source_identity": list(named_identity),
        "sealed_device": int(before.st_dev),
        "sealed_inode": int(before.st_ino),
        "sealed_size": int(before.st_size),
        "seals": seals,
        "transport": binding["transport"],
        "protocol": payload["native_bootstrap_protocol"],
    }


def _read_key_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if ":" in line:
            key, raw = line.split(":", 1)
        else:
            fields = line.split(None, 1)
            if len(fields) != 2:
                continue
            key, raw = fields
        match = re.search(r"-?[0-9]+", raw)
        if match:
            values[key] = int(match.group(0))
    return values


def host_sample() -> dict[str, int]:
    memory = _read_key_values(Path("/proc/meminfo"))
    vmstat = _read_key_values(Path("/proc/vmstat"))
    return {
        "mem_available_kib": memory["MemAvailable"],
        "swap_free_kib": memory["SwapFree"],
        "pswpin_pages": vmstat.get("pswpin", 0),
        "pswpout_pages": vmstat.get("pswpout", 0),
    }


def breach_reason(
    *,
    elapsed: float,
    group_rss_kib: int,
    group_vmswap_kib: int,
    sample: Mapping[str, int],
    launch: bool,
) -> str | None:
    floor = LAUNCH_MIN_MEM_AVAILABLE_KIB if launch else RUNTIME_MIN_MEM_AVAILABLE_KIB
    if sample["mem_available_kib"] < floor:
        return "host_mem_available_floor"
    if group_rss_kib >= PROCESS_GROUP_RSS_LIMIT_KIB:
        return "process_group_rss_limit"
    if group_vmswap_kib >= PROCESS_GROUP_VMSWAP_LIMIT_KIB:
        return "process_group_vmswap_limit"
    if elapsed >= SUPERVISOR_HARD_WALL_SECONDS:
        return "supervisor_hard_wall"
    return None


def _process_identity(pid: int) -> tuple[int, int, int, int] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    close = raw.rfind(")")
    fields = raw[close + 2 :].split()
    if len(fields) <= 19:
        return None
    return int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19])


def _process_group_from_stat(path: Path) -> int | None:
    try:
        pid = int(path.parent.name)
    except ValueError:
        return None
    identity = _process_identity(pid)
    return identity[1] if identity is not None else None


def process_group_usage(process_group: int) -> tuple[int, int, tuple[int, ...]]:
    rss = 0
    swap = 0
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if (
            not entry.name.isdigit()
            or _process_group_from_stat(entry / "stat") != process_group
        ):
            continue
        try:
            status = _read_key_values(entry / "status")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        pids.append(int(entry.name))
        rss += status.get("VmRSS", 0)
        swap += status.get("VmSwap", 0)
    return rss, swap, tuple(sorted(pids))


def whole_launch_usage(
    supervisor_pid: int, process_group: int | None
) -> tuple[int, int, tuple[int, ...]]:
    """Union supervisor and child-PGID PIDs, counting every PID exactly once."""
    pids: set[int] = {supervisor_pid}
    if process_group is not None:
        _child_rss, _child_swap, child_pids = process_group_usage(process_group)
        pids.update(child_pids)
    rss = 0
    swap = 0
    admitted: list[int] = []
    for pid in sorted(pids):
        try:
            status = _read_key_values(Path(f"/proc/{pid}/status"))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        admitted.append(pid)
        rss += status.get("VmRSS", 0)
        swap += status.get("VmSwap", 0)
    return rss, swap, tuple(admitted)


def whole_launch_breach(rss_kib: int, vmswap_kib: int) -> str | None:
    if rss_kib + vmswap_kib >= WHOLE_LAUNCH_MEMORY_LIMIT_KIB:
        return "whole_launch_vmrss_plus_vmswap_limit"
    return None


def probe_breach(
    *, elapsed: float, group_rss_kib: int, group_vmswap_kib: int,
    whole_rss_kib: int, whole_vmswap_kib: int, sample: Mapping[str, int]
) -> str | None:
    if sample["mem_available_kib"] < PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB:
        return "probe_runtime_memavailable_floor"
    if group_rss_kib >= PROBE_PROCESS_GROUP_RSS_LIMIT_KIB:
        return "probe_process_group_rss_limit"
    if group_vmswap_kib >= PROBE_PROCESS_GROUP_VMSWAP_LIMIT_KIB:
        return "probe_process_group_vmswap_limit"
    if whole_rss_kib + whole_vmswap_kib >= PROBE_WHOLE_LAUNCH_MEMORY_LIMIT_KIB:
        return "probe_whole_launch_vmrss_plus_vmswap_limit"
    if elapsed >= PROBE_HARD_WALL_SECONDS:
        return "probe_hard_wall"
    return None


def _probe_check_deadline(deadline: float, phase: str) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"probe absolute deadline exceeded: {phase}")


def _probe_elapsed(deadline: float) -> float:
    return max(0.0, time.monotonic() - (deadline - PROBE_HARD_WALL_SECONDS))


def _stream_capture(
    path: Path, expected: str, label: str, *, probe_deadline: float | None = None
) -> tuple[int, dict[str, Any]]:
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, f"capture:{label}:before")
    parent_before = os.lstat(path.parent)
    if not stat.S_ISDIR(parent_before.st_mode):
        raise RuntimeError(f"capture parent {label} is not a directory")
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    )
    source_fd = -1
    target_fd = -1
    try:
        parent_opened = os.fstat(parent_fd)
        source_fd = os.open(
            path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd
        )
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode) or source_before.st_nlink != 1:
            raise RuntimeError(f"capture source {label} contract rejected")
        target_fd = os.memfd_create(
            f"puproj-v19-{label}", getattr(os, "MFD_ALLOW_SEALING", 0x0002)
        )
        digest = sha256()
        offset = 0
        while offset < source_before.st_size:
            if probe_deadline is not None:
                _probe_check_deadline(probe_deadline, f"capture:{label}:read")
            block = os.pread(
                source_fd, min(1 << 20, source_before.st_size - offset), offset
            )
            if not block:
                raise RuntimeError(f"capture source {label} ended early")
            digest.update(block)
            view = memoryview(block)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise RuntimeError(
                        f"capture target {label} stopped accepting bytes"
                    )
                view = view[written:]
            offset += len(block)
        source_after = os.fstat(source_fd)
        named_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.lstat(path.parent)
        if _stable_identity(source_before) != _stable_identity(
            source_after
        ) or _stable_identity(source_after) != _stable_identity(named_after):
            raise RuntimeError(f"capture source {label} identity drift")
        if (parent_opened.st_dev, parent_opened.st_ino) != (
            parent_before.st_dev,
            parent_before.st_ino,
        ) or (parent_after.st_dev, parent_after.st_ino) != (
            parent_before.st_dev,
            parent_before.st_ino,
        ):
            raise RuntimeError(f"capture parent {label} identity drift")
        actual = digest.hexdigest()
        if actual != expected:
            raise RuntimeError(f"capture source {label} hash drift: {actual}")
        os.lseek(target_fd, 0, os.SEEK_SET)
        os.fchmod(target_fd, 0o500 if label == "python_binary" else 0o400)
        fcntl.fcntl(target_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        sealed = os.fstat(target_fd)
        seals = int(fcntl.fcntl(target_fd, fcntl.F_GET_SEALS))
        evidence = {
            "label": label,
            "path": str(path),
            "fd": target_fd,
            "sha256": actual,
            "expected_sha256": expected,
            "device": int(sealed.st_dev),
            "inode": int(sealed.st_ino),
            "size": int(sealed.st_size),
            "file_type": stat.S_IFMT(sealed.st_mode),
            "mode": stat.S_IMODE(sealed.st_mode),
            "uid": int(sealed.st_uid),
            "nlink": int(sealed.st_nlink),
            "seals": seals,
            "required_seals": REQUIRED_SEALS,
            "source_identity": list(_stable_identity(source_after)),
            "source_parent_identity": [
                int(parent_after.st_dev),
                int(parent_after.st_ino),
                stat.S_IMODE(parent_after.st_mode),
                int(parent_after.st_uid),
            ],
            "transport": "sealed_memfd",
        }
        target_fd = -1
        if probe_deadline is not None:
            _probe_check_deadline(probe_deadline, f"capture:{label}:after")
        return int(evidence["fd"]), evidence
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(parent_fd)


def verify_sealed_capture(
    descriptor: int, evidence: Mapping[str, Any], *, probe_deadline: float | None = None
) -> dict[str, Any]:
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, f"capture_replay:{evidence.get('label')}:before")
    before = os.fstat(descriptor)
    identity = _stable_identity(before)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    digest = sha256()
    offset = 0
    while offset < before.st_size:
        if probe_deadline is not None:
            _probe_check_deadline(probe_deadline, f"capture_replay:{evidence.get('label')}:read")
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError("sealed capture ended early")
        digest.update(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if (
        _stable_identity(after) != identity
        or int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)) != seals
    ):
        raise RuntimeError("sealed capture identity/seals drift")
    keys = ("device", "inode", "size", "file_type", "mode", "uid", "nlink")
    if (
        tuple(evidence.get(key) for key in keys) != identity
        or seals & REQUIRED_SEALS != REQUIRED_SEALS
    ):
        raise RuntimeError("sealed capture binding rejected")
    actual = digest.hexdigest()
    if actual != evidence.get("sha256") or actual != evidence.get("expected_sha256"):
        raise RuntimeError("sealed capture digest drift")
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, f"capture_replay:{evidence.get('label')}:after")
    return {
        key: evidence[key]
        for key in (
            *keys,
            "sha256",
            "seals",
            "required_seals",
            "transport",
            "path",
            "label",
        )
    }


def verify_source_contract(evidence: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(evidence["path"]))
    parent = os.lstat(path.parent)
    current = os.lstat(path)
    if list(_stable_identity(current)) != evidence.get("source_identity"):
        raise RuntimeError(f"source final identity drift: {evidence['label']}")
    parent_identity = [
        int(parent.st_dev),
        int(parent.st_ino),
        stat.S_IMODE(parent.st_mode),
        int(parent.st_uid),
    ]
    if parent_identity != evidence.get("source_parent_identity"):
        raise RuntimeError(f"source final parent drift: {evidence['label']}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        digest = sha256()
        offset = 0
        while offset < current.st_size:
            block = os.pread(descriptor, min(1 << 20, current.st_size - offset), offset)
            if not block:
                raise RuntimeError("source final rehash ended early")
            digest.update(block)
            offset += len(block)
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _stable_identity(opened) != _stable_identity(
        current
    ) or digest.hexdigest() != evidence.get("sha256"):
        raise RuntimeError(f"source final rehash drift: {evidence['label']}")
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "identity": list(_stable_identity(current)),
    }


def _pread_stable(descriptor: int, *, maximum_bytes: int) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
        raise RuntimeError("descriptor read contract rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError("descriptor read ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if _stable_identity(after) != _stable_identity(before):
        raise RuntimeError("descriptor identity drift while reading")
    return b"".join(chunks)


def _record_runtime_entries(
    captures: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, tuple[str, int, str]], list[str]]:
    entries: dict[str, tuple[str, int, str]] = {}
    excluded: list[str] = []
    for label in sorted(RUNTIME_RECORDS):
        raw = _pread_stable(int(captures[label]["fd"]), maximum_bytes=8 << 20)
        for row in csv.reader(raw.decode("utf-8").splitlines()):
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
            ):
                excluded.append(f"{label}:{raw_path}")
                continue
            if relative.suffix == ".pyc" or "__pycache__" in relative.parts:
                excluded.append(f"{label}:{raw_path}")
                continue
            padding = "=" * (-len(encoded.removeprefix("sha256=")) % 4)
            digest = base64.urlsafe_b64decode(
                encoded.removeprefix("sha256=") + padding
            ).hex()
            size = int(raw_size)
            if size < 0 or size > MAX_RUNTIME_FILE_BYTES:
                raise RuntimeError(f"runtime RECORD size rejected: {raw_path}")
            key = relative.as_posix()
            previous = entries.get(key)
            value = (digest, size, label)
            if previous is not None:
                raise RuntimeError(f"duplicate runtime RECORD entry: {key}")
            entries[key] = value
    if len(entries) > MAX_RUNTIME_BUNDLE_FILES:
        raise RuntimeError("runtime bundle file-count limit exceeded")
    if (
        sum(size for _digest, size, _label in entries.values())
        > MAX_RUNTIME_BUNDLE_BYTES
    ):
        raise RuntimeError("runtime bundle byte limit exceeded")
    if (
        frozenset(RUNTIME_RECORDS) != EXPECTED_RUNTIME_RECORD_LABELS
        or len(entries) != EXPECTED_RUNTIME_BUNDLE_FILES
        or sum(size for _digest, size, _label in entries.values())
        != EXPECTED_RUNTIME_BUNDLE_BYTES
        or len(excluded) != EXPECTED_RUNTIME_EXCLUDED_ROWS
    ):
        raise RuntimeError("frozen runtime bundle cardinality drift")
    return entries, sorted(excluded)


def _open_bundle_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            following = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            row = os.fstat(following)
            if not stat.S_ISDIR(row.st_mode) or row.st_uid != os.getuid():
                os.close(following)
                raise RuntimeError("runtime bundle directory contract rejected")
            os.close(current)
            current = following
        result = current
        current = -1
        return result
    finally:
        if current >= 0:
            os.close(current)


def _seal_bytes(name: str, raw: bytes) -> tuple[int, tuple[int, ...], int]:
    descriptor = os.memfd_create(name, getattr(os, "MFD_ALLOW_SEALING", 0x0002))
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("sealed runtime target stopped accepting bytes")
            view = view[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.fchmod(descriptor, 0o400)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        identity = _stable_identity(os.fstat(descriptor))
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        if seals & REQUIRED_SEALS != REQUIRED_SEALS:
            raise RuntimeError("sealed runtime target seal rejected")
        return descriptor, identity, seals
    except BaseException:
        os.close(descriptor)
        raise


def build_runtime_bundle(
    *, runtime_root_fd: int, captures: Mapping[str, Mapping[str, Any]],
    probe_mode: bool = False, probe_deadline: float | None = None
) -> tuple[int, int, list[int], dict[str, Any], dict[str, Any]]:
    if probe_mode:
        if probe_deadline is None:
            raise RuntimeError("probe runtime bundle requires absolute deadline")
        _probe_check_deadline(probe_deadline, "runtime_bundle:before_record")
    entries, excluded = _record_runtime_entries(captures)
    root_fd = os.dup(runtime_root_fd)
    source_root_fd = os.open(
        SITE_PACKAGES,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    runtime_fds: list[int] = []
    directory_paths: set[str] = set()
    manifest_entries: list[dict[str, Any]] = []
    try:
        for index, (relative, (expected, expected_size, record_label)) in enumerate(
            sorted(entries.items())
        ):
            if index % 64 == 0:
                if probe_deadline is not None:
                    _probe_check_deadline(probe_deadline, "runtime_bundle:entry")
                sample = host_sample()
                whole_rss, whole_swap, _whole_pids = whole_launch_usage(
                    os.getpid(), None
                )
                gate = (
                    probe_breach(
                        elapsed=_probe_elapsed(probe_deadline), group_rss_kib=0, group_vmswap_kib=0,
                        whole_rss_kib=whole_rss, whole_vmswap_kib=whole_swap,
                        sample=sample,
                    )
                    if probe_mode
                    else whole_launch_breach(whole_rss, whole_swap) or breach_reason(
                        elapsed=0, group_rss_kib=0, group_vmswap_kib=0,
                        sample=sample, launch=True,
                    )
                )
                if gate is not None:
                    raise RuntimeError(f"runtime bundle resource gate: {gate}")
            source_fd = os.open(
                relative,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_root_fd,
            )
            try:
                source_before = os.fstat(source_fd)
                if not stat.S_ISREG(source_before.st_mode):
                    raise RuntimeError(f"runtime source is not regular: {relative}")
                raw = _pread_stable(source_fd, maximum_bytes=MAX_RUNTIME_FILE_BYTES)
                source_after = os.fstat(source_fd)
            finally:
                os.close(source_fd)
            actual = sha256(raw).hexdigest()
            if actual != expected or len(raw) != expected_size:
                raise RuntimeError(f"runtime source RECORD mismatch: {relative}")
            runtime_fd, identity, seals = _seal_bytes(f"puproj-runtime-{index}", raw)
            runtime_fds.append(runtime_fd)
            parts = PurePosixPath(relative).parts
            parent_parts = tuple(parts[:-1])
            for depth in range(1, len(parent_parts) + 1):
                directory_paths.add(PurePosixPath(*parent_parts[:depth]).as_posix())
            parent_fd = _open_bundle_parent(root_fd, parent_parts)
            try:
                os.symlink(
                    f"/proc/self/fd/{runtime_fd}",
                    parts[-1],
                    dir_fd=parent_fd,
                )
            finally:
                os.close(parent_fd)
            manifest_entries.append(
                {
                    "relative_path": relative,
                    "record_label": record_label,
                    "fd": runtime_fd,
                    "sha256": actual,
                    "size": len(raw),
                    "device": identity[0],
                    "inode": identity[1],
                    "file_type": identity[3],
                    "mode": identity[4],
                    "uid": identity[5],
                    "nlink": identity[6],
                    "seals": seals,
                    "required_seals": REQUIRED_SEALS,
                    "source_identity": list(_stable_identity(source_after)),
                }
            )
        for relative in sorted(
            directory_paths, key=lambda value: value.count("/"), reverse=True
        ):
            descriptor = os.open(
                relative,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                os.fchmod(descriptor, 0o500)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fchmod(root_fd, 0o500)
        os.fsync(root_fd)
        root_row = os.fstat(root_fd)
        root_identity = (
            int(root_row.st_dev),
            int(root_row.st_ino),
            stat.S_IMODE(root_row.st_mode),
            int(root_row.st_uid),
        )
        manifest = {
            "schema": "planora.puproj.frontier-v19-sealed-runtime.v1",
            "site_packages_source": str(SITE_PACKAGES),
            "source_root_identity": list(_stable_identity(os.fstat(source_root_fd))),
            "root_fd": root_fd,
            "root_identity": list(root_identity),
            "entries": manifest_entries,
            "excluded_record_rows": excluded,
            "pyc_entries_excluded": True,
        }
        manifest_raw = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest_fd, manifest_identity, manifest_seals = _seal_bytes(
            "puproj-runtime-manifest", manifest_raw
        )
        binding = {
            "protocol": "planora.puproj.frontier-v19-sealed-runtime.v1",
            "root_fd": root_fd,
            "root_identity": list(root_identity),
            "manifest_fd": manifest_fd,
            "manifest_sha256": sha256(manifest_raw).hexdigest(),
            "manifest_size": len(manifest_raw),
            "manifest_identity": list(manifest_identity),
            "manifest_seals": manifest_seals,
            "required_seals": REQUIRED_SEALS,
        }
        post_capture_sample = host_sample()
        post_snapshot = (
            probe_prechild_accounting_snapshot(os.getpid())
            if probe_mode
            else None
        )
        if post_snapshot is not None:
            post_whole_rss = int(post_snapshot["whole_rss_kib"])
            post_whole_swap = int(post_snapshot["whole_vmswap_kib"])
            post_whole_pids = tuple(int(pid) for pid in post_snapshot["pids"])
        else:
            post_whole_rss, post_whole_swap, post_whole_pids = whole_launch_usage(
                os.getpid(), None
            )
        post_capture_gate = (
            probe_breach(
                elapsed=_probe_elapsed(probe_deadline), group_rss_kib=0, group_vmswap_kib=0,
                whole_rss_kib=post_whole_rss,
                whole_vmswap_kib=post_whole_swap,
                sample=post_capture_sample,
            )
            if probe_mode
            else whole_launch_breach(post_whole_rss, post_whole_swap) or breach_reason(
                elapsed=0, group_rss_kib=0, group_vmswap_kib=0,
                sample=post_capture_sample, launch=True,
            )
        )
        if post_capture_gate is not None:
            raise RuntimeError(f"runtime bundle resource gate: {post_capture_gate}")
        if probe_deadline is not None:
            _probe_check_deadline(probe_deadline, "runtime_bundle:after")
        summary = {
            "manifest_sha256": binding["manifest_sha256"],
            "manifest_size": len(manifest_raw),
            "file_count": len(manifest_entries),
            "total_bytes": sum(row["size"] for row in manifest_entries),
            "excluded_record_row_count": len(excluded),
            "root_identity": list(root_identity),
            "transport": "read_only_symlink_tree_to_sealed_memfds",
            "post_capture_host_sample": post_capture_sample,
            "post_capture_whole_launch_rss_kib": post_whole_rss,
            "post_capture_whole_launch_vmswap_kib": post_whole_swap,
            "post_capture_whole_launch_pids": list(post_whole_pids),
            "post_capture_whole_launch_per_pid": (
                post_snapshot["per_pid"] if post_snapshot is not None else []
            ),
            "post_capture_accounting_snapshot_reconciled": (
                post_snapshot["reconciled"] if post_snapshot is not None else True
            ),
        }
        return root_fd, manifest_fd, runtime_fds, binding, summary
    except BaseException:
        for descriptor in runtime_fds:
            os.close(descriptor)
        os.close(root_fd)
        raise
    finally:
        os.close(source_root_fd)


def replay_runtime_bundle(
    binding: Mapping[str, Any], *, probe_deadline: float | None = None
) -> dict[str, Any]:
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, "runtime_replay:before")
    root_fd = int(binding["root_fd"])
    manifest_fd = int(binding["manifest_fd"])
    root_row = os.fstat(root_fd)
    root_identity = (
        int(root_row.st_dev),
        int(root_row.st_ino),
        stat.S_IMODE(root_row.st_mode),
        int(root_row.st_uid),
    )
    if (
        not stat.S_ISDIR(root_row.st_mode)
        or tuple(binding.get("root_identity", ())) != root_identity
        or root_identity[2:] != (0o500, os.getuid())
    ):
        raise RuntimeError("sealed runtime root replay rejected")
    manifest_row = os.fstat(manifest_fd)
    manifest_identity = _stable_identity(manifest_row)
    manifest_seals = int(fcntl.fcntl(manifest_fd, fcntl.F_GET_SEALS))
    raw = _pread_stable(manifest_fd, maximum_bytes=16 << 20)
    if (
        tuple(binding.get("manifest_identity", ())) != manifest_identity
        or binding.get("manifest_seals") != manifest_seals
        or manifest_seals & REQUIRED_SEALS != REQUIRED_SEALS
        or binding.get("manifest_sha256") != sha256(raw).hexdigest()
        or binding.get("manifest_size") != len(raw)
    ):
        raise RuntimeError("sealed runtime manifest replay rejected")
    manifest = json.loads(raw.decode("utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_RUNTIME_BUNDLE_FILES:
        raise RuntimeError("sealed runtime replay entry count rejected")
    total = 0
    seen: set[str] = set()
    for entry in entries:
        if probe_deadline is not None:
            _probe_check_deadline(probe_deadline, "runtime_replay:entry")
        relative = entry.get("relative_path")
        descriptor = entry.get("fd")
        if (
            not isinstance(relative, str)
            or relative in seen
            or type(descriptor) is not int
        ):
            raise RuntimeError("sealed runtime replay entry rejected")
        before = os.fstat(descriptor)
        identity = _stable_identity(before)
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        payload = _pread_stable(descriptor, maximum_bytes=MAX_RUNTIME_FILE_BYTES)
        if (
            tuple(
                entry.get(key)
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
            or seals != entry.get("seals")
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
            or sha256(payload).hexdigest() != entry.get("sha256")
            or len(payload) != entry.get("size")
            or os.readlink(relative, dir_fd=root_fd) != f"/proc/self/fd/{descriptor}"
        ):
            raise RuntimeError(f"sealed runtime replay mismatch: {relative}")
        seen.add(relative)
        total += len(payload)
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, "runtime_replay:after")
    return {
        "manifest_sha256": sha256(raw).hexdigest(),
        "file_count": len(seen),
        "total_bytes": total,
        "root_identity": list(root_identity),
        "all_seals_and_links_replayed": True,
    }


def _arm_child(parent_pid: int) -> None:
    os.setsid()
    resource.setrlimit(
        resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES)
    )
    result = LIBC.prctl(PR_SET_PDEATHSIG, int(PARENT_DEATH_SIGNAL), 0, 0, 0)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "prctl")
    stop_signals = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
    for signum in stop_signals:
        signal.signal(signum, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, stop_signals)
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), PARENT_DEATH_SIGNAL)


def _enable_subreaper() -> None:
    result = LIBC.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "prctl(PR_SET_CHILD_SUBREAPER)")


def _signal_handlers(state: dict[str, int | None]) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def handler(signum: int, _frame: Any) -> None:
        state["signal"] = signum

    for signum in (
        signal.SIGINT,
        signal.SIGTERM,
        getattr(signal, "SIGHUP", signal.SIGTERM),
    ):
        previous[signum] = signal.signal(signum, handler)
    return previous


def _candidate_group_identities(process_group: int) -> list[tuple[int, tuple[int, int, int, int]]]:
    rows: list[tuple[int, tuple[int, int, int, int]]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        identity = _process_identity(pid)
        if identity is not None and identity[1] == process_group:
            rows.append((pid, identity))
    return sorted(rows)


def create_owned_group(process_group: int) -> dict[str, Any]:
    if process_group <= 1 or process_group == os.getpgrp():
        raise RuntimeError("unsafe process-group ownership target")
    identity = _process_identity(process_group)
    if identity is None or identity[1:3] != (process_group, process_group):
        raise RuntimeError("original session leader identity unavailable")
    descriptor = os.pidfd_open(process_group, 0)
    if _process_identity(process_group) != identity:
        os.close(descriptor)
        raise RuntimeError("original session leader identity drift")
    return {
        "leader_pid": process_group,
        "leader_identity": identity,
        "leader_pidfd": descriptor,
        "members": {
            (process_group, identity[3]): {
                "pid": process_group,
                "identity": identity,
                "pidfd": descriptor,
            }
        },
        "admission_errors": [],
        "leader_generation_gone": False,
        "admission_sealed": False,
    }


def _seal_member_admission(
    ownership: dict[str, Any], pending: list[dict[str, Any]], reason: str
) -> None:
    ownership["leader_generation_gone"] = True
    ownership["admission_sealed"] = True
    ownership["admission_seal_reason"] = reason
    for row in pending:
        try:
            os.close(int(row["pidfd"]))
        except OSError:
            pass


def admit_owned_members(ownership: dict[str, Any]) -> None:
    """Admit new members only while the captured session-leader generation is live."""
    if ownership.get("admission_sealed", False):
        return
    leader = int(ownership["leader_pid"])
    anchor = tuple(ownership["leader_identity"])
    if _process_identity(leader) != anchor:
        _seal_member_admission(ownership, [], "leader_anchor_precheck_failed")
        return
    members = ownership["members"]
    candidates = _candidate_group_identities(leader)
    if _process_identity(leader) != anchor:
        _seal_member_admission(ownership, [], "leader_anchor_post_enumeration_failed")
        return
    pending: list[dict[str, Any]] = []
    for pid, identity in candidates:
        if identity[2] != leader:
            continue
        key = (pid, identity[3])
        if key in members:
            continue
        try:
            descriptor = os.pidfd_open(pid, 0)
        except (OSError, ValueError) as exc:
            ownership["admission_errors"].append(
                f"pidfd_open:{pid}:{type(exc).__name__}:{exc}"
            )
            continue
        if _process_identity(pid) != identity:
            os.close(descriptor)
            ownership["admission_errors"].append(f"pidfd_identity_drift:{pid}")
            continue
        pending.append(
            {"pid": pid, "identity": identity, "pidfd": descriptor, "key": key}
        )
    if _process_identity(leader) != anchor:
        _seal_member_admission(
            ownership, pending, "leader_anchor_precommit_failed"
        )
        return
    for row in pending:
        members[row.pop("key")] = row


def _live_owned_members(ownership: dict[str, Any]) -> list[dict[str, Any]]:
    live: list[dict[str, Any]] = []
    leader = int(ownership["leader_pid"])
    for row in ownership["members"].values():
        identity = _process_identity(int(row["pid"]))
        if identity == tuple(row["identity"]) and identity[1:3] == (leader, leader):
            live.append(row)
    return live


def owned_group_usage(ownership: dict[str, Any]) -> tuple[int, int, tuple[int, ...]]:
    admit_owned_members(ownership)
    rss = 0
    swap = 0
    pids: list[int] = []
    for row in _live_owned_members(ownership):
        pid = int(row["pid"])
        try:
            status = _read_key_values(Path(f"/proc/{pid}/status"))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        pids.append(pid)
        rss += status.get("VmRSS", 0)
        swap += status.get("VmSwap", 0)
    return rss, swap, tuple(sorted(pids))


def whole_owned_launch_usage(
    supervisor_pid: int, ownership: dict[str, Any]
) -> tuple[int, int, tuple[int, ...]]:
    group_rss, group_swap, group_pids = owned_group_usage(ownership)
    pids = set(group_pids)
    pids.add(supervisor_pid)
    rss = group_rss
    swap = group_swap
    if supervisor_pid not in group_pids:
        status = _read_key_values(Path(f"/proc/{supervisor_pid}/status"))
        rss += status.get("VmRSS", 0)
        swap += status.get("VmSwap", 0)
    return rss, swap, tuple(sorted(pids))


def probe_accounting_snapshot(
    supervisor_pid: int, ownership: dict[str, Any]
) -> dict[str, Any]:
    """Read one generation-bound PID set once and derive every probe total from it."""
    admit_owned_members(ownership)
    expected: dict[int, tuple[int, int, int, int]] = {}
    leader = int(ownership["leader_pid"])
    for member in _live_owned_members(ownership):
        pid = int(member["pid"])
        identity = tuple(int(value) for value in member["identity"])
        if identity[1:3] != (leader, leader):
            raise RuntimeError(f"probe accounting generation mismatch: {pid}")
        expected[pid] = identity
    supervisor_identity = _process_identity(supervisor_pid)
    if supervisor_identity is None:
        raise RuntimeError("probe accounting supervisor identity unavailable")
    expected[supervisor_pid] = supervisor_identity
    rows: list[dict[str, Any]] = []
    for pid, identity in sorted(expected.items()):
        if _process_identity(pid) != identity:
            raise RuntimeError(f"probe accounting identity drift before read: {pid}")
        status = _read_key_values(Path(f"/proc/{pid}/status"))
        if _process_identity(pid) != identity:
            raise RuntimeError(f"probe accounting identity drift after read: {pid}")
        rows.append(
            {
                "pid": pid,
                "identity": list(identity),
                "generation_admitted_child": pid != supervisor_pid,
                "vmrss_kib": int(status.get("VmRSS", 0)),
                "vmswap_kib": int(status.get("VmSwap", 0)),
            }
        )
    child_rows = [row for row in rows if row["generation_admitted_child"]]
    group_rss = sum(int(row["vmrss_kib"]) for row in child_rows)
    group_swap = sum(int(row["vmswap_kib"]) for row in child_rows)
    whole_rss = sum(int(row["vmrss_kib"]) for row in rows)
    whole_swap = sum(int(row["vmswap_kib"]) for row in rows)
    return {
        "pids": [int(row["pid"]) for row in rows],
        "per_pid": rows,
        "group_rss_kib": group_rss,
        "group_vmswap_kib": group_swap,
        "whole_rss_kib": whole_rss,
        "whole_vmswap_kib": whole_swap,
        "reconciled": (
            whole_rss == sum(int(row["vmrss_kib"]) for row in rows)
            and whole_swap == sum(int(row["vmswap_kib"]) for row in rows)
        ),
    }


def probe_prechild_accounting_snapshot(supervisor_pid: int) -> dict[str, Any]:
    identity = _process_identity(supervisor_pid)
    if identity is None:
        raise RuntimeError("probe prechild supervisor identity unavailable")
    if _process_identity(supervisor_pid) != identity:
        raise RuntimeError("probe prechild supervisor identity drift before read")
    status = _read_key_values(Path(f"/proc/{supervisor_pid}/status"))
    if _process_identity(supervisor_pid) != identity:
        raise RuntimeError("probe prechild supervisor identity drift after read")
    row = {
        "pid": supervisor_pid,
        "identity": list(identity),
        "generation_admitted_child": False,
        "vmrss_kib": int(status.get("VmRSS", 0)),
        "vmswap_kib": int(status.get("VmSwap", 0)),
    }
    return {
        "pids": [supervisor_pid],
        "per_pid": [row],
        "whole_rss_kib": row["vmrss_kib"],
        "whole_vmswap_kib": row["vmswap_kib"],
        "reconciled": True,
    }


def signal_owned_members(ownership: dict[str, Any], signum: int) -> dict[str, Any]:
    admit_owned_members(ownership)
    sent: list[int] = []
    errors: list[str] = []
    leader = int(ownership["leader_pid"])
    rows = sorted(_live_owned_members(ownership), key=lambda row: int(row["pid"]) == leader)
    for row in rows:
        pid = int(row["pid"])
        try:
            signal.pidfd_send_signal(int(row["pidfd"]), signum)
            sent.append(pid)
        except (OSError, ValueError) as exc:
            errors.append(f"pidfd_send:{pid}:{type(exc).__name__}:{exc}")
            continue
    return {"signal": int(signum), "sent_pids": sent, "errors": errors}


def ensure_owned_group_empty(
    ownership: dict[str, Any], *, close_pidfds: bool = True
) -> dict[str, Any]:
    """Best-effort total cleanup; ownership ambiguity is reported, never signalled."""
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    initial: list[int] = []
    remaining: list[int] = []
    ambiguous: list[int] = []
    try:
        try:
            admit_owned_members(ownership)
            initial = [int(row["pid"]) for row in _live_owned_members(ownership)]
        except Exception as exc:
            errors.append(f"initial_snapshot:{type(exc).__name__}:{exc}")
        if initial:
            try:
                action = signal_owned_members(ownership, signal.SIGTERM)
                actions.append(action)
                errors.extend(str(value) for value in action["errors"])
            except Exception as exc:
                errors.append(f"sigterm_stage:{type(exc).__name__}:{exc}")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    remaining = [int(row["pid"]) for row in _live_owned_members(ownership)]
                except Exception as exc:
                    errors.append(f"term_poll:{type(exc).__name__}:{exc}")
                    break
                if not remaining:
                    break
                time.sleep(0.05)
        if remaining:
            try:
                action = signal_owned_members(ownership, signal.SIGKILL)
                actions.append(action)
                errors.extend(str(value) for value in action["errors"])
            except Exception as exc:
                errors.append(f"sigkill_stage:{type(exc).__name__}:{exc}")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    remaining = [int(row["pid"]) for row in _live_owned_members(ownership)]
                except Exception as exc:
                    errors.append(f"kill_poll:{type(exc).__name__}:{exc}")
                    break
                if not remaining:
                    break
                time.sleep(0.05)
        try:
            admitted = {(int(row["pid"]), int(row["identity"][3])) for row in ownership["members"].values()}
            ambiguous = [
                pid for pid, identity in _candidate_group_identities(int(ownership["leader_pid"]))
                if (pid, identity[3]) not in admitted
            ]
        except Exception as exc:
            errors.append(f"ambiguity_scan:{type(exc).__name__}:{exc}")
        errors.extend(str(value) for value in ownership.get("admission_errors", ()))
    except Exception as exc:
        errors.append(f"cleanup_outer:{type(exc).__name__}:{exc}")
    finally:
        if close_pidfds:
            for row in list(ownership.get("members", {}).values()):
                try:
                    os.close(int(row["pidfd"]))
                except OSError:
                    pass
    return {
        "initial_owned_pids": sorted(initial),
        "actions": actions,
        "final_owned_pids": sorted(remaining),
        "ambiguous_unowned_numeric_group_pids": sorted(ambiguous),
        "errors": errors,
        "leader_generation_gone": bool(ownership.get("leader_generation_gone")),
        "empty": not remaining and not ambiguous and not errors,
    }


def wait_child_and_drain(
    child: subprocess.Popen[bytes], ownership: dict[str, Any], *, timeout: float
) -> tuple[int, str | None, dict[str, Any]]:
    """Drain, reap the leader, then prove the exact process generation empty."""
    child_exit_code = -1
    wait_error: str | None = None
    try:
        child_exit_code = child.wait(timeout=timeout)
    except Exception as exc:
        wait_error = f"child_wait:{type(exc).__name__}:{exc}"
    first_cleanup = ensure_owned_group_empty(ownership, close_pidfds=False)
    observed_exit_code = child.poll()
    if observed_exit_code is None:
        try:
            child_exit_code = child.wait(timeout=POST_KILL_REAP_TIMEOUT_SECONDS)
        except Exception as exc:
            detail = f"post_cleanup_child_wait:{type(exc).__name__}:{exc}"
            wait_error = detail if wait_error is None else f"{wait_error};{detail}"
    else:
        child_exit_code = observed_exit_code
    final_cleanup = ensure_owned_group_empty(ownership)
    errors = list(
        dict.fromkeys(
            [
                *(str(value) for value in first_cleanup["errors"]),
                *(str(value) for value in final_cleanup["errors"]),
            ]
        )
    )
    cleanup = {
        "initial_owned_pids": first_cleanup["initial_owned_pids"],
        "actions": [*first_cleanup["actions"], *final_cleanup["actions"]],
        "final_owned_pids": final_cleanup["final_owned_pids"],
        "ambiguous_unowned_numeric_group_pids": final_cleanup[
            "ambiguous_unowned_numeric_group_pids"
        ],
        "errors": errors,
        "leader_generation_gone": final_cleanup["leader_generation_gone"],
        "empty": final_cleanup["empty"] and not errors,
    }
    return child_exit_code, wait_error, cleanup


def monitor_probe_child(
    child: subprocess.Popen[bytes], ownership: dict[str, Any], *, deadline: float
) -> dict[str, Any]:
    breach: str | None = None
    monitor_error: str | None = None
    peak_snapshot: dict[str, Any] | None = None
    child_exit_code = -1
    wait_error: str | None = None
    cleanup: dict[str, Any] = {"empty": False, "errors": ["cleanup_not_run"]}
    try:
        while child.poll() is None:
            _probe_check_deadline(deadline, "monitor:sample")
            snapshot = probe_accounting_snapshot(os.getpid(), ownership)
            if not snapshot["reconciled"]:
                raise RuntimeError("probe accounting snapshot did not reconcile")
            if (
                peak_snapshot is None
                or snapshot["whole_rss_kib"] + snapshot["whole_vmswap_kib"]
                > peak_snapshot["whole_rss_kib"] + peak_snapshot["whole_vmswap_kib"]
            ):
                peak_snapshot = snapshot
            breach = probe_breach(
                elapsed=_probe_elapsed(deadline),
                group_rss_kib=snapshot["group_rss_kib"],
                group_vmswap_kib=snapshot["group_vmswap_kib"],
                whole_rss_kib=snapshot["whole_rss_kib"],
                whole_vmswap_kib=snapshot["whole_vmswap_kib"],
                sample=host_sample(),
            )
            if breach is not None:
                signal_owned_members(ownership, signal.SIGTERM)
                break
            time.sleep(POLL_SECONDS)
    except Exception as exc:
        monitor_error = f"probe_monitor:{type(exc).__name__}:{exc}"
    finally:
        child_exit_code, wait_error, cleanup = wait_child_and_drain(
            child,
            ownership,
            timeout=max(0.0, min(5.0, deadline - time.monotonic())),
        )
    return {
        "breach": breach,
        "monitor_error": monitor_error,
        "peak_snapshot": peak_snapshot,
        "child_exit_code": child_exit_code,
        "wait_error": wait_error,
        "cleanup": cleanup,
    }


def planned_command(
    python_fd: int,
    runner_fd: int,
    runtime_root_fd: int,
    barrier_fd: int,
    pycache_prefix: Path,
    *,
    sealed_import_probe: bool = False,
) -> list[str]:
    command = [
        f"/proc/self/fd/{python_fd}",
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={pycache_prefix}",
        "-c",
        RUNNER_FD_LOADER,
        str(runner_fd),
        EXPECTED_RUNNER_SHA256,
        str(runtime_root_fd),
        str(barrier_fd),
    ]
    if sealed_import_probe:
        return [*command, "--sealed-import-probe"]
    return [
        *command,
        "--execute-frontier",
        "--allow-official-input",
        "--allow-solver",
        "--allow-publication",
    ]


def _read_relative_regular(
    dirfd: int, name: str, *, maximum_bytes: int
) -> tuple[bytes, dict[str, int]]:
    descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dirfd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise RuntimeError(f"child artifact {name} contract rejected")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise RuntimeError(f"child artifact {name} ended early")
            chunks.append(block)
            offset += len(block)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if _stable_identity(before) != _stable_identity(after) or _stable_identity(
            after
        ) != _stable_identity(named):
            raise RuntimeError(f"child artifact {name} identity drift")
        return b"".join(chunks), {
            "device": int(after.st_dev),
            "inode": int(after.st_ino),
            "size": int(after.st_size),
            "mode": stat.S_IMODE(after.st_mode),
            "uid": int(after.st_uid),
        }
    finally:
        os.close(descriptor)


def _pread_retained_named(
    dirfd: int,
    name: str,
    descriptor: int,
    *,
    maximum_bytes: int,
    probe_deadline: float,
) -> tuple[bytes, dict[str, int]]:
    _probe_check_deadline(probe_deadline, f"retained_read:{name}:before")
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size > maximum_bytes
        or before.st_uid != os.getuid()
    ):
        raise RuntimeError(f"retained child artifact {name} contract rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        _probe_check_deadline(probe_deadline, f"retained_read:{name}:read")
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError(f"retained child artifact {name} ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    named = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    identity = _stable_identity(before)
    if identity != _stable_identity(after) or identity != _stable_identity(named):
        raise RuntimeError(f"retained child artifact {name} identity drift")
    _probe_check_deadline(probe_deadline, f"retained_read:{name}:after")
    return b"".join(chunks), {
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "size": int(after.st_size),
        "mode": stat.S_IMODE(after.st_mode),
        "uid": int(after.st_uid),
    }


def _exact_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _exact_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


PROBE_CHILD_SUCCESS_KEYS = frozenset(
    {
        "schema",
        "status",
        "elapsed_seconds",
        "executing_python",
        "runtime_bundle",
        "runtime_install",
        "compile_warnings",
        "loaded_runtime",
        "system_runtime_comparison",
        "imported_planora_modules",
        "imported_planora_module_count",
        "official_instance_opened",
        "checkpoint_or_incumbent_opened",
        "solver_execution_started",
        "solver_child_process_started",
        "probe_child_process_started",
        "solve_call_count",
        "official_solution_xml_published",
        "runner_sha256_start",
        "runner_sha256_end",
        "runner_hash_stable",
    }
)


def admit_probe_child_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) != PROBE_CHILD_SUCCESS_KEYS:
        raise RuntimeError("probe child report exact schema rejected")
    elapsed = _finite_elapsed(report.get("elapsed_seconds"))
    if elapsed is None or elapsed >= PROBE_HARD_WALL_SECONDS:
        raise RuntimeError("probe child elapsed rejected")

    executing = report.get("executing_python")
    executing_keys = {
        "sha256", "identity", "sys_executable", "proc_self_exe_bound",
        "isolated", "no_site", "dont_write_bytecode", "transport",
    }
    identity = executing.get("identity") if isinstance(executing, dict) else None
    if (
        not isinstance(executing, dict)
        or set(executing) != executing_keys
        or executing.get("sha256") != EXPECTED_HASHES["python_binary"]
        or not isinstance(identity, list)
        or len(identity) != 7
        or not all(_exact_nonnegative_int(value) for value in identity)
        or identity[2] <= 0
        or identity[3] != stat.S_IFREG
        or identity[4:] != [0o500, os.getuid(), 0]
        or not isinstance(executing.get("sys_executable"), str)
        or not executing["sys_executable"].startswith("/proc/self/fd/")
        or executing.get("proc_self_exe_bound") is not True
        or executing.get("isolated") is not True
        or executing.get("no_site") is not True
        or executing.get("dont_write_bytecode") is not True
        or executing.get("transport") != "sealed_executable_memfd"
    ):
        raise RuntimeError("probe child executing Python structure rejected")

    runtime = report.get("runtime_bundle")
    runtime_keys = {
        "manifest_sha256", "manifest_size", "file_count", "total_bytes",
        "excluded_record_row_count", "root_identity",
        "all_files_sealed_before_third_party_import", "pyc_entries_excluded",
        "transport",
    }
    root_identity = runtime.get("root_identity") if isinstance(runtime, dict) else None
    if (
        not isinstance(runtime, dict)
        or set(runtime) != runtime_keys
        or not _exact_sha256(runtime.get("manifest_sha256"))
        or not _exact_nonnegative_int(runtime.get("manifest_size"))
        or not 0 < runtime["manifest_size"] <= 16 << 20
        or runtime.get("file_count") != 3_077
        or runtime.get("total_bytes") != 191_956_270
        or runtime.get("excluded_record_row_count") != 2_098
        or not isinstance(root_identity, list)
        or len(root_identity) != 4
        or not all(_exact_nonnegative_int(value) for value in root_identity)
        or root_identity[2:] != [0o500, os.getuid()]
        or runtime.get("all_files_sealed_before_third_party_import") is not True
        or runtime.get("pyc_entries_excluded") is not True
        or runtime.get("transport") != "read_only_symlink_tree_to_sealed_memfds"
    ):
        raise RuntimeError("probe child runtime bundle structure rejected")

    runtime_install = report.get("runtime_install")
    install_keys = {
        "sealed_source_finder_installed", "native_dependency_memfds_preloaded",
        "native_dependency_paths", "native_dependency_preload_failures",
        "live_site_packages_on_sys_path",
    }
    dependency_paths = (
        runtime_install.get("native_dependency_paths")
        if isinstance(runtime_install, dict) else None
    )
    if (
        not isinstance(runtime_install, dict)
        or set(runtime_install) != install_keys
        or runtime_install.get("sealed_source_finder_installed") is not True
        or not _exact_nonnegative_int(
            runtime_install.get("native_dependency_memfds_preloaded")
        )
        or not _exact_string_list(dependency_paths)
        or runtime_install["native_dependency_memfds_preloaded"] != len(dependency_paths)
        or runtime_install.get("native_dependency_preload_failures") != []
        or runtime_install.get("live_site_packages_on_sys_path") is not False
    ):
        raise RuntimeError("probe child runtime install structure rejected")

    compile_warnings = report.get("compile_warnings")
    warning_keys = {
        "schema", "status", "count", "category", "message",
        "source_relative_path", "source_sha256",
        "observed_v17_stderr_bytes", "observed_v17_stderr_sha256",
        "child_stderr_bytes",
    }
    if (
        not isinstance(compile_warnings, dict)
        or set(compile_warnings) != warning_keys
        or compile_warnings.get("schema")
        != "planora.puproj.frontier-joint-v19.compile-warnings.v1"
        or compile_warnings.get("status") != "ADMITTED"
        or compile_warnings.get("count") != 2
        or compile_warnings.get("category") != "DeprecationWarning"
        or compile_warnings.get("message") != CP_MODEL_COMPILE_WARNING_MESSAGE
        or compile_warnings.get("source_relative_path") != CP_MODEL_SOURCE_PATH
        or compile_warnings.get("source_sha256") != CP_MODEL_SOURCE_SHA256
        or compile_warnings.get("observed_v17_stderr_bytes") != 411
        or compile_warnings.get("observed_v17_stderr_sha256")
        != "59a10aaa235579022a6e84a089c42427f794e6de05ab74ded64de5874346c988"
        or compile_warnings.get("child_stderr_bytes") != 0
    ):
        raise RuntimeError("probe child compile-warning evidence rejected")

    loaded = report.get("loaded_runtime")
    loaded_keys = {
        "python_version", "python_cache_tag", "python_executable_realpath",
        "python_binary_sha256", "pyc_reads_disabled_by_private_prefix",
        "dont_write_bytecode", "sealed_record_hashes", "loaded_files",
        "loaded_file_count", "loaded_manifest_sha256",
    }
    loaded_files = loaded.get("loaded_files") if isinstance(loaded, dict) else None
    sealed_records = (
        loaded.get("sealed_record_hashes") if isinstance(loaded, dict) else None
    )
    expected_records = {
        root: EXPECTED_HASHES[label]
        for root, label in {
            "ortools": "runtime_ortools_record", "numpy": "runtime_numpy_record",
            "pandas": "runtime_pandas_record", "dateutil": "runtime_dateutil_record",
            "six": "runtime_six_record", "lxml": "runtime_lxml_record",
            "absl": "runtime_absl_record", "immutabledict": "runtime_immutabledict_record",
            "google": "runtime_protobuf_record",
            "typing_extensions": "runtime_typing_extensions_record",
        }.items()
    }
    if (
        not isinstance(loaded, dict)
        or set(loaded) != loaded_keys
        or any(
            not isinstance(loaded.get(key), str) or not loaded[key]
            for key in ("python_version", "python_cache_tag", "python_executable_realpath")
        )
        or loaded.get("python_binary_sha256") != EXPECTED_HASHES["python_binary"]
        or loaded.get("pyc_reads_disabled_by_private_prefix") is not True
        or loaded.get("dont_write_bytecode") is not True
        or sealed_records != expected_records
        or not isinstance(loaded_files, list)
        or not _exact_nonnegative_int(loaded.get("loaded_file_count"))
        or loaded["loaded_file_count"] != len(loaded_files)
        or not 0 < len(loaded_files) <= 3_077
        or not _exact_sha256(loaded.get("loaded_manifest_sha256"))
    ):
        raise RuntimeError("probe child loaded runtime structure rejected")
    loaded_paths: list[str] = []
    for index, row in enumerate(loaded_files):
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "sha256", "size", "transport"}
            or not isinstance(row.get("path"), str)
            or not row["path"]
            or not _exact_sha256(row.get("sha256"))
            or not _exact_nonnegative_int(row.get("size"))
            or row.get("transport") not in {
                "sealed_descriptor_loader", "sealed_native_descriptor"
            }
        ):
            raise RuntimeError(
                f"probe child loaded runtime row rejected at index {index}"
            )
        loaded_paths.append(row["path"])
    if loaded_paths != sorted(loaded_paths) or len(loaded_paths) != len(
        set(loaded_paths)
    ):
        raise RuntimeError("probe child loaded runtime canonical order rejected")
    observed_loaded_manifest_sha256 = sha256(
        json.dumps(
            loaded_files,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if loaded["loaded_manifest_sha256"] != observed_loaded_manifest_sha256:
        raise RuntimeError("probe child loaded runtime manifest hash rejected")

    comparison = report.get("system_runtime_comparison")
    comparison_keys = {
        "start_file_count", "end_file_count", "start_subset_stable",
        "new_post_import_files", "start_python_module_count",
        "end_python_module_count", "new_post_import_python_modules", "boundary",
    }
    if (
        not isinstance(comparison, dict)
        or set(comparison) != comparison_keys
        or any(
            not _exact_nonnegative_int(comparison.get(key))
            for key in (
                "start_file_count", "end_file_count",
                "start_python_module_count", "end_python_module_count",
            )
        )
        or comparison["end_file_count"] < comparison["start_file_count"]
        or comparison["end_python_module_count"] < comparison["start_python_module_count"]
        or comparison.get("start_subset_stable") is not True
        or not _exact_string_list(comparison.get("new_post_import_files"))
        or not _exact_string_list(comparison.get("new_post_import_python_modules"))
        or comparison.get("boundary") != "trusted_system_runtime_observed_and_hashed_not_sealed"
    ):
        raise RuntimeError("probe child runtime comparison rejected")

    expected_modules = {
        f"benchmarks.{label}": EXPECTED_HASHES[label]
        for label in PLANORA_FRESH_MODULES
    }
    imported = report.get("imported_planora_modules")
    if not isinstance(imported, list) or len(imported) != 13:
        raise RuntimeError("probe child module list rejected")
    actual_modules: dict[str, str] = {}
    for row in imported:
        if not isinstance(row, dict) or set(row) != {"module", "sha256"}:
            raise RuntimeError("probe child module row rejected")
        module = row.get("module")
        digest = row.get("sha256")
        if (
            not isinstance(module, str)
            or not _exact_sha256(digest)
            or module in actual_modules
        ):
            raise RuntimeError("probe child module identity rejected")
        actual_modules[module] = digest
    if (
        report.get("schema") != "planora.puproj.frontier-joint-v19-sealed-import-probe-child.v1"
        or report.get("status") != "PASS"
        or type(report.get("imported_planora_module_count")) is not int
        or report["imported_planora_module_count"] != 13
        or actual_modules != expected_modules
        or report.get("official_instance_opened") is not False
        or report.get("checkpoint_or_incumbent_opened") is not False
        or report.get("solver_execution_started") is not False
        or report.get("solver_child_process_started") is not False
        or report.get("probe_child_process_started") is not True
        or type(report.get("solve_call_count")) is not int
        or report["solve_call_count"] != 0
        or report.get("official_solution_xml_published") is not False
        or report.get("runner_sha256_start") != EXPECTED_RUNNER_SHA256
        or report.get("runner_sha256_end") != EXPECTED_RUNNER_SHA256
        or report.get("runner_hash_stable") is not True
    ):
        raise RuntimeError("probe child report admission rejected")
    return report


def _probe_stream_diagnostics(
    stdout_raw: bytes,
    stderr_raw: bytes,
    *,
    child_exit_code: int | None,
) -> dict[str, Any]:
    stderr_tail = stderr_raw[-PROBE_DIAGNOSTIC_TAIL_BYTES:]
    return {
        "schema": "planora.puproj.frontier-joint-v19-child-stream-diagnostics.v1",
        "child_exit_code": child_exit_code,
        "capture_limit_bytes_per_stream": PROBE_CAPTURE_MAX_BYTES,
        "stdout": {
            "size": len(stdout_raw),
            "sha256": sha256(stdout_raw).hexdigest(),
        },
        "stderr": {
            "size": len(stderr_raw),
            "sha256": sha256(stderr_raw).hexdigest(),
            "tail_base64": base64.b64encode(stderr_tail).decode("ascii"),
            "tail_size": len(stderr_tail),
            "tail_limit_bytes": PROBE_DIAGNOSTIC_TAIL_BYTES,
            "tail_truncated": len(stderr_raw) > len(stderr_tail),
            "encoding": "base64_exact_bytes",
        },
    }


def diagnose_probe_child_report(
    stdout_raw: bytes,
    stderr_raw: bytes,
    *,
    child_exit_code: int | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Classify child output before exact 21-key success admission."""
    streams = _probe_stream_diagnostics(
        stdout_raw,
        stderr_raw,
        child_exit_code=child_exit_code,
    )
    transport_failures: list[str] = []
    if child_exit_code != 0:
        transport_failures.append("child_exit_failure")
    if stderr_raw:
        transport_failures.append("child_stderr_failure")

    def rejected(classification: str, **details: Any):
        envelope = {
            "schema": "planora.puproj.frontier-joint-v19-child-rejection.v1",
            "classification": classification,
            "success_schema_key_count": len(PROBE_CHILD_SUCCESS_KEYS),
            "child_exit_code": child_exit_code,
            "transport_failures": transport_failures,
            "streams": streams,
            **details,
        }
        return None, envelope, streams

    if not stdout_raw:
        return rejected("empty_stdout")
    try:
        stdout_text = stdout_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        return rejected(
            "stdout_decoding_failure",
            decoding={
                "encoding": "utf-8",
                "start": error.start,
                "end": error.end,
                "reason": error.reason,
            },
        )
    try:
        decoded = json.loads(stdout_text)
    except json.JSONDecodeError as error:
        return rejected(
            "json_decode_failure",
            json_error={
                "message": error.msg,
                "line": error.lineno,
                "column": error.colno,
                "position": error.pos,
            },
        )
    if not isinstance(decoded, dict):
        return rejected(
            "non_object_json",
            decoded_json_type=type(decoded).__name__,
        )
    actual_keys = set(decoded)
    missing_keys = sorted(PROBE_CHILD_SUCCESS_KEYS - actual_keys)
    unexpected_keys = sorted(actual_keys - PROBE_CHILD_SUCCESS_KEYS)
    if missing_keys or unexpected_keys:
        return rejected(
            "schema_key_mismatch",
            missing_keys=missing_keys,
            unexpected_keys=unexpected_keys,
        )
    if child_exit_code != 0:
        return rejected(
            "child_exit_failure",
            missing_keys=[],
            unexpected_keys=[],
        )
    if stderr_raw:
        return rejected(
            "child_stderr_failure",
            missing_keys=[],
            unexpected_keys=[],
        )
    try:
        admitted = admit_probe_child_report(decoded)
    except RuntimeError as error:
        return rejected(
            "success_schema_admission_rejected",
            missing_keys=[],
            unexpected_keys=[],
            admission_error=str(error)[:256],
        )
    return admitted, None, streams


def _finite_elapsed(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


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


def child_acceptance_v19(
    *,
    dirfd: int,
    run_dir: Path,
    child_exit_code: int,
    observed_child_elapsed_seconds: float,
) -> tuple[str, list[str], dict[str, Any]]:
    """Admit only a complete fresh solution or a strict controlled unknown."""

    errors: list[str] = []
    artifacts: dict[str, Any] = {
        "observed_child_elapsed_seconds": observed_child_elapsed_seconds
    }
    names = sorted(entry.name for entry in os.scandir(f"/proc/self/fd/{dirfd}"))
    unexpected = sorted(
        set(names)
        - {"child.stdout.log", "child.stderr.log", "solution.xml", "runner-report.json"}
    )
    if unexpected:
        errors.append("unexpected_child_artifacts:" + ",".join(unexpected))
    stdout_bytes, stdout_identity = _read_relative_regular(
        dirfd, "child.stdout.log", maximum_bytes=32 << 20
    )
    stderr_bytes, stderr_identity = _read_relative_regular(
        dirfd, "child.stderr.log", maximum_bytes=32 << 20
    )
    artifacts["stdout"] = {**stdout_identity, "sha256": sha256(stdout_bytes).hexdigest()}
    artifacts["stderr"] = {**stderr_identity, "sha256": sha256(stderr_bytes).hexdigest()}
    try:
        child = json.loads(stdout_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        child = {}
        errors.append("child_stdout_invalid_json")
    if not isinstance(child, dict):
        child = {}
        errors.append("child_stdout_top_level_not_object")
    artifacts["child_payload"] = child
    if (
        child.get("runner_sha256_start") != EXPECTED_RUNNER_SHA256
        or child.get("runner_sha256_end") != EXPECTED_RUNNER_SHA256
        or child.get("runner_hash_stable") is not True
    ):
        errors.append("runner_hash_claim_mismatch")
    output_names = set(names) - {"child.stdout.log", "child.stderr.log"}
    if child_exit_code == 3:
        if output_names != {"runner-report.json"}:
            errors.append("controlled_unknown_output_set_mismatch")
            return "FAILED", errors, artifacts
        raw, identity = _read_relative_regular(dirfd, "runner-report.json", maximum_bytes=32 << 20)
        report = json.loads(raw)
        artifacts["runner-report.json"] = {**identity, "sha256": sha256(raw).hexdigest(), "payload": report}
        if (
            child.get("status") != "CONTROLLED_UNKNOWN_PUBLISHED"
            or child.get("admissible_as_solution") is not False
            or child.get("official_solution_xml_published") is not False
            or report.get("schema") != "planora.pu-proj.frontier-joint-v19.fresh-report.v1"
            or report.get("status") != "CONTROLLED_UNKNOWN"
            or report.get("solver_input_mode") != "OFFICIAL_INPUT_ONLY_FRESH"
            or report.get("checkpoint_or_incumbent_accessed") is not False
            or report.get("admissible_as_solution") is not False
        ):
            errors.append("controlled_unknown_schema_mismatch")
        return ("CONTROLLED_UNKNOWN" if not errors else "FAILED"), errors, artifacts
    if child_exit_code != 0 or output_names != {"solution.xml", "runner-report.json"}:
        errors.append(f"complete_output_or_exit_mismatch:{child_exit_code}")
        return "FAILED", errors, artifacts
    solution, solution_identity = _read_relative_regular(dirfd, "solution.xml", maximum_bytes=256 << 20)
    report_raw, report_identity = _read_relative_regular(dirfd, "runner-report.json", maximum_bytes=32 << 20)
    report = json.loads(report_raw)
    artifacts["solution.xml"] = {**solution_identity, "sha256": sha256(solution).hexdigest()}
    artifacts["runner-report.json"] = {**report_identity, "sha256": sha256(report_raw).hexdigest(), "payload": report}
    publication = child.get("publication")
    generic = report.get("generic_validation") if isinstance(report, dict) else None
    if (
        child.get("status") != "COMPLETE_VALID_PUBLISHED"
        or child.get("class_count") != 8_813
        or child.get("student_count") != 38_437
        or child.get("admissible_as_solution") is not True
        or child.get("official_solution_xml_published") is not True
        or not isinstance(publication, dict)
        or publication.get("solution.xml", {}).get("publication_order") != 1
        or publication.get("runner-report.json", {}).get("publication_order") != 2
        or report.get("schema") != "planora.pu-proj.frontier-joint-v19.fresh-report.v1"
        or report.get("status") != "COMPLETE_VALID"
        or report.get("solver_input_mode") != "OFFICIAL_INPUT_ONLY_FRESH"
        or report.get("checkpoint_or_incumbent_accessed") is not False
        or report.get("competitor_schedule_or_result_used") is not False
        or report.get("competitor_placement_or_hint_used") is not False
        or report.get("class_count") != 8_813
        or report.get("student_count") != 38_437
        or report.get("local_semantic_errors") != []
        or report.get("local_document_errors") != []
        or not isinstance(generic, dict)
        or generic.get("status") != "COMPLETE_VALID"
        or generic.get("classes") != 8_813
        or generic.get("students") != 38_437
        or publication.get("solution.xml", {}).get("sha256") != sha256(solution).hexdigest()
        or publication.get("runner-report.json", {}).get("sha256") != sha256(report_raw).hexdigest()
    ):
        errors.append("complete_fresh_claim_mismatch")
    return ("COMPLETE_VALID" if not errors else "FAILED"), errors, artifacts


def publish_supervisor_report(
    *,
    dirfd: int,
    parent: Path,
    parent_identity: tuple[int, int, int, int],
    payload: Mapping[str, Any],
    probe_deadline: float | None = None,
) -> dict[str, Any]:
    """Create an unpublished, sealed supervisor envelope.

    The returned mapping is an internal capability containing an open memfd.  It
    is deliberately not JSON serializable.  Callers must pass it exactly once to
    ``consume_supervisor_report``; no pathname is ever an authority for these
    bytes.
    """
    if probe_deadline is not None:
        _probe_check_deadline(probe_deadline, "publication:before")
    raw = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor = os.memfd_create(
        "planora-puproj-v19-supervisor-envelope",
        getattr(os, "MFD_ALLOW_SEALING", 0x0002),
    )
    try:
        os.fchmod(descriptor, 0o400)
        view = memoryview(raw)
        while view:
            if probe_deadline is not None:
                _probe_check_deadline(probe_deadline, "publication:write")
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("supervisor report stopped accepting bytes")
            view = view[written:]
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        retained = os.fstat(descriptor)
        identity = (
            int(retained.st_dev), int(retained.st_ino), stat.S_IFMT(retained.st_mode),
            stat.S_IMODE(retained.st_mode), int(retained.st_uid), int(retained.st_nlink),
        )
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        if (
            not stat.S_ISREG(retained.st_mode)
            or stat.S_IMODE(retained.st_mode) != 0o400
            or int(retained.st_uid) != os.getuid()
            or int(retained.st_nlink) != 0
            or retained.st_size != len(raw)
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
        ):
            raise RuntimeError("supervisor envelope sealing rejected")
        return {
            "descriptor": descriptor,
            "raw": raw,
            "identity": identity,
            "seals": seals,
            "dirfd": dirfd,
            "parent": parent,
            "parent_identity": parent_identity,
            "probe_deadline": probe_deadline,
        }
    except BaseException:
        os.close(descriptor)
        raise


def _supervisor_report_alias(name: str) -> bool:
    return (
        name == "supervisor-report.json"
        or name.startswith(".supervisor-report.")
        or (name.endswith("-report.json") and name != "runner-report.json")
    )


def _purge_supervisor_report_aliases(dirfd: int) -> list[str]:
    removed: list[str] = []
    for name in os.listdir(dirfd):
        if not _supervisor_report_alias(name):
            continue
        try:
            row = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        try:
            if stat.S_ISDIR(row.st_mode):
                os.rmdir(name, dir_fd=dirfd)
            else:
                os.unlink(name, dir_fd=dirfd)
        except FileNotFoundError:
            continue
        removed.append(name)
    residual = [name for name in os.listdir(dirfd) if _supervisor_report_alias(name)]
    if residual:
        raise RuntimeError(f"supervisor report aliases remain: {sorted(residual)!r}")
    return sorted(removed)


def consume_supervisor_report(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Consume one sealed descriptor binding and return serializable evidence."""
    descriptor = binding.get("descriptor")
    if type(descriptor) is not int:
        raise RuntimeError("supervisor envelope descriptor binding rejected")
    dirfd = binding["dirfd"]
    deadline = binding["probe_deadline"]
    try:
        if deadline is not None:
            _probe_check_deadline(deadline, "publication:retained_pread")
        expected_raw = binding["raw"]
        expected_identity = binding["identity"]
        chunks: list[bytes] = []
        offset = 0
        while offset < len(expected_raw):
            if deadline is not None:
                _probe_check_deadline(deadline, "publication:retained_pread")
            block = os.pread(descriptor, min(1 << 20, len(expected_raw) - offset), offset)
            if not block:
                raise RuntimeError("supervisor envelope retained descriptor ended early")
            chunks.append(block)
            offset += len(block)
        exact = b"".join(chunks)
        retained = os.fstat(descriptor)
        identity = (
            int(retained.st_dev), int(retained.st_ino), stat.S_IFMT(retained.st_mode),
            stat.S_IMODE(retained.st_mode), int(retained.st_uid), int(retained.st_nlink),
        )
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        named_parent = os.lstat(binding["parent"])
        current_parent_identity = (
            int(named_parent.st_dev), int(named_parent.st_ino),
            stat.S_IMODE(named_parent.st_mode), int(named_parent.st_uid),
        )
        if (
            exact != expected_raw
            or identity != expected_identity
            or retained.st_size != len(expected_raw)
            or seals != binding["seals"]
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
            or current_parent_identity != binding["parent_identity"]
        ):
            raise RuntimeError("supervisor descriptor envelope final replay failed")
        removed_aliases = _purge_supervisor_report_aliases(dirfd)
        if deadline is not None:
            _probe_check_deadline(deadline, "publication:after_descriptor_replay")
        completed = time.monotonic()
        elapsed: float | None = None
        if deadline is not None:
            elapsed = completed - (deadline - PROBE_HARD_WALL_SECONDS)
            if (
                not math.isfinite(elapsed)
                or elapsed < 0
                or completed >= deadline
                or elapsed >= PROBE_HARD_WALL_SECONDS
            ):
                raise TimeoutError("probe envelope completed outside absolute wall")
        return {
            "sha256": sha256(exact).hexdigest(),
            "size": len(exact),
            "device": identity[0],
            "inode": identity[1],
            "seals": seals,
            "verification_transport": "sealed_memfd_creation_binding_retained_fd_pread",
            "authoritative_path": None,
            "named_publication": False,
            "removed_untrusted_aliases": removed_aliases,
            "publication_completed_elapsed_seconds": elapsed,
        }
    finally:
        os.close(descriptor)


def _private_directory(
    prefix: str,
) -> tuple[Path, int, tuple[int, int, int, int]]:
    for _attempt in range(32):
        name = (
            datetime.now(UTC).strftime(prefix + "-%Y%m%dT%H%M%SZ-")
            + uuid.uuid4().hex[:16]
        )
        path = Path("/tmp") / name
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            continue
        descriptor = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        )
        row = os.fstat(descriptor)
        identity = (
            int(row.st_dev),
            int(row.st_ino),
            stat.S_IMODE(row.st_mode),
            int(row.st_uid),
        )
        if identity[2:] != (0o700, os.getuid()):
            os.close(descriptor)
            raise RuntimeError("private run directory contract rejected")
        return path, descriptor, identity
    raise RuntimeError("unable to allocate private run directory")


def _private_run_directory() -> tuple[Path, int, tuple[int, int, int, int]]:
    return _private_directory("planora-puproj-frontier-v19-run")


def _private_runtime_directory() -> tuple[Path, int, tuple[int, int, int, int]]:
    return _private_directory("planora-puproj-frontier-v19-runtime")


def minimal_child_environment(
    *,
    captures: Mapping[str, Any],
    output_binding: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    scratch_dir: Path,
) -> dict[str, str]:
    pycache_prefix = str(Path(str(output_binding["path"])) / ".pycache-v19")
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(scratch_dir),
        CAPTURE_MANIFEST_ENV: json.dumps(
            captures, sort_keys=True, separators=(",", ":")
        ),
        OUTPUT_BINDING_ENV: json.dumps(
            output_binding, sort_keys=True, separators=(",", ":")
        ),
        RUNTIME_BUNDLE_ENV: json.dumps(
            runtime_binding, sort_keys=True, separators=(",", ":")
        ),
        PYCACHE_PREFIX_ENV: pycache_prefix,
    }


def run_supervised() -> dict[str, Any]:
    supervisor_start = supervisor_execution_sha256()
    supervisor_contract_start = verify_current_supervisor_contract()
    resource.setrlimit(
        resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES)
    )
    launcher_contract_start = verify_external_launcher_contract()
    freeze_manifest_start = verify_external_freeze_manifest_contract()
    system_python_start = verify_system_python_provenance(phase="run_start")
    baseline = host_sample()
    initial_whole_rss, initial_whole_swap, initial_whole_pids = whole_launch_usage(
        os.getpid(), None
    )
    initial = (
        "host_initial_capture_headroom"
        if baseline["mem_available_kib"] < INITIAL_MIN_MEM_AVAILABLE_KIB
        else whole_launch_breach(initial_whole_rss, initial_whole_swap)
        or breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=baseline,
            launch=True,
        )
    )
    if initial is not None:
        return {
            "status": "NO_GO",
            "resource_gate": initial,
            "host_sample": baseline,
            "official_instance_opened": False,
            "solver_child_process_started": False,
            "solver_execution_started": False,
            "official_solution_xml_published": False,
        }
    captures: dict[str, dict[str, Any]] = {}
    inherited: list[int] = []
    run_dir_fd = -1
    runtime_initial_fd = -1
    scratch_fd = -1
    stdout_fd = -1
    stderr_fd = -1
    barrier_read_fd = -1
    barrier_write_fd = -1
    try:
        for label, path in CAPTURE_SOURCES.items():
            capture_whole_rss, capture_whole_swap, _capture_whole_pids = (
                whole_launch_usage(os.getpid(), None)
            )
            capture_whole_gate = whole_launch_breach(
                capture_whole_rss, capture_whole_swap
            )
            if capture_whole_gate is not None:
                raise MemoryError(capture_whole_gate)
            descriptor, evidence = _stream_capture(path, _expected_hash(label), label)
            inherited.append(descriptor)
            captures[label] = evidence
        after_capture = host_sample()
        capture_gate = breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=after_capture,
            launch=True,
        )
        if capture_gate is not None:
            return {
                "status": "NO_GO",
                "resource_gate": capture_gate,
                "host_sample": after_capture,
                "official_instance_opened": True,
                "solver_child_process_started": False,
                "solver_execution_started": False,
                "official_solution_xml_published": False,
            }
        run_dir, run_dir_fd, run_dir_identity = _private_run_directory()
        inherited.append(run_dir_fd)
        scratch_dir, scratch_fd, scratch_identity = _private_directory(
            "planora-puproj-frontier-v19-scratch"
        )
        inherited.append(scratch_fd)
        runtime_dir, runtime_initial_fd, _runtime_initial_identity = (
            _private_runtime_directory()
        )
        (
            runtime_root_fd,
            runtime_manifest_fd,
            runtime_file_fds,
            runtime_binding,
            runtime_summary,
        ) = build_runtime_bundle(
            runtime_root_fd=runtime_initial_fd,
            captures=captures,
        )
        os.close(runtime_initial_fd)
        runtime_initial_fd = -1
        inherited.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        named_runtime = os.lstat(runtime_dir)
        if (
            int(named_runtime.st_dev),
            int(named_runtime.st_ino),
            stat.S_IMODE(named_runtime.st_mode),
            int(named_runtime.st_uid),
        ) != tuple(runtime_binding["root_identity"]):
            raise RuntimeError("sealed runtime named root final replay failed")
        runtime_summary["directory"] = str(runtime_dir)
        output_binding = {
            "fd": run_dir_fd,
            "path": str(run_dir),
            "device": run_dir_identity[0],
            "inode": run_dir_identity[1],
            "mode": run_dir_identity[2],
            "uid": run_dir_identity[3],
        }
        environment = minimal_child_environment(
            captures=captures,
            output_binding=output_binding,
            runtime_binding=runtime_binding,
            scratch_dir=scratch_dir,
        )
        pycache_prefix = run_dir / ".pycache-v19"
        barrier_read_fd, barrier_write_fd = os.pipe2(os.O_CLOEXEC)
        command = planned_command(
            captures["python_binary"]["fd"],
            captures["runner"]["fd"],
            runtime_root_fd,
            barrier_read_fd,
            pycache_prefix,
        )
        stdout_fd = os.open(
            "child.stdout.log",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
            dir_fd=run_dir_fd,
        )
        stderr_fd = os.open(
            "child.stderr.log",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
            dir_fd=run_dir_fd,
        )
        prechild_whole_rss, prechild_whole_swap, prechild_whole_pids = (
            whole_launch_usage(os.getpid(), None)
        )
        prechild_whole_gate = whole_launch_breach(
            prechild_whole_rss, prechild_whole_swap
        )
        if prechild_whole_gate is not None:
            raise MemoryError(prechild_whole_gate)
        parent_pid = os.getpid()
        signal_state: dict[str, int | None] = {"signal": None}
        previous = _signal_handlers(signal_state)
        _enable_subreaper()
        started = time.monotonic()
        child = subprocess.Popen(
            command,
            pass_fds=tuple((*inherited, barrier_read_fd)),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_fd,
            stderr=stderr_fd,
            close_fds=True,
            preexec_fn=lambda: _arm_child(parent_pid),
        )
        process_group = child.pid
        os.close(barrier_read_fd)
        barrier_read_fd = -1
        ownership = create_owned_group(process_group)
        os.write(barrier_write_fd, b"G")
        os.close(barrier_write_fd)
        barrier_write_fd = -1
        peak_rss = 0
        peak_vmswap = 0
        peak_pids: tuple[int, ...] = ()
        if (
            prechild_whole_rss + prechild_whole_swap
            >= initial_whole_rss + initial_whole_swap
        ):
            peak_whole_rss = prechild_whole_rss
            peak_whole_vmswap = prechild_whole_swap
            peak_whole_pids = prechild_whole_pids
        else:
            peak_whole_rss = initial_whole_rss
            peak_whole_vmswap = initial_whole_swap
            peak_whole_pids = initial_whole_pids
        breach = None
        stop_action = None
        group_cleanup: dict[str, Any] | None = None
        supervision_error: str | None = None
        child_exit_code = -1
        observed_child_elapsed = 0.0
        try:
            if POST_POPEN_ADMISSION_TEST_HOOK is not None:
                POST_POPEN_ADMISSION_TEST_HOOK(child, process_group)
            while child.poll() is None:
                sample = host_sample()
                elapsed = time.monotonic() - started
                rss, vmswap, pids = owned_group_usage(ownership)
                whole_rss, whole_vmswap, whole_pids = whole_owned_launch_usage(
                    os.getpid(), ownership
                )
                if rss + vmswap > peak_rss + peak_vmswap:
                    peak_pids = pids
                peak_rss = max(peak_rss, rss)
                peak_vmswap = max(peak_vmswap, vmswap)
                if whole_rss + whole_vmswap > peak_whole_rss + peak_whole_vmswap:
                    peak_whole_rss = whole_rss
                    peak_whole_vmswap = whole_vmswap
                    peak_whole_pids = whole_pids
                if signal_state["signal"] is not None:
                    breach = f"supervisor_signal:{signal_state['signal']}"
                else:
                    breach = whole_launch_breach(
                        whole_rss, whole_vmswap
                    ) or breach_reason(
                        elapsed=elapsed,
                        group_rss_kib=rss,
                        group_vmswap_kib=vmswap,
                        sample=sample,
                        launch=False,
                    )
                if breach is not None:
                    stop_action = signal_owned_members(ownership, signal.SIGTERM)
                    break
                time.sleep(POLL_SECONDS)
        except Exception as exc:
            supervision_error = f"supervision:{type(exc).__name__}:{exc}"
        finally:
            observed_child_elapsed = time.monotonic() - started
            child_exit_code, wait_error, group_cleanup = wait_child_and_drain(
                child, ownership, timeout=5
            )
            if wait_error is not None:
                supervision_error = wait_error
            for signum, handler in previous.items():
                try:
                    signal.signal(signum, handler)
                except Exception as exc:
                    group_cleanup["errors"].append(
                        f"restore_signal:{signum}:{type(exc).__name__}:{exc}"
                    )
                    group_cleanup["empty"] = False
        os.close(stdout_fd)
        stdout_fd = -1
        os.close(stderr_fd)
        stderr_fd = -1
        status, errors, artifacts = child_acceptance_v19(
            dirfd=run_dir_fd,
            run_dir=run_dir,
            child_exit_code=child_exit_code,
            observed_child_elapsed_seconds=observed_child_elapsed,
        )
        solver_return_proven = status in {
            "COMPLETE_VALID",
            "CONTROLLED_UNKNOWN",
        }
        if supervision_error is not None:
            errors.append(supervision_error)
            status = "FAILED"
        if breach is not None:
            errors.append(f"resource_or_signal_breach:{breach}")
            status = "FAILED"
        if not group_cleanup["empty"]:
            errors.append("process_group_cleanup_incomplete")
            status = "FAILED"
        scratch_names = sorted(
            entry.name for entry in os.scandir(f"/proc/self/fd/{scratch_fd}")
        )
        scratch_named = os.lstat(scratch_dir)
        scratch_final_identity = (
            int(scratch_named.st_dev),
            int(scratch_named.st_ino),
            stat.S_IMODE(scratch_named.st_mode),
            int(scratch_named.st_uid),
        )
        if scratch_names or scratch_final_identity != scratch_identity:
            errors.append("private_scratch_contract_rejected")
            status = "FAILED"
        capture_end = {
            label: verify_sealed_capture(int(evidence["fd"]), evidence)
            for label, evidence in captures.items()
        }
        runtime_bundle_end = replay_runtime_bundle(runtime_binding)
        runtime_named_end = os.lstat(runtime_dir)
        if (
            int(runtime_named_end.st_dev),
            int(runtime_named_end.st_ino),
            stat.S_IMODE(runtime_named_end.st_mode),
            int(runtime_named_end.st_uid),
        ) != tuple(runtime_binding["root_identity"]):
            errors.append("sealed_runtime_named_root_drift")
            status = "FAILED"
        source_end = {
            label: verify_source_contract(evidence)
            for label, evidence in captures.items()
        }
        if (
            verify_current_supervisor_contract() != supervisor_contract_start
            or supervisor_execution_sha256() != supervisor_start
        ):
            errors.append("supervisor_contract_drift")
            status = "FAILED"
        if verify_external_launcher_contract() != launcher_contract_start:
            errors.append("launcher_contract_drift")
            status = "FAILED"
        if verify_external_freeze_manifest_contract() != freeze_manifest_start:
            errors.append("freeze_manifest_contract_drift")
            status = "FAILED"
        system_python_end = verify_system_python_provenance(phase="run_end")
        system_python_comparison = compare_system_python_provenance(
            system_python_start, system_python_end
        )
        final_host = host_sample()
        payload = {
            "schema": "planora.pu-proj.frontier-joint-v19-supervisor.v1",
            "status": status,
            "errors": errors,
            "breach": breach,
            "stop_action": stop_action,
            "child_exit_code": child_exit_code,
            "observed_child_elapsed_seconds": observed_child_elapsed,
            "child_acceptance_cooperative_deadline_seconds": CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS,
            "supervisor_hard_wall_seconds": SUPERVISOR_HARD_WALL_SECONDS,
            "peak_process_group_rss_kib": peak_rss,
            "peak_process_group_vmswap_kib": peak_vmswap,
            "peak_process_group_pids": list(peak_pids),
            "initial_whole_launch_rss_kib": initial_whole_rss,
            "initial_whole_launch_vmswap_kib": initial_whole_swap,
            "initial_whole_launch_pids": list(initial_whole_pids),
            "prechild_whole_launch_rss_kib": prechild_whole_rss,
            "prechild_whole_launch_vmswap_kib": prechild_whole_swap,
            "prechild_whole_launch_pids": list(prechild_whole_pids),
            "peak_whole_launch_rss_kib": peak_whole_rss,
            "peak_whole_launch_vmswap_kib": peak_whole_vmswap,
            "peak_whole_launch_vmrss_plus_vmswap_kib": peak_whole_rss
            + peak_whole_vmswap,
            "peak_whole_launch_pids": list(peak_whole_pids),
            "whole_launch_memory_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
            "whole_launch_pid_union_no_double_count": True,
            "process_group_cleanup": group_cleanup,
            "process_group_rss_limit_kib": PROCESS_GROUP_RSS_LIMIT_KIB,
            "process_group_vmswap_limit_kib": PROCESS_GROUP_VMSWAP_LIMIT_KIB,
            "runtime_mem_available_floor_kib": RUNTIME_MIN_MEM_AVAILABLE_KIB,
            "host_swap_telemetry_only": {
                "start_pswpin_pages": baseline["pswpin_pages"],
                "start_pswpout_pages": baseline["pswpout_pages"],
                "end_pswpin_pages": final_host["pswpin_pages"],
                "end_pswpout_pages": final_host["pswpout_pages"],
                "used_as_kill_gate": False,
            },
            "run_directory": str(run_dir),
            "run_directory_identity": list(run_dir_identity),
            "scratch_directory": str(scratch_dir),
            "scratch_directory_identity": list(scratch_identity),
            "scratch_directory_final_entries": scratch_names,
            "sealed_runtime_bundle": runtime_summary,
            "sealed_runtime_bundle_final_replay": runtime_bundle_end,
            "command": command,
            "artifacts": artifacts,
            "sealed_captures": capture_end,
            "final_source_rehash": source_end,
            "supervisor_sha256": supervisor_start,
            "native_bootstrap_and_launcher": launcher_contract_start,
            "native_bootstrap_freeze_manifest": freeze_manifest_start,
            "system_python_provenance_start": system_python_start,
            "system_python_provenance_end": system_python_end,
            "system_python_provenance_comparison": system_python_comparison,
            "official_instance_opened": True,
            "probe_child_process_started": True,
            "solver_child_process_started": False,
            "solver_execution_started": solver_return_proven,
            "admissible_as_solution": status == "COMPLETE_VALID",
            "official_solution_xml_published": status == "COMPLETE_VALID",
        }
        report_binding = publish_supervisor_report(
            dirfd=run_dir_fd,
            parent=run_dir,
            parent_identity=run_dir_identity,
            payload=payload,
        )
        report_evidence = consume_supervisor_report(report_binding)
        payload["supervisor_descriptor_envelope_evidence"] = report_evidence
        return payload
    finally:
        if barrier_write_fd >= 0:
            try:
                os.close(barrier_write_fd)
            except OSError:
                pass
        if barrier_read_fd >= 0:
            try:
                os.close(barrier_read_fd)
            except OSError:
                pass
        if stdout_fd >= 0:
            os.close(stdout_fd)
        if stderr_fd >= 0:
            os.close(stderr_fd)
        if runtime_initial_fd >= 0:
            os.close(runtime_initial_fd)
        for descriptor in inherited:
            try:
                os.close(descriptor)
            except OSError:
                pass


def static_pins() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for label, path in CAPTURE_SOURCES.items():
        if label == "full_instance":
            continue
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            digest = sha256()
            offset = 0
            while offset < before.st_size:
                block = os.pread(
                    descriptor, min(1 << 20, before.st_size - offset), offset
                )
                if not block:
                    raise RuntimeError("static pin ended early")
                digest.update(block)
                offset += len(block)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        actual = digest.hexdigest()
        if _stable_identity(before) != _stable_identity(
            after
        ) or actual != _expected_hash(label):
            raise RuntimeError(f"static pin drift: {label}")
        rows[label] = {
            "path": str(path),
            "sha256": actual,
            "size": int(after.st_size),
            "identity": list(_stable_identity(after)),
        }
    return rows


def self_test() -> dict[str, Any]:
    sample = {
        "mem_available_kib": 2_000_000,
        "swap_free_kib": 1_000_000,
        "pswpin_pages": 100,
        "pswpout_pages": 200,
    }
    if (
        breach_reason(
            elapsed=0,
            group_rss_kib=PROCESS_GROUP_RSS_LIMIT_KIB,
            group_vmswap_kib=0,
            sample=sample,
            launch=False,
        )
        != "process_group_rss_limit"
    ):
        raise AssertionError("RSS limit not enforced")
    if (
        breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=PROCESS_GROUP_VMSWAP_LIMIT_KIB,
            sample=sample,
            launch=False,
        )
        != "process_group_vmswap_limit"
    ):
        raise AssertionError("VmSwap limit not enforced")
    if (
        breach_reason(
            elapsed=SUPERVISOR_HARD_WALL_SECONDS,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=sample,
            launch=False,
        )
        != "supervisor_hard_wall"
    ):
        raise AssertionError("hard wall not enforced")
    if (
        whole_launch_breach(WHOLE_LAUNCH_MEMORY_LIMIT_KIB - 1, 1)
        != "whole_launch_vmrss_plus_vmswap_limit"
    ):
        raise AssertionError("whole-launch VmRSS+VmSwap limit not enforced")
    self_rss, self_swap, self_pids = whole_launch_usage(os.getpid(), os.getpgrp())
    if self_pids.count(os.getpid()) != 1:
        raise AssertionError("whole-launch PID union double-counted supervisor")
    command = planned_command(16, 17, 18, 19, Path("/tmp/nonexistent-private-pycache"))
    for flag in (
        "--execute-frontier",
        "--allow-official-input",
        "--allow-solver",
        "--allow-publication",
    ):
        if flag not in command:
            raise AssertionError(f"planned command lost gate {flag}")
    return {
        "status": "PASS",
        "process_group_monitoring": True,
        "pdeathsig": int(PARENT_DEATH_SIGNAL),
        "address_space_cap_bytes": ADDRESS_SPACE_CAP_BYTES,
        "initial_min_mem_available_kib": INITIAL_MIN_MEM_AVAILABLE_KIB,
        "child_acceptance_cooperative_deadline_seconds": CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS,
        "supervisor_hard_wall_seconds": SUPERVISOR_HARD_WALL_SECONDS,
        "process_group_rss_limit_kib": PROCESS_GROUP_RSS_LIMIT_KIB,
        "process_group_vmswap_limit_kib": PROCESS_GROUP_VMSWAP_LIMIT_KIB,
        "whole_launch_memory_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
        "whole_launch_vmrss_plus_vmswap_enforced": True,
        "whole_launch_pid_union_no_double_count": True,
        "self_test_whole_launch_rss_kib": self_rss,
        "self_test_whole_launch_vmswap_kib": self_swap,
        "self_test_whole_launch_pids": list(self_pids),
        "host_swap_counters_telemetry_only": True,
        "runner_execution": "sealed_memfd_exact_bytes",
        "repo_modules_execution": "sealed_memfd_exact_bytes",
        "official_instance_opened": False,
        "solver_execution_started": False,
        "solver_child_process_started": False,
        "official_solution_xml_published": False,
    }


def _probe_pid_evidence(ownership: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for member in _live_owned_members(ownership):
        pid = int(member["pid"])
        status = _read_key_values(Path(f"/proc/{pid}/status"))
        rows.append(
            {
                "pid": pid,
                "identity": list(member["identity"]),
                "vmrss_kib": status.get("VmRSS", 0),
                "vmswap_kib": status.get("VmSwap", 0),
            }
        )
    supervisor_pid = os.getpid()
    status = _read_key_values(Path(f"/proc/{supervisor_pid}/status"))
    identity = _process_identity(supervisor_pid)
    rows.append(
        {
            "pid": supervisor_pid,
            "identity": list(identity) if identity is not None else None,
            "vmrss_kib": status.get("VmRSS", 0),
            "vmswap_kib": status.get("VmSwap", 0),
        }
    )
    return sorted(rows, key=lambda row: row["pid"])


def sealed_import_probe() -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + PROBE_HARD_WALL_SECONDS
    _probe_check_deadline(deadline, "initial_sample:before")
    baseline = host_sample()
    _probe_check_deadline(deadline, "initial_sample:after")
    if baseline["mem_available_kib"] < PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB:
        return {
            "schema": "planora.puproj.frontier-joint-v19-sealed-import-probe.v1",
            "status": "NO_GO",
            "resource_gate": "probe_initial_memavailable_floor",
            "host_sample": baseline,
            "initial_memavailable_floor_kib": PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB,
            "official_instance_opened": False,
            "checkpoint_or_incumbent_opened": False,
            "solver_execution_started": False,
            "solver_child_process_started": False,
            "official_solution_xml_published": False,
            "chain_traversed": ["native_bootstrap", "sealed_launcher", "sealed_supervisor"],
            "_probe_started_monotonic_internal": started,
            "_probe_deadline_monotonic_internal": deadline,
        }
    captures: dict[str, dict[str, Any]] = {}
    inherited: list[int] = []
    run_dir_fd = scratch_fd = runtime_initial_fd = stdout_fd = stderr_fd = -1
    barrier_read_fd = barrier_write_fd = -1
    child: subprocess.Popen[bytes] | None = None
    ownership: dict[str, Any] | None = None
    drained = False
    try:
        for label, path in CAPTURE_SOURCES.items():
            if label == "full_instance":
                continue
            descriptor, evidence = _stream_capture(
                path, _expected_hash(label), label, probe_deadline=deadline
            )
            inherited.append(descriptor)
            captures[label] = evidence
        if "full_instance" in captures:
            raise RuntimeError("probe captured official input")
        _probe_check_deadline(deadline, "directories:before")
        run_dir, run_dir_fd, run_dir_identity = _private_run_directory()
        inherited.append(run_dir_fd)
        scratch_dir, scratch_fd, scratch_identity = _private_directory(
            "planora-puproj-frontier-v19-probe-scratch"
        )
        inherited.append(scratch_fd)
        runtime_dir, runtime_initial_fd, _ = _private_runtime_directory()
        (
            runtime_root_fd, runtime_manifest_fd, runtime_file_fds,
            runtime_binding, runtime_summary,
        ) = build_runtime_bundle(
            runtime_root_fd=runtime_initial_fd,
            captures=captures,
            probe_mode=True,
            probe_deadline=deadline,
        )
        os.close(runtime_initial_fd)
        runtime_initial_fd = -1
        inherited.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        output_binding = {
            "fd": run_dir_fd, "path": str(run_dir),
            "device": run_dir_identity[0], "inode": run_dir_identity[1],
            "mode": run_dir_identity[2], "uid": run_dir_identity[3],
        }
        environment = minimal_child_environment(
            captures=captures, output_binding=output_binding,
            runtime_binding=runtime_binding, scratch_dir=scratch_dir,
        )
        barrier_read_fd, barrier_write_fd = os.pipe2(os.O_CLOEXEC)
        command = planned_command(
            captures["python_binary"]["fd"], captures["runner"]["fd"],
            runtime_root_fd, barrier_read_fd, run_dir / ".pycache-v19",
            sealed_import_probe=True,
        )
        _probe_check_deadline(deadline, "child_descriptors:before")
        stdout_fd = os.open(
            "child.stdout.log", os.O_RDWR | os.O_CREAT | os.O_EXCL |
            getattr(os, "O_NOFOLLOW", 0), 0o400, dir_fd=run_dir_fd,
        )
        stderr_fd = os.open(
            "child.stderr.log", os.O_RDWR | os.O_CREAT | os.O_EXCL |
            getattr(os, "O_NOFOLLOW", 0), 0o400, dir_fd=run_dir_fd,
        )
        parent_pid = os.getpid()
        _enable_subreaper()
        _probe_check_deadline(deadline, "child_spawn:before")
        child = subprocess.Popen(
            command, pass_fds=tuple((*inherited, barrier_read_fd)),
            env=environment, stdin=subprocess.DEVNULL, stdout=stdout_fd,
            stderr=stderr_fd, close_fds=True,
            preexec_fn=lambda: _arm_child(parent_pid),
        )
        process_group = child.pid
        os.close(barrier_read_fd)
        barrier_read_fd = -1
        ownership = create_owned_group(process_group)
        os.write(barrier_write_fd, b"G")
        os.close(barrier_write_fd)
        barrier_write_fd = -1
        monitor_result = monitor_probe_child(child, ownership, deadline=deadline)
        drained = True
        breach = monitor_result["breach"]
        monitor_error = monitor_result["monitor_error"]
        peak_snapshot = monitor_result["peak_snapshot"]
        child_exit_code = monitor_result["child_exit_code"]
        wait_error = monitor_result["wait_error"]
        cleanup = monitor_result["cleanup"]
        _probe_check_deadline(deadline, "cleanup:after")
        if peak_snapshot is None:
            peak_snapshot = probe_accounting_snapshot(os.getpid(), ownership)
        stdout_raw, stdout_identity = _pread_retained_named(
            run_dir_fd,
            "child.stdout.log",
            stdout_fd,
            maximum_bytes=PROBE_CAPTURE_MAX_BYTES,
            probe_deadline=deadline,
        )
        stderr_raw, stderr_identity = _pread_retained_named(
            run_dir_fd,
            "child.stderr.log",
            stderr_fd,
            maximum_bytes=PROBE_CAPTURE_MAX_BYTES,
            probe_deadline=deadline,
        )
        _probe_check_deadline(deadline, "child_report:before")
        child_report, child_report_rejection, child_stream_diagnostics = (
            diagnose_probe_child_report(
                stdout_raw,
                stderr_raw,
                child_exit_code=child_exit_code,
            )
        )
        _probe_check_deadline(deadline, "child_report:after")
        capture_replay = {
            label: verify_sealed_capture(
                int(value["fd"]), value, probe_deadline=deadline
            )
            for label, value in captures.items()
        }
        runtime_replay = replay_runtime_bundle(
            runtime_binding, probe_deadline=deadline
        )
        errors: list[str] = []
        if breach is not None:
            errors.append(breach)
        if wait_error is not None:
            errors.append(wait_error)
        if monitor_error is not None:
            errors.append(monitor_error)
        if child_exit_code != 0:
            errors.append("probe_child_failed")
        if not cleanup.get("empty", False):
            errors.append("probe_cleanup_incomplete")
        if child_report_rejection is not None:
            errors.append(
                "probe_child_report_" + child_report_rejection["classification"]
            )
        if child_report is not None and (
            runtime_replay.get("file_count") != runtime_summary.get("file_count")
            or runtime_replay.get("total_bytes") != runtime_summary.get("total_bytes")
            or child_report["runtime_bundle"].get("file_count")
            != runtime_replay.get("file_count")
            or child_report["runtime_bundle"].get("total_bytes")
            != runtime_replay.get("total_bytes")
        ):
            errors.append("probe_runtime_comparison_rejected")
        _probe_check_deadline(deadline, "payload:before")
        payload = {
            "schema": "planora.puproj.frontier-joint-v19-sealed-import-probe.v1",
            "status": "PASS" if not errors else "FAILED",
            "errors": errors,
            "resource_gate": breach,
            "elapsed_seconds_before_publication": time.monotonic() - started,
            "probe_hard_wall_seconds": PROBE_HARD_WALL_SECONDS,
            "initial_memavailable_floor_kib": PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB,
            "runtime_memavailable_floor_kib": PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB,
            "process_group_rss_limit_kib": PROBE_PROCESS_GROUP_RSS_LIMIT_KIB,
            "process_group_vmswap_limit_kib": PROBE_PROCESS_GROUP_VMSWAP_LIMIT_KIB,
            "whole_launch_vmrss_plus_vmswap_limit_kib": PROBE_WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
            "peak_process_group_rss_kib": peak_snapshot["group_rss_kib"],
            "peak_process_group_vmswap_kib": peak_snapshot["group_vmswap_kib"],
            "peak_whole_launch_rss_kib": peak_snapshot["whole_rss_kib"],
            "peak_whole_launch_vmswap_kib": peak_snapshot["whole_vmswap_kib"],
            "peak_whole_launch_vmrss_plus_vmswap_kib": peak_snapshot["whole_rss_kib"] + peak_snapshot["whole_vmswap_kib"],
            "peak_whole_launch_unique_pids": peak_snapshot["pids"],
            "peak_whole_launch_per_pid": peak_snapshot["per_pid"],
            "peak_accounting_snapshot_reconciled": peak_snapshot["reconciled"],
            "whole_launch_pid_union_no_double_count": True,
            "child_exit_code": child_exit_code,
            "child_report": child_report,
            "child_report_rejection": child_report_rejection,
            "child_stream_diagnostics": child_stream_diagnostics,
            "child_stdout": {**stdout_identity, "sha256": sha256(stdout_raw).hexdigest()},
            "child_stderr": {**stderr_identity, "sha256": sha256(stderr_raw).hexdigest()},
            "sealed_captures": {label: value["sha256"] for label, value in captures.items()},
            "sealed_capture_replay": capture_replay,
            "sealed_runtime_bundle": runtime_summary,
            "sealed_runtime_replay": runtime_replay,
            "process_group_cleanup": cleanup,
            "chain_traversed": ["native_bootstrap", "sealed_launcher", "sealed_supervisor", "sealed_runner_import_child"],
            "official_instance_opened": False,
            "checkpoint_or_incumbent_opened": False,
            "solver_execution_started": False,
            "solver_child_process_started": False,
            "probe_child_process_started": True,
            "official_solution_xml_published": False,
            "publication_order": ["child.stdout.log", "child.stderr.log", "stdout_final_envelope"],
        }
        try:
            binding = publish_supervisor_report(
                dirfd=run_dir_fd, parent=run_dir,
                parent_identity=run_dir_identity, payload=payload,
                probe_deadline=deadline,
            )
            report = consume_supervisor_report(binding)
            _probe_check_deadline(deadline, "publication:complete")
            final_elapsed = time.monotonic() - started
            if (
                _finite_elapsed(final_elapsed) is None
                or final_elapsed >= PROBE_HARD_WALL_SECONDS
                or _finite_elapsed(report.get("publication_completed_elapsed_seconds")) is None
                or report["publication_completed_elapsed_seconds"] > final_elapsed
            ):
                raise TimeoutError("probe final publication elapsed rejected")
        except BaseException:
            _purge_supervisor_report_aliases(run_dir_fd)
            raise
        payload["final_elapsed_through_descriptor_acceptance_seconds"] = final_elapsed
        payload["publication_deadline_accepted"] = True
        payload["probe_descriptor_envelope_evidence"] = report
        payload["_probe_started_monotonic_internal"] = started
        payload["_probe_deadline_monotonic_internal"] = deadline
        return payload
    finally:
        if child is not None and ownership is not None and not drained:
            try:
                wait_child_and_drain(
                    child,
                    ownership,
                    timeout=max(0.0, min(5.0, deadline - time.monotonic())),
                )
            except BaseException:
                pass
        for descriptor in (barrier_write_fd, barrier_read_fd, stdout_fd, stderr_fd, runtime_initial_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        for descriptor in inherited:
            try:
                os.close(descriptor)
            except OSError:
                pass


def dry_run() -> dict[str, Any]:
    sample = host_sample()
    whole_rss, whole_swap, whole_pids = whole_launch_usage(os.getpid(), None)
    gate = (
        "host_initial_capture_headroom"
        if sample["mem_available_kib"] < INITIAL_MIN_MEM_AVAILABLE_KIB
        else whole_launch_breach(whole_rss, whole_swap)
        or breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=sample,
            launch=True,
        )
    )
    return {
        "status": "GO_FOR_INDEPENDENT_REVIEW" if gate is None else "NO_GO",
        "resource_gate": gate,
        "host_sample": sample,
        "static_pins_excluding_official_full_input": static_pins(),
        "expected_full_official_input_sha256": EXPECTED_HASHES["full_instance"],
        "full_official_input_path": str(FULL_INSTANCE),
        "full_official_input_opened": False,
        "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        "checkpoint_or_incumbent_path_configured": False,
        "checkpoint_or_incumbent_opened": False,
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
        "run_directory_created": False,
        "solver_execution_started": False,
        "solver_child_process_started": False,
        "official_solution_xml_published": False,
        "launch_requires_explicit_flag": "--launch",
        "child_acceptance_cooperative_deadline_seconds": CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS,
        "supervisor_hard_wall_seconds": SUPERVISOR_HARD_WALL_SECONDS,
        "initial_min_mem_available_kib": INITIAL_MIN_MEM_AVAILABLE_KIB,
        "sealed_runtime_bundle_expected_files": EXPECTED_RUNTIME_BUNDLE_FILES,
        "sealed_runtime_bundle_expected_bytes": EXPECTED_RUNTIME_BUNDLE_BYTES,
        "whole_launch_rss_kib": whole_rss,
        "whole_launch_vmswap_kib": whole_swap,
        "whole_launch_vmrss_plus_vmswap_kib": whole_rss + whole_swap,
        "whole_launch_pids": list(whole_pids),
        "whole_launch_memory_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
        "whole_launch_pid_union_no_double_count": True,
    }


def main() -> int:
    if globals().get(
        "__external_loader_protocol__"
    ) != EXTERNAL_LOADER_PROTOCOL or globals().get(
        "__external_expected_supervisor_sha256__"
    ) != globals().get("__captured_sha256__"):
        raise SystemExit("direct PU-PROJ v19 supervisor execution rejected")
    verify_current_supervisor_contract()
    entry_launcher = verify_external_launcher_contract()
    entry_freeze_manifest = verify_external_freeze_manifest_contract()
    entry_system_python = verify_system_python_provenance(phase="entry")
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--sealed-import-probe", action="store_true")
    modes.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    start_hash = supervisor_execution_sha256()
    start_contract = verify_current_supervisor_contract()
    if args.self_test:
        result = self_test()
    elif args.dry_run:
        result = dry_run()
    elif args.sealed_import_probe:
        result = sealed_import_probe()
    else:
        result = run_supervised()
    if (
        supervisor_execution_sha256() != start_hash
        or verify_current_supervisor_contract() != start_contract
    ):
        raise RuntimeError("supervisor bytes/path changed during execution")
    final_launcher = verify_external_launcher_contract()
    if final_launcher != entry_launcher:
        raise RuntimeError("launcher source/sealed binding changed during execution")
    final_freeze_manifest = verify_external_freeze_manifest_contract()
    if final_freeze_manifest != entry_freeze_manifest:
        raise RuntimeError(
            "freeze-manifest source/sealed binding changed during execution"
        )
    final_system_python = verify_system_python_provenance(phase="final")
    system_python_comparison = compare_system_python_provenance(
        entry_system_python, final_system_python
    )
    result["supervisor_sha256_start"] = start_hash
    result["supervisor_sha256_end"] = start_hash
    result["supervisor_hash_stable"] = True
    result["supervisor_execution_transport"] = "external_captured_exact_bytes"
    result["native_bootstrap_launcher_entry"] = entry_launcher
    result["native_bootstrap_launcher_final"] = final_launcher
    result["native_bootstrap_freeze_manifest_entry"] = entry_freeze_manifest
    result["native_bootstrap_freeze_manifest_final"] = final_freeze_manifest
    result["system_python_provenance_entry"] = entry_system_python
    result["system_python_provenance_final"] = final_system_python
    result["system_python_provenance_comparison"] = system_python_comparison
    probe_started = result.pop("_probe_started_monotonic_internal", None)
    probe_deadline = result.pop("_probe_deadline_monotonic_internal", None)
    if args.sealed_import_probe:
        if type(probe_started) is not float or type(probe_deadline) is not float:
            raise RuntimeError("probe final stdout deadline binding rejected")
        before_stdout_elapsed = time.monotonic() - probe_started
        if (
            not math.isfinite(before_stdout_elapsed)
            or before_stdout_elapsed < 0
            or before_stdout_elapsed >= PROBE_HARD_WALL_SECONDS
            or time.monotonic() >= probe_deadline
        ):
            raise TimeoutError("probe final stdout envelope outside absolute wall")
        result["final_elapsed_before_stdout_envelope_seconds"] = before_stdout_elapsed
        result["final_stdout_envelope_deadline_bound"] = True
    final_envelope = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    written = sys.stdout.buffer.write(final_envelope)
    sys.stdout.buffer.flush()
    if written != len(final_envelope):
        raise RuntimeError("final stdout envelope short write")
    if args.sealed_import_probe:
        _probe_check_deadline(probe_deadline, "stdout:after_final_envelope")
    return (
        0
        if result.get("status")
        in {"PASS", "GO_FOR_INDEPENDENT_REVIEW", "COMPLETE_VALID", "CONTROLLED_UNKNOWN"}
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
