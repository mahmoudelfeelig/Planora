from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable

import pytest

from benchmarks.itc2019_resource_controller import (
    DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    resource_evidence_sha256,
)
from scripts.summarize_itc2019_competitor_matrix import (
    _direct_planora_pairwise_comparisons,
    _official_result,
    main,
    summarize,
)


SEEDS = (17, 23, 31)
HELPER_SHA256 = hashlib.sha256(b"official-validator-helper").hexdigest()
INPUT_SHA256 = hashlib.sha256(b"case-a-input").hexdigest()
CAPTURED_AT = "2026-08-26T00:00:00.000Z"
INTENT_CREATED_AT = "2026-08-25T23:59:59.000Z"
MATRIX_CREATED_UTC = "2026-08-26T00:01:00.000Z"
_UNSET = object()
_MATRIX_TEMP = Path(tempfile.mkdtemp(prefix="planora-matrix-summary-"))
_RESOURCE_PROFILE = {
    "schema": "planora.itc2019.resource-profile.v1",
    "wall_time_seconds": 60.0,
    "artifact_grace_seconds": 5.0,
    "memory_bytes": 2_147_483_648,
    "memory_swap_bytes": 2_147_483_648,
    "cpu_quota_us": 100_000,
    "cpu_period_us": 100_000,
    "cpuset_cpus": "0",
    "pids_limit": 128,
}
_RESOURCE_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(
        _RESOURCE_PROFILE,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()
_CONTROLLER_SOURCE_SHA256 = hashlib.sha256(b"resource-controller").hexdigest()
_CAPABILITY_SHA256 = hashlib.sha256(b"capabilities").hexdigest()
_SUPERVISOR_SHA256 = hashlib.sha256(b"supervisor").hexdigest()
_OFFICIAL_RUN_IDENTITY_FIELDS = (
    "run_id",
    "case",
    "solver",
    "seed",
    "effective_seed",
    "seed_control",
    "seed_pairing_group",
    "repetition",
    "unseeded_trial",
)
_OFFICIAL_SUBMISSION_INTENT_SCHEMA = "planora.itc2019.official-submission-intent.v1"
_OFFICIAL_RESPONSE_CAPTURE_SCHEMA = "planora.itc2019.official-response-capture.v1"
_OFFICIAL_EXTERNAL_SOURCE_AUTHENTICITY = (
    "endpoint_and_existing_cdp_session_observed_not_independently_attested"
)
_V3_BINDING_FIELDS = (
    "evidence_version",
    *_OFFICIAL_RUN_IDENTITY_FIELDS,
    "input_sha256",
    "response_sha256",
    "response_capture_binding_sha256",
    "submission_intent_binding_sha256",
    "submitted_output_sha256",
    "helper_sha256",
    "attempt_id",
    "captured_at",
    "response_url",
    "response_status",
    "response_content_type",
    "log_id",
    "request_method",
    "request_url",
    "request_content_type",
    "request_body_sha256",
    "uploaded_file_sha256",
    "correlation_method",
    "external_source_authenticity",
)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_matrix_temp() -> Any:
    yield
    shutil.rmtree(_MATRIX_TEMP, ignore_errors=True)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _expected_run(
    *, seed: int = 17, repetition: int = 1, solver: str = "planora"
) -> dict[str, Any]:
    return {
        "run_id": f"case-a__{solver}__seed-{seed}__rep-{repetition:02d}",
        "case": "case-a",
        "solver": solver,
        "seed": seed,
        "effective_seed": seed,
        "seed_control": "explicit",
        "seed_pairing_group": seed,
        "repetition": repetition,
        "unseeded_trial": None,
    }


def _official_response(*, total: int, log_id: str) -> bytes:
    return json.dumps(
        {
            "status": "200",
            "obj": {
                "instance": "case-a",
                "result": "OK",
                "assignedVariables": {"value": 3, "total": 3},
                "totalCost": {"value": total},
                "timePenalty": {"value": total},
                "roomPenalty": {"value": 0},
                "distributionPenalty": {"value": 0},
                "studentConflicts": {"value": 0},
                "logId": log_id,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _official_evidence(
    *, identity: dict[str, Any], total: int, output_sha256: str
) -> dict[str, Any]:
    run_id = identity["run_id"]
    log_id = f"log-{run_id}"
    raw_response = _official_response(total=total, log_id=log_id)
    response_url = f"https://itc2019.org/server/validator/{log_id}"
    attempt_suffix = hashlib.sha256(run_id.encode()).hexdigest()[:12]
    evidence = {
        "instance": "case-a",
        "result": "OK",
        "assigned": 3,
        "variables": 3,
        "total": total,
        "time": total,
        "room": 0,
        "distribution": 0,
        "student": 0,
        "log_id": log_id,
        **identity,
        "input_sha256": INPUT_SHA256,
        "request_method": "POST",
        "request_url": response_url,
        "request_content_type": "multipart/form-data; boundary=planora-test",
        "request_body_sha256": hashlib.sha256(f"request-{run_id}".encode()).hexdigest(),
        "uploaded_file_sha256": output_sha256,
        "attempt_id": f"11111111-1111-4111-8111-{attempt_suffix}",
        "submission_intent_created_at": INTENT_CREATED_AT,
        "evidence_version": 3,
        "correlation_method": (
            "playwright_response_request_identity_and_multipart_bytes"
        ),
        "external_source_authenticity": _OFFICIAL_EXTERNAL_SOURCE_AUTHENTICITY,
        "response_body_base64": base64.b64encode(raw_response).decode("ascii"),
        "response_sha256": hashlib.sha256(raw_response).hexdigest(),
        "submitted_output_sha256": output_sha256,
        "helper_sha256": HELPER_SHA256,
        "captured_at": CAPTURED_AT,
        "response_url": response_url,
        "response_status": 200,
        "response_content_type": "application/json;charset=UTF-8",
    }
    _rebind_all_official_evidence(evidence)
    return evidence


def _rebind_evidence(evidence: dict[str, Any]) -> None:
    binding = {field: evidence[field] for field in _V3_BINDING_FIELDS}
    evidence["evidence_binding_sha256"] = hashlib.sha256(
        _canonical_bytes(binding)
    ).hexdigest()


def _rebind_all_official_evidence(evidence: dict[str, Any]) -> None:
    intent = {
        "schema": _OFFICIAL_SUBMISSION_INTENT_SCHEMA,
        **{
            field: evidence[field]
            for field in (*_OFFICIAL_RUN_IDENTITY_FIELDS, "input_sha256")
        },
        "output_sha256": evidence["submitted_output_sha256"],
        "helper_sha256": evidence["helper_sha256"],
        "attempt_id": evidence["attempt_id"],
        "created_at": evidence["submission_intent_created_at"],
    }
    evidence["submission_intent_binding_sha256"] = hashlib.sha256(
        _canonical_bytes(intent)
    ).hexdigest()
    capture = {
        "schema": _OFFICIAL_RESPONSE_CAPTURE_SCHEMA,
        **{
            field: evidence[field]
            for field in (*_OFFICIAL_RUN_IDENTITY_FIELDS, "input_sha256")
        },
        **{
            field: evidence[field]
            for field in (
                "request_method",
                "request_url",
                "request_content_type",
                "request_body_sha256",
                "uploaded_file_sha256",
                "attempt_id",
                "submission_intent_created_at",
                "submission_intent_binding_sha256",
                "response_sha256",
                "submitted_output_sha256",
                "helper_sha256",
                "captured_at",
                "response_url",
                "response_status",
                "response_content_type",
                "correlation_method",
                "external_source_authenticity",
            )
        },
    }
    evidence["response_capture_binding_sha256"] = hashlib.sha256(
        _canonical_bytes(capture)
    ).hexdigest()
    _rebind_evidence(evidence)


def _artifact_binding(record: dict[str, Any]) -> str:
    identity_fields = (
        "run_id",
        "case",
        "solver",
        "seed",
        "effective_seed",
        "seed_control",
        "seed_pairing_group",
        "repetition",
        "unseeded_trial",
    )
    return hashlib.sha256(
        _canonical_bytes(
            {
                "identity": {field: record.get(field) for field in identity_fields},
                "output_relative_path": record["output_relative_path"],
                "output_sha256": record["output_sha256"],
            }
        )
    ).hexdigest()


def _resource_evidence(
    *,
    run_id: str,
    output_sha256: str | None,
    invocation: dict[str, Any] | None = None,
    invocation_sha256: str | None = None,
) -> dict[str, Any]:
    invocation = invocation or {"run_id": run_id}
    invocation_sha256 = (
        invocation_sha256 or hashlib.sha256(_canonical_bytes(invocation)).hexdigest()
    )
    evidence = {
        "schema": "planora.itc2019.resource-evidence.v1",
        "run_id": run_id,
        "profile_sha256": _RESOURCE_PROFILE_SHA256,
        "invocation": invocation,
        "invocation_sha256": invocation_sha256,
        "capability_sha256": _CAPABILITY_SHA256,
        "supervisor_sha256": _SUPERVISOR_SHA256,
        "artifact_sha256": output_sha256,
        "claim_grade_ready": True,
        "deadline_exceeded": False,
        "cleanup_complete": True,
        "residual_processes": 0,
        "elapsed_monotonic_ns": 30_000_000_000,
        "memory_peak_bytes": 1_073_741_824,
        "memory_swap_peak_bytes": 0,
        "effective_memory_max": _RESOURCE_PROFILE["memory_bytes"],
        "effective_memory_swap_max": 0,
        "effective_cpu_max": "100000 100000",
        "effective_cpuset_cpus": "0",
        "effective_pids_max": _RESOURCE_PROFILE["pids_limit"],
    }
    return evidence


def _record(
    *,
    seed: int = 17,
    repetition: int = 1,
    total: int = 80,
    matrix_root: Path = _MATRIX_TEMP,
    solver: str = "planora",
) -> dict[str, Any]:
    identity = _expected_run(seed=seed, repetition=repetition, solver=solver)
    artifact_bytes = identity["run_id"].encode()
    output_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    relative_path = f"runs/{identity['run_id']}/solution.xml"
    artifact = matrix_root / relative_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(artifact_bytes)
    record = {
        **identity,
        "input_sha256": INPUT_SHA256,
        "output_path": relative_path,
        "output_relative_path": relative_path,
        "output_sha256": output_sha256,
        "independent_validation": {
            "validator": "planora-separate-post-run-validation-v1",
            "feasible": True,
            "errors": [],
            "objective": {
                "total": total,
                "time": total,
                "room": 0,
                "distribution": 0,
                "student": 0,
            },
        },
        "official_validator_status": "agreement",
        "official_validator_agreement": True,
        "official_validated_output_sha256": output_sha256,
        "official_validation": _official_evidence(
            identity=identity,
            total=total,
            output_sha256=output_sha256,
        ),
    }
    record["artifact_binding_sha256"] = _artifact_binding(record)
    invocation = {"run_id": identity["run_id"]}
    invocation_sha256 = hashlib.sha256(_canonical_bytes(invocation)).hexdigest()
    record["controller_invocation"] = invocation
    record["controller_invocation_sha256"] = invocation_sha256
    record["resource_evidence"] = _resource_evidence(
        run_id=identity["run_id"],
        output_sha256=output_sha256,
        invocation=invocation,
        invocation_sha256=invocation_sha256,
    )
    record["resource_evidence_sha256"] = hashlib.sha256(
        _canonical_bytes(record["resource_evidence"])
    ).hexdigest()
    raw_evidence = {
        "schema": "planora.itc2019.raw-resource-evidence.v1",
        "invocation_sha256": invocation_sha256,
        "inspect": {"run_id": identity["run_id"]},
        "execution": {"run_id": identity["run_id"]},
        "cgroup": {"run_id": identity["run_id"]},
        "supervisor": {"run_id": identity["run_id"]},
        "capability_snapshot": {"run_id": identity["run_id"]},
        "cleanup_outcomes": [{"absence_verified": True}],
    }
    record["raw_resource_evidence"] = raw_evidence
    record["raw_resource_evidence_sha256"] = hashlib.sha256(
        _canonical_bytes(raw_evidence)
    ).hexdigest()
    run_dir = matrix_root / "runs" / identity["run_id"]
    resource_path = run_dir / "resource-evidence.json"
    raw_path = run_dir / "resource-evidence-raw.json"
    resource_path.write_bytes(_canonical_bytes(record["resource_evidence"]))
    raw_path.write_bytes(_canonical_bytes(raw_evidence))
    record["resource_evidence_path"] = str(resource_path.resolve())
    record["resource_evidence_file_sha256"] = hashlib.sha256(
        resource_path.read_bytes()
    ).hexdigest()
    record["raw_resource_evidence_path"] = str(raw_path.resolve())
    record["raw_resource_evidence_file_sha256"] = hashlib.sha256(
        raw_path.read_bytes()
    ).hexdigest()
    return record


def _mark_infeasible(record: dict[str, Any]) -> None:
    evidence = _resource_evidence(run_id=record["run_id"], output_sha256=None)
    record.update(
        output_path=None,
        output_relative_path=None,
        output_sha256=None,
        artifact_binding_sha256=None,
        independent_validation={
            "validator": "planora-separate-post-run-validation-v1",
            "feasible": False,
            "errors": ["no output produced"],
            "objective": None,
        },
        official_validator_status="pending_upload",
        official_validator_agreement=None,
        official_validated_output_sha256=None,
        official_validation=None,
        resource_evidence=evidence,
        resource_evidence_sha256=hashlib.sha256(_canonical_bytes(evidence)).hexdigest(),
    )


def _refresh_claim_evidence_set(report: dict[str, Any]) -> None:
    bindings = [
        {
            "run_id": record["run_id"],
            "resource_evidence_sha256": record["resource_evidence_sha256"],
        }
        for record in sorted(report["records"], key=lambda item: item["run_id"])
    ]
    report["manifest"]["resource_controller"]["claim_evidence_set_sha256"] = (
        hashlib.sha256(_canonical_bytes(bindings)).hexdigest()
    )


def _add_infeasible_comparator(report: dict[str, Any], solver: str) -> None:
    report["manifest"]["solvers"].append(solver)
    for seed in SEEDS:
        for repetition in (1, 2):
            identity = _expected_run(seed=seed, repetition=repetition, solver=solver)
            report["manifest"]["expected_runs"].append(identity)
            record = {**identity}
            _mark_infeasible(record)
            report["records"].append(record)


def _add_comparator(
    report: dict[str, Any], solver: str, totals: dict[tuple[int, int], int]
) -> None:
    report["manifest"]["solvers"].append(solver)
    for seed in SEEDS:
        for repetition in (1, 2):
            identity = _expected_run(seed=seed, repetition=repetition, solver=solver)
            report["manifest"]["expected_runs"].append(identity)
            report["records"].append(
                _record(
                    seed=seed,
                    repetition=repetition,
                    total=totals[(seed, repetition)],
                    solver=solver,
                )
            )
    _refresh_claim_evidence_set(report)


def _report(
    *,
    seeds: tuple[int, ...] = SEEDS,
    repetitions: int = 2,
    totals: dict[tuple[int, int], int] | None = None,
) -> dict[str, Any]:
    totals = totals or {}
    expected = [
        _expected_run(seed=seed, repetition=repetition)
        for seed in seeds
        for repetition in range(1, repetitions + 1)
    ]
    report = {
        "manifest": {
            "created_utc": MATRIX_CREATED_UTC,
            "cases": ["case-a"],
            "solvers": ["planora"],
            "seeds": list(seeds),
            "repetitions": repetitions,
            "inputs": {"case-a": INPUT_SHA256},
            "official_validator_helper_sha256": HELPER_SHA256,
            "expected_runs": expected,
            "resource_controller": {
                "mode": "claim-grade-controller",
                "claim_grade_ready": True,
                "equal_wall_time_claim": True,
                "equal_memory_limit_claim": True,
                "profile": dict(_RESOURCE_PROFILE),
                "profile_sha256": _RESOURCE_PROFILE_SHA256,
                "controller_source_sha256": _CONTROLLER_SOURCE_SHA256,
                "capability_sha256": _CAPABILITY_SHA256,
                "supervisor_sha256": _SUPERVISOR_SHA256,
            },
        },
        "records": [
            _record(
                seed=seed,
                repetition=repetition,
                total=totals.get((seed, repetition), 80),
            )
            for seed in seeds
            for repetition in range(1, repetitions + 1)
        ],
    }
    _refresh_claim_evidence_set(report)
    return report


def _official_payload(*, total: int = 100) -> dict[str, Any]:
    return {
        "url": "https://www.itc2019.org/competition/results",
        "captured_at": "2026-08-26T00:00:00Z",
        "tables": [
            [
                ["Rank", "Instance", "Total cost"],
                ["1", "case-a", str(total)],
            ]
        ],
    }


def _matrix_evidence_sha256(report: dict[str, Any]) -> str:
    manifest = report["manifest"]
    controller = manifest["resource_controller"]
    records = sorted(report["records"], key=lambda item: item["run_id"])
    claim_bindings = [
        {
            "run_id": record["run_id"],
            "resource_evidence_sha256": record["resource_evidence_sha256"],
        }
        for record in records
    ]
    raw_bindings = [
        {
            "run_id": record["run_id"],
            "controller_invocation_sha256": record["controller_invocation_sha256"],
            "resource_evidence_sha256": record["resource_evidence_sha256"],
            "resource_evidence_file_sha256": record["resource_evidence_file_sha256"],
            "raw_resource_evidence_sha256": record["raw_resource_evidence_sha256"],
            "raw_resource_evidence_file_sha256": record[
                "raw_resource_evidence_file_sha256"
            ],
            "output_sha256": record["output_sha256"],
            "artifact_binding_sha256": record["artifact_binding_sha256"],
        }
        for record in records
    ]
    binding = {
        "schema": "planora.itc2019.controller-raw-run-evidence-binding.v1",
        "matrix_created_utc": manifest["created_utc"],
        "manifest_sha256": hashlib.sha256(_canonical_bytes(manifest)).hexdigest(),
        "controller_binding_sha256": hashlib.sha256(
            _canonical_bytes(controller)
        ).hexdigest(),
        "records_sha256": hashlib.sha256(_canonical_bytes(records)).hexdigest(),
        "claim_evidence_set_sha256": hashlib.sha256(
            _canonical_bytes(claim_bindings)
        ).hexdigest(),
        "raw_run_evidence_set_sha256": hashlib.sha256(
            _canonical_bytes(raw_bindings)
        ).hexdigest(),
        "run_count": len(records),
    }
    return hashlib.sha256(_canonical_bytes(binding)).hexdigest()


def _trust_anchor(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "planora.itc2019.official-results-trust-anchor.v2",
        "mode": "pinned-controller-raw-run-evidence",
        "authority": "ITC 2019",
        "source_url": payload["url"],
        "captured_at": payload["captured_at"],
        "official_payload_sha256": hashlib.sha256(
            _canonical_bytes(payload)
        ).hexdigest(),
        "matrix_created_utc": report["manifest"]["created_utc"],
        "matrix_evidence_sha256": _matrix_evidence_sha256(report),
    }


def _summarize(
    report: dict[str, Any],
    official_payload: dict[str, Any] | None = None,
    *,
    expected_sha256: str | None | object = _UNSET,
    payload_bytes: bytes | None | object = _UNSET,
    matrix_root: Path | None = _MATRIX_TEMP,
    include_local_trust_anchor: bool = True,
    claim_eligibility_requested: bool = True,
    trust_anchor: Any = _UNSET,
    trust_anchor_bytes: bytes | None | object = _UNSET,
    expected_anchor_sha256: str | None | object = _UNSET,
    trust_anchor_source: str | None | object = _UNSET,
) -> dict[str, Any]:
    official_payload = official_payload or _official_payload()
    raw = (
        _canonical_bytes(official_payload) if payload_bytes is _UNSET else payload_bytes
    )
    expected = (
        hashlib.sha256(raw).hexdigest()
        if expected_sha256 is _UNSET and isinstance(raw, bytes)
        else expected_sha256
    )
    if trust_anchor is _UNSET:
        try:
            anchor = (
                _trust_anchor(report, official_payload)
                if include_local_trust_anchor
                else None
            )
        except (KeyError, TypeError):
            anchor = None
    else:
        anchor = trust_anchor
    if trust_anchor_bytes is _UNSET:
        anchor_bytes = _canonical_bytes(anchor) if anchor is not None else None
    else:
        anchor_bytes = trust_anchor_bytes
    if expected_anchor_sha256 is _UNSET:
        anchor_sha256 = (
            hashlib.sha256(anchor_bytes).hexdigest()
            if isinstance(anchor_bytes, bytes)
            else None
        )
    else:
        anchor_sha256 = expected_anchor_sha256
    if trust_anchor_source is _UNSET:
        anchor_source = (
            "command-line:--expected-official-trust-anchor-sha256"
            if anchor_sha256 is not None
            else None
        )
    else:
        anchor_source = trust_anchor_source
    return summarize(
        report,
        official_payload,
        claim_eligibility_requested=claim_eligibility_requested,
        matrix_root=matrix_root,
        expected_official_payload_sha256=expected,
        official_payload_bytes=raw,
        official_trust_anchor=anchor,
        official_trust_anchor_bytes=(
            anchor_bytes if isinstance(anchor_bytes, bytes) else None
        ),
        expected_official_trust_anchor_sha256=anchor_sha256,
        official_trust_anchor_source=anchor_source,
    )


def test_complete_replicated_matrix_accepts_concrete_pinned_evidence_anchor() -> None:
    result = _summarize(_report())

    assert result["matrix_complete"] is True
    assert result["claim_gate"] == {"passed": True, "blockers": []}
    assert result["diagnostics"]["official_trust_anchor_errors"] == []
    assert result["official_results_source"]["external_authenticity_unproven"] is False
    assert result["summary_mode"]["claim_eligibility_status"] == "eligible"
    comparison = result["comparisons"][0]
    assert comparison["local_best_total"] == 80
    assert comparison["descriptive_outcome"] == "better"
    assert comparison["comparison_eligible"] is True
    assert comparison["outcome"] == "better"
    assert len(comparison["paired_cells"]) == 6
    assert comparison["paired_statistics"] == {
        "prespecified_cell_count": 6,
        "observed_valid_cell_count": 6,
        "complete": True,
        "mean_total": 80.0,
        "median_total": 80.0,
        "mean_delta": -20.0,
        "median_delta": -20.0,
        "better": 6,
        "ties": 0,
        "worse": 0,
    }


def test_direct_planora_pairing_uses_matching_seed_cells_and_excludes_lemos() -> None:
    report = _report()
    _add_comparator(
        report,
        "gashi-sa",
        {
            (17, 1): 90,
            (17, 2): 80,
            (23, 1): 70,
            (23, 2): 90,
            (31, 1): 80,
            (31, 2): 70,
        },
    )

    result = _summarize(report)

    direct = result["direct_planora_pairwise_comparisons"]
    assert direct == [
        {
            "competitor": "gashi-sa",
            "identical_seed_pairing_eligible": True,
            "pairing_exclusion_reason": None,
            "comparison_eligible": True,
            "paired_cells": direct[0]["paired_cells"],
            "paired_statistics": {
                "prespecified_cell_count": 6,
                "observed_valid_cell_count": 6,
                "complete": True,
                "mean_planora_minus_competitor": 0.0,
                "median_planora_minus_competitor": 0.0,
                "planora_wins": 2,
                "ties": 2,
                "planora_losses": 2,
            },
        }
    ]
    assert all(
        set(cell)
        >= {
            "case",
            "seed_pairing_group",
            "repetition",
            "planora_minus_competitor",
            "outcome",
        }
        for cell in direct[0]["paired_cells"]
    )

    unseeded = {
        "run_id": "case-a__lemos-maxsat__unseeded-trial-001",
        "case": "case-a",
        "solver": "lemos-maxsat",
        "seed": None,
        "effective_seed": None,
        "seed_control": "unsupported_upstream_clock_seed",
        "seed_pairing_group": None,
        "repetition": 1,
        "unseeded_trial": 1,
    }
    excluded = _direct_planora_pairwise_comparisons(
        expected=[report["manifest"]["expected_runs"][0], unseeded],
        validated_by_id={},
        solvers=["planora", "lemos-maxsat"],
        claim_ready=True,
    )[0]
    assert excluded["identical_seed_pairing_eligible"] is False
    assert excluded["paired_cells"] == []
    assert excluded["pairing_exclusion_reason"] == (
        "no explicit deterministic seed pairing shared with Planora"
    )


def test_browser_helper_v3_evidence_is_ingested_without_validation_failures() -> None:
    report = _report()

    result = _summarize(report)

    assert all(
        record["official_validation"]["evidence_version"] == 3
        for record in report["records"]
    )
    assert result["diagnostics"]["official_validation_failures"] == []
    assert result["claim_gate"]["passed"] is True
    assert result["claim_gate"]["blockers"] == []


def test_actual_evidence_only_runner_schema_is_structurally_summarizable() -> None:
    report = _report()
    controller = report["manifest"]["resource_controller"]
    controller.update(
        mode="evidence-only-controller",
        controller_version="docker-cgroup-v2-phase2",
        config_sha256=hashlib.sha256(b"config").hexdigest(),
        claim_grade_ready=False,
        equal_wall_time_claim=False,
        equal_memory_limit_claim=False,
        readiness_blocker="trusted post-exit cgroup evidence remains incomplete",
    )
    for record in report["records"]:
        evidence = {
            "schema": DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
            "mode": "evidence-only-controller",
            "run_id": record["run_id"],
            "controller_version": "docker-cgroup-v2-phase2",
            "controller_source_sha256": _CONTROLLER_SOURCE_SHA256,
            "config_sha256": hashlib.sha256(b"config").hexdigest(),
            "profile": dict(_RESOURCE_PROFILE),
            "profile_sha256": _RESOURCE_PROFILE_SHA256,
            "capability_sha256": _CAPABILITY_SHA256,
            "supervisor_sha256": _SUPERVISOR_SHA256,
            "image_reference": "sha256:" + "a" * 64,
            "invocation": {"run_id": record["run_id"]},
            "invocation_sha256": hashlib.sha256(
                f"invoke-{record['run_id']}".encode()
            ).hexdigest(),
            "execution": {
                "run_id": record["run_id"],
                "timed_out": False,
                "cleanup_complete": True,
                "residual_processes": 0,
            },
            "cleanup": [{"action": "absence-verification", "absence_verified": True}],
            "artifact_sha256": record["output_sha256"],
            "trusted_supervisor_evidence_complete": False,
            "post_exit_cgroup_evidence_complete": False,
            "cross_runtime_image_guarantees_complete": False,
            "claim_grade_ready": False,
            "readiness_blocker": controller["readiness_blocker"],
        }
        record["resource_evidence"] = evidence
        record["resource_evidence_sha256"] = resource_evidence_sha256(evidence)

    result = _summarize(report)

    assert result["diagnostics"]["resource_policy_errors"] == []
    assert result["diagnostics"]["resource_evidence_failures"] == []
    assert result["diagnostics"]["resource_claim_readiness_errors"] == [
        "resource controller run is explicitly evidence-only",
        "resource controller claim_grade_ready is not true",
        "resource controller equal_wall_time_claim is not true",
        "resource controller equal_memory_limit_claim is not true",
    ]
    assert result["claim_gate"]["passed"] is False


@pytest.mark.parametrize("version", [1, 2])
def test_official_evidence_pre_v3_downgrade_fails_closed(version: int) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    evidence["evidence_version"] = version
    _rebind_evidence(evidence)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert "official validator evidence version is not 3" in reasons


@pytest.mark.parametrize("field", _V3_BINDING_FIELDS)
def test_every_browser_v3_binding_field_is_covered(field: str) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    value = evidence[field]
    evidence[field] = value + 1 if type(value) is int else f"{value}-tampered"

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert "official evidence binding hash mismatch" in reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "submission_intent_created_at",
            "2026-08-25T23:59:58.000Z",
            "official evidence submission intent binding hash mismatch",
        ),
        (
            "response_content_type",
            "text/plain",
            "official evidence response capture binding hash mismatch",
        ),
    ],
)
def test_v3_nested_binding_layers_are_independently_validated(
    field: str, value: Any, reason: str
) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    evidence[field] = value
    _rebind_evidence(evidence)

    result = _summarize(report)

    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert reason in reasons


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda evidence: evidence.update(external_source_authenticity="unproven"),
            "official evidence external authenticity state is invalid",
        ),
        (
            lambda evidence: evidence.update(response_status=201),
            "official evidence HTTP response status is not 200",
        ),
        (
            lambda evidence: evidence.update(response_content_type=""),
            "official evidence response Content-Type is missing",
        ),
        (
            lambda evidence: evidence.update(request_method="GET"),
            "official evidence request method is not POST",
        ),
        (
            lambda evidence: evidence.update(attempt_id="not-a-uuid"),
            "official evidence submission attempt ID is not a lowercase UUIDv4",
        ),
        (
            lambda evidence: evidence.update(effective_seed=999),
            "official evidence run binding mismatch: effective_seed",
        ),
    ],
)
def test_v3_semantics_fail_after_all_hash_layers_are_recomputed(
    mutate: Callable[[dict[str, Any]], None], reason: str
) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    mutate(evidence)
    _rebind_all_official_evidence(evidence)

    result = _summarize(report)

    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert reason in reasons


