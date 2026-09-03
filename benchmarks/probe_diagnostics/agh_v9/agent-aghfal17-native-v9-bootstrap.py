#!/usr/bin/env python3
"""Capture and execute the AGH-FAL17 v9 launcher from sealed bytes."""

from __future__ import annotations

import argparse
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


BOOTSTRAP_LOADER_PROTOCOL = "planora.aghfal17.native-v9-bootstrap-loader.v1"
LAUNCHER_ATTESTATION_PROTOCOL = (
    "planora.aghfal17.native-v9-sealed-launcher-bootstrap.v1"
)
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
)
MAX_SOURCE_BYTES = 32 << 20
MINIMAL_TCB_EVIDENCE = globals().get("__minimal_tcb_evidence__")
PROBE_HARNESS = Path("/tmp/agent-aghfal17-native-v9-probe-harness.py")
EXPECTED_PROBE_HARNESS_SHA256 = (
    "c750a03b800a02289c5850a5bca51ca8828e83636a4fe5238e3f3d6181724849"
)
BOOTSTRAP_FD_LOADER = r'''
import fcntl, hashlib, os, stat, sys
path=sys.argv[1]; expected=sys.argv[2]; expected_python=sys.argv[3]; forwarded=sys.argv[4:]
required=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
identity=lambda row:(int(row.st_dev),int(row.st_ino),int(row.st_size),stat.S_IFMT(row.st_mode),stat.S_IMODE(row.st_mode),int(row.st_uid),int(row.st_nlink))
tcb_path='/tmp/agent-aghfal17-native-v9-minimal-tcb.sha256'; tcb_expected='825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea'
root_ro=False
with open('/proc/self/mountinfo',encoding='utf-8') as mountinfo:
 for line in mountinfo:
  fields=line.split(' - ',1)[0].split()
  if len(fields)>=6 and fields[4]=='/' and 'ro' in fields[5].split(','): root_ro=True
if not root_ro: raise RuntimeError('bootstrap minimal TCB filesystem is not read-only')
tcb_fd=os.open(tcb_path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)); tcb_row=os.fstat(tcb_fd); tcb_raw=os.pread(tcb_fd,tcb_row.st_size,0)
if hashlib.sha256(tcb_raw).hexdigest()!=tcb_expected: raise RuntimeError('bootstrap minimal TCB manifest drift')
tcb={line.split('  ',1)[1]:line.split('  ',1)[0] for line in tcb_raw.decode().splitlines()}
for module in tuple(sys.modules.values()):
 module_path=getattr(module,'__file__',None)
 if not isinstance(module_path,str) or module_path.startswith('<frozen '): continue
 resolved=os.path.realpath(module_path)
 if resolved!=module_path or resolved not in tcb: raise RuntimeError('bootstrap module outside minimal TCB: '+str(module_path))
 current=resolved
 while True:
  ownership=os.stat(current,follow_symlinks=False)
  if ownership.st_uid!=65534 or ownership.st_gid!=65534 or stat.S_IMODE(ownership.st_mode)&0o022: raise RuntimeError('bootstrap minimal TCB permissions rejected: '+current)
  if current=='/': break
  current=os.path.dirname(current)
 module_fd=os.open(resolved,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)); module_raw=os.pread(module_fd,os.fstat(module_fd).st_size,0); os.close(module_fd)
 if hashlib.sha256(module_raw).hexdigest()!=tcb[resolved]: raise RuntimeError('bootstrap minimal TCB module drift: '+resolved)
tcb_sealed=os.memfd_create('aghfal17-v9-minimal-tcb',getattr(os,'MFD_ALLOW_SEALING',0x0002)); os.write(tcb_sealed,tcb_raw); os.fchmod(tcb_sealed,0o400); fcntl.fcntl(tcb_sealed,fcntl.F_ADD_SEALS,required)
python_fd=os.open('/proc/self/exe',os.O_RDONLY); python_raw=b''; offset=0; python_row=os.fstat(python_fd)
while offset<python_row.st_size:
 block=os.pread(python_fd,min(1<<20,python_row.st_size-offset),offset)
 if not block: raise RuntimeError('bootstrap loader Python ended early')
 python_raw+=block; offset+=len(block)
os.close(python_fd)
if hashlib.sha256(python_raw).hexdigest()!=expected_python: raise RuntimeError('bootstrap loader Python hash drift')
parent=os.path.dirname(path); name=os.path.basename(path); parent_before=os.lstat(parent); parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0)); parent_open=os.fstat(parent_fd)
source_fd=os.open(name,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),dir_fd=parent_fd); before=os.fstat(source_fd)
if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1: raise RuntimeError('bootstrap loader source rejected')
chunks=[]; offset=0
while offset<before.st_size:
 block=os.pread(source_fd,min(1<<20,before.st_size-offset),offset)
 if not block: raise RuntimeError('bootstrap loader source ended early')
 chunks.append(block); offset+=len(block)
after=os.fstat(source_fd); named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False); parent_after=os.lstat(parent); raw=b''.join(chunks); actual=hashlib.sha256(raw).hexdigest()
if identity(parent_before)!=identity(parent_open) or identity(parent_open)!=identity(parent_after) or identity(before)!=identity(after) or identity(after)!=identity(named) or actual!=expected: raise RuntimeError('bootstrap loader source drift')
sealed=os.memfd_create('aghfal17-v9-bootstrap',getattr(os,'MFD_ALLOW_SEALING',0x0002)); view=memoryview(raw)
while view:
 written=os.write(sealed,view)
 if written<=0: raise RuntimeError('bootstrap loader sealed write failed')
 view=view[written:]
os.fchmod(sealed,0o400); fcntl.fcntl(sealed,fcntl.F_ADD_SEALS,required); sealed_raw=os.pread(sealed,len(raw),0)
if int(fcntl.fcntl(sealed,fcntl.F_GET_SEALS))&required!=required or sealed_raw!=raw: raise RuntimeError('bootstrap loader sealing failed')
os.close(source_fd); os.close(parent_fd); filename=f'<sealed-aghfal17-v9-bootstrap:{actual}>'; sys.argv=[filename,*forwarded]
namespace={'__name__':'__main__','__file__':filename,'__package__':None,'__cached__':None,'__captured_sha256__':actual,'__captured_fd__':sealed,'__captured_source_path__':path,'__bootstrap_loader_protocol__':'planora.aghfal17.native-v9-bootstrap-loader.v1','__minimal_tcb_evidence__':{'fd':tcb_sealed,'sha256':tcb_expected,'file_count':len(tcb),'uid':65534,'gid':65534,'root_mount_read_only':True,'non_writable_ancestors':True,'admitted_before_bootstrap_exec':True}}
exec(compile(sealed_raw,filename,'exec',dont_inherit=True),namespace)
'''.strip()
BOOTSTRAP_FD_LOADER_SHA256 = sha256(BOOTSTRAP_FD_LOADER.encode("utf-8")).hexdigest()


