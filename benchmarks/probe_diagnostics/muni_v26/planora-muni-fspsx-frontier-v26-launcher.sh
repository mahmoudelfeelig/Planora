#!/bin/bash
set -euo pipefail

if [[ "${1-}" != "--launch" && "${1-}" != "--dry-run" && "${1-}" != "--sealed-import-probe" ]]; then
  printf '%s\n' '{"schema":"planora.muni-fspsx.frontier-v26.launcher-gate.v1","status":"NOT_LAUNCHED","children_started":false,"artifacts_written":false,"required_flag":"--launch","pinned_interpreter_bootstrap_required":true}'
  exit 0
fi

exec /usr/bin/env -i \
  PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC \
  /usr/bin/python3.12 -I -S -B -c '
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import sys

PYTHON_SHA256 = "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273"
REQUIRED = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
IN_MASK = 0x00000002 | 0x00000004 | 0x00000008 | 0x00000400 | 0x00000800
LIBC = ctypes.CDLL(None, use_errno=True)
CHAIN_ROOT = "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/muni_v26"
TCB_PATH = CHAIN_ROOT + "/planora-muni-fspsx-frontier-v26-minimal-tcb.sha256"
TCB_SHA256 = "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea"
STDLIB_PATH = CHAIN_ROOT + "/planora-muni-fspsx-frontier-v26-stdlib.sha256"
STDLIB_SHA256 = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327"

def identity(row):
    return (
        int(row.st_dev), int(row.st_ino), int(row.st_size),
        stat.S_IFMT(row.st_mode), stat.S_IMODE(row.st_mode),
        int(row.st_uid), int(row.st_nlink), int(row.st_mtime_ns),
        int(row.st_ctime_ns),
    )