@pytest.mark.parametrize(
    "response_url",
    [
        "https://itc2019.org:443/server/validator/log-case-a__planora__seed-17__rep-01",
        "https://itc2019.org/server/validator/log-case-a__planora__seed-17__rep-01?x=1",
    ],
)
def test_v3_noncanonical_validator_urls_fail_closed(response_url: str) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    evidence["request_url"] = response_url
    evidence["response_url"] = response_url
    _rebind_all_official_evidence(evidence)

    result = _summarize(report)

    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert "official evidence URL is outside the validator endpoint" in reasons
    assert "official evidence request URL is outside the validator endpoint" in reasons


@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (
            lambda report: report["records"].__setitem__(
                1, deepcopy(report["records"][0])
            ),
            "duplicate_run_ids",
        ),
        (
            lambda report: report["records"][1].update(
                {
                    field: report["records"][0][field]
                    for field in (
                        "case",
                        "solver",
                        "seed",
                        "effective_seed",
                        "seed_control",
                        "seed_pairing_group",
                        "repetition",
                        "unseeded_trial",
                    )
                }
            ),
            "duplicate_semantic_cells",
        ),
        (lambda report: report["records"].pop(), "missing_cells"),
        (
            lambda report: report["records"].append(
                {
                    **_record(seed=17, repetition=2),
                    "run_id": "case-a__planora__seed-17__rep-99",
                    "repetition": 99,
                    "output_path": "/matrix/runs/unexpected/solution.xml",
                }
            ),
            "unexpected_cells",
        ),
        (
            lambda report: report["records"][1].update(
                output_path=report["records"][0]["output_path"]
            ),
            "duplicate_output_paths",
        ),
    ],
)
def test_structural_matrix_anomalies_fail_closed(
    mutate: Callable[[dict[str, Any]], None], diagnostic: str
) -> None:
    report = _report()
    mutate(report)

    result = _summarize(report)

    assert result["matrix_complete"] is False
    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"][diagnostic]
    assert result["comparisons"][0]["outcome"] is None
    assert result["comparisons"][0]["comparison_eligible"] is False


