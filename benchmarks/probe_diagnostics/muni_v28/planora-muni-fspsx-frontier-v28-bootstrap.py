#!/usr/bin/env python3
"""Externally pinned trust root for the MUNI frontier v28 diagnostic launcher.

This file is the explicit out-of-band trust root.  Its SHA-256 must be checked
by the independent reviewer before execution.  It opens, hashes, watches, and
seals the launcher as data before any launcher byte is interpreted.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence


PYTHON_SHA256 = "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273"
CHAIN_ROOT = Path(
    "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/muni_v28"
)
LAUNCHER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-launcher.sh"
ALL_SEALS = 0x0F
IN_SOURCE_MUTATION_MASK = (
    0x00000002 | 0x00000004 | 0x00000008 | 0x00000400 | 0x00000800
)
IN_NONBLOCK = getattr(os, "O_NONBLOCK", 0x800)
IN_CLOEXEC = getattr(os, "O_CLOEXEC", 0x80000)
_LIBC = ctypes.CDLL(None, use_errno=True)
INLINE_TRUST_EVIDENCE = globals().get("__planora_inline_trust_evidence__")


def _validate_minimal_tcb_before_use() -> None:
    if not isinstance(INLINE_TRUST_EVIDENCE, dict):
        raise RuntimeError("inline trust evidence absent")
    descriptor = INLINE_TRUST_EVIDENCE.get("minimal_tcb_fd")
    expected = INLINE_TRUST_EVIDENCE.get("minimal_tcb_sha256")
    if type(descriptor) is not int or not isinstance(expected, str):
        raise RuntimeError("minimal TCB evidence absent")
    seals = int(fcntl.fcntl(descriptor, getattr(fcntl, "F_GET_SEALS", 1034)))
    observed = os.fstat(descriptor)
    raw = os.pread(descriptor, int(observed.st_size), 0)
    if (
        seals & ALL_SEALS != ALL_SEALS
        or sha256(raw).hexdigest() != expected
        or expected
        != "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea"
    ):
        raise RuntimeError("minimal TCB sealed evidence drift")
    admitted = {
        path: digest
        for digest, path in (
            line.split("  ", 1) for line in raw.decode("utf-8").splitlines()
        )
    }
    for module in tuple(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not isinstance(path, str) or path.startswith("<frozen "):
            continue
        if os.path.realpath(path) != path or path not in admitted:
            raise RuntimeError(f"bootstrap module outside minimal TCB: {path}")
        file_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            size = int(os.fstat(file_fd).st_size)
            value = os.pread(file_fd, size, 0)
        finally:
            os.close(file_fd)
        if sha256(value).hexdigest() != admitted[path]:
            raise RuntimeError(f"bootstrap minimal TCB module drift: {path}")


if __name__ == "__main__":
    _validate_minimal_tcb_before_use()


def _identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        int(row.st_dev), int(row.st_ino), int(row.st_size),
        stat.S_IFMT(row.st_mode), stat.S_IMODE(row.st_mode),
        int(row.st_uid), int(row.st_nlink),
    )


def _read_fd(descriptor: int, maximum: int = 1 << 20) -> bytes:
    before = os.fstat(descriptor)
    if before.st_size < 0 or before.st_size > maximum:
        raise RuntimeError("bootstrap source size rejected")
    output: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(
            descriptor, min(1 << 20, before.st_size - offset), offset
        )
        if not block:
            raise RuntimeError("bootstrap source ended early")
        output.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
    if _identity(before) != _identity(after) or (
        before.st_mtime_ns, before.st_ctime_ns
    ) != (after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError("bootstrap source changed during capture")
    return b"".join(output)


def _watch(path: Path) -> tuple[int, int]:
    watch_fd = int(_LIBC.inotify_init1(IN_NONBLOCK | IN_CLOEXEC))
    if watch_fd < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(path))
    watch_descriptor = int(
        _LIBC.inotify_add_watch(
            watch_fd,
            ctypes.c_char_p(os.fsencode(path)),
            ctypes.c_uint32(IN_SOURCE_MUTATION_MASK),
        )
    )
    if watch_descriptor < 0:
        code = ctypes.get_errno()
        os.close(watch_fd)
        raise OSError(code, os.strerror(code), str(path))
    return watch_fd, watch_descriptor


def capture_launcher(path: Path, expected_sha256: str) -> dict[str, object]:
    watch_fd, watch_descriptor = _watch(path)
    descriptor: int | None = None
    sealed: int | None = None
    try:
        parent_before = path.parent.lstat()
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("launcher source contract rejected")
        raw = _read_fd(descriptor)
        after = os.fstat(descriptor)
        named = path.lstat()
        parent_after = path.parent.lstat()
        if _identity(after) != _identity(named) or (
            parent_before.st_dev, parent_before.st_ino
        ) != (parent_after.st_dev, parent_after.st_ino):
            raise RuntimeError("launcher named source drift")
        actual = sha256(raw).hexdigest()
        if actual != expected_sha256:
            raise RuntimeError(
                f"launcher SHA-256 drift: {actual} != {expected_sha256}"
            )
        sealed = os.memfd_create(
            "planora-muni-v28-launcher",
            getattr(os, "MFD_ALLOW_SEALING", 0x0002),
        )
        view = memoryview(raw)
        while view:
            written = os.write(sealed, view)
            if written <= 0:
                raise RuntimeError("launcher memfd stopped accepting bytes")
            view = view[written:]
        os.fchmod(sealed, 0o400)
        fcntl.fcntl(sealed, fcntl.F_ADD_SEALS, ALL_SEALS)
        seals = int(fcntl.fcntl(sealed, fcntl.F_GET_SEALS))
        if seals & ALL_SEALS != ALL_SEALS or _read_fd(sealed) != raw:
            raise RuntimeError("launcher memfd sealing failed")
        os.set_inheritable(sealed, True)
        os.set_inheritable(watch_fd, True)
        sealed_row = os.fstat(sealed)
        evidence = {
            "label": "launcher",
            "path": str(path),
            "fd": sealed,
            "sha256": actual,
            "expected_sha256": expected_sha256,
            "device": int(sealed_row.st_dev),
            "inode": int(sealed_row.st_ino),
            "size": int(sealed_row.st_size),
            "file_type": stat.S_IFMT(sealed_row.st_mode),
            "mode": stat.S_IMODE(sealed_row.st_mode),
            "uid": int(sealed_row.st_uid),
            "nlink": int(sealed_row.st_nlink),
            "seals": seals,
            "required_seals": ALL_SEALS,
            "source_identity": list(_identity(after)[:7]),
            "source_mutation_clock": [
                int(after.st_mtime_ns), int(after.st_ctime_ns)
            ],
            "source_parent_identity": [
                int(parent_after.st_dev), int(parent_after.st_ino),
                stat.S_IMODE(parent_after.st_mode), int(parent_after.st_uid),
            ],
            "source_watch_fd": watch_fd,
            "source_watch_descriptor": watch_descriptor,
            "source_watch_mask": IN_SOURCE_MUTATION_MASK,
            "transport": "sealed_memfd_before_launcher_execution",
        }
        sealed = None
        return evidence
    except BaseException:
        os.close(watch_fd)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if sealed is not None:
            os.close(sealed)


def verify_interpreter() -> None:
    descriptor = os.open("/proc/self/exe", os.O_RDONLY)
    try:
        raw = _read_fd(descriptor, maximum=16 << 20)
    finally:
        os.close(descriptor)
    if (
        sha256(raw).hexdigest() != PYTHON_SHA256
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or Path(sys.executable).resolve()
        != Path("/usr/bin/python3.12").resolve()
    ):
        raise RuntimeError("pinned bootstrap interpreter rejected")


def verify_inline_trust() -> dict[str, object]:
    if not isinstance(INLINE_TRUST_EVIDENCE, dict):
        raise RuntimeError(
            "direct bootstrap pathname execution rejected; inline sealed trust root required"
        )
    descriptor = INLINE_TRUST_EVIDENCE.get("fd")
    expected = INLINE_TRUST_EVIDENCE.get("bootstrap_sha256")
    payload_hash = INLINE_TRUST_EVIDENCE.get("inline_payload_sha256")
    if (
        type(descriptor) is not int
        or descriptor < 3
        or not isinstance(expected, str)
        or not isinstance(payload_hash, str)
        or INLINE_TRUST_EVIDENCE.get("argv_schema")
        != "planora.muni-fspsx.frontier-v28.inline-trust-argv.v1"
        or INLINE_TRUST_EVIDENCE.get("transport")
        != "inline_argv_to_sealed_memfd"
    ):
        raise RuntimeError("inline trust evidence schema rejected")
    raw = _read_fd(descriptor)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    if sha256(raw).hexdigest() != expected or seals & ALL_SEALS != ALL_SEALS:
        raise RuntimeError("sealed bootstrap execution evidence drift")
    return {
        "bootstrap_sha256": expected,
        "inline_payload_sha256": payload_hash,
        "argv_schema": INLINE_TRUST_EVIDENCE["argv_schema"],
        "transport": INLINE_TRUST_EVIDENCE["transport"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    inline_trust = verify_inline_trust()
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--launch", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--sealed-import-probe", action="store_true")
    parser.add_argument("--expected-launcher-sha256")
    parser.add_argument("--expected-supervisor-sha256")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--launcher-path", type=Path, default=LAUNCHER)
    args = parser.parse_args(argv)
    if not args.launch and not args.dry_run and not args.sealed_import_probe:
        print(json.dumps({
            "schema": "planora.muni-fspsx.frontier-v28.bootstrap-gate.v1",
            "status": "NOT_LAUNCHED",
            "children_started": False,
            "artifacts_written": False,
            "required_flag": "--launch",
            "external_bootstrap_pin_required": True,
        }, sort_keys=True))
        return 0
    if not all((
        args.expected_launcher_sha256,
        args.expected_supervisor_sha256,
        args.expected_manifest_sha256,
    )):
        parser.error("all execution modes require all downstream SHA-256 pins")
    verify_interpreter()
    evidence = capture_launcher(
        args.launcher_path, args.expected_launcher_sha256
    )
    evidence["bootstrap_trust"] = inline_trust
    forwarded = [
        (
            "--launch" if args.launch
            else "--sealed-import-probe" if args.sealed_import_probe
            else "--dry-run"
        ),
        "--expected-launcher-sha256", args.expected_launcher_sha256,
        "--expected-supervisor-sha256", args.expected_supervisor_sha256,
        "--expected-manifest-sha256", args.expected_manifest_sha256,
        "--bootstrap-launcher-evidence",
        json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    ]
    os.execve(
        "/bin/bash",
        ["/bin/bash", f"/proc/self/fd/{evidence['fd']}", *forwarded],
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"},
    )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
