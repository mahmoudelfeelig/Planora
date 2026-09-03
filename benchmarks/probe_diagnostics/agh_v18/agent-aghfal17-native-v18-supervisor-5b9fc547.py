#!/usr/bin/env python3
"""Exact-byte process-group supervisor for AGH-FAL17 native v11."""

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
import time
from typing import Any, Mapping
import uuid
from xml.etree import ElementTree


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
SITE_PACKAGES = ROOT / ".venv/lib/python3.12/site-packages"
RUNNER = Path("/tmp/agent-aghfal17-native-v18-runner-5b9fc547.py")
GENERIC_VALIDATOR = Path("/tmp/agent-aghfal17-native-v18-generic-validator.py")
STDLIB_MANIFEST = Path("/tmp/agent-aghfal17-native-v18-stdlib.sha256")
MINIMAL_TCB_MANIFEST = Path("/tmp/agent-aghfal17-native-v18-minimal-tcb.sha256")
OFFICIAL_INSTANCE = (
    ROOT
    / "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/agh-fal17.xml"
)
PLANORA_SOURCES = {
    "planora_benchmarks_init": ROOT / "benchmarks/__init__.py",
    "planora_benchmarks_corpus": ROOT / "benchmarks/corpus.py",
    "planora_itc2019": ROOT / "benchmarks/itc2019.py",
    "planora_itc2019_compact_joint": ROOT / "benchmarks/itc2019_compact_joint.py",
    "planora_itc2019_decomposed": ROOT / "benchmarks/itc2019_decomposed.py",
    "planora_itc2019_decomposed_quality": ROOT
    / "benchmarks/itc2019_decomposed_quality.py",
    "planora_itc2019_factorized": ROOT / "benchmarks/itc2019_factorized.py",
    "planora_itc2019_generalized_occurrences": ROOT
    / "benchmarks/itc2019_generalized_occurrences.py",
    "planora_itc2019_global_components": ROOT
    / "benchmarks/itc2019_global_components.py",
    "planora_itc2019_global_quality": ROOT / "benchmarks/itc2019_global_quality.py",
    "planora_itc2019_grouped_calendar": ROOT / "benchmarks/itc2019_grouped_calendar.py",
    "planora_itc2019_resource_seed": ROOT / "benchmarks/itc2019_resource_seed.py",
    "planora_itc2019_sparse_joint": ROOT / "benchmarks/itc2019_sparse_joint.py",
    "planora_itc2019_structural": ROOT / "benchmarks/itc2019_structural.py",
    "planora_itc2019_violation_lns": ROOT / "benchmarks/itc2019_violation_lns.py",
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
    "4fccaaae750a26475214d888bd6a67c0efeec781309590886f8b42e3002bb752"
)
EXPECTED_HASHES = {
    "official_instance": "bae3363ed68e895280cd33bc20686bf396932f532c2b197f7b863f4167437528",
    "generic_validator": "a7e45885980368d56083e321749337dcaf3fca8ef1e2a2c984181df9c5d6a89c",
    "stdlib_manifest": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "minimal_tcb_manifest": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "planora_benchmarks_init": "be6f5557e4565d1de24b4ced5a56a610fd935fc8320f1ffe5014255a59e3b84a",
    "planora_benchmarks_corpus": "74d23c0940713b8a40a9f789d4c0ece7402e5d9b81514587d3015d497d4112b3",
    "planora_itc2019": "5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f",
    "planora_itc2019_compact_joint": "427264334276fb48ce5b54c151a42d4a85b75055c0bea96f47a928b1fe28362a",
    "planora_itc2019_decomposed": "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
    "planora_itc2019_decomposed_quality": "534622d096728ff4e4e9b53fd8d58ec3827ec09540d4c95a3e3dcad271c7f78b",
    "planora_itc2019_factorized": "959be9e028773492538c4a541892955d37c5cdeb02cfaa762d8b9ce3fff48f02",
    "planora_itc2019_generalized_occurrences": "7ed4224c0f338f9f983a358babb5dfdb6b90d5026383283cd0d805aef733d85f",
    "planora_itc2019_global_components": "c2d158dc9434f8da4f3e9478b1526face365702cf317fd14e693af75769e7f11",
    "planora_itc2019_global_quality": "397d308a4fb368aaab96db1789394e1b9f289a8f6b8d87b9ce5b4a569f8ccc7f",
    "planora_itc2019_grouped_calendar": "37b82b7f01fb47a655bb76ae0d6734315b00bf58ec7ebf28c66bb701c00a6ee5",
    "planora_itc2019_resource_seed": "8d497bc609ec5b717b0d9e2b77406e89c45c6eaef378148c0bebadd6a429d665",
    "planora_itc2019_sparse_joint": "2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2",
    "planora_itc2019_structural": "db4ac0adbfe38f1b618b2e8f7a5a9e5a613000a62034017819cca2c20640d024",
    "planora_itc2019_violation_lns": "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343",
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
CAPTURE_SOURCES = {
    "runner": RUNNER,
    "generic_validator": GENERIC_VALIDATOR,
    "stdlib_manifest": STDLIB_MANIFEST,
    "minimal_tcb_manifest": MINIMAL_TCB_MANIFEST,
    "official_instance": OFFICIAL_INSTANCE,
    "python_binary": PYTHON_BINARY,
    **PLANORA_SOURCES,
    **RUNTIME_RECORDS,
}
PROBE_CAPTURE_SOURCES = {
    "runner": RUNNER,
    "python_binary": PYTHON_BINARY,
    "stdlib_manifest": STDLIB_MANIFEST,
    **RUNTIME_RECORDS,
}

CAPTURE_MANIFEST_ENV = "AGHFAL_NATIVE_V18_CAPTURE_MANIFEST"
OUTPUT_BINDING_ENV = "AGHFAL_NATIVE_V18_OUTPUT_BINDING"
RUNTIME_BUNDLE_ENV = "AGHFAL_NATIVE_V18_RUNTIME_BUNDLE"
EXTERNAL_LOADER_PROTOCOL = "planora.aghfal17.native-v18-supervisor-loader.v1"
RUNNER_LOADER_PROTOCOL = "planora.aghfal17.native-v18-runner-loader.v1"
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)
LAUNCH_MIN_MEM_AVAILABLE_KIB = 1_900_000
INITIAL_MIN_MEM_AVAILABLE_KIB = 1_900_000
RUNTIME_MIN_MEM_AVAILABLE_KIB = 900_000
PROCESS_GROUP_MEMORY_LIMIT_KIB = 368_640
# Provisional 600 MiB whole-launch ceiling. It remains NO-GO for freeze until
# the sealed no-solver probe measures the actual supervisor+child baseline.
WHOLE_LAUNCH_MEMORY_LIMIT_KIB = 614_400
ADDRESS_SPACE_CAP_BYTES = 2_800_000_000
CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS = 1_680.0
SUPERVISOR_HARD_WALL_SECONDS = 1_780.0
POLL_SECONDS = 0.10
TERMINATION_GRACE_SECONDS = 1.0
SEALED_IMPORT_PROBE_HARD_WALL_SECONDS = 180.0
REJECTION_STDOUT_TAIL_BYTES = 4_096
REJECTION_STDERR_TAIL_BYTES = 4_096
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
PARENT_DEATH_SIGNAL = signal.SIGKILL
STOP_SIGNALS = tuple(
    dict.fromkeys(
        (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM))
    )
)
AT_FDCWD = -100
RENAME_NOREPLACE = 1
LIBC = ctypes.CDLL(None, use_errno=True)