def test_manifest_expected_runs_cannot_shrink_the_configured_matrix() -> None:
    report = _report()
    report["manifest"]["expected_runs"].pop()

    result = _summarize(report)

    assert result["planned_runs"] == 6
    assert result["matrix_complete"] is False
    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["manifest_errors"] == [
        "manifest.expected_runs does not match cases, solvers, seeds, and repetitions"
    ]


@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (
            lambda record: record.update(independent_validation=None),
            "incomplete_local_validation",
        ),
        (
            lambda record: record["independent_validation"].update(objective={}),
            "incomplete_local_validation",
        ),
        (
            lambda record: record.update(
                official_validator_status="disagreement",
                official_validator_agreement=False,
            ),
            "official_validation_failures",
        ),
        (
            lambda record: record.update(
                official_validator_status="pending_upload",
                official_validator_agreement=None,
            ),
            "official_validation_failures",
        ),
    ],
)
def test_validation_gaps_suppress_claim_outcomes_but_keep_diagnostics(
    mutate: Callable[[dict[str, Any]], None], diagnostic: str
) -> None:
    report = _report()
    mutate(report["records"][0])

    result = _summarize(report)

    assert result["matrix_complete"] is True
    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"][diagnostic]
    assert result["comparisons"][0]["outcome"] is None
    assert result["comparisons"][0]["comparison_eligible"] is False
    assert result["comparisons"][0]["descriptive_outcome"] == "better"


