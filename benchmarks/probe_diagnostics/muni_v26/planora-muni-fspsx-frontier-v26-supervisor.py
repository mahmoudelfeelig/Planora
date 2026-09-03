#!/usr/bin/env python3
"""Attribution-safe immutable supervisor for the MUNI-FSPSX v26 diagnostic."""

from __future__ import annotations

import argparse
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
import ctypes
import errno
import fcntl
from hashlib import sha256
from importlib.metadata import distributions
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
CHAIN_ROOT = ROOT / "benchmarks/probe_diagnostics/muni_v26"
PYTHON = Path("/usr/bin/python3.12")
SITE_PACKAGES = ROOT / ".venv/lib/python3.12/site-packages"
SUPERVISOR = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-supervisor.py"
LAUNCHER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-launcher.sh"
RUNNER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-runner.py"
FREEZE_MANIFEST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json"
STDLIB_MANIFEST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-stdlib.sha256"
EXPECTED_STDLIB_MANIFEST_SHA256 = (
    "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327"
)
INSTANCE = ROOT / (
    "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/"
    "muni-fspsx-fal17.xml"
)
PROGRESS = Path("/tmp/planora-muni-fspsx-hall-objective-v35-progress.json")
EXPECTED_INSTANCE_SHA256 = (
    "151664dfc27f377e5048cf0bf8ad48fac350c46a7db6ca7181fed6d1933960b6"
)
EXPECTED_PROGRESS_SHA256 = (
    "5cf7e3450ff96d79b3a5dbac1baa784a585b777397603d379a91513ada35cedf"
)
EXPECTED_OPEN_CLASSES = 152
EXPECTED_FIXED_CLASSES = 1471
EXPECTED_FRONTIER_SHA256 = "ade6b42c3baa08a53454db3842b0c4f3cd2e2738c6eb0c54108f419a148d7793"
EXPECTED_FRONTIER_TEST_SHA256 = "ef125a8c9ea64500074700fe0f6b445f5f686832f0f32bf39bc6f35430615ed0"
WALL_SECONDS = 630.0
SEALED_IMPORT_PROBE_WALL_SECONDS = 180.0
RUNNER_SECONDS = 600.0
LAUNCH_MEMAVAILABLE_FLOOR_KIB = 1_900_000
RUNTIME_MEMAVAILABLE_FLOOR_KIB = 650_000
PROCESS_GROUP_MEMORY_CAP_KIB = 700_000
WHOLE_LAUNCH_MEMORY_CAP_KIB = 700_000
POLL_SECONDS = 0.25
TERMINATION_GRACE_SECONDS = 5.0
PROBE_STDIO_TAIL_BYTES = 4096
CP_MODEL_COMPILE_WARNING_MESSAGE = (
    "Bitwise inversion '~' on bool is deprecated. This returns the bitwise "
    "inversion of the underlying int object and is usually not what you expect "
    "from negating a bool. Use the 'not' operator for boolean negation or "
    "~int(x) if you really want the bitwise inversion of the underlying int."
)
CP_MODEL_SOURCE_SHA256 = (
    "b5f2a3ae5c418d11af23cb77a766fa10103c8bb71703dafa1ecad74823603f25"
)
ALL_SEALS = 0x0F
REQUIRED_SEALS = ALL_SEALS
PR_SET_PDEATHSIG = 1
STOP_SIGNALS = tuple(
    value
    for value in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None))
    if value is not None
)
SEALED_SELF_EVIDENCE = globals().get("__planora_supervisor_evidence__")
SEALED_LAUNCHER_EVIDENCE = globals().get("__planora_launcher_evidence__")
SEALED_MANIFEST_EVIDENCE = globals().get("__planora_freeze_manifest_evidence__")
PRE_SUPERVISOR_STDLIB_EVIDENCE = globals().get(
    "__planora_pre_supervisor_stdlib_evidence__"
)
CAPTURE_MANIFEST_ENV = "MUNI_FSPSX_FRONTIER_V10_CAPTURE_MANIFEST"
RUNTIME_BUNDLE_ENV = "MUNI_FSPSX_FRONTIER_V10_RUNTIME_BUNDLE"
RUNNER_LOADER_PROTOCOL = "planora.muni-fspsx.frontier-v26-runner-loader.v1"
RUNTIME_BUNDLE_PROTOCOL = "planora.muni-fspsx.frontier-v26-sealed-runtime.v1"
CACHE_RELEASE_ADVISORY = "POSIX_FADV_DONTNEED"
CACHE_RELEASE_PHASE = "after_stable_read_hash_size_verification_and_sealed_copy"
STREAM_CHUNK_BYTES = 1 << 20
MEMFD_PAGE_SIZE_BYTES = 4096
INITIAL_ADMISSION_PHASE = "initial_pre_admission"
RUNTIME_SOURCE_PHASE = "runtime_source_sealed"
RUNTIME_MANIFEST_PHASE = "runtime_manifest_sealed"
RUNTIME_RESOURCE_PROTOCOL = (
    "planora.muni-fspsx.frontier-v26-runtime-resource-checkpoints.v1"
)
EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256 = (
    "426a8b55f35aba4cabef808823cf9e25b3dd546dcb506a75bee6c10c4126105a"
)
MAX_RUNTIME_BUNDLE_FILES = 6_000
MAX_RUNTIME_BUNDLE_BYTES = 512 << 20
MAX_RUNTIME_FILE_BYTES = 128 << 20
RUNTIME_RECORDS = {
    "runtime_ortools_record": SITE_PACKAGES / "ortools-9.15.6755.dist-info/RECORD",
    "runtime_numpy_record": SITE_PACKAGES / "numpy-2.4.2.dist-info/RECORD",
    "runtime_pandas_record": SITE_PACKAGES / "pandas-3.0.1.dist-info/RECORD",
    "runtime_dateutil_record": SITE_PACKAGES / "python_dateutil-2.9.0.post0.dist-info/RECORD",
    "runtime_six_record": SITE_PACKAGES / "six-1.17.0.dist-info/RECORD",
    "runtime_absl_record": SITE_PACKAGES / "absl_py-2.4.0.dist-info/RECORD",
    "runtime_immutabledict_record": SITE_PACKAGES / "immutabledict-4.3.1.dist-info/RECORD",
    "runtime_protobuf_record": SITE_PACKAGES / "protobuf-6.33.5.dist-info/RECORD",
    "runtime_typing_extensions_record": SITE_PACKAGES / "typing_extensions-4.15.0.dist-info/RECORD",
}
EXPECTED_RUNTIME_RECORD_LABELS = frozenset(RUNTIME_RECORDS)
PLANORA_FRESH_MODULES = {
    name: ROOT / f"benchmarks/{name}.py"
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
}
IN_NONBLOCK = getattr(os, "O_NONBLOCK", 0x800)
IN_CLOEXEC = getattr(os, "O_CLOEXEC", 0x80000)
IN_SOURCE_MUTATION_MASK = (
    0x00000002  # IN_MODIFY
    | 0x00000004  # IN_ATTRIB
    | 0x00000008  # IN_CLOSE_WRITE
    | 0x00000400  # IN_DELETE_SELF
    | 0x00000800  # IN_MOVE_SELF
)

_LIBC = ctypes.CDLL(None, use_errno=True)
_PRCTL = _LIBC.prctl
_PRCTL.argtypes = (
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
)
_PRCTL.restype = ctypes.c_int
POST_POPEN_ADMISSION_TEST_HOOK = None
PROBE_REPORT_POST_CHILD_TEST_HOOK = None


RUNNER_LOADER = r'''
import fcntl, hashlib, json, os, signal, stat, sys
ALL=0x0F
runner_fd=int(sys.argv[1]); expected=sys.argv[2]; evidence=json.loads(sys.argv[3]); runtime_root_fd=int(sys.argv[4]); stdlib_fd=int(sys.argv[5]); stdlib_expected=sys.argv[6]; child_argv=sys.argv[7:]
def read(fd):
    size=os.fstat(fd).st_size; out=[]; off=0
    while off<size:
        part=os.pread(fd,min(1<<20,size-off),off)
        if not part: raise RuntimeError("short runner descriptor read")
        out.append(part); off+=len(part)
    return b"".join(out)
source=read(runner_fd); digest=hashlib.sha256(source).hexdigest(); seals=fcntl.fcntl(runner_fd,getattr(fcntl,"F_GET_SEALS",1034))
if digest!=expected or seals&ALL!=ALL: raise RuntimeError("sealed runner drift")
stdlib_raw=read(stdlib_fd); stdlib_digest=hashlib.sha256(stdlib_raw).hexdigest(); stdlib_seals=fcntl.fcntl(stdlib_fd,getattr(fcntl,"F_GET_SEALS",1034))
if stdlib_digest!=stdlib_expected or stdlib_seals&ALL!=ALL: raise RuntimeError("sealed stdlib manifest drift")
stdlib={}
for line in stdlib_raw.decode("utf-8").splitlines():
    h,path=line.split("  ",1)
    if len(h)!=64 or not path.startswith("/usr/lib/python3.12/") or path in stdlib: raise RuntimeError("stdlib manifest row rejected")
    stdlib[path]=h
if not stdlib: raise RuntimeError("stdlib manifest empty")
root_mount=False
for line in open("/proc/self/mountinfo",encoding="utf-8"):
    pre=line.split(" - ",1)[0].split()
    if len(pre)>=6 and pre[4]=="/" and "ro" in pre[5].split(","): root_mount=True
if not root_mount: raise RuntimeError("stdlib filesystem is not frozen read-only")
def admit(path):
    resolved=os.path.realpath(path)
    if resolved!=path or resolved not in stdlib: raise RuntimeError("unbound stdlib module: "+path)
    current=resolved
    while True:
        row=os.stat(current,follow_symlinks=False)
        if row.st_uid!=65534 or row.st_gid!=65534 or stat.S_IMODE(row.st_mode)&0o022: raise RuntimeError("stdlib ownership/permissions rejected: "+current)
        if current=="/": break
        current=os.path.dirname(current)
    fd=os.open(resolved,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
    try:
        before=os.fstat(fd); raw=read(fd); after=os.fstat(fd)
    finally: os.close(fd)
    if not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or hashlib.sha256(raw).hexdigest()!=stdlib[resolved]: raise RuntimeError("stdlib file admission rejected: "+resolved)
for module in tuple(sys.modules.values()):
    raw=getattr(module,"__file__",None)
    if isinstance(raw,str) and not raw.startswith("<frozen "): admit(raw)
binding=json.loads(os.environ["MUNI_FSPSX_FRONTIER_V10_RUNTIME_BUNDLE"]); runtime_row=os.fstat(runtime_root_fd)
runtime_identity=(int(runtime_row.st_dev),int(runtime_row.st_ino),stat.S_IMODE(runtime_row.st_mode),int(runtime_row.st_uid))
if binding.get("root_fd")!=runtime_root_fd or tuple(binding.get("root_identity",()))!=runtime_identity or not stat.S_ISDIR(runtime_row.st_mode) or runtime_identity[2:]!=(0o500,os.getuid()): raise RuntimeError("sealed runtime root binding rejected")
if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode: raise RuntimeError("Python isolation flags rejected")
sys.path.insert(0,f"/proc/self/fd/{runtime_root_fd}"); sys.dont_write_bytecode=True
sys.argv=["sealed:muni-v26-runner",*child_argv]
scope={"__name__":"__main__","__package__":None,"__file__":"sealed:muni-v26-runner","__planora_runner_evidence__":{"fd":runner_fd,"sha256":digest},"__planora_stdlib_evidence__":{"fd":stdlib_fd,"sha256":stdlib_digest,"pre_runner_admitted":True},"__planora_source_evidence__":evidence,"__captured_sha256__":digest,"__runner_loader_protocol__":"planora.muni-fspsx.frontier-v26-runner-loader.v1"}
exec(compile(source,"sealed:muni-v26-runner","exec"),scope)
'''


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def file_identity(observed: os.stat_result) -> dict[str, int]:
    return {
        "device": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "uid": int(observed.st_uid),
        "mode": stat.S_IMODE(observed.st_mode),
        "size": int(observed.st_size),
        "nlink": int(observed.st_nlink),
    }


def read_fd(fd: int) -> bytes:
    size = int(os.fstat(fd).st_size)
    output: list[bytes] = []
    offset = 0
    while offset < size:
        block = os.pread(fd, min(1 << 20, size - offset), offset)
        if not block:
            raise RuntimeError("short descriptor read")
        output.append(block)
        offset += len(block)
    return b"".join(output)


def capture_regular(path: Path) -> tuple[bytes, dict[str, int]]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"not a regular file: {path}")
        value = read_fd(fd)
        after = os.fstat(fd)
        if file_identity(before) != file_identity(after):
            raise RuntimeError(f"file identity changed during capture: {path}")
        return value, file_identity(before)
    finally:
        os.close(fd)


def verify_run_directory_binding(
    path: Path, directory_fd: int, expected: Mapping[str, int]
) -> dict[str, int]:
    observed = os.fstat(directory_fd)
    actual = file_identity(observed)
    for key in ("device", "inode", "uid", "mode"):
        if actual[key] != int(expected[key]):
            raise RuntimeError("bound run directory identity drift")
    if not stat.S_ISDIR(observed.st_mode) or actual["mode"] != 0o700:
        raise RuntimeError("bound run directory is not private")
    try:
        named = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("run directory name detached from bound FD") from exc
    named_identity = file_identity(named)
    if stat.S_ISLNK(named.st_mode) or any(
        named_identity[key] != actual[key]
        for key in ("device", "inode", "uid", "mode")
    ):
        raise RuntimeError("run directory name no longer matches bound FD")
    return actual


def capture_regular_at(
    directory_fd: int, name: str, *, maximum_bytes: int = 128 << 20
) -> tuple[bytes, dict[str, int]]:
    if Path(name).name != name:
        raise RuntimeError("artifact name rejected")
    fd = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"not a regular artifact: {name}")
        if before.st_size < 0 or before.st_size > maximum_bytes:
            raise RuntimeError(f"artifact size rejected: {name}")
        value = read_fd(fd)
        after = os.fstat(fd)
        if file_identity(before) != file_identity(after):
            raise RuntimeError(f"artifact identity changed during capture: {name}")
        return value, file_identity(after)
    finally:
        os.close(fd)


def sealed_memfd(label: str, value: bytes) -> tuple[int, dict[str, object]]:
    fd = os.memfd_create(
        label,
        getattr(os, "MFD_CLOEXEC", 1) | getattr(os, "MFD_ALLOW_SEALING", 2),
    )
    try:
        view = memoryview(value)
        offset = 0
        while offset < len(view):
            offset += os.write(fd, view[offset:])
        os.fchmod(fd, 0o400)
        fcntl.fcntl(fd, getattr(fcntl, "F_ADD_SEALS", 1033), ALL_SEALS)
        seals = int(fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)))
        if seals & ALL_SEALS != ALL_SEALS or read_fd(fd) != value:
            raise RuntimeError("sealed memfd verification failed")
        return fd, {
            "fd": fd,
            "sha256": digest_bytes(value),
            "size_bytes": len(value),
            "seals": seals,
            "identity": file_identity(os.fstat(fd)),
        }
    except BaseException:
        os.close(fd)
        raise


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


def _watch_source(path: Path) -> tuple[int, int]:
    descriptor = int(_LIBC.inotify_init1(IN_NONBLOCK | IN_CLOEXEC))
    if descriptor < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(path))
    watch = int(
        _LIBC.inotify_add_watch(
            descriptor,
            ctypes.c_char_p(os.fsencode(path)),
            ctypes.c_uint32(IN_SOURCE_MUTATION_MASK),
        )
    )
    if watch < 0:
        code = ctypes.get_errno()
        os.close(descriptor)
        raise OSError(code, os.strerror(code), str(path))
    return descriptor, watch


def _source_watch_events(evidence: Mapping[str, Any]) -> bytes:
    descriptor = evidence.get("source_watch_fd")
    if type(descriptor) is not int:
        raise RuntimeError(f"source watch absent: {evidence.get('label')}")
    chunks: list[bytes] = []
    while True:
        try:
            part = os.read(descriptor, 64 << 10)
        except BlockingIOError:
            break
        if not part:
            break
        chunks.append(part)
    return b"".join(chunks)


def _stream_capture(path: Path, expected: str, label: str) -> tuple[int, dict[str, Any]]:
    watch_fd, watch_descriptor = _watch_source(path)
    parent_before = os.lstat(path.parent)
    if not stat.S_ISDIR(parent_before.st_mode):
        raise RuntimeError(f"capture parent {label} is not a directory")
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    source_fd = -1
    target_fd = -1
    try:
        parent_opened = os.fstat(parent_fd)
        source_fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode) or source_before.st_nlink != 1:
            raise RuntimeError(f"capture source {label} contract rejected")
        target_fd = os.memfd_create(f"muni-v26-{label}", getattr(os, "MFD_ALLOW_SEALING", 0x0002))
        digest = sha256()
        offset = 0
        while offset < source_before.st_size:
            block = os.pread(source_fd, min(1 << 20, source_before.st_size - offset), offset)
            if not block:
                raise RuntimeError(f"capture source {label} ended early")
            digest.update(block)
            view = memoryview(block)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise RuntimeError(f"capture target {label} stopped accepting bytes")
                view = view[written:]
            offset += len(block)
        source_after = os.fstat(source_fd)
        named_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.lstat(path.parent)
        if _stable_identity(source_before) != _stable_identity(source_after) or _stable_identity(source_after) != _stable_identity(named_after):
            raise RuntimeError(f"capture source {label} identity drift")
        if (parent_opened.st_dev, parent_opened.st_ino) != (parent_before.st_dev, parent_before.st_ino) or (parent_after.st_dev, parent_after.st_ino) != (parent_before.st_dev, parent_before.st_ino):
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
            "source_mutation_clock": [
                int(source_after.st_mtime_ns),
                int(source_after.st_ctime_ns),
            ],
            "source_parent_identity": [int(parent_after.st_dev), int(parent_after.st_ino), stat.S_IMODE(parent_after.st_mode), int(parent_after.st_uid)],
            "source_watch_fd": watch_fd,
            "source_watch_descriptor": watch_descriptor,
            "source_watch_mask": IN_SOURCE_MUTATION_MASK,
            "transport": "sealed_memfd",
        }
        target_fd = -1
        watch_fd = -1
        return int(evidence["fd"]), evidence
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
        if watch_fd >= 0:
            os.close(watch_fd)
        os.close(parent_fd)


def verify_sealed_capture(descriptor: int, evidence: Mapping[str, Any]) -> dict[str, Any]:
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
    if _stable_identity(after) != identity or int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)) != seals:
        raise RuntimeError("sealed capture identity/seals drift")
    keys = ("device", "inode", "size", "file_type", "mode", "uid", "nlink")
    if tuple(evidence.get(key) for key in keys) != identity or seals & REQUIRED_SEALS != REQUIRED_SEALS:
        raise RuntimeError("sealed capture binding rejected")
    actual = digest.hexdigest()
    if actual != evidence.get("sha256") or actual != evidence.get("expected_sha256"):
        raise RuntimeError("sealed capture digest drift")
    return {key: evidence[key] for key in (*keys, "sha256", "seals", "required_seals", "transport", "path", "label")}


def verify_source_contract(evidence: Mapping[str, Any]) -> dict[str, Any]:
    events = _source_watch_events(evidence)
    if events:
        raise RuntimeError(f"source mutation event observed: {evidence['label']}")
    path = Path(str(evidence["path"]))
    parent = os.lstat(path.parent)
    current = os.lstat(path)
    if list(_stable_identity(current)) != evidence.get("source_identity"):
        raise RuntimeError(f"source final identity drift: {evidence['label']}")
    if [int(current.st_mtime_ns), int(current.st_ctime_ns)] != evidence.get(
        "source_mutation_clock"
    ):
        raise RuntimeError(f"source final mutation-clock drift: {evidence['label']}")
    parent_identity = [int(parent.st_dev), int(parent.st_ino), stat.S_IMODE(parent.st_mode), int(parent.st_uid)]
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
    if _stable_identity(opened) != _stable_identity(current) or digest.hexdigest() != evidence.get("sha256"):
        raise RuntimeError(f"source final rehash drift: {evidence['label']}")
    if _source_watch_events(evidence):
        raise RuntimeError(
            f"source mutation event during final replay: {evidence['label']}"
        )
    return {"path": str(path), "sha256": digest.hexdigest(), "identity": list(_stable_identity(current))}