RUNNER_FD_LOADER = r"""
import fcntl, hashlib, json, os, stat, sys
fd = int(sys.argv[1]); expected = sys.argv[2]; runtime_root_fd = int(sys.argv[3]); forwarded = sys.argv[4:]
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
runtime_binding=json.loads(os.environ["AGHFAL_NATIVE_V18_RUNTIME_BUNDLE"]); runtime_row=os.fstat(runtime_root_fd)
runtime_identity=(int(runtime_row.st_dev),int(runtime_row.st_ino),stat.S_IMODE(runtime_row.st_mode),int(runtime_row.st_uid))
if runtime_binding.get("root_fd") != runtime_root_fd or tuple(runtime_binding.get("root_identity",())) != runtime_identity or not stat.S_ISDIR(runtime_row.st_mode) or runtime_identity[2:] != (0o500,os.getuid()): raise RuntimeError("sealed runtime root binding rejected")
if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode: raise RuntimeError("Python isolation flags rejected")
captures=json.loads(os.environ["AGHFAL_NATIVE_V18_CAPTURE_MANIFEST"]); stdlib_fd=int(captures["stdlib_manifest"]["fd"]); stdlib_row=os.fstat(stdlib_fd); stdlib_raw=os.pread(stdlib_fd,stdlib_row.st_size,0)
if hashlib.sha256(stdlib_raw).hexdigest()!="355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327": raise RuntimeError("runner loader stdlib manifest drift")
stdlib={line.split("  ",1)[1]:line.split("  ",1)[0] for line in stdlib_raw.decode().splitlines()}
if len(stdlib)!=619: raise RuntimeError("runner loader stdlib cardinality drift")
root_ro=any(len(fields)>=6 and fields[4]=="/" and "ro" in fields[5].split(",") for fields in (line.split(" - ",1)[0].split() for line in open("/proc/self/mountinfo",encoding="utf-8")))
if not root_ro: raise RuntimeError("runner loader stdlib mount is not read-only")
for file_path,file_hash in stdlib.items():
 current=file_path
 while True:
  ownership=os.stat(current,follow_symlinks=False)
  if ownership.st_uid!=65534 or ownership.st_gid!=65534 or stat.S_IMODE(ownership.st_mode)&0o022: raise RuntimeError("runner loader stdlib permissions rejected")
  if current=="/": break
  current=os.path.dirname(current)
 file_fd=os.open(file_path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); file_row=os.fstat(file_fd); value=os.pread(file_fd,file_row.st_size,0); os.close(file_fd)
 if hashlib.sha256(value).hexdigest()!=file_hash: raise RuntimeError("runner loader stdlib file drift")
for module in tuple(sys.modules.values()):
 module_path=getattr(module,"__file__",None)
 if isinstance(module_path,str) and not module_path.startswith("<") and os.path.realpath(module_path).startswith("/usr/lib/python3.12/") and (os.path.realpath(module_path)!=module_path or module_path not in stdlib): raise RuntimeError("runner loader module outside stdlib manifest")
sys.path.insert(0,f"/proc/self/fd/{runtime_root_fd}")
sys.dont_write_bytecode=True; filename=f"<sealed-aghfal17-native-v18-runner:{actual}>"; sys.argv=[filename,*forwarded]
namespace={"__name__":"__main__","__file__":filename,"__package__":None,"__cached__":None,"__captured_sha256__":actual,"__runner_loader_protocol__":"planora.aghfal17.native-v18-runner-loader.v1"}
exec(compile(source,filename,"exec",dont_inherit=True),namespace)
"""
GENERIC_FD_LOADER = r"""
import fcntl, hashlib, json, os, stat, sys
fd=int(sys.argv[1]); expected=sys.argv[2]; runtime_root_fd=int(sys.argv[3]); forwarded=sys.argv[4:]
required=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
before=os.fstat(fd); chunks=[]; offset=0
if not stat.S_ISREG(before.st_mode) or int(fcntl.fcntl(fd,fcntl.F_GET_SEALS))&required!=required: raise RuntimeError("generic capture rejected")
while offset<before.st_size:
 block=os.pread(fd,min(1<<20,before.st_size-offset),offset)
 if not block: raise RuntimeError("generic capture ended early")
 chunks.append(block); offset+=len(block)
source=b"".join(chunks); actual=hashlib.sha256(source).hexdigest()
if actual!=expected or os.fstat(fd).st_ino!=before.st_ino: raise RuntimeError("generic capture drift")
if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode: raise RuntimeError("generic Python isolation rejected")
captures=json.loads(os.environ["AGHFAL_NATIVE_V18_CAPTURE_MANIFEST"]); stdlib_fd=int(captures["stdlib_manifest"]["fd"]); stdlib_row=os.fstat(stdlib_fd); stdlib_raw=os.pread(stdlib_fd,stdlib_row.st_size,0)
if hashlib.sha256(stdlib_raw).hexdigest()!="355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327": raise RuntimeError("generic loader stdlib manifest drift")
stdlib={line.split("  ",1)[1]:line.split("  ",1)[0] for line in stdlib_raw.decode().splitlines()}
if len(stdlib)!=619: raise RuntimeError("generic loader stdlib cardinality drift")
root_ro=any(len(fields)>=6 and fields[4]=="/" and "ro" in fields[5].split(",") for fields in (line.split(" - ",1)[0].split() for line in open("/proc/self/mountinfo",encoding="utf-8")))
if not root_ro: raise RuntimeError("generic loader stdlib mount is not read-only")
for file_path,file_hash in stdlib.items():
 current=file_path
 while True:
  ownership=os.stat(current,follow_symlinks=False)
  if ownership.st_uid!=65534 or ownership.st_gid!=65534 or stat.S_IMODE(ownership.st_mode)&0o022: raise RuntimeError("generic loader stdlib permissions rejected")
  if current=="/": break
  current=os.path.dirname(current)
 file_fd=os.open(file_path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); file_row=os.fstat(file_fd); value=os.pread(file_fd,file_row.st_size,0); os.close(file_fd)
 if hashlib.sha256(value).hexdigest()!=file_hash: raise RuntimeError("generic loader stdlib file drift")
for module in tuple(sys.modules.values()):
 module_path=getattr(module,"__file__",None)
 if isinstance(module_path,str) and not module_path.startswith("<") and os.path.realpath(module_path).startswith("/usr/lib/python3.12/") and (os.path.realpath(module_path)!=module_path or module_path not in stdlib): raise RuntimeError("generic loader module outside stdlib manifest")
sys.path.insert(0,f"/proc/self/fd/{runtime_root_fd}"); filename=f"<sealed-aghfal17-native-v18-generic:{actual}>"; sys.argv=[filename,*forwarded]
namespace={"__name__":"__main__","__file__":filename,"__package__":None,"__cached__":None,"__captured_sha256__":actual,"__generic_loader_protocol__":"planora.aghfal17.native-v18-generic-loader.v1"}
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


def _expected_hash(label: str) -> str:
    return EXPECTED_RUNNER_SHA256 if label == "runner" else EXPECTED_HASHES[label]


def supervisor_execution_sha256() -> str:
    value = globals().get("__captured_sha256__")
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RuntimeError("supervisor captured execution hash missing")
    return value


def launcher_attestation() -> dict[str, Any]:
    value = globals().get("__external_launcher_attestation__")
    if (
        not isinstance(value, dict)
        or value.get("protocol")
        != "planora.aghfal17.native-v18-sealed-launcher-bootstrap.v1"
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(value.get(key, ""))) is None
            for key in ("bootstrap_sha256", "launcher_sha256", "bash_sha256")
        )
        or any(
            type(value.get(key)) is not int
            for key in ("bootstrap_fd", "launcher_fd", "bash_fd")
        )
        or type(value.get("launcher_seals")) is not int
        or value.get("required_seals") != REQUIRED_SEALS
        or value.get("launcher_seals", 0) & REQUIRED_SEALS != REQUIRED_SEALS
        or value.get("launcher_executed_from_sealed_capture") is not True
        or value.get("external_bootstrap_loader_trust_root_required") is not True
        or value.get("stdlib_manifest_sha256")
        != "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327"
        or value.get("stdlib_file_count") != 619
        or value.get("stdlib_expected_uid") != 65534
        or value.get("stdlib_expected_gid") != 65534
        or value.get("stdlib_root_mount_read_only") is not True
        or value.get("stdlib_non_writable_ancestors") is not True
        or value.get("stdlib_admitted_before_supervisor_exec") is not True
        or value.get("bash_executed_from_verified_sealed_capture") is not True
        or value.get("bash_fd_post_exec_replay_available") is not False
    ):
        raise RuntimeError("sealed launcher bootstrap attestation missing")
    descriptors = [int(value[key]) for key in ("bootstrap_fd", "launcher_fd")]
    if len(set(descriptors)) != 2:
        raise RuntimeError("sealed launcher bootstrap descriptor alias")
    for label in ("bootstrap", "launcher"):
        descriptor = int(value[f"{label}_fd"])
        before = os.fstat(descriptor)
        raw = _pread_stable(descriptor, maximum_bytes=32 << 20)
        after = os.fstat(descriptor)
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        if (
            not stat.S_ISREG(before.st_mode)
            or _stable_identity(before) != _stable_identity(after)
            or sha256(raw).hexdigest() != value[f"{label}_sha256"]
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
        ):
            raise RuntimeError(f"sealed launcher bootstrap {label} replay drift")
    return dict(value)


def verify_current_supervisor_contract() -> tuple[int, ...]:
    binding = globals().get("__external_supervisor_binding__")
    path_value = globals().get("__external_supervisor_path__")
    if not isinstance(binding, dict) or not isinstance(path_value, str):
        raise RuntimeError("external supervisor path binding missing")
    path = Path(path_value)
    current = os.lstat(path)
    identity = _stable_identity(current)
    keys = ("device", "inode", "size", "file_type", "mode", "uid", "nlink")
    if tuple(binding.get(key) for key in keys) != identity:
        raise RuntimeError("supervisor current path contract drift")
    if binding.get("sha256") != supervisor_execution_sha256():
        raise RuntimeError("supervisor current hash binding drift")
    if not stat.S_ISREG(current.st_mode):
        raise RuntimeError("supervisor current path is not regular")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        raw = _pread_stable(descriptor, maximum_bytes=8 << 20)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final_named = os.lstat(path)
    if (
        _stable_identity(before) != identity
        or _stable_identity(after) != identity
        or _stable_identity(final_named) != identity
        or sha256(raw).hexdigest() != binding.get("sha256")
    ):
        raise RuntimeError("supervisor current source bytes drift")
    return identity


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
    supervisor_rss_kib: int = 0,
    supervisor_vmswap_kib: int = 0,
    supervisor_in_group: bool = False,
) -> str | None:
    floor = LAUNCH_MIN_MEM_AVAILABLE_KIB if launch else RUNTIME_MIN_MEM_AVAILABLE_KIB
    if sample["mem_available_kib"] < floor:
        return "host_mem_available_floor"
    if group_rss_kib + group_vmswap_kib >= PROCESS_GROUP_MEMORY_LIMIT_KIB:
        return "process_group_vmrss_plus_vmswap_limit"
    whole_launch_memory = group_rss_kib + group_vmswap_kib
    if not supervisor_in_group:
        whole_launch_memory += supervisor_rss_kib + supervisor_vmswap_kib
    if whole_launch_memory >= WHOLE_LAUNCH_MEMORY_LIMIT_KIB:
        return "whole_launch_vmrss_plus_vmswap_limit"
    if elapsed >= SUPERVISOR_HARD_WALL_SECONDS:
        return "supervisor_hard_wall"
    return None


def _process_group_from_stat(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    close = raw.rfind(")")
    fields = raw[close + 2 :].split()
    return int(fields[2]) if len(fields) > 2 else None


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


def process_usage(pid: int) -> tuple[int, int]:
    try:
        status = _read_key_values(Path("/proc") / str(pid) / "status")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        raise RuntimeError(f"required process accounting unavailable: {pid}") from None
    if "VmRSS" not in status:
        raise RuntimeError(f"required process RSS accounting unavailable: {pid}")
    return status["VmRSS"], status.get("VmSwap", 0)


def generation_accounting_sample(
    supervisor_pid: int,
    admitted_members: Mapping[int, tuple[int, int, int]],
) -> dict[str, Any]:
    """Sample only exact original-generation identities plus the supervisor.

    The numeric process group is deliberately absent from this interface.  A
    PID contributes at most once, and only after its PGID/session/starttime
    identity is replayed immediately before reading that PID's status file.
    """

    started_ns = time.monotonic_ns()
    rows: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    seen: set[tuple[int, tuple[int, int, int]]] = set()
    requested: list[tuple[str, int, tuple[int, int, int] | None]] = [
        ("generation_member", pid, identity)
        for pid, identity in sorted(admitted_members.items())
    ]
    requested.append(("supervisor", supervisor_pid, proc_stat_identity(supervisor_pid)))
    for role, pid, expected_identity in requested:
        if expected_identity is None:
            unavailable.append(
                {"role": role, "pid": pid, "reason": "identity_unavailable"}
            )
            continue
        key = (pid, expected_identity)
        if key in seen:
            continue
        seen.add(key)
        replayed = proc_stat_identity(pid)
        if replayed != expected_identity:
            unavailable.append(
                {
                    "role": role,
                    "pid": pid,
                    "expected_identity": list(expected_identity),
                    "observed_identity": (None if replayed is None else list(replayed)),
                    "reason": "identity_replay_mismatch",
                }
            )
            continue
        try:
            rss_kib, swap_kib = process_usage(pid)
        except RuntimeError as exc:
            unavailable.append(
                {
                    "role": role,
                    "pid": pid,
                    "identity": list(expected_identity),
                    "reason": str(exc),
                }
            )
            continue
        replayed_after = proc_stat_identity(pid)
        if replayed_after != expected_identity:
            unavailable.append(
                {
                    "role": role,
                    "pid": pid,
                    "expected_identity": list(expected_identity),
                    "observed_identity_after_status": (
                        None if replayed_after is None else list(replayed_after)
                    ),
                    "reason": "identity_drift_during_status_read",
                }
            )
            continue
        rows.append(
            {
                "role": role,
                "pid": pid,
                "identity": {
                    "process_group": expected_identity[0],
                    "session": expected_identity[1],
                    "starttime_ticks": expected_identity[2],
                },
                "vmrss_kib": rss_kib,
                "vmswap_kib": swap_kib,
                "vmrss_plus_vmswap_kib": rss_kib + swap_kib,
            }
        )
    group_rows = [row for row in rows if row["role"] == "generation_member"]
    group_rss = sum(int(row["vmrss_kib"]) for row in group_rows)
    group_swap = sum(int(row["vmswap_kib"]) for row in group_rows)
    whole_rss = sum(int(row["vmrss_kib"]) for row in rows)
    whole_swap = sum(int(row["vmswap_kib"]) for row in rows)
    return {
        "sample_started_monotonic_ns": started_ns,
        "sample_finished_monotonic_ns": time.monotonic_ns(),
        "sampled_processes": rows,
        "unavailable_identities": unavailable,
        "sampled_pid_count": len(rows),
        "unique_identity_count": len(seen),
        "group_vmrss_kib": group_rss,
        "group_vmswap_kib": group_swap,
        "group_vmrss_plus_vmswap_kib": group_rss + group_swap,
        "whole_launch_vmrss_kib": whole_rss,
        "whole_launch_vmswap_kib": whole_swap,
        "whole_launch_vmrss_plus_vmswap_kib": whole_rss + whole_swap,
        "numeric_pgid_rescan_used": False,
        "identity_replayed_before_and_after_each_status_read": True,
        "deduplicated": True,
    }


def reconcile_successfully_reaped_generation_member(
    accounting: Mapping[str, Any],
    child: subprocess.Popen[bytes],
    leader_identity: tuple[int, int, int] | None,
    admitted_members: Mapping[int, tuple[int, int, int]],
    previously_sampled_members: set[tuple[int, tuple[int, int, int]]],
) -> dict[str, Any]:
    """Permit one proven-gone, successfully reaped leader to contribute zero.

    This closes only the race in which the exact admitted direct child was
    sampled successfully, exits between samples, and is then reaped with exit
    status zero. Missing live status, PID reuse, identity drift, malformed
    numeric identities, and generations without a prior sample remain in the
    unavailable set and therefore fail closed at the caller.
    """

    result = dict(accounting)
    unavailable = [dict(row) for row in accounting["unavailable_identities"]]
    result["unavailable_identities"] = unavailable
    result["successfully_reaped_zero_contributions"] = []
    result["successful_reap_zero_contribution_used"] = False

    child_pid = getattr(child, "pid", None)
    trusted_identity = (
        type(child_pid) is int
        and child_pid > 1
        and isinstance(leader_identity, tuple)
        and len(leader_identity) == 3
        and all(type(value) is int and value > 0 for value in leader_identity)
        and leader_identity[:2] == (child_pid, child_pid)
    )
    if not trusted_identity:
        return result
    assert leader_identity is not None
    identity_key = (child_pid, leader_identity)
    if (
        admitted_members.get(child_pid) != leader_identity
        or identity_key not in previously_sampled_members
    ):
        return result

    eligible_rows = []
    for row in unavailable:
        if row.get("role") != "generation_member" or row.get("pid") != child_pid:
            continue
        if row.get("expected_identity") != list(leader_identity):
            continue
        reason = row.get("reason")
        if (
            reason == "identity_replay_mismatch"
            and row.get("observed_identity") is None
        ):
            eligible_rows.append(row)
        elif (
            reason == "identity_drift_during_status_read"
            and row.get("observed_identity_after_status") is None
        ):
            eligible_rows.append(row)
    if len(eligible_rows) != 1:
        return result

    try:
        exit_code = child.poll()
    except BaseException:
        return result
    if type(exit_code) is not int or exit_code != 0:
        return result
    if proc_stat_identity(child_pid) is not None:
        return result

    unavailable.remove(eligible_rows[0])
    zero_row = {
        "role": "generation_member",
        "pid": child_pid,
        "identity": {
            "process_group": leader_identity[0],
            "session": leader_identity[1],
            "starttime_ticks": leader_identity[2],
        },
        "vmrss_kib": 0,
        "vmswap_kib": 0,
        "vmrss_plus_vmswap_kib": 0,
        "basis": "prior_valid_identity_bound_sample_successful_zero_exit_reap_and_final_absence",
    }
    result["successfully_reaped_zero_contributions"] = [zero_row]
    result["successful_reap_zero_contribution_used"] = True
    return result


def whole_launch_usage(
    supervisor_pid: int, process_group: int
) -> tuple[int, int, int, int, int, int, tuple[int, ...], bool]:
    group_rss, group_swap, group_pids = process_group_usage(process_group)
    supervisor_rss, supervisor_swap = process_usage(supervisor_pid)
    supervisor_in_group = supervisor_pid in group_pids
    whole_rss = group_rss + (0 if supervisor_in_group else supervisor_rss)
    whole_swap = group_swap + (0 if supervisor_in_group else supervisor_swap)
    return (
        whole_rss,
        whole_swap,
        group_rss,
        group_swap,
        supervisor_rss,
        supervisor_swap,
        group_pids,
        supervisor_in_group,
    )


def _stream_capture(
    path: Path, expected: str, label: str
) -> tuple[int, dict[str, Any]]:
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
            f"aghfal17-v3-{label}", getattr(os, "MFD_ALLOW_SEALING", 0x0002)
        )
        digest = sha256()
        offset = 0
        while offset < source_before.st_size:
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
        return int(evidence["fd"]), evidence
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(parent_fd)


def verify_sealed_capture(
    descriptor: int, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    before = os.fstat(descriptor)
    identity = _stable_identity(before)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    digest = sha256()
    offset = 0
    while offset < before.st_size:
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
    *, runtime_root_fd: int, captures: Mapping[str, Mapping[str, Any]]
) -> tuple[int, int, list[int], dict[str, Any], dict[str, Any]]:
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
                sample = host_sample()
                gate = breach_reason(
                    elapsed=0,
                    group_rss_kib=0,
                    group_vmswap_kib=0,
                    sample=sample,
                    launch=True,
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
            runtime_fd, identity, seals = _seal_bytes(
                f"aghfal17-v3-runtime-{index}", raw
            )
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
            "schema": "planora.aghfal17.native-v18-sealed-runtime.v1",
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
            "aghfal17-v3-runtime-manifest", manifest_raw
        )
        binding = {
            "protocol": "planora.aghfal17.native-v18-sealed-runtime.v1",
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
        post_capture_gate = breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=post_capture_sample,
            launch=True,
        )
        if post_capture_gate is not None:
            raise RuntimeError(f"runtime bundle resource gate: {post_capture_gate}")
        summary = {
            "manifest_sha256": binding["manifest_sha256"],
            "manifest_size": len(manifest_raw),
            "file_count": len(manifest_entries),
            "total_bytes": sum(row["size"] for row in manifest_entries),
            "excluded_record_row_count": len(excluded),
            "root_identity": list(root_identity),
            "transport": "read_only_symlink_tree_to_sealed_memfds",
            "post_capture_host_sample": post_capture_sample,
        }
        return root_fd, manifest_fd, runtime_fds, binding, summary
    except BaseException:
        for descriptor in runtime_fds:
            os.close(descriptor)
        os.close(root_fd)
        raise
    finally:
        os.close(source_root_fd)


def replay_runtime_bundle(binding: Mapping[str, Any]) -> dict[str, Any]:
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
    return {
        "manifest_sha256": sha256(raw).hexdigest(),
        "file_count": len(seen),
        "total_bytes": total,
        "root_identity": list(root_identity),
        "all_seals_and_links_replayed": True,
    }


def _reset_child_stop_signals() -> None:
    for signum in STOP_SIGNALS:
        signal.signal(signum, signal.SIG_DFL)
    if hasattr(signal, "pthread_sigmask"):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, STOP_SIGNALS)


def _arm_child(parent_pid: int) -> None:
    _reset_child_stop_signals()
    os.setsid()
    resource.setrlimit(
        resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES)
    )
    result = LIBC.prctl(PR_SET_PDEATHSIG, int(PARENT_DEATH_SIGNAL), 0, 0, 0)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "prctl")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), PARENT_DEATH_SIGNAL)


def _signal_handlers(state: dict[str, int | None]) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def handler(signum: int, _frame: Any) -> None:
        state["signal"] = signum

    for signum in STOP_SIGNALS:
        previous[signum] = signal.signal(signum, handler)
    return previous


def _restore_signal_handlers_no_throw(previous: Mapping[int, Any]) -> list[str]:
    errors: list[str] = []
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except BaseException as exc:
            errors.append(f"restore_signal:{signum}:{type(exc).__name__}:{exc}")
    return errors


def proc_stat_identity(pid: int) -> tuple[int, int, int] | None:
    """Return (process-group, session, starttime) for a live PID."""
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[2]), int(fields[3]), int(fields[19])
    except ValueError:
        return None


def process_group_snapshot(
    process_group: int,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    result: list[tuple[int, tuple[int, int, int]]] = []
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError:
        return ()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        identity = proc_stat_identity(pid)
        if identity is not None and identity[0] == process_group:
            result.append((pid, identity))
    return tuple(sorted(result))


def refresh_group_generation(
    process_group: int,
    leader_identity: tuple[int, int, int] | None,
    admitted_members: dict[int, tuple[int, int, int]],
) -> dict[str, Any]:
    """Admit members only while the original leader generation is anchored."""
    evidence: dict[str, Any] = {
        "leader_anchored_before": False,
        "leader_anchored_after": False,
        "added_pids": [],
        "errors": [],
    }
    if leader_identity is None:
        evidence["errors"].append("missing_original_leader_identity")
        return evidence
    before = proc_stat_identity(process_group)
    evidence["leader_anchored_before"] = before == leader_identity
    if before != leader_identity:
        if before is not None:
            evidence["errors"].append("original_leader_generation_reused")
        return evidence
    snapshot = process_group_snapshot(process_group)
    after = proc_stat_identity(process_group)
    evidence["leader_anchored_after"] = after == leader_identity
    if after != leader_identity:
        evidence["errors"].append("original_leader_anchor_lost_during_snapshot")
        return evidence
    additions: dict[int, tuple[int, int, int]] = {}
    for pid, identity in snapshot:
        if identity[:2] != (process_group, process_group):
            evidence["errors"].append(f"member_group_or_session_drift:{pid}")
            continue
        existing = admitted_members.get(pid)
        if existing is not None and existing != identity:
            evidence["errors"].append(f"admitted_member_pid_reused:{pid}")
            continue
        if existing is None:
            additions[pid] = identity
    admitted_members.update(additions)
    evidence["added_pids"] = sorted(additions)
    evidence["admitted_pids"] = sorted(admitted_members)
    return evidence


def partition_generation_members(
    snapshot: tuple[tuple[int, tuple[int, int, int]], ...],
    admitted_members: Mapping[int, tuple[int, int, int]],
) -> tuple[
    tuple[tuple[int, tuple[int, int, int]], ...],
    tuple[tuple[int, tuple[int, int, int]], ...],
]:
    eligible: list[tuple[int, tuple[int, int, int]]] = []
    untrusted: list[tuple[int, tuple[int, int, int]]] = []
    for pid, identity in snapshot:
        if admitted_members.get(pid) == identity:
            eligible.append((pid, identity))
        else:
            untrusted.append((pid, identity))
    return tuple(eligible), tuple(untrusted)


def signal_process_group_snapshot(
    process_group: int,
    snapshot: tuple[tuple[int, tuple[int, int, int]], ...],
    signum: int,
    admitted_members: Mapping[int, tuple[int, int, int]],
) -> dict[str, Any]:
    """Signal only original-generation members; aggregate every member error."""
    eligible, untrusted = partition_generation_members(snapshot, admitted_members)
    result: dict[str, Any] = {
        "signal": int(signum),
        "snapshot_pids": [pid for pid, _identity in snapshot],
        "eligible_pids": [pid for pid, _identity in eligible],
        "untrusted_pids": [pid for pid, _identity in untrusted],
        "signaled_pids": [],
        "vanished_pids": [],
        "errors": [],
        "numeric_pgid_signal_sent": False,
    }
    if not eligible:
        return result
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        result["errors"].append("pidfd_member_signalling_unavailable")
        return result

    opened: list[tuple[int, tuple[int, int, int], int]] = []
    ready: list[tuple[int, int]] = []
    for pid, expected_identity in eligible:
        try:
            descriptor = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            result["vanished_pids"].append(pid)
            continue
        except OSError as exc:
            result["errors"].append(
                f"pidfd_open:{pid}:{exc.errno}:{type(exc).__name__}:{exc}"
            )
            continue
        opened.append((pid, expected_identity, descriptor))
        replayed = proc_stat_identity(pid)
        if replayed != expected_identity:
            result["errors"].append(f"member_identity_replay:{pid}")
            continue
        ready.append((pid, descriptor))

    # Every opened member identity has been replayed before the first signal.
    for pid, descriptor in ready:
        try:
            signal.pidfd_send_signal(descriptor, signum, None, 0)
        except ProcessLookupError:
            result["vanished_pids"].append(pid)
            continue
        except OSError as exc:
            result["errors"].append(
                f"pidfd_send_signal:{pid}:{exc.errno}:{type(exc).__name__}:{exc}"
            )
            continue
        result["signaled_pids"].append(pid)
    for pid, _identity, descriptor in opened:
        try:
            os.close(descriptor)
        except OSError as exc:
            result["errors"].append(
                f"pidfd_close:{pid}:{exc.errno}:{type(exc).__name__}:{exc}"
            )
    return result


def admit_spawned_process_group(
    child: subprocess.Popen[bytes],
    provisional_group: int,
    leader_identity: tuple[int, int, int] | None,
    leader_pidfd: int | None,
) -> tuple[int, tuple[int, int, int], int, dict[int, tuple[int, int, int]]]:
    """Bind the new session to both starttime identity and a leader pidfd."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("pidfd process-group admission unavailable")
    process_group = os.getpgid(child.pid)
    session = os.getsid(child.pid)
    replayed_identity = proc_stat_identity(child.pid)
    if (
        provisional_group != child.pid
        or process_group != provisional_group
        or session != provisional_group
        or leader_identity is None
        or replayed_identity != leader_identity
        or leader_identity[:2] != (provisional_group, provisional_group)
        or leader_pidfd is None
    ):
        raise RuntimeError("child process-group identity admission failed")
    admitted_members: dict[int, tuple[int, int, int]] = {}
    generation = refresh_group_generation(
        process_group, leader_identity, admitted_members
    )
    if generation["errors"] or admitted_members.get(child.pid) != leader_identity:
        raise RuntimeError("initial process-group generation admission failed")
    return process_group, leader_identity, leader_pidfd, admitted_members