@pytest.mark.parametrize("forged_hash", ["not-a-sha", "A" * 64])
def test_forged_or_noncanonical_sha256_values_fail_closed(forged_hash: str) -> None:
    report = _report()
    record = report["records"][0]
    record["output_sha256"] = forged_hash
    record["official_validated_output_sha256"] = forged_hash
    record["official_validation"]["submitted_output_sha256"] = forged_hash

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["sha256_validation_failures"]
    assert result["diagnostics"]["incomplete_local_validation"]
    assert result["comparisons"][0]["descriptive_outcome"] == "better"


def test_forged_raw_official_evidence_fails_closed() -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    forged_raw = _official_response(total=81, log_id=evidence["log_id"])
    evidence["response_body_base64"] = base64.b64encode(forged_raw).decode("ascii")
    evidence["response_sha256"] = hashlib.sha256(forged_raw).hexdigest()
    evidence["total"] = 81
    evidence["time"] = 81
    _rebind_evidence(evidence)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert "official response components disagree with local validation" in reasons


@pytest.mark.parametrize(
    ("container", "member", "field"),
    [
        ("assignedVariables", "value", "assigned"),
        ("assignedVariables", "total", "variables"),
        ("totalCost", "value", "total"),
        ("timePenalty", "value", "time"),
        ("roomPenalty", "value", "room"),
        ("distributionPenalty", "value", "distribution"),
        ("studentConflicts", "value", "student"),
    ],
)
def test_official_response_rejects_numbers_outside_js_safe_integer_range(
    container: str, member: str, field: str
) -> None:
    response = json.loads(_official_response(total=80, log_id="log-safe-range"))
    response["obj"][container][member] = 1 << 53

    with pytest.raises(
        ValueError, match=rf"official response has an invalid {field} value"
    ):
        _official_result(_canonical_bytes(response))