def read_fd(descriptor):
    before = os.fstat(descriptor)
    chunks = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError("bootstrap capture ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if identity(after) != identity(before):
        raise RuntimeError("bootstrap descriptor changed during read")
    return b"".join(chunks)

root_read_only = False
with open("/proc/self/mountinfo", encoding="utf-8") as mountinfo:
    for line in mountinfo:
        fields = line.split(" - ", 1)[0].split()
        if len(fields) >= 6 and fields[4] == "/" and "ro" in fields[5].split(","):
            root_read_only = True
if not root_read_only:
    raise RuntimeError("launcher minimal TCB filesystem is not read-only")
tcb_fd = os.open(TCB_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    tcb_raw = read_fd(tcb_fd)
finally:
    os.close(tcb_fd)
if hashlib.sha256(tcb_raw).hexdigest() != TCB_SHA256:
    raise RuntimeError("launcher minimal TCB manifest drift")
tcb = {}
for line in tcb_raw.decode("utf-8").splitlines():
    file_hash, file_path = line.split("  ", 1)
    if file_path in tcb:
        raise RuntimeError("launcher duplicate minimal TCB path")
    tcb[file_path] = file_hash
for module in tuple(sys.modules.values()):
    file_path = getattr(module, "__file__", None)
    if not isinstance(file_path, str) or file_path.startswith("<frozen "):
        continue
    if os.path.realpath(file_path) != file_path or file_path not in tcb:
        raise RuntimeError("launcher module outside minimal TCB")
    current = file_path
    while True:
        ownership = os.stat(current, follow_symlinks=False)
        if (
            ownership.st_uid != 65534
            or ownership.st_gid != 65534
            or stat.S_IMODE(ownership.st_mode) & 0o022
        ):
            raise RuntimeError("launcher minimal TCB permissions rejected")
        if current == "/":
            break
        current = os.path.dirname(current)
    descriptor = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        module_raw = read_fd(descriptor)
    finally:
        os.close(descriptor)
    if hashlib.sha256(module_raw).hexdigest() != tcb[file_path]:
        raise RuntimeError("launcher minimal TCB module drift")

import argparse

def capture(path_value, expected, label):
    path = Path(path_value)
    watch_fd = int(LIBC.inotify_init1(getattr(os, "O_NONBLOCK", 0x800)))
    if watch_fd < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(path))
    watch_descriptor = int(
        LIBC.inotify_add_watch(
            watch_fd, ctypes.c_char_p(os.fsencode(path)), ctypes.c_uint32(IN_MASK)
        )
    )
    if watch_descriptor < 0:
        code = ctypes.get_errno()
        os.close(watch_fd)
        raise OSError(code, os.strerror(code), str(path))
    parent_before = path.parent.lstat()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError(f"{label} source contract rejected")
        raw = read_fd(descriptor)
        after = os.fstat(descriptor)
        named = path.lstat()
        parent_after = path.parent.lstat()
    finally:
        os.close(descriptor)
    if identity(after) != identity(named) or (
        parent_before.st_dev, parent_before.st_ino
    ) != (parent_after.st_dev, parent_after.st_ino):
        raise RuntimeError(f"{label} named source drift")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 drift: {actual} != {expected}")
    sealed = os.memfd_create(
        f"planora-muni-v26-{label}",
        getattr(os, "MFD_ALLOW_SEALING", 0x0002),
    )
    view = memoryview(raw)
    while view:
        written = os.write(sealed, view)
        if written <= 0:
            raise RuntimeError("bootstrap memfd stopped accepting bytes")
        view = view[written:]
    os.fchmod(sealed, 0o400)
    fcntl.fcntl(sealed, fcntl.F_ADD_SEALS, REQUIRED)
    seals = int(fcntl.fcntl(sealed, fcntl.F_GET_SEALS))
    if seals & REQUIRED != REQUIRED or read_fd(sealed) != raw:
        raise RuntimeError(f"{label} memfd sealing failed")
    sealed_row = os.fstat(sealed)
    return raw, {
        "label": label,
        "path": str(path),
        "fd": sealed,
        "sha256": actual,
        "expected_sha256": expected,
        "device": int(sealed_row.st_dev),
        "inode": int(sealed_row.st_ino),
        "size": int(sealed_row.st_size),
        "file_type": stat.S_IFMT(sealed_row.st_mode),
        "mode": stat.S_IMODE(sealed_row.st_mode),
        "uid": int(sealed_row.st_uid),
        "nlink": int(sealed_row.st_nlink),
        "seals": seals,
        "required_seals": REQUIRED,
        "source_identity": list(identity(after)[:7]),
        "source_mutation_clock": [int(after.st_mtime_ns), int(after.st_ctime_ns)],
        "source_parent_identity": [
            int(parent_after.st_dev), int(parent_after.st_ino),
            stat.S_IMODE(parent_after.st_mode), int(parent_after.st_uid),
        ],
        "source_watch_fd": watch_fd,
        "source_watch_descriptor": watch_descriptor,
        "source_watch_mask": IN_MASK,
        "transport": "sealed_memfd",
    }

launcher_path = sys.argv[1]
forwarded = sys.argv[2:]
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--launch", action="store_true")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--sealed-import-probe", action="store_true")
parser.add_argument("--expected-launcher-sha256", required=True)
parser.add_argument("--expected-supervisor-sha256", required=True)
parser.add_argument("--expected-manifest-sha256", required=True)
parser.add_argument("--bootstrap-launcher-evidence", required=True)
args = parser.parse_args(forwarded)
if sum((args.launch, args.dry_run, args.sealed_import_probe)) != 1:
    raise RuntimeError("exactly one execution mode is required")
python_fd = os.open("/proc/self/exe", os.O_RDONLY)
try:
    python_raw = read_fd(python_fd)
finally:
    os.close(python_fd)
if (
    hashlib.sha256(python_raw).hexdigest() != PYTHON_SHA256
    or not sys.flags.isolated
    or not sys.flags.no_site
    or not sys.dont_write_bytecode
    or Path(sys.executable).resolve() != Path("/usr/bin/python3.12").resolve()
):
    raise RuntimeError("pinned interpreter bootstrap rejected")
