from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import scripts.run_pu_official_build_only_receipt as runner


TOKEN = "a" * 32
CLAIM_SHA256 = "b" * 64
AUTHORIZATION_SHA256 = "c" * 64
RUNNER_SHA256 = "d" * 64
HANDOFF_SHA256 = "e" * 64
PARENT_IDENTITY = {"pid": 4242, "creation_time_100ns": 987654321}
CHILD_IDENTITY = {"pid": 4343, "creation_time_100ns": 123456789}
CLAIM_EVIDENCE = {
    "resolved_path": r"c:\claim.json",
    "device": 1,
    "inode": 2,
    "size": 3,
    "mtime_ns": 4,
    "sha256": CLAIM_SHA256,
}


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = CHILD_IDENTITY["pid"]
        self.killed = False

    def poll(self) -> int | None:
        return 9 if self.killed else None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.killed = True
        return 9


def _binding() -> dict[str, object]:
    return runner._session_binding(
        token=TOKEN,
        claim_sha256=CLAIM_SHA256,
        claim_evidence=CLAIM_EVIDENCE,
        parent_identity=PARENT_IDENTITY,
        child_identity=CHILD_IDENTITY,
        authorization_sha256=AUTHORIZATION_SHA256,
        runner_sha256=RUNNER_SHA256,
        handoff_sha256=HANDOFF_SHA256,
    )


def _telemetry() -> dict[str, object]:
    return {
        "schema": "planora.itc2019.timetable-factorized-build.v1",
        "class_count": 8813,
        "time_domain_values": 1,
        "room_domain_values": 1,
        "required_pair_distributions": 1,
        "required_pair_relations": 12041,
        "required_group_distributions": 0,
        "required_group_cells": 0,
        "room_pair_evaluations": 2377059,
        "sparse_room_constraints": 1274444,
        "model_variables": 1,
        "model_constraints": 1,
        "model_proto_bytes": 0,
        "source_student_records_excluded": 1,
        "source_soft_distributions_excluded": 1,
    }


def _success_worker_payload(binding: dict[str, object]) -> dict[str, object]:
    return {
        "schema": runner.WORKER_SCHEMA,
        "run_id": runner.RUN_ID,
        "binding": binding,
        "outcome": "BUILT_WITHOUT_SOLVE",
        "result": {
            "status": "BUILT",
            "build_only": True,
            "has_model": True,
            "solver_status": "NOT_RUN",
            "has_validated_candidate": False,
            "placement_count": 0,
            "solver_constructor_calls": 0,
            "telemetry": _telemetry(),
        },
        "error": None,
    }


def _claim(
    *,
    token: str = TOKEN,
    authorization_sha256: str = AUTHORIZATION_SHA256,
    runner_sha256: str = RUNNER_SHA256,
    parent_identity: dict[str, int] = PARENT_IDENTITY,
) -> dict[str, object]:
    return {
        "schema": runner.CLAIM_SCHEMA,
        "run_id": runner.RUN_ID,
        "token": token,
        "owner_pid": parent_identity["pid"],
        "owner_identity": dict(parent_identity),
        "authorization_sha256": authorization_sha256,
        "runner_sha256": runner_sha256,
        "claimed_at_utc": "mock-claim-time",
    }


def _claim_material(claim: dict[str, object]) -> tuple[bytes, str]:
    encoded = runner._encode_json(claim)
    return encoded, hashlib.sha256(encoded).hexdigest()


def _alternate_claim_encoding(canonical: bytes, mode: str) -> bytes:
    payload = json.loads(canonical)
    if mode == "compact":
        return json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    if mode == "reordered":
        reordered = dict(reversed(tuple(payload.items())))
        return (
            json.dumps(reordered, indent=2, sort_keys=False, allow_nan=False) + "\n"
        ).encode("utf-8")
    if mode == "duplicate-key":
        return b'{"schema":"duplicate",' + canonical[1:]
    if mode == "missing-lf":
        return canonical.removesuffix(b"\n")
    if mode == "type-confusion":
        payload["owner_pid"] = float(payload["owner_pid"])
        return runner._encode_json(payload)
    raise AssertionError("unknown alternate claim encoding")