@pytest.mark.parametrize(
    ("container", "member", "field"),
    [
        ("assignedVariables", "value", "assigned"),
        ("assignedVariables", "total", "variables"),
        ("totalCost", "value", "total"),
        ("timePenalty", "value", "time"),
        ("roomPenalty", "value", "room"),
        ("distributionPenalty", "value", "distribution"),
        ("studentConflicts", "value", "student"),
    ],
)
def test_official_response_accepts_integral_json_float_lexemes(
    container: str, member: str, field: str
) -> None:
    response = json.loads(_official_response(total=80, log_id="log-safe-range"))
    response["obj"][container][member] = 1.0

    parsed = _official_result(_canonical_bytes(response))

    assert parsed[field] == 1
    assert type(parsed[field]) is int


@pytest.mark.parametrize("status", [200, ["200"], {"value": "200"}, "", None])
def test_official_response_requires_exact_string_200_status(status: Any) -> None:
    response = json.loads(_official_response(total=80, log_id="log-status"))
    response["status"] = status

    with pytest.raises(ValueError, match="official response status is not 200"):
        _official_result(_canonical_bytes(response))


def test_official_response_rejects_missing_status() -> None:
    response = json.loads(_official_response(total=80, log_id="log-status"))
    del response["status"]

    with pytest.raises(ValueError, match="official response status is not 200"):
        _official_result(_canonical_bytes(response))


@pytest.mark.parametrize(
    "field",
    [
        "seed",
        "effective_seed",
        "seed_pairing_group",
        "repetition",
        "response_status",
        "assigned",
        "variables",
        "total",
        "time",
        "room",
        "distribution",
        "student",
    ],
)
def test_persisted_integral_float_forms_match_javascript_bindings(field: str) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    evidence[field] = float(evidence[field])

    result = _summarize(report)

    assert result["diagnostics"]["official_validation_failures"] == []
    assert result["claim_gate"]["passed"] is True


def test_js_unsafe_official_total_cannot_pass_claim_gate() -> None:
    report = _report()
    record = report["records"][0]
    evidence = record["official_validation"]
    unsafe_total = 1 << 53
    raw_response = _official_response(total=unsafe_total, log_id=evidence["log_id"])
    record["independent_validation"]["objective"].update(
        total=unsafe_total, time=unsafe_total
    )
    evidence.update(
        total=unsafe_total,
        time=unsafe_total,
        response_body_base64=base64.b64encode(raw_response).decode("ascii"),
        response_sha256=hashlib.sha256(raw_response).hexdigest(),
    )
    _rebind_all_official_evidence(evidence)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert "official response has an invalid total value" in reasons


@pytest.mark.parametrize(
    ("field", "forged_value", "reason"),
    [
        (
            "helper_sha256",
            hashlib.sha256(b"forged-helper").hexdigest(),
            "official evidence helper hash does not match the manifest",
        ),
        (
            "submitted_output_sha256",
            hashlib.sha256(b"forged-output").hexdigest(),
            "official evidence submitted hash does not match the output",
        ),
        (
            "captured_at",
            "2026-08-26T00:00:00Z",
            "official evidence timestamp is not canonical ISO-8601",
        ),
        (
            "response_url",
            "https://evil.example/server/validator/result",
            "official evidence URL is outside the validator endpoint",
        ),
        ("log_id", "forged-log", "official parsed response mismatch: log_id"),
    ],
)
def test_bound_official_metadata_cannot_be_replaced(
    field: str, forged_value: str, reason: str
) -> None:
    report = _report()
    evidence = report["records"][0]["official_validation"]
    evidence[field] = forged_value
    _rebind_evidence(evidence)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["official_validation_failures"][0]["reasons"]
    assert reason in reasons