def stop_group(
    child: subprocess.Popen[bytes],
    process_group: int,
    leader_identity: tuple[int, int, int] | None,
    leader_pidfd: int | None,
    admitted_members: dict[int, tuple[int, int, int]],
) -> dict[str, Any]:
    """Best-effort, identity-bound descendant drain that never throws."""
    result: dict[str, Any] = {
        "initial_residual_pids": [],
        "actions": [],
        "final_residual_pids": [],
        "errors": [],
        "empty": False,
        "leader_identity_available": leader_identity is not None,
        "leader_pidfd_available": leader_pidfd is not None,
        "admitted_generation_pids": sorted(admitted_members),
        "numeric_pgid_signal_sent": False,
    }
    if process_group <= 1 or process_group == os.getpgrp():
        result["errors"].append("unsafe_process_group_cleanup_target")
        return result

    generation_refresh = refresh_group_generation(
        process_group, leader_identity, admitted_members
    )
    result["final_anchored_generation_refresh"] = generation_refresh
    result["errors"].extend(generation_refresh["errors"])
    result["admitted_generation_pids"] = sorted(admitted_members)

    try:
        child.wait(timeout=0)
        result["leader_reaped_before_group_interpretation"] = True
    except subprocess.TimeoutExpired:
        result["leader_reaped_before_group_interpretation"] = False
    except BaseException as exc:
        result["leader_reaped_before_group_interpretation"] = False
        result["errors"].append(f"initial_wait:{type(exc).__name__}:{exc}")

    initial = process_group_snapshot(process_group)
    result["initial_residual_pids"] = [pid for pid, _identity in initial]
    term = signal_process_group_snapshot(
        process_group, initial, signal.SIGTERM, admitted_members
    )
    result["actions"].append(term)
    result["errors"].extend("sigterm:" + value for value in term["errors"])

    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    survivors = initial
    while time.monotonic() < deadline:
        try:
            if child.returncode is None:
                child.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
        except BaseException as exc:
            result["errors"].append(f"grace_wait:{type(exc).__name__}:{exc}")
        survivors = process_group_snapshot(process_group)
        if not survivors:
            break
        time.sleep(0.05)

    if survivors:
        kill = signal_process_group_snapshot(
            process_group, survivors, signal.SIGKILL, admitted_members
        )
        result["actions"].append(kill)
        result["errors"].extend("sigkill:" + value for value in kill["errors"])

    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        survivors = process_group_snapshot(process_group)
        if not survivors:
            break
        time.sleep(0.05)
    try:
        child.wait(timeout=0 if survivors else TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        result["errors"].append("final_wait:TimeoutExpired")
    except BaseException as exc:
        result["errors"].append(f"final_wait:{type(exc).__name__}:{exc}")
    final = process_group_snapshot(process_group)
    _eligible_final, untrusted_final = partition_generation_members(
        final, admitted_members
    )
    if untrusted_final:
        result["errors"].append(
            "untrusted_generation_survivors:"
            + ",".join(str(pid) for pid, _identity in untrusted_final)
        )
    result["final_residual_pids"] = [pid for pid, _identity in final]
    result["empty"] = not final
    result["original_pgid_asserted_empty"] = not final
    result["pid_reuse_guard_passed"] = all(
        set(action["untrusted_pids"]).isdisjoint(action["signaled_pids"])
        for action in result["actions"]
    )
    result["untrusted_generation_pids"] = [pid for pid, _identity in untrusted_final]
    return result


def planned_command(
    python_fd: int, runner_fd: int, runtime_root_fd: int, pycache_prefix: Path
) -> list[str]:
    return [
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
        "--execute-completion",
        "--allow-official-input",
        "--allow-solver",
        "--allow-publication",
    ]


def planned_probe_command(
    python_fd: int, runner_fd: int, runtime_root_fd: int, pycache_prefix: Path
) -> list[str]:
    return [
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
        "--sealed-import-probe",
    ]


def planned_generic_command(
    python_fd: int,
    generic_fd: int,
    runtime_root_fd: int,
    pycache_prefix: Path,
    solution_fd: int,
    report_fd: int,
) -> list[str]:
    return [
        f"/proc/self/fd/{python_fd}",
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={pycache_prefix}",
        "-c",
        GENERIC_FD_LOADER,
        str(generic_fd),
        EXPECTED_HASHES["generic_validator"],
        str(runtime_root_fd),
        "--solution-fd",
        str(solution_fd),
        "--report-fd",
        str(report_fd),
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


def _read_retained_named_regular(
    dirfd: int,
    name: str,
    descriptor: int,
    *,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, int]]:
    """Read only the retained FD, then bind it to the still-named inode."""
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size < 1
        or before.st_size > maximum_bytes
    ):
        raise RuntimeError(f"retained artifact {name} contract rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError(f"retained artifact {name} ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    named = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    if _stable_identity(before) != _stable_identity(after) or _stable_identity(
        after
    ) != _stable_identity(named):
        raise RuntimeError(f"retained artifact {name} identity drift")
    return b"".join(chunks), {
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "size": int(after.st_size),
        "mode": stat.S_IMODE(after.st_mode),
        "uid": int(after.st_uid),
        "parent_created_exclusive": True,
        "child_wrote_inherited_fd_only": True,
        "parent_pread_retained_fd": True,
        "named_identity_replayed": True,
    }


def _finite_elapsed(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def run_isolated_generic_validator(
    *,
    dirfd: int,
    run_dir: Path,
    captures: Mapping[str, Mapping[str, Any]],
    runtime_root_fd: int,
    inherited: tuple[int, ...],
    environment: Mapping[str, str],
    hard_deadline: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the distinct validator with a parent-created retained report FD."""
    solution_fd = -1
    report_fd = -1
    child: subprocess.Popen[bytes] | None = None
    process_group: int | None = None
    leader_identity: tuple[int, int, int] | None = None
    leader_pidfd: int | None = None
    admitted_members: dict[int, tuple[int, int, int]] = {}
    cleanup: dict[str, Any] = {
        "initial_residual_pids": [],
        "actions": [],
        "final_residual_pids": [],
        "empty": True,
    }
    report_identity: tuple[int, ...] | None = None
    try:
        solution_fd = os.open(
            "solution.xml",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=dirfd,
        )
        solution_row = os.fstat(solution_fd)
        if not stat.S_ISREG(solution_row.st_mode) or solution_row.st_size < 1:
            raise RuntimeError("generic solution descriptor contract rejected")
        report_fd = os.open(
            "generic-validator-report.json",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
            dir_fd=dirfd,
        )
        report_identity = _stable_identity(os.fstat(report_fd))
        command = planned_generic_command(
            int(captures["python_binary"]["fd"]),
            int(captures["generic_validator"]["fd"]),
            runtime_root_fd,
            Path(f"/proc/self/fd/{dirfd}/.generic-pycache-disabled"),
            solution_fd,
            report_fd,
        )
        parent_pid = os.getpid()
        child = subprocess.Popen(
            command,
            pass_fds=tuple(dict.fromkeys((*inherited, solution_fd, report_fd))),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            preexec_fn=lambda: _arm_child(parent_pid),
        )
        process_group = child.pid
        cleanup["empty"] = False
        leader_identity = proc_stat_identity(child.pid)
        leader_pidfd = os.pidfd_open(child.pid, 0)
        (
            process_group,
            leader_identity,
            leader_pidfd,
            admitted_members,
        ) = admit_spawned_process_group(
            child, process_group, leader_identity, leader_pidfd
        )
        peak_whole = 0
        peak_group = 0
        breach: str | None = None
        while child.poll() is None:
            generation = refresh_group_generation(
                process_group, leader_identity, admitted_members
            )
            if generation["errors"]:
                breach = "process_group_generation_drift"
                break
            elapsed = max(
                0.0, SUPERVISOR_HARD_WALL_SECONDS - (hard_deadline - time.monotonic())
            )
            sample = host_sample()
            (
                whole_rss,
                whole_swap,
                group_rss,
                group_swap,
                supervisor_rss,
                supervisor_swap,
                _pids,
                supervisor_in_group,
            ) = whole_launch_usage(os.getpid(), process_group)
            peak_whole = max(peak_whole, whole_rss + whole_swap)
            peak_group = max(peak_group, group_rss + group_swap)
            breach = breach_reason(
                elapsed=elapsed,
                group_rss_kib=group_rss,
                group_vmswap_kib=group_swap,
                sample=sample,
                launch=False,
                supervisor_rss_kib=supervisor_rss,
                supervisor_vmswap_kib=supervisor_swap,
                supervisor_in_group=supervisor_in_group,
            )
            if time.monotonic() >= hard_deadline:
                breach = "supervisor_hard_wall"
            if breach is not None:
                cleanup.update(
                    stop_group(
                        child,
                        process_group,
                        leader_identity,
                        leader_pidfd,
                        admitted_members,
                    )
                )
                break
            time.sleep(POLL_SECONDS)
        exit_code = child.wait(timeout=5)
        cleanup.update(
            stop_group(
                child,
                process_group,
                leader_identity,
                leader_pidfd,
                admitted_members,
            )
        )
        if not cleanup["empty"] or cleanup["errors"]:
            raise RuntimeError("isolated generic validator descendant drain rejected")
        if breach is not None or exit_code != 0:
            raise RuntimeError(
                f"isolated generic validator rejected: exit={exit_code} breach={breach}"
            )
        raw, evidence = _read_retained_named_regular(
            dirfd,
            "generic-validator-report.json",
            report_fd,
            maximum_bytes=64 << 20,
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("generic validator report is not strict JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("generic validator report top level rejected")
        evidence.update(
            {
                "path": str(run_dir / "generic-validator-report.json"),
                "sha256": sha256(raw).hexdigest(),
                "generic_exit_code": exit_code,
                "peak_process_group_vmrss_plus_vmswap_kib": peak_group,
                "peak_whole_launch_vmrss_plus_vmswap_kib": peak_whole,
            }
        )
        return payload, evidence, cleanup
    finally:
        if child is not None and process_group is not None and not cleanup["empty"]:
            cleanup.update(
                stop_group(
                    child,
                    process_group,
                    leader_identity,
                    leader_pidfd,
                    admitted_members,
                )
            )
        if leader_pidfd is not None:
            os.close(leader_pidfd)
        if report_fd >= 0:
            os.close(report_fd)
        if solution_fd >= 0:
            os.close(solution_fd)
        if report_identity is not None:
            try:
                named = os.stat(
                    "generic-validator-report.json",
                    dir_fd=dirfd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                if child is not None and child.returncode == 0:
                    raise RuntimeError("generic validator report pathname disappeared")
            else:
                named_identity = _stable_identity(named)
                if (
                    named_identity[0],
                    named_identity[1],
                    *named_identity[3:],
                ) != (
                    report_identity[0],
                    report_identity[1],
                    *report_identity[3:],
                ) and child is not None:
                    raise RuntimeError(
                        "generic validator report pathname was substituted"
                    )


def agh_child_acceptance(
    *,
    dirfd: int,
    run_dir: Path,
    child_exit_code: int,
    observed_child_elapsed_seconds: float,
    generic_payload: Mapping[str, Any] | None = None,
    generic_evidence: Mapping[str, Any] | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    errors: list[str] = []
    observed = _finite_elapsed(observed_child_elapsed_seconds)
    artifacts: dict[str, Any] = {"observed_child_elapsed_seconds": observed}
    names = sorted(entry.name for entry in os.scandir(f"/proc/self/fd/{dirfd}"))
    allowed = {
        "child.stdout.log",
        "child.stderr.log",
        "solution.xml",
        "completion-report.json",
        "generic-validator-report.json",
    }
    unexpected = sorted(set(names) - allowed)
    if unexpected:
        errors.append("unexpected_child_artifacts:" + ",".join(unexpected))
    stdout_raw, stdout_identity = _read_relative_regular(
        dirfd, "child.stdout.log", maximum_bytes=64 << 20
    )
    stderr_raw, stderr_identity = _read_relative_regular(
        dirfd, "child.stderr.log", maximum_bytes=32 << 20
    )
    artifacts["stdout"] = {
        **stdout_identity,
        "path": str(run_dir / "child.stdout.log"),
        "sha256": sha256(stdout_raw).hexdigest(),
    }
    artifacts["stderr"] = {
        **stderr_identity,
        "path": str(run_dir / "child.stderr.log"),
        "sha256": sha256(stderr_raw).hexdigest(),
    }
    try:
        child = json.loads(stdout_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"child_stdout_invalid_json:{type(exc).__name__}")
        child = {}
    if not isinstance(child, dict):
        errors.append("child_stdout_top_level_not_object")
        child = {}
    artifacts["child_payload"] = child
    claimed = _finite_elapsed(child.get("elapsed_seconds"))
    if observed is None or claimed is None:
        errors.append("runner_elapsed_claim_invalid")
    elif (
        observed > CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS
        or claimed > CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS
    ):
        errors.append("runner_elapsed_exceeds_child_acceptance_deadline")
    if (
        child.get("runner_sha256_start") != EXPECTED_RUNNER_SHA256
        or child.get("runner_sha256_end") != EXPECTED_RUNNER_SHA256
        or child.get("runner_hash_stable") is not True
    ):
        errors.append("runner_hash_claim_mismatch")
    output_names = set(names) - {"child.stdout.log", "child.stderr.log"}
    if child_exit_code == 2 and child.get("status") == "NO_RESULT":
        if output_names:
            errors.append("no_result_published_completion_artifacts")
        if (
            child.get("schema") != "planora.agh-fal17.native-v18-runner.v1"
            or child.get("xml_published") is not False
            or child.get("native_validation_complete") is not False
            or child.get("cooperative_deadline_seconds")
            != CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS
            or child.get("competitor_schedule_or_result_used") is not False
            or child.get("competitor_placement_or_hint_used") is not False
        ):
            errors.append("no_result_claim_mismatch")
        return ("NO_RESULT" if not errors else "FAILED"), errors, artifacts
    if child_exit_code != 0:
        errors.append(f"child_exit_code:{child_exit_code}")
        return "FAILED", errors, artifacts
    if output_names != {
        "solution.xml",
        "completion-report.json",
        "generic-validator-report.json",
    }:
        errors.append("validated_completion_artifact_set_mismatch")
        return "FAILED", errors, artifacts
    if not isinstance(generic_payload, Mapping) or not isinstance(
        generic_evidence, Mapping
    ):
        errors.append("isolated_generic_validation_evidence_missing")
        return "FAILED", errors, artifacts
    artifacts["isolated_generic_validation"] = {
        **dict(generic_evidence),
        "payload": dict(generic_payload),
    }
    xml_raw, xml_identity = _read_relative_regular(
        dirfd, "solution.xml", maximum_bytes=256 << 20
    )
    report_raw, report_identity = _read_relative_regular(
        dirfd, "completion-report.json", maximum_bytes=64 << 20
    )
    xml_digest = sha256(xml_raw).hexdigest()
    report_digest = sha256(report_raw).hexdigest()
    artifacts["solution_xml"] = {
        **xml_identity,
        "path": str(run_dir / "solution.xml"),
        "sha256": xml_digest,
    }
    try:
        report = json.loads(report_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"completion_report_invalid_json:{type(exc).__name__}")
        report = {}
    if not isinstance(report, dict):
        errors.append("completion_report_top_level_not_object")
        report = {}
    artifacts["completion_report"] = {
        **report_identity,
        "path": str(run_dir / "completion-report.json"),
        "sha256": report_digest,
        "payload": report,
    }
    try:
        root = ElementTree.fromstring(xml_raw)
    except ElementTree.ParseError as exc:
        errors.append(f"solution_xml_parse_error:{exc}")
        root = ElementTree.Element("invalid")
    classes = list(root.findall("class")) if root.tag == "solution" else []
    class_ids = [row.get("id") for row in classes]
    xml_shape_ok = (
        root.tag == "solution"
        and root.get("inputSha256") == EXPECTED_HASHES["official_instance"]
        and len(classes) == 5_081
        and len(set(class_ids)) == 5_081
        and all(
            isinstance(row.get("id"), str)
            and isinstance(row.get("days"), str)
            and isinstance(row.get("start"), str)
            and isinstance(row.get("weeks"), str)
            for row in classes
        )
    )
    if not xml_shape_ok:
        errors.append("solution_xml_strict_shape_mismatch")
    publication = child.get("publication")
    if not isinstance(publication, dict):
        publication = {}
        errors.append("child_publication_not_object")
    serialized = report.get("serialized_solution")
    executing_python = report.get("executing_python")
    runtime_evidence = report.get("runtime_evidence")
    runtime_install = report.get("sealed_runtime_install")
    final_loaded = report.get("final_loaded_runtime_replay")
    final_maps = report.get("final_system_runtime")
    expected_record_hashes = {
        root_name: EXPECTED_HASHES[label]
        for root_name, label in {
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
        }.items()
    }
    runtime_claims_ok = (
        isinstance(executing_python, dict)
        and executing_python.get("sha256") == EXPECTED_HASHES["python_binary"]
        and executing_python.get("proc_self_exe_bound") is True
        and executing_python.get("isolated") is True
        and executing_python.get("no_site") is True
        and executing_python.get("dont_write_bytecode") is True
        and isinstance(runtime_evidence, dict)
        and runtime_evidence.get("sealed_record_hashes") == expected_record_hashes
        and type(runtime_evidence.get("loaded_file_count")) is int
        and runtime_evidence.get("loaded_file_count", 0) > 0
        and isinstance(final_loaded, dict)
        and final_loaded.get("sealed_record_hashes") == expected_record_hashes
        and isinstance(runtime_install, dict)
        and runtime_install.get("sealed_source_finder_installed") is True
        and runtime_install.get("live_site_packages_on_sys_path") is False
        and type(runtime_install.get("native_dependency_memfds_preloaded")) is int
        and runtime_install.get("native_dependency_memfds_preloaded", 0) > 0
        and isinstance(final_maps, dict)
        and final_maps.get("sealed_python_mapped") is True
        and final_maps.get("system_runtime_boundary")
        == "observed_and_hashed_not_sealed"
    )
    if not runtime_claims_ok:
        errors.append("sealed_runtime_claim_mismatch")
    stdlib_claims = (
        report.get("stdlib_start"),
        report.get("stdlib_final"),
        generic_payload.get("stdlib_start"),
        generic_payload.get("stdlib_final"),
    )
    if not all(
        isinstance(row, dict)
        and row.get("manifest_sha256") == EXPECTED_HASHES["stdlib_manifest"]
        and row.get("file_count") == 619
        and row.get("expected_uid") == 65534
        and row.get("expected_gid") == 65534
        and row.get("root_mount_read_only") is True
        and row.get("group_or_world_writable_file_or_ancestor_allowed") is False
        and row.get("exact_per_path_hashes_verified") is True
        for row in stdlib_claims
    ):
        errors.append("stdlib_trust_boundary_claim_mismatch")
    student_ids = {
        student.get("id")
        for row in classes
        for student in row.findall("student")
        if isinstance(student.get("id"), str)
    }
    expected_planora_hashes = {
        name: EXPECTED_HASHES[label]
        for name, label in {
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
        }.items()
    }
    final_planora = report.get("final_loaded_planora_modules")
    generic_planora = generic_payload.get("loaded_planora_modules")
    planora_claims_ok = (
        isinstance(final_planora, dict)
        and final_planora.get("benchmarks.itc2019")
        == EXPECTED_HASHES["planora_itc2019"]
        and set(final_planora).issubset(expected_planora_hashes)
        and all(
            expected_planora_hashes[name] == value
            for name, value in final_planora.items()
        )
        and isinstance(generic_planora, dict)
        and generic_planora.get("benchmarks.itc2019")
        == EXPECTED_HASHES["planora_itc2019"]
        and set(generic_planora).issubset(expected_planora_hashes)
        and all(
            expected_planora_hashes[name] == value
            for name, value in generic_planora.items()
        )
    )
    if not planora_claims_ok:
        errors.append("sealed_planora_claim_mismatch")
    actual_students = report.get("actual_problem_students")
    generic_claims_ok = (
        generic_payload.get("schema")
        == "planora.agh-fal17.native-v18-isolated-generic-validator.v1"
        and generic_payload.get("status") == "PASS"
        and generic_payload.get("errors") == []
        and generic_payload.get("classes") == 5_081
        and type(generic_payload.get("students")) is int
        and generic_payload.get("students") == actual_students
        and generic_payload.get("actual_problem_students") == actual_students
        and generic_payload.get("official_input_only") is True
        and generic_payload.get("checkpoint_or_certified_provenance_used") is False
        and generic_evidence.get("parent_created_exclusive") is True
        and generic_evidence.get("child_wrote_inherited_fd_only") is True
        and generic_evidence.get("parent_pread_retained_fd") is True
        and generic_evidence.get("named_identity_replayed") is True
    )
    if not generic_claims_ok:
        errors.append("isolated_generic_validation_claim_mismatch")
    if (
        child.get("schema") != "planora.agh-fal17.native-v18-runner.v1"
        or child.get("status") != "NATIVE_LOCAL_VALIDATED_GENERIC_PENDING"
        or child.get("classes") != 5_081
        or child.get("students") != actual_students
        or child.get("native_validation_complete") is not True
        or child.get("generic_validation_complete") is not False
        or child.get("xml_published") is not True
        or child.get("competitor_schedule_or_result_used") is not False
        or child.get("competitor_placement_or_hint_used") is not False
        or report.get("schema") != "planora.agh-fal17.native-v18-report.v1"
        or report.get("status") != "NATIVE_LOCAL_VALIDATION_PASSED_GENERIC_PENDING"
        or report.get("input_sha256") != EXPECTED_HASHES["official_instance"]
        or report.get("classes") != 5_081
        or type(actual_students) is not int
        or actual_students < 1
        or report.get("students") != actual_students
        or len(student_ids) != actual_students
        or report.get("requested_formulation") != "auto"
        or report.get("local_validation_errors") != []
        or report.get("local_document_validation_errors") != []
        or report.get("isolated_generic_validation_required") is not True
        or report.get("official_input_only") is not True
        or report.get("checkpoint_or_certified_provenance_used") is not False
        or report.get("competitor_schedule_or_result_used") is not False
        or report.get("competitor_placement_or_hint_used") is not False
        or not isinstance(serialized, dict)
        or serialized.get("sha256") != xml_digest
        or serialized.get("size") != len(xml_raw)
        or publication.get("solution.xml", {}).get("sha256") != xml_digest
        or publication.get("solution.xml", {}).get("size") != len(xml_raw)
        or publication.get("solution.xml", {}).get("publication_order") != 1
        or publication.get("completion-report.json", {}).get("sha256") != report_digest
        or publication.get("completion-report.json", {}).get("size") != len(report_raw)
        or publication.get("completion-report.json", {}).get("publication_order") != 2
    ):
        errors.append("validated_completion_claim_mismatch")
    return ("COMPLETION_VALID" if not errors else "FAILED"), errors, artifacts


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


def publish_supervisor_report(
    *,
    dirfd: int,
    parent: Path,
    parent_identity: tuple[int, int, int, int],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    pending = f".supervisor-report.pending-{uuid.uuid4().hex}"
    descriptor = os.open(
        pending,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o400,
        dir_fd=dirfd,
    )
    admitted: tuple[int, ...] | None = None
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("supervisor report stopped accepting bytes")
            view = view[written:]
        os.fsync(descriptor)
        identity = _stable_identity(os.fstat(descriptor))
        _rename_noreplace(dirfd, pending, "supervisor-report.json")
        admitted = identity
        os.fsync(dirfd)
        named_parent = os.lstat(parent)
        if (
            int(named_parent.st_dev),
            int(named_parent.st_ino),
            stat.S_IMODE(named_parent.st_mode),
            int(named_parent.st_uid),
        ) != parent_identity:
            raise RuntimeError("supervisor report parent final replay failed")
        named = os.stat("supervisor-report.json", dir_fd=dirfd, follow_symlinks=False)
        exact, _ = _read_relative_regular(
            dirfd, "supervisor-report.json", maximum_bytes=64 << 20
        )
        if (
            _stable_identity(named) != identity
            or exact != raw
            or _stable_identity(os.fstat(descriptor)) != identity
        ):
            raise RuntimeError("supervisor report canonical final replay failed")
        return {
            "path": str(parent / "supervisor-report.json"),
            "sha256": sha256(exact).hexdigest(),
            "size": len(exact),
            "device": identity[0],
            "inode": identity[1],
        }
    except BaseException:
        if admitted is not None:
            try:
                current = os.stat(
                    "supervisor-report.json", dir_fd=dirfd, follow_symlinks=False
                )
                if _stable_identity(current) == admitted:
                    os.unlink("supervisor-report.json", dir_fd=dirfd)
            except FileNotFoundError:
                pass
        else:
            try:
                os.unlink(pending, dir_fd=dirfd)
            except FileNotFoundError:
                pass
        raise
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
    return _private_directory("planora-aghfal17-native-v18-run")


def _private_runtime_directory() -> tuple[Path, int, tuple[int, int, int, int]]:
    return _private_directory("planora-aghfal17-native-v18-runtime")


def minimal_child_environment(
    *,
    captures: Mapping[str, Any],
    output_binding: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    scratch_fd: int,
) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": f"/proc/self/fd/{scratch_fd}",
        CAPTURE_MANIFEST_ENV: json.dumps(
            captures, sort_keys=True, separators=(",", ":")
        ),
        OUTPUT_BINDING_ENV: json.dumps(
            output_binding, sort_keys=True, separators=(",", ":")
        ),
        RUNTIME_BUNDLE_ENV: json.dumps(
            runtime_binding, sort_keys=True, separators=(",", ":")
        ),
    }


def run_supervised() -> dict[str, Any]:
    supervisor_start = supervisor_execution_sha256()
    admitted_launcher = launcher_attestation()
    supervisor_contract_start = verify_current_supervisor_contract()
    baseline = host_sample()
    initial_supervisor_rss, initial_supervisor_swap = process_usage(os.getpid())
    initial = (
        "host_initial_capture_headroom"
        if baseline["mem_available_kib"] < INITIAL_MIN_MEM_AVAILABLE_KIB
        else breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=baseline,
            launch=True,
            supervisor_rss_kib=initial_supervisor_rss,
            supervisor_vmswap_kib=initial_supervisor_swap,
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
            "checkpoint_or_certified_provenance_used": False,
        }
    resource.setrlimit(
        resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES)
    )
    captures: dict[str, dict[str, Any]] = {}
    inherited: list[int] = []
    run_dir_fd = -1
    runtime_initial_fd = -1
    scratch_fd = -1
    stdout_fd = -1
    stderr_fd = -1
    try:
        for label, path in CAPTURE_SOURCES.items():
            descriptor, evidence = _stream_capture(path, _expected_hash(label), label)
            inherited.append(descriptor)
            captures[label] = evidence
        after_capture = host_sample()
        capture_supervisor_rss, capture_supervisor_swap = process_usage(os.getpid())
        capture_gate = breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=after_capture,
            launch=True,
            supervisor_rss_kib=capture_supervisor_rss,
            supervisor_vmswap_kib=capture_supervisor_swap,
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
                "checkpoint_or_certified_provenance_used": False,
            }
        run_dir, run_dir_fd, run_dir_identity = _private_run_directory()
        inherited.append(run_dir_fd)
        scratch_dir, scratch_fd, scratch_identity = _private_directory(
            "planora-aghfal17-native-v18-scratch"
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
            scratch_fd=scratch_fd,
        )
        pycache_prefix = Path(f"/proc/self/fd/{run_dir_fd}/.pycache-disabled")
        command = planned_command(
            captures["python_binary"]["fd"],
            captures["runner"]["fd"],
            runtime_root_fd,
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
        parent_pid = os.getpid()
        signal_state: dict[str, int | None] = {"signal": None}
        previous = _signal_handlers(signal_state)
        started = time.monotonic()
        process_group = -1
        leader_identity: tuple[int, int, int] | None = None
        leader_pidfd: int | None = None
        admitted_members: dict[int, tuple[int, int, int]] = {}
        try:
            child = subprocess.Popen(
                command,
                pass_fds=tuple(inherited),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_fd,
                stderr=stderr_fd,
                close_fds=True,
                preexec_fn=lambda: _arm_child(parent_pid),
            )
        except BaseException:
            _restore_signal_handlers_no_throw(previous)
            raise
        process_group = child.pid
        group_cleanup: dict[str, Any] = {
            "initial_residual_pids": [],
            "actions": [],
            "final_residual_pids": [],
            "empty": False,
        }
        lifecycle_errors: list[str] = []
        try:
            leader_identity = proc_stat_identity(child.pid)
            leader_pidfd = os.pidfd_open(child.pid, 0)
            (
                process_group,
                leader_identity,
                leader_pidfd,
                admitted_members,
            ) = admit_spawned_process_group(
                child, process_group, leader_identity, leader_pidfd
            )
        except BaseException:
            group_cleanup.update(
                stop_group(
                    child,
                    process_group,
                    leader_identity,
                    leader_pidfd,
                    admitted_members,
                )
            )
            if leader_pidfd is not None:
                os.close(leader_pidfd)
                leader_pidfd = None
            _restore_signal_handlers_no_throw(previous)
            raise
        peak_rss = 0
        peak_vmswap = 0
        peak_group_memory = 0
        peak_pids: tuple[int, ...] = ()
        peak_whole_rss = 0
        peak_whole_vmswap = 0
        peak_whole_memory = 0
        peak_supervisor_rss = 0
        peak_supervisor_vmswap = 0
        peak_supervisor_in_group = False
        peak_group_accounting_sample: dict[str, Any] = {}
        peak_whole_accounting_sample: dict[str, Any] = {}
        breach = None
        stop_action = None
        try:
            while child.poll() is None:
                generation = refresh_group_generation(
                    process_group, leader_identity, admitted_members
                )
                if generation["errors"]:
                    breach = "process_group_generation_drift"
                    break
                sample = host_sample()
                elapsed = time.monotonic() - started
                (
                    whole_rss,
                    whole_vmswap,
                    rss,
                    vmswap,
                    supervisor_rss,
                    supervisor_vmswap,
                    pids,
                    supervisor_in_group,
                ) = whole_launch_usage(os.getpid(), process_group)
                group_memory = rss + vmswap
                if group_memory > peak_group_memory:
                    peak_pids = pids
                    peak_rss = rss
                    peak_vmswap = vmswap
                    peak_group_memory = group_memory
                whole_memory = whole_rss + whole_vmswap
                if whole_memory > peak_whole_memory:
                    peak_whole_rss = whole_rss
                    peak_whole_vmswap = whole_vmswap
                    peak_whole_memory = whole_memory
                    peak_supervisor_rss = supervisor_rss
                    peak_supervisor_vmswap = supervisor_vmswap
                    peak_supervisor_in_group = supervisor_in_group
                if signal_state["signal"] is not None:
                    breach = f"supervisor_signal:{signal_state['signal']}"
                else:
                    breach = breach_reason(
                        elapsed=elapsed,
                        group_rss_kib=rss,
                        group_vmswap_kib=vmswap,
                        sample=sample,
                        launch=False,
                        supervisor_rss_kib=supervisor_rss,
                        supervisor_vmswap_kib=supervisor_vmswap,
                        supervisor_in_group=supervisor_in_group,
                    )
                if breach is not None:
                    stop_action = "identity_bound_descendant_drain"
                    break
                time.sleep(POLL_SECONDS)
            child_exit_code = child.wait(timeout=5)
            observed_child_elapsed = time.monotonic() - started
        except BaseException as exc:
            lifecycle_errors.append(f"{type(exc).__name__}:{exc}")
            child_exit_code = child.returncode if child.returncode is not None else -1
            observed_child_elapsed = time.monotonic() - started
            if breach is None:
                breach = "child_lifecycle_exception"
        finally:
            if process_group > 1:
                group_cleanup.update(
                    stop_group(
                        child,
                        process_group,
                        leader_identity,
                        leader_pidfd,
                        admitted_members,
                    )
                )
            if leader_pidfd is not None:
                os.close(leader_pidfd)
                leader_pidfd = None
            lifecycle_errors.extend(_restore_signal_handlers_no_throw(previous))
        os.close(stdout_fd)
        stdout_fd = -1
        os.close(stderr_fd)
        stderr_fd = -1
        generic_payload: dict[str, Any] | None = None
        generic_evidence: dict[str, Any] | None = None
        generic_cleanup: dict[str, Any] | None = None
        generic_error: str | None = None
        if child_exit_code == 0 and breach is None and group_cleanup["empty"]:
            try:
                generic_payload, generic_evidence, generic_cleanup = (
                    run_isolated_generic_validator(
                        dirfd=run_dir_fd,
                        run_dir=run_dir,
                        captures=captures,
                        runtime_root_fd=runtime_root_fd,
                        inherited=tuple(inherited),
                        environment=environment,
                        hard_deadline=started + SUPERVISOR_HARD_WALL_SECONDS,
                    )
                )
            except BaseException as exc:
                generic_error = f"{type(exc).__name__}:{exc}"
        status, errors, artifacts = agh_child_acceptance(
            dirfd=run_dir_fd,
            run_dir=run_dir,
            child_exit_code=child_exit_code,
            observed_child_elapsed_seconds=observed_child_elapsed,
            generic_payload=generic_payload,
            generic_evidence=generic_evidence,
        )
        errors.extend("child_lifecycle:" + value for value in lifecycle_errors)
        if lifecycle_errors:
            status = "FAILED"
        if group_cleanup.get("errors"):
            errors.extend(
                "process_group_cleanup:" + str(value)
                for value in group_cleanup["errors"]
            )
            status = "FAILED"
        if generic_error is not None:
            errors.append("isolated_generic_validator_failed:" + generic_error)
            status = "FAILED"
        artifacts["isolated_generic_process_group_cleanup"] = generic_cleanup
        solver_return_proven = status in {
            "COMPLETION_VALID",
            "NO_RESULT",
        }
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
        if launcher_attestation() != admitted_launcher:
            errors.append("sealed_launcher_bootstrap_drift")
            status = "FAILED"
        final_host = host_sample()
        payload = {
            "schema": "planora.agh-fal17.native-v18-supervisor.v1",
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
            "peak_process_group_vmrss_plus_vmswap_kib": peak_group_memory,
            "peak_process_group_pids": list(peak_pids),
            "peak_whole_launch_rss_kib": peak_whole_rss,
            "peak_whole_launch_vmswap_kib": peak_whole_vmswap,
            "peak_whole_launch_vmrss_plus_vmswap_kib": peak_whole_memory,
            "peak_whole_launch_supervisor_rss_kib": peak_supervisor_rss,
            "peak_whole_launch_supervisor_vmswap_kib": peak_supervisor_vmswap,
            "peak_whole_launch_supervisor_in_child_group": peak_supervisor_in_group,
            "process_group_cleanup": group_cleanup,
            "process_group_vmrss_plus_vmswap_limit_kib": (
                PROCESS_GROUP_MEMORY_LIMIT_KIB
            ),
            "whole_launch_vmrss_plus_vmswap_limit_kib": (WHOLE_LAUNCH_MEMORY_LIMIT_KIB),
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
            "external_launcher_attestation": admitted_launcher,
            "official_instance_opened": True,
            "solver_child_process_started": True,
            "solver_execution_started": solver_return_proven,
            "admissible_as_solution": status == "COMPLETION_VALID",
            "official_solution_xml_published": status == "COMPLETION_VALID",
            "checkpoint_or_certified_provenance_used": False,
        }
        report_evidence = publish_supervisor_report(
            dirfd=run_dir_fd,
            parent=run_dir,
            parent_identity=run_dir_identity,
            payload=payload,
        )
        payload["supervisor_report_evidence"] = report_evidence
        return payload
    finally:
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


def classify_probe_stdout(raw: bytes) -> tuple[str, str, Any]:
    """Classify retained child stdout without erasing its rejection cause."""

    if not raw:
        return "empty", "empty_bytes", {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "non_json", "invalid_utf8", {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "non_json", "invalid_json", {}
    if not isinstance(payload, dict):
        return "non_object", "json_value_not_object", None
    return "object", "json_object", payload


def sealed_import_probe_claim_predicates(
    stdout_classification: str,
    child_payload: Any,
    expected_modules: set[str],
) -> dict[str, bool]:
    """Return every child-claim predicate used by the unchanged PASS gate."""

    is_object = stdout_classification == "object" and isinstance(child_payload, dict)
    imported_modules: set[Any] = set()
    if is_object:
        try:
            imported_modules = set(child_payload.get("imported_modules", ()))
        except TypeError:
            imported_modules = set()
    return {
        "stdout_is_json_object": is_object,
        "schema_exact": is_object
        and child_payload.get("schema")
        == "planora.agh-fal17.native-v18-sealed-import-probe.v1",
        "status_pass": is_object and child_payload.get("status") == "PASS",
        "imported_modules_exact": is_object and imported_modules == expected_modules,
        "truth_schema_exact": is_object and validate_probe_truth_schema(child_payload),
        "official_instance_unopened": is_object
        and child_payload.get("official_instance_opened") is False,
        "solver_execution_not_started": is_object
        and child_payload.get("solver_execution_started") is False,
        "official_solution_not_published": is_object
        and child_payload.get("official_solution_xml_published") is False,
        "runner_sha256_start_exact": is_object
        and child_payload.get("runner_sha256_start") == EXPECTED_RUNNER_SHA256,
        "runner_sha256_end_exact": is_object
        and child_payload.get("runner_sha256_end") == EXPECTED_RUNNER_SHA256,
        "runner_hash_stable": is_object
        and child_payload.get("runner_hash_stable") is True,
    }


def bounded_probe_rejection_diagnostics(
    *,
    child_exit_code: int | None,
    stdout_raw: bytes,
    stderr_raw: bytes,
    stdout_classification: str,
    stdout_detail: str,
    acceptance_predicates: Mapping[str, bool],
) -> dict[str, Any]:
    """Build bounded diagnostics; callers must publish this only on rejection."""

    stdout_tail = stdout_raw[-REJECTION_STDOUT_TAIL_BYTES:]
    stderr_tail = stderr_raw[-REJECTION_STDERR_TAIL_BYTES:]
    predicate_results = {
        name: accepted is True for name, accepted in acceptance_predicates.items()
    }
    return {
        "child_exit_code": child_exit_code,
        "failed_predicates": [
            name for name, accepted in predicate_results.items() if not accepted
        ],
        "predicate_results": predicate_results,
        "stdout": {
            "classification": stdout_classification,
            "detail": stdout_detail,
            "size_bytes": len(stdout_raw),
            "sha256": sha256(stdout_raw).hexdigest(),
            "tail": {
                "encoding": "base64",
                "maximum_bytes": REJECTION_STDOUT_TAIL_BYTES,
                "captured_bytes": len(stdout_tail),
                "truncated": len(stdout_raw) > len(stdout_tail),
                "data": base64.b64encode(stdout_tail).decode("ascii"),
            },
        },
        "stderr": {
            "size_bytes": len(stderr_raw),
            "sha256": sha256(stderr_raw).hexdigest(),
            "tail": {
                "encoding": "base64",
                "maximum_bytes": REJECTION_STDERR_TAIL_BYTES,
                "captured_bytes": len(stderr_tail),
                "truncated": len(stderr_raw) > len(stderr_tail),
                "data": base64.b64encode(stderr_tail).decode("ascii"),
            },
        },
    }


def run_sealed_import_probe() -> dict[str, Any]:
    supervisor_start = supervisor_execution_sha256()
    admitted_launcher = launcher_attestation()
    supervisor_contract_start = verify_current_supervisor_contract()
    baseline = host_sample()
    initial_supervisor_rss, initial_supervisor_swap = process_usage(os.getpid())
    initial_gate = (
        "host_initial_capture_headroom"
        if baseline["mem_available_kib"] < INITIAL_MIN_MEM_AVAILABLE_KIB
        else breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=baseline,
            launch=True,
            supervisor_rss_kib=initial_supervisor_rss,
            supervisor_vmswap_kib=initial_supervisor_swap,
        )
    )
    if initial_gate is not None:
        return {
            "status": "NO_GO",
            "resource_gate": initial_gate,
            "host_sample": baseline,
            "probe_child_process_started": False,
            "solver_child_process_started": False,
            "official_opened": False,
            "publication": False,
            "official_instance_opened": False,
            "solver_execution_started": False,
            "official_solution_xml_published": False,
            "checkpoint_or_certified_provenance_used": False,
        }
    resource.setrlimit(
        resource.RLIMIT_AS, (ADDRESS_SPACE_CAP_BYTES, ADDRESS_SPACE_CAP_BYTES)
    )
    captures: dict[str, dict[str, Any]] = {}
    inherited: list[int] = []
    runtime_initial_fd = -1
    run_dir_fd = -1
    scratch_fd = -1
    stdout_fd = -1
    stderr_fd = -1
    child: subprocess.Popen[bytes] | None = None
    process_group: int | None = None
    leader_identity: tuple[int, int, int] | None = None
    leader_pidfd: int | None = None
    admitted_members: dict[int, tuple[int, int, int]] = {}
    group_cleanup: dict[str, Any] = {
        "initial_residual_pids": [],
        "actions": [],
        "final_residual_pids": [],
        "errors": [],
        "empty": True,
    }
    try:
        for label, path in PROBE_CAPTURE_SOURCES.items():
            descriptor, evidence = _stream_capture(path, _expected_hash(label), label)
            inherited.append(descriptor)
            captures[label] = evidence
        after_capture = host_sample()
        capture_supervisor_rss, capture_supervisor_swap = process_usage(os.getpid())
        capture_gate = breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=after_capture,
            launch=True,
            supervisor_rss_kib=capture_supervisor_rss,
            supervisor_vmswap_kib=capture_supervisor_swap,
        )
        if capture_gate is not None:
            return {
                "status": "NO_GO",
                "resource_gate": capture_gate,
                "host_sample": after_capture,
                "probe_child_process_started": False,
                "solver_child_process_started": False,
                "official_opened": False,
                "publication": False,
                "official_instance_opened": False,
                "solver_execution_started": False,
                "official_solution_xml_published": False,
                "checkpoint_or_certified_provenance_used": False,
            }
        run_dir, run_dir_fd, run_identity = _private_directory(
            "planora-aghfal17-native-v18-import-probe"
        )
        inherited.append(run_dir_fd)
        scratch_dir, scratch_fd, scratch_identity = _private_directory(
            "planora-aghfal17-native-v18-import-probe-scratch"
        )
        inherited.append(scratch_fd)
        runtime_dir, runtime_initial_fd, _ = _private_runtime_directory()
        (
            runtime_root_fd,
            runtime_manifest_fd,
            runtime_file_fds,
            runtime_binding,
            runtime_summary,
        ) = build_runtime_bundle(runtime_root_fd=runtime_initial_fd, captures=captures)
        os.close(runtime_initial_fd)
        runtime_initial_fd = -1
        inherited.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        runtime_summary["directory"] = str(runtime_dir)
        output_binding = {
            "fd": run_dir_fd,
            "path": str(run_dir),
            "device": run_identity[0],
            "inode": run_identity[1],
            "mode": run_identity[2],
            "uid": run_identity[3],
        }
        environment = minimal_child_environment(
            captures=captures,
            output_binding=output_binding,
            runtime_binding=runtime_binding,
            scratch_fd=scratch_fd,
        )
        command = planned_probe_command(
            int(captures["python_binary"]["fd"]),
            int(captures["runner"]["fd"]),
            runtime_root_fd,
            Path(f"/proc/self/fd/{run_dir_fd}/.pycache-disabled"),
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
        parent_pid = os.getpid()
        started = time.monotonic()
        child = subprocess.Popen(
            command,
            pass_fds=tuple(inherited),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_fd,
            stderr=stderr_fd,
            close_fds=True,
            preexec_fn=lambda: _arm_child(parent_pid),
        )
        process_group = child.pid
        group_cleanup["empty"] = False
        leader_identity = proc_stat_identity(child.pid)
        leader_pidfd = os.pidfd_open(child.pid, 0)
        (
            process_group,
            leader_identity,
            leader_pidfd,
            admitted_members,
        ) = admit_spawned_process_group(
            child, process_group, leader_identity, leader_pidfd
        )
        peak_group_memory = 0
        peak_rss = 0
        peak_vmswap = 0
        peak_pids: tuple[int, ...] = ()
        peak_whole_rss = 0
        peak_whole_vmswap = 0
        peak_whole_memory = 0
        peak_supervisor_rss = 0
        peak_supervisor_vmswap = 0
        peak_supervisor_in_group = False
        sampled_generation_identities: set[tuple[int, tuple[int, int, int]]] = set()
        reaped_zero_contribution_events: list[dict[str, Any]] = []
        breach: str | None = None
        stop_action: str | None = None
        while child.poll() is None:
            generation = refresh_group_generation(
                process_group, leader_identity, admitted_members
            )
            if generation["errors"]:
                breach = "process_group_generation_drift"
                break
            elapsed = time.monotonic() - started
            sample = host_sample()
            accounting = generation_accounting_sample(os.getpid(), admitted_members)
            if accounting["unavailable_identities"]:
                accounting = reconcile_successfully_reaped_generation_member(
                    accounting,
                    child,
                    leader_identity,
                    admitted_members,
                    sampled_generation_identities,
                )
            if accounting["unavailable_identities"]:
                breach = "generation_identity_accounting_unavailable"
                stop_action = "identity_bound_descendant_drain"
                break
            reaped_zero_contribution_events.extend(
                accounting.get("successfully_reaped_zero_contributions", ())
            )
            sampled_generation_identities.update(
                (int(row["pid"]), admitted_members[int(row["pid"])])
                for row in accounting["sampled_processes"]
                if row["role"] == "generation_member"
                and admitted_members.get(int(row["pid"])) is not None
            )
            rss = int(accounting["group_vmrss_kib"])
            vmswap = int(accounting["group_vmswap_kib"])
            whole_rss = int(accounting["whole_launch_vmrss_kib"])
            whole_vmswap = int(accounting["whole_launch_vmswap_kib"])
            pids = tuple(
                int(row["pid"])
                for row in accounting["sampled_processes"]
                if row["role"] == "generation_member"
            )
            supervisor_row = next(
                (
                    row
                    for row in accounting["sampled_processes"]
                    if row["role"] == "supervisor"
                ),
                None,
            )
            supervisor_rss = (
                0 if supervisor_row is None else int(supervisor_row["vmrss_kib"])
            )
            supervisor_vmswap = (
                0 if supervisor_row is None else int(supervisor_row["vmswap_kib"])
            )
            supervisor_in_group = any(
                row["pid"] == os.getpid() and row["role"] == "generation_member"
                for row in accounting["sampled_processes"]
            )
            if rss + vmswap > peak_group_memory:
                peak_group_memory = rss + vmswap
                peak_rss = rss
                peak_vmswap = vmswap
                peak_pids = pids
                peak_group_accounting_sample = accounting
            whole_memory = whole_rss + whole_vmswap
            if whole_memory > peak_whole_memory:
                peak_whole_rss = whole_rss
                peak_whole_vmswap = whole_vmswap
                peak_whole_memory = whole_memory
                peak_supervisor_rss = supervisor_rss
                peak_supervisor_vmswap = supervisor_vmswap
                peak_supervisor_in_group = supervisor_in_group
                peak_whole_accounting_sample = accounting
            breach = breach_reason(
                elapsed=elapsed,
                group_rss_kib=rss,
                group_vmswap_kib=vmswap,
                sample=sample,
                launch=False,
                supervisor_rss_kib=supervisor_rss,
                supervisor_vmswap_kib=supervisor_vmswap,
                supervisor_in_group=supervisor_in_group,
            )
            if elapsed >= SEALED_IMPORT_PROBE_HARD_WALL_SECONDS:
                breach = "sealed_import_probe_hard_wall"
            if breach is not None:
                stop_action = "identity_bound_descendant_drain"
                break
            time.sleep(POLL_SECONDS)
        if child.poll() is None:
            group_cleanup.update(
                stop_group(
                    child,
                    process_group,
                    leader_identity,
                    leader_pidfd,
                    admitted_members,
                )
            )
        try:
            exit_code = child.wait(timeout=5)
        except BaseException as exc:
            exit_code = child.returncode
            group_cleanup["errors"].append(
                f"post_cleanup_wait:{type(exc).__name__}:{exc}"
            )
        elapsed = time.monotonic() - started
        if not group_cleanup.get("empty"):
            group_cleanup.update(
                stop_group(
                    child,
                    process_group,
                    leader_identity,
                    leader_pidfd,
                    admitted_members,
                )
            )
        os.close(stdout_fd)
        stdout_fd = -1
        os.close(stderr_fd)
        stderr_fd = -1
        stdout_raw, stdout_identity = _read_relative_regular(
            run_dir_fd, "child.stdout.log", maximum_bytes=64 << 20
        )
        stderr_raw, stderr_identity = _read_relative_regular(
            run_dir_fd, "child.stderr.log", maximum_bytes=32 << 20
        )
        (
            stdout_classification,
            stdout_detail,
            child_payload,
        ) = classify_probe_stdout(stdout_raw)
        expected_modules = {
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
        }
        acceptance_predicates = {
            "child_exit_zero": exit_code == 0,
            "no_resource_or_timeout_breach": breach is None,
            "process_group_cleanup_empty": group_cleanup["empty"] is True,
            "process_group_cleanup_error_free": not group_cleanup.get("errors", ()),
        }
        errors: list[str] = []
        if exit_code != 0:
            errors.append(f"child_exit_code:{exit_code}")
        if breach is not None:
            errors.append(f"resource_or_timeout_breach:{breach}")
        if not group_cleanup["empty"]:
            errors.append("process_group_cleanup_incomplete")
        errors.extend(
            "process_group_cleanup:" + str(value)
            for value in group_cleanup.get("errors", ())
        )
        claim_predicates = sealed_import_probe_claim_predicates(
            stdout_classification, child_payload, expected_modules
        )
        acceptance_predicates.update(claim_predicates)
        if not all(claim_predicates.values()):
            errors.append("sealed_import_probe_claim_mismatch")
        scratch_entries = sorted(
            entry.name for entry in os.scandir(f"/proc/self/fd/{scratch_fd}")
        )
        scratch_named = os.lstat(scratch_dir)
        private_scratch_contract = (
            not scratch_entries
            and (
                int(scratch_named.st_dev),
                int(scratch_named.st_ino),
                stat.S_IMODE(scratch_named.st_mode),
                int(scratch_named.st_uid),
            )
            == scratch_identity
        )
        acceptance_predicates["private_scratch_contract"] = private_scratch_contract
        if not private_scratch_contract:
            errors.append("private_scratch_contract_rejected")
        capture_end = {
            label: verify_sealed_capture(int(row["fd"]), row)
            for label, row in captures.items()
        }
        runtime_end = replay_runtime_bundle(runtime_binding)
        source_end = {
            label: verify_source_contract(row) for label, row in captures.items()
        }
        supervisor_contract_stable = not (
            verify_current_supervisor_contract() != supervisor_contract_start
            or supervisor_execution_sha256() != supervisor_start
        )
        acceptance_predicates["supervisor_contract_stable"] = supervisor_contract_stable
        if not supervisor_contract_stable:
            errors.append("supervisor_contract_drift")
        launcher_bootstrap_stable = launcher_attestation() == admitted_launcher
        acceptance_predicates["sealed_launcher_bootstrap_stable"] = (
            launcher_bootstrap_stable
        )
        if not launcher_bootstrap_stable:
            errors.append("sealed_launcher_bootstrap_drift")
        payload = {
            "schema": "planora.agh-fal17.native-v18-sealed-import-supervisor.v1",
            "status": "PASS" if not errors else "FAILED",
            "errors": errors,
            "breach": breach,
            "stop_action": stop_action,
            "child_exit_code": exit_code,
            "observed_child_elapsed_seconds": elapsed,
            "probe_hard_wall_seconds": SEALED_IMPORT_PROBE_HARD_WALL_SECONDS,
            "peak_process_group_rss_kib": peak_rss,
            "peak_process_group_vmswap_kib": peak_vmswap,
            "peak_process_group_vmrss_plus_vmswap_kib": peak_group_memory,
            "peak_process_group_pids": list(peak_pids),
            "peak_whole_launch_rss_kib": peak_whole_rss,
            "peak_whole_launch_vmswap_kib": peak_whole_vmswap,
            "peak_whole_launch_vmrss_plus_vmswap_kib": peak_whole_memory,
            "peak_whole_launch_supervisor_rss_kib": peak_supervisor_rss,
            "peak_whole_launch_supervisor_vmswap_kib": peak_supervisor_vmswap,
            "peak_whole_launch_supervisor_in_child_group": peak_supervisor_in_group,
            "peak_process_group_accounting_sample": peak_group_accounting_sample,
            "peak_whole_launch_accounting_sample": peak_whole_accounting_sample,
            "probe_accounting_source": (
                "exact_generation_admitted_identities_plus_supervisor_pid"
            ),
            "probe_numeric_pgid_accounting_rescan_used": False,
            "successfully_reaped_zero_contributions": reaped_zero_contribution_events,
            "process_group_vmrss_plus_vmswap_limit_kib": PROCESS_GROUP_MEMORY_LIMIT_KIB,
            "whole_launch_vmrss_plus_vmswap_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
            "process_group_cleanup": group_cleanup,
            "run_directory": str(run_dir),
            "scratch_directory": str(scratch_dir),
            "scratch_final_entries": scratch_entries,
            "sealed_runtime_bundle": runtime_summary,
            "sealed_runtime_bundle_final_replay": runtime_end,
            "sealed_captures": capture_end,
            "final_source_rehash": source_end,
            "external_launcher_attestation": admitted_launcher,
            "stdout": {
                **stdout_identity,
                "sha256": sha256(stdout_raw).hexdigest(),
            },
            "stderr": {
                **stderr_identity,
                "sha256": sha256(stderr_raw).hexdigest(),
            },
            "probe_child_process_started": True,
            "solver_child_process_started": False,
            "official_opened": False,
            "publication": False,
            "official_instance_opened": False,
            "solver_execution_started": False,
            "official_solution_xml_published": False,
            "checkpoint_or_certified_provenance_used": False,
        }
        if errors:
            payload["rejection_diagnostics"] = bounded_probe_rejection_diagnostics(
                child_exit_code=exit_code,
                stdout_raw=stdout_raw,
                stderr_raw=stderr_raw,
                stdout_classification=stdout_classification,
                stdout_detail=stdout_detail,
                acceptance_predicates=acceptance_predicates,
            )
        else:
            payload["child_payload"] = child_payload
        return payload
    finally:
        if (
            child is not None
            and process_group is not None
            and not group_cleanup["empty"]
        ):
            group_cleanup.update(
                stop_group(
                    child,
                    process_group,
                    leader_identity,
                    leader_pidfd,
                    admitted_members,
                )
            )
        if leader_pidfd is not None:
            os.close(leader_pidfd)
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


def validate_probe_truth_schema(payload: Mapping[str, Any]) -> bool:
    """Reject any probe result that blurs probe, solver, input, or publication."""

    return (
        payload.get("probe_child_process_started") is True
        and payload.get("solver_child_process_started") is False
        and payload.get("official_opened") is False
        and payload.get("publication") is False
    )


def static_pins() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for label, path in CAPTURE_SOURCES.items():
        if label == "official_instance":
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
            group_rss_kib=PROCESS_GROUP_MEMORY_LIMIT_KIB - 1,
            group_vmswap_kib=1,
            sample=sample,
            launch=False,
        )
        != "process_group_vmrss_plus_vmswap_limit"
    ):
        raise AssertionError("combined process-group memory limit not enforced")
    if (
        breach_reason(
            elapsed=0,
            group_rss_kib=PROCESS_GROUP_MEMORY_LIMIT_KIB - 1,
            group_vmswap_kib=0,
            sample=sample,
            launch=False,
        )
        is not None
    ):
        raise AssertionError(
            "combined process-group memory exact lower boundary rejected"
        )
    if (
        breach_reason(
            elapsed=0,
            group_rss_kib=PROCESS_GROUP_MEMORY_LIMIT_KIB - 1,
            group_vmswap_kib=0,
            supervisor_rss_kib=(
                WHOLE_LAUNCH_MEMORY_LIMIT_KIB - PROCESS_GROUP_MEMORY_LIMIT_KIB + 1
            ),
            supervisor_vmswap_kib=0,
            supervisor_in_group=False,
            sample=sample,
            launch=False,
        )
        != "whole_launch_vmrss_plus_vmswap_limit"
    ):
        raise AssertionError("combined whole-launch memory limit not enforced")
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
    command = planned_command(16, 17, 18, Path("/tmp/nonexistent-private-pycache"))
    for flag in (
        "--execute-completion",
        "--allow-official-input",
        "--allow-solver",
        "--allow-publication",
    ):
        if flag not in command:
            raise AssertionError(f"planned command lost gate {flag}")
    return {
        "status": "PASS",
        "process_group_monitoring": True,
        "inner_monitoring_without_double_count": True,
        "outer_controller_authoritative": True,
        "pdeathsig": int(PARENT_DEATH_SIGNAL),
        "address_space_cap_bytes": ADDRESS_SPACE_CAP_BYTES,
        "initial_min_mem_available_kib": INITIAL_MIN_MEM_AVAILABLE_KIB,
        "child_acceptance_cooperative_deadline_seconds": CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS,
        "supervisor_hard_wall_seconds": SUPERVISOR_HARD_WALL_SECONDS,
        "process_group_vmrss_plus_vmswap_limit_kib": PROCESS_GROUP_MEMORY_LIMIT_KIB,
        "whole_launch_vmrss_plus_vmswap_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
        "host_swap_counters_telemetry_only": True,
        "external_launcher_attestation": launcher_attestation(),
        "runner_execution": "sealed_memfd_exact_bytes",
        "repo_modules_execution": "sealed_memfd_exact_bytes",
        "official_instance_opened": False,
        "solver_execution_started": False,
        "solver_child_process_started": False,
        "official_solution_xml_published": False,
        "checkpoint_or_certified_provenance_used": False,
    }


def dry_run() -> dict[str, Any]:
    sample = host_sample()
    supervisor_rss, supervisor_swap = process_usage(os.getpid())
    gate = (
        "host_initial_capture_headroom"
        if sample["mem_available_kib"] < INITIAL_MIN_MEM_AVAILABLE_KIB
        else breach_reason(
            elapsed=0,
            group_rss_kib=0,
            group_vmswap_kib=0,
            sample=sample,
            launch=True,
            supervisor_rss_kib=supervisor_rss,
            supervisor_vmswap_kib=supervisor_swap,
        )
    )
    return {
        "status": "GO_FOR_INDEPENDENT_REVIEW" if gate is None else "NO_GO",
        "resource_gate": gate,
        "host_sample": sample,
        "external_launcher_attestation": launcher_attestation(),
        "static_pins_excluding_official_full_input": static_pins(),
        "expected_official_input_sha256": EXPECTED_HASHES["official_instance"],
        "official_input_path": str(OFFICIAL_INSTANCE),
        "official_input_opened": False,
        "run_directory_created": False,
        "solver_execution_started": False,
        "solver_child_process_started": False,
        "official_solution_xml_published": False,
        "checkpoint_or_certified_provenance_used": False,
        "launch_requires_explicit_flag": "--launch",
        "child_acceptance_cooperative_deadline_seconds": CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS,
        "supervisor_hard_wall_seconds": SUPERVISOR_HARD_WALL_SECONDS,
        "initial_min_mem_available_kib": INITIAL_MIN_MEM_AVAILABLE_KIB,
        "sealed_runtime_bundle_expected_files": EXPECTED_RUNTIME_BUNDLE_FILES,
        "sealed_runtime_bundle_expected_bytes": EXPECTED_RUNTIME_BUNDLE_BYTES,
    }


def main() -> int:
    if globals().get(
        "__external_loader_protocol__"
    ) != EXTERNAL_LOADER_PROTOCOL or globals().get(
        "__external_expected_supervisor_sha256__"
    ) != globals().get("__captured_sha256__"):
        raise SystemExit("direct AGH-FAL17 native v11 supervisor execution rejected")
    launcher_attestation()
    verify_current_supervisor_contract()
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
        result = run_sealed_import_probe()
    else:
        result = run_supervised()
    if (
        supervisor_execution_sha256() != start_hash
        or verify_current_supervisor_contract() != start_contract
    ):
        raise RuntimeError("supervisor bytes/path changed during execution")
    result["supervisor_sha256_start"] = start_hash
    result["supervisor_sha256_end"] = start_hash
    result["supervisor_hash_stable"] = True
    result["supervisor_execution_transport"] = "external_captured_exact_bytes"
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return (
        0
        if result.get("status")
        in {"PASS", "GO_FOR_INDEPENDENT_REVIEW", "COMPLETION_VALID"}
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