def _patch_runtime_paths(monkeypatch: pytest.MonkeyPatch, temporary_root: Path) -> None:
    monkeypatch.setattr(runner, "RECEIPT_PATH", temporary_root / "attempt.json")
    monkeypatch.setattr(runner, "CLAIM_PATH", temporary_root / "claim.json")
    monkeypatch.setattr(runner, "HANDOFF_PATH", temporary_root / "handoff.json")
    monkeypatch.setattr(runner, "WORKER_RESULT_PATH", temporary_root / "worker.json")
    monkeypatch.setattr(
        runner,
        "EVENT_PATHS",
        {name: temporary_root / f"event-{name}.json" for name in runner.EVENT_SEQUENCE},
    )
    monkeypatch.setattr(
        runner,
        "FALLBACK_RECEIPT_TEMP_PATH",
        temporary_root / "claim-error.tmp",
    )


def _patch_parent_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    authorization = {"rejected_predecessors": [{"run_id": "rejected"}]}
    evidence = {"runner": {"sha256": RUNNER_SHA256}}
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda **_kwargs: (
            authorization,
            AUTHORIZATION_SHA256,
            evidence,
            [4_000_000_000, 4_000_000_000],
        ),
    )
    monkeypatch.setattr(runner, "_process_identity", lambda _pid: PARENT_IDENTITY)


def _configure_claimed_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], dict[str, dict[str, object]], _FakeProcess]:
    claim = _claim()
    runner.CLAIM_PATH.write_bytes(runner._encode_json(claim))
    evidence = {"runner": {"sha256": RUNNER_SHA256}}
    process = _FakeProcess()

    def process_identity(pid: int) -> dict[str, int]:
        if pid == PARENT_IDENTITY["pid"]:
            return dict(PARENT_IDENTITY)
        if pid == CHILD_IDENTITY["pid"]:
            return dict(CHILD_IDENTITY)
        raise RuntimeError("unexpected process")

    monkeypatch.setattr(runner, "_process_identity", process_identity)
    monkeypatch.setattr(runner, "_launch_worker", lambda _token: (process, 0.0))
    monkeypatch.setattr(runner, "_verify_evidence", lambda _evidence: None)
    return claim, evidence, process


def _parent_binding() -> dict[str, object]:
    return runner._session_binding(
        token=TOKEN,
        claim_sha256=runner._sha256(runner.CLAIM_PATH),
        claim_evidence=runner._file_evidence(runner.CLAIM_PATH),
        parent_identity=PARENT_IDENTITY,
        child_identity=CHILD_IDENTITY,
        authorization_sha256=AUTHORIZATION_SHA256,
        runner_sha256=RUNNER_SHA256,
        handoff_sha256=runner._sha256(runner.HANDOFF_PATH),
    )


def _install_valid_worker_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object]]:
    _patch_runtime_paths(monkeypatch, tmp_path)
    authorization = tmp_path / "authorization.json"
    authorization.write_text('{"authorized":true}\n', encoding="utf-8")
    monkeypatch.setattr(runner, "AUTHORIZATION_PATH", authorization)
    authorization_sha256 = runner._sha256(authorization)
    runner_sha256 = runner._sha256(Path(runner.__file__).resolve())
    claim = _claim(
        authorization_sha256=authorization_sha256,
        runner_sha256=runner_sha256,
    )
    runner.CLAIM_PATH.write_bytes(runner._encode_json(claim))
    claim_evidence = runner._file_evidence(runner.CLAIM_PATH)
    handoff = runner._handoff_payload(
        token=TOKEN,
        claim_snapshot=claim,
        claim_sha256=runner._sha256(runner.CLAIM_PATH),
        claim_evidence=claim_evidence,
        parent_identity=PARENT_IDENTITY,
        child_identity=CHILD_IDENTITY,
        authorization_sha256=authorization_sha256,
        runner_sha256=runner_sha256,
    )
    runner.HANDOFF_PATH.write_bytes(runner._encode_json(handoff))

    def process_identity(pid: int) -> dict[str, int]:
        if pid == PARENT_IDENTITY["pid"]:
            return dict(PARENT_IDENTITY)
        if pid == CHILD_IDENTITY["pid"]:
            return dict(CHILD_IDENTITY)
        raise RuntimeError("unexpected process identity request")

    monkeypatch.setattr(runner.os, "getpid", lambda: CHILD_IDENTITY["pid"])
    monkeypatch.setattr(runner.os, "getppid", lambda: 5884)
    monkeypatch.setattr(runner, "_process_identity", process_identity)
    return claim, handoff


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["binding"].__setitem__("token", "f" * 32),
        lambda payload: payload["binding"].__setitem__("claim_sha256", "f" * 64),
        lambda payload: payload["binding"].__setitem__("parent_pid", 4243),
        lambda payload: payload["binding"]["parent_identity"].__setitem__(
            "creation_time_100ns", 1
        ),
        lambda payload: payload["binding"].__setitem__("child_pid", 4344),
        lambda payload: payload["binding"]["child_identity"].__setitem__(
            "creation_time_100ns", 1
        ),
        lambda payload: payload["binding"].__setitem__(
            "authorization_sha256", "f" * 64
        ),
        lambda payload: payload["binding"].__setitem__("runner_sha256", "f" * 64),
        lambda payload: payload["binding"].__setitem__("handoff_sha256", "f" * 64),
    ),
)
def test_worker_result_rejects_forged_session_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: object,
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    payload = _success_worker_payload(_binding())
    mutation(payload)
    runner.WORKER_RESULT_PATH.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="worker result"):
        runner._read_worker_result(_binding())


