from __future__ import annotations

from dataclasses import asdict
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ortools.sat.python import cp_model  # noqa: E402

from benchmarks.itc2019 import parse_itc2019_xml  # noqa: E402
from benchmarks.itc2019_timetable_factorized import (  # noqa: E402
    ITC2019TimetableFactorizedLimits,
    ITC2019TimetableFactorizedResult,
    ITC2019TimetableFactorizedTelemetry,
    solve_itc2019_timetable_factorized,
)


ATTEMPT_SCHEMA = "planora.itc2019.pu-official-build-only-attempt.v4"
AUTHORIZATION_SCHEMA = "planora.itc2019.pu-official-build-only-authorization.v4"
CLAIM_SCHEMA = "planora.itc2019.pu-official-build-only-claim.v2"
HANDOFF_SCHEMA = "planora.itc2019.pu-official-build-only-handoff.v2"
WORKER_SCHEMA = "planora.itc2019.pu-official-build-only-worker-result.v3"
EVENT_SCHEMA = "planora.itc2019.pu-official-build-only-worker-event.v3"
RUN_ID = "eae925cd87c14cab8eee558288804331"
AUTHORIZATION_RELATIVE_PATH = (
    "output/diagnostic-receipts/"
    "pu-proj-timetable-build-only-authorization-20260827T074804Z.receipt.json"
)
AUTHORIZATION_PATH = ROOT / AUTHORIZATION_RELATIVE_PATH
RECEIPT_RELATIVE_PATH = (
    f"output/diagnostic-receipts/pu-proj-official-build-only-{RUN_ID}.receipt.json"
)
RECEIPT_PATH = ROOT / RECEIPT_RELATIVE_PATH
CLAIM_RELATIVE_PATH = (
    f"output/diagnostic-receipts/.pu-proj-official-build-only-{RUN_ID}.claim.json"
)
CLAIM_PATH = ROOT / CLAIM_RELATIVE_PATH
HANDOFF_RELATIVE_PATH = (
    f"output/diagnostic-receipts/.pu-proj-official-build-only-{RUN_ID}.handoff.json"
)
HANDOFF_PATH = ROOT / HANDOFF_RELATIVE_PATH
WORKER_RESULT_PATH = ROOT / (
    f"output/diagnostic-receipts/.pu-proj-official-build-only-{RUN_ID}.worker.json"
)
EVENT_PATHS = {
    name: ROOT
    / (f"output/diagnostic-receipts/.pu-proj-official-build-only-{RUN_ID}.{name}.json")
    for name in (
        "parse-started",
        "parse-completed",
        "build-started",
        "build-completed",
    )
}
EVENT_SEQUENCE = (
    "parse-started",
    "parse-completed",
    "build-started",
    "build-completed",
)
EVENT_SEQUENCE_NUMBERS = {
    name: index for index, name in enumerate(EVENT_SEQUENCE, start=1)
}
INPUT_RELATIVE_PATH = (
    "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/pu-proj-fal19.xml"
)
INPUT_PATH = ROOT / INPUT_RELATIVE_PATH
ADMISSION_RELATIVE_PATH = (
    "output/diagnostic-receipts/"
    "pu-proj-sameattendees-static-admission-20260827T060819Z.receipt.json"
)
ADMISSION_PATH = ROOT / ADMISSION_RELATIVE_PATH
IMMEDIATE_PREDECESSOR_RUN_ID = "7ecfd6634c67485482511601ce77fe62"
IMMEDIATE_PREDECESSOR_RECEIPT_RELATIVE_PATH = (
    "output/diagnostic-receipts/"
    f"pu-proj-official-build-only-{IMMEDIATE_PREDECESSOR_RUN_ID}.receipt.json"
)
IMMEDIATE_PREDECESSOR_RECEIPT_PATH = ROOT / IMMEDIATE_PREDECESSOR_RECEIPT_RELATIVE_PATH
ORIGINAL_PREDECESSOR_RUN_ID = "272c5f5f26134297a756f9936673e0e9"
ORIGINAL_PREDECESSOR_RECEIPT_RELATIVE_PATH = (
    "output/diagnostic-receipts/"
    f"pu-proj-official-build-only-{ORIGINAL_PREDECESSOR_RUN_ID}.receipt.json"
)
ORIGINAL_PREDECESSOR_RECEIPT_PATH = ROOT / ORIGINAL_PREDECESSOR_RECEIPT_RELATIVE_PATH
REVIEW_TEST_RELATIVE_PATH = "tests/test_run_pu_official_build_only_receipt.py"
REVIEW_TEST_PATH = ROOT / REVIEW_TEST_RELATIVE_PATH

BUILD_TIME_LIMIT_SECONDS = 570.0
PROCESS_WALL_CLOCK_LIMIT_SECONDS = 600.0
HANDOFF_WAIT_LIMIT_SECONDS = 15.0
HANDOFF_POLL_INTERVAL_SECONDS = 0.05
MIN_AVAILABLE_PHYSICAL_MEMORY_BYTES = 3 * 1024 * 1024 * 1024
MEMORY_READING_COUNT = 2
MEMORY_READING_INTERVAL_SECONDS = 5.0
WORKERS = 1
RANDOM_SEED = 0
EXPECTED_INPUT_SHA256 = (
    "2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42"
)
EXPECTED_SOURCE_SHA256 = {
    "benchmarks/itc2019.py": (
        "5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f"
    ),
    "benchmarks/itc2019_factorized.py": (
        "959be9e028773492538c4a541892955d37c5cdeb02cfaa762d8b9ce3fff48f02"
    ),
    "benchmarks/itc2019_timetable_factorized.py": (
        "6cd00de292d82bab6ac24a841c93290d1fd4feb8acc3053d96c4e6b2b43e9df3"
    ),
}
EXPECTED_ADMISSION_RECEIPT_SHA256 = (
    "faf895884249bcd2ef8d576600504f6b80cf2cc106a782e920f01ae90cc997b2"
)
EXPECTED_IMMEDIATE_PREDECESSOR_RECEIPT_SHA256 = (
    "6ca57f17789d19dd829734854203680bb387cc6f49b1691194e4112d26e1e136"
)
EXPECTED_ORIGINAL_PREDECESSOR_RECEIPT_SHA256 = (
    "7664bd1ad3513d091da6e00eebe5fe86106197e0df1748231116b86854c78ae8"
)
EXPECTED_REVIEW_TEST_SHA256 = (
    "4be8600cf34bfd146302de6126fc88c6b065c286f1e2849fcbe06f1c804df823"
)
EXPECTED_ADMISSION = {
    "prepared_relations": 12_041,
    "room_pair_evaluations": 2_377_059,
}
CONSTRUCTION_LIMITS = asdict(ITC2019TimetableFactorizedLimits())
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MINIMAL_CLAIM_ERROR_BYTES = (
    "{\n"
    f'  "run_id": "{RUN_ID}",\n'
    f'  "schema": "{ATTEMPT_SCHEMA}",\n'
    '  "outcome": "ERROR",\n'
    '  "error": {"code": "POST_CLAIM_FAILURE"}\n'
    "}\n"
).encode("ascii")
FALLBACK_RECEIPT_TEMP_PATH = RECEIPT_PATH.with_name(
    f".{RECEIPT_PATH.name}.claim-error.tmp"
)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_identity(pid: int) -> dict[str, int]:
    if type(pid) is not int or pid <= 0:
        raise RuntimeError("process PID must be a positive exact integer")
    if os.name != "nt":
        raise RuntimeError("process identity requires the reviewed Windows host")
    kernel32 = ctypes.windll.kernel32
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise RuntimeError("could not open process for identity capture")
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    try:
        get_process_times = kernel32.GetProcessTimes
        get_process_times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        get_process_times.restype = wintypes.BOOL
        if not get_process_times(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise RuntimeError("could not read process creation identity")
    finally:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(handle)
    creation_time_100ns = (int(creation.dwHighDateTime) << 32) | int(
        creation.dwLowDateTime
    )
    return {"pid": pid, "creation_time_100ns": creation_time_100ns}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json_text(text: str) -> dict[str, object]:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise RuntimeError(f"non-standard JSON constant: {value}")

    payload = json.loads(
        text,
        object_pairs_hook=pairs_hook,
        parse_constant=reject_constant,
    )
    if type(payload) is not dict:
        raise RuntimeError("JSON evidence must contain an object")
    return payload


def _strict_json(path: Path) -> dict[str, object]:
    return _strict_json_text(path.read_text(encoding="utf-8"))


def _strict_json_with_evidence(
    path: Path,
) -> tuple[dict[str, object], bytes, dict[str, object]]:
    if path.is_symlink():
        raise RuntimeError("symbolic-link JSON evidence path rejected")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RuntimeError("JSON evidence path is not a regular file")
    with resolved.open("rb") as stream:
        before = os.fstat(stream.fileno())
        encoded = stream.read()
        after = os.fstat(stream.fileno())
    stable_fields_before = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_size),
        int(before.st_mtime_ns),
    )
    stable_fields_after = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_size),
        int(after.st_mtime_ns),
    )
    if stable_fields_before != stable_fields_after or len(encoded) != after.st_size:
        raise RuntimeError("JSON evidence changed while being read")
    if path.is_symlink() or path.resolve(strict=True) != resolved:
        raise RuntimeError("JSON evidence path identity changed")
    current = resolved.stat()
    stable_fields_current = (
        int(current.st_dev),
        int(current.st_ino),
        int(current.st_size),
        int(current.st_mtime_ns),
    )
    if stable_fields_current != stable_fields_after:
        raise RuntimeError("JSON evidence file identity changed")
    evidence = {
        "resolved_path": os.path.normcase(str(resolved)),
        "device": stable_fields_after[0],
        "inode": stable_fields_after[1],
        "size": stable_fields_after[2],
        "mtime_ns": stable_fields_after[3],
    }
    return _strict_json_text(encoded.decode("utf-8")), encoded, evidence