def test_duplicate_official_score_rows_are_rejected_without_losing_diagnostics() -> (
    None
):
    payload = _official_payload()
    payload["tables"][0].append(["2", "case-a", "90"])

    result = _summarize(_report(), payload)

    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["official_results_errors"] == [
        "official results contain duplicate instance rows: case-a",
        "official results contain conflicting instance scores: case-a",
    ]
    assert result["comparisons"][0]["descriptive_outcome"] == "better"
    assert result["comparisons"][0]["outcome"] is None


@pytest.mark.parametrize("second_total", [100, 90])
def test_duplicate_or_conflicting_official_rows_across_tables_fail_closed(
    second_total: int,
) -> None:
    payload = _official_payload()
    payload["tables"].append(
        [
            ["Rank", "Instance", "Total cost"],
            ["1", "case-a", str(second_total)],
        ]
    )

    result = _summarize(_report(), payload)

    assert result["claim_gate"]["passed"] is False
    assert "official_results_errors" in result["claim_gate"]["blockers"]
    assert result["diagnostics"]["official_results_errors"]
    if second_total == 90:
        assert any(
            "conflicting" in error
            for error in result["diagnostics"]["official_results_errors"]
        )


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("seeds", [17.0, 23, 31], "manifest.seeds must contain actual integers"),
        ("seeds", ["17", 23, 31], "manifest.seeds must contain actual integers"),
        ("seeds", [True, 23, 31], "manifest.seeds must contain actual integers"),
        (
            "repetitions",
            2.0,
            "manifest.repetitions must be a positive actual integer",
        ),
        (
            "repetitions",
            "2",
            "manifest.repetitions must be a positive actual integer",
        ),
        (
            "repetitions",
            True,
            "manifest.repetitions must be a positive actual integer",
        ),
    ],
)
def test_manifest_dimensions_reject_coercible_non_integer_values(
    field: str, value: Any, expected_error: str
) -> None:
    report = _report()
    report["manifest"][field] = value

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    assert expected_error in result["diagnostics"]["manifest_errors"]


def test_missing_or_mismatched_expected_official_payload_hash_fails_closed() -> None:
    missing = _summarize(_report(), expected_sha256=None)
    mismatched = _summarize(_report(), expected_sha256="f" * 64)

    assert missing["claim_gate"]["passed"] is False
    assert missing["diagnostics"]["official_payload_hash_errors"] == [
        "expected official payload SHA-256 was not supplied"
    ]
    assert mismatched["claim_gate"]["passed"] is False
    assert mismatched["diagnostics"]["official_payload_hash_errors"] == [
        "official payload SHA-256 does not match the expected digest"
    ]


def test_one_seed_one_repetition_is_descriptive_only() -> None:
    result = _summarize(_report(seeds=(17,), repetitions=1))

    assert result["matrix_complete"] is True
    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["replication_errors"] == [
        "claim-grade aggregation requires at least 3 seeds",
        "claim-grade aggregation requires at least 2 repetitions",
    ]
    comparison = result["comparisons"][0]
    assert comparison["local_best_total"] == 80
    assert comparison["descriptive_outcome"] == "better"
    assert comparison["outcome"] is None
    assert comparison["comparison_eligible"] is False


def test_best_of_selection_cannot_turn_mixed_80_200_cells_into_superiority() -> None:
    totals = {
        (seed, repetition): (80 if (seed, repetition) == (17, 1) else 200)
        for seed in SEEDS
        for repetition in (1, 2)
    }

    result = _summarize(_report(totals=totals), _official_payload(total=90))

    assert result["claim_gate"]["passed"] is True
    comparison = result["comparisons"][0]
    assert comparison["local_best_total"] == 80
    assert comparison["descriptive_outcome"] == "better"
    assert comparison["comparison_eligible"] is True
    assert comparison["outcome"] == "mixed"
    assert comparison["paired_statistics"]["better"] == 1
    assert comparison["paired_statistics"]["worse"] == 5
    assert comparison["paired_statistics"]["mean_total"] == 180.0


def test_infeasible_planora_cell_blocks_the_global_claim_gate() -> None:
    report = _report()
    _mark_infeasible(report["records"][0])

    result = _summarize(report)

    assert result["matrix_complete"] is True
    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["planora_feasibility_failures"] == [
        {
            "run_id": "case-a__planora__seed-17__rep-01",
            "reason": "independent validation reports infeasible",
        }
    ]
    assert result["diagnostics"]["official_validation_failures"] == []
    assert result["comparisons"][0]["outcome"] is None
    assert result["comparisons"][0]["comparison_eligible"] is False


def test_complete_infeasible_comparator_is_descriptive_feasibility_evidence() -> None:
    report = _report()
    _add_infeasible_comparator(report, "cpsolver")

    result = _summarize(report)

    assert result["matrix_complete"] is True
    assert result["claim_gate"]["passed"] is False
    comparator = next(row for row in result["solvers"] if row["solver"] == "cpsolver")
    assert comparator["descriptive_feasibility_evidence"] == {
        "expected_cells": 6,
        "locally_valid_cells": 6,
        "feasible_cells": 0,
        "infeasible_cells": 6,
        "unresolved_cells": 0,
        "complete": True,
    }


def test_summary_reports_verified_controller_raw_run_anchor_scope() -> None:
    result = _summarize(_report())

    assert result["official_results_source"]["external_authenticity_unproven"] is False
    assert result["official_results_source"]["integrity_scope"] == (
        "Claim eligibility requires a separately pinned canonical anchor bound to the "
        "exact official payload and the immutable controller/raw-run evidence set. The "
        "anchor does not by itself prove benchmark quality or performance superiority."
    )
    assert result["diagnostics"]["official_trust_anchor_errors"] == []
    assert result["official_results_source"]["actual_matrix_evidence_sha256"]


def test_forged_official_payload_cannot_reuse_an_independently_pinned_anchor() -> None:
    report = _report()
    original = _official_payload()
    anchor = _trust_anchor(report, original)
    anchor_bytes = _canonical_bytes(anchor)
    forged = _official_payload(total=999_999)

    result = _summarize(
        report,
        forged,
        trust_anchor=anchor,
        trust_anchor_bytes=anchor_bytes,
        expected_anchor_sha256=hashlib.sha256(anchor_bytes).hexdigest(),
    )

    assert result["official_results_source"]["external_authenticity_unproven"] is True
    assert result["claim_gate"]["passed"] is False
    assert "official_trust_anchor_errors" in result["claim_gate"]["blockers"]
    assert "external_authenticity_unproven" in result["claim_gate"]["blockers"]
    assert (
        "official payload does not match the pinned trust anchor"
        in result["diagnostics"]["official_trust_anchor_errors"]
    )


def test_replayed_official_log_and_response_across_runs_fail_closed() -> None:
    report = _report()
    original = deepcopy(report["records"][0]["official_validation"])
    for record in report["records"][1:]:
        replay = deepcopy(original)
        replay["submitted_output_sha256"] = record["output_sha256"]
        _rebind_evidence(replay)
        record["official_validation"] = replay

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reused = result["diagnostics"]["reused_official_evidence"]
    assert {next(iter(item)) for item in reused} == {
        "attempt_id",
        "log_id",
        "request_body_sha256",
        "response_capture_binding_sha256",
        "response_sha256",
        "submission_intent_binding_sha256",
    }
    assert all(len(item["run_ids"]) == 6 for item in reused)