def test_worker_result_and_complete_events_accept_only_current_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    binding = _binding()
    runner.WORKER_RESULT_PATH.write_text(
        json.dumps(_success_worker_payload(binding)), encoding="utf-8"
    )
    for event in runner.EVENT_SEQUENCE:
        runner._mark_event(event, binding)

    payload = runner._read_worker_result(binding)
    scope, events = runner._event_scope(binding)

    assert payload["outcome"] == "BUILT_WITHOUT_SOLVE"
    assert events == runner.EVENT_SEQUENCE
    assert scope["official_input_used"] is True
    assert scope["model_construction_completed"] is True


def test_broker_parent_mismatch_accepts_exact_handoff_without_using_getppid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_valid_worker_handoff(tmp_path, monkeypatch)
    parser_calls = 0
    builder_calls = 0

    def parser_forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal parser_calls
        parser_calls += 1
        raise AssertionError("parser must not run in binding test")

    def builder_forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal builder_calls
        builder_calls += 1
        raise AssertionError("builder must not run in binding test")

    monkeypatch.setattr(runner, "parse_itc2019_xml", parser_forbidden)
    monkeypatch.setattr(runner, "solve_itc2019_timetable_factorized", builder_forbidden)

    binding, handoff_evidence, claim_evidence = runner._validate_worker_handoff(TOKEN)

    assert binding["parent_pid"] == PARENT_IDENTITY["pid"]
    assert binding["child_pid"] == CHILD_IDENTITY["pid"]
    assert binding["handoff_sha256"] == handoff_evidence["sha256"]
    assert binding["claim_evidence"] == claim_evidence
    assert parser_calls == 0
    assert builder_calls == 0


def test_worker_handoff_accepts_exact_canonical_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _claim_snapshot, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)

    assert runner.HANDOFF_PATH.read_bytes() == runner._encode_json(handoff)
    binding, evidence, claim_evidence = runner._validate_worker_handoff(TOKEN)
    assert binding["handoff_sha256"] == evidence["sha256"]
    assert binding["claim_evidence"] == claim_evidence


@pytest.mark.parametrize("encoding", ("compact", "reordered"))
def test_worker_handoff_rejects_noncanonical_equivalent_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
) -> None:
    _claim_snapshot, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    if encoding == "compact":
        encoded = json.dumps(
            handoff,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    else:
        encoded = (
            json.dumps(handoff, indent=2, sort_keys=False, allow_nan=False) + "\n"
        ).encode("utf-8")
    assert json.loads(encoded) == handoff
    assert encoded != runner._encode_json(handoff)
    runner.HANDOFF_PATH.write_bytes(encoded)

    with pytest.raises(RuntimeError, match="canonical"):
        runner._validate_worker_handoff(TOKEN)


def test_worker_handoff_rejects_duplicate_json_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _claim_snapshot, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    encoded = b'{"schema":"duplicate",' + runner._encode_json(handoff)[1:]
    runner.HANDOFF_PATH.write_bytes(encoded)

    with pytest.raises(RuntimeError, match="duplicate JSON member"):
        runner._validate_worker_handoff(TOKEN)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.__setitem__("token", "f" * 32),
        lambda payload: payload.__setitem__("claim_sha256", "f" * 64),
        lambda payload: payload.__setitem__("authorization_sha256", "f" * 64),
        lambda payload: payload.__setitem__("runner_sha256", "f" * 64),
        lambda payload: payload.__setitem__("child_pid", CHILD_IDENTITY["pid"] + 1),
        lambda payload: payload["child_identity"].__setitem__("creation_time_100ns", 1),
        lambda payload: payload.__setitem__("parent_pid", PARENT_IDENTITY["pid"] + 1),
        lambda payload: payload["parent_identity"].__setitem__(
            "creation_time_100ns", 1
        ),
        lambda payload: payload.__setitem__("extra", "candidate"),
    ),
)
def test_worker_handoff_rejects_identity_token_hash_and_schema_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: object,
) -> None:
    _claim_snapshot, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    mutation(handoff)
    runner.HANDOFF_PATH.write_bytes(runner._encode_json(handoff))

    with pytest.raises(RuntimeError, match="handoff"):
        runner._validate_worker_handoff(TOKEN)


