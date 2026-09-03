#!/usr/bin/env python3
"""Outer whole-tree containment for the AGH-FAL17 v9 import-only probe."""

from __future__ import annotations

import argparse
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
OUTER_WALL_SECONDS = 240.0
TERMINATION_GRACE_SECONDS = 1.0
POLL_SECONDS = 0.05
STOP_SIGNALS = tuple(
    dict.fromkeys(
        (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM))
    )
)
LIBC = ctypes.CDLL(None, use_errno=True)
PR_SET_PDEATHSIG = 1


def proc_identity(pid: int) -> tuple[int, int, int, int] | None:
    """Return (ppid, process-group, session, starttime) for an exact PID."""

    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    close = raw.rfind(")")
    fields = raw[close + 2 :].split() if close >= 0 else []
    if len(fields) < 20:
        return None
    try:
        return int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19])
    except ValueError:
        return None


def proc_snapshot() -> dict[int, tuple[int, int, int, int]]:
    result: dict[int, tuple[int, int, int, int]] = {}
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError:
        return result
    for entry in entries:
        if entry.name.isdigit():
            identity = proc_identity(int(entry.name))
            if identity is not None:
                result[int(entry.name)] = identity
    return result


def refresh_descendant_registry(
    wrapper_pid: int,
    root_pid: int,
    admitted: dict[int, tuple[int, int, int, int]],
) -> dict[str, Any]:
    """Append descendants proved by the retained subreaper parent chain."""

    snapshot = proc_snapshot()
    added: list[int] = []
    changed = True
    while changed:
        changed = False
        live_parents = {
            pid
            for pid, identity in admitted.items()
            if snapshot.get(pid) == identity
        }
        for pid, identity in sorted(snapshot.items()):
            if pid in admitted:
                continue
            ppid = identity[0]
            if (pid == root_pid and ppid == wrapper_pid) or ppid in live_parents:
                admitted[pid] = identity
                added.append(pid)
                changed = True
                continue
            # A descendant orphaned after its parent exits is reparented to
            # this retained subreaper.  The wrapper creates no unrelated child.
            if ppid == wrapper_pid and pid != root_pid:
                admitted[pid] = identity
                added.append(pid)
                changed = True
    return {
        "added_pids": added,
        "live_admitted_pids": sorted(
            pid for pid, identity in admitted.items() if snapshot.get(pid) == identity
        ),
    }


def signal_admitted(
    admitted: dict[int, tuple[int, int, int, int]], signum: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "signal": int(signum),
        "attempted_pids": [],
        "signaled_pids": [],
        "vanished_pids": [],
        "identity_mismatch_pids": [],
        "errors": [],
        "numeric_process_group_signal_sent": False,
    }
    for pid, identity in sorted(admitted.items(), reverse=True):
        if proc_identity(pid) != identity:
            result["vanished_pids"].append(pid)
            continue
        result["attempted_pids"].append(pid)
        try:
            pidfd = os.pidfd_open(pid, 0)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                result["vanished_pids"].append(pid)
            else:
                result["errors"].append(
                    f"pidfd_open:{pid}:{int(exc.errno or errno.EIO)}"
                )
            continue
        try:
            if proc_identity(pid) != identity:
                result["identity_mismatch_pids"].append(pid)
                continue
            try:
                signal.pidfd_send_signal(pidfd, signum, None, 0)
            except OSError as exc:
                if exc.errno == errno.ESRCH:
                    result["vanished_pids"].append(pid)
                else:
                    result["errors"].append(
                        f"pidfd_send:{pid}:{int(exc.errno or errno.EIO)}"
                    )
                continue
            result["signaled_pids"].append(pid)
        finally:
            try:
                os.close(pidfd)
            except OSError as exc:
                result["errors"].append(
                    f"pidfd_close:{pid}:{int(exc.errno or errno.EIO)}"
                )
    return result


def live_admitted(
    admitted: dict[int, tuple[int, int, int, int]]
) -> list[dict[str, Any]]:
    return [
        {"pid": pid, "identity": list(identity)}
        for pid, identity in sorted(admitted.items())
        if proc_identity(pid) == identity
    ]


def reap_children() -> list[dict[str, int]]:
    reaped: list[dict[str, int]] = []
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        except OSError as exc:
            if exc.errno == errno.ECHILD:
                break
            raise
        if pid == 0:
            break
        reaped.append({"pid": pid, "wait_status": status})
    return reaped