def test_reused_attempt_id_fails_closed_after_all_bindings_are_recomputed() -> None:
    report = _report()
    reused_attempt_id = report["records"][0]["official_validation"]["attempt_id"]
    for record in report["records"][1:]:
        evidence = record["official_validation"]
        evidence["attempt_id"] = reused_attempt_id
        _rebind_all_official_evidence(evidence)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["official_validation_failures"] == []
    assert result["diagnostics"]["reused_official_evidence"] == [
        {
            "attempt_id": reused_attempt_id,
            "run_ids": sorted(record["run_id"] for record in report["records"]),
        }
    ]


def test_nonexistent_solution_artifacts_cannot_pass_offline_gate() -> None:
    report = _report()
    for record in report["records"]:
        record["output_path"] = f"missing/{record['run_id']}/solution.xml"
        record["output_relative_path"] = record["output_path"]
        record["artifact_binding_sha256"] = _artifact_binding(record)

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    failures = result["diagnostics"]["artifact_validation_failures"]
    assert len(failures) == 6
    assert all(
        "solution artifact does not exist or cannot be resolved" in item["reasons"]
        for item in failures
    )


def test_solution_artifact_path_cannot_escape_declared_matrix_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.xml"
    outside.write_bytes(b"outside")
    report = _report()
    record = report["records"][0]
    record["output_path"] = str(outside)
    record["output_relative_path"] = "outside.xml"
    record["output_sha256"] = hashlib.sha256(b"outside").hexdigest()
    record["artifact_binding_sha256"] = _artifact_binding(record)

    result = _summarize(report)

    reasons = result["diagnostics"]["artifact_validation_failures"][0]["reasons"]
    assert "solution artifact escapes the declared matrix root" in reasons


def test_solution_artifact_content_hash_mismatch_fails_closed() -> None:
    report = _report()
    record = report["records"][0]
    artifact = _MATRIX_TEMP / record["output_path"]
    artifact.write_bytes(b"tampered-after-report")

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    reasons = result["diagnostics"]["artifact_validation_failures"][0]["reasons"]
    assert "solution artifact hash does not match the recorded output hash" in reasons
    assert "solution artifact identity binding hash mismatch" in reasons


def test_absent_controller_profile_and_per_run_resource_evidence_fail_closed() -> None:
    report = _report()
    report["manifest"].pop("resource_controller")
    for record in report["records"]:
        record.pop("resource_evidence")
        record.pop("resource_evidence_sha256")

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["resource_policy_errors"] == [
        "resource controller profile is missing"
    ]
    assert len(result["diagnostics"]["resource_evidence_failures"]) == 6
    assert all(
        item["reasons"] == ["per-run resource evidence is missing"]
        for item in result["diagnostics"]["resource_evidence_failures"]
    )


def test_replayed_resource_invocation_fails_closed_after_rebinding() -> None:
    report = _report()
    original = deepcopy(report["records"][0]["resource_evidence"])
    for record in report["records"][1:]:
        replay = deepcopy(original)
        replay["run_id"] = record["run_id"]
        replay["artifact_sha256"] = record["output_sha256"]
        record["resource_evidence"] = replay
        record["resource_evidence_sha256"] = hashlib.sha256(
            _canonical_bytes(replay)
        ).hexdigest()

    result = _summarize(report)

    assert result["claim_gate"]["passed"] is False
    assert result["diagnostics"]["resource_evidence_failures"] == []
    assert result["diagnostics"]["reused_resource_invocations"] == [
        {
            "invocation_sha256": original["invocation_sha256"],
            "run_ids": [record["run_id"] for record in report["records"]],
        }
    ]


def test_missing_anchor_never_emits_claim_eligibility() -> None:
    result = _summarize(_report(), include_local_trust_anchor=False)

    assert result["claim_gate"]["passed"] is False
    assert result["summary_mode"]["claim_eligibility_status"] == "ineligible"
    assert result["comparisons"][0]["comparison_eligible"] is False
    assert result["comparisons"][0]["outcome"] is None
    errors = result["diagnostics"]["official_trust_anchor_errors"]
    assert "official trust anchor is missing or malformed" in errors
    assert (
        "expected official trust-anchor digest is missing, malformed, or placeholder"
        in errors
    )


@pytest.mark.parametrize("placeholder", ["0" * 64, "f" * 64, "A" * 64, "todo"])
def test_placeholder_or_malformed_anchor_pin_fails_closed(placeholder: str) -> None:
    result = _summarize(_report(), expected_anchor_sha256=placeholder)

    assert result["claim_gate"]["passed"] is False
    assert result["comparisons"][0]["comparison_eligible"] is False
    assert (
        "expected official trust-anchor digest is missing, malformed, or placeholder"
        in result["diagnostics"]["official_trust_anchor_errors"]
    )


def test_malformed_and_noncanonical_anchor_bytes_fail_closed() -> None:
    report = _report()
    payload = _official_payload()
    malformed = b'{"schema":'
    malformed_result = _summarize(
        report,
        payload,
        trust_anchor=None,
        trust_anchor_bytes=malformed,
        expected_anchor_sha256=hashlib.sha256(malformed).hexdigest(),
    )
    anchor = _trust_anchor(report, payload)
    noncanonical = json.dumps(anchor, indent=2).encode()
    noncanonical_result = _summarize(
        report,
        payload,
        trust_anchor=anchor,
        trust_anchor_bytes=noncanonical,
        expected_anchor_sha256=hashlib.sha256(noncanonical).hexdigest(),
    )
    array_bytes = b"[]"
    array_result = _summarize(
        report,
        payload,
        trust_anchor=[],
        trust_anchor_bytes=array_bytes,
        expected_anchor_sha256=hashlib.sha256(array_bytes).hexdigest(),
    )

    assert malformed_result["claim_gate"]["passed"] is False
    assert (
        "official trust-anchor bytes are not valid UTF-8 JSON"
        in malformed_result["diagnostics"]["official_trust_anchor_errors"]
    )
    assert noncanonical_result["claim_gate"]["passed"] is False
    assert (
        "official trust-anchor bytes are not canonical JSON"
        in noncanonical_result["diagnostics"]["official_trust_anchor_errors"]
    )
    assert array_result["claim_gate"]["passed"] is False
    assert array_result["official_results_source"]["trust_anchor_mode"] is None
    assert (
        "official trust anchor is missing or malformed"
        in array_result["diagnostics"]["official_trust_anchor_errors"]
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        (
            "schema",
            "planora.itc2019.official-results-trust-anchor.v1",
            "unsupported schema",
        ),
        (
            "mode",
            "external-detached-sha256",
            "not bound to controller raw-run evidence",
        ),
        ("authority", "placeholder", "authority is not ITC 2019"),
        ("matrix_evidence_sha256", "0" * 64, "malformed or placeholder"),
    ],
)
def test_repinning_malformed_anchor_content_cannot_promote_claims(
    field: str, value: str, expected_error: str
) -> None:
    report = _report()
    payload = _official_payload()
    anchor = _trust_anchor(report, payload)
    anchor[field] = value
    anchor_bytes = _canonical_bytes(anchor)

    result = _summarize(
        report,
        payload,
        trust_anchor=anchor,
        trust_anchor_bytes=anchor_bytes,
        expected_anchor_sha256=hashlib.sha256(anchor_bytes).hexdigest(),
    )

    assert result["claim_gate"]["passed"] is False
    assert result["comparisons"][0]["outcome"] is None
    assert any(
        expected_error in error
        for error in result["diagnostics"]["official_trust_anchor_errors"]
    )