@pytest.mark.parametrize(
    "mode",
    (
        "omission",
        "addition",
        "type-confusion",
        "mtime-drift",
        "path-drift",
        "sha-drift",
    ),
)
def test_worker_handoff_rejects_claim_identity_evidence_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _claim_snapshot, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    claim_evidence = handoff["claim_evidence"]
    assert type(claim_evidence) is dict
    if mode == "omission":
        claim_evidence.pop("inode")
    elif mode == "addition":
        claim_evidence["candidate"] = "forged"
    elif mode == "type-confusion":
        claim_evidence["device"] = float(claim_evidence["device"])
    elif mode == "mtime-drift":
        claim_evidence["mtime_ns"] += 1
    elif mode == "path-drift":
        claim_evidence["resolved_path"] += ".replacement"
    else:
        claim_evidence["sha256"] = "f" * 64
    runner.HANDOFF_PATH.write_bytes(runner._encode_json(handoff))

    with pytest.raises(RuntimeError, match="handoff"):
        runner._validate_worker_handoff(TOKEN)


@pytest.mark.parametrize(
    "mode",
    (
        "omission",
        "addition",
        "type-confusion",
        "mtime-drift",
        "path-drift",
        "sha-drift",
    ),
)
def test_worker_session_binding_rejects_claim_identity_evidence_mutations(
    mode: str,
) -> None:
    claim_evidence = deepcopy(CLAIM_EVIDENCE)
    if mode == "omission":
        claim_evidence.pop("inode")
    elif mode == "addition":
        claim_evidence["candidate"] = "forged"
    elif mode == "type-confusion":
        claim_evidence["inode"] = True
    elif mode == "mtime-drift":
        claim_evidence["mtime_ns"] = 4.0
    elif mode == "path-drift":
        claim_evidence["resolved_path"] = 7
    else:
        claim_evidence["sha256"] = "f" * 64

    with pytest.raises(RuntimeError, match="file evidence|session binding"):
        runner._session_binding(
            token=TOKEN,
            claim_sha256=CLAIM_SHA256,
            claim_evidence=claim_evidence,
            parent_identity=PARENT_IDENTITY,
            child_identity=CHILD_IDENTITY,
            authorization_sha256=AUTHORIZATION_SHA256,
            runner_sha256=RUNNER_SHA256,
            handoff_sha256=HANDOFF_SHA256,
        )


def test_worker_session_rejects_byte_identical_claim_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_valid_worker_handoff(tmp_path, monkeypatch)
    binding, handoff_evidence, claim_evidence = runner._validate_worker_handoff(TOKEN)
    original_claim = runner.CLAIM_PATH.read_bytes()
    replacement = tmp_path / "replacement-claim.json"
    replacement.write_bytes(original_claim)
    runner.os.replace(replacement, runner.CLAIM_PATH)
    replaced_evidence = runner._file_evidence(runner.CLAIM_PATH)

    assert runner.CLAIM_PATH.read_bytes() == original_claim
    assert replaced_evidence["sha256"] == claim_evidence["sha256"]
    assert replaced_evidence != claim_evidence
    assert (
        replaced_evidence["inode"] != claim_evidence["inode"]
        or replaced_evidence["mtime_ns"] != claim_evidence["mtime_ns"]
        or replaced_evidence["device"] != claim_evidence["device"]
    )
    with pytest.raises(RuntimeError, match="claim file identity drift"):
        runner._verify_worker_session_current(binding, handoff_evidence, claim_evidence)


def test_worker_handoff_rejects_claim_schema_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    claim["candidate"] = "forged"
    handoff["claim_snapshot"] = claim
    runner.CLAIM_PATH.write_bytes(runner._encode_json(claim))
    handoff["claim_sha256"] = runner._sha256(runner.CLAIM_PATH)
    runner.HANDOFF_PATH.write_bytes(runner._encode_json(handoff))

    with pytest.raises(RuntimeError, match="claim ownership"):
        runner._validate_worker_handoff(TOKEN)