def _validate_minimal_tcb_evidence() -> None:
    evidence = MINIMAL_TCB_EVIDENCE
    if (
        not isinstance(evidence, dict)
        or evidence.get("sha256")
        != "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea"
        or evidence.get("file_count") != 50
        or evidence.get("uid") != 65534
        or evidence.get("gid") != 65534
        or evidence.get("root_mount_read_only") is not True
        or evidence.get("non_writable_ancestors") is not True
        or evidence.get("admitted_before_bootstrap_exec") is not True
    ):
        raise RuntimeError("minimal TCB before-use evidence rejected")


if __name__ == "__main__":
    _validate_minimal_tcb_evidence()


def _identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        int(row.st_dev),
        int(row.st_ino),
        int(row.st_size),
        stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode),
        int(row.st_uid),
        int(row.st_nlink),
    )


def _pread_exact(descriptor: int) -> bytes:
    before = os.fstat(descriptor)
    if before.st_size < 1 or before.st_size > MAX_SOURCE_BYTES:
        raise RuntimeError("bootstrap capture size rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(
            descriptor, min(1 << 20, before.st_size - offset), offset
        )
        if not block:
            raise RuntimeError("bootstrap capture ended early")
        chunks.append(block)
        offset += len(block)
    if _identity(os.fstat(descriptor)) != _identity(before):
        raise RuntimeError("bootstrap capture descriptor drift")
    return b"".join(chunks)