def test_extra_claim_toggle_field_is_not_part_of_the_anchor_contract() -> None:
    report = _report()
    payload = _official_payload()
    anchor = _trust_anchor(report, payload)
    anchor["claim_eligible"] = True
    anchor_bytes = _canonical_bytes(anchor)

    result = _summarize(
        report,
        payload,
        trust_anchor=anchor,
        trust_anchor_bytes=anchor_bytes,
        expected_anchor_sha256=hashlib.sha256(anchor_bytes).hexdigest(),
    )

    assert result["claim_gate"]["passed"] is False
    assert (
        "official trust anchor fields do not match the v2 contract"
        in result["diagnostics"]["official_trust_anchor_errors"]
    )
    assert result["comparisons"][0]["comparison_eligible"] is False


def test_stale_anchor_from_prior_matrix_creation_fails_closed() -> None:
    report = _report()
    payload = _official_payload()
    anchor = _trust_anchor(report, payload)
    anchor_bytes = _canonical_bytes(anchor)
    report["manifest"]["created_utc"] = "2026-08-27T00:01:00.000Z"

    result = _summarize(
        report,
        payload,
        trust_anchor=anchor,
        trust_anchor_bytes=anchor_bytes,
        expected_anchor_sha256=hashlib.sha256(anchor_bytes).hexdigest(),
    )

    assert result["claim_gate"]["passed"] is False
    errors = result["diagnostics"]["official_trust_anchor_errors"]
    assert "official trust anchor is stale for this matrix creation" in errors
    assert "official trust anchor is stale or mismatched for matrix evidence" in errors


def test_raw_evidence_file_tampering_blocks_even_with_unchanged_pinned_anchor() -> None:
    report = _report()
    payload = _official_payload()
    anchor = _trust_anchor(report, payload)
    anchor_bytes = _canonical_bytes(anchor)
    raw_path = Path(report["records"][0]["raw_resource_evidence_path"])
    raw_path.write_bytes(b'{"tampered":true}')

    result = _summarize(
        report,
        payload,
        trust_anchor=anchor,
        trust_anchor_bytes=anchor_bytes,
        expected_anchor_sha256=hashlib.sha256(anchor_bytes).hexdigest(),
    )

    assert result["claim_gate"]["passed"] is False
    assert any(
        "raw resource evidence file digest mismatch" in error
        for error in result["diagnostics"]["official_trust_anchor_errors"]
    )
    assert result["comparisons"][0]["outcome"] is None


def test_obsolete_environment_style_anchor_source_is_rejected() -> None:
    result = _summarize(
        _report(),
        trust_anchor_source=(
            "environment:PLANORA_ITC2019_OFFICIAL_TRUST_ANCHOR_SHA256"
        ),
    )

    assert result["claim_gate"]["passed"] is False
    assert (
        "official trust anchor was not pinned by the claim CLI"
        in result["diagnostics"]["official_trust_anchor_errors"]
    )


def test_descriptive_execution_cannot_be_promoted_by_toggling_mode_field() -> None:
    result = _summarize(_report(), claim_eligibility_requested=False)

    assert result["summary_mode"]["mode"] == "descriptive_only"
    assert result["summary_mode"]["claim_eligibility_status"] == (
        "not_evaluated_descriptive_only"
    )
    assert result["claim_gate"]["passed"] is False
    assert "summary_mode_errors" in result["claim_gate"]["blockers"]
    assert result["comparisons"][0]["outcome"] is None
    assert result["comparisons"][0]["comparison_eligible"] is False

    relabeled = deepcopy(result)
    relabeled["summary_mode"]["mode"] = "claim_gate_required"
    assert relabeled["claim_gate"]["passed"] is False
    assert relabeled["summary_mode"]["claim_eligibility_status"] == (
        "not_evaluated_descriptive_only"
    )
    assert relabeled["comparisons"][0]["outcome"] is None
    assert (
        relabeled["summary_mode"]["eligibility_binding_sha256"]
        == result["summary_mode"]["eligibility_binding_sha256"]
    )


def test_cli_fails_closed_unless_explicitly_descriptive_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report()
    _mark_infeasible(report["records"][0])
    payload = _official_payload()
    payload_bytes = _canonical_bytes(payload)
    report_path = tmp_path / "report.json"
    official_path = tmp_path / "official.json"
    default_out = tmp_path / "default-summary.json"
    descriptive_out = tmp_path / "descriptive-summary.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    official_path.write_bytes(payload_bytes)
    digest = hashlib.sha256(payload_bytes).hexdigest()

    base_args = [
        "summarize_itc2019_competitor_matrix.py",
        "--report",
        str(report_path),
        "--official-results",
        str(official_path),
        "--matrix-root",
        str(_MATRIX_TEMP),
        "--expected-official-payload-sha256",
        digest,
    ]
    monkeypatch.setattr(sys, "argv", [*base_args, "--out", str(default_out)])
    assert main() != 0
    default_summary = json.loads(default_out.read_text(encoding="utf-8"))
    assert default_summary["claim_gate"]["passed"] is False
    assert default_summary["summary_mode"]["mode"] == "claim_gate_required"
    assert default_summary["summary_mode"]["claim_gate_enforced"] is True
    assert default_summary["summary_mode"]["claim_eligibility_status"] == ("ineligible")

    monkeypatch.setattr(
        sys,
        "argv",
        [*base_args, "--out", str(descriptive_out), "--descriptive-only"],
    )
    assert main() == 0
    descriptive_summary = json.loads(descriptive_out.read_text(encoding="utf-8"))
    assert descriptive_summary["claim_gate"]["passed"] is False
    assert descriptive_summary["diagnostics"]["planora_feasibility_failures"]
    assert descriptive_summary["summary_mode"]["mode"] == "descriptive_only"
    assert descriptive_summary["summary_mode"]["claim_gate_enforced"] is False
    assert descriptive_summary["summary_mode"]["claim_eligibility_status"] == (
        "not_evaluated_descriptive_only"
    )


def test_cli_accepts_only_explicit_pinned_anchor_for_claim_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report()
    payload = _official_payload()
    payload_bytes = _canonical_bytes(payload)
    anchor = _trust_anchor(report, payload)
    anchor_bytes = _canonical_bytes(anchor)
    report_path = tmp_path / "report.json"
    official_path = tmp_path / "official.json"
    anchor_path = tmp_path / "anchor.json"
    claim_out = tmp_path / "claim-summary.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    official_path.write_bytes(payload_bytes)
    anchor_path.write_bytes(anchor_bytes)
    args = [
        "summarize_itc2019_competitor_matrix.py",
        "--report",
        str(report_path),
        "--official-results",
        str(official_path),
        "--matrix-root",
        str(_MATRIX_TEMP),
        "--expected-official-payload-sha256",
        hashlib.sha256(payload_bytes).hexdigest(),
        "--official-trust-anchor",
        str(anchor_path),
        "--expected-official-trust-anchor-sha256",
        hashlib.sha256(anchor_bytes).hexdigest(),
        "--out",
        str(claim_out),
    ]
    monkeypatch.setattr(sys, "argv", args)

    assert main() == 0
    result = json.loads(claim_out.read_text(encoding="utf-8"))
    assert result["claim_gate"] == {"passed": True, "blockers": []}
    assert result["summary_mode"]["claim_eligibility_status"] == "eligible"
    assert result["comparisons"][0]["comparison_eligible"] is True

    monkeypatch.setenv(
        "PLANORA_ITC2019_OFFICIAL_TRUST_ANCHOR_SHA256",
        hashlib.sha256(anchor_bytes).hexdigest(),
    )
    without_pin_out = tmp_path / "without-pin-summary.json"
    without_pin_args = [
        value for index, value in enumerate(args) if index not in {11, 12}
    ]
    without_pin_args[-1] = str(without_pin_out)
    monkeypatch.setattr(sys, "argv", without_pin_args)
    assert main() == 2
    without_pin = json.loads(without_pin_out.read_text(encoding="utf-8"))
    assert without_pin["claim_gate"]["passed"] is False
    assert "official_trust_anchor_errors" in without_pin["claim_gate"]["blockers"]