def test_worker_session_rejects_replaced_handoff_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_valid_worker_handoff(tmp_path, monkeypatch)
    binding, evidence, claim_evidence = runner._validate_worker_handoff(TOKEN)
    replacement = runner._strict_json(runner.HANDOFF_PATH)
    replacement["token"] = "f" * 32
    runner.HANDOFF_PATH.write_bytes(runner._encode_json(replacement))

    with pytest.raises(RuntimeError, match="handoff"):
        runner._verify_worker_session_current(binding, evidence, claim_evidence)


def test_worker_handoff_rejects_rival_claim_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_valid_worker_handoff(tmp_path, monkeypatch)
    runner.CLAIM_PATH.write_bytes(runner._encode_json(_claim(token="f" * 32)))

    with pytest.raises(RuntimeError, match="handoff"):
        runner._validate_worker_handoff(TOKEN)


@pytest.mark.parametrize("failure_mode", ("dead", "identity-change"))
def test_worker_handoff_rejects_parent_death_or_creation_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    _install_valid_worker_handoff(tmp_path, monkeypatch)

    def changed_identity(pid: int) -> dict[str, int]:
        if pid == CHILD_IDENTITY["pid"]:
            return dict(CHILD_IDENTITY)
        if failure_mode == "dead":
            raise RuntimeError("parent no longer exists")
        return {"pid": PARENT_IDENTITY["pid"], "creation_time_100ns": 1}

    monkeypatch.setattr(runner, "_process_identity", changed_identity)

    with pytest.raises(RuntimeError, match="parent|handoff"):
        runner._validate_worker_handoff(TOKEN)


def test_worker_handoff_wait_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    readings = iter((10.0, 10.0 + runner.HANDOFF_WAIT_LIMIT_SECONDS))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(readings))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="handoff"):
        runner._wait_for_worker_handoff(TOKEN)


def test_events_require_authenticated_exact_prefix_and_mark_input_used_on_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    binding = _binding()
    runner._mark_event("parse-started", binding)

    scope, observed = runner._event_scope(binding)

    assert observed == ("parse-started",)
    assert scope["official_input_parse_started"] is True
    assert scope["official_input_parse_completed"] is False
    assert scope["official_input_used"] is True


def test_events_reject_forged_binding_and_sequence_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    forged = _binding()
    forged["claim_sha256"] = "f" * 64
    runner._mark_event("parse-started", forged)
    with pytest.raises(RuntimeError, match="event binding"):
        runner._event_scope(_binding())

    runner.EVENT_PATHS["parse-started"].unlink()
    runner._mark_event("parse-completed", _binding())
    with pytest.raises(RuntimeError, match="event binding"):
        runner._event_scope(_binding())


def test_malformed_later_event_preserves_authenticated_input_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    claim, evidence, _process = _configure_claimed_parent(monkeypatch)

    def worker_wait(_process: _FakeProcess, _started: float) -> tuple[bool, int, float]:
        binding = _parent_binding()
        runner._mark_event("parse-started", binding)
        runner.EVENT_PATHS["parse-completed"].write_text("{malformed", encoding="utf-8")
        return False, 1, 0.1

    monkeypatch.setattr(runner, "_wait_for_launched_worker", worker_wait)
    intended_claim_encoded, intended_claim_sha256 = _claim_material(claim)

    exit_code = runner._claimed_parent_main(
        authorization={"rejected_predecessors": []},
        authorization_hash=AUTHORIZATION_SHA256,
        evidence=evidence,
        memory_readings=[],
        token=TOKEN,
        parent_identity=PARENT_IDENTITY,
        claim_snapshot=claim,
        intended_claim_encoded=intended_claim_encoded,
        intended_claim_sha256=intended_claim_sha256,
    )

    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["outcome"] == "ERROR"
    assert receipt["worker_event_sequence"] == ["parse-started"]
    assert receipt["scope"]["official_input_parse_started"] is True
    assert receipt["scope"]["official_input_used"] is True