def capture_sealed_source(
    path: Path, expected_sha256: str, label: str, *, executable: bool
) -> tuple[int, dict[str, Any]]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RuntimeError(f"{label} expected SHA-256 rejected")
    parent_before = os.lstat(path.parent)
    parent_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    source_fd = -1
    target_fd = -1
    try:
        parent_opened = os.fstat(parent_fd)
        source_fd = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode) or source_before.st_nlink != 1:
            raise RuntimeError(f"{label} source contract rejected")
        raw = _pread_exact(source_fd)
        source_after = os.fstat(source_fd)
        named_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.lstat(path.parent)
        actual = sha256(raw).hexdigest()
        if (
            _identity(parent_before) != _identity(parent_opened)
            or _identity(parent_opened) != _identity(parent_after)
            or _identity(source_before) != _identity(source_after)
            or _identity(source_after) != _identity(named_after)
            or actual != expected_sha256
        ):
            raise RuntimeError(f"{label} source capture drift")
        target_fd = os.memfd_create(
            f"aghfal17-v9-{label}", getattr(os, "MFD_ALLOW_SEALING", 0x0002)
        )
        view = memoryview(raw)
        while view:
            written = os.write(target_fd, view)
            if written <= 0:
                raise RuntimeError(f"{label} sealed capture stopped accepting bytes")
            view = view[written:]
        os.fchmod(target_fd, 0o500 if executable else 0o400)
        fcntl.fcntl(target_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        sealed = os.fstat(target_fd)
        replay = _pread_exact(target_fd)
        seals = int(fcntl.fcntl(target_fd, fcntl.F_GET_SEALS))
        if replay != raw or seals & REQUIRED_SEALS != REQUIRED_SEALS:
            raise RuntimeError(f"{label} sealed capture replay failed")
        evidence = {
            "label": label,
            "sha256": actual,
            "size": len(raw),
            "source_identity": list(_identity(source_after)),
            "sealed_identity": list(_identity(sealed)),
            "seals": seals,
            "required_seals": REQUIRED_SEALS,
            "transport": "sealed_memfd",
        }
        result = target_fd
        target_fd = -1
        return result, evidence
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(parent_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-bootstrap-sha256", required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--expected-launcher-sha256", required=True)
    parser.add_argument("--bash", type=Path, required=True)
    parser.add_argument("--expected-bash-sha256", required=True)
    parser.add_argument("target", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    forwarded = list(args.target)
    if forwarded and forwarded[0] == "--":
        forwarded.pop(0)
    executed = globals().get("__captured_sha256__")
    bootstrap_fd = globals().get("__captured_fd__")
    if (
        globals().get("__bootstrap_loader_protocol__")
        != BOOTSTRAP_LOADER_PROTOCOL
        or executed != args.expected_bootstrap_sha256
        or type(bootstrap_fd) is not int
    ):
        raise SystemExit("bootstrap was not executed from admitted captured bytes")
    launcher_fd, launcher = capture_sealed_source(
        args.launcher,
        args.expected_launcher_sha256,
        "launcher",
        executable=False,
    )
    bash_fd, bash = capture_sealed_source(
        args.bash, args.expected_bash_sha256, "bash", executable=True
    )
    harness_fd, _harness = capture_sealed_source(
        PROBE_HARNESS,
        EXPECTED_PROBE_HARNESS_SHA256,
        "probe-harness",
        executable=False,
    )
    for descriptor in (bootstrap_fd, launcher_fd, bash_fd, harness_fd):
        os.set_inheritable(descriptor, True)
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "AGHFAL_NATIVE_V9_BOOTSTRAP_SHA256": str(executed),
        "AGHFAL_NATIVE_V9_BOOTSTRAP_FD": str(bootstrap_fd),
        "AGHFAL_NATIVE_V9_LAUNCHER_SHA256": launcher["sha256"],
        "AGHFAL_NATIVE_V9_LAUNCHER_FD": str(launcher_fd),
        "AGHFAL_NATIVE_V9_BASH_SHA256": bash["sha256"],
        "AGHFAL_NATIVE_V9_BASH_FD": str(bash_fd),
        "AGHFAL_NATIVE_V9_SEALED_LAUNCHER": "1",
    }
    bash_exec_fd = os.dup(bash_fd)
    os.set_inheritable(bash_exec_fd, True)
    argv = [
        f"/proc/self/fd/{bash_exec_fd}",
        f"/proc/self/fd/{launcher_fd}",
        *forwarded,
    ]
    if forwarded == ["--sealed-import-probe"]:
        command_sha256 = sha256(
            json.dumps(
                argv, ensure_ascii=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        pass_fds = tuple(
            dict.fromkeys(
                (bootstrap_fd, launcher_fd, bash_fd, bash_exec_fd)
            )
        )
        harness_argv = [
            "/proc/self/exe",
            "-I",
            "-S",
            "-B",
            f"/proc/self/fd/{harness_fd}",
            "--wall-seconds",
            "240",
            "--expected-command-sha256",
            command_sha256,
        ]
        for descriptor in pass_fds:
            harness_argv.extend(("--pass-fd", str(descriptor)))
        harness_argv.extend(("--", *argv))
        os.execve("/proc/self/exe", harness_argv, environment)
        raise AssertionError("sealed probe harness exec unexpectedly returned")
    os.execve(bash_exec_fd, argv, environment)
    raise AssertionError("sealed launcher exec unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