def _pread_stable(descriptor: int, *, maximum_bytes: int) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
        raise RuntimeError("descriptor read contract rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(
            descriptor, min(1 << 20, before.st_size - offset), offset
        )
        if not block:
            raise RuntimeError("descriptor read ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if _stable_identity(after) != _stable_identity(before):
        raise RuntimeError("descriptor identity drift while reading")
    return b"".join(chunks)


def _pread_digest_stable(
    descriptor: int,
    *,
    maximum_bytes: int,
    expected_size: int | None = None,
) -> tuple[str, int, tuple[int, ...]]:
    """Hash a regular descriptor with a strict one-MiB maximum buffer."""

    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
        raise RuntimeError("descriptor digest contract rejected")
    if expected_size is not None and before.st_size != expected_size:
        raise RuntimeError("descriptor digest size mismatch before read")
    digest = sha256()
    offset = 0
    while offset < before.st_size:
        requested = min(STREAM_CHUNK_BYTES, before.st_size - offset)
        block = os.pread(descriptor, requested, offset)
        if len(block) != requested:
            raise RuntimeError("descriptor digest read ended early")
        digest.update(block)
        offset += len(block)
    if os.pread(descriptor, 1, offset):
        raise RuntimeError("descriptor digest grew while reading")
    after = os.fstat(descriptor)
    if _stable_identity(after) != _stable_identity(before):
        raise RuntimeError("descriptor identity drift while digesting")
    return digest.hexdigest(), offset, _stable_identity(after)


def _page_rounded_bytes(size: int) -> int:
    if type(size) is not int or size < 0:
        raise RuntimeError("sealed storage size rejected")
    return ((size + MEMFD_PAGE_SIZE_BYTES - 1) // MEMFD_PAGE_SIZE_BYTES) * (
        MEMFD_PAGE_SIZE_BYTES
    )


def _phase_memavailable_floor_kib(phase: str) -> int:
    if phase == INITIAL_ADMISSION_PHASE:
        return LAUNCH_MEMAVAILABLE_FLOOR_KIB
    if phase in {RUNTIME_SOURCE_PHASE, RUNTIME_MANIFEST_PHASE}:
        return RUNTIME_MEMAVAILABLE_FLOOR_KIB
    raise RuntimeError(f"unknown memory-accounting phase: {phase}")


def _identity_pinned_self_memory() -> dict[str, int]:
    pid = os.getpid()
    pinned = proc_stat_identity(pid)
    if pinned is None:
        raise RuntimeError("supervisor identity unavailable for bundle accounting")
    return identity_pinned_process_memory(pid, pinned)


def _runtime_resource_checkpoint(
    *,
    index: int,
    phase: str,
    source_relative_path: str | None,
    source_logical_bytes: int,
    cumulative_logical_bytes: int,
    cumulative_runtime_sealed_page_rounded_bytes: int,
    preexisting_sealed_page_rounded_bytes: int,
    host: Mapping[str, int] | None = None,
    process_memory: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    if type(index) is not int or index < 0:
        raise RuntimeError("runtime resource checkpoint index rejected")
    floor = _phase_memavailable_floor_kib(phase)
    sample = host_sample() if host is None else dict(host)
    memory = _identity_pinned_self_memory() if process_memory is None else dict(process_memory)
    required_host = {"mem_available_kib", "shmem_kib"}
    required_memory = {"VmRSS", "VmSwap"}
    if not required_host <= sample.keys() or not required_memory <= memory.keys():
        raise RuntimeError("runtime resource checkpoint sample incomplete")
    sealed_total = (
        preexisting_sealed_page_rounded_bytes
        + cumulative_runtime_sealed_page_rounded_bytes
    )
    if any(
        type(value) is not int or value < 0
        for value in (
            source_logical_bytes,
            cumulative_logical_bytes,
            cumulative_runtime_sealed_page_rounded_bytes,
            preexisting_sealed_page_rounded_bytes,
            int(sample["mem_available_kib"]),
            int(sample["shmem_kib"]),
            int(memory["VmRSS"]),
            int(memory["VmSwap"]),
        )
    ):
        raise RuntimeError("runtime resource checkpoint value rejected")
    process_kib = int(memory["VmRSS"]) + int(memory["VmSwap"])
    sealed_kib = sealed_total // 1024
    whole_kib = process_kib + sealed_kib
    floor_ok = int(sample["mem_available_kib"]) >= floor
    cap_ok = whole_kib <= WHOLE_LAUNCH_MEMORY_CAP_KIB
    row = {
        "index": index,
        "phase": phase,
        "memavailable_floor_kib": floor,
        "source_relative_path": source_relative_path,
        "source_logical_bytes": source_logical_bytes,
        "cumulative_logical_bytes": cumulative_logical_bytes,
        "page_size_bytes": MEMFD_PAGE_SIZE_BYTES,
        "cumulative_runtime_sealed_page_rounded_bytes": (
            cumulative_runtime_sealed_page_rounded_bytes
        ),
        "preexisting_sealed_page_rounded_bytes": (
            preexisting_sealed_page_rounded_bytes
        ),
        "cumulative_sealed_page_rounded_bytes": sealed_total,
        "sealed_storage_kib": sealed_kib,
        "mem_available_kib": int(sample["mem_available_kib"]),
        "shmem_kib": int(sample["shmem_kib"]),
        "process_rss_kib": int(memory["VmRSS"]),
        "process_swap_kib": int(memory["VmSwap"]),
        "process_memory_kib": process_kib,
        "whole_launch_accounted_kib": whole_kib,
        "whole_launch_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
        "memavailable_floor_satisfied": floor_ok,
        "whole_launch_cap_satisfied": cap_ok,
    }
    if not floor_ok:
        raise RuntimeError(f"runtime bundle {phase} MemAvailable floor")
    if not cap_ok:
        raise RuntimeError(f"runtime bundle {phase} whole-launch memory cap")
    return row


def _runtime_resource_telemetry_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _verify_runtime_resource_telemetry(
    entries: Sequence[Mapping[str, Any]],
    telemetry: object,
    *,
    preexisting_sealed_page_rounded_bytes: object,
    expected_sha256: object,
) -> dict[str, Any]:
    if (
        type(preexisting_sealed_page_rounded_bytes) is not int
        or preexisting_sealed_page_rounded_bytes < 0
        or not isinstance(telemetry, list)
        or len(telemetry) != len(entries)
    ):
        raise RuntimeError("runtime resource checkpoint telemetry rejected")
    required = frozenset(
        {
            "index", "phase", "memavailable_floor_kib", "source_relative_path",
            "source_logical_bytes", "cumulative_logical_bytes", "page_size_bytes",
            "cumulative_runtime_sealed_page_rounded_bytes",
            "preexisting_sealed_page_rounded_bytes",
            "cumulative_sealed_page_rounded_bytes", "sealed_storage_kib",
            "mem_available_kib", "shmem_kib", "process_rss_kib",
            "process_swap_kib", "process_memory_kib",
            "whole_launch_accounted_kib", "whole_launch_cap_kib",
            "memavailable_floor_satisfied", "whole_launch_cap_satisfied",
        }
    )
    logical = 0
    runtime_sealed = 0
    for index, (entry, checkpoint) in enumerate(zip(entries, telemetry, strict=True)):
        if not isinstance(checkpoint, dict) or frozenset(checkpoint) != required:
            raise RuntimeError("runtime resource checkpoint shape rejected")
        size = entry.get("size")
        if type(size) is not int or size < 0:
            raise RuntimeError("runtime resource entry size rejected")
        logical += size
        runtime_sealed += _page_rounded_bytes(size)
        expected_values = {
            "index": index,
            "phase": RUNTIME_SOURCE_PHASE,
            "memavailable_floor_kib": RUNTIME_MEMAVAILABLE_FLOOR_KIB,
            "source_relative_path": entry.get("relative_path"),
            "source_logical_bytes": size,
            "cumulative_logical_bytes": logical,
            "page_size_bytes": MEMFD_PAGE_SIZE_BYTES,
            "cumulative_runtime_sealed_page_rounded_bytes": runtime_sealed,
            "preexisting_sealed_page_rounded_bytes": (
                preexisting_sealed_page_rounded_bytes
            ),
            "cumulative_sealed_page_rounded_bytes": (
                preexisting_sealed_page_rounded_bytes + runtime_sealed
            ),
            "sealed_storage_kib": (
                preexisting_sealed_page_rounded_bytes + runtime_sealed
            ) // 1024,
            "process_memory_kib": (
                checkpoint.get("process_rss_kib", -1)
                + checkpoint.get("process_swap_kib", -1)
            ),
            "whole_launch_accounted_kib": (
                checkpoint.get("process_memory_kib", -1)
                + checkpoint.get("sealed_storage_kib", -1)
            ),
            "whole_launch_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
            "memavailable_floor_satisfied": (
                checkpoint.get("mem_available_kib", -1)
                >= RUNTIME_MEMAVAILABLE_FLOOR_KIB
            ),
            "whole_launch_cap_satisfied": (
                checkpoint.get("whole_launch_accounted_kib", -1)
                <= WHOLE_LAUNCH_MEMORY_CAP_KIB
            ),
        }
        if any(checkpoint.get(key) != value for key, value in expected_values.items()):
            raise RuntimeError("runtime resource checkpoint telemetry mismatch")
        for key in ("mem_available_kib", "shmem_kib", "process_rss_kib", "process_swap_kib"):
            if type(checkpoint.get(key)) is not int or checkpoint[key] < 0:
                raise RuntimeError("runtime resource checkpoint telemetry value rejected")
        if not checkpoint["memavailable_floor_satisfied"]:
            raise RuntimeError("runtime resource checkpoint floor evidence rejected")
        if not checkpoint["whole_launch_cap_satisfied"]:
            raise RuntimeError("runtime resource checkpoint cap evidence rejected")
    actual_sha256 = _runtime_resource_telemetry_sha256(telemetry)
    if expected_sha256 != actual_sha256:
        raise RuntimeError("runtime resource checkpoint telemetry hash mismatch")
    return {
        "schema": RUNTIME_RESOURCE_PROTOCOL,
        "checkpoint_count": len(telemetry),
        "telemetry_sha256": actual_sha256,
        "cumulative_logical_bytes": logical,
        "runtime_file_page_rounded_bytes": runtime_sealed,
        "preexisting_sealed_page_rounded_bytes": (
            preexisting_sealed_page_rounded_bytes
        ),
    }


def _captured_memfd_page_rounded_bytes(
    captures: Mapping[str, Mapping[str, Any]],
) -> int:
    total = 0
    identities: set[tuple[int, int]] = set()
    for label in sorted(captures):
        row = captures[label]
        descriptor = row.get("fd")
        size = row.get("size")
        if type(descriptor) is not int or type(size) is not int or size < 0:
            raise RuntimeError(f"captured sealed-storage evidence rejected: {label}")
        observed = os.fstat(descriptor)
        identity = (int(observed.st_dev), int(observed.st_ino))
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        if (
            identity in identities
            or not stat.S_ISREG(observed.st_mode)
            or observed.st_size != size
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
        ):
            raise RuntimeError(f"captured sealed-storage identity rejected: {label}")
        identities.add(identity)
        total += _page_rounded_bytes(size)
    return total


def _verify_runtime_final_checkpoint(
    checkpoint: object,
    *,
    entry_count: int,
    runtime_logical_bytes: int,
    runtime_file_page_rounded_bytes: int,
    manifest_size: int,
    preexisting_sealed_page_rounded_bytes: int,
    expected_sha256: object,
) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise RuntimeError("runtime final checkpoint rejected")
    required = frozenset(
        {
            "index", "phase", "memavailable_floor_kib", "source_relative_path",
            "source_logical_bytes", "cumulative_logical_bytes", "page_size_bytes",
            "cumulative_runtime_sealed_page_rounded_bytes",
            "preexisting_sealed_page_rounded_bytes",
            "cumulative_sealed_page_rounded_bytes", "sealed_storage_kib",
            "mem_available_kib", "shmem_kib", "process_rss_kib",
            "process_swap_kib", "process_memory_kib",
            "whole_launch_accounted_kib", "whole_launch_cap_kib",
            "memavailable_floor_satisfied", "whole_launch_cap_satisfied",
        }
    )
    if frozenset(checkpoint) != required:
        raise RuntimeError("runtime final checkpoint shape rejected")
    manifest_page_bytes = _page_rounded_bytes(manifest_size)
    runtime_sealed = runtime_file_page_rounded_bytes + manifest_page_bytes
    sealed_total = preexisting_sealed_page_rounded_bytes + runtime_sealed
    expected_values = {
        "index": entry_count,
        "phase": RUNTIME_MANIFEST_PHASE,
        "memavailable_floor_kib": RUNTIME_MEMAVAILABLE_FLOOR_KIB,
        "source_relative_path": None,
        "source_logical_bytes": manifest_size,
        "cumulative_logical_bytes": runtime_logical_bytes + manifest_size,
        "page_size_bytes": MEMFD_PAGE_SIZE_BYTES,
        "cumulative_runtime_sealed_page_rounded_bytes": runtime_sealed,
        "preexisting_sealed_page_rounded_bytes": preexisting_sealed_page_rounded_bytes,
        "cumulative_sealed_page_rounded_bytes": sealed_total,
        "sealed_storage_kib": sealed_total // 1024,
        "process_memory_kib": (
            checkpoint.get("process_rss_kib", -1)
            + checkpoint.get("process_swap_kib", -1)
        ),
        "whole_launch_accounted_kib": (
            checkpoint.get("process_memory_kib", -1)
            + checkpoint.get("sealed_storage_kib", -1)
        ),
        "whole_launch_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
        "memavailable_floor_satisfied": (
            checkpoint.get("mem_available_kib", -1) >= RUNTIME_MEMAVAILABLE_FLOOR_KIB
        ),
        "whole_launch_cap_satisfied": (
            checkpoint.get("whole_launch_accounted_kib", -1)
            <= WHOLE_LAUNCH_MEMORY_CAP_KIB
        ),
    }
    if any(checkpoint.get(key) != value for key, value in expected_values.items()):
        raise RuntimeError("runtime final checkpoint mismatch")
    for key in ("mem_available_kib", "shmem_kib", "process_rss_kib", "process_swap_kib"):
        if type(checkpoint.get(key)) is not int or checkpoint[key] < 0:
            raise RuntimeError("runtime final checkpoint value rejected")
    if not checkpoint["memavailable_floor_satisfied"]:
        raise RuntimeError("runtime final checkpoint floor evidence rejected")
    if not checkpoint["whole_launch_cap_satisfied"]:
        raise RuntimeError("runtime final checkpoint cap evidence rejected")
    actual_sha256 = _runtime_resource_telemetry_sha256([checkpoint])
    if actual_sha256 != expected_sha256:
        raise RuntimeError("runtime final checkpoint hash mismatch")
    return {
        "checkpoint": dict(checkpoint),
        "checkpoint_sha256": actual_sha256,
        "manifest_page_rounded_bytes": manifest_page_bytes,
        "sealed_page_rounded_bytes": sealed_total,
        "sealed_page_rounded_kib": sealed_total // 1024,
    }


def _stream_source_to_sealed_memfd(
    source_fd: int,
    *,
    name: str,
    expected_sha256: str,
    expected_size: int,
) -> tuple[int, tuple[int, ...], int, str, int, tuple[int, ...], tuple[int, ...]]:
    """Verify and seal one source without retaining a whole-file buffer."""

    source_before_row = os.fstat(source_fd)
    source_before = _stable_identity(source_before_row)
    if (
        not stat.S_ISREG(source_before_row.st_mode)
        or source_before_row.st_size != expected_size
        or expected_size > MAX_RUNTIME_FILE_BYTES
    ):
        raise RuntimeError("runtime source identity or size rejected")
    target_fd = os.memfd_create(name, getattr(os, "MFD_ALLOW_SEALING", 0x0002))
    digest = sha256()
    offset = 0
    try:
        while offset < expected_size:
            requested = min(STREAM_CHUNK_BYTES, expected_size - offset)
            block = os.pread(source_fd, requested, offset)
            if len(block) != requested:
                raise RuntimeError("runtime source short read")
            written = os.write(target_fd, block)
            if written != len(block):
                raise RuntimeError("sealed runtime target short write")
            digest.update(block)
            offset += len(block)
        if os.pread(source_fd, 1, offset):
            raise RuntimeError("runtime source grew while streaming")
        source_after_row = os.fstat(source_fd)
        source_after = _stable_identity(source_after_row)
        actual_sha256 = digest.hexdigest()
        if (
            source_after != source_before
            or offset != expected_size
            or actual_sha256 != expected_sha256
        ):
            raise RuntimeError("runtime source RECORD mismatch")
        os.lseek(target_fd, 0, os.SEEK_SET)
        os.fchmod(target_fd, 0o400)
        fcntl.fcntl(target_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        target_row = os.fstat(target_fd)
        target_identity = _stable_identity(target_row)
        seals = int(fcntl.fcntl(target_fd, fcntl.F_GET_SEALS))
        replay_sha256, replay_size, replay_identity = _pread_digest_stable(
            target_fd,
            maximum_bytes=MAX_RUNTIME_FILE_BYTES,
            expected_size=expected_size,
        )
        if (
            seals & REQUIRED_SEALS != REQUIRED_SEALS
            or replay_sha256 != expected_sha256
            or replay_size != expected_size
            or replay_identity != target_identity
        ):
            raise RuntimeError("sealed runtime target verification rejected")
        return (
            target_fd,
            target_identity,
            seals,
            actual_sha256,
            offset,
            source_before,
            source_after,
        )
    except BaseException:
        os.close(target_fd)
        raise


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
    if sum(size for _digest, size, _label in entries.values()) > MAX_RUNTIME_BUNDLE_BYTES:
        raise RuntimeError("runtime bundle byte limit exceeded")
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


def _expected_cache_release_advisories(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "relative_path": row["relative_path"],
            "sha256": row["sha256"],
            "size": row["size"],
            "offset": 0,
            "length": 0,
            "advice": CACHE_RELEASE_ADVISORY,
            "phase": CACHE_RELEASE_PHASE,
            "advisory_count": 1,
        }
        for index, row in enumerate(entries)
    ]


def _cache_release_telemetry_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _verify_cache_release_telemetry(
    entries: Sequence[Mapping[str, Any]],
    telemetry: object,
    *,
    expected_sha256: object = None,
) -> dict[str, Any]:
    expected = _expected_cache_release_advisories(entries)
    if telemetry != expected:
        raise RuntimeError("runtime source cache-release telemetry mismatch")
    actual_sha256 = _cache_release_telemetry_sha256(expected)
    if expected_sha256 is not None and expected_sha256 != actual_sha256:
        raise RuntimeError("runtime source cache-release telemetry hash mismatch")
    return {
        "advisory": CACHE_RELEASE_ADVISORY,
        "phase": CACHE_RELEASE_PHASE,
        "advisory_count": len(expected),
        "source_count": len(entries),
        "exactly_once_per_source": True,
        "telemetry_sha256": actual_sha256,
    }


def _release_runtime_source_cache(
    descriptor: int,
    *,
    index: int,
    relative_path: str,
    digest: str,
    size: int,
) -> dict[str, Any]:
    try:
        os.posix_fadvise(
            descriptor,
            0,
            0,
            os.POSIX_FADV_DONTNEED,
        )
    except (AttributeError, OSError) as exc:
        raise RuntimeError(
            f"runtime source cache-release advisory failed at index {index}"
        ) from exc
    return {
        "index": index,
        "relative_path": relative_path,
        "sha256": digest,
        "size": size,
        "offset": 0,
        "length": 0,
        "advice": CACHE_RELEASE_ADVISORY,
        "phase": CACHE_RELEASE_PHASE,
        "advisory_count": 1,
    }


def build_runtime_bundle(
    *, runtime_root_fd: int, captures: Mapping[str, Mapping[str, Any]]
) -> tuple[int, int, list[int], dict[str, Any], dict[str, Any]]:
    entries, excluded = _record_runtime_entries(captures)
    if os.sysconf("SC_PAGE_SIZE") != MEMFD_PAGE_SIZE_BYTES:
        raise RuntimeError("runtime memfd page-size contract rejected")
    root_fd = -1
    source_root_fd = -1
    runtime_fds: list[int] = []
    manifest_fd = -1
    directory_paths: set[str] = set()
    manifest_entries: list[dict[str, Any]] = []
    cache_release_advisories: list[dict[str, Any]] = []
    resource_checkpoints: list[dict[str, Any]] = []
    cumulative_logical_bytes = 0
    cumulative_runtime_sealed_bytes = 0
    try:
        root_fd = os.dup(runtime_root_fd)
        source_root_fd = os.open(
            SITE_PACKAGES,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        preexisting_sealed_bytes = _captured_memfd_page_rounded_bytes(captures)
        for index, (relative, (expected, expected_size, record_label)) in enumerate(
            sorted(entries.items())
        ):
            source_fd = os.open(
                relative,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_root_fd,
            )
            try:
                (
                    runtime_fd,
                    identity,
                    seals,
                    actual,
                    actual_size,
                    source_before,
                    source_after,
                ) = _stream_source_to_sealed_memfd(
                    source_fd,
                    name=f"muni-v26-runtime-{index}",
                    expected_sha256=expected,
                    expected_size=expected_size,
                )
                runtime_fds.append(runtime_fd)
                cache_release_advisories.append(
                    _release_runtime_source_cache(
                        source_fd,
                        index=index,
                        relative_path=relative,
                        digest=actual,
                        size=actual_size,
                    )
                )
                if _stable_identity(os.fstat(source_fd)) != source_after:
                    raise RuntimeError(
                        f"runtime source identity drift after advisory: {relative}"
                    )
            finally:
                os.close(source_fd)
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
                    "size": actual_size,
                    "device": identity[0],
                    "inode": identity[1],
                    "file_type": identity[3],
                    "mode": identity[4],
                    "uid": identity[5],
                    "nlink": identity[6],
                    "seals": seals,
                    "required_seals": REQUIRED_SEALS,
                    "source_identity_before": list(source_before),
                    "source_identity_after": list(source_after),
                }
            )
            cumulative_logical_bytes += actual_size
            cumulative_runtime_sealed_bytes += _page_rounded_bytes(actual_size)
            resource_checkpoints.append(
                _runtime_resource_checkpoint(
                    index=index,
                    phase=RUNTIME_SOURCE_PHASE,
                    source_relative_path=relative,
                    source_logical_bytes=actual_size,
                    cumulative_logical_bytes=cumulative_logical_bytes,
                    cumulative_runtime_sealed_page_rounded_bytes=(
                        cumulative_runtime_sealed_bytes
                    ),
                    preexisting_sealed_page_rounded_bytes=preexisting_sealed_bytes,
                )
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
        cache_release = _verify_cache_release_telemetry(
            manifest_entries,
            cache_release_advisories,
        )
        if (
            frozenset(RUNTIME_RECORDS) == EXPECTED_RUNTIME_RECORD_LABELS
            and cache_release["telemetry_sha256"]
            != EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256
        ):
            raise RuntimeError("runtime source cache-release telemetry pin mismatch")
        resource_telemetry_sha256 = _runtime_resource_telemetry_sha256(
            resource_checkpoints
        )
        resource_replay = _verify_runtime_resource_telemetry(
            manifest_entries,
            resource_checkpoints,
            preexisting_sealed_page_rounded_bytes=preexisting_sealed_bytes,
            expected_sha256=resource_telemetry_sha256,
        )
        manifest = {
            "schema": "planora.muni-fspsx.frontier-v26-sealed-runtime.v1",
            "site_packages_source": str(SITE_PACKAGES),
            "source_root_identity": list(_stable_identity(os.fstat(source_root_fd))),
            "root_fd": root_fd,
            "root_identity": list(root_identity),
            "entries": manifest_entries,
            "source_cache_release_advisories": cache_release_advisories,
            "source_cache_release_telemetry_sha256": cache_release[
                "telemetry_sha256"
            ],
            "resource_checkpoint_protocol": RUNTIME_RESOURCE_PROTOCOL,
            "resource_checkpoints": resource_checkpoints,
            "resource_checkpoint_telemetry_sha256": resource_telemetry_sha256,
            "preexisting_sealed_page_rounded_bytes": preexisting_sealed_bytes,
            "excluded_record_rows": excluded,
            "pyc_entries_excluded": True,
        }
        manifest_raw = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest_fd, manifest_identity, manifest_seals = _seal_bytes(
            "muni-v26-runtime-manifest", manifest_raw
        )
        manifest_page_bytes = _page_rounded_bytes(len(manifest_raw))
        final_checkpoint = _runtime_resource_checkpoint(
            index=len(manifest_entries),
            phase=RUNTIME_MANIFEST_PHASE,
            source_relative_path=None,
            source_logical_bytes=len(manifest_raw),
            cumulative_logical_bytes=cumulative_logical_bytes + len(manifest_raw),
            cumulative_runtime_sealed_page_rounded_bytes=(
                cumulative_runtime_sealed_bytes + manifest_page_bytes
            ),
            preexisting_sealed_page_rounded_bytes=preexisting_sealed_bytes,
        )
        final_checkpoint_sha256 = _runtime_resource_telemetry_sha256(
            [final_checkpoint]
        )
        sealed_page_rounded_bytes = int(
            final_checkpoint["cumulative_sealed_page_rounded_bytes"]
        )
        binding = {
            "protocol": "planora.muni-fspsx.frontier-v26-sealed-runtime.v1",
            "root_fd": root_fd,
            "root_identity": list(root_identity),
            "manifest_fd": manifest_fd,
            "manifest_sha256": sha256(manifest_raw).hexdigest(),
            "manifest_size": len(manifest_raw),
            "manifest_identity": list(manifest_identity),
            "manifest_seals": manifest_seals,
            "required_seals": REQUIRED_SEALS,
            "source_cache_release_advisory_count": cache_release[
                "advisory_count"
            ],
            "source_cache_release_telemetry_sha256": cache_release[
                "telemetry_sha256"
            ],
            "resource_checkpoint_protocol": RUNTIME_RESOURCE_PROTOCOL,
            "resource_checkpoint_telemetry_sha256": resource_telemetry_sha256,
            "resource_final_checkpoint": final_checkpoint,
            "resource_final_checkpoint_sha256": final_checkpoint_sha256,
            "preexisting_sealed_page_rounded_bytes": preexisting_sealed_bytes,
            "runtime_file_page_rounded_bytes": cumulative_runtime_sealed_bytes,
            "runtime_manifest_page_rounded_bytes": manifest_page_bytes,
            "sealed_page_rounded_bytes": sealed_page_rounded_bytes,
            "sealed_page_rounded_kib": sealed_page_rounded_bytes // 1024,
            "page_size_bytes": MEMFD_PAGE_SIZE_BYTES,
        }
        summary = {
            "manifest_sha256": binding["manifest_sha256"],
            "manifest_size": len(manifest_raw),
            "file_count": len(manifest_entries),
            "total_bytes": sum(row["size"] for row in manifest_entries),
            "excluded_record_row_count": len(excluded),
            "root_identity": list(root_identity),
            "transport": "read_only_symlink_tree_to_sealed_memfds",
            "source_cache_release": cache_release,
            "resource_accounting": {
                **resource_replay,
                "final_checkpoint": final_checkpoint,
                "final_checkpoint_sha256": final_checkpoint_sha256,
                "runtime_manifest_page_rounded_bytes": manifest_page_bytes,
                "sealed_page_rounded_bytes": sealed_page_rounded_bytes,
                "sealed_page_rounded_kib": sealed_page_rounded_bytes // 1024,
            },
        }
        transferred_root_fd = root_fd
        transferred_manifest_fd = manifest_fd
        transferred_runtime_fds = runtime_fds
        root_fd = -1
        manifest_fd = -1
        runtime_fds = []
        return (
            transferred_root_fd,
            transferred_manifest_fd,
            transferred_runtime_fds,
            binding,
            summary,
        )
    finally:
        if source_root_fd >= 0:
            os.close(source_root_fd)
        if manifest_fd >= 0:
            os.close(manifest_fd)
        for descriptor in runtime_fds:
            os.close(descriptor)
        if root_fd >= 0:
            os.close(root_fd)


def verify_runtime_bundle_end(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Replay every runtime memfd, link target, directory, and manifest."""

    if binding.get("protocol") != RUNTIME_BUNDLE_PROTOCOL:
        raise RuntimeError("runtime replay protocol rejected")
    root_fd = binding.get("root_fd")
    manifest_fd = binding.get("manifest_fd")
    if type(root_fd) is not int or type(manifest_fd) is not int:
        raise RuntimeError("runtime replay descriptors rejected")
    root = os.fstat(root_fd)
    root_identity = (
        int(root.st_dev),
        int(root.st_ino),
        stat.S_IMODE(root.st_mode),
        int(root.st_uid),
    )
    if (
        not stat.S_ISDIR(root.st_mode)
        or root_identity[2:] != (0o500, os.getuid())
        or tuple(binding.get("root_identity", ())) != root_identity
    ):
        raise RuntimeError("runtime replay root rejected")
    manifest_raw = _pread_stable(manifest_fd, maximum_bytes=16 << 20)
    manifest_seals = int(fcntl.fcntl(manifest_fd, fcntl.F_GET_SEALS))
    if (
        manifest_seals & ALL_SEALS != ALL_SEALS
        or binding.get("manifest_sha256") != sha256(manifest_raw).hexdigest()
        or binding.get("manifest_size") != len(manifest_raw)
    ):
        raise RuntimeError("runtime replay manifest rejected")
    manifest = json.loads(manifest_raw)
    if (
        manifest.get("schema") != RUNTIME_BUNDLE_PROTOCOL
        or manifest.get("root_fd") != root_fd
        or tuple(manifest.get("root_identity", ())) != root_identity
        or not isinstance(manifest.get("entries"), list)
    ):
        raise RuntimeError("runtime replay manifest contract rejected")
    cache_release = _verify_cache_release_telemetry(
        manifest["entries"],
        manifest.get("source_cache_release_advisories"),
        expected_sha256=manifest.get("source_cache_release_telemetry_sha256"),
    )
    if (
        binding.get("source_cache_release_advisory_count")
        != cache_release["advisory_count"]
        or binding.get("source_cache_release_telemetry_sha256")
        != cache_release["telemetry_sha256"]
    ):
        raise RuntimeError("runtime replay cache-release binding rejected")
    if manifest.get("resource_checkpoint_protocol") != RUNTIME_RESOURCE_PROTOCOL:
        raise RuntimeError("runtime replay resource checkpoint protocol rejected")
    resource_replay = _verify_runtime_resource_telemetry(
        manifest["entries"],
        manifest.get("resource_checkpoints"),
        preexisting_sealed_page_rounded_bytes=manifest.get(
            "preexisting_sealed_page_rounded_bytes"
        ),
        expected_sha256=manifest.get("resource_checkpoint_telemetry_sha256"),
    )
    if (
        binding.get("resource_checkpoint_protocol") != RUNTIME_RESOURCE_PROTOCOL
        or binding.get("resource_checkpoint_telemetry_sha256")
        != resource_replay["telemetry_sha256"]
        or binding.get("preexisting_sealed_page_rounded_bytes")
        != resource_replay["preexisting_sealed_page_rounded_bytes"]
        or binding.get("runtime_file_page_rounded_bytes")
        != resource_replay["runtime_file_page_rounded_bytes"]
        or binding.get("page_size_bytes") != MEMFD_PAGE_SIZE_BYTES
    ):
        raise RuntimeError("runtime replay resource checkpoint binding rejected")
    final_resource = _verify_runtime_final_checkpoint(
        binding.get("resource_final_checkpoint"),
        entry_count=len(manifest["entries"]),
        runtime_logical_bytes=resource_replay["cumulative_logical_bytes"],
        runtime_file_page_rounded_bytes=resource_replay[
            "runtime_file_page_rounded_bytes"
        ],
        manifest_size=len(manifest_raw),
        preexisting_sealed_page_rounded_bytes=resource_replay[
            "preexisting_sealed_page_rounded_bytes"
        ],
        expected_sha256=binding.get("resource_final_checkpoint_sha256"),
    )
    if (
        binding.get("runtime_manifest_page_rounded_bytes")
        != final_resource["manifest_page_rounded_bytes"]
        or binding.get("sealed_page_rounded_bytes")
        != final_resource["sealed_page_rounded_bytes"]
        or binding.get("sealed_page_rounded_kib")
        != final_resource["sealed_page_rounded_kib"]
    ):
        raise RuntimeError("runtime replay final resource binding rejected")
    observed: list[dict[str, Any]] = []
    for row in manifest["entries"]:
        relative = row.get("relative_path")
        descriptor = row.get("fd")
        if not isinstance(relative, str) or type(descriptor) is not int:
            raise RuntimeError("runtime replay entry malformed")
        payload_sha256, payload_size, payload_identity = _pread_digest_stable(
            descriptor,
            maximum_bytes=MAX_RUNTIME_FILE_BYTES,
            expected_size=int(row.get("size", -1)),
        )
        current = os.fstat(descriptor)
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
        if (
            seals & ALL_SEALS != ALL_SEALS
            or payload_sha256 != row.get("sha256")
            or payload_size != row.get("size")
            or payload_identity != _stable_identity(current)
            or tuple(
                row.get(key)
                for key in (
                    "device", "inode", "size", "file_type", "mode", "uid", "nlink"
                )
            )
            != _stable_identity(current)
            or row.get("source_identity_before")
            != row.get("source_identity_after")
            or not isinstance(row.get("source_identity_before"), list)
            or len(row["source_identity_before"]) != 7
            or any(type(value) is not int for value in row["source_identity_before"])
            or os.readlink(relative, dir_fd=root_fd)
            != f"/proc/self/fd/{descriptor}"
        ):
            raise RuntimeError(f"runtime replay entry rejected: {relative}")
        observed.append(
            {
                "relative_path": relative,
                "sha256": row["sha256"],
                "size": row["size"],
            }
        )
    return {
        "manifest_sha256": sha256(manifest_raw).hexdigest(),
        "file_count": len(observed),
        "total_bytes": sum(int(row["size"]) for row in observed),
        "all_memfds_sealed": True,
        "all_link_targets_replayed": True,
        "root_identity": list(root_identity),
        "source_cache_release": cache_release,
        "resource_accounting": {
            **resource_replay,
            **final_resource,
        },
    }




def verify_external_evidence(
    evidence: object,
    expected_sha256: str,
    label: str,
) -> dict[str, object]:
    if not isinstance(evidence, Mapping):
        raise RuntimeError(f"missing external {label} evidence")
    fd = evidence.get("fd")
    if type(fd) is not int:
        raise RuntimeError(f"invalid external {label} descriptor")
    value = read_fd(fd)
    seals = int(fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)))
    actual = digest_bytes(value)
    if actual != expected_sha256 or evidence.get("sha256") != actual or seals & ALL_SEALS != ALL_SEALS:
        raise RuntimeError(f"external {label} captured bytes drift")
    return {"fd": fd, "sha256": actual, "seals": seals, "size_bytes": len(value)}


def load_freeze_manifest(expected_sha256: str, *, external: bool) -> tuple[dict[str, object], bytes]:
    if external:
        evidence = verify_external_evidence(
            SEALED_MANIFEST_EVIDENCE, expected_sha256, "freeze manifest"
        )
        value = read_fd(int(evidence["fd"]))
    else:
        value, _identity = capture_regular(FREEZE_MANIFEST)
        if digest_bytes(value) != expected_sha256:
            raise RuntimeError("freeze manifest hash drift")
    payload = json.loads(value)
    if not isinstance(payload, dict) or payload.get("schema") != "planora.muni-fspsx.frontier-v26.freeze.v1":
        raise RuntimeError("unsupported v26 freeze manifest")
    return payload, value


def validate_manifest_contract(manifest: Mapping[str, object]) -> None:
    constraints = manifest.get("constraints")
    if not isinstance(constraints, Mapping):
        raise RuntimeError("freeze manifest constraints absent")
    expected = {
        "wall_seconds": WALL_SECONDS,
        "runner_seconds": RUNNER_SECONDS,
        "launch_memavailable_floor_kib": LAUNCH_MEMAVAILABLE_FLOOR_KIB,
        "runtime_memavailable_floor_kib": RUNTIME_MEMAVAILABLE_FLOOR_KIB,
        "process_group_memory_cap_kib": PROCESS_GROUP_MEMORY_CAP_KIB,
        "whole_launch_memory_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
        "expected_open_classes": EXPECTED_OPEN_CLASSES,
        "expected_fixed_classes": EXPECTED_FIXED_CLASSES,
        "host_swap_counters_kill_enabled": False,
    }
    if dict(constraints) != expected:
        raise RuntimeError("freeze manifest constraint drift")
    trust = manifest.get("inline_trust_root")
    if (
        not isinstance(trust, Mapping)
        or trust.get("argv_schema_id")
        != "planora.muni-fspsx.frontier-v26.inline-trust-argv.v1"
        or trust.get("argv_schema")
        != [
            "--inline-trust-v1",
            "bootstrap_path",
            "expected_bootstrap_sha256",
            "expected_inline_payload_sha256",
            "downstream_args",
        ]
        or trust.get("first_exec")
        != "/usr/bin/python3.12 -I -S -B -c <exact-inline-payload>"
        or trust.get("interpreter_sha256")
        != "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273"
        or trust.get("pathname_execution_allowed") is not False
    ):
        raise RuntimeError("inline trust-root contract drift")
    stdlib_boundary = manifest.get("stdlib_trust_boundary")
    if (
        not isinstance(stdlib_boundary, Mapping)
        or stdlib_boundary.get("exact_manifest_sha256")
        != EXPECTED_STDLIB_MANIFEST_SHA256
        or stdlib_boundary.get("expected_uid") != 65534
        or stdlib_boundary.get("expected_gid") != 65534
        or stdlib_boundary.get("minimal_tcb_file_count") != 50
        or stdlib_boundary.get("minimal_tcb_manifest_sha256")
        != "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea"
        or stdlib_boundary.get("read_only_root_mount_required") is not True
        or stdlib_boundary.get(
            "world_or_group_writable_file_or_ancestor_allowed"
        )
        is not False
    ):
        raise RuntimeError("stdlib trust-boundary contract drift")
    official = manifest.get("official_instance")
    if not isinstance(official, Mapping) or official.get("path") != str(INSTANCE) or official.get("sha256") != EXPECTED_INSTANCE_SHA256:
        raise RuntimeError("freeze manifest official-instance drift")
    progress = manifest.get("excluded_progress")
    if not isinstance(progress, Mapping) or progress.get("path") != str(PROGRESS) or progress.get("sha256") != EXPECTED_PROGRESS_SHA256:
        raise RuntimeError("freeze manifest excluded-progress drift")
    fairness = manifest.get("fairness_provenance")
    if not isinstance(fairness, Mapping):
        raise RuntimeError("fairness provenance admission absent")
    if fairness.get("progress_sha256") != EXPECTED_PROGRESS_SHA256:
        raise RuntimeError("fairness provenance progress binding drift")
    if (
        fairness.get("status")
        != "V35_AND_COMPONENT_CHECKPOINT_NO_GO_UNPROVEN"
        or fairness.get("solver_input_mode") != "OFFICIAL_INPUT_ONLY_FRESH"
        or fairness.get("progress_runtime_access_allowed") is not False
        or fairness.get("component_checkpoint_sha256")
        != "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80"
    ):
        raise RuntimeError("official-input-only fairness mode rejected")
    certificate_path = fairness.get("derivation_audit_path")
    certificate_sha256 = fairness.get("derivation_audit_sha256")
    if (
        not isinstance(certificate_path, str)
        or not certificate_path.startswith("/tmp/")
        or not isinstance(certificate_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", certificate_sha256) is None
    ):
        raise RuntimeError("fairness provenance certificate pin rejected")
    rows = manifest_files(manifest)
    certificate_row = rows.get("fairness_certificate")
    if (
        certificate_row is None
        or certificate_row.get("path") != certificate_path
        or certificate_row.get("sha256") != certificate_sha256
    ):
        raise RuntimeError("fairness certificate file row drift")
    certificate_bytes, _certificate_identity = capture_regular(
        Path(certificate_path)
    )
    if digest_bytes(certificate_bytes) != certificate_sha256:
        raise RuntimeError("fairness certificate hash drift")
    certificate = json.loads(certificate_bytes)
    if (
        not isinstance(certificate, dict)
        or certificate.get("verdict") != "NO_GO_UNPROVEN"
        or not isinstance(certificate.get("target"), dict)
        or certificate["target"].get("progress_sha256")
        != EXPECTED_PROGRESS_SHA256
        or not isinstance(certificate.get("component_checkpoint"), dict)
        or certificate["component_checkpoint"].get("checkpoint_sha256")
        != fairness.get("component_checkpoint_sha256")
        or certificate["component_checkpoint"].get(
            "transitive_imports_bound_by_producer_report"
        )
        is not False
        or certificate["component_checkpoint"].get(
            "safe_restart_without_fresh_sealed_replay"
        )
        is not False
        or not isinstance(certificate.get("fairness"), dict)
        or certificate["fairness"].get("derivation_admissible") is not False
        or certificate["fairness"].get(
            "competitor_or_external_schedule_absence_fully_proven_for_recursive_lineage"
        )
        is not False
    ):
        raise RuntimeError("fairness certificate verdict contract rejected")
    dependency_trees = manifest.get("dependency_trees")
    if not isinstance(dependency_trees, dict) or set(dependency_trees) != {
        "ortools", "protobuf", "numpy", "pandas", "absl-py", "immutabledict",
        "python-dateutil", "six", "typing-extensions",
    }:
        raise RuntimeError("freeze manifest dependency-tree contract drift")


def dependency_tree_digest(name: str) -> dict[str, object]:
    """Hash every installed non-pyc file recorded by one distribution."""

    normalized = re.sub(r"[-_.]+", "-", name).lower()
    candidates = [
        row
        for row in distributions(path=[str(SITE_PACKAGES)])
        if re.sub(r"[-_.]+", "-", str(row.metadata.get("Name", ""))).lower()
        == normalized
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"dependency metadata admission failed: {name}")
    installed = candidates[0]
    aggregate = sha256()
    count = 0
    for relative in sorted(
        str(value)
        for value in (installed.files or ())
        if not str(value).endswith(".pyc")
    ):
        path = Path(installed.locate_file(relative))
        if not path.is_file():
            continue
        file_hash = sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(block)
        aggregate.update(relative.encode())
        aggregate.update(b"\0")
        aggregate.update(file_hash.hexdigest().encode())
        aggregate.update(b"\0")
        aggregate.update(str(path.stat().st_size).encode())
        aggregate.update(b"\n")
        count += 1
    return {
        "version": installed.version,
        "file_count": count,
        "sha256": aggregate.hexdigest(),
    }


def verify_dependency_trees(
    manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    expected = manifest["dependency_trees"]
    assert isinstance(expected, dict)
    names = tuple(sorted(expected))
    with ThreadPoolExecutor(max_workers=len(names)) as executor:
        observed_values = tuple(executor.map(dependency_tree_digest, names))
    observed = dict(zip(names, observed_values, strict=True))
    if observed != expected:
        raise RuntimeError("installed dependency tree drift")
    return observed


def manifest_files(manifest: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw = manifest.get("files")
    if not isinstance(raw, list):
        raise RuntimeError("freeze manifest files must be a list")
    rows: dict[str, dict[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict) or set(row) != {"label", "path", "sha256"}:
            raise RuntimeError("malformed freeze manifest file row")
        label = row["label"]
        path = row["path"]
        expected = row["sha256"]
        if not isinstance(label, str) or not isinstance(path, str) or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise RuntimeError("invalid freeze manifest file values")
        if label in rows:
            raise RuntimeError("duplicate freeze manifest file label")
        rows[label] = row
    required = {
        "bootstrap", "inline_trust_payload", "fairness_certificate",
        "runner", "generic_validator", "stdlib_manifest",
        "minimal_tcb_manifest",
        "python_binary", "benchmarks",
        "semantic", "preprocessing", "frontier", "room_oracle",
        "test_preprocessing", "test_frontier", "test_room_oracle",
        "test_violation_lns",
        "v26_adversarial_tests",
        "ortools_init", "ortools_cp_model", "ortools_cp_model_helper",
        "protobuf_init", "numpy_init", "pandas_init", "absl_init",
        "immutabledict_init", "python_venv_config",
        *RUNTIME_RECORDS, *PLANORA_FRESH_MODULES,
    }
    missing = sorted(required - set(rows))
    if missing:
        raise RuntimeError("freeze manifest missing files: " + ", ".join(missing))
    if Path(str(rows["runner"]["path"])) != RUNNER:
        raise RuntimeError("freeze manifest runner path drift")
    if Path(str(rows["bootstrap"]["path"])) != Path(
        str(CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-bootstrap.py")
    ):
        raise RuntimeError("freeze manifest bootstrap path drift")
    trust = manifest.get("inline_trust_root")
    if not isinstance(trust, Mapping):
        raise RuntimeError("inline trust-root manifest absent")
    if (
        rows["bootstrap"].get("sha256") != trust.get("bootstrap_sha256")
        or rows["inline_trust_payload"].get("path")
        != trust.get("inline_payload_path_for_review_only")
        or rows["inline_trust_payload"].get("sha256")
        != trust.get("inline_payload_sha256")
    ):
        raise RuntimeError("inline trust-root file pins drift")
    if Path(str(rows["python_binary"]["path"])).resolve() != PYTHON.resolve():
        raise RuntimeError("freeze manifest python path drift")
    if (
        Path(str(rows["stdlib_manifest"]["path"])) != STDLIB_MANIFEST
        or rows["stdlib_manifest"]["sha256"]
        != EXPECTED_STDLIB_MANIFEST_SHA256
    ):
        raise RuntimeError("freeze manifest stdlib closure drift")
    if (
        Path(str(rows["minimal_tcb_manifest"]["path"]))
        != CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-minimal-tcb.sha256"
        or rows["minimal_tcb_manifest"]["sha256"]
        != "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea"
    ):
        raise RuntimeError("freeze manifest minimal TCB drift")
    if rows["frontier"]["sha256"] != EXPECTED_FRONTIER_SHA256:
        raise RuntimeError("freeze manifest frontier hash drift")
    if rows["test_frontier"]["sha256"] != EXPECTED_FRONTIER_TEST_SHA256:
        raise RuntimeError("freeze manifest frontier-test hash drift")
    return rows


def verify_manifest_files(
    manifest: Mapping[str, object],
    *,
    dry: bool,
) -> dict[str, dict[str, object]]:
    rows = manifest_files(manifest)
    observed: dict[str, dict[str, object]] = {}
    for label, row in rows.items():
        path = Path(str(row["path"]))
        value, identity = capture_regular(path)
        actual = digest_bytes(value)
        if actual != row["sha256"]:
            raise RuntimeError(f"frozen file drift: {label}")
        observed[label] = {"sha256": actual, "identity": identity}
    official = manifest["official_instance"]
    instance_stat = INSTANCE.lstat()
    if not stat.S_ISREG(instance_stat.st_mode) or INSTANCE.is_symlink():
        raise RuntimeError("official instance is not a regular file")
    if int(official["size_bytes"]) != int(instance_stat.st_size):
        raise RuntimeError("official instance size drift")
    if not dry:
        value, identity = capture_regular(INSTANCE)
        if digest_bytes(value) != EXPECTED_INSTANCE_SHA256:
            raise RuntimeError("official instance hash drift")
        observed["instance"] = {
            "sha256": EXPECTED_INSTANCE_SHA256,
            "identity": identity,
        }
        observed["excluded_progress"] = {
            "opened": False,
            "checked": False,
            "reason": "fairness_certificate_NO_GO_official_input_only_mode",
        }
    else:
        observed["excluded_progress"] = {
            "opened": False,
            "checked": False,
            "reason": "fairness_certificate_NO_GO_official_input_only_mode",
        }
    observed["dependency_trees"] = verify_dependency_trees(manifest)
    return observed


def verify_probe_manifest_files(
    manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Replay frozen code/runtime pins without touching any problem input."""

    rows = manifest_files(manifest)
    observed: dict[str, dict[str, object]] = {}
    for label, row in rows.items():
        path = Path(str(row["path"]))
        value, identity = capture_regular(path)
        actual = digest_bytes(value)
        if actual != row["sha256"]:
            raise RuntimeError(f"frozen file drift: {label}")
        observed[label] = {"sha256": actual, "identity": identity}
    observed["excluded_inputs"] = {
        "official": {"opened": False, "statted": False},
        "progress": {"opened": False, "statted": False},
        "checkpoint": {"opened": False, "statted": False},
    }
    observed["dependency_trees"] = verify_dependency_trees(manifest)
    return observed


def read_key_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) >= 2 and fields[0].endswith(":"):
                    try:
                        values[fields[0][:-1]] = int(fields[1])
                    except ValueError:
                        continue
                elif len(fields) == 2:
                    try:
                        values[fields[0]] = int(fields[1])
                    except ValueError:
                        continue
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return {}
    return values


def host_sample() -> dict[str, int]:
    memory = read_key_values(Path("/proc/meminfo"))
    virtual = read_key_values(Path("/proc/vmstat"))
    return {
        "mem_available_kib": memory.get("MemAvailable", 0),
        "shmem_kib": memory.get("Shmem", 0),
        "swap_free_kib": memory.get("SwapFree", 0),
        "pswpin_pages": virtual.get("pswpin", 0),
        "pswpout_pages": virtual.get("pswpout", 0),
    }


def resource_decision(
    *,
    elapsed_seconds: float,
    group_memory_kib: int,
    supervisor_memory_kib: int,
    sealed_storage_kib: int = 0,
    sample: Mapping[str, int],
) -> str | None:
    """Return an attributable stop reason; host swap counters are telemetry only."""

    if elapsed_seconds >= WALL_SECONDS:
        return "wall_deadline"
    if group_memory_kib > PROCESS_GROUP_MEMORY_CAP_KIB:
        return "process_group_memory_cap"
    if (
        supervisor_memory_kib + group_memory_kib + sealed_storage_kib
        > WHOLE_LAUNCH_MEMORY_CAP_KIB
    ):
        return "whole_launch_memory_cap"
    if int(sample.get("mem_available_kib", 0)) < RUNTIME_MEMAVAILABLE_FLOOR_KIB:
        return "host_pressure:memavailable_floor"
    return None


def set_union_memory_kib(
    supervisor_memory: int,
    group_memory: int,
    group_members: Sequence[int],
    *,
    supervisor_pid: int | None = None,
) -> int:
    """Account each PID once if a supervisor is ever in the admitted group."""

    owner = os.getpid() if supervisor_pid is None else supervisor_pid
    return group_memory if owner in group_members else supervisor_memory + group_memory


def sealed_import_probe_stop_reason(
    *,
    elapsed_seconds: float,
    group_memory_kib: int,
    whole_memory_kib: int,
    mem_available_kib: int,
) -> str | None:
    if elapsed_seconds >= SEALED_IMPORT_PROBE_WALL_SECONDS:
        return "probe_wall_deadline"
    if group_memory_kib > PROCESS_GROUP_MEMORY_CAP_KIB:
        return "process_group_memory_cap"
    if whole_memory_kib > WHOLE_LAUNCH_MEMORY_CAP_KIB:
        return "whole_launch_memory_cap"
    if mem_available_kib < RUNTIME_MEMAVAILABLE_FLOOR_KIB:
        return "host_pressure:memavailable_floor"
    return None


def sealed_import_probe_iteration_decision(
    *,
    elapsed_seconds: float,
    group_memory_kib: int,
    whole_memory_kib: int,
    mem_available_kib: int,
    received_signal: int | None,
    process_exited: bool,
) -> str | None:
    """Evaluate every attributable breach before honoring a child exit."""

    if received_signal is not None:
        return f"signal:{received_signal}"
    breach = sealed_import_probe_stop_reason(
        elapsed_seconds=elapsed_seconds,
        group_memory_kib=group_memory_kib,
        whole_memory_kib=whole_memory_kib,
        mem_available_kib=mem_available_kib,
    )
    if breach is not None:
        return breach
    return "child_exit" if process_exited else None


def sealed_import_probe_accepted(
    *,
    errors: Sequence[str],
    stop_reason: str,
    child_exit: int | None,
    cleanup: Mapping[str, object] | None,
    child_report: Mapping[str, object] | None,
    final_elapsed_seconds: float,
    peak_whole_memory_kib: int,
) -> bool:
    return bool(
        not errors
        and stop_reason == "normal_exit"
        and child_exit == 0
        and cleanup is not None
        and not cleanup.get("errors")
        and not cleanup.get("observation_errors")
        and cleanup.get("original_pgid_asserted_empty") is True
        and child_report is not None
        and final_elapsed_seconds <= SEALED_IMPORT_PROBE_WALL_SECONDS
        and peak_whole_memory_kib <= WHOLE_LAUNCH_MEMORY_CAP_KIB
    )


def supervisor_memory_kib() -> int:
    values = read_key_values(Path("/proc/self/status"))
    return values.get("VmRSS", 0) + values.get("VmSwap", 0)


class ProcessStatusMemoryUnavailable(RuntimeError):
    """The pinned process status cannot provide a complete memory sample."""


def read_process_memory_status_once(pid: int) -> dict[str, int]:
    """Read one process status file exactly once and require both memory fields."""

    path = Path("/proc") / str(pid) / "status"
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = tuple(handle)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError) as exc:
        raise ProcessStatusMemoryUnavailable(
            f"process status missing for identity-pinned PID {pid}"
        ) from exc
    values: dict[str, int] = {}
    state: str | None = None
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "State:":
            state = fields[1]
        if len(fields) >= 2 and fields[0] in {"VmRSS:", "VmSwap:"}:
            try:
                values[fields[0][:-1]] = int(fields[1])
            except ValueError as exc:
                raise ProcessStatusMemoryUnavailable(
                    f"process status memory value rejected for PID {pid}"
                ) from exc
    if state == "Z" and not values:
        return {"VmRSS": 0, "VmSwap": 0}
    if state is None or set(values) != {"VmRSS", "VmSwap"}:
        raise ProcessStatusMemoryUnavailable(
            f"process status memory fields missing for PID {pid}"
        )
    return values


def identity_pinned_process_memory(
    pid: int, pinned: tuple[int, int, int]
) -> dict[str, int]:
    before = proc_stat_identity(pid)
    if before != pinned:
        raise RuntimeError(f"process identity missing or drifted before status read: {pid}")
    values = read_process_memory_status_once(pid)
    after = proc_stat_identity(pid)
    if after is None:
        raise RuntimeError(f"identity-pinned PID disappeared during status read: {pid}")
    if after != pinned:
        raise RuntimeError(f"identity-pinned PID drifted during status read: {pid}")
    return values


class ProcObservationError(RuntimeError):
    """A /proc observation failed without proving process disappearance."""


def _confirmed_proc_disappearance(exc: OSError) -> bool:
    return exc.errno in {errno.ENOENT, errno.ESRCH}


def proc_stat_identity(pid: int) -> tuple[int, int, int] | None:
    """Return None only when /proc confirms ENOENT/ESRCH disappearance."""

    path = Path("/proc") / str(pid) / "stat"
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        if _confirmed_proc_disappearance(exc):
            return None
        raise ProcObservationError(
            f"proc stat observation failed for PID {pid}: "
            f"{type(exc).__name__}:errno={exc.errno}"
        ) from exc
    closing = value.rfind(")")
    if closing < 0:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: missing command terminator"
        )
    fields = value[closing + 2 :].split()
    if len(fields) < 20:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: expected at least 20 tail fields"
        )
    try:
        return int(fields[2]), int(fields[3]), int(fields[19])
    except ValueError as exc:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: non-integer identity field"
        ) from exc