@pytest.mark.parametrize(
    "return_code,events",
    (
        (7, runner.EVENT_SEQUENCE),
        (0, runner.EVENT_SEQUENCE[:-1]),
    ),
)
def test_parent_rejects_false_success_exit_or_incomplete_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    return_code: int,
    events: tuple[str, ...],
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    claim, evidence, _process = _configure_claimed_parent(monkeypatch)
    runner.WORKER_RESULT_PATH.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_wait_for_launched_worker",
        lambda _process, _started: (False, return_code, 0.1),
    )
    monkeypatch.setattr(
        runner,
        "_read_worker_result",
        lambda binding: _success_worker_payload(binding),
    )
    monkeypatch.setattr(
        runner,
        "_event_scope",
        lambda _binding: (runner._scope_from_event_prefix(events), events),
    )
    intended_claim_encoded, intended_claim_sha256 = _claim_material(claim)

    exit_code = runner._claimed_parent_main(
        authorization={"rejected_predecessors": []},
        authorization_hash=AUTHORIZATION_SHA256,
        evidence=evidence,
        memory_readings=[],
        token=TOKEN,
        parent_identity=PARENT_IDENTITY,
        claim_snapshot=claim,
        intended_claim_encoded=intended_claim_encoded,
        intended_claim_sha256=intended_claim_sha256,
    )

    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["outcome"] == "ERROR"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.__setitem__("workers", True),
        lambda payload: payload.__setitem__("build_time_limit_seconds", 570),
        lambda payload: payload["construction_limits"].__setitem__(
            "max_domain_values", 2_500_000.0
        ),
        lambda payload: payload["scope"].__setitem__("attempts_authorized", True),
        lambda payload: payload["scope"].__setitem__(
            "cp_solver_construction_authorized", 0
        ),
        lambda payload: payload["reviewed_admission_evidence"][
            "durable_metrics"
        ].__setitem__("admitted", 1),
        lambda payload: payload["watchdog"].__setitem__("worker_result_create_only", 1),
        lambda payload: payload["watchdog"].__setitem__("broker_tolerant_handoff", 1),
    ),
)
def test_authorization_rejects_recursive_scalar_type_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: object,
) -> None:
    runner_hash = runner._sha256(Path(runner.__file__).resolve())
    payload = deepcopy(runner._expected_authorization(runner_hash))
    mutate(payload)
    authorization = tmp_path / "authorization.json"
    authorization.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(runner, "AUTHORIZATION_PATH", authorization)

    with pytest.raises(RuntimeError, match="type-exact"):
        runner._validate_authorization()


def test_current_authorization_is_type_exact_and_bound() -> None:
    authorization, authorization_hash = runner._validate_authorization()

    assert authorization["run_id"] == runner.RUN_ID
    assert authorization_hash == runner._sha256(runner.AUTHORIZATION_PATH)


def test_every_authorization_numeric_scalar_rejects_equal_wrong_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_hash = runner._sha256(Path(runner.__file__).resolve())
    expected = runner._expected_authorization(runner_hash)
    paths: list[tuple[object, ...]] = []

    def collect(value: object, path: tuple[object, ...] = ()) -> None:
        if type(value) is dict:
            for key, child in value.items():
                collect(child, (*path, key))
        elif type(value) is list:
            for index, child in enumerate(value):
                collect(child, (*path, index))
        elif type(value) in {bool, int, float}:
            paths.append(path)

    def replace(payload: object, path: tuple[object, ...], value: object) -> None:
        parent = payload
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value

    collect(expected)
    authorization_path = tmp_path / "authorization.json"
    monkeypatch.setattr(runner, "AUTHORIZATION_PATH", authorization_path)
    for path in paths:
        payload = deepcopy(expected)
        value = payload
        for key in path:
            value = value[key]
        if type(value) is bool:
            replacement = int(value)
        elif type(value) is int:
            replacement = float(value)
        else:
            replacement = int(value)
        replace(payload, path, replacement)
        authorization_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RuntimeError, match="type-exact"):
            runner._validate_authorization()

    assert len(paths) >= 20


def test_every_failure_after_claim_writes_error_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    monkeypatch.setattr(
        runner,
        "_claimed_parent_main",
        lambda **_kwargs: (_ for _ in ()).throw(MemoryError()),
    )

    assert runner._parent_main() == 1
    assert runner.CLAIM_PATH.exists()
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt == {
        "schema": runner.ATTEMPT_SCHEMA,
        "run_id": runner.RUN_ID,
        "outcome": "ERROR",
        "error": {"code": "POST_CLAIM_FAILURE"},
    }


def test_claim_evidence_capture_failure_writes_error_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    monkeypatch.setattr(
        runner,
        "_file_evidence",
        lambda _path: (_ for _ in ()).throw(MemoryError()),
    )

    assert runner._parent_main() == 1
    assert json.loads(runner.RECEIPT_PATH.read_text())["outcome"] == "ERROR"


def test_post_claim_timestamp_failure_writes_error_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    calls = iter(("claim-time", MemoryError()))

    def timestamp() -> str:
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(runner, "_utc_now", timestamp)

    assert runner._parent_main() == 1
    assert json.loads(runner.RECEIPT_PATH.read_text())["outcome"] == "ERROR"


