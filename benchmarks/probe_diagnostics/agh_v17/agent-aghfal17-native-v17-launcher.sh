#!/bin/bash
set -euo pipefail

unset LD_AUDIT LD_LIBRARY_PATH LD_PRELOAD PYTHONHOME PYTHONPATH PYTHONSTARTUP
readonly expected_launcher_sha256=${AGHFAL_NATIVE_V17_LAUNCHER_SHA256:-}
readonly admitted_bootstrap_sha256=${AGHFAL_NATIVE_V17_BOOTSTRAP_SHA256:-}
readonly admitted_bash_sha256=${AGHFAL_NATIVE_V17_BASH_SHA256:-}
readonly admitted_bootstrap_fd=${AGHFAL_NATIVE_V17_BOOTSTRAP_FD:-}
readonly admitted_launcher_fd=${AGHFAL_NATIVE_V17_LAUNCHER_FD:-}
readonly admitted_bash_fd=${AGHFAL_NATIVE_V17_BASH_FD:-}
if [[ "${AGHFAL_NATIVE_V17_SEALED_LAUNCHER:-}" != "1" \
   || ! "$expected_launcher_sha256" =~ ^[0-9a-f]{64}$ \
   || ! "$admitted_bootstrap_sha256" =~ ^[0-9a-f]{64}$ \
   || ! "$admitted_bash_sha256" =~ ^[0-9a-f]{64}$ \
   || ! "$admitted_bootstrap_fd" =~ ^[0-9]+$ \
   || ! "$admitted_launcher_fd" =~ ^[0-9]+$ \
   || ! "$admitted_bash_fd" =~ ^[0-9]+$ \
   || "${BASH_SOURCE[0]}" != /proc/self/fd/* ]]; then
    echo "AGH-FAL17 v17 launcher requires the sealed bootstrap" >&2
    exit 70
fi
launcher_digest_line=$(/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/sha256sum "${BASH_SOURCE[0]}")
readonly actual_launcher_sha256=${launcher_digest_line%% *}
if [[ "$actual_launcher_sha256" != "$expected_launcher_sha256" ]]; then
    echo "AGH-FAL17 v17 sealed launcher digest drift" >&2
    exit 70
fi
exec 9</usr/bin/python3.12
readonly expected_python_sha256=c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273
python_digest_line=$(/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/sha256sum "/proc/$$/fd/9")
readonly actual_python_sha256=${python_digest_line%% *}
if [[ "$actual_python_sha256" != "$expected_python_sha256" ]]; then
    echo "AGH-FAL17 v17 launcher Python hash drift" >&2
    exit 70
fi

exec /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC \
    AGHFAL_NATIVE_V17_LAUNCHER_SHA256="$actual_launcher_sha256" \
    AGHFAL_NATIVE_V17_BOOTSTRAP_SHA256="$admitted_bootstrap_sha256" \
    AGHFAL_NATIVE_V17_BOOTSTRAP_FD="$admitted_bootstrap_fd" \
    AGHFAL_NATIVE_V17_BASH_SHA256="$admitted_bash_sha256" \
    AGHFAL_NATIVE_V17_BASH_FD="$admitted_bash_fd" \
    AGHFAL_NATIVE_V17_LAUNCHER_FD="$admitted_launcher_fd" \
    AGHFAL_NATIVE_V17_SEALED_LAUNCHER=1 \
    "/proc/$$/fd/9" -I -S -B -c '
import fcntl
import hashlib
import os
import stat
import sys

stdlib_path = "/tmp/agent-aghfal17-native-v17-stdlib.sha256"
stdlib_expected = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327"
root_read_only = False
with open("/proc/self/mountinfo", encoding="utf-8") as mountinfo:
    for line in mountinfo:
        fields = line.split(" - ", 1)[0].split()
        if len(fields) >= 6 and fields[4] == "/" and "ro" in fields[5].split(","):
            root_read_only = True
if not root_read_only:
    raise RuntimeError("AGH-FAL17 v17 stdlib filesystem is not read-only")
stdlib_fd = os.open(stdlib_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
stdlib_row = os.fstat(stdlib_fd)
stdlib_raw = os.pread(stdlib_fd, stdlib_row.st_size, 0)
if hashlib.sha256(stdlib_raw).hexdigest() != stdlib_expected:
    raise RuntimeError("AGH-FAL17 v17 stdlib manifest drift")
stdlib = {}
for line in stdlib_raw.decode("utf-8").splitlines():
    file_hash, file_path = line.split("  ", 1)
    if file_path in stdlib or not file_path.startswith("/usr/lib/python3.12/"):
        raise RuntimeError("AGH-FAL17 v17 stdlib manifest row rejected")
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
            raise RuntimeError("AGH-FAL17 v17 stdlib ownership/permissions rejected")
        if current == "/":
            break
        current = os.path.dirname(current)
    descriptor = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    before = os.fstat(descriptor)
    raw = os.pread(descriptor, before.st_size, 0)
    after = os.fstat(descriptor)
    os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or hashlib.sha256(raw).hexdigest() != file_hash
    ):
        raise RuntimeError("AGH-FAL17 v17 stdlib file drift")
for module in tuple(sys.modules.values()):
    file_path = getattr(module, "__file__", None)
    if not isinstance(file_path, str) or file_path.startswith("<frozen "):
        continue
    if os.path.realpath(file_path) != file_path or file_path not in stdlib:
        raise RuntimeError("AGH-FAL17 v17 pre-supervisor module outside stdlib closure")

path = sys.argv[1]
expected = sys.argv[2]
launcher_path = sys.argv[3]
if set(os.environ) != {"PATH", "LANG", "LC_ALL", "TZ", "AGHFAL_NATIVE_V17_LAUNCHER_SHA256", "AGHFAL_NATIVE_V17_BOOTSTRAP_SHA256", "AGHFAL_NATIVE_V17_BASH_SHA256", "AGHFAL_NATIVE_V17_BOOTSTRAP_FD", "AGHFAL_NATIVE_V17_LAUNCHER_FD", "AGHFAL_NATIVE_V17_BASH_FD", "AGHFAL_NATIVE_V17_SEALED_LAUNCHER"}:
    raise RuntimeError("AGH-FAL17 v17 launcher environment was not sanitized")
launcher_fd = int(launcher_path.removeprefix("/proc/self/fd/"))
if launcher_fd != int(os.environ["AGHFAL_NATIVE_V17_LAUNCHER_FD"]):
    raise RuntimeError("AGH-FAL17 v17 sealed launcher descriptor handoff drift")
launcher_row = os.fstat(launcher_fd)
required_seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
launcher_seals = int(fcntl.fcntl(launcher_fd, fcntl.F_GET_SEALS))
chunks = []; offset = 0
while offset < launcher_row.st_size:
    block = os.pread(launcher_fd, min(1 << 20, launcher_row.st_size - offset), offset)
    if not block: raise RuntimeError("AGH-FAL17 v17 sealed launcher ended early")
    chunks.append(block); offset += len(block)
launcher_raw = b"".join(chunks)
launcher_sha256 = hashlib.sha256(launcher_raw).hexdigest()
if launcher_sha256 != os.environ["AGHFAL_NATIVE_V17_LAUNCHER_SHA256"] or launcher_seals & required_seals != required_seals:
    raise RuntimeError("AGH-FAL17 v17 sealed launcher binding drift")
sealed_rows = {}
for label in ("BOOTSTRAP", "LAUNCHER"):
    descriptor = int(os.environ[f"AGHFAL_NATIVE_V17_{label}_FD"])
    row = os.fstat(descriptor); chunks = []; offset = 0
    while offset < row.st_size:
        block = os.pread(descriptor, min(1 << 20, row.st_size - offset), offset)
        if not block: raise RuntimeError(f"AGH-FAL17 v17 sealed {label.lower()} ended early")
        chunks.append(block); offset += len(block)
    digest = hashlib.sha256(b"".join(chunks)).hexdigest()
    try:
        seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    except OSError as exc:
        raise RuntimeError(f"AGH-FAL17 v17 sealed {label.lower()} descriptor replay unavailable") from exc
    if not stat.S_ISREG(row.st_mode) or digest != os.environ[f"AGHFAL_NATIVE_V17_{label}_SHA256"] or seals & required_seals != required_seals:
        raise RuntimeError(f"AGH-FAL17 v17 sealed {label.lower()} replay drift")
    sealed_rows[label.lower()] = {"fd": descriptor, "sha256": digest, "size": int(row.st_size), "seals": seals}
if len(expected) != 64 or any(value not in "0123456789abcdef" for value in expected):
    raise RuntimeError("frozen AGH-FAL17 v17 supervisor SHA-256 is invalid")
flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(path, flags)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError("AGH-FAL17 v17 supervisor path is not regular")
    identity = lambda row: (
        int(row.st_dev), int(row.st_ino), int(row.st_size), stat.S_IFMT(row.st_mode),
        stat.S_IMODE(row.st_mode), int(row.st_uid), int(row.st_nlink),
    )
    admitted_identity = identity(before)
    chunks = []
    offset = 0
    while offset < before.st_size:
        block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
        if not block:
            raise RuntimeError("AGH-FAL17 v17 supervisor source ended early")
        chunks.append(block)
        offset += len(block)
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)
current = os.lstat(path)
if (
    identity(after) != admitted_identity
    or identity(current) != admitted_identity
    or not stat.S_ISREG(current.st_mode)
):
    raise RuntimeError("AGH-FAL17 v17 supervisor regular-file contract changed")
source = b"".join(chunks)
actual = hashlib.sha256(source).hexdigest()
if actual != expected:
    raise RuntimeError(f"AGH-FAL17 v17 supervisor hash drift: {actual} != {expected}")
filename = f"<captured-aghfal17-native-v17-supervisor:{actual}>"
sys.argv = [filename, *sys.argv[4:]]
namespace = {
    "__name__": "__main__",
    "__file__": filename,
    "__package__": None,
    "__cached__": None,
    "__captured_sha256__": actual,
    "__external_expected_supervisor_sha256__": expected,
    "__external_loader_protocol__": "planora.aghfal17.native-v17-supervisor-loader.v1",
    "__external_loader_handoff_name__": "agent-aghfal17-native-v17-launcher.sh",
    "__external_launcher_attestation__": {
        "protocol": "planora.aghfal17.native-v17-sealed-launcher-bootstrap.v1",
        "bootstrap_sha256": sealed_rows["bootstrap"]["sha256"],
        "bootstrap_fd": sealed_rows["bootstrap"]["fd"],
        "launcher_sha256": sealed_rows["launcher"]["sha256"],
        "launcher_fd": sealed_rows["launcher"]["fd"],
        "bash_sha256": os.environ["AGHFAL_NATIVE_V17_BASH_SHA256"],
        "bash_fd": int(os.environ["AGHFAL_NATIVE_V17_BASH_FD"]),
        "bash_executed_from_verified_sealed_capture": True,
        "bash_fd_post_exec_replay_available": False,
        "launcher_seals": launcher_seals,
        "required_seals": required_seals,
        "launcher_executed_from_sealed_capture": True,
        "external_bootstrap_loader_trust_root_required": True,
        "stdlib_manifest_sha256": stdlib_expected,
        "stdlib_file_count": len(stdlib),
        "stdlib_expected_uid": 65534,
        "stdlib_expected_gid": 65534,
        "stdlib_root_mount_read_only": True,
        "stdlib_non_writable_ancestors": True,
        "stdlib_admitted_before_supervisor_exec": True,
    },
    "__external_supervisor_path__": path,
    "__external_supervisor_binding__": {
        "path": path,
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "size": int(after.st_size),
        "file_type": stat.S_IFMT(after.st_mode),
        "mode": stat.S_IMODE(after.st_mode),
        "uid": int(after.st_uid),
        "nlink": int(after.st_nlink),
        "sha256": actual,
    },
}
exec(compile(source, filename, "exec", dont_inherit=True), namespace)
' /tmp/agent-aghfal17-native-v17-supervisor.py 56a78bc55e2b6e324397d9e7350346382d63e1676cdda06553b40dd280c0cc89 "${BASH_SOURCE[0]}" "$@"