def process_group_snapshot(
    pgid: int,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Capture identities; observation failure is never an empty-group proof."""

    result: list[tuple[int, tuple[int, int, int]]] = []
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError as exc:
        raise ProcObservationError(
            f"proc enumeration failed for PGID {pgid}: "
            f"{type(exc).__name__}:errno={exc.errno}"
        ) from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            identity = proc_stat_identity(pid)
        except ProcObservationError as exc:
            raise ProcObservationError(
                f"proc identity scan failed for PID {pid} in PGID {pgid}"
            ) from exc
        if identity is not None and identity[0] == pgid:
            result.append((pid, identity))
    return tuple(sorted(result))


def process_group_pids(pgid: int) -> tuple[int, ...]:
    return tuple(pid for pid, _identity in process_group_snapshot(pgid))


class ProcessGroupGeneration:
    """Members observed while the original session leader generation is live.

    A numeric PGID is reusable.  This registry is therefore append-only only
    while the original leader PID/starttime identity can be replayed both
    before and after a /proc scan.  Once that anchor disappears or changes,
    the registry is sealed permanently and later occupants are never admitted.
    """

    __slots__ = (
        "pgid", "leader_pid", "leader_identity", "members", "sealed",
        "seal_reason", "refresh_count", "sampled_members",
    )

    def __init__(
        self,
        pgid: int,
        leader_pid: int,
        leader_identity: tuple[int, int, int],
    ) -> None:
        if (
            leader_pid != pgid
            or leader_identity[0] != pgid
            or leader_identity[1] != pgid
        ):
            raise RuntimeError("process-group generation leader binding rejected")
        self.pgid = pgid
        self.leader_pid = leader_pid
        self.leader_identity = leader_identity
        self.members: dict[int, tuple[int, int, int]] = {
            leader_pid: leader_identity
        }
        self.sealed = False
        self.seal_reason: str | None = None
        self.refresh_count = 0
        self.sampled_members: set[tuple[int, tuple[int, int, int]]] = set()

    def seal(self, reason: str) -> None:
        self.sealed = True
        if self.seal_reason is None:
            self.seal_reason = reason


def refresh_process_group_generation(
    generation: ProcessGroupGeneration,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Admit a snapshot only under a before-and-after leader-generation replay."""

    if generation.sealed:
        return ()
    try:
        before = proc_stat_identity(generation.leader_pid)
    except ProcObservationError:
        generation.seal("leader_generation_observation_failed_before_snapshot")
        raise
    if before != generation.leader_identity:
        generation.seal("leader_generation_absent_before_snapshot")
        return ()
    try:
        candidate = process_group_snapshot(generation.pgid)
    except ProcObservationError:
        generation.seal("process_group_observation_failed_during_snapshot")
        raise
    try:
        after = proc_stat_identity(generation.leader_pid)
    except ProcObservationError:
        generation.seal("leader_generation_observation_failed_after_snapshot")
        raise
    if after != generation.leader_identity:
        generation.seal("leader_generation_absent_after_snapshot")
        return ()
    admitted: list[tuple[int, tuple[int, int, int]]] = []
    for pid, identity in candidate:
        if identity[0] != generation.pgid or identity[1] != generation.pgid:
            continue
        previous = generation.members.get(pid)
        if previous is not None and previous != identity:
            generation.seal("admitted_member_pid_identity_changed")
            return ()
        generation.members[pid] = identity
        admitted.append((pid, identity))
    generation.refresh_count += 1
    return tuple(admitted)


def admitted_generation_snapshot(
    generation: ProcessGroupGeneration,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Return still-live members from the immutable admitted identity set."""

    return tuple(
        (pid, identity)
        for pid, identity in sorted(generation.members.items())
        if proc_stat_identity(pid) == identity
    )


def identity_pinned_process_memory_snapshot(
    generation: ProcessGroupGeneration,
    *,
    supervisor_pid: int,
    supervisor_identity: tuple[int, int, int],
    reaped_zero_proof: tuple[int, tuple[int, int, int], int] | None = None,
) -> dict[str, object]:
    """Measure one unique admitted set without rescanning a numeric PGID.

    Members absent before snapshot derivation are recorded as already gone.
    Every selected member and the supervisor must retain its pinned identity
    across its single status read; replacements, missing status, and drift are
    fatal rather than attributable to the original launch.
    """

    if reaped_zero_proof is not None:
        proof_pid, proof_identity, proof_exit = reaped_zero_proof
        if (
            type(proof_pid) is not int
            or proof_pid != generation.leader_pid
            or proof_identity != generation.leader_identity
            or type(proof_exit) is not int
            or proof_exit != 0
        ):
            raise RuntimeError("reaped-zero proof is not the admitted zero-exit leader")

    selected: dict[int, tuple[tuple[int, int, int], bool]] = {}
    reaped_zero: dict[int, tuple[int, int, int]] = {}
    vanished_before: list[int] = []
    for pid, pinned in sorted(generation.members.items()):
        observed = proc_stat_identity(pid)
        if observed is None:
            if reaped_zero_proof is not None and pid == reaped_zero_proof[0]:
                if (pid, pinned) not in generation.sampled_members:
                    raise RuntimeError(
                        "reaped-zero leader was never identity-bound sampled"
                    )
                reaped_zero[pid] = pinned
            vanished_before.append(pid)
            continue
        if observed != pinned:
            raise RuntimeError(f"admitted PID identity replaced before memory snapshot: {pid}")
        selected[pid] = (pinned, True)
    observed_supervisor = proc_stat_identity(supervisor_pid)
    if observed_supervisor != supervisor_identity:
        raise RuntimeError("supervisor identity missing or drifted before memory snapshot")
    previous = selected.get(supervisor_pid)
    if previous is not None and previous[0] != supervisor_identity:
        raise RuntimeError("supervisor PID collides with a different admitted identity")
    selected[supervisor_pid] = (
        supervisor_identity,
        bool(previous is not None and previous[1]),
    )

    rows: list[dict[str, object]] = []
    group_memory = 0
    supervisor_memory = 0
    whole_memory = 0
    for pid, (pinned, admitted_group_member) in sorted(selected.items()):
        try:
            values = identity_pinned_process_memory(pid, pinned)
        except ProcessStatusMemoryUnavailable:
            after_failure = proc_stat_identity(pid)
            if after_failure is not None and after_failure != pinned:
                raise RuntimeError(
                    f"identity-pinned PID drifted during failed status read: {pid}"
                )
            if (
                reaped_zero_proof is None
                or pid != reaped_zero_proof[0]
                or pinned != reaped_zero_proof[1]
                or after_failure is not None
            ):
                raise
            if (pid, pinned) not in generation.sampled_members:
                raise RuntimeError(
                    "reaped-zero leader was never identity-bound sampled"
                )
            values = {"VmRSS": 0, "VmSwap": 0}
            reaped_zero[pid] = pinned
        else:
            generation.sampled_members.add((pid, pinned))
        memory = int(values["VmRSS"]) + int(values["VmSwap"])
        row = {
            "pid": pid,
            "identity": pinned,
            "vm_rss_kib": int(values["VmRSS"]),
            "vm_swap_kib": int(values["VmSwap"]),
            "memory_kib": memory,
            "admitted_group_member": admitted_group_member,
            "supervisor": pid == supervisor_pid,
            "reaped_gone_zero_memory": pid in reaped_zero,
        }
        rows.append(row)
        whole_memory += memory
        if admitted_group_member:
            group_memory += memory
        if pid == supervisor_pid:
            supervisor_memory = memory
    represented = {int(row["pid"]) for row in rows}
    for pid, pinned in sorted(reaped_zero.items()):
        if pid in represented:
            continue
        rows.append({
            "pid": pid,
            "identity": pinned,
            "vm_rss_kib": 0,
            "vm_swap_kib": 0,
            "memory_kib": 0,
            "admitted_group_member": True,
            "supervisor": False,
            "reaped_gone_zero_memory": True,
        })
    rows.sort(key=lambda row: int(row["pid"]))
    return {
        "rows": tuple(rows),
        "pids": tuple(int(row["pid"]) for row in rows),
        "vanished_before_snapshot_pids": tuple(vanished_before),
        "group_memory_kib": group_memory,
        "supervisor_memory_kib": supervisor_memory,
        "whole_launch_set_union_memory_kib": whole_memory,
        "numeric_pgid_rescan_used": False,
        "status_reads_per_selected_pid": 1,
        "identity_replayed_after_each_status_read": True,
        "reaped_gone_zero_memory_pids": tuple(sorted(reaped_zero)),
    }


def identity_pinned_probe_telemetry_sample(
    generation: ProcessGroupGeneration,
    *,
    supervisor_pid: int,
    supervisor_identity: tuple[int, int, int],
    started: float,
    stage: str,
    received_signal: int | None,
    sealed_storage_kib: int = 0,
    reaped_zero_proof: tuple[int, tuple[int, int, int], int] | None = None,
) -> tuple[dict[str, object], str | None]:
    host = host_sample()
    memory = identity_pinned_process_memory_snapshot(
        generation,
        supervisor_pid=supervisor_pid,
        supervisor_identity=supervisor_identity,
        reaped_zero_proof=reaped_zero_proof,
    )
    elapsed = time.monotonic() - started
    process_whole_memory = int(memory["whole_launch_set_union_memory_kib"])
    whole_memory = process_whole_memory + sealed_storage_kib
    decision = sealed_import_probe_iteration_decision(
        elapsed_seconds=elapsed,
        group_memory_kib=int(memory["group_memory_kib"]),
        whole_memory_kib=whole_memory,
        mem_available_kib=host["mem_available_kib"],
        received_signal=received_signal,
        process_exited=False,
    )
    return {
        "stage": stage,
        "elapsed_seconds": elapsed,
        "group_memory_kib": int(memory["group_memory_kib"]),
        "supervisor_memory_kib": int(memory["supervisor_memory_kib"]),
        "process_set_union_memory_kib": process_whole_memory,
        "sealed_storage_kib": sealed_storage_kib,
        "whole_launch_set_union_memory_kib": whole_memory,
        "identity_pinned_pids": memory["pids"],
        "memory_snapshot": memory,
        **host,
    }, decision


def successful_reaped_leader_zero_memory_proof(
    process: subprocess.Popen[bytes],
    generation: ProcessGroupGeneration,
) -> tuple[int, tuple[int, int, int], int] | None:
    """Bind zero memory to one successfully reaped, previously sampled leader."""

    if process.pid != generation.leader_pid:
        raise RuntimeError("reaped-zero Popen leader binding rejected")
    returncode = process.poll()
    if returncode is None or returncode != 0:
        return None
    pinned = generation.leader_identity
    if (process.pid, pinned) not in generation.sampled_members:
        raise RuntimeError("reaped-zero leader was never identity-bound sampled")
    observed = proc_stat_identity(process.pid)
    if observed is not None:
        raise RuntimeError("reaped-zero leader PID is still live or was reused")
    return process.pid, pinned, returncode


def signal_process_group_snapshot(
    pgid: int,
    snapshot: tuple[tuple[int, tuple[int, int, int]], ...],
    signum: int,
) -> dict[str, object]:
    """Signal only identity-pinned members; never signal a numeric PGID."""
    if not snapshot:
        return {
            "signal": int(signum),
            "snapshot_pids": (),
            "signaled_pids": (),
            "vanished_pids": (),
            "identity_mismatch_pids": (),
            "identity_observation_failures": (),
            "pidfd_open_failures": (),
            "pidfd_send_failures": (),
            "pidfd_close_failures": (),
            "numeric_pgid_signal_sent": False,
        }
    signaled: list[int] = []
    vanished: list[int] = []
    identity_mismatches: list[int] = []
    identity_observation_failures: list[dict[str, object]] = []
    pidfd_open_failures: list[dict[str, int]] = []
    pidfd_send_failures: list[dict[str, int]] = []
    pidfd_close_failures: list[dict[str, int]] = []
    for pid, admitted_identity in snapshot:
        if admitted_identity[0] != pgid:
            raise RuntimeError("process-group snapshot PGID binding rejected")
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            pidfd_open_failures.append({"pid": pid, "errno": errno.ENOSYS})
            continue
        try:
            descriptor = os.pidfd_open(pid, 0)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                vanished.append(pid)
            else:
                pidfd_open_failures.append(
                    {"pid": pid, "errno": int(exc.errno or errno.EIO)}
                )
            continue
        try:
            try:
                replayed_identity = proc_stat_identity(pid)
            except ProcObservationError as exc:
                identity_observation_failures.append({
                    "pid": pid,
                    "error": f"{type(exc).__name__}:{exc}",
                })
                continue
            if replayed_identity is None:
                vanished.append(pid)
                continue
            if replayed_identity != admitted_identity:
                identity_mismatches.append(pid)
                continue
            try:
                signal.pidfd_send_signal(descriptor, signum, None, 0)
            except OSError as exc:
                if exc.errno == errno.ESRCH:
                    vanished.append(pid)
                else:
                    pidfd_send_failures.append(
                        {"pid": pid, "errno": int(exc.errno or errno.EIO)}
                    )
                continue
            signaled.append(pid)
        finally:
            try:
                os.close(descriptor)
            except OSError as exc:
                pidfd_close_failures.append(
                    {"pid": pid, "errno": int(exc.errno or errno.EIO)}
                )
    return {
        "signal": int(signum),
        "snapshot_pids": tuple(pid for pid, _identity in snapshot),
        "signaled_pids": tuple(signaled),
        "vanished_pids": tuple(vanished),
        "identity_mismatch_pids": tuple(identity_mismatches),
        "identity_observation_failures": tuple(identity_observation_failures),
        "pidfd_open_failures": tuple(pidfd_open_failures),
        "pidfd_send_failures": tuple(pidfd_send_failures),
        "pidfd_close_failures": tuple(pidfd_close_failures),
        "numeric_pgid_signal_sent": False,
    }


def process_group_memory_kib(pgid: int) -> tuple[int, tuple[int, ...]]:
    pids = process_group_pids(pgid)
    total = 0
    for pid in pids:
        values = read_key_values(Path("/proc") / str(pid) / "status")
        total += values.get("VmRSS", 0) + values.get("VmSwap", 0)
    return total, pids


def arm_parent_death_signal(expected_parent: int) -> None:
    if _PRCTL(PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)
    # The supervisor blocks stop signals while it linearizes launch and
    # publication.  preexec inherits that mask, so explicitly restore delivery
    # after PDEATHSIG is armed and before the runner image executes.
    signal.pthread_sigmask(signal.SIG_UNBLOCK, STOP_SIGNALS)


def stop_process_group(
    process: subprocess.Popen[bytes],
    generation: ProcessGroupGeneration,
    pidfd: int | None,
) -> dict[str, object]:
    """Drain admitted identities while never converting uncertainty to absence."""

    pgid = generation.pgid
    if process.pid != generation.leader_pid:
        raise RuntimeError("Popen leader does not match admitted generation")
    observation_errors: list[str] = []

    def record_observation(stage: str, exc: BaseException) -> None:
        value = f"{stage}:{type(exc).__name__}:{exc}"
        if value not in observation_errors:
            observation_errors.append(value)

    try:
        observed = proc_stat_identity(process.pid)
    except ProcObservationError as exc:
        record_observation("leader_before_stop", exc)
        observed = None
        identity_changed = False
        generation.seal("leader_generation_observation_failed_before_stop")
    else:
        identity_changed = observed not in (None, generation.leader_identity)
        if identity_changed:
            generation.seal("leader_generation_identity_changed_before_stop")

    def observe_wait(timeout: float, stage: str) -> tuple[int | None, bool]:
        try:
            return process.wait(timeout=timeout), True
        except subprocess.TimeoutExpired:
            return None, False
        except (OSError, ValueError) as exc:
            record_observation(stage, exc)
            return None, False

    def safe_refresh(stage: str) -> None:
        try:
            refresh_process_group_generation(generation)
        except ProcObservationError as exc:
            record_observation(stage, exc)
            generation.seal(f"{stage}_observation_failed")

    def cleanup_snapshot(stage: str) -> tuple[tuple[int, tuple[int, int, int]], ...]:
        snapshot: list[tuple[int, tuple[int, int, int]]] = []
        for admitted_pid, admitted_identity in sorted(generation.members.items()):
            try:
                current = proc_stat_identity(admitted_pid)
            except ProcObservationError as exc:
                record_observation(f"{stage}:pid={admitted_pid}", exc)
                snapshot.append((admitted_pid, admitted_identity))
                continue
            if current is None:
                continue
            if current != admitted_identity:
                generation.seal("admitted_member_identity_changed_during_cleanup")
                continue
            snapshot.append((admitted_pid, admitted_identity))
        return tuple(snapshot)

    def record_signal_observation(stage: str, result: Mapping[str, object]) -> None:
        for row in result.get("identity_observation_failures", ()):
            record_observation(
                f"{stage}:pid={row.get('pid')}",
                RuntimeError(str(row.get("error"))),
            )

    safe_refresh("final_admission_refresh")
    _initial_returncode, known_leader_reaped = observe_wait(0, "initial_wait")
    snapshot_before = cleanup_snapshot("before_term_snapshot")
    members_before = tuple(pid for pid, _identity in snapshot_before)
    leader_exited_before_cleanup = process.returncode is not None
    if known_leader_reaped and process.pid in members_before:
        raise RuntimeError("reaped process-group leader PID was reused")
    term_signal = signal_process_group_snapshot(pgid, snapshot_before, signal.SIGTERM)
    record_signal_observation("term_signal", term_signal)
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    group_observed_empty = False
    while time.monotonic() < deadline:
        safe_refresh("grace_refresh")
        if process.returncode is None:
            observe_wait(0, "grace_wait")
        current_snapshot = cleanup_snapshot("grace_snapshot")
        if not current_snapshot and not observation_errors:
            group_observed_empty = True
            break
        time.sleep(0.05)
    survivor_snapshot = () if group_observed_empty else cleanup_snapshot("pre_kill_snapshot")
    survivors = tuple(pid for pid, _identity in survivor_snapshot)
    kill_signal = signal_process_group_snapshot(pgid, survivor_snapshot, signal.SIGKILL)
    record_signal_observation("kill_signal", kill_signal)
    observed_returncode, _final_wait_completed = observe_wait(
        TERMINATION_GRACE_SECONDS, "final_wait"
    )
    returncode = observed_returncode if observed_returncode is not None else process.returncode
    final_snapshot = cleanup_snapshot("final_admitted_snapshot")
    final_admitted_survivors = tuple(pid for pid, _identity in final_snapshot)
    try:
        current_group = process_group_snapshot(pgid)
    except ProcObservationError as exc:
        record_observation("final_process_group_snapshot", exc)
        current_group = None
        unregistered_current_members: tuple[int, ...] = ()
    else:
        unregistered_current_members = tuple(
            current_pid
            for current_pid, identity in current_group
            if generation.members.get(current_pid) != identity
        )
    original_pgid_asserted_empty = bool(
        current_group is not None
        and not observation_errors
        and not final_admitted_survivors
        and not unregistered_current_members
    )
    cleanup_errors = list(observation_errors)
    if final_admitted_survivors or unregistered_current_members:
        cleanup_errors.append(
            "process-group cleanup left admitted or unregistered survivors: "
            + ",".join(
                str(item)
                for item in (*final_admitted_survivors, *unregistered_current_members)
            )
        )
    if not original_pgid_asserted_empty:
        cleanup_errors.append(
            "process-group empty assertion rejected due to survivors or observation uncertainty"
        )
    return {
        "returncode": returncode,
        "members_before": members_before,
        "term_survivors": survivors,
        "final_survivors": final_admitted_survivors,
        "unregistered_current_members": unregistered_current_members,
        "leader_identity_changed": identity_changed,
        "leader_identity_available": observed is not None,
        "pidfd_evidence_available": pidfd is not None,
        "known_leader_reaped_before_group_interpretation": known_leader_reaped,
        "pid_reuse_guard_passed": bool(
            current_group is not None
            and not observation_errors
            and not unregistered_current_members
        ),
        "leader_exited_before_cleanup": leader_exited_before_cleanup,
        "original_pgid_asserted_empty": original_pgid_asserted_empty,
        "group_observed_empty_before_any_later_signal": bool(
            group_observed_empty and not observation_errors
        ),
        "term_signal": term_signal,
        "kill_signal": kill_signal,
        "numeric_pgid_signal_sent": False,
        "generation_registry_size": len(generation.members),
        "generation_registry_sealed": generation.sealed,
        "generation_registry_seal_reason": generation.seal_reason,
        "generation_refresh_count": generation.refresh_count,
        "observation_errors": tuple(observation_errors),
        "errors": tuple(cleanup_errors),
    }

def admit_spawned_process_group(
    process: subprocess.Popen[bytes], provisional_pgid: int, admitted_pidfd: int | None
) -> tuple[int, tuple[int, int, int], int | None, ProcessGroupGeneration]:
    """Admit a new session after its provisional PGID is already recorded."""

    observed_pgid = os.getpgid(process.pid)
    sid = os.getsid(process.pid)
    leader_identity = proc_stat_identity(process.pid)
    if (
        observed_pgid != provisional_pgid
        or sid != provisional_pgid
        or leader_identity is None
    ):
        raise RuntimeError("child PGID/session/identity admission failed")
    generation = ProcessGroupGeneration(
        observed_pgid, process.pid, leader_identity
    )
    refresh_process_group_generation(generation)
    return observed_pgid, leader_identity, admitted_pidfd, generation


class BoundarySignal(RuntimeError):
    """A stop signal linearized before descriptor publication."""


def publish_monitor(
    path: Path,
    value: bytes,
    run_directory: Path,
    run_directory_fd: int,
    run_identity: Mapping[str, int],
    *,
    boundary_hook=None,
) -> dict[str, object]:
    verify_run_directory_binding(run_directory, run_directory_fd, run_identity)
    if path.parent != run_directory or Path(path.name).name != path.name:
        raise RuntimeError("monitor publication escaped run directory")
    directory_fd = os.dup(run_directory_fd)
    temporary = f".{path.name}.partial-{os.getpid()}-{secrets.token_hex(8)}"
    fd: int | None = None
    try:
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("monitor path already exists")
        fd = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
            dir_fd=directory_fd,
        )
        os.write(fd, value)
        os.fchmod(fd, 0o400)
        os.fsync(fd)
        if read_fd(fd) != value:
            raise RuntimeError("monitor descriptor bytes drift")
        if boundary_hook is not None:
            boundary_hook()
        verify_run_directory_binding(run_directory, directory_fd, run_identity)
        os.link(
            f"/proc/self/fd/{fd}",
            path.name,
            dst_dir_fd=directory_fd,
            follow_symlinks=True,
        )
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        verify_run_directory_binding(run_directory, directory_fd, run_identity)
        final_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        try:
            final = read_fd(final_fd)
            identity = file_identity(os.fstat(final_fd))
        finally:
            os.close(final_fd)
        if final != value or identity["nlink"] != 1 or identity["mode"] != 0o400:
            raise RuntimeError("monitor final identity/bytes invalid")
        return {"path": str(path), "sha256": digest_bytes(value), "identity": identity}
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def configured_run_id() -> str:
    value = os.environ.get("PLANORA_MUNI_FRONTIER_V10_RUN_ID")
    if value is None:
        return secrets.token_hex(12)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value) is None:
        raise RuntimeError("invalid v10 run id")
    return value


def sanitized_child_environment(
    *,
    run_directory: Path,
    run_directory_fd: int,
    captures: Mapping[str, Mapping[str, Any]],
    runtime_binding: Mapping[str, Any],
) -> dict[str, str]:
    """Return the complete allowlisted child environment; inherit nothing."""

    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": f"/proc/self/fd/{run_directory_fd}",
        CAPTURE_MANIFEST_ENV: json.dumps(
            captures, sort_keys=True, separators=(",", ":")
        ),
        RUNTIME_BUNDLE_ENV: json.dumps(
            runtime_binding, sort_keys=True, separators=(",", ":")
        ),
    }


def _capture_json_at(
    directory_fd: int, name: str, display_path: Path
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    try:
        value, identity = capture_regular_at(directory_fd, name, maximum_bytes=128 << 20)
    except FileNotFoundError:
        return None, None
    try:
        payload = json.loads(
            value,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {constant}")
            ),
        )
    except (json.JSONDecodeError, ValueError):
        payload = None
    return payload, {
        "path": str(display_path),
        "sha256": digest_bytes(value),
        "identity": identity,
    }


def validate_partial_payload(payload: object) -> bool:
    """Validate the fresh-solve non-solution checkpoint and exclusions."""

    return bool(
        isinstance(payload, dict)
        and frozenset(payload)
        == {
            "schema", "status", "admissible_as_solution",
            "solver_input_mode",
            "competitor_schedule_or_result_used",
            "competitor_placement_or_hint_used", "lineage",
            "fairness_exclusion", "runtime_lineage",
        }
        and payload.get("schema")
        == "planora.muni-fspsx.frontier-v26.fresh-partial.v1"
        and payload.get("status") == "FRESH_SOLVE_NOT_YET_ADMISSIBLE"
        and payload.get("admissible_as_solution") is False
        and payload.get("solver_input_mode") == "OFFICIAL_INPUT_ONLY_FRESH"
        and payload.get("competitor_schedule_or_result_used") is False
        and payload.get("competitor_placement_or_hint_used") is False
        and isinstance(payload.get("lineage"), dict)
        and payload["lineage"].get("instance_sha256")
        == EXPECTED_INSTANCE_SHA256
        and payload["lineage"].get("unsolved_classes")
        == EXPECTED_OPEN_CLASSES + EXPECTED_FIXED_CLASSES
        and payload["lineage"].get("unsolved_students") == 1152
        and isinstance(
            payload["lineage"].get("planora_source_manifest_sha256"), str
        )
        and frozenset(payload["lineage"])
        == {
            "instance_sha256", "runner_sha256", "supervisor_sha256",
            "planora_source_manifest_sha256", "unsolved_classes",
            "unsolved_students",
        }
        and isinstance(payload.get("runtime_lineage"), dict)
        and frozenset(payload["runtime_lineage"])
        == {
            "python_binary_sha256", "runtime_manifest_sha256",
            "loaded_manifest_sha256", "stdlib_manifest_sha256",
            "residual_system_boundary",
        }
        and payload["runtime_lineage"].get("residual_system_boundary")
        == "observed_and_hashed_not_sealed"
        and validate_fairness_exclusion_payload(payload.get("fairness_exclusion"))
    )


def validate_fairness_exclusion_payload(payload: object) -> bool:
    return bool(
        isinstance(payload, dict)
        and frozenset(payload)
        == {
            "certificate_sha256", "verdict", "excluded_progress_sha256",
            "excluded_component_checkpoint_sha256", "solver_input_mode",
            "progress_runtime_accessed",
            "component_checkpoint_runtime_accessed",
        }
        and payload.get("certificate_sha256")
        == "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4"
        and payload.get("verdict") == "NO_GO_UNPROVEN"
        and payload.get("excluded_progress_sha256")
        == EXPECTED_PROGRESS_SHA256
        and payload.get("excluded_component_checkpoint_sha256")
        == "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80"
        and payload.get("solver_input_mode") == "OFFICIAL_INPUT_ONLY_FRESH"
        and payload.get("progress_runtime_accessed") is False
        and payload.get("component_checkpoint_runtime_accessed") is False
    )


def validate_controlled_stdout(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    required = {
        "schema", "status", "admissible_as_solution",
        "solver_input_mode", "fairness_exclusion",
        "competitor_schedule_or_result_used", "competitor_placement_or_hint_used",
        "partial", "runtime_closure", "reason",
    }
    allowed = required | {"fresh_solve"}
    return bool(
        required <= frozenset(payload) <= allowed
        and payload.get("schema")
        == "planora.muni-fspsx.frontier-v26.controlled-unknown.v1"
        and payload.get("status") == "CONTROLLED_UNKNOWN"
        and payload.get("admissible_as_solution") is False
        and payload.get("solver_input_mode") == "OFFICIAL_INPUT_ONLY_FRESH"
        and validate_fairness_exclusion_payload(
            payload.get("fairness_exclusion")
        )
        and payload.get("competitor_schedule_or_result_used") is False
        and payload.get("competitor_placement_or_hint_used") is False
        and isinstance(payload.get("reason"), str)
        and isinstance(payload.get("partial"), dict)
        and isinstance(payload.get("runtime_closure"), dict)
        and payload["runtime_closure"].get("phase")
        == "controlled-unknown-pre-exit"
    )


def validate_complete_report(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    expected_keys = {
        "schema", "status", "admissible_as_solution", "instance_sha256",
        "solver_input_mode", "planora_source_manifest_sha256",
        "placements", "students", "fresh_solve", "fresh_generic_validation",
        "semantic_errors", "document_errors", "cardinality_errors", "score",
        "partial_checkpoint", "fairness_exclusion",
        "runtime_admission", "runtime_closure",
        "competitor_schedule_or_result_used",
        "competitor_placement_or_hint_used", "output",
    }
    return bool(
        frozenset(payload) == expected_keys
        and payload.get("schema")
        == "planora.muni-fspsx.frontier-v26.fresh-complete.v1"
        and payload.get("status") == "COMPLETE_VALID"
        and payload.get("admissible_as_solution") is True
        and payload.get("instance_sha256") == EXPECTED_INSTANCE_SHA256
        and payload.get("solver_input_mode") == "OFFICIAL_INPUT_ONLY_FRESH"
        and isinstance(payload.get("planora_source_manifest_sha256"), str)
        and payload.get("placements") == EXPECTED_OPEN_CLASSES + EXPECTED_FIXED_CLASSES
        and payload.get("students") == 1152
        and payload.get("semantic_errors") == []
        and payload.get("document_errors") == []
        and payload.get("cardinality_errors") == []
        and payload.get("competitor_schedule_or_result_used") is False
        and payload.get("competitor_placement_or_hint_used") is False
        and validate_fairness_exclusion_payload(
            payload.get("fairness_exclusion")
        )
        and isinstance(payload.get("runtime_admission"), dict)
        and isinstance(payload.get("runtime_closure"), dict)
        and payload["runtime_closure"].get("phase") == "complete-pre-publication"
        and isinstance(payload.get("output"), dict)
    )


def validate_solution_document_bytes(value: bytes) -> bool:
    try:
        root = ElementTree.fromstring(value)
    except ElementTree.ParseError:
        return False
    if (
        root.tag != "solution"
        or root.attrib.get("technique") != "planora-v10"
        or frozenset(root.attrib) != {"name", "technique"}
    ):
        return False
    classes = list(root)
    if len(classes) != EXPECTED_OPEN_CLASSES + EXPECTED_FIXED_CLASSES:
        return False
    class_ids: set[str] = set()
    student_ids: set[str] = set()
    for row in classes:
        if row.tag != "class" or frozenset(row.attrib) not in (
            {"id", "days", "start", "weeks"},
            {"id", "days", "start", "weeks", "room"},
        ):
            return False
        class_id = row.attrib.get("id")
        if not class_id or class_id in class_ids:
            return False
        class_ids.add(class_id)
        try:
            int(row.attrib["start"])
        except (KeyError, ValueError):
            return False
        for child in row:
            if child.tag != "student" or frozenset(child.attrib) != {"id"}:
                return False
            student_id = child.attrib.get("id")
            if not student_id:
                return False
            student_ids.add(student_id)
    return len(student_ids) == 1152


def classify_artifacts(
    *,
    child_exit: int | None,
    stop_reason: str,
    received_signal: int | None,
    partial_payload: object,
    partial_capture: Mapping[str, object] | None,
    report_payload: object,
    child_stdout_payload: object,
    output_bytes: bytes | None,
    output_capture: Mapping[str, object] | None,
    report_capture: Mapping[str, object] | None,
    errors: Sequence[str],
) -> tuple[bool, bool]:
    """Return ``(accepted, controlled_partial)`` without conflating the two."""

    partial_valid = validate_partial_payload(partial_payload)
    controlled_partial = bool(
        child_exit == 3
        and partial_valid
        and validate_controlled_stdout(child_stdout_payload)
        and isinstance(child_stdout_payload, dict)
        and child_stdout_payload.get("partial") == partial_capture
        and output_bytes is None
        and report_payload is None
    )
    complete_stdout = bool(
        isinstance(child_stdout_payload, dict)
        and frozenset(child_stdout_payload)
        == {
            "schema", "status", "admissible_as_solution",
            "competitor_schedule_or_result_used",
            "competitor_placement_or_hint_used", "output", "report",
        }
        and child_stdout_payload.get("schema")
        == "planora.muni-fspsx.frontier-v26.runner-result.v1"
        and child_stdout_payload.get("status") == "COMPLETE_VALID"
        and child_stdout_payload.get("admissible_as_solution") is True
        and child_stdout_payload.get("competitor_schedule_or_result_used") is False
        and child_stdout_payload.get("competitor_placement_or_hint_used") is False
        and child_stdout_payload.get("output") == output_capture
        and child_stdout_payload.get("report") == report_capture
    )
    report_output_bound = bool(
        validate_complete_report(report_payload)
        and isinstance(report_payload, dict)
        and report_payload.get("output") == output_capture
    )
    accepted = bool(
        stop_reason == "normal_exit"
        and child_exit == 0
        and received_signal is None
        and partial_valid
        and complete_stdout
        and report_output_bound
        and output_bytes is not None
        and validate_solution_document_bytes(output_bytes)
        and not errors
    )
    return accepted, controlled_partial


def run_launch(
    expected_supervisor_sha256: str,
    expected_launcher_sha256: str,
    expected_manifest_sha256: str,
) -> int:
    started = time.monotonic()
    started_epoch = time.time()
    supervisor_pid = os.getpid()
    supervisor_identity = proc_stat_identity(supervisor_pid)
    if supervisor_identity is None:
        raise RuntimeError("supervisor identity unavailable before launch capture")
    verify_external_evidence(
        SEALED_SELF_EVIDENCE, expected_supervisor_sha256, "supervisor"
    )
    verify_external_evidence(
        SEALED_LAUNCHER_EVIDENCE, expected_launcher_sha256, "launcher"
    )
    verify_external_evidence(
        PRE_SUPERVISOR_STDLIB_EVIDENCE,
        EXPECTED_STDLIB_MANIFEST_SHA256,
        "pre-supervisor stdlib manifest",
    )
    manifest, manifest_bytes = load_freeze_manifest(
        expected_manifest_sha256, external=True
    )
    validate_manifest_contract(manifest)

    signal_state = {"number": None}

    def receive(signum, _frame) -> None:
        signal_state["number"] = int(signum)

    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
    previous_handlers = {signum: signal.getsignal(signum) for signum in STOP_SIGNALS}
    for signum in STOP_SIGNALS:
        signal.signal(signum, receive)
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    sealed_fds: list[int] = []
    run_directory: Path | None = None
    run_directory_fd: int | None = None
    run_identity: dict[str, int] | None = None
    run_id = configured_run_id()
    stop_reason = "normal_exit"
    cleanup: dict[str, object] | None = None
    errors: list[str] = []
    samples: list[dict[str, object]] = []
    peak_group_memory = 0
    peak_supervisor_memory = 0
    peak_whole_launch_memory = 0
    minimum_available: int | None = None
    child_exit: int | None = None
    leader_identity: tuple[int, int, int] | None = None
    generation: ProcessGroupGeneration | None = None
    pidfd: int | None = None
    runtime_initial_fd: int | None = None
    runtime_directory: Path | None = None
    captures: dict[str, dict[str, Any]] = {}
    capture_end: dict[str, dict[str, Any]] = {}
    source_end: dict[str, dict[str, Any]] = {}
    runtime_summary: dict[str, Any] | None = None
    runtime_binding: dict[str, Any] | None = None
    sealed_storage_kib = 0
    runtime_end: dict[str, Any] | None = None
    baseline = host_sample()
    try:
        if baseline["mem_available_kib"] < LAUNCH_MEMAVAILABLE_FLOOR_KIB:
            raise RuntimeError("launch host MemAvailable floor is not satisfied")
        admitted = verify_manifest_files(manifest, dry=False)
        if signal.sigpending().intersection(STOP_SIGNALS):
            raise RuntimeError("stop signal pending before launch mutation")
        run_directory = Path(f"/tmp/planora-muni-fspsx-frontier-v26-{run_id}")
        os.mkdir(run_directory, 0o700)
        run_directory_fd = os.open(
            run_directory,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        run_stat = os.fstat(run_directory_fd)
        run_identity = file_identity(run_stat)
        if run_identity["mode"] != 0o700 or run_identity["uid"] != os.getuid():
            raise RuntimeError("private run directory admission failed")
        verify_run_directory_binding(
            run_directory, run_directory_fd, run_identity
        )

        rows = manifest_files(manifest)
        pass_fds: list[int] = [run_directory_fd]
        capture_sources = {
            "runner": (RUNNER, str(rows["runner"]["sha256"])),
            "benchmarks": (
                Path(str(rows["benchmarks"]["path"])),
                str(rows["benchmarks"]["sha256"]),
            ),
            "semantic": (
                Path(str(rows["semantic"]["path"])),
                str(rows["semantic"]["sha256"]),
            ),
            "preprocessing": (
                Path(str(rows["preprocessing"]["path"])),
                str(rows["preprocessing"]["sha256"]),
            ),
            "frontier": (
                Path(str(rows["frontier"]["path"])),
                str(rows["frontier"]["sha256"]),
            ),
            "room_oracle": (
                Path(str(rows["room_oracle"]["path"])),
                str(rows["room_oracle"]["sha256"]),
            ),
            "generic_validator": (
                Path(str(rows["generic_validator"]["path"])),
                str(rows["generic_validator"]["sha256"]),
            ),
            "fairness_certificate": (
                Path(str(rows["fairness_certificate"]["path"])),
                str(rows["fairness_certificate"]["sha256"]),
            ),
            "stdlib_manifest": (
                STDLIB_MANIFEST,
                EXPECTED_STDLIB_MANIFEST_SHA256,
            ),
            "instance": (INSTANCE, EXPECTED_INSTANCE_SHA256),
            "python_binary": (PYTHON, str(rows["python_binary"]["sha256"])),
            **{
                label: (path, str(rows[label]["sha256"]))
                for label, path in PLANORA_FRESH_MODULES.items()
            },
            **{
                label: (path, str(rows[label]["sha256"]))
                for label, path in RUNTIME_RECORDS.items()
            },
        }
        for label, (path, expected) in capture_sources.items():
            descriptor, row = _stream_capture(path, expected, label)
            captures[label] = row
            sealed_fds.append(descriptor)
            pass_fds.append(descriptor)
        runner_fd = int(captures["runner"]["fd"])
        runtime_directory = Path(
            f"/tmp/planora-muni-fspsx-frontier-v26-runtime-{run_id}"
        )
        os.mkdir(runtime_directory, 0o700)
        runtime_initial_fd = os.open(
            runtime_directory,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
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
        sealed_storage_kib = int(runtime_binding["sealed_page_rounded_kib"])
        pre_child_values = identity_pinned_process_memory(
            supervisor_pid, supervisor_identity
        )
        pre_child_supervisor_memory = (
            int(pre_child_values["VmRSS"]) + int(pre_child_values["VmSwap"])
        )
        pre_child_whole_memory = pre_child_supervisor_memory + sealed_storage_kib
        peak_supervisor_memory = max(
            peak_supervisor_memory, pre_child_supervisor_memory
        )
        peak_whole_launch_memory = max(
            peak_whole_launch_memory, pre_child_whole_memory
        )
        if pre_child_whole_memory > WHOLE_LAUNCH_MEMORY_CAP_KIB:
            raise RuntimeError("whole launch memory cap exceeded before child")
        os.close(runtime_initial_fd)
        runtime_initial_fd = None
        sealed_fds.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        pass_fds.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        source_evidence = {
            "benchmarks": captures["benchmarks"],
            "benchmarks.itc2019": captures["semantic"],
            "benchmarks.itc2019_preprocessing": captures["preprocessing"],
            "benchmarks.itc2019_frontier_joint": captures["frontier"],
            "benchmarks.itc2019_room_oracle": captures["room_oracle"],
            "generic_validator": captures["generic_validator"],
            "fairness_certificate": captures["fairness_certificate"],
            "instance": captures["instance"],
            **{
                f"benchmarks.{label}": captures[label]
                for label in PLANORA_FRESH_MODULES
            },
        }
        runner_stdout = os.open(
            "runner.stdout.log",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
            dir_fd=run_directory_fd,
        )
        runner_stderr = os.open(
            "runner.stderr.log",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
            dir_fd=run_directory_fd,
        )
        pass_fds.extend((runner_stdout, runner_stderr))
        absolute_deadline = started + RUNNER_SECONDS
        pycache_prefix = Path(
            f"/proc/self/fd/{run_directory_fd}/.pycache-disabled"
        )
        command = [
            f"/proc/self/fd/{captures['python_binary']['fd']}",
            "-I", "-S", "-B", "-X", f"pycache_prefix={pycache_prefix}",
            "-c", RUNNER_LOADER,
            str(runner_fd), str(rows["runner"]["sha256"]),
            json.dumps(source_evidence, sort_keys=True),
            str(runtime_root_fd),
            str(captures["stdlib_manifest"]["fd"]),
            EXPECTED_STDLIB_MANIFEST_SHA256,
            "--launch", "--run-directory", str(run_directory),
            "--run-directory-fd", str(run_directory_fd),
            "--run-device", str(run_identity["device"]),
            "--run-inode", str(run_identity["inode"]),
            "--run-uid", str(run_identity["uid"]),
            "--runner-sha256", str(rows["runner"]["sha256"]),
            "--supervisor-sha256", expected_supervisor_sha256,
            "--absolute-deadline-monotonic", repr(absolute_deadline),
            "--python", f"/proc/self/fd/{captures['python_binary']['fd']}",
        ]
        child_environment = sanitized_child_environment(
            run_directory=run_directory,
            run_directory_fd=run_directory_fd,
            captures=captures,
            runtime_binding=runtime_binding,
        )
        parent_pid = os.getpid()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=runner_stdout,
            stderr=runner_stderr,
            close_fds=True,
            pass_fds=tuple(pass_fds),
            env=child_environment,
            start_new_session=True,
            preexec_fn=lambda: arm_parent_death_signal(parent_pid),
        )
        # start_new_session=True makes the child's PID its expected PGID.
        # Record that provisional cleanup target before any fallible admission
        # query so exception/finally paths can never skip a surviving group.
        pgid = process.pid
        pgid, leader_identity, pidfd, generation = admit_spawned_process_group(
            process, pgid, None
        )
        if hasattr(os, "pidfd_open"):
            try:
                pidfd = os.pidfd_open(process.pid, 0)
            except OSError:
                pidfd = None
        hook = POST_POPEN_ADMISSION_TEST_HOOK
        if hook is not None:
            hook(process, pgid, generation)
        os.close(runner_stdout)
        os.close(runner_stderr)
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        while True:
            refresh_process_group_generation(generation)
            if process.poll() is not None:
                break
            sample = host_sample()
            memory_snapshot = identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=supervisor_pid,
                supervisor_identity=supervisor_identity,
            )
            group_memory = int(memory_snapshot["group_memory_kib"])
            own_memory = int(memory_snapshot["supervisor_memory_kib"])
            process_whole_memory = int(
                memory_snapshot["whole_launch_set_union_memory_kib"]
            )
            whole_memory = process_whole_memory + sealed_storage_kib
            members = tuple(memory_snapshot["pids"])
            peak_group_memory = max(peak_group_memory, group_memory)
            peak_supervisor_memory = max(peak_supervisor_memory, own_memory)
            peak_whole_launch_memory = max(
                peak_whole_launch_memory, whole_memory
            )
            minimum_available = (
                sample["mem_available_kib"]
                if minimum_available is None
                else min(minimum_available, sample["mem_available_kib"])
            )
            samples.append(
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "group_memory_kib": group_memory,
                    "supervisor_memory_kib": own_memory,
                    "process_set_union_memory_kib": process_whole_memory,
                    "sealed_storage_kib": sealed_storage_kib,
                    "whole_launch_memory_kib": whole_memory,
                    "group_pids": members,
                    **sample,
                }
            )
            if signal_state["number"] is not None:
                stop_reason = f"signal:{signal_state['number']}"
                break
            breach = resource_decision(
                elapsed_seconds=time.monotonic() - started,
                group_memory_kib=group_memory,
                supervisor_memory_kib=own_memory,
                sealed_storage_kib=sealed_storage_kib,
                sample=sample,
            )
            if breach is not None:
                stop_reason = breach
                break
            time.sleep(POLL_SECONDS)
        # Always enumerate and drain the original PGID, even when the leader
        # has already exited.  A leader can exit while descendants remain in
        # its session/process group; successful leader exit is not closure.
        cleanup = stop_process_group(process, generation, pidfd)
        child_exit = process.wait()
        if cleanup.get("errors"):
            raise RuntimeError(
                "process-group cleanup reported errors: "
                + ";".join(str(value) for value in cleanup["errors"])
            )
        if process_group_pids(pgid):
            raise RuntimeError("original process group was not empty after cleanup")
    except BaseException as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        if stop_reason == "normal_exit":
            stop_reason = "supervisor_exception"
        if process is not None and pgid is not None and generation is not None:
            try:
                cleanup = stop_process_group(process, generation, pidfd)
            except BaseException as cleanup_exc:
                errors.append(f"cleanup:{type(cleanup_exc).__name__}:{cleanup_exc}")
    finally:
        signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
        try:
            if process is not None and pgid is not None and generation is not None:
                remaining_group = process_group_pids(pgid)
                if remaining_group:
                    cleanup = stop_process_group(
                        process, generation, pidfd
                    )
                remaining_group = process_group_pids(pgid)
                if remaining_group:
                    raise RuntimeError(
                        "original process group non-empty before closure replay: "
                        + ",".join(str(pid) for pid in remaining_group)
                    )
            if captures:
                capture_end = {
                    label: verify_sealed_capture(int(row["fd"]), row)
                    for label, row in captures.items()
                }
                source_end = {
                    label: verify_source_contract(row)
                    for label, row in captures.items()
                }
            external_rows = {
                "external_supervisor": SEALED_SELF_EVIDENCE,
                "external_launcher": SEALED_LAUNCHER_EVIDENCE,
                "external_freeze_manifest": SEALED_MANIFEST_EVIDENCE,
            }
            for label, row in external_rows.items():
                if not isinstance(row, Mapping):
                    raise RuntimeError(f"missing {label} replay evidence")
                capture_end[label] = verify_sealed_capture(int(row["fd"]), row)
                source_end[label] = verify_source_contract(row)
            if runtime_binding is not None:
                runtime_end = verify_runtime_bundle_end(runtime_binding)
        except BaseException as replay_exc:
            errors.append(
                f"post_execution_closure:{type(replay_exc).__name__}:{replay_exc}"
            )
            if stop_reason == "normal_exit":
                stop_reason = "post_execution_closure_rejected"
        finally:
            watch_rows = [*captures.values()]
            for external in (
                SEALED_SELF_EVIDENCE,
                SEALED_LAUNCHER_EVIDENCE,
                SEALED_MANIFEST_EVIDENCE,
            ):
                if isinstance(external, Mapping):
                    watch_rows.append(external)
            for row in watch_rows:
                watch_fd = row.get("source_watch_fd")
                if type(watch_fd) is int:
                    try:
                        os.close(watch_fd)
                    except OSError:
                        pass
        if pidfd is not None:
            os.close(pidfd)
        for fd in sealed_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        if runtime_initial_fd is not None:
            os.close(runtime_initial_fd)
        # Keep the non-terminating handlers installed until the descriptor
        # publication boundary has completed.  Signals remain blocked here.

    final_host = host_sample()
    output_payload = report_payload = partial_payload = None
    child_stdout_payload = None
    output_capture = report_capture = partial_capture = child_stdout_capture = None
    runner_stderr_capture = None
    output_bytes: bytes | None = None
    accepted = False
    controlled_partial = False
    if (
        run_directory is not None
        and run_directory_fd is not None
        and run_identity is not None
    ):
        try:
            verify_run_directory_binding(
                run_directory, run_directory_fd, run_identity
            )
        except BaseException as directory_exc:
            errors.append(
                "run_directory_binding:"
                f"{type(directory_exc).__name__}:{directory_exc}"
            )
        observed_names = {
            entry.name for entry in os.scandir(run_directory_fd)
        }
        expected_names = {
            "runner.stdout.log", "runner.stderr.log", "partial-checkpoint.json"
        }
        if child_exit == 0:
            expected_names |= {"solution.xml", "runner-report.json"}
        if observed_names != expected_names:
            errors.append(
                "run_directory_artifact_schema:" + ",".join(sorted(observed_names))
            )
        partial_payload, partial_capture = _capture_json_at(
            run_directory_fd,
            "partial-checkpoint.json",
            run_directory / "partial-checkpoint.json",
        )
        report_payload, report_capture = _capture_json_at(
            run_directory_fd,
            "runner-report.json",
            run_directory / "runner-report.json",
        )
        child_stdout_payload, child_stdout_capture = _capture_json_at(
            run_directory_fd,
            "runner.stdout.log",
            run_directory / "runner.stdout.log",
        )
        try:
            stderr_bytes, stderr_identity = capture_regular_at(
                run_directory_fd, "runner.stderr.log"
            )
            runner_stderr_capture = {
                "path": str(run_directory / "runner.stderr.log"),
                "sha256": digest_bytes(stderr_bytes),
                "identity": stderr_identity,
                "empty": not stderr_bytes,
            }
            if stderr_bytes:
                errors.append("runner_stderr_not_empty")
        except FileNotFoundError:
            errors.append("runner_stderr_missing")
        output_path = run_directory / "solution.xml"
        try:
            output_bytes, output_identity = capture_regular_at(
                run_directory_fd, "solution.xml"
            )
            output_capture = {
                "path": str(output_path),
                "sha256": digest_bytes(output_bytes),
                "identity": output_identity,
            }
        except FileNotFoundError:
            output_capture = None
        accepted, controlled_partial = classify_artifacts(
            child_exit=child_exit,
            stop_reason=stop_reason,
            received_signal=signal_state["number"],
            partial_payload=partial_payload,
            partial_capture=partial_capture,
            report_payload=report_payload,
            child_stdout_payload=child_stdout_payload,
            output_bytes=output_bytes,
            output_capture=output_capture,
            report_capture=report_capture,
            errors=errors,
        )

    pending_before_boundary = signal.sigpending().intersection(STOP_SIGNALS)
    if pending_before_boundary:
        signal_state["number"] = min(int(value) for value in pending_before_boundary)
        accepted = False
        if stop_reason == "normal_exit":
            stop_reason = f"signal:{signal_state['number']}"

    def monitor_payload() -> dict[str, object]:
        return {
        "schema": "planora.muni-fspsx.frontier-v26.supervisor.v1",
        "status": "COMPLETE_VALID" if accepted else ("CONTROLLED_PARTIAL" if controlled_partial else "REJECTED"),
        "accepted": accepted,
        "controlled_partial": controlled_partial,
        "run_id": run_id,
        "run_directory": str(run_directory) if run_directory else None,
        "child_exit_code": child_exit,
        "stop_reason": stop_reason,
        "received_signal": signal_state["number"],
        "cleanup": cleanup,
        "errors": errors,
        "constraints": manifest.get("constraints"),
        "resource_attribution": {
            "kill_metric": "process_group_sum_VmRSS_plus_VmSwap",
            "host_swap_counters_telemetry_only": True,
            "host_pressure_label": "host_pressure:memavailable_floor",
            "peak_group_memory_kib": peak_group_memory,
            "peak_supervisor_memory_kib": peak_supervisor_memory,
            "peak_whole_launch_memory_kib": peak_whole_launch_memory,
            "whole_launch_memory_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
            "whole_launch_accounting": (
                "supervisor_VmRSS_plus_VmSwap_plus_"
                "child_process_group_VmRSS_plus_VmSwap_no_double_count"
            ),
            "minimum_memavailable_kib": minimum_available,
            "initial_host_sample": baseline,
            "final_host_sample": final_host,
            "host_pswpin_delta_pages": max(0, final_host["pswpin_pages"] - baseline["pswpin_pages"]),
            "host_pswpout_delta_pages": max(0, final_host["pswpout_pages"] - baseline["pswpout_pages"]),
            "host_swapfree_delta_kib": final_host["swap_free_kib"] - baseline["swap_free_kib"],
        },
        "samples": samples,
        "partial_checkpoint": partial_capture,
        "runner_report": report_capture,
        "runner_stdout": child_stdout_capture,
        "runner_stderr": runner_stderr_capture,
        "output": output_capture,
        "runtime_bundle": runtime_summary,
        "runtime_bundle_post_execution": runtime_end,
        "sealed_captures_post_execution": capture_end,
        "live_sources_post_execution": source_end,
        "child_environment_keys": [
            "PATH", "LANG", "LC_ALL", "TZ", "TMPDIR",
            CAPTURE_MANIFEST_ENV, RUNTIME_BUNDLE_ENV,
        ],
        "environment_inherited": False,
        "lineage": {
            "supervisor_sha256": expected_supervisor_sha256,
            "launcher_sha256": expected_launcher_sha256,
            "freeze_manifest_sha256": expected_manifest_sha256,
            "freeze_manifest_bytes_sha256": digest_bytes(manifest_bytes),
            "instance_sha256": EXPECTED_INSTANCE_SHA256,
            "excluded_progress_sha256": EXPECTED_PROGRESS_SHA256,
            "fairness_certificate_sha256": (
                "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4"
            ),
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
        },
        "started_epoch_seconds": started_epoch,
        "elapsed_seconds": time.monotonic() - started,
        }

    if run_directory is None or run_directory_fd is None or run_identity is None:
        monitor = monitor_payload()
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if run_directory_fd is not None:
            os.close(run_directory_fd)
        print(json.dumps(monitor, sort_keys=True), flush=True)
        return 2

    def linearize_signals() -> None:
        nonlocal accepted
        expected_artifacts = {
            "partial-checkpoint.json": partial_capture,
            "runner.stdout.log": child_stdout_capture,
            "runner.stderr.log": runner_stderr_capture,
        }
        if output_capture is not None:
            expected_artifacts["solution.xml"] = output_capture
        if report_capture is not None:
            expected_artifacts["runner-report.json"] = report_capture
        try:
            for name, expected in expected_artifacts.items():
                if not isinstance(expected, Mapping):
                    raise RuntimeError(f"artifact capture absent: {name}")
                verify_run_directory_binding(
                    run_directory, run_directory_fd, run_identity
                )
                value, identity = capture_regular_at(run_directory_fd, name)
                if (
                    expected.get("sha256") != digest_bytes(value)
                    or expected.get("identity") != identity
                ):
                    raise RuntimeError(f"artifact final-boundary drift: {name}")
        except BaseException as artifact_exc:
            accepted = False
            errors.append(
                f"artifact_final_boundary:{type(artifact_exc).__name__}:{artifact_exc}"
            )
            raise BoundarySignal("artifact drift before publication boundary")
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
        pending = signal.sigpending().intersection(STOP_SIGNALS)
        if pending and signal_state["number"] is None:
            signal_state["number"] = min(int(value) for value in pending)
        if signal_state["number"] is not None and accepted:
            raise BoundarySignal("stop signal arrived before publication boundary")

    monitor = monitor_payload()
    monitor_bytes = (json.dumps(monitor, indent=2, sort_keys=True) + "\n").encode()
    try:
        evidence = publish_monitor(
            run_directory / "supervisor-report.json",
            monitor_bytes,
            run_directory,
            run_directory_fd,
            run_identity,
            boundary_hook=linearize_signals,
        )
    except BoundarySignal:
        accepted = False
        if stop_reason == "normal_exit":
            stop_reason = f"signal:{signal_state['number']}"
        monitor = monitor_payload()
        monitor_bytes = (
            json.dumps(monitor, indent=2, sort_keys=True) + "\n"
        ).encode()
        evidence = publish_monitor(
            run_directory / "supervisor-report.json",
            monitor_bytes,
            run_directory,
            run_directory_fd,
            run_identity,
        )
    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
    for signum, handler in previous_handlers.items():
        signal.signal(signum, handler)
    os.close(run_directory_fd)
    print(json.dumps({"accepted": accepted, "controlled_partial": controlled_partial, "monitor": evidence}, sort_keys=True), flush=True)
    return 0 if accepted else (3 if controlled_partial else 2)


def consume_probe_report(
    run_directory_fd: int,
    report_fd: int,
    created: os.stat_result,
) -> tuple[dict[str, object], dict[str, object]]:
    retained = os.fstat(report_fd)
    named = os.stat(
        "sealed-import-probe-child.json",
        dir_fd=run_directory_fd,
        follow_symlinks=False,
    )
    identity_keys = ("st_dev", "st_ino", "st_uid", "st_nlink")
    if (
        not stat.S_ISREG(retained.st_mode)
        or stat.S_IMODE(retained.st_mode) != 0o400
        or int(retained.st_nlink) != 1
        or any(getattr(retained, key) != getattr(named, key) for key in identity_keys)
        or any(getattr(retained, key) != getattr(created, key) for key in identity_keys)
    ):
        raise RuntimeError("probe report retained-FD/name identity drift")
    if retained.st_size <= 0 or retained.st_size > 4 << 20:
        raise RuntimeError("probe report size rejected")
    value = read_fd(report_fd)
    if int(retained.st_size) != len(value):
        raise RuntimeError("probe report size rejected")
    payload = json.loads(
        value,
        parse_constant=lambda constant: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON constant: {constant}")
        ),
    )
    if not isinstance(payload, dict):
        raise RuntimeError("probe report payload rejected")
    os.unlink("sealed-import-probe-child.json", dir_fd=run_directory_fd)
    return payload, {
        "path": "retained-fd-unlinked-after-identity-replay",
        "sha256": digest_bytes(value),
        "identity": file_identity(retained),
        "transport": "parent_created_retained_fd_and_named_identity_replay",
    }


def _absent_probe_log_diagnostic(*, include_tail: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "present": False,
        "size_bytes": None,
        "sha256": None,
        "identity_matches_parent_creation": None,
        "inspection_error": None,
    }
    if include_tail:
        result.update(
            {
                "tail_encoding": "base64",
                "tail_base64": "",
                "tail_bytes": 0,
                "tail_limit_bytes": PROBE_STDIO_TAIL_BYTES,
                "tail_truncated": False,
            }
        )
    return result


def _digest_fd_and_tail(
    descriptor: int, size: int, *, tail_limit: int
) -> tuple[str, bytes]:
    digest_state = sha256()
    tail = b""
    offset = 0
    while offset < size:
        block = os.pread(descriptor, min(1 << 20, size - offset), offset)
        if not block:
            raise RuntimeError("probe diagnostic artifact ended early")
        digest_state.update(block)
        if tail_limit:
            tail = (tail + block)[-tail_limit:]
        offset += len(block)
    return digest_state.hexdigest(), tail


def capture_probe_log_diagnostic(
    directory_fd: int | None,
    name: str,
    created: os.stat_result | None,
    *,
    include_tail: bool,
) -> dict[str, object]:
    """Hash a completed child log by its parent-created identity."""

    result = _absent_probe_log_diagnostic(include_tail=include_tail)
    if directory_fd is None or created is None:
        return result
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return result
    try:
        before = os.fstat(descriptor)
        result["present"] = True
        identity_keys = ("st_dev", "st_ino", "st_uid", "st_nlink")
        identity_matches = all(
            getattr(before, key) == getattr(created, key) for key in identity_keys
        )
        result["identity_matches_parent_creation"] = identity_matches
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o400
            or int(before.st_nlink) != 1
            or not identity_matches
        ):
            raise RuntimeError(f"probe diagnostic log identity rejected: {name}")
        size = int(before.st_size)
        actual, tail = _digest_fd_and_tail(
            descriptor,
            size,
            tail_limit=PROBE_STDIO_TAIL_BYTES if include_tail else 0,
        )
        after = os.fstat(descriptor)
        if file_identity(before) != file_identity(after):
            raise RuntimeError(f"probe diagnostic log drift: {name}")
        result.update({"size_bytes": size, "sha256": actual})
        if include_tail:
            result.update(
                {
                    "tail_base64": base64.b64encode(tail).decode("ascii"),
                    "tail_bytes": len(tail),
                    "tail_truncated": size > len(tail),
                }
            )
    except BaseException as exc:
        result["inspection_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result


def probe_report_presence(
    directory_fd: int | None,
    report_fd: int | None,
    created: os.stat_result | None,
) -> dict[str, object]:
    """Describe report presence without substituting pathname authority for the FD."""

    result: dict[str, object] = {
        "parent_created": created is not None,
        "retained_fd_present": report_fd is not None,
        "named_entry_present": False,
        "named_entry_matches_retained_fd": None,
        "size_bytes": None,
        "sha256": None,
        "payload_consumed": False,
        "contract_valid": False,
        "inspection_error": None,
    }
    if report_fd is None or created is None:
        return result
    try:
        retained = os.fstat(report_fd)
        size = int(retained.st_size)
        actual, _tail = _digest_fd_and_tail(report_fd, size, tail_limit=0)
        result.update({"size_bytes": size, "sha256": actual})
        retained_keys = ("st_dev", "st_ino", "st_uid", "st_nlink")
        if any(
            getattr(retained, key) != getattr(created, key) for key in retained_keys
        ):
            raise RuntimeError("probe report retained descriptor drift")
        if directory_fd is not None:
            try:
                named = os.stat(
                    "sealed-import-probe-child.json",
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                named = None
            if named is not None:
                result["named_entry_present"] = True
                result["named_entry_matches_retained_fd"] = all(
                    getattr(named, key) == getattr(retained, key)
                    for key in retained_keys
                )
    except BaseException as exc:
        result["inspection_error"] = f"{type(exc).__name__}: {exc}"
    return result


def classify_probe_rejection(
    *,
    child_started: bool,
    child_exit: int | None,
    stop_reason: str,
    cleanup: Mapping[str, object] | None,
    report: Mapping[str, object],
    stdout: Mapping[str, object],
    stderr: Mapping[str, object],
    errors: Sequence[str],
) -> dict[str, object]:
    """Return stable, ordered rejection classes without changing admission."""

    classifications: list[str] = []

    def add(value: str) -> None:
        if value not in classifications:
            classifications.append(value)

    if stop_reason in {"probe_wall_deadline", "wall_deadline"} or any(
        "deadline_exceeded" in value for value in errors
    ):
        add("deadline_exceeded")
    if stop_reason.startswith(("host_pressure:", "process_group_memory_cap", "whole_launch_memory_cap")):
        add("resource_gate_breach")
    if stop_reason.startswith("signal:"):
        add("signal_received")
    if child_started and cleanup is None:
        add("cleanup_missing")
    elif cleanup is not None and (
        cleanup.get("errors") or not cleanup.get("original_pgid_asserted_empty", True)
    ):
        add("cleanup_failed")
    if not child_started:
        add("child_not_started")
    elif child_exit is None:
        add("child_exit_unobserved")
    elif child_exit != 0:
        add("child_exit_nonzero")
    if report.get("inspection_error"):
        add("report_inspection_failed")
    if not report.get("parent_created"):
        add("report_not_created")
    elif report.get("size_bytes") == 0:
        add("report_empty")
    elif not report.get("named_entry_present") and not report.get("payload_consumed"):
        add("report_named_entry_missing")
    elif report.get("named_entry_matches_retained_fd") is False:
        add("report_identity_mismatch")
    elif not report.get("payload_consumed"):
        add("report_rejected")
    elif not report.get("contract_valid"):
        add("report_contract_mismatch")
    if stdout.get("inspection_error"):
        add("stdout_inspection_failed")
    elif stdout.get("present") and int(stdout.get("size_bytes") or 0) > 0:
        add("child_stdout_nonempty")
    if stderr.get("inspection_error"):
        add("stderr_inspection_failed")
    elif stderr.get("present") and int(stderr.get("size_bytes") or 0) > 0:
        add("child_stderr_nonempty")
    if any(
        value.startswith(("capture_replay:", "external_replay:", "runtime_replay:"))
        for value in errors
    ):
        add("closure_replay_failed")
    if stop_reason == "probe_exception" or any(
        value.startswith(("RuntimeError:", "ValueError:", "OSError:"))
        for value in errors
    ):
        add("probe_exception")
    if not classifications:
        add("unspecified_rejection")
    return {
        "primary_failure_classification": classifications[0],
        "failure_classifications": classifications,
    }


def build_probe_rejection_diagnostics(
    *,
    child_started: bool,
    child_exit: int | None,
    stop_reason: str,
    cleanup: Mapping[str, object] | None,
    report: Mapping[str, object] | None,
    stdout: Mapping[str, object] | None,
    stderr: Mapping[str, object] | None,
    errors: Sequence[str],
) -> dict[str, object]:
    report_value = dict(report or probe_report_presence(None, None, None))
    stdout_value = dict(
        stdout or _absent_probe_log_diagnostic(include_tail=True)
    )
    stderr_value = dict(
        stderr or _absent_probe_log_diagnostic(include_tail=True)
    )
    classification = classify_probe_rejection(
        child_started=child_started,
        child_exit=child_exit,
        stop_reason=stop_reason,
        cleanup=cleanup,
        report=report_value,
        stdout=stdout_value,
        stderr=stderr_value,
        errors=errors,
    )
    return {
        "schema": "planora.muni-fspsx.frontier-v26.rejection-diagnostics.v1",
        "child_started": child_started,
        "child_exit": child_exit,
        "report_presence": report_value,
        "stdout": stdout_value,
        "stderr": stderr_value,
        **classification,
    }


def probe_result_payload(
    *,
    accepted: bool,
    stop_reason: str,
    child_exit: int | None,
    final_elapsed_seconds: float,
    peak_whole_memory_kib: int,
    errors: Sequence[str],
    evidence: Mapping[str, object] | None,
    rejection_diagnostics: Mapping[str, object] | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "accepted": accepted,
        "status": "PASS" if accepted else "REJECTED",
        "stop_reason": stop_reason,
        "child_exit": child_exit,
        "final_elapsed_seconds": final_elapsed_seconds,
        "peak_whole_launch_set_union_memory_kib": peak_whole_memory_kib,
        "errors": list(errors),
        "evidence": evidence,
    }
    if not accepted:
        if rejection_diagnostics is None:
            raise RuntimeError("rejected probe missing diagnostics")
        result["rejection_diagnostics"] = dict(rejection_diagnostics)
    return result


def probe_deadline_error(
    errors: list[str],
    stage: str,
    absolute_deadline: float,
    *,
    clock=None,
) -> bool:
    now = time.monotonic() if clock is None else clock()
    if now <= absolute_deadline:
        return False
    value = f"probe_deadline_exceeded:{stage}"
    if value not in errors:
        errors.append(value)
    return True


def replay_probe_closure_with_deadline(
    captures: Mapping[str, Mapping[str, Any]],
    runtime_binding: Mapping[str, Any],
    absolute_deadline: float,
    *,
    external_rows: Sequence[object],
    clock=None,
) -> tuple[str, ...]:
    """Run every closure replay, recording but not short-circuiting lateness."""

    errors: list[str] = []
    for label, row in captures.items():
        try:
            verify_sealed_capture(int(row["fd"]), row)
            verify_source_contract(row)
        except BaseException as exc:
            errors.append(f"capture_replay:{label}:{type(exc).__name__}:{exc}")
        probe_deadline_error(
            errors, f"capture_replay:{label}", absolute_deadline, clock=clock
        )
    for index, row in enumerate(external_rows):
        try:
            if not isinstance(row, Mapping):
                raise RuntimeError("external capture replay missing")
            verify_sealed_capture(int(row["fd"]), row)
            verify_source_contract(row)
        except BaseException as exc:
            errors.append(f"external_replay:{index}:{type(exc).__name__}:{exc}")
        probe_deadline_error(
            errors, f"external_replay:{index}", absolute_deadline, clock=clock
        )
    try:
        verify_runtime_bundle_end(runtime_binding)
    except BaseException as exc:
        errors.append(f"runtime_replay:{type(exc).__name__}:{exc}")
    probe_deadline_error(errors, "runtime_replay", absolute_deadline, clock=clock)
    return tuple(errors)


def unlink_published_monitor(
    run_directory_fd: int,
    name: str,
    evidence: Mapping[str, object],
) -> None:
    named = os.stat(name, dir_fd=run_directory_fd, follow_symlinks=False)
    expected = evidence.get("identity")
    if not isinstance(expected, Mapping) or file_identity(named) != expected:
        raise RuntimeError("late probe monitor identity drift before unlink")
    os.unlink(name, dir_fd=run_directory_fd)
    os.fsync(run_directory_fd)


def publish_probe_monitor_with_deadline(
    *,
    path: Path,
    value: bytes,
    run_directory: Path,
    run_directory_fd: int,
    run_identity: Mapping[str, int],
    absolute_deadline: float,
    boundary_hook=None,
    clock=None,
) -> tuple[dict[str, object] | None, str | None]:
    now = time.monotonic() if clock is None else clock()
    if now > absolute_deadline:
        return None, "probe_deadline_exceeded:before_report_publication"
    evidence = publish_monitor(
        path,
        value,
        run_directory,
        run_directory_fd,
        run_identity,
        boundary_hook=boundary_hook,
    )
    now = time.monotonic() if clock is None else clock()
    if now > absolute_deadline:
        unlink_published_monitor(run_directory_fd, path.name, evidence)
        return None, "probe_deadline_exceeded:after_report_publication"
    return evidence, None


def run_sealed_import_probe(
    expected_supervisor_sha256: str,
    expected_launcher_sha256: str,
    expected_manifest_sha256: str,
) -> int:
    """Traverse the real sealed chain for a bounded, input-free import smoke."""

    started = time.monotonic()
    absolute_deadline = started + SEALED_IMPORT_PROBE_WALL_SECONDS
    supervisor_pid = os.getpid()
    supervisor_identity = proc_stat_identity(supervisor_pid)
    if supervisor_identity is None:
        raise RuntimeError("supervisor identity unavailable before probe capture")
    verify_external_evidence(
        SEALED_SELF_EVIDENCE, expected_supervisor_sha256, "supervisor"
    )
    verify_external_evidence(
        SEALED_LAUNCHER_EVIDENCE, expected_launcher_sha256, "launcher"
    )
    verify_external_evidence(
        PRE_SUPERVISOR_STDLIB_EVIDENCE,
        EXPECTED_STDLIB_MANIFEST_SHA256,
        "pre-supervisor stdlib manifest",
    )
    manifest, _ = load_freeze_manifest(expected_manifest_sha256, external=True)
    validate_manifest_contract(manifest)
    baseline = host_sample()
    if time.monotonic() > absolute_deadline:
        rejection = build_probe_rejection_diagnostics(
            child_started=False,
            child_exit=None,
            stop_reason="probe_wall_deadline",
            cleanup=None,
            report=None,
            stdout=None,
            stderr=None,
            errors=("probe_deadline_exceeded:before_probe_child",),
        )
        print(json.dumps({
            "schema": "planora.muni-fspsx.frontier-v26.sealed-import-probe-gate.v1",
            "status": "NO_GO_ABSOLUTE_DEADLINE",
            "probe_child_started": False,
            "official_input_opened": False,
            "solve_called": False,
            "rejection_diagnostics": rejection,
        }, sort_keys=True), flush=True)
        return 2
    if baseline["mem_available_kib"] < LAUNCH_MEMAVAILABLE_FLOOR_KIB:
        rejection = build_probe_rejection_diagnostics(
            child_started=False,
            child_exit=None,
            stop_reason="host_pressure:launch_memavailable_floor",
            cleanup=None,
            report=None,
            stdout=None,
            stderr=None,
            errors=(),
        )
        print(json.dumps({
            "schema": "planora.muni-fspsx.frontier-v26.sealed-import-probe-gate.v1",
            "status": "NO_GO_RESOURCE_GATE",
            "chain_traversed": ["bootstrap", "launcher", "supervisor"],
            "probe_child_started": False,
            "official_input_opened": False,
            "progress_opened": False,
            "checkpoint_opened": False,
            "solve_called": False,
            "required_memavailable_kib": LAUNCH_MEMAVAILABLE_FLOOR_KIB,
            "observed_memavailable_kib": baseline["mem_available_kib"],
            "rejection_diagnostics": rejection,
        }, sort_keys=True), flush=True)
        return 2

    stop_signals = STOP_SIGNALS
    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)
    previous_handlers = {item: signal.getsignal(item) for item in stop_signals}
    signal_state = {"number": None}

    def receive(signum, _frame) -> None:
        signal_state["number"] = int(signum)

    for item in stop_signals:
        signal.signal(item, receive)
    process: subprocess.Popen[bytes] | None = None
    generation: ProcessGroupGeneration | None = None
    pgid: int | None = None
    pidfd: int | None = None
    report_fd: int | None = None
    report_created: os.stat_result | None = None
    stdout_fd: int | None = None
    stderr_fd: int | None = None
    stdout_created: os.stat_result | None = None
    stderr_created: os.stat_result | None = None
    run_directory_fd: int | None = None
    runtime_initial_fd: int | None = None
    run_directory: Path | None = None
    runtime_directory: Path | None = None
    run_identity: dict[str, int] | None = None
    sealed_fds: list[int] = []
    captures: dict[str, dict[str, Any]] = {}
    runtime_binding: dict[str, Any] | None = None
    sealed_storage_kib = 0
    cleanup: dict[str, object] | None = None
    errors: list[str] = []
    samples: list[dict[str, object]] = []
    stop_reason = "normal_exit"
    child_exit: int | None = None
    peak_group = peak_supervisor = peak_whole = 0
    child_report: dict[str, object] | None = None
    child_report_evidence: dict[str, object] | None = None
    child_report_contract_valid = False
    report_diagnostic: dict[str, object] | None = None
    stdout_diagnostic: dict[str, object] | None = None
    stderr_diagnostic: dict[str, object] | None = None
    reaped_zero_proof: tuple[int, tuple[int, int, int], int] | None = None

    def record_identity_pinned_sample(stage: str) -> str | None:
        nonlocal peak_group, peak_supervisor, peak_whole, stop_reason
        if generation is None:
            raise RuntimeError(f"probe generation absent at telemetry stage {stage}")
        observed, decision = identity_pinned_probe_telemetry_sample(
            generation,
            supervisor_pid=supervisor_pid,
            supervisor_identity=supervisor_identity,
            started=started,
            stage=stage,
            received_signal=signal_state["number"],
            sealed_storage_kib=sealed_storage_kib,
            reaped_zero_proof=reaped_zero_proof,
        )
        group_memory = int(observed["group_memory_kib"])
        own_memory = int(observed["supervisor_memory_kib"])
        whole_memory = int(observed["whole_launch_set_union_memory_kib"])
        peak_group = max(peak_group, group_memory)
        peak_supervisor = max(peak_supervisor, own_memory)
        peak_whole = max(peak_whole, whole_memory)
        samples.append(observed)
        if decision is not None:
            value = f"probe_resource_decision:{stage}:{decision}"
            if value not in errors:
                errors.append(value)
            if stop_reason == "normal_exit":
                stop_reason = decision
        return decision

    try:
        verify_probe_manifest_files(manifest)
        if signal.sigpending().intersection(stop_signals):
            raise RuntimeError("stop signal pending before probe mutation")
        run_id = configured_run_id()
        run_directory = Path(
            f"/tmp/planora-muni-fspsx-frontier-v26-probe-{run_id}"
        )
        os.mkdir(run_directory, 0o700)
        run_directory_fd = os.open(
            run_directory,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        run_identity = file_identity(os.fstat(run_directory_fd))
        verify_run_directory_binding(run_directory, run_directory_fd, run_identity)
        rows = manifest_files(manifest)
        capture_sources = {
            "runner": (RUNNER, str(rows["runner"]["sha256"])),
            "benchmarks": (Path(str(rows["benchmarks"]["path"])), str(rows["benchmarks"]["sha256"])),
            "semantic": (Path(str(rows["semantic"]["path"])), str(rows["semantic"]["sha256"])),
            "preprocessing": (Path(str(rows["preprocessing"]["path"])), str(rows["preprocessing"]["sha256"])),
            "frontier": (Path(str(rows["frontier"]["path"])), str(rows["frontier"]["sha256"])),
            "room_oracle": (Path(str(rows["room_oracle"]["path"])), str(rows["room_oracle"]["sha256"])),
            "generic_validator": (Path(str(rows["generic_validator"]["path"])), str(rows["generic_validator"]["sha256"])),
            "fairness_certificate": (Path(str(rows["fairness_certificate"]["path"])), str(rows["fairness_certificate"]["sha256"])),
            "stdlib_manifest": (STDLIB_MANIFEST, EXPECTED_STDLIB_MANIFEST_SHA256),
            "python_binary": (PYTHON, str(rows["python_binary"]["sha256"])),
            **{label: (path, str(rows[label]["sha256"])) for label, path in PLANORA_FRESH_MODULES.items()},
            **{label: (path, str(rows[label]["sha256"])) for label, path in RUNTIME_RECORDS.items()},
        }
        pass_fds = [run_directory_fd]
        for label, (path, expected) in capture_sources.items():
            descriptor, row = _stream_capture(path, expected, label)
            captures[label] = row
            sealed_fds.append(descriptor)
            pass_fds.append(descriptor)
        runtime_directory = Path(
            f"/tmp/planora-muni-fspsx-frontier-v26-probe-runtime-{run_id}"
        )
        os.mkdir(runtime_directory, 0o700)
        runtime_initial_fd = os.open(
            runtime_directory,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        runtime_root_fd, runtime_manifest_fd, runtime_file_fds, runtime_binding, _ = build_runtime_bundle(
            runtime_root_fd=runtime_initial_fd, captures=captures
        )
        sealed_storage_kib = int(runtime_binding["sealed_page_rounded_kib"])
        os.close(runtime_initial_fd)
        runtime_initial_fd = None
        sealed_fds.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        pass_fds.extend((runtime_root_fd, runtime_manifest_fd, *runtime_file_fds))
        pre_child_values = identity_pinned_process_memory(
            supervisor_pid, supervisor_identity
        )
        pre_child_memory = (
            int(pre_child_values["VmRSS"]) + int(pre_child_values["VmSwap"])
        )
        peak_supervisor = max(peak_supervisor, pre_child_memory)
        pre_child_whole_memory = pre_child_memory + sealed_storage_kib
        peak_whole = max(peak_whole, pre_child_whole_memory)
        if pre_child_whole_memory > WHOLE_LAUNCH_MEMORY_CAP_KIB:
            raise RuntimeError("whole launch memory cap exceeded before probe child")
        if time.monotonic() > absolute_deadline:
            raise RuntimeError("probe wall deadline exceeded before child")
        report_fd = os.open(
            "sealed-import-probe-child.json",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=run_directory_fd,
        )
        report_created = os.fstat(report_fd)
        stdout_fd = os.open(
            "probe.stdout.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400, dir_fd=run_directory_fd,
        )
        stdout_created = os.fstat(stdout_fd)
        stderr_fd = os.open(
            "probe.stderr.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400, dir_fd=run_directory_fd,
        )
        stderr_created = os.fstat(stderr_fd)
        pass_fds.extend((report_fd, stdout_fd, stderr_fd))
        source_evidence = {
            "benchmarks": captures["benchmarks"],
            "benchmarks.itc2019": captures["semantic"],
            "benchmarks.itc2019_preprocessing": captures["preprocessing"],
            "benchmarks.itc2019_frontier_joint": captures["frontier"],
            "benchmarks.itc2019_room_oracle": captures["room_oracle"],
            "generic_validator": captures["generic_validator"],
            "fairness_certificate": captures["fairness_certificate"],
            **{f"benchmarks.{label}": captures[label] for label in PLANORA_FRESH_MODULES},
        }
        command = [
            f"/proc/self/fd/{captures['python_binary']['fd']}",
            "-I", "-S", "-B", "-X", f"pycache_prefix=/proc/self/fd/{run_directory_fd}/.pycache-disabled",
            "-c", RUNNER_LOADER,
            str(captures["runner"]["fd"]), str(rows["runner"]["sha256"]),
            json.dumps(source_evidence, sort_keys=True),
            str(runtime_root_fd), str(captures["stdlib_manifest"]["fd"]),
            EXPECTED_STDLIB_MANIFEST_SHA256,
            "--sealed-import-probe",
            "--probe-report-fd", str(report_fd),
            "--probe-report-device", str(report_created.st_dev),
            "--probe-report-inode", str(report_created.st_ino),
            "--probe-report-uid", str(report_created.st_uid),
        ]
        environment = sanitized_child_environment(
            run_directory=run_directory,
            run_directory_fd=run_directory_fd,
            captures=captures,
            runtime_binding=runtime_binding,
        )
        parent_pid = os.getpid()
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=stdout_fd, stderr=stderr_fd,
            close_fds=True, pass_fds=tuple(pass_fds), env=environment,
            start_new_session=True,
            preexec_fn=lambda: arm_parent_death_signal(parent_pid),
        )
        pgid = process.pid
        pgid, _, pidfd, generation = admit_spawned_process_group(process, pgid, None)
        if hasattr(os, "pidfd_open"):
            try:
                pidfd = os.pidfd_open(process.pid, 0)
            except OSError:
                pidfd = None
        os.close(stdout_fd)
        stdout_fd = None
        os.close(stderr_fd)
        stderr_fd = None
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        while True:
            refresh_process_group_generation(generation)
            decision = record_identity_pinned_sample("child_monitor")
            if decision is not None:
                break
            if process.poll() is not None:
                break
            remaining = max(0.0, absolute_deadline - time.monotonic())
            time.sleep(min(POLL_SECONDS, remaining))
        cleanup = stop_process_group(process, generation, pidfd)
        reaped_zero_proof = successful_reaped_leader_zero_memory_proof(
            process, generation
        )
        probe_deadline_error(errors, "primary_cleanup", absolute_deadline)
        record_identity_pinned_sample("after_primary_cleanup")
        child_exit = process.returncode
        if child_exit is None:
            errors.append("child_exit_unobserved_after_cleanup")
        if cleanup.get("errors"):
            errors.extend(f"cleanup:{value}" for value in cleanup["errors"])
        if process_group_pids(pgid):
            errors.append("original_process_group_not_empty")
        hook = PROBE_REPORT_POST_CHILD_TEST_HOOK
        if hook is not None:
            hook(run_directory, run_directory_fd, report_fd)
        stdout_diagnostic = capture_probe_log_diagnostic(
            run_directory_fd,
            "probe.stdout.log",
            stdout_created,
            include_tail=True,
        )
        stderr_diagnostic = capture_probe_log_diagnostic(
            run_directory_fd,
            "probe.stderr.log",
            stderr_created,
            include_tail=True,
        )
        if stdout_diagnostic.get("inspection_error"):
            errors.append("probe_stdout_diagnostic_inspection_failed")
        elif int(stdout_diagnostic.get("size_bytes") or 0) > 0:
            errors.append("probe_child_stdout_not_empty")
        if stderr_diagnostic.get("inspection_error"):
            errors.append("probe_stderr_diagnostic_inspection_failed")
        elif int(stderr_diagnostic.get("size_bytes") or 0) > 0:
            errors.append("probe_child_stderr_not_empty")
        report_diagnostic = probe_report_presence(
            run_directory_fd, report_fd, report_created
        )
        probe_deadline_error(errors, "diagnostic_capture", absolute_deadline)
        probe_deadline_error(errors, "before_report_consumption", absolute_deadline)
        child_report, child_report_evidence = consume_probe_report(
            run_directory_fd, report_fd, report_created
        )
        report_diagnostic["payload_consumed"] = True
        probe_deadline_error(errors, "report_consumption", absolute_deadline)
        record_identity_pinned_sample("after_report_consumption")
        expected_child = {
            "schema": "planora.muni-fspsx.frontier-v26.sealed-import-probe-child.v1",
            "status": "PASS",
            "input_mode": "NONE",
            "official_input_opened": False,
            "progress_opened": False,
            "checkpoint_opened": False,
            "solve_called": False,
            "compile_warnings": {
                "schema": "planora.muni-fspsx.frontier-v26.compile-warnings.v1",
                "status": "ADMITTED",
                "count": 2,
                "category": "DeprecationWarning",
                "message": CP_MODEL_COMPILE_WARNING_MESSAGE,
                "source_relative_path": "ortools/sat/python/cp_model.py",
                "source_sha256": CP_MODEL_SOURCE_SHA256,
                "child_stderr_bytes": 0,
            },
        }
        child_report_contract_valid = not any(
            child_report.get(key) != value for key, value in expected_child.items()
        )
        report_diagnostic["contract_valid"] = child_report_contract_valid
        if not child_report_contract_valid:
            errors.append("probe_child_report_contract_rejected")
        errors.extend(replay_probe_closure_with_deadline(
            captures,
            runtime_binding,
            absolute_deadline,
            external_rows=(
                SEALED_SELF_EVIDENCE,
                SEALED_LAUNCHER_EVIDENCE,
                SEALED_MANIFEST_EVIDENCE,
            ),
        ))
        record_identity_pinned_sample("after_closure_replay")
    except BaseException as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        if stop_reason == "normal_exit":
            stop_reason = "probe_exception"
    finally:
        signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)
        if process is not None and generation is not None:
            try:
                final_cleanup = stop_process_group(process, generation, pidfd)
                child_exit = process.returncode
                if reaped_zero_proof is None:
                    reaped_zero_proof = successful_reaped_leader_zero_memory_proof(
                        process, generation
                    )
                if final_cleanup.get("errors"):
                    errors.extend(f"final_cleanup:{value}" for value in final_cleanup["errors"])
            except BaseException as exc:
                errors.append(f"final_cleanup:{type(exc).__name__}:{exc}")
            probe_deadline_error(errors, "final_cleanup", absolute_deadline)
            try:
                record_identity_pinned_sample("after_final_cleanup")
            except BaseException as exc:
                errors.append(
                    f"final_cleanup_memory_sample:{type(exc).__name__}:{exc}"
                )
        if pidfd is not None:
            try:
                os.close(pidfd)
            except OSError:
                pass
        if runtime_initial_fd is not None:
            os.close(runtime_initial_fd)
        for stream_name, stream_fd in (("stdout", stdout_fd), ("stderr", stderr_fd)):
            if stream_fd is not None:
                try:
                    os.close(stream_fd)
                except OSError as exc:
                    errors.append(
                        f"probe_{stream_name}_parent_close:{type(exc).__name__}:{exc}"
                    )
        for fd in sealed_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        sealed_storage_kib = 0
        for row in captures.values():
            watch_fd = row.get("source_watch_fd")
            if type(watch_fd) is int:
                try:
                    os.close(watch_fd)
                except OSError:
                    pass

    if run_directory_fd is not None:
        if stdout_diagnostic is None:
            stdout_diagnostic = capture_probe_log_diagnostic(
                run_directory_fd,
                "probe.stdout.log",
                stdout_created,
                include_tail=True,
            )
        if stderr_diagnostic is None:
            stderr_diagnostic = capture_probe_log_diagnostic(
                run_directory_fd,
                "probe.stderr.log",
                stderr_created,
                include_tail=True,
            )
        if report_diagnostic is None:
            report_diagnostic = probe_report_presence(
                run_directory_fd, report_fd, report_created
            )
        report_diagnostic["payload_consumed"] = child_report is not None
        report_diagnostic["contract_valid"] = child_report_contract_valid
    if generation is not None:
        try:
            record_identity_pinned_sample("pre_publication")
        except BaseException as exc:
            errors.append(f"pre_publication_memory_sample:{type(exc).__name__}:{exc}")
    final_elapsed = time.monotonic() - started
    accepted = sealed_import_probe_accepted(
        errors=errors,
        stop_reason=stop_reason,
        child_exit=child_exit,
        cleanup=cleanup,
        child_report=child_report,
        final_elapsed_seconds=final_elapsed,
        peak_whole_memory_kib=peak_whole,
    )
    evidence = None
    if accepted and run_directory is not None and run_directory_fd is not None and run_identity is not None:
        monitor = {
            "schema": "planora.muni-fspsx.frontier-v26.sealed-import-probe.v1",
            "status": "PASS",
            "chain_traversed": ["bootstrap", "launcher", "supervisor", "probe_child"],
            "official_input_opened": False,
            "progress_opened": False,
            "checkpoint_opened": False,
            "solve_called": False,
            "wall_limit_seconds": SEALED_IMPORT_PROBE_WALL_SECONDS,
            "absolute_deadline_monotonic": absolute_deadline,
            "pre_publication_elapsed_seconds": final_elapsed,
            "whole_launch_memory_cap_kib": WHOLE_LAUNCH_MEMORY_CAP_KIB,
            "peak_group_memory_kib": peak_group,
            "peak_supervisor_memory_kib": peak_supervisor,
            "peak_whole_launch_set_union_memory_kib": peak_whole,
            "samples": samples,
            "cleanup": cleanup,
            "child_report": child_report_evidence,
        }
        value = (json.dumps(monitor, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        try:
            evidence, publication_error = publish_probe_monitor_with_deadline(
                path=run_directory / "sealed-import-probe-report.json",
                value=value,
                run_directory=run_directory,
                run_directory_fd=run_directory_fd,
                run_identity=run_identity,
                absolute_deadline=absolute_deadline,
            )
        except BaseException as exc:
            evidence = None
            publication_error = (
                f"probe_report_publication:{type(exc).__name__}:{exc}"
            )
        if publication_error is not None:
            errors.append(publication_error)
            accepted = False
        final_elapsed = time.monotonic() - started
        if final_elapsed > SEALED_IMPORT_PROBE_WALL_SECONDS:
            if evidence is not None:
                unlink_published_monitor(
                    run_directory_fd,
                    "sealed-import-probe-report.json",
                    evidence,
                )
                evidence = None
            errors.append("probe_deadline_exceeded:final_acceptance")
            accepted = False
        if peak_whole > WHOLE_LAUNCH_MEMORY_CAP_KIB:
            if evidence is not None:
                unlink_published_monitor(
                    run_directory_fd,
                    "sealed-import-probe-report.json",
                    evidence,
                )
                evidence = None
            errors.append("whole_launch_memory_cap:final_acceptance")
            accepted = False
    rejection_diagnostics = None
    if not accepted:
        rejection_diagnostics = build_probe_rejection_diagnostics(
            child_started=process is not None,
            child_exit=child_exit,
            stop_reason=stop_reason,
            cleanup=cleanup,
            report=report_diagnostic,
            stdout=stdout_diagnostic,
            stderr=stderr_diagnostic,
            errors=errors,
        )
    result = probe_result_payload(
        accepted=accepted,
        stop_reason=stop_reason,
        child_exit=child_exit,
        final_elapsed_seconds=final_elapsed,
        peak_whole_memory_kib=peak_whole,
        errors=errors,
        evidence=evidence,
        rejection_diagnostics=rejection_diagnostics,
    )
    if report_fd is not None:
        os.close(report_fd)
    if run_directory_fd is not None:
        os.close(run_directory_fd)
    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
    for item, handler in previous_handlers.items():
        signal.signal(item, handler)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if accepted else 2


def dry_run(expected_manifest_sha256: str | None) -> dict[str, object]:
    errors: list[str] = []
    observed: dict[str, object] = {}
    memory = host_sample()
    if memory["mem_available_kib"] < LAUNCH_MEMAVAILABLE_FLOOR_KIB:
        errors.append(
            "launch host MemAvailable floor is not currently satisfied: "
            f"{memory['mem_available_kib']} < {LAUNCH_MEMAVAILABLE_FLOOR_KIB} KiB"
        )
    try:
        manifest_bytes, _identity = capture_regular(FREEZE_MANIFEST)
        actual_manifest = digest_bytes(manifest_bytes)
        if expected_manifest_sha256 is not None and actual_manifest != expected_manifest_sha256:
            raise RuntimeError("freeze manifest hash differs from explicit dry-run pin")
        manifest, _ = load_freeze_manifest(actual_manifest, external=False)
        validate_manifest_contract(manifest)
        observed = verify_manifest_files(manifest, dry=True)
    except BaseException as exc:
        actual_manifest = None
        errors.append(f"{type(exc).__name__}: {exc}")
    run_directory = Path(f"/tmp/planora-muni-fspsx-frontier-v26-{configured_run_id()}")
    if os.path.lexists(run_directory):
        errors.append(f"planned run directory exists: {run_directory}")
    return {
        "schema": "planora.muni-fspsx.frontier-v26.supervisor-dry.v1",
        "status": "READY" if not errors else "REJECTED",
        "children_started": False,
        "artifacts_written": False,
        "official_instance_opened": False,
        "official_instance_check": "pinned_path_regular_stat_and_size_only",
        "host_sample": memory,
        "launch_memory_ready": (
            memory["mem_available_kib"] >= LAUNCH_MEMAVAILABLE_FLOOR_KIB
        ),
        "freeze_manifest_sha256": actual_manifest,
        "supervisor_sha256": digest(SUPERVISOR),
        "launcher_sha256": digest(LAUNCHER),
        "planned_run_directory": str(run_directory),
        "observed_files": observed,
        "errors": errors,
    }


def pre_child_manifest_contract_check(
    expected_manifest_sha256: str,
) -> dict[str, object]:
    """Validate the frozen manifest and fairness pin without starting a child."""

    manifest_bytes, _identity = capture_regular(FREEZE_MANIFEST)
    actual_manifest_sha256 = digest_bytes(manifest_bytes)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "freeze manifest hash differs from explicit pre-child pin"
        )
    manifest, _ = load_freeze_manifest(actual_manifest_sha256, external=False)
    validate_manifest_contract(manifest)
    fairness = manifest["fairness_provenance"]
    rows = manifest_files(manifest)
    certificate_row = rows["fairness_certificate"]
    return {
        "schema": (
            "planora.muni-fspsx.frontier-v26."
            "pre-child-manifest-contract.v1"
        ),
        "status": "PASS",
        "children_started": False,
        "artifacts_written": False,
        "official_input_opened": False,
        "progress_or_checkpoint_opened": False,
        "solver_called": False,
        "freeze_manifest_sha256": actual_manifest_sha256,
        "fairness_certificate_path": certificate_row["path"],
        "fairness_certificate_sha256": certificate_row["sha256"],
        "fairness_dependency_order": [
            "derivation_audit",
            "source_artifacts",
            "freeze_manifest",
            "implementation_certificate",
        ],
        "implementation_certificate_is_manifest_dependency": False,
        "derivation_audit_path_matches_provenance": (
            certificate_row["path"] == fairness["derivation_audit_path"]
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--launch", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--sealed-import-probe", action="store_true")
    mode.add_argument("--pre-child-manifest-contract-check", action="store_true")
    parser.add_argument("--expected-supervisor-sha256")
    parser.add_argument("--expected-launcher-sha256")
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args(argv)
    if args.pre_child_manifest_contract_check:
        if args.expected_manifest_sha256 is None:
            parser.error(
                "--pre-child-manifest-contract-check requires the manifest hash"
            )
        payload = pre_child_manifest_contract_check(
            args.expected_manifest_sha256
        )
        print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
        return 0
    if args.sealed_import_probe:
        if not all((args.expected_supervisor_sha256, args.expected_launcher_sha256, args.expected_manifest_sha256)):
            parser.error("--sealed-import-probe requires supervisor, launcher, and manifest hashes")
        return run_sealed_import_probe(
            args.expected_supervisor_sha256,
            args.expected_launcher_sha256,
            args.expected_manifest_sha256,
        )
    if not args.launch:
        if args.dry_run:
            payload = dry_run(args.expected_manifest_sha256)
            print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
            return 0 if payload["status"] == "READY" else 2
        print(json.dumps({
            "schema": "planora.muni-fspsx.frontier-v26.supervisor-gate.v1",
            "status": "NOT_LAUNCHED",
            "children_started": False,
            "artifacts_written": False,
            "required_flag": "--launch",
        }, sort_keys=True))
        return 0
    if not all((args.expected_supervisor_sha256, args.expected_launcher_sha256, args.expected_manifest_sha256)):
        parser.error("--launch requires supervisor, launcher, and manifest hashes")
    return run_launch(
        args.expected_supervisor_sha256,
        args.expected_launcher_sha256,
        args.expected_manifest_sha256,
    )


if __name__ == "__main__":
    raise SystemExit(main())