def test_minimal_fallback_survives_normal_finalizer_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    monkeypatch.setattr(
        runner,
        "_claimed_parent_main",
        lambda **_kwargs: (_ for _ in ()).throw(MemoryError()),
    )
    monkeypatch.setattr(
        runner,
        "_finalize_receipt",
        lambda _payload: (_ for _ in ()).throw(MemoryError()),
    )

    assert runner._parent_main() == 1
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="ascii"))
    assert receipt["outcome"] == "ERROR"
    assert receipt["error"]["code"] == "POST_CLAIM_FAILURE"


def test_post_link_claim_publication_failure_still_writes_error_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    publish = runner._publish_bytes_create_only

    def publish_then_fail(path: Path, payload: bytes) -> None:
        publish(path, payload)
        if path == runner.CLAIM_PATH:
            raise MemoryError()

    monkeypatch.setattr(runner, "_publish_bytes_create_only", publish_then_fail)

    assert runner._parent_main() == 1
    assert runner.CLAIM_PATH.exists()
    assert json.loads(runner.RECEIPT_PATH.read_text())["outcome"] == "ERROR"


@pytest.mark.parametrize(
    "mode",
    ("compact", "reordered", "duplicate-key", "missing-lf", "type-confusion"),
)
def test_parent_rejects_prebaseline_claim_substitution_before_worker_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    monkeypatch.setattr(runner.os, "getpid", lambda: PARENT_IDENTITY["pid"])
    publish = runner._publish_bytes_create_only
    intended_claims: list[bytes] = []
    launch_tokens: list[str] = []

    def publish_then_replace(path: Path, payload: bytes) -> None:
        publish(path, payload)
        if path == runner.CLAIM_PATH:
            intended_claims.append(payload)
            path.write_bytes(_alternate_claim_encoding(payload, mode))

    def forbidden_launch(token: str) -> None:
        launch_tokens.append(token)
        raise AssertionError(
            "worker launch must follow exact claim baseline validation"
        )

    monkeypatch.setattr(runner, "_publish_bytes_create_only", publish_then_replace)
    monkeypatch.setattr(runner, "_launch_worker", forbidden_launch)

    assert runner._parent_main() == 1
    assert len(intended_claims) == 1
    assert runner.CLAIM_PATH.read_bytes() != intended_claims[0]
    assert launch_tokens == []
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "ERROR"
    assert receipt["error"]["code"] == "POST_CLAIM_FAILURE"


@pytest.mark.parametrize(
    "mode",
    ("compact", "reordered", "duplicate-key", "missing-lf", "type-confusion"),
)
def test_child_independently_rejects_alternate_claim_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _canonical_claim, handoff = _install_valid_worker_handoff(tmp_path, monkeypatch)
    canonical = runner.CLAIM_PATH.read_bytes()
    alternate = _alternate_claim_encoding(canonical, mode)
    runner.CLAIM_PATH.write_bytes(alternate)
    if mode != "duplicate-key":
        handoff["claim_snapshot"] = json.loads(alternate)
        handoff["claim_sha256"] = hashlib.sha256(alternate).hexdigest()
        handoff["claim_evidence"] = runner._file_evidence(runner.CLAIM_PATH)
        runner.HANDOFF_PATH.write_bytes(runner._encode_json(handoff))

    with pytest.raises(RuntimeError, match="claim|duplicate JSON member"):
        runner._validate_worker_handoff(TOKEN)


def test_parent_rejects_intended_claim_hash_mismatch_before_worker_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    claim, evidence, _process = _configure_claimed_parent(monkeypatch)
    intended_claim_encoded, _intended_claim_sha256 = _claim_material(claim)
    launch_tokens: list[str] = []

    def forbidden_launch(token: str) -> None:
        launch_tokens.append(token)
        raise AssertionError("worker launch must follow intended claim hash validation")

    monkeypatch.setattr(runner, "_launch_worker", forbidden_launch)

    with pytest.raises(RuntimeError, match="canonical bytes or hash"):
        runner._claimed_parent_main(
            authorization={"rejected_predecessors": []},
            authorization_hash=AUTHORIZATION_SHA256,
            evidence=evidence,
            memory_readings=[],
            token=TOKEN,
            parent_identity=PARENT_IDENTITY,
            claim_snapshot=claim,
            intended_claim_encoded=intended_claim_encoded,
            intended_claim_sha256="f" * 64,
        )

    assert launch_tokens == []
    assert not runner.HANDOFF_PATH.exists()