def _arm_contained_root(expected_parent: int) -> None:
    for signum in STOP_SIGNALS:
        signal.signal(signum, signal.SIG_DFL)
    if hasattr(signal, "pthread_sigmask"):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, STOP_SIGNALS)
    if LIBC.prctl(PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_SET_PDEATHSIG")
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)


def _retained_bytes(descriptor: int, maximum: int) -> bytes:
    row = os.fstat(descriptor)
    if row.st_size > maximum:
        raise RuntimeError("retained descriptor size rejected")
    raw = os.pread(descriptor, row.st_size, 0)
    if len(raw) != row.st_size:
        raise RuntimeError("retained descriptor short read")
    return raw


def _exact_json_envelope(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        decoder = json.JSONDecoder()
        payload, end = decoder.raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("inner stdout is not one JSON envelope") from exc
    if text[end:].strip() or not isinstance(payload, dict):
        raise RuntimeError("inner stdout contains concatenated or non-object JSON")
    return payload


def run_contained(
    command: list[str],
    wall_seconds: float,
    *,
    expected_command_sha256: str,
    pass_fds: tuple[int, ...] = (),
) -> dict[str, Any]:
    command_raw = json.dumps(
        command, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    if sha256(command_raw).hexdigest() != expected_command_sha256:
        raise RuntimeError("sealed outer command hash mismatch")
    if "--sealed-import-probe" not in command:
        raise RuntimeError("outer harness requires sealed import probe mode")
    forbidden = {
        "--execute-completion",
        "--allow-official-input",
        "--allow-solver",
        "--allow-publication",
    }
    if forbidden.intersection(command):
        raise RuntimeError("outer harness rejects official or solver authorization")
    previous_subreaper = ctypes.c_int()
    if LIBC.prctl(
        PR_GET_CHILD_SUBREAPER, ctypes.byref(previous_subreaper), 0, 0, 0
    ) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_GET_CHILD_SUBREAPER")
    if LIBC.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), "PR_SET_CHILD_SUBREAPER")
    started = time.monotonic()
    stop_state: dict[str, int | None] = {"signal": None}
    previous: dict[int, Any] = {}
    for signum in STOP_SIGNALS:
        previous[signum] = signal.signal(
            signum,
            lambda observed, _frame: stop_state.__setitem__("signal", observed),
        )
    child: subprocess.Popen[bytes] | None = None
    admitted: dict[int, tuple[int, int, int, int]] = {}
    actions: list[dict[str, Any]] = []
    reaped: list[dict[str, int]] = []
    reason = "normal_exit"
    errors: list[str] = []
    stdout_fd = os.memfd_create("aghfal17-v9-probe-stdout")
    stderr_fd = os.memfd_create("aghfal17-v9-probe-stderr")
    report_fd = os.memfd_create("aghfal17-v9-probe-report")
    for descriptor in (stdout_fd, stderr_fd, report_fd):
        os.fchmod(descriptor, 0o400)
    try:
        parent_pid = os.getpid()
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_fd,
            stderr=stderr_fd,
            close_fds=True,
            pass_fds=pass_fds,
            start_new_session=True,
            preexec_fn=lambda: _arm_contained_root(parent_pid),
        )
        identity = proc_identity(child.pid)
        if identity is None:
            raise RuntimeError("outer harness root identity unavailable")
        admitted[child.pid] = identity
        while child.poll() is None:
            refresh_descendant_registry(os.getpid(), child.pid, admitted)
            if stop_state["signal"] is not None:
                reason = f"signal:{stop_state['signal']}"
                break
            if time.monotonic() - started >= wall_seconds:
                reason = "outer_hard_wall"
                break
            time.sleep(POLL_SECONDS)
    except BaseException as exc:
        reason = "outer_exception"
        errors.append(f"{type(exc).__name__}:{exc}")
    finally:
        if child is not None:
            try:
                refresh_descendant_registry(os.getpid(), child.pid, admitted)
            except BaseException as exc:
                errors.append(f"cleanup_refresh:{type(exc).__name__}:{exc}")
        if child is not None and (child.poll() is None or live_admitted(admitted)):
            actions.append(signal_admitted(admitted, signal.SIGTERM))
            deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
            while time.monotonic() < deadline:
                try:
                    refresh_descendant_registry(os.getpid(), child.pid, admitted)
                except BaseException as exc:
                    errors.append(f"term_refresh:{type(exc).__name__}:{exc}")
                child.poll()
                try:
                    reaped.extend(reap_children())
                except BaseException as exc:
                    errors.append(f"term_reap:{type(exc).__name__}:{exc}")
                if not live_admitted(admitted):
                    break
                time.sleep(POLL_SECONDS)
            residual = live_admitted(admitted)
            if residual:
                actions.append(signal_admitted(admitted, signal.SIGKILL))
        if child is not None:
            deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
            while time.monotonic() < deadline:
                try:
                    refresh_descendant_registry(os.getpid(), child.pid, admitted)
                except BaseException as exc:
                    errors.append(f"kill_refresh:{type(exc).__name__}:{exc}")
                child.poll()
                try:
                    reaped.extend(reap_children())
                except BaseException as exc:
                    errors.append(f"kill_reap:{type(exc).__name__}:{exc}")
                if not live_admitted(admitted):
                    break
                time.sleep(POLL_SECONDS)
            child.poll()
            try:
                reaped.extend(reap_children())
            except BaseException as exc:
                errors.append(f"final_reap:{type(exc).__name__}:{exc}")
        residual = live_admitted(admitted)
        errors.extend(
            error for action in actions for error in action.get("errors", ())
        )
        if residual:
            errors.append("outer_containment_residual_processes")
        child_exit_code = None if child is None else child.returncode
        if child is not None and child_exit_code is None:
            errors.append("contained_root_exit_unavailable")
        elif child_exit_code != 0:
            errors.append(f"contained_root_exit:{child_exit_code}")
        try:
            stdout_raw = _retained_bytes(stdout_fd, 64 << 20)
            stderr_raw = _retained_bytes(stderr_fd, 32 << 20)
        except BaseException as exc:
            stdout_raw = b""
            stderr_raw = b""
            errors.append(f"retained_output:{type(exc).__name__}:{exc}")
        inner_payload: dict[str, Any] = {}
        try:
            inner_payload = _exact_json_envelope(stdout_raw)
        except BaseException as exc:
            errors.append(f"inner_envelope:{type(exc).__name__}:{exc}")
        inner_status = inner_payload.get("status")
        if inner_status != "PASS":
            errors.append(f"inner_status:{inner_status}")
        payload = {
            "schema": "planora.agh-fal17.native-v9-probe-harness.v1",
            "status": "PASS" if not errors else "FAILED",
            "containment_mode": "linux_subreaper_exact_generation_registry",
            "reason": reason,
            "outer_wall_seconds": wall_seconds,
            "elapsed_seconds": time.monotonic() - started,
            "root_process_started": child is not None,
            "probe_child_process_started": child is not None,
            "solver_child_process_started": False,
            "official_opened": False,
            "publication": False,
            "admitted_identities": [
                {"pid": pid, "identity": list(identity)}
                for pid, identity in sorted(admitted.items())
            ],
            "actions": actions,
            "reaped": reaped,
            "final_residual_identities": residual,
            "post_exit_empty": not residual,
            "errors": errors,
            "numeric_process_group_signal_sent": False,
            "contained_root_exit_code": child_exit_code,
            "inner_payload": inner_payload,
            "inner_stdout": {
                "transport": "parent_created_retained_memfd",
                "size": len(stdout_raw),
                "sha256": sha256(stdout_raw).hexdigest(),
                "exact_single_json_envelope": bool(inner_payload),
            },
            "inner_stderr": {
                "transport": "parent_created_retained_memfd",
                "size": len(stderr_raw),
                "sha256": sha256(stderr_raw).hexdigest(),
            },
            "report_transport": "parent_created_retained_memfd",
            "command_sha256": expected_command_sha256,
            "command": command,
        }
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if LIBC.prctl(
            PR_SET_CHILD_SUBREAPER, int(previous_subreaper.value), 0, 0, 0
        ) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), "restore child subreaper")
        report_raw = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        os.write(report_fd, report_raw)
        replay = _retained_bytes(report_fd, 128 << 20)
        if replay != report_raw:
            raise RuntimeError("retained harness report replay mismatch")
        for descriptor in (stdout_fd, stderr_fd, report_fd):
            os.close(descriptor)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wall-seconds", type=float, default=OUTER_WALL_SECONDS)
    parser.add_argument("--expected-command-sha256", required=True)
    parser.add_argument("--pass-fd", type=int, action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command or not 0.05 <= args.wall_seconds <= OUTER_WALL_SECONDS:
        raise SystemExit("invalid outer probe harness invocation")
    payload = run_contained(
        command,
        args.wall_seconds,
        expected_command_sha256=args.expected_command_sha256,
        pass_fds=tuple(args.pass_fd),
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
