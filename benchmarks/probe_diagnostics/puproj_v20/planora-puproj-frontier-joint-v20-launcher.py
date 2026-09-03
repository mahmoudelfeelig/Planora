"""Sealed v20 launcher for the revised PU-PROJ resource control plane."""

from __future__ import annotations

import fcntl
from hashlib import sha256
import os
from pathlib import Path
import stat
import sys


ARTIFACT_ROOT = Path(
    "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/puproj_v20"
)
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v20-supervisor.py"
EXPECTED_SUPERVISOR_SHA256 = (
    "2b9b1c797f26b472eee66fd82a674e85b3951828307fdc653aa5878fe6db6e09"
)
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)


def _identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        int(row.st_dev),
        int(row.st_ino),
        int(row.st_size),
        stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode),
        int(row.st_uid),
        int(row.st_nlink),
        int(row.st_mtime_ns),
        int(row.st_ctime_ns),
    )


def _read(descriptor: int, size: int) -> bytes:
    parts: list[bytes] = []
    offset = 0
    while offset < size:
        block = os.pread(descriptor, min(1 << 20, size - offset), offset)
        if not block:
            raise RuntimeError("PU-PROJ v19 supervisor source ended early")
        parts.append(block)
        offset += len(block)
    return b"".join(parts)


def _verify_bootstrap_handoff() -> tuple[dict[str, object], dict[str, object]]:
    if (
        globals().get("__bootstrap_loader_protocol__")
        != "planora.native-sealed-python-bootstrap.v1"
    ):
        raise RuntimeError("direct PU-PROJ v19 launcher execution rejected")
    binding = globals().get("__bootstrap_launcher_binding__")
    runtime = globals().get("__bootstrap_runtime_binding__")
    manifest = globals().get("__bootstrap_manifest_binding__")
    descriptor = globals().get("__bootstrap_launcher_fd__")
    if (
        not isinstance(binding, dict)
        or not isinstance(runtime, dict)
        or not isinstance(manifest, dict)
        or type(descriptor) is not int
    ):
        raise RuntimeError("PU-PROJ v19 bootstrap handoff binding rejected")
    before = os.fstat(descriptor)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    raw = _read(descriptor, before.st_size)
    if (
        seals & REQUIRED_SEALS != REQUIRED_SEALS
        or binding.get("seals") != seals
        or binding.get("sha256") != sha256(raw).hexdigest()
        or globals().get("__captured_launcher_sha256__") != binding.get("sha256")
    ):
        raise RuntimeError("PU-PROJ v19 sealed launcher replay rejected")
    source_identity = tuple(binding.get("source_identity", ()))
    named = os.lstat(str(binding.get("path", "")))
    if (
        _identity(named) != source_identity
        or binding.get("transport")
        != "native_bootstrap_sealed_memfd_before_launcher_execution"
        or binding.get("source_watch_fd") is None
    ):
        raise RuntimeError("PU-PROJ v19 launcher source/watch binding rejected")
    return binding, runtime, manifest


def main() -> int:
    launcher_binding, bootstrap_runtime, freeze_manifest_binding = (
        _verify_bootstrap_handoff()
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(SUPERVISOR, flags)
    sealed_fd = -1
    try:
        before = os.fstat(descriptor)
        admitted = _identity(before)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("PU-PROJ v19 supervisor source contract rejected")
        source = _read(descriptor, before.st_size)
        after = os.fstat(descriptor)
        named = os.lstat(SUPERVISOR)
        if _identity(after) != admitted or _identity(named) != admitted:
            raise RuntimeError("PU-PROJ v19 supervisor source identity drift")
        actual = sha256(source).hexdigest()
        if actual != EXPECTED_SUPERVISOR_SHA256:
            raise RuntimeError(f"PU-PROJ v19 supervisor hash drift: {actual}")
        sealed_fd = os.memfd_create(
            "planora-puproj-v19-supervisor", getattr(os, "MFD_ALLOW_SEALING", 0x0002)
        )
        view = memoryview(source)
        while view:
            written = os.write(sealed_fd, view)
            if written <= 0:
                raise RuntimeError(
                    "PU-PROJ v19 supervisor memfd stopped accepting bytes"
                )
            view = view[written:]
        os.fchmod(sealed_fd, 0o400)
        fcntl.fcntl(sealed_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        sealed = os.fstat(sealed_fd)
        seals = int(fcntl.fcntl(sealed_fd, fcntl.F_GET_SEALS))
        if (
            seals & REQUIRED_SEALS != REQUIRED_SEALS
            or _read(sealed_fd, sealed.st_size) != source
        ):
            raise RuntimeError("PU-PROJ v19 supervisor sealed replay rejected")
        filename = f"<sealed-puproj-frontier-v19-supervisor:{actual}>"
        namespace = {
            "__name__": "__main__",
            "__file__": filename,
            "__package__": None,
            "__cached__": None,
            "__captured_sha256__": actual,
            "__external_expected_supervisor_sha256__": EXPECTED_SUPERVISOR_SHA256,
            "__external_loader_protocol__": "planora.puproj.frontier-v19-supervisor-loader.v1",
            "__external_loader_handoff_name__": "planora-puproj-frontier-joint-v19-launcher.py",
            "__external_supervisor_path__": str(SUPERVISOR),
            "__external_supervisor_binding__": {
                "path": str(SUPERVISOR),
                "device": int(after.st_dev),
                "inode": int(after.st_ino),
                "size": int(after.st_size),
                "file_type": stat.S_IFMT(after.st_mode),
                "mode": stat.S_IMODE(after.st_mode),
                "uid": int(after.st_uid),
                "nlink": int(after.st_nlink),
                "mtime_ns": int(after.st_mtime_ns),
                "ctime_ns": int(after.st_ctime_ns),
                "sha256": actual,
                "sealed_fd": sealed_fd,
                "sealed_seals": seals,
            },
            "__external_launcher_binding__": launcher_binding,
            "__external_bootstrap_runtime_binding__": bootstrap_runtime,
            "__external_freeze_manifest_binding__": freeze_manifest_binding,
        }
        exec(compile(source, filename, "exec", dont_inherit=True), namespace)
    finally:
        os.close(descriptor)
        if sealed_fd >= 0:
            os.close(sealed_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