def test_claim_publication_race_loser_never_finalizes_foreign_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    _patch_parent_preflight(monkeypatch)
    publish = runner._publish_bytes_create_only
    foreign_serialized_claim = runner._encode_json(_claim(token="f" * 32))

    def lose_race(path: Path, payload: bytes) -> None:
        if path == runner.CLAIM_PATH:
            publish(path, foreign_serialized_claim)
            raise FileExistsError("foreign claim won")
        publish(path, payload)

    monkeypatch.setattr(runner, "_publish_bytes_create_only", lose_race)

    with pytest.raises(FileExistsError, match="foreign claim won"):
        runner._parent_main()

    assert runner.CLAIM_PATH.read_bytes() == foreign_serialized_claim
    assert not runner.RECEIPT_PATH.exists()


def test_success_requires_exit_zero_and_complete_authenticated_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_runtime_paths(monkeypatch, tmp_path)
    claim, evidence, _process = _configure_claimed_parent(monkeypatch)
    runner.WORKER_RESULT_PATH.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_wait_for_launched_worker",
        lambda _process, _started: (False, 0, 0.1),
    )
    monkeypatch.setattr(
        runner,
        "_read_worker_result",
        lambda binding: _success_worker_payload(binding),
    )
    monkeypatch.setattr(
        runner,
        "_event_scope",
        lambda _binding: (
            runner._scope_from_event_prefix(runner.EVENT_SEQUENCE),
            runner.EVENT_SEQUENCE,
        ),
    )
    intended_claim_encoded, intended_claim_sha256 = _claim_material(claim)

    exit_code = runner._claimed_parent_main(
        authorization={"rejected_predecessors": []},
        authorization_hash=AUTHORIZATION_SHA256,
        evidence=evidence,
        memory_readings=[],
        token=TOKEN,
        parent_identity=PARENT_IDENTITY,
        claim_snapshot=claim,
        intended_claim_encoded=intended_claim_encoded,
        intended_claim_sha256=intended_claim_sha256,
    )

    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert receipt["outcome"] == "BUILT_WITHOUT_SOLVE"
    assert receipt["worker_event_sequence"] == list(runner.EVENT_SEQUENCE)
    assert receipt["handoff_sha256"] == runner._sha256(runner.HANDOFF_PATH)
    assert receipt["worker_session_binding"]["child_identity"] == CHILD_IDENTITY


def test_consumed_predecessor_chain_is_exact_and_rejected() -> None:
    expected = (
        (
            runner.IMMEDIATE_PREDECESSOR_RECEIPT_PATH,
            runner.EXPECTED_IMMEDIATE_PREDECESSOR_RECEIPT_SHA256,
            runner.IMMEDIATE_PREDECESSOR_RUN_ID,
            "planora.itc2019.pu-official-build-only-attempt.v2",
        ),
        (
            runner.ORIGINAL_PREDECESSOR_RECEIPT_PATH,
            runner.EXPECTED_ORIGINAL_PREDECESSOR_RECEIPT_SHA256,
            runner.ORIGINAL_PREDECESSOR_RUN_ID,
            "planora.itc2019.pu-official-build-only-attempt.v1",
        ),
    )
    for path, expected_hash, run_id, schema in expected:
        assert runner._sha256(path) == expected_hash
        payload = runner._strict_json(path)
        assert payload["run_id"] == run_id
        assert payload["schema"] == schema
        assert payload["outcome"] == "ERROR"
    consumed = runner._strict_json(runner.IMMEDIATE_PREDECESSOR_RECEIPT_PATH)
    assert consumed["worker_return_code"] == 2
    assert consumed["worker_event_sequence"] == []
    assert consumed["scope"]["official_input_used"] is False


def test_parser_builder_and_solver_are_reachable_only_from_worker_entrypoint() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    sensitive_calls: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            name = ""
            if isinstance(child.func, ast.Name):
                name = child.func.id
            elif isinstance(child.func, ast.Attribute):
                name = child.func.attr
            if name in {
                "parse_itc2019_xml",
                "solve_itc2019_timetable_factorized",
                "CpSolver",
            }:
                sensitive_calls.append((node.name, name))

    assert sensitive_calls == [
        ("_worker_main", "parse_itc2019_xml"),
        ("_worker_main", "solve_itc2019_timetable_factorized"),
    ]
    assert "os.getppid" not in source


def test_no_fresh_attempt_artifacts_exist_in_workspace() -> None:
    assert not runner.RECEIPT_PATH.exists()
    assert not runner.CLAIM_PATH.exists()
    assert not runner.HANDOFF_PATH.exists()
    assert not runner.WORKER_RESULT_PATH.exists()
    assert not runner.FALLBACK_RECEIPT_TEMP_PATH.exists()
    assert not any(path.exists() for path in runner.EVENT_PATHS.values())