stdlib_raw, stdlib_evidence = capture(
    STDLIB_PATH, STDLIB_SHA256, "stdlib_manifest"
)
stdlib = {}
for line in stdlib_raw.decode("utf-8").splitlines():
    file_hash, file_path = line.split("  ", 1)
    if file_path in stdlib or not file_path.startswith("/usr/lib/python3.12/"):
        raise RuntimeError("full stdlib manifest row rejected")
    stdlib[file_path] = file_hash
for file_path, file_hash in stdlib.items():
    current = file_path
    while True:
        ownership = os.stat(current, follow_symlinks=False)
        if (
            ownership.st_uid != 65534
            or ownership.st_gid != 65534
            or stat.S_IMODE(ownership.st_mode) & 0o022
        ):
            raise RuntimeError("full stdlib permissions rejected")
        if current == "/":
            break
        current = os.path.dirname(current)
    descriptor = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        module_raw = read_fd(descriptor)
    finally:
        os.close(descriptor)
    if hashlib.sha256(module_raw).hexdigest() != file_hash:
        raise RuntimeError("full stdlib file drift")
launcher = __import__("json").loads(args.bootstrap_launcher_evidence)
launcher_fd = launcher.get("fd")
if type(launcher_fd) is not int or launcher_fd < 3:
    raise RuntimeError("bootstrap launcher descriptor rejected")
launcher_raw = read_fd(launcher_fd)
launcher_stat = os.fstat(launcher_fd)
launcher_seals = int(fcntl.fcntl(launcher_fd, fcntl.F_GET_SEALS))
executed_stat = os.stat(launcher_path)
if (
    hashlib.sha256(launcher_raw).hexdigest() != args.expected_launcher_sha256
    or launcher.get("sha256") != args.expected_launcher_sha256
    or launcher.get("expected_sha256") != args.expected_launcher_sha256
    or launcher_seals & REQUIRED != REQUIRED
    or (int(executed_stat.st_dev), int(executed_stat.st_ino))
       != (int(launcher_stat.st_dev), int(launcher_stat.st_ino))
    or launcher.get("device") != int(launcher_stat.st_dev)
    or launcher.get("inode") != int(launcher_stat.st_ino)
    or launcher.get("size") != int(launcher_stat.st_size)
    or launcher.get("transport") != "sealed_memfd_before_launcher_execution"
):
    raise RuntimeError("pre-execution launcher evidence rejected")
supervisor_path = CHAIN_ROOT + "/planora-muni-fspsx-frontier-v26-supervisor.py"
manifest_path = CHAIN_ROOT + "/planora-muni-fspsx-frontier-v26-freeze-manifest.json"
supervisor_raw, supervisor = capture(
    supervisor_path, args.expected_supervisor_sha256, "supervisor"
)
manifest_raw, manifest = capture(
    manifest_path, args.expected_manifest_sha256, "freeze_manifest"
)
sys.argv = [
    "sealed:muni-v26-supervisor",
    (
        "--launch" if args.launch
        else "--sealed-import-probe" if args.sealed_import_probe
        else "--dry-run"
    ),
    "--expected-supervisor-sha256", args.expected_supervisor_sha256,
    "--expected-launcher-sha256", args.expected_launcher_sha256,
    "--expected-manifest-sha256", args.expected_manifest_sha256,
]
scope = {
    "__name__": "__main__",
    "__package__": None,
    "__file__": "sealed:muni-v26-supervisor",
    "__planora_supervisor_evidence__": supervisor,
    "__planora_launcher_evidence__": launcher,
    "__planora_freeze_manifest_evidence__": manifest,
    "__planora_pre_supervisor_stdlib_evidence__": stdlib_evidence,
}
exec(compile(supervisor_raw, "sealed:muni-v26-supervisor", "exec", dont_inherit=True), scope)
' "$0" "$@"
