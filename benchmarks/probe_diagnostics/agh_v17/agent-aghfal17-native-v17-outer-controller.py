#!/usr/bin/env python3
"""Authoritative whole-launch controller for the AGH-FAL17 v17 chain.

The controller is the retained Linux child subreaper for both the sealed import
probe and the official launch.  It admits the bootstrap root behind a barrier,
tracks exact PID generations across process groups and sessions, charges sealed
storage and retained report bytes once, and is the only component allowed to
declare the launch envelope acceptable.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-side static/unit inspection
    fcntl = None  # type: ignore[assignment]


SCHEMA = "planora.agh-fal17.native-v17-outer-controller.v1"
FREEZE_SCHEMA = "planora.agh-fal17.native-v17-freeze.v1"
PR_SET_PDEATHSIG = 1
PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
REQUIRED_SEALS = 0x0001 | 0x0002 | 0x0004 | 0x0008
BARRIER_FD = 198
BARRIER_TOKEN = b"G"
SIGKILL = getattr(signal, "SIGKILL", 9)
BARRIER_LOADER = (
    "import os,sys;fd=int(sys.argv[1]);"
    "token=os.read(fd,1);os.close(fd);"
    "token==b'G' or (_ for _ in ()).throw(RuntimeError('outer barrier rejected'));"
    "marker=sys.argv.index('--');argv=sys.argv[marker+1:];"
    "argv or (_ for _ in ()).throw(RuntimeError('inner argv missing'));"
    "os.execve(argv[0],argv,dict(os.environ))"
)
WHOLE_LAUNCH_MEMORY_LIMIT_KIB = 614_400
PROCESS_GENERATION_MEMORY_LIMIT_KIB = 368_640
INITIAL_MEMAVAILABLE_FLOOR_KIB = 1_900_000
RUNTIME_MEMAVAILABLE_FLOOR_KIB = 900_000
INITIAL_SAMPLE_INTERVAL_SECONDS = 5.0
PROBE_OUTER_WALL_SECONDS = 240.0
LAUNCH_OUTER_WALL_SECONDS = 1_800.0
POLL_SECONDS = 0.05
TERMINATION_GRACE_SECONDS = 1.0
FINAL_ZERO_SNAPSHOTS_REQUIRED = 2
MAX_STDOUT_BYTES = 64 << 20
MAX_STDERR_BYTES = 32 << 20
STOP_SIGNALS = tuple(
    dict.fromkeys(
        (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM))
    )
)
LIBC = ctypes.CDLL(None, use_errno=True) if os.name == "posix" else None


@dataclass(frozen=True)
class ProcessIdentity:
    starttime: int


@dataclass(frozen=True)
class ProcessTopology:
    ppid: int
    process_group: int
    session: int


@dataclass(frozen=True)
class ProcessRecord:
    identity: ProcessIdentity
    topology: ProcessTopology
    state: str = "S"


@dataclass
class AdmittedMember:
    identity: ProcessIdentity
    pidfd: int
    topology: ProcessTopology


class ProcInspectionError(RuntimeError):
    """A /proc observation failed for a reason other than process disappearance."""


def _sha256_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical_argv_sha256(argv: Sequence[str]) -> str:
    if any("\0" in value for value in argv):
        raise RuntimeError("canonical argv contains NUL")
    return _sha256_bytes("\0".join(argv).encode("utf-8"))


def proc_record(pid: int) -> ProcessRecord | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (
            errno.ENOENT,
            errno.ESRCH,
        ):
            return None
        raise ProcInspectionError(
            f"proc stat read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    close = raw.rfind(")")
    fields = raw[close + 2 :].split() if close >= 0 else []
    if len(fields) < 20:
        raise ProcInspectionError(f"proc stat malformed: {pid}")
    state = fields[0]
    if len(state) != 1 or not state.isascii() or not state.isalpha():
        raise ProcInspectionError(f"proc stat state malformed: {pid}")
    try:
        return ProcessRecord(
            identity=ProcessIdentity(starttime=int(fields[19])),
            topology=ProcessTopology(
                ppid=int(fields[1]),
                process_group=int(fields[2]),
                session=int(fields[3]),
            ),
            state=state,
        )
    except ValueError as exc:
        raise ProcInspectionError(f"proc stat parse failed: {pid}") from exc


def proc_identity(pid: int) -> ProcessIdentity | None:
    record = proc_record(pid)
    return None if record is None else record.identity


def proc_snapshot() -> dict[int, ProcessRecord]:
    result: dict[int, ProcessRecord] = {}
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError as exc:
        raise RuntimeError(f"proc snapshot unavailable: {exc}") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        record = proc_record(int(entry.name))
        if record is not None:
            result[int(entry.name)] = record
    return result


def _status_values(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    raw = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
    tracked = frozenset(("VmRSS", "VmSwap"))
    for line in raw.splitlines():
        match = re.match(r"^\s*(VmRSS|VmSwap)(?=\s|:|$)", line)
        if match is None:
            continue
        tracked_key = match.group(1)
        key, separator, value = line.partition(":")
        if not separator or key != tracked_key:
            raise ProcInspectionError(
                f"proc status {tracked_key} key syntax malformed: {pid}"
            )
        if tracked_key not in tracked:
            raise ProcInspectionError(f"proc status tracked key rejected: {pid}")
        if tracked_key in values:
            raise ProcInspectionError(
                f"proc status duplicate {tracked_key}: {pid}"
            )
        tokens = value.strip().split()
        if len(tokens) != 2 or tokens[1] != "kB":
            raise ProcInspectionError(
                f"proc status {tracked_key} malformed: {pid}"
            )
        try:
            parsed = int(tokens[0])
        except ValueError as exc:
            raise ProcInspectionError(
                f"proc status {tracked_key} malformed: {pid}"
            ) from exc
        if parsed < 0:
            raise ProcInspectionError(
                f"proc status {tracked_key} negative: {pid}"
            )
        values[tracked_key] = parsed
    return values


def pidfd_exit_confirmed(pidfd: int) -> bool:
    """Return true only when the pinned process generation has terminated."""

    poll_factory = getattr(select, "poll", None)
    if poll_factory is None:
        raise ProcInspectionError("pidfd polling unavailable")
    poll_in = int(getattr(select, "POLLIN", 0x001))
    poll_invalid = int(getattr(select, "POLLNVAL", 0x020))
    try:
        poller = poll_factory()
        poller.register(pidfd, poll_in)
        events = tuple(poller.poll(0))
    except (OSError, ValueError) as exc:
        raise ProcInspectionError(
            f"pidfd exit observation failed: {pidfd}:{type(exc).__name__}:{exc}"
        ) from exc
    for observed_fd, event_mask in events:
        if int(observed_fd) != pidfd or int(event_mask) & poll_invalid:
            raise ProcInspectionError(f"pidfd exit observation invalid: {pidfd}")
        if int(event_mask) & poll_in:
            return True
    return False


def _confirmed_exit_or_raise(pid: int, pidfd: int | None, reason: str) -> None:
    if pidfd is not None and pidfd_exit_confirmed(pidfd):
        return None
    raise ProcInspectionError(f"{reason}: {pid}")


def _generation_ambiguity_error(
    context: str,
    pid: int,
    expected: ProcessIdentity,
    observed: ProcessIdentity,
) -> ProcInspectionError:
    return ProcInspectionError(
        "admitted PID generation ambiguity:"
        f"{context}:{pid}:expected={expected.starttime}:observed={observed.starttime}"
    )


def identity_bound_status(
    pid: int, expected: ProcessIdentity, pidfd: int | None = None
) -> dict[str, Any] | None:
    before = proc_record(pid)
    if before is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat absent without confirmed generation exit"
        )
    if before.identity != expected:
        raise _generation_ambiguity_error(
            "identity replay failed before status read",
            pid,
            expected,
            before.identity,
        )
    try:
        status = _status_values(pid)
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (
            errno.ENOENT,
            errno.ESRCH,
        ):
            return _confirmed_exit_or_raise(
                pid, pidfd, "proc status absent without confirmed generation exit"
            )
        raise ProcInspectionError(
            f"proc status read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    after = proc_record(pid)
    if after is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat vanished without confirmed generation exit"
        )
    if after.identity != expected:
        raise _generation_ambiguity_error(
            "identity replay failed after status read",
            pid,
            expected,
            after.identity,
        )
    if "VmRSS" not in status:
        if after.state != "Z":
            raise ProcInspectionError(
                f"VmRSS unavailable for non-zombie admitted identity: {pid}:{after.state}"
            )
        if pidfd is None or not pidfd_exit_confirmed(pidfd):
            raise ProcInspectionError(
                f"zombie VmRSS unavailable without confirmed generation exit: {pid}"
            )
        return None
    return {
        "pid": pid,
        "identity": [pid, expected.starttime],
        "topology": [
            after.topology.ppid,
            after.topology.process_group,
            after.topology.session,
        ],
        "process_state": after.state,
        "vmrss_kib": int(status["VmRSS"]),
        "vmswap_kib": int(status.get("VmSwap", 0)),
    }


def _open_pidfd(pid: int, expected: ProcessIdentity) -> int:
    if not hasattr(os, "pidfd_open"):
        raise RuntimeError("pidfd_open is required for the v12 containment contract")
    descriptor = os.pidfd_open(pid, 0)
    replay = proc_record(pid)
    if replay is None or replay.identity != expected:
        os.close(descriptor)
        raise RuntimeError(f"pidfd generation replay failed: {pid}")
    return descriptor


def admit_member(
    admitted: dict[int, AdmittedMember], pid: int, record: ProcessRecord
) -> None:
    existing = admitted.get(pid)
    if existing is not None:
        if existing.identity != record.identity:
            raise RuntimeError(f"admitted PID generation changed: {pid}")
        existing.topology = record.topology
        return
    admitted[pid] = AdmittedMember(
        identity=record.identity,
        pidfd=_open_pidfd(pid, record.identity),
        topology=record.topology,
    )


def refresh_descendant_registry(
    *,
    wrapper_pid: int,
    root_pid: int,
    admitted: dict[int, AdmittedMember],
    baseline_direct_children: Mapping[int, ProcessIdentity],
    snapshot: Mapping[int, ProcessRecord] | None = None,
) -> dict[str, Any]:
    observed = dict(proc_snapshot() if snapshot is None else snapshot)
    added: list[int] = []
    changed = True
    while changed:
        changed = False
        live_parents: set[int] = set()
        for pid, member in admitted.items():
            record = observed.get(pid)
            if record is None:
                continue
            if record.identity != member.identity:
                raise _generation_ambiguity_error(
                    "descendant_refresh", pid, member.identity, record.identity
                )
            member.topology = record.topology
            live_parents.add(pid)
        for pid, record in sorted(observed.items()):
            if pid in admitted or pid == wrapper_pid:
                continue
            direct_root = pid == root_pid and record.topology.ppid == wrapper_pid
            descendant = record.topology.ppid in live_parents
            reparented_orphan = (
                record.topology.ppid == wrapper_pid
                and baseline_direct_children.get(pid) != record.identity
            )
            if not (direct_root or descendant or reparented_orphan):
                continue
            admit_member(admitted, pid, record)
            added.append(pid)
            changed = True
    return {
        "added_pids": added,
        "live_admitted_pids": sorted(
            pid for pid in admitted if observed.get(pid) is not None
        ),
        "generation_ambiguities": [],
    }


def accounting_sample(
    *,
    wrapper_pid: int,
    wrapper_identity: ProcessIdentity,
    admitted: Mapping[int, AdmittedMember],
) -> dict[str, Any]:
    requested: list[tuple[str, int, ProcessIdentity, int | None]] = [
        ("outer_controller", wrapper_pid, wrapper_identity, None)
    ]
    requested.extend(
        ("launch_generation", pid, member.identity, member.pidfd)
        for pid, member in sorted(admitted.items())
    )
    rows: list[dict[str, Any]] = []
    vanished: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for role, pid, identity, pidfd in requested:
        key = (pid, identity.starttime)
        if key in seen:
            continue
        seen.add(key)
        try:
            row = identity_bound_status(pid, identity, pidfd)
        except RuntimeError as exc:
            unavailable.append({"role": role, "pid": pid, "error": str(exc)})
            continue
        if row is None:
            vanished.append({"role": role, "pid": pid, "basis": "pidfd_exit_confirmed"})
            continue
        row["role"] = role
        rows.append(row)
    group_totals: dict[int, int] = {}
    for row in rows:
        topology = row["topology"]
        process_group = int(topology[1])
        charge = int(row["vmrss_kib"]) + int(row["vmswap_kib"])
        group_totals[process_group] = group_totals.get(process_group, 0) + charge
    return {
        "rows": rows,
        "vanished": vanished,
        "unavailable": unavailable,
        "unique_identity_count": len(rows),
        "process_vmrss_kib": sum(int(row["vmrss_kib"]) for row in rows),
        "process_vmswap_kib": sum(int(row["vmswap_kib"]) for row in rows),
        "process_group_charges_kib": {
            str(key): value for key, value in sorted(group_totals.items())
        },
        "pid_generation_deduplicated": True,
    }


def sealed_reservation(mode_contract: Mapping[str, Any]) -> dict[str, Any]:
    allocations = mode_contract.get("allocations")
    if not isinstance(allocations, list):
        raise RuntimeError("sealed allocation contract is missing")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    total = 0
    for value in allocations:
        if not isinstance(value, dict):
            raise RuntimeError("sealed allocation row is not an object")
        allocation_id = value.get("allocation_id")
        size = value.get("size_bytes")
        if (
            not isinstance(allocation_id, str)
            or not allocation_id
            or allocation_id in seen
            or type(size) is not int
            or size < 0
        ):
            raise RuntimeError("sealed allocation row rejected")
        seen.add(allocation_id)
        total += size
        rows.append({"allocation_id": allocation_id, "size_bytes": size})
    return {
        "allocations": rows,
        "allocation_count": len(rows),
        "reserved_bytes": total,
        "deduplicated_by_allocation_id": True,
    }


def retained_report_bytes(*descriptors: int) -> int:
    total = 0
    seen: set[tuple[int, int]] = set()
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        row = os.fstat(descriptor)
        key = (int(row.st_dev), int(row.st_ino))
        if key in seen:
            continue
        seen.add(key)
        total += int(row.st_size)
    return total


def resource_breach(
    *,
    elapsed_seconds: float,
    process_rss_kib: int,
    process_swap_kib: int,
    process_group_charges_kib: Mapping[str, int],
    sealed_bytes: int,
    report_bytes: int,
    mem_available_kib: int,
    wall_seconds: float,
    accounting_errors: Sequence[Mapping[str, Any]] = (),
) -> str | None:
    if accounting_errors:
        return "exact_generation_accounting_unavailable"
    if mem_available_kib < RUNTIME_MEMAVAILABLE_FLOOR_KIB:
        return "runtime_memavailable_floor"
    if any(
        value >= PROCESS_GENERATION_MEMORY_LIMIT_KIB
        for value in process_group_charges_kib.values()
    ):
        return "process_generation_vmrss_plus_vmswap_limit"
    storage_kib = math.ceil((sealed_bytes + report_bytes) / 1024)
    if process_rss_kib + process_swap_kib + storage_kib >= WHOLE_LAUNCH_MEMORY_LIMIT_KIB:
        return "whole_launch_process_plus_sealed_plus_report_limit"
    if elapsed_seconds >= wall_seconds:
        return "outer_hard_wall"
    return None


def _read_key_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        try:
            values[key] = int(value.strip().split(maxsplit=1)[0])
        except (ValueError, IndexError):
            continue
    return values


def host_sample() -> dict[str, int]:
    memory = _read_key_values(Path("/proc/meminfo"))
    return {
        "mem_available_kib": memory["MemAvailable"],
        "swap_free_kib": memory.get("SwapFree", 0),
    }


def _stable_file(path: Path, expected_sha256: str, maximum: int) -> bytes:
    descriptor_match = re.fullmatch(r"/proc/self/fd/([0-9]+)", str(path))
    if descriptor_match is not None:
        descriptor = int(descriptor_match.group(1))
        before = os.fstat(descriptor)
        if before.st_size > maximum:
            raise RuntimeError(f"frozen descriptor exceeds limit: {path}")
        raw = os.pread(descriptor, before.st_size, 0)
        after = os.fstat(descriptor)
        seals = (
            int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
            if fcntl is not None
            else 0
        )
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or _sha256_bytes(raw) != expected_sha256
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
        ):
            raise RuntimeError(f"sealed frozen descriptor rejected: {path}")
        return raw
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if before.st_size > maximum:
            raise RuntimeError(f"frozen file exceeds limit: {path}")
        raw = os.pread(descriptor, before.st_size, 0)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(raw) != before.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or _sha256_bytes(raw) != expected_sha256
    ):
        raise RuntimeError(f"frozen file binding rejected: {path}")
    return raw


def load_freeze(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = _stable_file(path, expected_sha256, 4 << 20)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("freeze manifest is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != FREEZE_SCHEMA:
        raise RuntimeError("freeze manifest schema rejected")
    return payload


def verify_sealed_self(expected_sha256: str, freeze: Mapping[str, Any]) -> dict[str, Any]:
    if fcntl is None or not str(__file__).startswith("/proc/self/fd/"):
        raise RuntimeError("outer controller must execute from a sealed memfd")
    descriptor = int(str(__file__).rsplit("/", 1)[1])
    row = os.fstat(descriptor)
    raw = os.pread(descriptor, row.st_size, 0)
    seals = int(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS))
    actual = _sha256_bytes(raw)
    expected_row = freeze.get("artifacts", {}).get("outer_controller", {})
    if (
        actual != expected_sha256
        or expected_row.get("sha256") != actual
        or expected_row.get("size_bytes") != row.st_size
        or seals & REQUIRED_SEALS != REQUIRED_SEALS
    ):
        raise RuntimeError("sealed outer controller replay rejected")
    return {
        "fd": descriptor,
        "size_bytes": int(row.st_size),
        "sha256": actual,
        "seals": seals,
        "required_seals": REQUIRED_SEALS,
    }


def build_root_command(inner_command: Sequence[str]) -> list[str]:
    return [
        "/usr/bin/python3.12",
        "-I",
        "-S",
        "-B",
        "-c",
        BARRIER_LOADER,
        str(BARRIER_FD),
        "--",
        *inner_command,
    ]


def verify_mode_command(
    mode: str, inner_command: Sequence[str], freeze: Mapping[str, Any]
) -> tuple[list[str], Mapping[str, Any]]:
    commands = freeze.get("commands")
    if not isinstance(commands, dict) or not isinstance(commands.get(mode), dict):
        raise RuntimeError("mode command freeze is missing")
    contract = commands[mode]
    root = build_root_command(inner_command)
    if root != contract.get("argv"):
        raise RuntimeError("mode command differs from frozen exact argv")
    digest = _canonical_argv_sha256(root)
    if digest != contract.get("canonical_argv_sha256"):
        raise RuntimeError("mode command canonical digest drift")
    terminal = "--sealed-import-probe" if mode == "probe" else "--launch"
    if not root or root[-1] != terminal:
        raise RuntimeError("mode command terminal flag rejected")
    forbidden = {"--allow-official-input", "--allow-solver", "--allow-publication"}
    if forbidden.intersection(root):
        raise RuntimeError("outer command contains internal authorization flags")
    return root, contract


def _arm_root(expected_parent: int) -> None:
    if LIBC is None:
        raise RuntimeError("Linux prctl support is required")
    for signum in STOP_SIGNALS:
        signal.signal(signum, signal.SIG_DFL)
    if hasattr(signal, "pthread_sigmask"):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, STOP_SIGNALS)
    os.setsid()
    if LIBC.prctl(PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_SET_PDEATHSIG")
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), SIGKILL)


def _enable_subreaper() -> int:
    if LIBC is None:
        raise RuntimeError("Linux child-subreaper support is required")
    previous = ctypes.c_int()
    if LIBC.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_GET_CHILD_SUBREAPER")
    if LIBC.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_SET_CHILD_SUBREAPER")
    return int(previous.value)


def _restore_subreaper(previous: int) -> None:
    if LIBC is None:
        raise RuntimeError("Linux child-subreaper support is required")
    if LIBC.prctl(PR_SET_CHILD_SUBREAPER, previous, 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "restore child subreaper")


def live_admitted(admitted: Mapping[int, AdmittedMember]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pid, member in sorted(admitted.items()):
        record = proc_record(pid)
        if record is None:
            continue
        if record.identity != member.identity:
            raise _generation_ambiguity_error(
                "live_admitted", pid, member.identity, record.identity
            )
        member.topology = record.topology
        rows.append(
            {
                "pid": pid,
                "identity": [pid, member.identity.starttime],
                "topology": [
                    record.topology.ppid,
                    record.topology.process_group,
                    record.topology.session,
                ],
            }
        )
    return rows


def signal_admitted(
    admitted: Mapping[int, AdmittedMember], signum: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "signal": int(signum),
        "signaled_pids": [],
        "vanished_pids": [],
        "identity_mismatch_pids": [],
        "proc_unknown_pids": [],
        "errors": [],
        "numeric_process_group_signal_sent": False,
    }
    if not hasattr(signal, "pidfd_send_signal"):
        result["errors"].append("pidfd_send_signal_unavailable")
        return result
    for pid, member in sorted(admitted.items(), reverse=True):
        try:
            current = proc_record(pid)
        except ProcInspectionError as exc:
            current = None
            result["proc_unknown_pids"].append(pid)
            result["errors"].append(f"proc_inspection:{pid}:{exc}")
        else:
            if current is None:
                result["vanished_pids"].append(pid)
                continue
            if current.identity != member.identity:
                result["identity_mismatch_pids"].append(pid)
                result["errors"].append(
                    str(
                        _generation_ambiguity_error(
                            "signal_admitted",
                            pid,
                            member.identity,
                            current.identity,
                        )
                    )
                )
                continue
            member.topology = current.topology
        if current is None and pid not in result["proc_unknown_pids"]:
            result["vanished_pids"].append(pid)
            continue
        try:
            signal.pidfd_send_signal(member.pidfd, signum, None, 0)
            result["signaled_pids"].append(pid)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                result["vanished_pids"].append(pid)
            else:
                result["errors"].append(
                    f"pidfd_send:{pid}:{int(exc.errno or errno.EIO)}"
                )
    return result


def _reap_known_children(
    wrapper_pid: int,
    root: subprocess.Popen[bytes] | None,
    admitted: Mapping[int, AdmittedMember],
) -> list[dict[str, int]]:
    reaped: list[dict[str, int]] = []
    if root is not None:
        root.poll()
    for pid, member in sorted(admitted.items()):
        if root is not None and pid == root.pid:
            continue
        record = proc_record(pid)
        if record is None:
            continue
        if record.identity != member.identity:
            raise _generation_ambiguity_error(
                "reap_known_children", pid, member.identity, record.identity
            )
        if record.topology.ppid != wrapper_pid:
            continue
        member.topology = record.topology
        try:
            observed, status = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, ProcessLookupError):
            continue
        except OSError as exc:
            if exc.errno in (errno.ECHILD, errno.ENOENT, errno.ESRCH):
                continue
            raise ProcInspectionError(
                f"waitpid failed: {pid}:{int(exc.errno or errno.EIO)}"
            ) from exc
        if observed:
            reaped.append({"pid": observed, "wait_status": status})
    return reaped


def _append_cleanup_error(errors: list[str], value: str) -> None:
    if value not in errors:
        errors.append(value)


def final_zero_fixed_point(
    *,
    wrapper_pid: int,
    root: subprocess.Popen[bytes] | None,
    root_pid: int,
    admitted: dict[int, AdmittedMember],
    baseline_direct_children: Mapping[int, ProcessIdentity],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    reaped: list[dict[str, int]] = []
    errors: list[str] = []
    snapshots: list[dict[str, Any]] = []
    stable_zero_snapshots = 0
    residual: list[dict[str, Any]] = []
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while True:
        if root is not None:
            root.poll()
        try:
            reaped.extend(_reap_known_children(wrapper_pid, root, admitted))
            discovery = refresh_descendant_registry(
                wrapper_pid=wrapper_pid,
                root_pid=root_pid,
                admitted=admitted,
                baseline_direct_children=baseline_direct_children,
            )
        except BaseException as exc:
            stable_zero_snapshots = 0
            residual = []
            message = f"final_refresh:{type(exc).__name__}:{exc}"
            _append_cleanup_error(errors, message)
            snapshots.append(
                {
                    "index": len(snapshots) + 1,
                    "status": "UNKNOWN",
                    "error": message,
                }
            )
        else:
            try:
                residual = live_admitted(admitted)
            except BaseException as exc:
                stable_zero_snapshots = 0
                residual = []
                message = f"final_liveness:{type(exc).__name__}:{exc}"
                _append_cleanup_error(errors, message)
                snapshots.append(
                    {
                        "index": len(snapshots) + 1,
                        "status": "UNKNOWN",
                        "added_pids": discovery["added_pids"],
                        "error": message,
                    }
                )
            else:
                snapshots.append(
                    {
                        "index": len(snapshots) + 1,
                        "status": "NONZERO" if residual else "ZERO",
                        "added_pids": discovery["added_pids"],
                        "residual_identities": residual,
                    }
                )
                if residual:
                    stable_zero_snapshots = 0
                    action = signal_admitted(admitted, SIGKILL)
                    actions.append(action)
                    for value in action["errors"]:
                        _append_cleanup_error(errors, str(value))
                else:
                    stable_zero_snapshots += 1
                    if stable_zero_snapshots >= FINAL_ZERO_SNAPSHOTS_REQUIRED:
                        break
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
    if residual:
        _append_cleanup_error(errors, "outer_generation_residual_processes")
    if stable_zero_snapshots < FINAL_ZERO_SNAPSHOTS_REQUIRED:
        _append_cleanup_error(errors, "outer_stable_zero_not_established")
    return {
        "actions": actions,
        "reaped": reaped,
        "final_discovery_snapshots": snapshots,
        "stable_zero_snapshots": stable_zero_snapshots,
        "stable_zero_snapshots_required": FINAL_ZERO_SNAPSHOTS_REQUIRED,
        "residual_identities": residual,
        "empty": (
            stable_zero_snapshots >= FINAL_ZERO_SNAPSHOTS_REQUIRED
            and not residual
            and not errors
        ),
        "errors": errors,
        "numeric_process_group_signal_sent": False,
    }


def drain_generation(
    *,
    wrapper_pid: int,
    root: subprocess.Popen[bytes] | None,
    root_pid: int,
    admitted: dict[int, AdmittedMember],
    baseline_direct_children: Mapping[int, ProcessIdentity],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    reaped: list[dict[str, int]] = []
    errors: list[str] = []
    for signum in (signal.SIGTERM, SIGKILL):
        live: list[dict[str, Any]] | None = None
        try:
            refresh_descendant_registry(
                wrapper_pid=wrapper_pid,
                root_pid=root_pid,
                admitted=admitted,
                baseline_direct_children=baseline_direct_children,
            )
            live = live_admitted(admitted)
        except BaseException as exc:
            _append_cleanup_error(
                errors, f"cleanup_refresh:{type(exc).__name__}:{exc}"
            )
        if live is None or live:
            action = signal_admitted(admitted, signum)
            actions.append(action)
            for value in action["errors"]:
                _append_cleanup_error(errors, str(value))
        deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
        while time.monotonic() < deadline:
            if root is not None:
                root.poll()
            try:
                reaped.extend(_reap_known_children(wrapper_pid, root, admitted))
                refresh_descendant_registry(
                    wrapper_pid=wrapper_pid,
                    root_pid=root_pid,
                    admitted=admitted,
                    baseline_direct_children=baseline_direct_children,
                )
                live = live_admitted(admitted)
            except BaseException as exc:
                live = None
                _append_cleanup_error(
                    errors, f"cleanup_refresh:{type(exc).__name__}:{exc}"
                )
            if live == []:
                break
            time.sleep(POLL_SECONDS)
        if live == []:
            break
    final = final_zero_fixed_point(
        wrapper_pid=wrapper_pid,
        root=root,
        root_pid=root_pid,
        admitted=admitted,
        baseline_direct_children=baseline_direct_children,
    )
    actions.extend(final["actions"])
    reaped.extend(final["reaped"])
    for value in final["errors"]:
        _append_cleanup_error(errors, str(value))
    return {
        "actions": actions,
        "reaped": reaped,
        "final_discovery_snapshots": final["final_discovery_snapshots"],
        "stable_zero_snapshots": final["stable_zero_snapshots"],
        "stable_zero_snapshots_required": final["stable_zero_snapshots_required"],
        "residual_identities": final["residual_identities"],
        "empty": bool(final["empty"] and not errors),
        "errors": errors,
        "numeric_process_group_signal_sent": False,
    }


def _retained_bytes(descriptor: int, maximum: int) -> bytes:
    row = os.fstat(descriptor)
    if row.st_size > maximum:
        raise RuntimeError("retained output exceeds limit")
    raw = os.pread(descriptor, row.st_size, 0)
    if len(raw) != row.st_size:
        raise RuntimeError("retained output short read")
    return raw


def exact_json_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        payload, end = json.JSONDecoder().raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("inner stdout is not one JSON object") from exc
    if text[end:].strip() or not isinstance(payload, dict):
        raise RuntimeError("inner stdout has a suffix or non-object value")
    return payload


def validate_inner_truth(mode: str, payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if mode == "probe":
        expected = {
            "status": "PASS",
            "official_instance_opened": False,
            "solver_child_process_started": False,
            "solver_execution_started": False,
            "publication": False,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                errors.append(f"probe_truth:{key}")
    elif payload.get("status") != "COMPLETION_VALID":
        errors.append(f"launch_inner_status:{payload.get('status')}")
    return errors


def _initial_resource_gate() -> tuple[list[dict[str, int]], str | None]:
    samples = [host_sample()]
    if samples[0]["mem_available_kib"] < INITIAL_MEMAVAILABLE_FLOOR_KIB:
        return samples, "initial_memavailable_floor:first"
    time.sleep(INITIAL_SAMPLE_INTERVAL_SECONDS)
    samples.append(host_sample())
    if samples[1]["mem_available_kib"] < INITIAL_MEMAVAILABLE_FLOOR_KIB:
        return samples, "initial_memavailable_floor:second"
    return samples, None


def run_controlled(
    *,
    mode: str,
    root_command: list[str],
    command_contract: Mapping[str, Any],
    freeze: Mapping[str, Any],
    self_binding: Mapping[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    wall_seconds = (
        PROBE_OUTER_WALL_SECONDS if mode == "probe" else LAUNCH_OUTER_WALL_SECONDS
    )
    initial_samples, initial_gate = _initial_resource_gate()
    if initial_gate is not None:
        return {
            "schema": SCHEMA,
            "status": "NO_GO",
            "mode": mode,
            "resource_gate": initial_gate,
            "initial_host_samples": initial_samples,
            "root_process_started": False,
            "probe_child_process_started": False,
            "solver_child_process_started": False,
            "official_instance_opened": False,
            "publication": False,
        }
    storage_contract = freeze.get("sealed_storage_contract", {}).get(mode)
    if not isinstance(storage_contract, dict):
        raise RuntimeError("mode sealed-storage contract is missing")
    sealed = sealed_reservation(storage_contract)
    wrapper_pid = os.getpid()
    wrapper_identity = proc_identity(wrapper_pid)
    if wrapper_identity is None:
        raise RuntimeError("outer controller identity unavailable")
    previous_subreaper = _enable_subreaper()
    baseline = {
        pid: record.identity
        for pid, record in proc_snapshot().items()
        if record.topology.ppid == wrapper_pid
    }
    stop_state: dict[str, int | None] = {"signal": None}
    previous_handlers: dict[int, Any] = {}
    for signum in STOP_SIGNALS:
        previous_handlers[signum] = signal.signal(
            signum,
            lambda observed, _frame: stop_state.__setitem__("signal", observed),
        )
    stdout_fd = os.memfd_create("aghfal17-v17-inner-stdout")
    stderr_fd = os.memfd_create("aghfal17-v17-inner-stderr")
    report_fd = os.memfd_create("aghfal17-v17-outer-report")
    root: subprocess.Popen[bytes] | None = None
    barrier_read = barrier_write = -1
    admitted: dict[int, AdmittedMember] = {}
    errors: list[str] = []
    breach: str | None = None
    peak: dict[str, Any] | None = None
    cleanup: dict[str, Any] = {
        "empty": False,
        "residual_identities": [],
        "actions": [],
        "errors": [],
        "stable_zero_snapshots": 0,
        "stable_zero_snapshots_required": FINAL_ZERO_SNAPSHOTS_REQUIRED,
    }
    root_pid = -1
    child_exit_code: int | None = None
    try:
        barrier_read, barrier_write = os.pipe2(os.O_CLOEXEC)
        try:
            os.fstat(BARRIER_FD)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise
        else:
            raise RuntimeError(f"fixed barrier descriptor is already occupied: {BARRIER_FD}")
        os.dup2(barrier_read, BARRIER_FD, inheritable=True)
        os.close(barrier_read)
        barrier_read = -1
        parent_pid = os.getpid()
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "AGHFAL_NATIVE_V17_OUTER_CONTROLLER": "1",
        }
        root = subprocess.Popen(
            root_command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_fd,
            stderr=stderr_fd,
            close_fds=True,
            pass_fds=(BARRIER_FD,),
            env=environment,
            preexec_fn=lambda: _arm_root(parent_pid),
        )
        root_pid = root.pid
        root_record = proc_record(root_pid)
        if root_record is None:
            raise RuntimeError("barrier-stopped root identity unavailable")
        admit_member(admitted, root_pid, root_record)
        refresh_descendant_registry(
            wrapper_pid=wrapper_pid,
            root_pid=root_pid,
            admitted=admitted,
            baseline_direct_children=baseline,
        )
        initial_accounting = accounting_sample(
            wrapper_pid=wrapper_pid,
            wrapper_identity=wrapper_identity,
            admitted=admitted,
        )
        initial_reports = retained_report_bytes(stdout_fd, stderr_fd, report_fd)
        initial_breach = resource_breach(
            elapsed_seconds=time.monotonic() - started,
            process_rss_kib=initial_accounting["process_vmrss_kib"],
            process_swap_kib=initial_accounting["process_vmswap_kib"],
            process_group_charges_kib=initial_accounting["process_group_charges_kib"],
            sealed_bytes=sealed["reserved_bytes"],
            report_bytes=initial_reports,
            mem_available_kib=host_sample()["mem_available_kib"],
            wall_seconds=wall_seconds,
            accounting_errors=initial_accounting["unavailable"],
        )
        if initial_breach is not None:
            breach = f"pre_barrier:{initial_breach}"
        else:
            os.write(barrier_write, BARRIER_TOKEN)
        os.close(barrier_write)
        barrier_write = -1
        while breach is None:
            refresh_descendant_registry(
                wrapper_pid=wrapper_pid,
                root_pid=root_pid,
                admitted=admitted,
                baseline_direct_children=baseline,
            )
            sample = accounting_sample(
                wrapper_pid=wrapper_pid,
                wrapper_identity=wrapper_identity,
                admitted=admitted,
            )
            report_bytes = retained_report_bytes(stdout_fd, stderr_fd, report_fd)
            host = host_sample()
            charge = (
                sample["process_vmrss_kib"]
                + sample["process_vmswap_kib"]
                + math.ceil((sealed["reserved_bytes"] + report_bytes) / 1024)
            )
            if peak is None or charge > peak["whole_launch_charged_kib"]:
                peak = {
                    **sample,
                    "sealed_reserved_bytes": sealed["reserved_bytes"],
                    "retained_report_bytes": report_bytes,
                    "whole_launch_charged_kib": charge,
                    "host_sample": host,
                    "elapsed_seconds": time.monotonic() - started,
                }
            breach = resource_breach(
                elapsed_seconds=time.monotonic() - started,
                process_rss_kib=sample["process_vmrss_kib"],
                process_swap_kib=sample["process_vmswap_kib"],
                process_group_charges_kib=sample["process_group_charges_kib"],
                sealed_bytes=sealed["reserved_bytes"],
                report_bytes=report_bytes,
                mem_available_kib=host["mem_available_kib"],
                wall_seconds=wall_seconds,
                accounting_errors=sample["unavailable"],
            )
            if stop_state["signal"] is not None:
                breach = f"external_signal:{stop_state['signal']}"
            child_exit_code = root.poll()
            _reap_known_children(wrapper_pid, root, admitted)
            if child_exit_code is not None:
                refresh_descendant_registry(
                    wrapper_pid=wrapper_pid,
                    root_pid=root_pid,
                    admitted=admitted,
                    baseline_direct_children=baseline,
                )
                _reap_known_children(wrapper_pid, root, admitted)
                if not live_admitted(admitted):
                    break
            if breach is None:
                time.sleep(POLL_SECONDS)
    except BaseException as exc:
        errors.append(f"outer_exception:{type(exc).__name__}:{exc}")
    finally:
        if barrier_write >= 0:
            os.close(barrier_write)
        if barrier_read >= 0:
            os.close(barrier_read)
        try:
            os.close(BARRIER_FD)
        except OSError:
            pass
        cleanup = drain_generation(
            wrapper_pid=wrapper_pid,
            root=root,
            root_pid=root_pid,
            admitted=admitted,
            baseline_direct_children=baseline,
        )
        errors.extend(str(value) for value in cleanup["errors"])
        if root is not None:
            child_exit_code = root.poll()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        _restore_subreaper(previous_subreaper)
    stdout_raw = _retained_bytes(stdout_fd, MAX_STDOUT_BYTES)
    stderr_raw = _retained_bytes(stderr_fd, MAX_STDERR_BYTES)
    inner_payload: dict[str, Any] = {}
    try:
        inner_payload = exact_json_object(stdout_raw)
    except RuntimeError as exc:
        errors.append(f"inner_envelope:{exc}")
    if child_exit_code != 0:
        errors.append(f"contained_root_exit:{child_exit_code}")
    if not cleanup.get("empty", False):
        errors.append("outer_cleanup_not_empty")
    if inner_payload:
        errors.extend(validate_inner_truth(mode, inner_payload))
    if breach is not None:
        errors.append(f"resource_or_signal_breach:{breach}")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": (
            "PASS"
            if mode == "probe" and not errors
            else "COMPLETION_VALID"
            if mode == "launch" and not errors
            else "FAILED"
        ),
        "mode": mode,
        "errors": errors,
        "breach": breach,
        "outer_authoritative": True,
        "outer_wall_seconds": wall_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "whole_launch_memory_limit_kib": WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
        "process_generation_memory_limit_kib": PROCESS_GENERATION_MEMORY_LIMIT_KIB,
        "initial_memavailable_floor_kib": INITIAL_MEMAVAILABLE_FLOOR_KIB,
        "runtime_memavailable_floor_kib": RUNTIME_MEMAVAILABLE_FLOOR_KIB,
        "initial_host_samples": initial_samples,
        "canonical_argv_encoding": "utf8_nul_joined",
        "canonical_argv_sha256": command_contract["canonical_argv_sha256"],
        "root_command": root_command,
        "sealed_controller": dict(self_binding),
        "sealed_storage": sealed,
        "peak_accounting": peak,
        "cleanup": cleanup,
        "contained_root_exit_code": child_exit_code,
        "inner_payload": inner_payload,
        "inner_stdout": {
            "transport": "outer_created_retained_memfd",
            "size_bytes": len(stdout_raw),
            "sha256": _sha256_bytes(stdout_raw),
        },
        "inner_stderr": {
            "transport": "outer_created_retained_memfd",
            "size_bytes": len(stderr_raw),
            "sha256": _sha256_bytes(stderr_raw),
        },
        "root_process_started": root is not None,
        "probe_child_process_started": mode == "probe" and root is not None,
        "solver_child_process_started": (
            inner_payload.get("solver_child_process_started", False)
            if inner_payload
            else False
        ),
        "official_instance_opened": (
            inner_payload.get("official_instance_opened", False)
            if inner_payload
            else False
        ),
        "publication": (
            inner_payload.get("publication", False) if inner_payload else False
        ),
        "post_exit_empty": bool(cleanup.get("empty")),
        "numeric_process_group_signal_sent": False,
    }
    report_raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    os.write(report_fd, report_raw)
    final_report_bytes = retained_report_bytes(stdout_fd, stderr_fd, report_fd)
    if peak is not None:
        final_charge = (
            peak["process_vmrss_kib"]
            + peak["process_vmswap_kib"]
            + math.ceil((sealed["reserved_bytes"] + final_report_bytes) / 1024)
        )
        if final_charge >= WHOLE_LAUNCH_MEMORY_LIMIT_KIB and payload["status"] != "FAILED":
            payload["status"] = "FAILED"
            payload["errors"].append("final_report_memory_limit")
    for descriptor in (stdout_fd, stderr_fd, report_fd):
        os.close(descriptor)
    for member in admitted.values():
        try:
            os.close(member.pidfd)
        except OSError:
            pass
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "launch"), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    inner_command = list(args.command)
    if inner_command and inner_command[0] == "--":
        inner_command.pop(0)
    freeze = load_freeze(args.freeze, args.expected_freeze_sha256)
    self_binding = verify_sealed_self(args.expected_controller_sha256, freeze)
    root_command, command_contract = verify_mode_command(
        args.mode, inner_command, freeze
    )
    payload = run_controlled(
        mode=args.mode,
        root_command=root_command,
        command_contract=command_contract,
        freeze=freeze,
        self_binding=self_binding,
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)
    accepted = "PASS" if args.mode == "probe" else "COMPLETION_VALID"
    return 0 if payload.get("status") == accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