def _type_exact_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if type(expected) is dict:
        observed_dict = observed
        expected_dict = expected
        if set(observed_dict) != set(expected_dict):
            return False
        return all(
            _type_exact_equal(observed_dict[key], expected_dict[key])
            for key in expected_dict
        )
    if type(expected) is list:
        observed_list = observed
        expected_list = expected
        return len(observed_list) == len(expected_list) and all(
            _type_exact_equal(left, right)
            for left, right in zip(observed_list, expected_list, strict=True)
        )
    return bool(observed == expected)


def _require_type_exact_equal(observed: object, expected: object, label: str) -> None:
    if not _type_exact_equal(observed, expected):
        raise RuntimeError(f"{label} type-exact binding mismatch")


def _encode_json(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _claim_is_exactly_owned(
    *,
    intended_claim: dict[str, object],
    intended_serialized_claim: bytes,
    intended_claim_sha256: str,
    parent_identity: dict[str, int],
) -> bool:
    try:
        if CLAIM_PATH.is_symlink() or not CLAIM_PATH.is_file():
            return False
        owner_pid = intended_claim.get("owner_pid")
        if type(owner_pid) is not int:
            return False
        current_identity = _process_identity(owner_pid)
        if not _type_exact_equal(current_identity, parent_identity):
            return False
        observed_serialized_claim = CLAIM_PATH.read_bytes()
        observed_claim_sha256 = hashlib.sha256(observed_serialized_claim).hexdigest()
        if not hmac.compare_digest(
            observed_claim_sha256,
            intended_claim_sha256,
        ) or not hmac.compare_digest(
            observed_serialized_claim,
            intended_serialized_claim,
        ):
            return False
        observed_claim = _strict_json_text(observed_serialized_claim.decode("utf-8"))
        return _type_exact_equal(observed_claim, intended_claim)
    except BaseException:
        return False


def _minimal_serialization_error_bytes() -> bytes:
    return (
        "{\n"
        f'  "run_id": "{RUN_ID}",\n'
        f'  "schema": "{ATTEMPT_SCHEMA}",\n'
        '  "outcome": "ERROR",\n'
        '  "error": {"code": "RECEIPT_SERIALIZATION_FAILED"}\n'
        "}\n"
    ).encode("ascii")


def _publish_bytes_create_only(path: Path, encoded: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    published = False
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        published = True
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except BaseException:
            if not published:
                raise


def _publish_json_create_only(path: Path, payload: dict[str, object]) -> None:
    _publish_bytes_create_only(path, _encode_json(payload))


def _finalize_receipt(payload: dict[str, object]) -> bool:
    intended_payload_serialized = True
    try:
        encoded = _encode_json(payload)
    except BaseException:
        encoded = _minimal_serialization_error_bytes()
        intended_payload_serialized = False
    _publish_bytes_create_only(RECEIPT_PATH, encoded)
    return intended_payload_serialized


def _publish_minimal_claim_error_create_only() -> None:
    descriptor: int | None = None
    published = False
    try:
        descriptor = os.open(
            FALLBACK_RECEIPT_TEMP_PATH,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        offset = 0
        while offset < len(MINIMAL_CLAIM_ERROR_BYTES):
            written = os.write(descriptor, MINIMAL_CLAIM_ERROR_BYTES[offset:])
            if written <= 0:
                raise OSError("minimal claim error write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(FALLBACK_RECEIPT_TEMP_PATH, RECEIPT_PATH)
        published = True
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            FALLBACK_RECEIPT_TEMP_PATH.unlink(missing_ok=True)
        except BaseException:
            if not published:
                raise


def _finalize_post_claim_failure() -> None:
    if RECEIPT_PATH.exists():
        return
    try:
        _finalize_receipt(
            {
                "schema": ATTEMPT_SCHEMA,
                "run_id": RUN_ID,
                "outcome": "ERROR",
                "error": {"code": "POST_CLAIM_FAILURE"},
            }
        )
        return
    except BaseException:
        if RECEIPT_PATH.exists():
            return
    _publish_minimal_claim_error_create_only()


def _available_physical_memory_bytes() -> int:
    if os.name != "nt":
        raise RuntimeError("runner requires the reviewed Windows host")
    status = _MemoryStatusEx()
    status.length = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError("could not read physical-memory availability")
    return int(status.available_physical)


def _memory_preflight() -> list[int]:
    readings: list[int] = []
    for index in range(MEMORY_READING_COUNT):
        available = _available_physical_memory_bytes()
        if available < MIN_AVAILABLE_PHYSICAL_MEMORY_BYTES:
            raise RuntimeError("insufficient available physical memory")
        readings.append(available)
        if index + 1 < MEMORY_READING_COUNT:
            time.sleep(MEMORY_READING_INTERVAL_SECONDS)
    return readings


def _file_evidence(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise RuntimeError("symbolic-link evidence path rejected")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RuntimeError("evidence path is not a regular file")
    stat = resolved.stat()
    return {
        "resolved_path": os.path.normcase(str(resolved)),
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(resolved),
    }


def _validated_file_evidence(evidence: object, label: str) -> dict[str, object]:
    expected_keys = {
        "resolved_path",
        "device",
        "inode",
        "size",
        "mtime_ns",
        "sha256",
    }
    if type(evidence) is not dict or set(evidence) != expected_keys:
        raise RuntimeError(f"{label} file evidence schema mismatch")
    resolved_path = evidence.get("resolved_path")
    sha256 = evidence.get("sha256")
    if (
        type(resolved_path) is not str
        or not resolved_path
        or type(sha256) is not str
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
    ):
        raise RuntimeError(f"{label} file evidence string mismatch")
    for name in ("device", "inode", "size", "mtime_ns"):
        value = evidence.get(name)
        if type(value) is not int or value < 0:
            raise RuntimeError(f"{label} file evidence integer mismatch")
    return {
        "resolved_path": resolved_path,
        "device": evidence["device"],
        "inode": evidence["inode"],
        "size": evidence["size"],
        "mtime_ns": evidence["mtime_ns"],
        "sha256": sha256,
    }


def _evidence_paths() -> dict[str, Path]:
    paths = {
        "runner": Path(__file__).resolve(),
        "authorization": AUTHORIZATION_PATH,
        "official_input": INPUT_PATH,
        "static_admission": ADMISSION_PATH,
        "immediate_rejected_predecessor": IMMEDIATE_PREDECESSOR_RECEIPT_PATH,
        "original_rejected_predecessor": ORIGINAL_PREDECESSOR_RECEIPT_PATH,
        "review_test": REVIEW_TEST_PATH,
    }
    paths.update({f"source:{name}": ROOT / name for name in EXPECTED_SOURCE_SHA256})
    return paths


def _capture_evidence() -> dict[str, dict[str, object]]:
    return {name: _file_evidence(path) for name, path in _evidence_paths().items()}


def _verify_evidence(expected: dict[str, dict[str, object]]) -> None:
    if _capture_evidence() != expected:
        raise RuntimeError("postflight file identity or hash drift")


def _expected_authorization(runner_sha256: str) -> dict[str, object]:
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "status": "AUTHORIZED_FOR_ONE_BUILD_ONLY_ATTEMPT",
        "run_id": RUN_ID,
        "runner_path": "scripts/run_pu_official_build_only_receipt.py",
        "runner_sha256": runner_sha256,
        "review_test": {
            "path": REVIEW_TEST_RELATIVE_PATH,
            "sha256": EXPECTED_REVIEW_TEST_SHA256,
        },
        "receipt_path": RECEIPT_RELATIVE_PATH,
        "claim_path": CLAIM_RELATIVE_PATH,
        "handoff_path": HANDOFF_RELATIVE_PATH,
        "input_path": INPUT_RELATIVE_PATH,
        "input_sha256": EXPECTED_INPUT_SHA256,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "build_time_limit_seconds": BUILD_TIME_LIMIT_SECONDS,
        "process_wall_clock_limit_seconds": PROCESS_WALL_CLOCK_LIMIT_SECONDS,
        "min_available_physical_memory_bytes": MIN_AVAILABLE_PHYSICAL_MEMORY_BYTES,
        "memory_preflight": {
            "reading_count": MEMORY_READING_COUNT,
            "minimum_interval_seconds": MEMORY_READING_INTERVAL_SECONDS,
        },
        "workers": WORKERS,
        "random_seed": RANDOM_SEED,
        "construction_limits": CONSTRUCTION_LIMITS,
        "expected_admission": EXPECTED_ADMISSION,
        "reviewed_admission_evidence": {
            "path": ADMISSION_RELATIVE_PATH,
            "sha256": EXPECTED_ADMISSION_RECEIPT_SHA256,
            "schema": "planora.itc2019.sameattendees-static-admission-receipt.v1",
            "result_schema": "planora.itc2019.sameattendees-static-admission.v1",
            "durable_metrics": {
                "safe_prepared_relations": 12_041,
                "safe_prepared_evaluations": 2_377_059,
                "configured_cap": 2_500_000,
                "headroom": 122_941,
                "admitted": True,
                "model_built": False,
                "solver_run": False,
            },
        },
        "rejected_predecessors": [
            {
                "run_id": IMMEDIATE_PREDECESSOR_RUN_ID,
                "receipt_path": IMMEDIATE_PREDECESSOR_RECEIPT_RELATIVE_PATH,
                "receipt_sha256": EXPECTED_IMMEDIATE_PREDECESSOR_RECEIPT_SHA256,
                "required_outcome": "ERROR",
                "required_schema": "planora.itc2019.pu-official-build-only-attempt.v2",
            },
            {
                "run_id": ORIGINAL_PREDECESSOR_RUN_ID,
                "receipt_path": ORIGINAL_PREDECESSOR_RECEIPT_RELATIVE_PATH,
                "receipt_sha256": EXPECTED_ORIGINAL_PREDECESSOR_RECEIPT_SHA256,
                "required_outcome": "ERROR",
                "required_schema": "planora.itc2019.pu-official-build-only-attempt.v1",
            },
        ],
        "watchdog": {
            "kind": "parent-process-subprocess-timeout",
            "broker_tolerant_handoff": True,
            "handoff_wait_limit_seconds": HANDOFF_WAIT_LIMIT_SECONDS,
            "handoff_poll_interval_seconds": HANDOFF_POLL_INTERVAL_SECONDS,
            "handoff_create_only": True,
            "worker_termination_on_timeout": True,
            "worker_result_create_only": True,
            "post_claim_error_fallback_create_only": True,
            "worker_evidence_bindings": [
                "token",
                "claim_sha256",
                "claim_evidence",
                "parent_pid",
                "parent_identity",
                "child_pid",
                "child_identity",
                "authorization_sha256",
                "runner_sha256",
                "handoff_sha256",
            ],
            "successful_event_sequence": list(EVENT_SEQUENCE),
        },
        "scope": {
            "attempts_authorized": 1,
            "official_input_parse_authorized": True,
            "cp_model_construction_authorized": True,
            "cp_solver_construction_authorized": False,
            "solver_run_authorized": False,
            "solution_output_authorized": False,
            "performance_claim_authorized": False,
            "quality_claim_authorized": False,
        },
    }


def _validate_authorization() -> tuple[dict[str, object], str]:
    authorization = _strict_json(AUTHORIZATION_PATH)
    runner_hash = _sha256(Path(__file__).resolve())
    _require_type_exact_equal(
        authorization,
        _expected_authorization(runner_hash),
        "authorization schema",
    )
    return authorization, _sha256(AUTHORIZATION_PATH)


def _require_exact_keys(payload: dict[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise RuntimeError("evidence schema members mismatch")


def _validate_admission_receipt() -> None:
    if _sha256(ADMISSION_PATH) != EXPECTED_ADMISSION_RECEIPT_SHA256:
        raise RuntimeError("static admission receipt hash mismatch")
    payload = _strict_json(ADMISSION_PATH)
    _require_exact_keys(
        payload,
        {
            "schema",
            "created_at_utc",
            "command",
            "scanner",
            "rejected_predecessor",
            "result",
            "scope",
        },
    )
    if payload["schema"] != "planora.itc2019.sameattendees-static-admission-receipt.v1":
        raise RuntimeError("static admission receipt schema mismatch")
    result = payload["result"]
    scope = payload["scope"]
    if type(result) is not dict or type(scope) is not dict:
        raise RuntimeError("static admission receipt object mismatch")
    durable = {
        "safe_prepared_relations": 12_041,
        "safe_prepared_evaluations": 2_377_059,
        "configured_cap": 2_500_000,
        "headroom": 122_941,
        "admitted": True,
        "model_built": False,
        "solver_run": False,
    }
    for name, expected in durable.items():
        value = result.get(name)
        if value != expected or type(value) is not type(expected):
            raise RuntimeError("static admission durable metric mismatch")
    if (
        result.get("schema") != "planora.itc2019.sameattendees-static-admission.v1"
        or result.get("input_path") != INPUT_RELATIVE_PATH
        or result.get("input_sha256") != EXPECTED_INPUT_SHA256
        or scope
        != {
            "static_xml_scan_only": True,
            "model_built": False,
            "solver_run": False,
            "official_output_created": False,
            "performance_claim_authorized": False,
            "quality_claim_authorized": False,
        }
    ):
        raise RuntimeError("static admission evidence binding mismatch")


def _validate_predecessor_receipts() -> None:
    expected = (
        (
            IMMEDIATE_PREDECESSOR_RECEIPT_PATH,
            EXPECTED_IMMEDIATE_PREDECESSOR_RECEIPT_SHA256,
            IMMEDIATE_PREDECESSOR_RUN_ID,
            "planora.itc2019.pu-official-build-only-attempt.v2",
        ),
        (
            ORIGINAL_PREDECESSOR_RECEIPT_PATH,
            EXPECTED_ORIGINAL_PREDECESSOR_RECEIPT_SHA256,
            ORIGINAL_PREDECESSOR_RUN_ID,
            "planora.itc2019.pu-official-build-only-attempt.v1",
        ),
    )
    for path, expected_hash, expected_run_id, expected_schema in expected:
        if _sha256(path) != expected_hash:
            raise RuntimeError("rejected predecessor receipt hash mismatch")
        payload = _strict_json(path)
        if (
            payload.get("run_id") != expected_run_id
            or payload.get("outcome") != "ERROR"
            or payload.get("schema") != expected_schema
        ):
            raise RuntimeError("rejected predecessor evidence mismatch")
        if expected_run_id == IMMEDIATE_PREDECESSOR_RUN_ID and (
            payload.get("worker_return_code") != 2
            or type(payload.get("worker_return_code")) is not int
            or payload.get("worker_event_sequence") != []
            or payload.get("scope", {}).get("official_input_used") is not False
            or payload.get("scope", {}).get("official_input_parse_started") is not False
        ):
            raise RuntimeError("immediate predecessor root-cause evidence mismatch")


def _preflight(
    *, include_memory: bool
) -> tuple[dict[str, object], str, dict[str, dict[str, object]], list[int]]:
    if RECEIPT_PATH.exists():
        raise RuntimeError("one-shot authorization already has a final receipt")
    authorization, authorization_hash = _validate_authorization()
    _validate_admission_receipt()
    _validate_predecessor_receipts()
    evidence = _capture_evidence()
    if evidence["official_input"]["sha256"] != EXPECTED_INPUT_SHA256:
        raise RuntimeError("official input hash drift")
    for relative, expected_hash in EXPECTED_SOURCE_SHA256.items():
        if evidence[f"source:{relative}"]["sha256"] != expected_hash:
            raise RuntimeError("reviewed source hash drift")
    if evidence["review_test"]["sha256"] != EXPECTED_REVIEW_TEST_SHA256:
        raise RuntimeError("reviewed hostile-regression test hash drift")
    readings = _memory_preflight() if include_memory else []
    return authorization, authorization_hash, evidence, readings


def _safe_error(
    code: str, stage: str, exc: BaseException | None = None
) -> dict[str, object]:
    category = "NONE"
    if exc is not None:
        for exception_type, label in (
            (KeyboardInterrupt, "KEYBOARD_INTERRUPT"),
            (SystemExit, "SYSTEM_EXIT"),
            (TimeoutError, "TIMEOUT"),
            (MemoryError, "MEMORY_ERROR"),
            (Exception, "EXCEPTION"),
            (BaseException, "BASE_EXCEPTION"),
        ):
            if isinstance(exc, exception_type):
                category = label
                break
    return {"code": code, "stage": stage, "category": category}


def _session_binding(
    *,
    token: str,
    claim_sha256: str,
    claim_evidence: dict[str, object],
    parent_identity: dict[str, int],
    child_identity: dict[str, int],
    authorization_sha256: str,
    runner_sha256: str,
    handoff_sha256: str,
) -> dict[str, object]:
    validated_claim_evidence = _validated_file_evidence(
        claim_evidence, "worker session claim"
    )
    if (
        type(token) is not str
        or len(token) != 32
        or any(character not in "0123456789abcdef" for character in token)
        or type(claim_sha256) is not str
        or len(claim_sha256) != 64
        or not hmac.compare_digest(validated_claim_evidence["sha256"], claim_sha256)
        or type(authorization_sha256) is not str
        or len(authorization_sha256) != 64
        or type(runner_sha256) is not str
        or len(runner_sha256) != 64
        or type(handoff_sha256) is not str
        or len(handoff_sha256) != 64
        or type(parent_identity) is not dict
        or set(parent_identity) != {"pid", "creation_time_100ns"}
        or type(parent_identity.get("pid")) is not int
        or type(parent_identity.get("creation_time_100ns")) is not int
        or type(child_identity) is not dict
        or set(child_identity) != {"pid", "creation_time_100ns"}
        or type(child_identity.get("pid")) is not int
        or type(child_identity.get("creation_time_100ns")) is not int
    ):
        raise RuntimeError("invalid worker session binding")
    return {
        "token": token,
        "claim_sha256": claim_sha256,
        "claim_evidence": validated_claim_evidence,
        "parent_pid": parent_identity["pid"],
        "parent_identity": dict(parent_identity),
        "child_pid": child_identity["pid"],
        "child_identity": dict(child_identity),
        "authorization_sha256": authorization_sha256,
        "runner_sha256": runner_sha256,
        "handoff_sha256": handoff_sha256,
    }


def _handoff_payload(
    *,
    token: str,
    claim_snapshot: dict[str, object],
    claim_sha256: str,
    claim_evidence: dict[str, object],
    parent_identity: dict[str, int],
    child_identity: dict[str, int],
    authorization_sha256: str,
    runner_sha256: str,
) -> dict[str, object]:
    validated_claim_evidence = _validated_file_evidence(claim_evidence, "handoff claim")
    if (
        type(claim_sha256) is not str
        or len(claim_sha256) != 64
        or not hmac.compare_digest(validated_claim_evidence["sha256"], claim_sha256)
    ):
        raise RuntimeError("handoff claim hash evidence mismatch")
    return {
        "schema": HANDOFF_SCHEMA,
        "run_id": RUN_ID,
        "token": token,
        "claim_path": CLAIM_RELATIVE_PATH,
        "claim_sha256": claim_sha256,
        "claim_evidence": validated_claim_evidence,
        "claim_snapshot": claim_snapshot,
        "parent_pid": parent_identity["pid"],
        "parent_identity": dict(parent_identity),
        "child_pid": child_identity["pid"],
        "child_identity": dict(child_identity),
        "authorization_sha256": authorization_sha256,
        "runner_sha256": runner_sha256,
    }


def _mark_event(name: str, binding: dict[str, object]) -> None:
    if name not in EVENT_PATHS:
        raise RuntimeError("unknown worker event")
    _publish_json_create_only(
        EVENT_PATHS[name],
        {
            "schema": EVENT_SCHEMA,
            "run_id": RUN_ID,
            "event": name,
            "sequence": EVENT_SEQUENCE_NUMBERS[name],
            "binding": binding,
        },
    )


def _sanitize_telemetry(telemetry: object) -> dict[str, object]:
    if type(telemetry) is not ITC2019TimetableFactorizedTelemetry:
        raise RuntimeError("telemetry type mismatch")
    integer_fields = (
        "class_count",
        "time_domain_values",
        "room_domain_values",
        "required_pair_distributions",
        "required_pair_relations",
        "required_group_distributions",
        "required_group_cells",
        "room_pair_evaluations",
        "sparse_room_constraints",
        "model_variables",
        "model_constraints",
        "model_proto_bytes",
        "source_student_records_excluded",
        "source_soft_distributions_excluded",
    )
    sanitized: dict[str, object] = {"schema": telemetry.schema}
    if telemetry.schema != "planora.itc2019.timetable-factorized-build.v1":
        raise RuntimeError("telemetry schema mismatch")
    for name in integer_fields:
        value = getattr(telemetry, name)
        if type(value) is not int or value < 0:
            raise RuntimeError("telemetry integer field mismatch")
        sanitized[name] = value
    if (
        telemetry.model_proto_sha256 != ""
        or telemetry.model_fingerprint_mode != "not_requested"
    ):
        raise RuntimeError("unexpected model fingerprint telemetry")
    if type(telemetry.phase_wall_seconds) is not tuple:
        raise RuntimeError("telemetry phase container mismatch")
    for phase in telemetry.phase_wall_seconds:
        if (
            type(phase) is not tuple
            or len(phase) != 2
            or type(phase[0]) is not str
            or type(phase[1]) is not float
            or not math.isfinite(phase[1])
            or phase[1] < 0.0
        ):
            raise RuntimeError("telemetry phase entry mismatch")
    if (
        sanitized["required_pair_relations"] != EXPECTED_ADMISSION["prepared_relations"]
        or sanitized["room_pair_evaluations"]
        != EXPECTED_ADMISSION["room_pair_evaluations"]
        or sanitized["sparse_room_constraints"]
        > CONSTRUCTION_LIMITS["max_sparse_room_constraints"]
    ):
        raise RuntimeError("telemetry admission contract mismatch")
    return sanitized


def _sanitize_result(
    result: object, solver_constructor_calls: int
) -> dict[str, object]:
    if type(result) is not ITC2019TimetableFactorizedResult:
        raise RuntimeError("build result type mismatch")
    if (
        result.status != "BUILT"
        or result.build_only is not True
        or type(result.model) is not cp_model.CpModel
        or result.solver_status != "NOT_RUN"
        or result.has_validated_candidate is not False
        or type(result.placements) is not tuple
        or result.placements != ()
        or type(result.validation_errors) is not tuple
        or result.validation_errors != ()
        or type(result.unsupported_reasons) is not tuple
        or result.unsupported_reasons != ()
        or type(result.solver_wall_time_seconds) is not float
        or result.solver_wall_time_seconds != 0.0
        or type(result.conflicts) is not int
        or result.conflicts != 0
        or type(result.branches) is not int
        or result.branches != 0
        or solver_constructor_calls != 0
    ):
        raise RuntimeError("build result contract mismatch")
    return {
        "status": "BUILT",
        "build_only": True,
        "has_model": True,
        "solver_status": "NOT_RUN",
        "has_validated_candidate": False,
        "placement_count": 0,
        "solver_constructor_calls": 0,
        "telemetry": _sanitize_telemetry(result.telemetry),
    }


def _validate_worker_handoff(
    token: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    handoff, handoff_encoded, handoff_identity = _strict_json_with_evidence(
        HANDOFF_PATH
    )
    child_identity = _process_identity(os.getpid())
    claim_snapshot = handoff.get("claim_snapshot")
    if type(claim_snapshot) is not dict:
        raise RuntimeError("handoff claim snapshot mismatch")
    current_claim, claim_encoded, claim_identity = _strict_json_with_evidence(
        CLAIM_PATH
    )
    if not _type_exact_equal(current_claim, claim_snapshot):
        raise RuntimeError("worker handoff claim content mismatch")
    authorization_sha256 = _sha256(AUTHORIZATION_PATH)
    runner_sha256 = _sha256(Path(__file__).resolve())
    claimed_at_utc = claim_snapshot.get("claimed_at_utc")
    parent_pid = claim_snapshot.get("owner_pid")
    claimed_parent_identity = claim_snapshot.get("owner_identity")
    if type(claimed_at_utc) is not str or not claimed_at_utc:
        raise RuntimeError("worker handoff claim timestamp mismatch")
    if (
        type(parent_pid) is not int
        or type(claimed_parent_identity) is not dict
        or set(claimed_parent_identity) != {"pid", "creation_time_100ns"}
        or claimed_parent_identity.get("pid") != parent_pid
        or type(claimed_parent_identity.get("pid")) is not int
        or type(claimed_parent_identity.get("creation_time_100ns")) is not int
    ):
        raise RuntimeError("worker handoff claim parent identity mismatch")
    expected_claim = {
        "schema": CLAIM_SCHEMA,
        "run_id": RUN_ID,
        "token": token,
        "owner_pid": parent_pid,
        "owner_identity": claimed_parent_identity,
        "authorization_sha256": authorization_sha256,
        "runner_sha256": runner_sha256,
        "claimed_at_utc": claimed_at_utc,
    }
    if not _type_exact_equal(claim_snapshot, expected_claim):
        raise RuntimeError("worker handoff claim ownership mismatch")
    expected_claim_encoded = _encode_json(expected_claim)
    if not hmac.compare_digest(claim_encoded, expected_claim_encoded):
        raise RuntimeError("worker handoff claim canonical encoding mismatch")
    claim_sha256 = hashlib.sha256(claim_encoded).hexdigest()
    claim_evidence = _validated_file_evidence(
        {**claim_identity, "sha256": claim_sha256}, "worker claim"
    )
    live_parent_identity = _process_identity(parent_pid)
    if not _type_exact_equal(live_parent_identity, claimed_parent_identity):
        raise RuntimeError("worker handoff claimed parent identity changed")
    expected_handoff = _handoff_payload(
        token=token,
        claim_snapshot=claim_snapshot,
        claim_sha256=claim_sha256,
        claim_evidence=claim_evidence,
        parent_identity=live_parent_identity,
        child_identity=child_identity,
        authorization_sha256=authorization_sha256,
        runner_sha256=runner_sha256,
    )
    if not _type_exact_equal(handoff, expected_handoff):
        raise RuntimeError("worker handoff binding mismatch")
    expected_handoff_encoded = _encode_json(expected_handoff)
    if not hmac.compare_digest(handoff_encoded, expected_handoff_encoded):
        raise RuntimeError("worker handoff canonical encoding mismatch")
    handoff_sha256 = hashlib.sha256(handoff_encoded).hexdigest()
    handoff_evidence = {**handoff_identity, "sha256": handoff_sha256}
    binding = _session_binding(
        token=token,
        claim_sha256=claim_sha256,
        claim_evidence=claim_evidence,
        parent_identity=live_parent_identity,
        child_identity=child_identity,
        authorization_sha256=authorization_sha256,
        runner_sha256=runner_sha256,
        handoff_sha256=handoff_sha256,
    )
    return binding, handoff_evidence, claim_evidence


def _wait_for_worker_handoff(
    token: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    deadline = time.monotonic() + HANDOFF_WAIT_LIMIT_SECONDS
    while True:
        if HANDOFF_PATH.exists():
            return _validate_worker_handoff(token)
        if time.monotonic() >= deadline:
            raise TimeoutError("authenticated parent handoff did not arrive")
        time.sleep(HANDOFF_POLL_INTERVAL_SECONDS)


def _verify_worker_session_current(
    binding: dict[str, object],
    handoff_evidence: dict[str, object],
    claim_evidence: dict[str, object],
) -> None:
    token = binding.get("token")
    if type(token) is not str:
        raise RuntimeError("worker session token type mismatch")
    validated_claim_evidence = _validated_file_evidence(
        claim_evidence, "worker session expected claim"
    )
    _current_claim, current_claim_encoded, current_claim_identity = (
        _strict_json_with_evidence(CLAIM_PATH)
    )
    current_claim_evidence = _validated_file_evidence(
        {
            **current_claim_identity,
            "sha256": hashlib.sha256(current_claim_encoded).hexdigest(),
        },
        "worker session current claim",
    )
    if not _type_exact_equal(
        binding.get("claim_evidence"), validated_claim_evidence
    ) or not _type_exact_equal(current_claim_evidence, validated_claim_evidence):
        raise RuntimeError("worker claim file identity drift")
    (
        refreshed_binding,
        refreshed_handoff_evidence,
        refreshed_claim_evidence,
    ) = _validate_worker_handoff(token)
    if (
        not _type_exact_equal(refreshed_binding, binding)
        or not _type_exact_equal(refreshed_handoff_evidence, handoff_evidence)
        or not _type_exact_equal(refreshed_claim_evidence, validated_claim_evidence)
    ):
        raise RuntimeError("worker handoff identity, hash, or content drift")
    parent_pid = binding.get("parent_pid")
    child_pid = binding.get("child_pid")
    if type(parent_pid) is not int or type(child_pid) is not int:
        raise RuntimeError("worker session PID type mismatch")
    if not _type_exact_equal(
        _process_identity(parent_pid), binding.get("parent_identity")
    ):
        raise RuntimeError("claimed parent process identity changed")
    if child_pid != os.getpid() or not _type_exact_equal(
        _process_identity(child_pid), binding.get("child_identity")
    ):
        raise RuntimeError("worker process identity changed")
    if (
        _sha256(CLAIM_PATH) != binding.get("claim_sha256")
        or _sha256(AUTHORIZATION_PATH) != binding.get("authorization_sha256")
        or _sha256(Path(__file__).resolve()) != binding.get("runner_sha256")
    ):
        raise RuntimeError("worker session evidence drift")


def _worker_main(token: str) -> int:
    original_solver = cp_model.CpSolver
    solver_constructor_calls = 0
    stage = "worker-preflight"

    def forbidden_solver(*_args: object, **_kwargs: object) -> None:
        nonlocal solver_constructor_calls
        solver_constructor_calls += 1
        raise RuntimeError("CpSolver construction is forbidden")

    try:
        binding, handoff_evidence, claim_evidence = _wait_for_worker_handoff(token)
        _preflight(include_memory=False)
        _verify_worker_session_current(binding, handoff_evidence, claim_evidence)
        cp_model.CpSolver = forbidden_solver  # type: ignore[assignment]
        stage = "parse"
        _mark_event("parse-started", binding)
        problem = parse_itc2019_xml(INPUT_PATH)
        _mark_event("parse-completed", binding)
        _verify_worker_session_current(binding, handoff_evidence, claim_evidence)
        stage = "build"
        _mark_event("build-started", binding)
        result = solve_itc2019_timetable_factorized(
            problem,
            build_only=True,
            build_time_limit_seconds=BUILD_TIME_LIMIT_SECONDS,
            workers=WORKERS,
            random_seed=RANDOM_SEED,
            limits=ITC2019TimetableFactorizedLimits(),
            include_proto_fingerprint=False,
        )
        sanitized = _sanitize_result(result, solver_constructor_calls)
        _verify_worker_session_current(binding, handoff_evidence, claim_evidence)
        _mark_event("build-completed", binding)
        payload: dict[str, object] = {
            "schema": WORKER_SCHEMA,
            "run_id": RUN_ID,
            "binding": binding,
            "outcome": "BUILT_WITHOUT_SOLVE",
            "result": sanitized,
            "error": None,
        }
        exit_code = 0
    except BaseException as exc:
        error_binding = locals().get("binding")
        if type(error_binding) is not dict:
            return 2
        payload = {
            "schema": WORKER_SCHEMA,
            "run_id": RUN_ID,
            "binding": error_binding,
            "outcome": "ERROR",
            "result": None,
            "error": _safe_error("WORKER_FAILURE", stage, exc),
        }
        exit_code = 1
    finally:
        cp_model.CpSolver = original_solver  # type: ignore[assignment]
    try:
        _publish_json_create_only(WORKER_RESULT_PATH, payload)
    except BaseException:
        return 2
    return exit_code


def _wait_with_hard_timeout(
    process: subprocess.Popen[bytes], timeout_seconds: float
) -> tuple[bool, int]:
    try:
        return False, process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        return True, process.wait()


def _launch_worker(token: str) -> tuple[subprocess.Popen[bytes], float]:
    started = time.monotonic()
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            token,
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process, started


def _wait_for_launched_worker(
    process: subprocess.Popen[bytes], started: float
) -> tuple[bool, int | None, float]:
    elapsed_before_wait = max(0.0, time.monotonic() - started)
    remaining = max(0.001, PROCESS_WALL_CLOCK_LIMIT_SECONDS - elapsed_before_wait)
    try:
        timed_out, return_code = _wait_with_hard_timeout(process, remaining)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    return timed_out, return_code, max(0.0, time.monotonic() - started)


def _validate_sanitized_telemetry(payload: dict[str, object]) -> None:
    integer_fields = {
        "class_count",
        "time_domain_values",
        "room_domain_values",
        "required_pair_distributions",
        "required_pair_relations",
        "required_group_distributions",
        "required_group_cells",
        "room_pair_evaluations",
        "sparse_room_constraints",
        "model_variables",
        "model_constraints",
        "model_proto_bytes",
        "source_student_records_excluded",
        "source_soft_distributions_excluded",
    }
    _require_exact_keys(payload, {"schema", *integer_fields})
    if payload.get("schema") != "planora.itc2019.timetable-factorized-build.v1":
        raise RuntimeError("worker telemetry schema mismatch")
    for name in integer_fields:
        value = payload.get(name)
        if type(value) is not int or value < 0:
            raise RuntimeError("worker telemetry integer mismatch")
    if (
        payload["required_pair_relations"] != EXPECTED_ADMISSION["prepared_relations"]
        or payload["room_pair_evaluations"]
        != EXPECTED_ADMISSION["room_pair_evaluations"]
        or payload["sparse_room_constraints"]
        > CONSTRUCTION_LIMITS["max_sparse_room_constraints"]
    ):
        raise RuntimeError("worker telemetry admission mismatch")


def _validate_worker_error(payload: dict[str, object]) -> None:
    _require_exact_keys(payload, {"code", "stage", "category"})
    if payload.get("code") != "WORKER_FAILURE":
        raise RuntimeError("worker error code mismatch")
    if payload.get("stage") not in {"worker-preflight", "parse", "build"}:
        raise RuntimeError("worker error stage mismatch")
    if payload.get("category") not in {
        "KEYBOARD_INTERRUPT",
        "SYSTEM_EXIT",
        "TIMEOUT",
        "MEMORY_ERROR",
        "EXCEPTION",
        "BASE_EXCEPTION",
    }:
        raise RuntimeError("worker error category mismatch")


def _read_worker_result(binding: dict[str, object]) -> dict[str, object]:
    payload = _strict_json(WORKER_RESULT_PATH)
    _require_exact_keys(
        payload,
        {"schema", "run_id", "binding", "outcome", "result", "error"},
    )
    if payload.get("schema") != WORKER_SCHEMA or payload.get("run_id") != RUN_ID:
        raise RuntimeError("worker result binding mismatch")
    _require_type_exact_equal(payload.get("binding"), binding, "worker result")
    if payload.get("outcome") not in {"BUILT_WITHOUT_SOLVE", "ERROR"}:
        raise RuntimeError("worker outcome mismatch")
    if payload["outcome"] == "BUILT_WITHOUT_SOLVE":
        result = payload.get("result")
        if type(result) is not dict or payload.get("error") is not None:
            raise RuntimeError("worker success schema mismatch")
        _require_exact_keys(
            result,
            {
                "status",
                "build_only",
                "has_model",
                "solver_status",
                "has_validated_candidate",
                "placement_count",
                "solver_constructor_calls",
                "telemetry",
            },
        )
        telemetry = result.get("telemetry")
        if (
            result.get("status") != "BUILT"
            or result.get("build_only") is not True
            or result.get("has_model") is not True
            or result.get("solver_status") != "NOT_RUN"
            or result.get("has_validated_candidate") is not False
            or result.get("placement_count") != 0
            or type(result.get("placement_count")) is not int
            or result.get("solver_constructor_calls") != 0
            or type(result.get("solver_constructor_calls")) is not int
            or type(telemetry) is not dict
        ):
            raise RuntimeError("worker success contract mismatch")
        _validate_sanitized_telemetry(telemetry)
    else:
        worker_error = payload.get("error")
        if payload.get("result") is not None or type(worker_error) is not dict:
            raise RuntimeError("worker error schema mismatch")
        _validate_worker_error(worker_error)
    return payload


def _scope_from_event_prefix(observed: tuple[str, ...]) -> dict[str, object]:
    return {
        "official_input_parse_started": "parse-started" in observed,
        "official_input_parse_completed": "parse-completed" in observed,
        "official_input_used": "parse-started" in observed,
        "model_construction_started": "build-started" in observed,
        "model_construction_completed": "build-completed" in observed,
        "solver_construction_authorized": False,
        "solver_run": False,
        "solution_output_created": False,
        "performance_claim_authorized": False,
        "quality_claim_authorized": False,
    }


class _EventEvidenceError(RuntimeError):
    def __init__(self, observed_events: tuple[str, ...]) -> None:
        super().__init__("worker event binding mismatch")
        self.observed_events = observed_events
        self.scope = _scope_from_event_prefix(observed_events)


def _authenticated_event_prefix(
    binding: dict[str, object],
) -> tuple[tuple[str, ...], bool]:
    observed: list[str] = []
    missing_seen = False
    for name in EVENT_SEQUENCE:
        path = EVENT_PATHS[name]
        if not path.exists():
            missing_seen = True
            continue
        if missing_seen:
            return tuple(observed), True
        try:
            payload = _strict_json(path)
        except BaseException:
            return tuple(observed), True
        expected = {
            "schema": EVENT_SCHEMA,
            "run_id": RUN_ID,
            "event": name,
            "sequence": EVENT_SEQUENCE_NUMBERS[name],
            "binding": binding,
        }
        if not _type_exact_equal(payload, expected):
            return tuple(observed), True
        observed.append(name)
    return tuple(observed), False


def _event_scope(
    binding: dict[str, object],
) -> tuple[dict[str, object], tuple[str, ...]]:
    observed, invalid_later_evidence = _authenticated_event_prefix(binding)
    if invalid_later_evidence:
        raise _EventEvidenceError(observed)
    return _scope_from_event_prefix(observed), observed


def _event_scope_fallback(
    binding: dict[str, object],
) -> tuple[dict[str, object], tuple[str, ...]]:
    observed, _invalid_later_evidence = _authenticated_event_prefix(binding)
    return _scope_from_event_prefix(observed), observed


def _empty_scope() -> dict[str, object]:
    return {
        "official_input_parse_started": False,
        "official_input_parse_completed": False,
        "official_input_used": False,
        "model_construction_started": False,
        "model_construction_completed": False,
        "solver_construction_authorized": False,
        "solver_run": False,
        "solution_output_created": False,
        "performance_claim_authorized": False,
        "quality_claim_authorized": False,
    }


def _validate_parent_claim_baseline(
    *,
    token: str,
    parent_identity: dict[str, int],
    authorization_hash: str,
    runner_sha256: str,
    claim_snapshot: dict[str, object],
    intended_claim_encoded: bytes,
    intended_claim_sha256: str,
) -> tuple[dict[str, object], str]:
    observed_claim, observed_claim_encoded, claim_identity = _strict_json_with_evidence(
        CLAIM_PATH
    )
    claimed_at_utc = claim_snapshot.get("claimed_at_utc")
    if (
        type(token) is not str
        or len(token) != 32
        or any(character not in "0123456789abcdef" for character in token)
        or type(parent_identity) is not dict
        or set(parent_identity) != {"pid", "creation_time_100ns"}
        or type(parent_identity.get("pid")) is not int
        or type(parent_identity.get("creation_time_100ns")) is not int
        or type(authorization_hash) is not str
        or len(authorization_hash) != 64
        or type(runner_sha256) is not str
        or len(runner_sha256) != 64
        or type(claimed_at_utc) is not str
        or not claimed_at_utc
        or type(intended_claim_encoded) is not bytes
        or type(intended_claim_sha256) is not str
        or len(intended_claim_sha256) != 64
    ):
        raise RuntimeError("parent intended claim binding mismatch")
    expected_claim = {
        "schema": CLAIM_SCHEMA,
        "run_id": RUN_ID,
        "token": token,
        "owner_pid": parent_identity["pid"],
        "owner_identity": dict(parent_identity),
        "authorization_sha256": authorization_hash,
        "runner_sha256": runner_sha256,
        "claimed_at_utc": claimed_at_utc,
    }
    if not _type_exact_equal(claim_snapshot, expected_claim) or not _type_exact_equal(
        observed_claim, expected_claim
    ):
        raise RuntimeError("parent claim type-exact binding mismatch")
    expected_claim_encoded = _encode_json(expected_claim)
    computed_intended_sha256 = hashlib.sha256(intended_claim_encoded).hexdigest()
    observed_claim_sha256 = hashlib.sha256(observed_claim_encoded).hexdigest()
    if (
        not hmac.compare_digest(intended_claim_encoded, expected_claim_encoded)
        or not hmac.compare_digest(computed_intended_sha256, intended_claim_sha256)
        or not hmac.compare_digest(observed_claim_encoded, intended_claim_encoded)
        or not hmac.compare_digest(observed_claim_sha256, intended_claim_sha256)
    ):
        raise RuntimeError("parent claim canonical bytes or hash mismatch")
    claim_evidence = _validated_file_evidence(
        {**claim_identity, "sha256": observed_claim_sha256}, "parent claim"
    )
    return claim_evidence, observed_claim_sha256


def _claimed_parent_main(
    *,
    authorization: dict[str, object],
    authorization_hash: str,
    evidence: dict[str, dict[str, object]],
    memory_readings: list[int],
    token: str,
    parent_identity: dict[str, int],
    claim_snapshot: dict[str, object],
    intended_claim_encoded: bytes,
    intended_claim_sha256: str,
) -> int:
    runner_sha256 = evidence["runner"]["sha256"]
    if type(runner_sha256) is not str:
        raise RuntimeError("runner hash type mismatch")
    claim_evidence, claim_sha256 = _validate_parent_claim_baseline(
        token=token,
        parent_identity=parent_identity,
        authorization_hash=authorization_hash,
        runner_sha256=runner_sha256,
        claim_snapshot=claim_snapshot,
        intended_claim_encoded=intended_claim_encoded,
        intended_claim_sha256=intended_claim_sha256,
    )
    started_at = _utc_now()
    process: subprocess.Popen[bytes] | None = None
    binding: dict[str, object] | None = None
    handoff_snapshot: dict[str, object] | None = None
    handoff_evidence: dict[str, object] | None = None
    timed_out = False
    return_code: int | None = None
    process_elapsed = 0.0
    worker_payload: dict[str, object] | None = None
    outcome = "ERROR"
    error: dict[str, object] | None = None
    scope = _empty_scope()
    observed_events: tuple[str, ...] = ()
    stage = "worker-launch"
    try:
        if not _type_exact_equal(
            _process_identity(parent_identity["pid"]), parent_identity
        ):
            raise RuntimeError("claiming parent process identity changed")
        process, process_started = _launch_worker(token)
        stage = "handoff-publication"
        child_identity = _process_identity(process.pid)
        handoff_snapshot = _handoff_payload(
            token=token,
            claim_snapshot=claim_snapshot,
            claim_sha256=claim_sha256,
            claim_evidence=claim_evidence,
            parent_identity=parent_identity,
            child_identity=child_identity,
            authorization_sha256=authorization_hash,
            runner_sha256=runner_sha256,
        )
        _publish_json_create_only(HANDOFF_PATH, handoff_snapshot)
        handoff_evidence = _file_evidence(HANDOFF_PATH)
        if not _type_exact_equal(_strict_json(HANDOFF_PATH), handoff_snapshot):
            raise RuntimeError("published handoff content mismatch")
        handoff_sha256 = handoff_evidence["sha256"]
        if type(handoff_sha256) is not str:
            raise RuntimeError("handoff hash type mismatch")
        binding = _session_binding(
            token=token,
            claim_sha256=claim_sha256,
            claim_evidence=claim_evidence,
            parent_identity=parent_identity,
            child_identity=child_identity,
            authorization_sha256=authorization_hash,
            runner_sha256=runner_sha256,
            handoff_sha256=handoff_sha256,
        )
        timed_out, return_code, process_elapsed = _wait_for_launched_worker(
            process, process_started
        )
        stage = "postflight"
        _verify_evidence(evidence)
        if _file_evidence(CLAIM_PATH) != claim_evidence:
            raise RuntimeError("postflight claim identity or hash drift")
        if (
            handoff_evidence is None
            or _file_evidence(HANDOFF_PATH) != handoff_evidence
            or not _type_exact_equal(_strict_json(HANDOFF_PATH), handoff_snapshot)
        ):
            raise RuntimeError("postflight handoff identity, hash, or content drift")
        scope, observed_events = _event_scope(binding)
        if timed_out:
            error = _safe_error("PROCESS_WALL_CLOCK_EXCEEDED", "watchdog")
        elif not WORKER_RESULT_PATH.exists():
            error = _safe_error("WORKER_RESULT_MISSING", "worker-result")
        else:
            worker_payload = _read_worker_result(binding)
            outcome_value = worker_payload["outcome"]
            if type(outcome_value) is not str:
                raise RuntimeError("worker outcome type mismatch")
            if outcome_value == "BUILT_WITHOUT_SOLVE":
                if (
                    type(return_code) is not int
                    or return_code != 0
                    or observed_events != EVENT_SEQUENCE
                ):
                    raise RuntimeError("successful worker process contract mismatch")
                outcome = "BUILT_WITHOUT_SOLVE"
            else:
                worker_error = worker_payload["error"]
                if type(worker_error) is not dict:
                    raise RuntimeError("worker error type mismatch")
                error = worker_error
    except BaseException as exc:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        error = _safe_error("PARENT_FAILURE", stage, exc)
        if isinstance(exc, _EventEvidenceError) and len(exc.observed_events) > len(
            observed_events
        ):
            scope = exc.scope
            observed_events = exc.observed_events
        try:
            if binding is not None:
                fallback_scope, fallback_events = _event_scope_fallback(binding)
                if len(fallback_events) > len(observed_events):
                    scope = fallback_scope
                    observed_events = fallback_events
        except BaseException:
            pass
        outcome = "ERROR"
    result = None
    if outcome == "BUILT_WITHOUT_SOLVE" and worker_payload is not None:
        result = worker_payload["result"]
    receipt: dict[str, object] = {
        "schema": ATTEMPT_SCHEMA,
        "run_id": RUN_ID,
        "outcome": outcome,
        "started_at_utc": started_at,
        "completed_at_utc": _utc_now(),
        "process_wall_seconds": process_elapsed,
        "process_timed_out": timed_out,
        "worker_return_code": return_code,
        "authorization_path": AUTHORIZATION_RELATIVE_PATH,
        "authorization_sha256": authorization_hash,
        "claim_path": CLAIM_RELATIVE_PATH,
        "claim_sha256": claim_evidence["sha256"],
        "claim_evidence": claim_evidence,
        "handoff_path": HANDOFF_RELATIVE_PATH,
        "handoff_sha256": (
            handoff_evidence.get("sha256") if handoff_evidence is not None else None
        ),
        "handoff_snapshot": handoff_snapshot,
        "worker_session_binding": binding,
        "worker_event_sequence": list(observed_events),
        "runner_path": "scripts/run_pu_official_build_only_receipt.py",
        "runner_sha256": evidence["runner"]["sha256"],
        "input_path": INPUT_RELATIVE_PATH,
        "input_sha256": EXPECTED_INPUT_SHA256,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "reviewed_admission_receipt_sha256": EXPECTED_ADMISSION_RECEIPT_SHA256,
        "rejected_predecessors": authorization["rejected_predecessors"],
        "memory_preflight_available_physical_bytes": memory_readings,
        "limits": {
            "build_time_limit_seconds": BUILD_TIME_LIMIT_SECONDS,
            "process_wall_clock_limit_seconds": PROCESS_WALL_CLOCK_LIMIT_SECONDS,
            "workers": WORKERS,
            "random_seed": RANDOM_SEED,
            "construction": CONSTRUCTION_LIMITS,
        },
        "expected_admission": EXPECTED_ADMISSION,
        "result": result,
        "error": error,
        "scope": scope,
    }
    intended_receipt_written = _finalize_receipt(receipt)
    if not intended_receipt_written:
        return 1
    return 0 if outcome == "BUILT_WITHOUT_SOLVE" else 1


def _parent_main() -> int:
    authorization, authorization_hash, evidence, memory_readings = _preflight(
        include_memory=True
    )
    runtime_paths = [
        CLAIM_PATH,
        HANDOFF_PATH,
        WORKER_RESULT_PATH,
        FALLBACK_RECEIPT_TEMP_PATH,
        *EVENT_PATHS.values(),
    ]
    if any(path.exists() for path in runtime_paths):
        raise RuntimeError("one-shot authorization has prior runtime evidence")
    token = uuid.uuid4().hex
    owner_pid = os.getpid()
    parent_identity = _process_identity(owner_pid)
    claim = {
        "schema": CLAIM_SCHEMA,
        "run_id": RUN_ID,
        "token": token,
        "owner_pid": owner_pid,
        "owner_identity": parent_identity,
        "authorization_sha256": authorization_hash,
        "runner_sha256": evidence["runner"]["sha256"],
        "claimed_at_utc": _utc_now(),
    }
    serialized_claim = _encode_json(claim)
    serialized_claim_sha256 = hashlib.sha256(serialized_claim).hexdigest()
    try:
        _publish_bytes_create_only(CLAIM_PATH, serialized_claim)
    except BaseException:
        if _claim_is_exactly_owned(
            intended_claim=claim,
            intended_serialized_claim=serialized_claim,
            intended_claim_sha256=serialized_claim_sha256,
            parent_identity=parent_identity,
        ):
            _finalize_post_claim_failure()
            return 1
        raise
    try:
        return _claimed_parent_main(
            authorization=authorization,
            authorization_hash=authorization_hash,
            evidence=evidence,
            memory_readings=memory_readings,
            token=token,
            parent_identity=parent_identity,
            claim_snapshot=claim,
            intended_claim_encoded=serialized_claim,
            intended_claim_sha256=serialized_claim_sha256,
        )
    except BaseException:
        _finalize_post_claim_failure()
        return 1


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return _worker_main(sys.argv[2])
    if len(sys.argv) != 1:
        return 2
    try:
        return _parent_main()
    except BaseException:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
