from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.itc2019_resource_controller import (
    DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    RESOURCE_EVIDENCE_SCHEMA,
    ResourceControllerError,
    resource_evidence_sha256,
)


_SEMANTIC_CELL_FIELDS = (
    "case",
    "solver",
    "seed",
    "effective_seed",
    "seed_control",
    "seed_pairing_group",
    "repetition",
    "unseeded_trial",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JS_SAFE_INTEGER_MAX = (1 << 53) - 1
_OFFICIAL_COMPONENT_FIELDS = (
    "time",
    "room",
    "distribution",
    "student",
)
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
_OFFICIAL_EVIDENCE_FIELDS = {
    "instance",
    "result",
    "assigned",
    "variables",
    "total",
    *_OFFICIAL_COMPONENT_FIELDS,
    "log_id",
    *_OFFICIAL_RUN_IDENTITY_FIELDS,
    "input_sha256",
    "request_method",
    "request_url",
    "request_content_type",
    "request_body_sha256",
    "uploaded_file_sha256",
    "attempt_id",
    "submission_intent_created_at",
    "submission_intent_binding_sha256",
    "evidence_version",
    "correlation_method",
    "external_source_authenticity",
    "response_body_base64",
    "response_sha256",
    "response_capture_binding_sha256",
    "submitted_output_sha256",
    "helper_sha256",
    "captured_at",
    "response_url",
    "response_status",
    "response_content_type",
    "evidence_binding_sha256",
}
_OFFICIAL_EVIDENCE_BINDING_FIELDS = (
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
_OFFICIAL_UNIQUE_EVIDENCE_FIELDS = (
    "log_id",
    "attempt_id",
    "response_sha256",
    "request_body_sha256",
    "submission_intent_binding_sha256",
    "response_capture_binding_sha256",
    "evidence_binding_sha256",
)
_OFFICIAL_CORRELATION_METHOD = (
    "playwright_response_request_identity_and_multipart_bytes"
)

_OFFICIAL_TRUST_ANCHOR_SCHEMA = "planora.itc2019.official-results-trust-anchor.v2"
_OFFICIAL_TRUST_ANCHOR_MODE = "pinned-controller-raw-run-evidence"
_OFFICIAL_TRUST_ANCHOR_SOURCE = "command-line:--expected-official-trust-anchor-sha256"
_CONTROLLER_EVIDENCE_BINDING_SCHEMA = (
    "planora.itc2019.controller-raw-run-evidence-binding.v1"
)
_RAW_RESOURCE_EVIDENCE_SCHEMA = "planora.itc2019.raw-resource-evidence.v1"
_OFFICIAL_TRUST_ANCHOR_FIELDS = {
    "schema",
    "mode",
    "authority",
    "source_url",
    "captured_at",
    "official_payload_sha256",
    "matrix_created_utc",
    "matrix_evidence_sha256",
}
_ARTIFACT_BINDING_FIELDS = ("run_id", *_SEMANTIC_CELL_FIELDS)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_concrete_sha256(value: Any) -> bool:
    return _is_sha256(value) and len(set(value)) > 1


def _is_js_safe_integer(value: Any) -> bool:
    if type(value) is int:
        return abs(value) <= _JS_SAFE_INTEGER_MAX
    return (
        type(value) is float
        and math.isfinite(value)
        and value.is_integer()
        and abs(value) <= _JS_SAFE_INTEGER_MAX
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _official_binding_json_bytes(value: Any) -> bytes:
    def normalize_js_numbers(item: Any) -> Any:
        if type(item) is float and _is_js_safe_integer(item):
            return int(item)
        if isinstance(item, list):
            return [normalize_js_numbers(element) for element in item]
        if isinstance(item, dict):
            return {key: normalize_js_numbers(element) for key, element in item.items()}
        return item

    return _canonical_json_bytes(normalize_js_numbers(value))


def _sha256_field_errors(
    value: Any, *, path: str, values_are_hashes: bool = False
) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if (
                values_are_hashes or str(key).lower().endswith("sha256")
            ) and child is not None:
                if not _is_sha256(child):
                    errors.append(f"{child_path} is not a canonical SHA-256 digest")
            errors.extend(
                _sha256_field_errors(
                    child,
                    path=child_path,
                    values_are_hashes=str(key) in {"inputs", "source_files"},
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_sha256_field_errors(child, path=f"{path}[{index}]"))
    return errors


def _official_scores(payload: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    scores: dict[str, int] = {}
    duplicate_instances: set[str] = set()
    conflicting_instances: set[str] = set()
    for table in payload.get("tables", []):
        rows = list(table or [])
        if not rows or "Total cost" not in rows[0]:
            continue
        for row in rows[1:]:
            cells = [str(value).strip() for value in row]
            if len(cells) >= 3 and cells[1] and cells[2].isdigit():
                instance = cells[1]
                score = int(cells[2])
                if instance in scores:
                    duplicate_instances.add(instance)
                    if scores[instance] != score:
                        conflicting_instances.add(instance)
                    continue
                scores[instance] = score
    if duplicate_instances:
        errors.append(
            "official results contain duplicate instance rows: "
            + ", ".join(sorted(duplicate_instances))
        )
    if conflicting_instances:
        errors.append(
            "official results contain conflicting instance scores: "
            + ", ".join(sorted(conflicting_instances))
        )
    if scores:
        return scores, errors
    return {}, ["official results payload contains no competition score table"]


def _semantic_cell(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in _SEMANTIC_CELL_FIELDS}


def _cell_token(row: dict[str, Any]) -> str:
    return json.dumps(
        [row.get(field) for field in _SEMANTIC_CELL_FIELDS],
        sort_keys=False,
        separators=(",", ":"),
    )


def _derived_expected_runs(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []

    def unique_strings(field: str) -> list[str]:
        raw = manifest.get(field)
        if not isinstance(raw, list) or not raw:
            errors.append(f"manifest.{field} must be a non-empty list")
            return []
        values = [str(value) for value in raw]
        if any(not value for value in values):
            errors.append(f"manifest.{field} contains an empty value")
        if len(values) != len(set(values)):
            errors.append(f"manifest.{field} contains duplicates")
        return values

    cases = unique_strings("cases")
    solvers = unique_strings("solvers")
    raw_seeds = manifest.get("seeds")
    seeds: list[int] = []
    if not isinstance(raw_seeds, list) or not raw_seeds:
        errors.append("manifest.seeds must be a non-empty list")
    elif any(type(value) is not int for value in raw_seeds):
        errors.append("manifest.seeds must contain actual integers")
    else:
        seeds = list(raw_seeds)
        if len(seeds) != len(set(seeds)):
            errors.append("manifest.seeds contains duplicates")
    raw_repetitions = manifest.get("repetitions")
    if type(raw_repetitions) is not int or raw_repetitions <= 0:
        repetitions = 0
        errors.append("manifest.repetitions must be a positive actual integer")
    else:
        repetitions = raw_repetitions

    expected: list[dict[str, Any]] = []
    if errors:
        return expected, errors
    for case in cases:
        for solver in solvers:
            for seed_index, seed in enumerate(seeds):
                for repetition in range(1, repetitions + 1):
                    if solver == "lemos-maxsat":
                        trial = seed_index * repetitions + repetition
                        expected.append(
                            {
                                "run_id": (
                                    f"{case}__{solver}__unseeded-trial-{trial:03d}"
                                ),
                                "case": case,
                                "solver": solver,
                                "seed": None,
                                "effective_seed": None,
                                "seed_control": "unsupported_upstream_clock_seed",
                                "seed_pairing_group": None,
                                "repetition": repetition,
                                "unseeded_trial": trial,
                            }
                        )
                    else:
                        expected.append(
                            {
                                "run_id": (
                                    f"{case}__{solver}__seed-{seed}__rep-{repetition:02d}"
                                ),
                                "case": case,
                                "solver": solver,
                                "seed": seed,
                                "effective_seed": seed,
                                "seed_control": "explicit",
                                "seed_pairing_group": seed,
                                "repetition": repetition,
                                "unseeded_trial": None,
                            }
                        )
    return expected, errors


def _manifest_expected_run_errors(
    manifest: dict[str, Any], expected: list[dict[str, Any]]
) -> list[str]:
    if "expected_runs" not in manifest:
        return []
    declared = manifest.get("expected_runs")
    if not isinstance(declared, list) or any(
        not isinstance(row, dict) for row in declared
    ):
        return ["manifest.expected_runs must be a list of run identity objects"]
    expected_ids = Counter(str(row["run_id"]) for row in expected)
    declared_ids = Counter(str(row.get("run_id", "")) for row in declared)
    expected_cells = Counter(_cell_token(row) for row in expected)
    declared_cells = Counter(_cell_token(row) for row in declared)
    if expected_ids != declared_ids or expected_cells != declared_cells:
        return [
            "manifest.expected_runs does not match cases, solvers, seeds, and repetitions"
        ]
    expected_by_id = {str(row["run_id"]): row for row in expected}
    for row in declared:
        run_id = str(row.get("run_id", ""))
        if _semantic_cell(row) != _semantic_cell(expected_by_id[run_id]):
            return [f"manifest.expected_runs identity mismatch: {run_id}"]
    return []


def _normal_output_path(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return os.path.normcase(os.path.normpath(str(value).strip()))


def _artifact_binding(
    row: dict[str, Any], *, relative_path: str, output_sha256: str
) -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "identity": {
                    field: row.get(field) for field in _ARTIFACT_BINDING_FIELDS
                },
                "output_relative_path": relative_path,
                "output_sha256": output_sha256,
            }
        )
    )


def _hash_confined_artifact(
    row: dict[str, Any], *, matrix_root: Path | None
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    run_id = str(row.get("run_id", ""))
    output_path = row.get("output_path")
    if matrix_root is None:
        return None, ["declared matrix root was not supplied"]
    try:
        resolved_root = matrix_root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, ["declared matrix root does not exist or cannot be resolved"]
    if not resolved_root.is_dir():
        return None, ["declared matrix root is not a directory"]
    if not isinstance(output_path, str) or not output_path.strip():
        return None, ["solution artifact path is missing"]

    candidate = Path(output_path)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    try:
        resolved_artifact = candidate.resolve(strict=True)
        relative = resolved_artifact.relative_to(resolved_root)
    except ValueError:
        return None, ["solution artifact escapes the declared matrix root"]
    except (OSError, RuntimeError):
        return None, ["solution artifact does not exist or cannot be resolved"]
    if not resolved_artifact.is_file():
        return None, ["solution artifact is not a regular file"]

    digest = hashlib.sha256()
    try:
        with resolved_artifact.open("rb") as handle:
            before = os.fstat(handle.fileno())
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
        final = resolved_artifact.stat()
    except OSError:
        return None, ["solution artifact could not be read atomically"]
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    identity_final = (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
    )
    if identity_before != identity_after or identity_after != identity_final:
        errors.append("solution artifact changed while it was being verified")

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != row.get("output_sha256"):
        errors.append("solution artifact hash does not match the recorded output hash")
    relative_path = relative.as_posix()
    if row.get("output_relative_path") != relative_path:
        errors.append("solution artifact relative path is not immutably recorded")
    expected_binding = _artifact_binding(
        row, relative_path=relative_path, output_sha256=actual_sha256
    )
    if row.get("artifact_binding_sha256") != expected_binding:
        errors.append("solution artifact identity binding hash mismatch")
    if not _is_sha256(row.get("artifact_binding_sha256")):
        errors.append("solution artifact binding is not a canonical SHA-256 digest")
    if not run_id:
        errors.append("solution artifact has no bound run identity")
    return actual_sha256, errors


def _local_validation_errors(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    output_path = row.get("output_path")
    output_sha256 = row.get("output_sha256")
    if bool(output_path) != bool(output_sha256):
        errors.append("output path and hash presence differ")
    if output_sha256 is not None and not _is_sha256(output_sha256):
        errors.append("output hash is not a canonical SHA-256 digest")

    validation = row.get("independent_validation")
    if validation is None:
        return [*errors, "independent validation result is missing"]
    if not isinstance(validation, dict):
        return [*errors, "independent validation is not an object"]
    if not isinstance(validation.get("validator"), str) or not validation.get(
        "validator"
    ):
        errors.append("independent validator identity is missing")
    feasible = validation.get("feasible")
    if type(feasible) is not bool:
        errors.append("independent feasible status is not Boolean")
    if not isinstance(validation.get("errors"), list):
        errors.append("independent validation errors are missing")
    objective = validation.get("objective")
    if feasible is True:
        if not output_path or not output_sha256:
            errors.append("feasible output path or hash is missing")
        if not isinstance(objective, dict):
            errors.append("feasible objective is missing")
        else:
            for field in ("total", *_OFFICIAL_COMPONENT_FIELDS):
                value = objective.get(field)
                if type(value) is not int or value < 0:
                    errors.append(
                        f"feasible objective {field} is not a non-negative integer"
                    )
    elif feasible is False and objective is not None:
        errors.append("infeasible validation unexpectedly has an objective")
    return errors


def _decode_official_response(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("official response bytes are missing")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("official response bytes are not valid Base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("official response bytes are not canonical Base64")
    return decoded


def _official_result(raw_response: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"official response contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        response = json.loads(
            raw_response.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("official response payload is not strict UTF-8 JSON") from exc
    if not isinstance(response, dict) or response.get("status") != "200":
        raise ValueError("official response status is not 200")
    obj = response.get("obj")
    if not isinstance(obj, dict):
        raise ValueError("official response result object is missing")

    def required_text(field: str, value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"official response has an invalid {field} value")
        return value

    def required_count(field: str, container: Any) -> int:
        if not isinstance(container, dict):
            raise ValueError(f"official response has an invalid {field} object")
        value = container.get("value")
        if not _is_js_safe_integer(value) or value < 0:
            raise ValueError(f"official response has an invalid {field} value")
        return int(value)

    assigned = obj.get("assignedVariables")
    if not isinstance(assigned, dict):
        raise ValueError("official response has an invalid assigned object")
    assigned_value = assigned.get("value")
    variables = assigned.get("total")
    if not _is_js_safe_integer(assigned_value) or assigned_value < 0:
        raise ValueError("official response has an invalid assigned value")
    if not _is_js_safe_integer(variables) or variables < 0:
        raise ValueError("official response has an invalid variables value")
    assigned_value = int(assigned_value)
    variables = int(variables)

    return {
        "instance": required_text("instance", obj.get("instance")),
        "result": required_text("result", obj.get("result")),
        "assigned": assigned_value,
        "variables": variables,
        "total": required_count("total", obj.get("totalCost")),
        "time": required_count("time", obj.get("timePenalty")),
        "room": required_count("room", obj.get("roomPenalty")),
        "distribution": required_count("distribution", obj.get("distributionPenalty")),
        "student": required_count("student", obj.get("studentConflicts")),
        "log_id": required_text("log identifier", obj.get("logId")),
    }


def _official_evidence_binding(evidence: dict[str, Any]) -> str:
    return _sha256(
        _official_binding_json_bytes(
            {field: evidence.get(field) for field in _OFFICIAL_EVIDENCE_BINDING_FIELDS}
        )
    )


def _official_submission_intent_binding(evidence: dict[str, Any]) -> str:
    intent = {
        "schema": _OFFICIAL_SUBMISSION_INTENT_SCHEMA,
        **{
            field: evidence.get(field)
            for field in (*_OFFICIAL_RUN_IDENTITY_FIELDS, "input_sha256")
        },
        "output_sha256": evidence.get("submitted_output_sha256"),
        "helper_sha256": evidence.get("helper_sha256"),
        "attempt_id": evidence.get("attempt_id"),
        "created_at": evidence.get("submission_intent_created_at"),
    }
    return _sha256(_official_binding_json_bytes(intent))


def _official_response_capture_binding(evidence: dict[str, Any]) -> str:
    capture = {
        "schema": _OFFICIAL_RESPONSE_CAPTURE_SCHEMA,
        **{
            field: evidence.get(field)
            for field in (*_OFFICIAL_RUN_IDENTITY_FIELDS, "input_sha256")
        },
        **{
            field: evidence.get(field)
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
    return _sha256(_official_binding_json_bytes(capture))


def _canonical_official_timestamp(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value) is None
    ):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _canonical_official_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname in {"itc2019.org", "www.itc2019.org"}
        and port is None
        and parsed.username is None
        and parsed.password is None
        and re.fullmatch(r"/server/validator/[A-Za-z0-9._~-]+", parsed.path) is not None
        and parsed.params == ""
        and parsed.query == ""
        and parsed.fragment == ""
    )


def _official_validation_errors(
    row: dict[str, Any], *, expected_helper_sha256: Any, expected_input_sha256: Any
) -> list[str]:
    validation = row.get("independent_validation")
    if not isinstance(validation, dict) or validation.get("feasible") is not True:
        return []
    errors: list[str] = []
    agreement = row.get("official_validator_agreement")
    if agreement is False:
        errors.append("official validator disagrees")
    elif agreement is not True:
        errors.append("official validator agreement is missing")
    if row.get("official_validator_status") != "agreement":
        errors.append("official validator status is not agreement")
    output_sha256 = row.get("output_sha256")
    validated_output_sha256 = row.get("official_validated_output_sha256")
    if not _is_sha256(output_sha256):
        errors.append("output hash is not a canonical SHA-256 digest")
    if not _is_sha256(validated_output_sha256):
        errors.append("official validated output hash is not canonical SHA-256")
    if validated_output_sha256 != output_sha256:
        errors.append("official validation is not bound to the output hash")
    if not _is_sha256(expected_helper_sha256):
        errors.append("manifest official validator helper hash is missing or malformed")
    input_sha256 = row.get("input_sha256")
    if not _is_sha256(expected_input_sha256):
        errors.append("manifest input hash is missing or malformed")
    if not _is_sha256(input_sha256):
        errors.append("run input hash is missing or malformed")
    if input_sha256 != expected_input_sha256:
        errors.append("run input hash does not match the manifest")

    evidence = row.get("official_validation")
    if not isinstance(evidence, dict):
        return [*errors, "official validator evidence is missing"]
    unexpected_fields = sorted(set(evidence) - _OFFICIAL_EVIDENCE_FIELDS)
    missing_fields = sorted(_OFFICIAL_EVIDENCE_FIELDS - set(evidence))
    if unexpected_fields:
        errors.append(
            "official validator evidence has unbound fields: "
            + ", ".join(unexpected_fields)
        )
    if missing_fields:
        errors.append(
            "official validator evidence is missing fields: "
            + ", ".join(missing_fields)
        )
    if evidence.get("evidence_version") != 3:
        errors.append("official validator evidence version is not 3")
    for field in (
        "response_sha256",
        "response_capture_binding_sha256",
        "submission_intent_binding_sha256",
        "submitted_output_sha256",
        "helper_sha256",
        "evidence_binding_sha256",
        "input_sha256",
        "request_body_sha256",
        "uploaded_file_sha256",
    ):
        if not _is_sha256(evidence.get(field)):
            errors.append(f"official validator {field} is not canonical SHA-256")

    numeric_identity_fields = {
        "seed",
        "effective_seed",
        "seed_pairing_group",
        "repetition",
        "unseeded_trial",
    }
    for field in (*_OFFICIAL_RUN_IDENTITY_FIELDS, "input_sha256"):
        evidence_value = evidence.get(field)
        row_value = row.get(field)
        if field in numeric_identity_fields:
            values_match = (evidence_value is None and row_value is None) or (
                _is_js_safe_integer(evidence_value)
                and _is_js_safe_integer(row_value)
                and int(evidence_value) == int(row_value)
            )
        else:
            values_match = (
                type(evidence_value) is type(row_value) and evidence_value == row_value
            )
        if not values_match:
            errors.append(f"official evidence run binding mismatch: {field}")
    for field in ("seed", "effective_seed", "seed_pairing_group", "unseeded_trial"):
        value = evidence.get(field)
        if value is not None and not _is_js_safe_integer(value):
            errors.append(f"official evidence {field} binding is invalid")
    if not isinstance(evidence.get("seed_control"), str) or not evidence.get(
        "seed_control"
    ):
        errors.append("official evidence seed_control binding is invalid")
    evidence_repetition = evidence.get("repetition")
    if not _is_js_safe_integer(evidence_repetition) or evidence_repetition <= 0:
        errors.append("official evidence repetition binding is invalid")
    attempt_id = evidence.get("attempt_id")
    if (
        not isinstance(attempt_id, str)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            attempt_id,
        )
        is None
    ):
        errors.append(
            "official evidence submission attempt ID is not a lowercase UUIDv4"
        )

    try:
        raw_response = _decode_official_response(evidence.get("response_body_base64"))
    except ValueError as exc:
        errors.append(str(exc))
        raw_response = None
    if raw_response is not None:
        if _sha256(raw_response) != evidence.get("response_sha256"):
            errors.append(
                "official response hash does not match the raw response bytes"
            )
        try:
            parsed = _official_result(raw_response)
        except ValueError as exc:
            errors.append(str(exc))
            parsed = None
        if parsed is not None:
            for field, value in parsed.items():
                if evidence.get(field) != value:
                    errors.append(f"official parsed response mismatch: {field}")
            objective = validation.get("objective") or {}
            agreement = bool(
                parsed["instance"] == row.get("case")
                and parsed["result"] == "OK"
                and parsed["assigned"] == parsed["variables"]
                and parsed["total"] == objective.get("total")
                and all(
                    parsed[field] == objective.get(field)
                    for field in _OFFICIAL_COMPONENT_FIELDS
                )
            )
            if agreement is not True:
                errors.append(
                    "official response components disagree with local validation"
                )

    if evidence.get("submitted_output_sha256") != output_sha256:
        errors.append("official evidence submitted hash does not match the output")
    if evidence.get("uploaded_file_sha256") != output_sha256:
        errors.append("official evidence uploaded-file hash does not match the output")
    if evidence.get("helper_sha256") != expected_helper_sha256:
        errors.append("official evidence helper hash does not match the manifest")
    if evidence.get("input_sha256") != expected_input_sha256:
        errors.append("official evidence input hash does not match the manifest")
    if not _canonical_official_timestamp(evidence.get("submission_intent_created_at")):
        errors.append(
            "official evidence submission intent timestamp is not canonical ISO-8601"
        )
    if not _canonical_official_timestamp(evidence.get("captured_at")):
        errors.append("official evidence timestamp is not canonical ISO-8601")
    response_url = evidence.get("response_url")
    response_url_is_canonical = _canonical_official_url(response_url)
    if not response_url_is_canonical:
        errors.append("official evidence URL is outside the validator endpoint")
    elif urlparse(response_url).path != f"/server/validator/{evidence.get('log_id')}":
        errors.append(
            "official evidence log identifier does not match the response URL"
        )
    response_status = evidence.get("response_status")
    if not _is_js_safe_integer(response_status) or int(response_status) != 200:
        errors.append("official evidence HTTP response status is not 200")
    response_content_type = evidence.get("response_content_type")
    if (
        not isinstance(response_content_type, str)
        or response_content_type.strip() == ""
    ):
        errors.append("official evidence response Content-Type is missing")
    if evidence.get("request_method") != "POST":
        errors.append("official evidence request method is not POST")
    request_url = evidence.get("request_url")
    if not _canonical_official_url(request_url):
        errors.append("official evidence request URL is outside the validator endpoint")
    if request_url != evidence.get("response_url"):
        errors.append("official evidence request URL does not match the response URL")
    request_content_type = evidence.get("request_content_type")
    if (
        not isinstance(request_content_type, str)
        or re.match(
            r"^multipart/form-data\s*;", request_content_type, flags=re.IGNORECASE
        )
        is None
    ):
        errors.append("official evidence request is not a multipart file upload")
    if evidence.get("correlation_method") != _OFFICIAL_CORRELATION_METHOD:
        errors.append("official evidence correlation method is unsupported")
    if (
        evidence.get("external_source_authenticity")
        != _OFFICIAL_EXTERNAL_SOURCE_AUTHENTICITY
    ):
        errors.append("official evidence external authenticity state is invalid")
    if _official_submission_intent_binding(evidence) != evidence.get(
        "submission_intent_binding_sha256"
    ):
        errors.append("official evidence submission intent binding hash mismatch")
    if _official_response_capture_binding(evidence) != evidence.get(
        "response_capture_binding_sha256"
    ):
        errors.append("official evidence response capture binding hash mismatch")
    if _official_evidence_binding(evidence) != evidence.get("evidence_binding_sha256"):
        errors.append("official evidence binding hash mismatch")
    return errors


def _official_payload_hash_errors(
    official_payload: dict[str, Any],
    *,
    official_payload_bytes: bytes | None,
    expected_sha256: str | None,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    actual_sha256 = (
        _sha256(official_payload_bytes) if official_payload_bytes is not None else None
    )
    if expected_sha256 is None:
        errors.append("expected official payload SHA-256 was not supplied")
    elif not _is_sha256(expected_sha256):
        errors.append(
            "expected official payload SHA-256 is not canonical lowercase hex"
        )
    if official_payload_bytes is None:
        errors.append("exact official payload bytes were not supplied")
    else:
        try:
            decoded_payload = json.loads(official_payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append("official payload bytes are not valid UTF-8 JSON")
        else:
            if decoded_payload != official_payload:
                errors.append("official payload bytes do not match the parsed payload")
    if (
        actual_sha256 is not None
        and _is_sha256(expected_sha256)
        and actual_sha256 != expected_sha256
    ):
        errors.append("official payload SHA-256 does not match the expected digest")
    return actual_sha256, errors


def _read_bound_evidence_file(
    row: dict[str, Any],
    *,
    matrix_root: Path | None,
    object_field: str,
    path_field: str,
    canonical_sha256_field: str,
    file_sha256_field: str,
    filename: str,
) -> list[str]:
    run_id = row.get("run_id")
    label = object_field.replace("_", " ")
    errors: list[str] = []
    payload = row.get(object_field)
    canonical_sha256 = row.get(canonical_sha256_field)
    file_sha256 = row.get(file_sha256_field)
    if not isinstance(payload, dict):
        errors.append(f"{label} is missing")
    if not _is_concrete_sha256(canonical_sha256):
        errors.append(f"{label} canonical digest is missing, malformed, or placeholder")
    elif (
        isinstance(payload, dict)
        and _sha256(_canonical_json_bytes(payload)) != canonical_sha256
    ):
        errors.append(f"{label} canonical digest mismatch")
    if not _is_concrete_sha256(file_sha256):
        errors.append(f"{label} file digest is missing, malformed, or placeholder")
    if matrix_root is None:
        return [*errors, f"{label} cannot be verified without the matrix root"]
    if not isinstance(run_id, str) or not run_id:
        return [*errors, f"{label} run identity is missing"]
    try:
        root = matrix_root.resolve(strict=True)
        runs_root = (root / "runs").resolve(strict=True)
        expected_path = (runs_root / run_id / filename).resolve(strict=True)
    except (OSError, RuntimeError):
        return [*errors, f"{label} expected file is unavailable"]
    try:
        expected_path.relative_to(runs_root)
    except ValueError:
        return [*errors, f"{label} expected file escapes the matrix root"]
    supplied_path = row.get(path_field)
    if not isinstance(supplied_path, str) or not supplied_path:
        errors.append(f"{label} path is missing")
    else:
        try:
            resolved_supplied = Path(supplied_path).resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"{label} path is unavailable")
        else:
            if resolved_supplied != expected_path:
                errors.append(f"{label} path does not match the immutable run path")
    if not expected_path.is_file():
        return [*errors, f"{label} expected path is not a regular file"]
    try:
        chunks: list[bytes] = []
        with expected_path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            while chunk := handle.read(1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
        final = expected_path.stat()
    except OSError:
        return [*errors, f"{label} file could not be read"]
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    final_identity = (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
    )
    if before_identity != after_identity or after_identity != final_identity:
        errors.append(f"{label} file changed while it was being verified")
    raw = b"".join(chunks)
    if _is_concrete_sha256(file_sha256) and _sha256(raw) != file_sha256:
        errors.append(f"{label} file digest mismatch")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"{label} file is not valid UTF-8 JSON")
    else:
        if decoded != payload:
            errors.append(f"{label} file does not match the inline evidence")
    return errors


def _controller_raw_run_evidence_binding(
    report: dict[str, Any], *, matrix_root: Path | None
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    manifest = report.get("manifest")
    records = report.get("records")
    if not isinstance(manifest, dict):
        return None, ["matrix manifest is missing"]
    if not isinstance(records, list) or not records:
        return None, ["matrix records are missing"]
    if any(not isinstance(row, dict) for row in records):
        return None, ["matrix records contain a non-object entry"]
    controller = manifest.get("resource_controller")
    if not isinstance(controller, dict):
        return None, ["claim-grade resource controller binding is missing"]
    if controller.get("mode") != "claim-grade-controller":
        errors.append("trust anchor requires claim-grade controller mode")
    for field in (
        "claim_grade_ready",
        "equal_wall_time_claim",
        "equal_memory_limit_claim",
    ):
        if controller.get(field) is not True:
            errors.append(f"trust anchor controller {field} is not true")

    matrix_created_utc = manifest.get("created_utc")
    if not isinstance(matrix_created_utc, str) or not matrix_created_utc:
        errors.append("matrix creation timestamp is missing")

    claim_evidence_bindings: list[dict[str, str]] = []
    raw_run_bindings: list[dict[str, Any]] = []
    for row in sorted(records, key=lambda item: str(item.get("run_id", ""))):
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            errors.append("raw-run evidence has a missing run identity")
            continue
        row_errors: list[str] = []
        resource_evidence = row.get("resource_evidence")
        raw_evidence = row.get("raw_resource_evidence")
        controller_invocation = row.get("controller_invocation")
        if not isinstance(resource_evidence, dict):
            row_errors.append("normalized resource evidence is missing")
        if not isinstance(raw_evidence, dict):
            row_errors.append("raw resource evidence is missing")
        resource_sha256 = row.get("resource_evidence_sha256")
        raw_sha256 = row.get("raw_resource_evidence_sha256")
        invocation_sha256 = row.get("controller_invocation_sha256")
        for field, value in (
            ("controller invocation", invocation_sha256),
            ("normalized resource evidence", resource_sha256),
            ("raw resource evidence", raw_sha256),
            ("output artifact", row.get("output_sha256")),
            ("artifact binding", row.get("artifact_binding_sha256")),
        ):
            if not _is_concrete_sha256(value):
                row_errors.append(
                    f"{field} digest is missing, malformed, or placeholder"
                )
        if not isinstance(controller_invocation, dict):
            row_errors.append("controller invocation payload is missing")
        else:
            if controller_invocation.get("run_id") != run_id:
                row_errors.append("controller invocation run identity mismatch")
            if _sha256(_canonical_json_bytes(controller_invocation)) != (
                invocation_sha256
            ):
                row_errors.append("controller invocation digest mismatch")
        if isinstance(resource_evidence, dict):
            if resource_evidence.get("schema") != RESOURCE_EVIDENCE_SCHEMA:
                row_errors.append("normalized resource evidence schema is unsupported")
            if resource_evidence.get("run_id") != run_id:
                row_errors.append("normalized resource evidence run identity mismatch")
            if resource_evidence.get("invocation_sha256") != invocation_sha256:
                row_errors.append("normalized resource evidence invocation mismatch")
            if resource_evidence.get("invocation") != controller_invocation:
                row_errors.append(
                    "normalized resource evidence invocation payload mismatch"
                )
        if isinstance(raw_evidence, dict):
            if raw_evidence.get("schema") != _RAW_RESOURCE_EVIDENCE_SCHEMA:
                row_errors.append("raw resource evidence schema is unsupported")
            if raw_evidence.get("invocation_sha256") != invocation_sha256:
                row_errors.append("raw resource evidence invocation mismatch")
        row_errors.extend(
            _read_bound_evidence_file(
                row,
                matrix_root=matrix_root,
                object_field="resource_evidence",
                path_field="resource_evidence_path",
                canonical_sha256_field="resource_evidence_sha256",
                file_sha256_field="resource_evidence_file_sha256",
                filename="resource-evidence.json",
            )
        )
        row_errors.extend(
            _read_bound_evidence_file(
                row,
                matrix_root=matrix_root,
                object_field="raw_resource_evidence",
                path_field="raw_resource_evidence_path",
                canonical_sha256_field="raw_resource_evidence_sha256",
                file_sha256_field="raw_resource_evidence_file_sha256",
                filename="resource-evidence-raw.json",
            )
        )
        if row_errors:
            errors.extend(f"{run_id}: {error}" for error in row_errors)
        claim_evidence_bindings.append(
            {
                "run_id": run_id,
                "resource_evidence_sha256": str(resource_sha256),
            }
        )
        raw_run_bindings.append(
            {
                "run_id": run_id,
                "controller_invocation_sha256": invocation_sha256,
                "resource_evidence_sha256": resource_sha256,
                "resource_evidence_file_sha256": row.get(
                    "resource_evidence_file_sha256"
                ),
                "raw_resource_evidence_sha256": raw_sha256,
                "raw_resource_evidence_file_sha256": row.get(
                    "raw_resource_evidence_file_sha256"
                ),
                "output_sha256": row.get("output_sha256"),
                "artifact_binding_sha256": row.get("artifact_binding_sha256"),
            }
        )

    actual_claim_evidence_set_sha256 = _sha256(
        _canonical_json_bytes(claim_evidence_bindings)
    )
    declared_claim_evidence_set_sha256 = controller.get("claim_evidence_set_sha256")
    if not _is_concrete_sha256(declared_claim_evidence_set_sha256):
        errors.append(
            "controller claim evidence-set digest is missing, malformed, or placeholder"
        )
    elif declared_claim_evidence_set_sha256 != actual_claim_evidence_set_sha256:
        errors.append("controller claim evidence-set digest mismatch")

    evidence_binding = {
        "schema": _CONTROLLER_EVIDENCE_BINDING_SCHEMA,
        "matrix_created_utc": matrix_created_utc,
        "manifest_sha256": _sha256(_canonical_json_bytes(manifest)),
        "controller_binding_sha256": _sha256(_canonical_json_bytes(controller)),
        "records_sha256": _sha256(
            _canonical_json_bytes(
                sorted(records, key=lambda item: str(item.get("run_id", "")))
            )
        ),
        "claim_evidence_set_sha256": actual_claim_evidence_set_sha256,
        "raw_run_evidence_set_sha256": _sha256(_canonical_json_bytes(raw_run_bindings)),
        "run_count": len(records),
    }
    return evidence_binding, errors


def _official_trust_anchor_errors(
    report: dict[str, Any],
    official_payload: dict[str, Any],
    *,
    matrix_root: Path | None,
    actual_payload_sha256: str | None,
    trust_anchor: Any,
    trust_anchor_bytes: bytes | None,
    expected_trust_anchor_sha256: str | None,
    trust_anchor_source: str | None,
) -> tuple[str | None, str | None, list[str]]:
    errors: list[str] = []
    actual_anchor_sha256 = (
        _sha256(trust_anchor_bytes) if trust_anchor_bytes is not None else None
    )
    evidence_binding, evidence_errors = _controller_raw_run_evidence_binding(
        report, matrix_root=matrix_root
    )
    errors.extend(evidence_errors)
    actual_matrix_evidence_sha256 = (
        _sha256(_canonical_json_bytes(evidence_binding))
        if evidence_binding is not None
        else None
    )
    if trust_anchor_source != _OFFICIAL_TRUST_ANCHOR_SOURCE:
        errors.append("official trust anchor was not pinned by the claim CLI")
    if not _is_concrete_sha256(expected_trust_anchor_sha256):
        errors.append(
            "expected official trust-anchor digest is missing, malformed, or placeholder"
        )
    elif actual_anchor_sha256 != expected_trust_anchor_sha256:
        errors.append("official trust-anchor bytes do not match the pinned digest")
    if trust_anchor_bytes is None:
        errors.append("exact official trust-anchor bytes were not supplied")
    else:
        try:
            decoded_anchor = json.loads(trust_anchor_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append("official trust-anchor bytes are not valid UTF-8 JSON")
        else:
            if decoded_anchor != trust_anchor:
                errors.append(
                    "official trust-anchor bytes do not match the parsed anchor"
                )
            if trust_anchor_bytes != _canonical_json_bytes(decoded_anchor):
                errors.append("official trust-anchor bytes are not canonical JSON")
    if not isinstance(trust_anchor, dict):
        return (
            actual_anchor_sha256,
            actual_matrix_evidence_sha256,
            [
                *errors,
                "official trust anchor is missing or malformed",
            ],
        )
    if set(trust_anchor) != _OFFICIAL_TRUST_ANCHOR_FIELDS:
        errors.append("official trust anchor fields do not match the v2 contract")
    if trust_anchor.get("schema") != _OFFICIAL_TRUST_ANCHOR_SCHEMA:
        errors.append("official trust anchor has an unsupported schema")
    if trust_anchor.get("mode") != _OFFICIAL_TRUST_ANCHOR_MODE:
        errors.append(
            "official trust anchor is not bound to controller raw-run evidence"
        )
    if trust_anchor.get("authority") != "ITC 2019":
        errors.append("official trust anchor authority is not ITC 2019")
    payload_sha256 = trust_anchor.get("official_payload_sha256")
    if not _is_concrete_sha256(payload_sha256):
        errors.append(
            "official trust anchor payload digest is malformed or placeholder"
        )
    elif payload_sha256 != actual_payload_sha256:
        errors.append("official payload does not match the pinned trust anchor")
    source_url = trust_anchor.get("source_url")
    if source_url != official_payload.get("url"):
        errors.append("official trust anchor URL does not match the payload source")
    if not isinstance(source_url, str):
        errors.append("official trust anchor URL is missing")
    else:
        try:
            parsed = urlparse(source_url)
            port = parsed.port
        except ValueError:
            parsed = None
            port = None
        if not (
            parsed
            and parsed.scheme == "https"
            and parsed.hostname in {"itc2019.org", "www.itc2019.org"}
            and port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and parsed.fragment == ""
        ):
            errors.append("official trust anchor source is not an ITC 2019 HTTPS URL")
    if trust_anchor.get("captured_at") != official_payload.get("captured_at"):
        errors.append("official trust anchor capture time does not match the payload")
    matrix_created_utc = (
        evidence_binding.get("matrix_created_utc")
        if isinstance(evidence_binding, dict)
        else None
    )
    if trust_anchor.get("matrix_created_utc") != matrix_created_utc:
        errors.append("official trust anchor is stale for this matrix creation")
    matrix_evidence_sha256 = trust_anchor.get("matrix_evidence_sha256")
    if not _is_concrete_sha256(matrix_evidence_sha256):
        errors.append(
            "official trust anchor matrix-evidence digest is malformed or placeholder"
        )
    elif matrix_evidence_sha256 != actual_matrix_evidence_sha256:
        errors.append(
            "official trust anchor is stale or mismatched for matrix evidence"
        )
    return actual_anchor_sha256, actual_matrix_evidence_sha256, errors


def _resource_policy_errors(manifest: dict[str, Any]) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    controller = manifest.get("resource_controller")
    if not isinstance(controller, dict):
        return None, ["resource controller profile is missing"]
    mode = controller.get("mode")
    if mode not in {"claim-grade-controller", "evidence-only-controller"}:
        errors.append("resource controller mode is unsupported")
    if mode == "evidence-only-controller":
        for field in (
            "claim_grade_ready",
            "equal_wall_time_claim",
            "equal_memory_limit_claim",
        ):
            if controller.get(field) is not False:
                errors.append(
                    f"evidence-only resource controller {field} must be false"
                )
    for field in (
        "controller_source_sha256",
        "capability_sha256",
        "supervisor_sha256",
    ):
        if not _is_sha256(controller.get(field)):
            errors.append(f"resource controller {field} is malformed")
    profile = controller.get("profile")
    if not isinstance(profile, dict):
        return None, [*errors, "resource controller profile is missing"]
    if profile.get("schema") != "planora.itc2019.resource-profile.v1":
        errors.append("resource controller profile schema is unsupported")
    profile_sha256 = controller.get("profile_sha256")
    if not _is_sha256(profile_sha256):
        errors.append("resource controller profile hash is malformed")
    elif profile_sha256 != _sha256(_canonical_json_bytes(profile)):
        errors.append("resource controller profile hash mismatch")
    positive_int_fields = (
        "memory_bytes",
        "memory_swap_bytes",
        "cpu_quota_us",
        "cpu_period_us",
        "pids_limit",
    )
    for field in positive_int_fields:
        value = profile.get(field)
        if type(value) is not int or value <= 0:
            errors.append(f"resource controller profile {field} is invalid")
    wall_time = profile.get("wall_time_seconds")
    if (
        isinstance(wall_time, bool)
        or not isinstance(wall_time, (int, float))
        or not math.isfinite(float(wall_time))
        or float(wall_time) <= 0
    ):
        errors.append("resource controller profile wall_time_seconds is invalid")
    artifact_grace = profile.get("artifact_grace_seconds")
    if (
        isinstance(artifact_grace, bool)
        or not isinstance(artifact_grace, (int, float))
        or not math.isfinite(float(artifact_grace))
        or float(artifact_grace) < 0
    ):
        errors.append("resource controller profile artifact_grace_seconds is invalid")
    if (
        type(profile.get("memory_swap_bytes")) is int
        and type(profile.get("memory_bytes")) is int
        and profile["memory_swap_bytes"] < profile["memory_bytes"]
    ):
        errors.append(
            "resource controller profile memory_swap_bytes is below memory_bytes"
        )
    if not isinstance(profile.get("cpuset_cpus"), str) or not profile.get(
        "cpuset_cpus"
    ):
        errors.append("resource controller profile cpuset_cpus is invalid")
    if (
        type(profile.get("cpu_quota_us")) is int
        and type(profile.get("cpu_period_us")) is int
        and profile["cpu_quota_us"] != profile["cpu_period_us"]
    ):
        errors.append("resource controller profile does not enforce one CPU of quota")
    return profile_sha256 if _is_sha256(profile_sha256) else None, errors


def _resource_claim_readiness_errors(manifest: dict[str, Any]) -> list[str]:
    controller = manifest.get("resource_controller")
    if not isinstance(controller, dict):
        return ["resource controller is unavailable for claim-grade comparison"]
    errors = []
    if controller.get("mode") != "claim-grade-controller":
        errors.append("resource controller run is explicitly evidence-only")
    for field in (
        "claim_grade_ready",
        "equal_wall_time_claim",
        "equal_memory_limit_claim",
    ):
        if controller.get(field) is not True:
            errors.append(f"resource controller {field} is not true")
    return errors


def _resource_evidence_errors(
    row: dict[str, Any],
    *,
    expected_profile_sha256: str | None,
    profile: dict[str, Any] | None,
    controller: dict[str, Any] | None,
) -> list[str]:
    evidence = row.get("resource_evidence")
    if not isinstance(evidence, dict):
        return ["per-run resource evidence is missing"]
    errors: list[str] = []
    schema = evidence.get("schema")
    if schema not in {
        RESOURCE_EVIDENCE_SCHEMA,
        DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
    }:
        errors.append("resource evidence schema is unsupported")
    if evidence.get("run_id") != row.get("run_id"):
        errors.append("resource evidence run identity mismatch")
    if evidence.get("profile_sha256") != expected_profile_sha256:
        errors.append("resource evidence profile hash mismatch")
    if evidence.get("artifact_sha256") != row.get("output_sha256"):
        errors.append("resource evidence artifact hash mismatch")
    for field in (
        "invocation_sha256",
        "capability_sha256",
        "supervisor_sha256",
    ):
        if not _is_sha256(evidence.get(field)):
            errors.append(f"resource evidence {field} is malformed")
    if isinstance(controller, dict):
        for field in ("capability_sha256", "supervisor_sha256"):
            if evidence.get(field) != controller.get(field):
                errors.append(
                    f"resource evidence {field} does not match the controller"
                )
    evidence_sha256 = row.get("resource_evidence_sha256")
    if not _is_sha256(evidence_sha256):
        errors.append("resource evidence binding hash is malformed")
    else:
        try:
            actual_evidence_sha256 = resource_evidence_sha256(evidence)
        except ResourceControllerError:
            actual_evidence_sha256 = None
        if evidence_sha256 != actual_evidence_sha256:
            errors.append("resource evidence binding hash mismatch")

    if schema == DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA:
        if not isinstance(controller, dict) or controller.get("mode") != (
            "evidence-only-controller"
        ):
            errors.append(
                "descriptive resource evidence requires evidence-only controller mode"
            )
        if evidence.get("mode") != "evidence-only-controller":
            errors.append("descriptive resource evidence mode is invalid")
        if evidence.get("claim_grade_ready") is not False:
            errors.append("descriptive resource evidence must remain non-claim-grade")
        if isinstance(controller, dict):
            for field in (
                "controller_version",
                "controller_source_sha256",
                "config_sha256",
                "profile_sha256",
            ):
                if evidence.get(field) != controller.get(field):
                    errors.append(
                        f"descriptive resource evidence {field} does not match "
                        "the controller"
                    )
        execution = evidence.get("execution")
        if not isinstance(execution, dict):
            errors.append("descriptive resource execution evidence is missing")
        else:
            if execution.get("run_id") != row.get("run_id"):
                errors.append("descriptive execution run identity mismatch")
            if execution.get("timed_out") is not False:
                errors.append("descriptive execution reports a timeout")
            if execution.get("cleanup_complete") is not True:
                errors.append("descriptive execution cleanup is incomplete")
            if execution.get("residual_processes") != 0:
                errors.append("descriptive execution reports residual processes")
        cleanup = evidence.get("cleanup")
        if not isinstance(cleanup, list) or not any(
            isinstance(item, dict) and item.get("absence_verified") is True
            for item in cleanup
        ):
            errors.append("descriptive resource cleanup proof is incomplete")
        return errors

    if evidence.get("claim_grade_ready") is not True:
        errors.append("resource evidence is not claim-grade ready")
    if evidence.get("deadline_exceeded") is not False:
        errors.append("resource evidence reports a deadline overrun")
    if evidence.get("cleanup_complete") is not True:
        errors.append("resource evidence cleanup is incomplete")
    if evidence.get("residual_processes") != 0:
        errors.append("resource evidence reports residual processes")
    if isinstance(profile, dict):
        swap_allowance = None
        if (
            type(profile.get("memory_swap_bytes")) is int
            and type(profile.get("memory_bytes")) is int
        ):
            swap_allowance = profile["memory_swap_bytes"] - profile["memory_bytes"]
        expected_limits = {
            "effective_memory_max": profile.get("memory_bytes"),
            "effective_memory_swap_max": swap_allowance,
            "effective_cpu_max": (
                f"{profile.get('cpu_quota_us')} {profile.get('cpu_period_us')}"
            ),
            "effective_cpuset_cpus": profile.get("cpuset_cpus"),
            "effective_pids_max": profile.get("pids_limit"),
        }
        for field, expected in expected_limits.items():
            if evidence.get(field) != expected:
                errors.append(f"resource evidence {field} does not match the profile")
        elapsed = evidence.get("elapsed_monotonic_ns")
        if type(elapsed) is not int or elapsed < 0:
            errors.append("resource evidence elapsed_monotonic_ns is invalid")
        elif isinstance(profile.get("wall_time_seconds"), (int, float)) and elapsed > (
            float(profile["wall_time_seconds"]) * 1_000_000_000
        ):
            errors.append("resource evidence exceeds the wall-time profile")
        for evidence_field, profile_field in (("memory_peak_bytes", "memory_bytes"),):
            value = evidence.get(evidence_field)
            limit = profile.get(profile_field)
            if type(value) is not int or value < 0:
                errors.append(f"resource evidence {evidence_field} is invalid")
            elif type(limit) is int and value > limit:
                errors.append(f"resource evidence {evidence_field} exceeds the profile")
        swap_peak = evidence.get("memory_swap_peak_bytes")
        if type(swap_peak) is not int or swap_peak < 0:
            errors.append("resource evidence memory_swap_peak_bytes is invalid")
        elif type(swap_allowance) is int and swap_peak > swap_allowance:
            errors.append(
                "resource evidence memory_swap_peak_bytes exceeds the profile"
            )
    return errors


def _claim_replication_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    raw_seeds = manifest.get("seeds")
    seeds = (
        set(raw_seeds)
        if isinstance(raw_seeds, list)
        and all(type(value) is int for value in raw_seeds)
        else set()
    )
    if len(seeds) < 3:
        errors.append("claim-grade aggregation requires at least 3 seeds")
    raw_repetitions = manifest.get("repetitions")
    if type(raw_repetitions) is not int:
        repetitions = 0
    else:
        repetitions = raw_repetitions
    if repetitions < 2:
        errors.append("claim-grade aggregation requires at least 2 repetitions")
    return errors


def _validated_total(row: dict[str, Any] | None) -> int | None:
    validation = row.get("independent_validation") if isinstance(row, dict) else None
    objective = (
        validation.get("objective")
        if isinstance(validation, dict) and validation.get("feasible") is True
        else None
    )
    total = objective.get("total") if isinstance(objective, dict) else None
    return total if type(total) is int else None


def _direct_planora_pairwise_comparisons(
    *,
    expected: list[dict[str, Any]],
    validated_by_id: dict[str, dict[str, Any]],
    solvers: list[str],
    claim_ready: bool,
) -> list[dict[str, Any]]:
    planora = {
        (row["case"], row["seed_pairing_group"], row["repetition"]): row
        for row in expected
        if row.get("solver") == "planora"
        and row.get("seed_control") == "explicit"
        and type(row.get("seed_pairing_group")) is int
    }
    comparisons = []
    for competitor in (solver for solver in solvers if solver != "planora"):
        competitor_rows = {
            (row["case"], row["seed_pairing_group"], row["repetition"]): row
            for row in expected
            if row.get("solver") == competitor
            and row.get("seed_control") == "explicit"
            and type(row.get("seed_pairing_group")) is int
        }
        matching_keys = sorted(set(planora) & set(competitor_rows))
        pairing_eligible = bool(matching_keys)
        paired_cells = []
        outcomes = []
        deltas = []
        for case, seed_group, repetition in matching_keys:
            planora_identity = planora[(case, seed_group, repetition)]
            competitor_identity = competitor_rows[(case, seed_group, repetition)]
            planora_total = _validated_total(
                validated_by_id.get(str(planora_identity["run_id"]))
            )
            competitor_total = _validated_total(
                validated_by_id.get(str(competitor_identity["run_id"]))
            )
            delta = (
                planora_total - competitor_total
                if planora_total is not None and competitor_total is not None
                else None
            )
            outcome = (
                "planora_better"
                if delta is not None and delta < 0
                else "tie"
                if delta == 0
                else "planora_worse"
                if delta is not None
                else None
            )
            paired_cells.append(
                {
                    "case": case,
                    "seed_pairing_group": seed_group,
                    "repetition": repetition,
                    "planora_run_id": planora_identity["run_id"],
                    "competitor_run_id": competitor_identity["run_id"],
                    "planora_total": planora_total,
                    "competitor_total": competitor_total,
                    "planora_minus_competitor": delta,
                    "outcome": outcome,
                }
            )
            if outcome is not None and delta is not None:
                outcomes.append(outcome)
                deltas.append(delta)
        complete = pairing_eligible and len(outcomes) == len(matching_keys)
        comparisons.append(
            {
                "competitor": competitor,
                "identical_seed_pairing_eligible": pairing_eligible,
                "pairing_exclusion_reason": None
                if pairing_eligible
                else "no explicit deterministic seed pairing shared with Planora",
                "comparison_eligible": bool(claim_ready and complete),
                "paired_cells": paired_cells,
                "paired_statistics": {
                    "prespecified_cell_count": len(matching_keys),
                    "observed_valid_cell_count": len(outcomes),
                    "complete": complete,
                    "mean_planora_minus_competitor": statistics.fmean(deltas)
                    if deltas
                    else None,
                    "median_planora_minus_competitor": statistics.median(deltas)
                    if deltas
                    else None,
                    "planora_wins": outcomes.count("planora_better"),
                    "ties": outcomes.count("tie"),
                    "planora_losses": outcomes.count("planora_worse"),
                },
            }
        )
    return comparisons


def summarize(
    report: dict[str, Any],
    official_payload: dict[str, Any],
    *,
    claim_eligibility_requested: bool = True,
    matrix_root: Path | None = None,
    expected_official_payload_sha256: str | None = None,
    official_payload_bytes: bytes | None = None,
    official_trust_anchor: Any = None,
    official_trust_anchor_bytes: bytes | None = None,
    expected_official_trust_anchor_sha256: str | None = None,
    official_trust_anchor_source: str | None = None,
) -> dict[str, Any]:
    manifest = dict(report.get("manifest") or {})
    raw_records = report.get("records")
    records = list(raw_records) if isinstance(raw_records, list) else []
    official, official_results_errors = _official_scores(official_payload)
    actual_official_payload_sha256, official_payload_hash_errors = (
        _official_payload_hash_errors(
            official_payload,
            official_payload_bytes=official_payload_bytes,
            expected_sha256=expected_official_payload_sha256,
        )
    )
    (
        actual_official_trust_anchor_sha256,
        actual_matrix_evidence_sha256,
        official_trust_anchor_errors,
    ) = _official_trust_anchor_errors(
        report,
        official_payload,
        matrix_root=matrix_root,
        actual_payload_sha256=actual_official_payload_sha256,
        trust_anchor=official_trust_anchor,
        trust_anchor_bytes=official_trust_anchor_bytes,
        expected_trust_anchor_sha256=expected_official_trust_anchor_sha256,
        trust_anchor_source=official_trust_anchor_source,
    )
    external_authenticity_unproven = bool(official_trust_anchor_errors)
    summary_mode_errors = (
        []
        if claim_eligibility_requested
        else [
            "descriptive-only execution never emits claim eligibility; rerun the "
            "claim CLI with independently pinned evidence"
        ]
    )
    cases = [str(value) for value in manifest.get("cases") or []]
    solvers = [str(value) for value in manifest.get("solvers") or []]
    expected, manifest_errors = _derived_expected_runs(manifest)
    manifest_errors.extend(_manifest_expected_run_errors(manifest, expected))
    if not isinstance(raw_records, list):
        manifest_errors.append("report.records must be a list")
    non_object_records = [
        index for index, row in enumerate(records) if not isinstance(row, dict)
    ]
    if non_object_records:
        manifest_errors.append(
            "report.records contains non-object entries at indexes "
            + ", ".join(str(index) for index in non_object_records)
        )
    records = [row for row in records if isinstance(row, dict)]
    planned = len(expected)
    sha256_validation_failures = [
        *_sha256_field_errors(report, path="report"),
        *_sha256_field_errors(official_payload, path="official_payload"),
    ]
    replication_errors = _claim_replication_errors(manifest)
    resource_profile_sha256, resource_policy_errors = _resource_policy_errors(manifest)
    resource_claim_readiness_errors = _resource_claim_readiness_errors(manifest)
    resource_controller = manifest.get("resource_controller")
    resource_profile = (
        resource_controller.get("profile")
        if isinstance(resource_controller, dict)
        and isinstance(resource_controller.get("profile"), dict)
        else None
    )
    manifest_inputs = manifest.get("inputs")

    expected_by_id = {str(row["run_id"]): row for row in expected}
    expected_id_counts = Counter(str(row["run_id"]) for row in expected)
    actual_id_counts = Counter(str(row.get("run_id", "")) for row in records)
    expected_cell_counts = Counter(_cell_token(row) for row in expected)
    actual_cell_counts = Counter(_cell_token(row) for row in records)
    expected_cell_values = {_cell_token(row): _semantic_cell(row) for row in expected}
    actual_cell_values = {_cell_token(row): _semantic_cell(row) for row in records}

    duplicate_run_ids = sorted(
        run_id for run_id, count in actual_id_counts.items() if count > 1
    )
    duplicate_semantic_cells = []
    for token, count in sorted(actual_cell_counts.items()):
        if count <= 1:
            continue
        duplicate_semantic_cells.append(
            {
                "cell": actual_cell_values[token],
                "count": count,
                "run_ids": sorted(
                    str(row.get("run_id", ""))
                    for row in records
                    if _cell_token(row) == token
                ),
            }
        )
    missing_run_ids = sorted((expected_id_counts - actual_id_counts).elements())
    unexpected_run_ids = sorted((actual_id_counts - expected_id_counts).elements())
    missing_cells = [
        {"cell": expected_cell_values[token], "count": count}
        for token, count in sorted((expected_cell_counts - actual_cell_counts).items())
    ]
    unexpected_cells = [
        {"cell": actual_cell_values[token], "count": count}
        for token, count in sorted((actual_cell_counts - expected_cell_counts).items())
    ]
    identity_mismatches = []
    for row in records:
        run_id = str(row.get("run_id", ""))
        expected_row = expected_by_id.get(run_id)
        if expected_row is None:
            continue
        fields = [
            field
            for field in _SEMANTIC_CELL_FIELDS
            if row.get(field) != expected_row.get(field)
        ]
        if fields:
            identity_mismatches.append({"run_id": run_id, "fields": fields})

    output_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        normalized = _normal_output_path(row.get("output_path"))
        if normalized is not None:
            output_groups[normalized].append(row)
    duplicate_output_paths = [
        {
            "output_path": path,
            "run_ids": sorted(str(row.get("run_id", "")) for row in grouped),
        }
        for path, grouped in sorted(output_groups.items())
        if len(grouped) > 1
    ]
    duplicated_paths = {
        path for path, grouped in output_groups.items() if len(grouped) > 1
    }

    trusted_records: list[dict[str, Any]] = []
    for row in records:
        run_id = str(row.get("run_id", ""))
        token = _cell_token(row)
        normalized_output = _normal_output_path(row.get("output_path"))
        if (
            run_id in expected_by_id
            and actual_id_counts[run_id] == 1
            and actual_cell_counts[token] == 1
            and token == _cell_token(expected_by_id[run_id])
            and normalized_output not in duplicated_paths
        ):
            trusted_records.append(row)
    trusted_by_id = {str(row.get("run_id", "")): row for row in trusted_records}

    incomplete_local_validation = []
    official_validation_failures = []
    artifact_validation_failures = []
    resource_evidence_failures = []
    locally_complete_records: list[dict[str, Any]] = []
    for row in trusted_records:
        if row.get("output_path") is not None:
            _artifact_sha256, artifact_errors = _hash_confined_artifact(
                row, matrix_root=matrix_root
            )
            if artifact_errors:
                artifact_validation_failures.append(
                    {
                        "run_id": str(row.get("run_id", "")),
                        "reasons": artifact_errors,
                    }
                )
        resource_errors = _resource_evidence_errors(
            row,
            expected_profile_sha256=resource_profile_sha256,
            profile=resource_profile,
            controller=resource_controller
            if isinstance(resource_controller, dict)
            else None,
        )
        if resource_errors:
            resource_evidence_failures.append(
                {"run_id": str(row.get("run_id", "")), "reasons": resource_errors}
            )
        local_errors = _local_validation_errors(row)
        if local_errors:
            incomplete_local_validation.append(
                {"run_id": str(row.get("run_id", "")), "reasons": local_errors}
            )
            continue
        locally_complete_records.append(row)
        official_errors = _official_validation_errors(
            row,
            expected_helper_sha256=manifest.get("official_validator_helper_sha256"),
            expected_input_sha256=(
                manifest_inputs.get(str(row.get("case")))
                if isinstance(manifest_inputs, dict)
                else None
            ),
        )
        if official_errors:
            official_validation_failures.append(
                {"run_id": str(row.get("run_id", "")), "reasons": official_errors}
            )

    official_evidence_groups: dict[str, dict[str, set[str]]] = {
        field: defaultdict(set) for field in _OFFICIAL_UNIQUE_EVIDENCE_FIELDS
    }
    for row in trusted_records:
        evidence = row.get("official_validation")
        if not isinstance(evidence, dict):
            continue
        run_id = str(row.get("run_id", ""))
        for field, groups in official_evidence_groups.items():
            value = evidence.get(field)
            if isinstance(value, str) and value:
                groups[value].add(run_id)
    reused_official_evidence = []
    for field, groups in official_evidence_groups.items():
        for value, run_ids in sorted(groups.items()):
            if len(run_ids) > 1:
                reused_official_evidence.append(
                    {field: value, "run_ids": sorted(run_ids)}
                )

    resource_invocation_groups: dict[str, set[str]] = defaultdict(set)
    for row in trusted_records:
        evidence = row.get("resource_evidence")
        if not isinstance(evidence, dict):
            continue
        invocation_sha256 = evidence.get("invocation_sha256")
        if _is_sha256(invocation_sha256):
            resource_invocation_groups[str(invocation_sha256)].add(
                str(row.get("run_id", ""))
            )
    reused_resource_invocations = [
        {"invocation_sha256": value, "run_ids": sorted(run_ids)}
        for value, run_ids in sorted(resource_invocation_groups.items())
        if len(run_ids) > 1
    ]

    locally_complete_by_id = {
        str(row.get("run_id", "")): row for row in locally_complete_records
    }
    planora_feasibility_failures = []
    for identity in expected:
        if identity["solver"] != "planora":
            continue
        run_id = str(identity["run_id"])
        row = locally_complete_by_id.get(run_id)
        if row is None:
            reason = (
                "local validation is incomplete"
                if run_id in trusted_by_id
                else "expected cell is missing or structurally untrusted"
            )
        elif row["independent_validation"]["feasible"] is not True:
            reason = "independent validation reports infeasible"
        else:
            continue
        planora_feasibility_failures.append({"run_id": run_id, "reason": reason})

    missing_official_cases = sorted(case for case in cases if case not in official)
    diagnostics = {
        "manifest_errors": manifest_errors,
        "sha256_validation_failures": sha256_validation_failures,
        "official_results_errors": official_results_errors,
        "official_payload_hash_errors": official_payload_hash_errors,
        "official_trust_anchor_errors": official_trust_anchor_errors,
        "external_authenticity_unproven": external_authenticity_unproven,
        "summary_mode_errors": summary_mode_errors,
        "replication_errors": replication_errors,
        "resource_policy_errors": resource_policy_errors,
        "resource_claim_readiness_errors": resource_claim_readiness_errors,
        "duplicate_run_ids": duplicate_run_ids,
        "duplicate_semantic_cells": duplicate_semantic_cells,
        "missing_run_ids": missing_run_ids,
        "unexpected_run_ids": unexpected_run_ids,
        "missing_cells": missing_cells,
        "unexpected_cells": unexpected_cells,
        "identity_mismatches": identity_mismatches,
        "duplicate_output_paths": duplicate_output_paths,
        "incomplete_local_validation": incomplete_local_validation,
        "planora_feasibility_failures": planora_feasibility_failures,
        "official_validation_failures": official_validation_failures,
        "reused_official_evidence": reused_official_evidence,
        "artifact_validation_failures": artifact_validation_failures,
        "resource_evidence_failures": resource_evidence_failures,
        "reused_resource_invocations": reused_resource_invocations,
        "missing_official_cases": missing_official_cases,
    }
    structural_keys = (
        "manifest_errors",
        "duplicate_run_ids",
        "duplicate_semantic_cells",
        "missing_run_ids",
        "unexpected_run_ids",
        "missing_cells",
        "unexpected_cells",
        "identity_mismatches",
        "duplicate_output_paths",
    )
    matrix_complete = not any(diagnostics[key] for key in structural_keys)
    blockers = [key for key, value in diagnostics.items() if value]
    claim_ready = claim_eligibility_requested and not blockers

    rows: list[dict[str, Any]] = []
    solver_summary: list[dict[str, Any]] = []
    for solver in solvers:
        expected_solver_cells = [
            identity for identity in expected if identity["solver"] == solver
        ]
        locally_valid_solver_records = [
            locally_complete_by_id[str(identity["run_id"])]
            for identity in expected_solver_cells
            if str(identity["run_id"]) in locally_complete_by_id
        ]
        feasible_solver_cells = sum(
            row["independent_validation"]["feasible"] is True
            for row in locally_valid_solver_records
        )
        infeasible_solver_cells = sum(
            row["independent_validation"]["feasible"] is False
            for row in locally_valid_solver_records
        )
        feasibility_evidence = {
            "expected_cells": len(expected_solver_cells),
            "locally_valid_cells": len(locally_valid_solver_records),
            "feasible_cells": feasible_solver_cells,
            "infeasible_cells": infeasible_solver_cells,
            "unresolved_cells": len(expected_solver_cells)
            - len(locally_valid_solver_records),
            "complete": bool(expected_solver_cells)
            and len(locally_valid_solver_records) == len(expected_solver_cells),
        }
        local_rows = []
        descriptive_ratios = []
        claim_ratios = []
        for case in cases:
            candidates = [
                row
                for row in locally_complete_records
                if row.get("case") == case
                and row.get("solver") == solver
                and (row.get("independent_validation") or {}).get("feasible") is True
                and (row.get("independent_validation") or {})
                .get("objective", {})
                .get("total")
                is not None
            ]
            local_best = min(
                (
                    int(row["independent_validation"]["objective"]["total"])
                    for row in candidates
                ),
                default=None,
            )
            official_score = official.get(case)
            descriptive_outcome = None
            if local_best is not None and official_score is not None:
                descriptive_outcome = (
                    "better"
                    if local_best < official_score
                    else "tie"
                    if local_best == official_score
                    else "worse"
                )
                descriptive_ratios.append(
                    local_best / official_score if official_score else None
                )

            expected_group = [
                identity
                for identity in expected
                if identity["case"] == case and identity["solver"] == solver
            ]
            paired_cells = []
            paired_totals = []
            paired_deltas = []
            paired_outcomes = []
            for identity in expected_group:
                candidate = trusted_by_id.get(str(identity["run_id"]))
                validation = (
                    candidate.get("independent_validation")
                    if candidate is not None
                    else None
                )
                objective = (
                    validation.get("objective")
                    if isinstance(validation, dict)
                    and validation.get("feasible") is True
                    else None
                )
                total = objective.get("total") if isinstance(objective, dict) else None
                delta = (
                    total - official_score
                    if type(total) is int and official_score is not None
                    else None
                )
                outcome = (
                    "better"
                    if delta is not None and delta < 0
                    else "tie"
                    if delta == 0
                    else "worse"
                    if delta is not None
                    else None
                )
                paired_cells.append(
                    {
                        "run_id": identity["run_id"],
                        "seed": identity["seed"],
                        "repetition": identity["repetition"],
                        "unseeded_trial": identity["unseeded_trial"],
                        "local_total": total,
                        "official_competition_best_total": official_score,
                        "delta": delta,
                        "outcome": outcome,
                        "official_validator_agreement": None
                        if candidate is None
                        else candidate.get("official_validator_agreement"),
                    }
                )
                if type(total) is int and delta is not None and outcome is not None:
                    paired_totals.append(total)
                    paired_deltas.append(delta)
                    paired_outcomes.append(outcome)

            paired_complete = bool(expected_group) and len(paired_totals) == len(
                expected_group
            )
            comparison_eligible = bool(
                claim_ready and paired_complete and official_score is not None
            )
            claim_outcome = None
            if comparison_eligible:
                unique_outcomes = set(paired_outcomes)
                claim_outcome = (
                    paired_outcomes[0] if len(unique_outcomes) == 1 else "mixed"
                )
                if official_score:
                    claim_ratios.extend(
                        total / official_score for total in paired_totals
                    )

            paired_statistics = {
                "prespecified_cell_count": len(expected_group),
                "observed_valid_cell_count": len(paired_totals),
                "complete": paired_complete,
                "mean_total": statistics.fmean(paired_totals)
                if paired_totals
                else None,
                "median_total": statistics.median(paired_totals)
                if paired_totals
                else None,
                "mean_delta": statistics.fmean(paired_deltas)
                if paired_deltas
                else None,
                "median_delta": statistics.median(paired_deltas)
                if paired_deltas
                else None,
                "better": paired_outcomes.count("better"),
                "ties": paired_outcomes.count("tie"),
                "worse": paired_outcomes.count("worse"),
            }
            local_rows.append(
                {
                    "case": case,
                    "solver": solver,
                    "local_best_total": local_best,
                    "official_competition_best_total": official_score,
                    "delta": None
                    if local_best is None or official_score is None
                    else local_best - official_score,
                    "descriptive_outcome": descriptive_outcome,
                    "outcome": claim_outcome,
                    "comparison_eligible": comparison_eligible,
                    "paired_cells": paired_cells,
                    "paired_statistics": paired_statistics,
                    "official_validator_agreement": None
                    if not candidates
                    else all(
                        row.get("official_validator_agreement") is True
                        for row in candidates
                    ),
                }
            )
        rows.extend(local_rows)
        comparable = [row for row in local_rows if row["outcome"] is not None]
        descriptive = [
            row for row in local_rows if row["descriptive_outcome"] is not None
        ]
        solver_summary.append(
            {
                "solver": solver,
                "valid_cases": len(comparable),
                "missing_cases": len(cases) - len(comparable),
                "better": sum(row["outcome"] == "better" for row in comparable),
                "ties": sum(row["outcome"] == "tie" for row in comparable),
                "worse": sum(row["outcome"] == "worse" for row in comparable),
                "mixed": sum(row["outcome"] == "mixed" for row in comparable),
                "median_local_to_official_ratio": statistics.median(claim_ratios)
                if claim_ratios
                else None,
                "descriptive_valid_cases": len(descriptive),
                "descriptive_missing_cases": len(cases) - len(descriptive),
                "descriptive_better": sum(
                    row["descriptive_outcome"] == "better" for row in descriptive
                ),
                "descriptive_ties": sum(
                    row["descriptive_outcome"] == "tie" for row in descriptive
                ),
                "descriptive_worse": sum(
                    row["descriptive_outcome"] == "worse" for row in descriptive
                ),
                "descriptive_median_local_to_official_ratio": statistics.median(
                    [ratio for ratio in descriptive_ratios if ratio is not None]
                )
                if any(ratio is not None for ratio in descriptive_ratios)
                else None,
                "descriptive_feasibility_evidence": feasibility_evidence,
            }
        )

    direct_pairwise_comparisons = _direct_planora_pairwise_comparisons(
        expected=expected,
        validated_by_id=locally_complete_by_id,
        solvers=solvers,
        claim_ready=claim_ready,
    )

    claim_eligibility_binding = {
        "schema": "planora.itc2019.claim-eligibility-binding.v1",
        "execution_mode": (
            "claim_gate_required" if claim_eligibility_requested else "descriptive_only"
        ),
        "claim_gate_passed": claim_ready,
        "official_trust_anchor_sha256": actual_official_trust_anchor_sha256,
        "matrix_evidence_sha256": actual_matrix_evidence_sha256,
        "blockers": blockers,
    }
    return {
        "schema_version": 4,
        "kind": "planora_itc2019_open_source_comparison_summary",
        "summary_mode": {
            "mode": (
                "claim_gate_required"
                if claim_eligibility_requested
                else "descriptive_only"
            ),
            "claim_gate_enforced": claim_eligibility_requested,
            "claim_eligibility_status": (
                "eligible"
                if claim_ready
                else "ineligible"
                if claim_eligibility_requested
                else "not_evaluated_descriptive_only"
            ),
            "eligibility_binding_sha256": _sha256(
                _canonical_json_bytes(claim_eligibility_binding)
            ),
        },
        "claim_boundary": (
            "Descriptive statistics remain available for incomplete evidence. Equal-resource "
            "claim outcomes remain suppressed unless exact-cell, replicated-pairing, "
            "artifact, local-validation, official-evidence, pinned official-results, "
            "controller-profile, raw-run, and per-run resource-evidence gates "
            "pass. Best-of-run fields are descriptive only; claim outcomes summarize every "
            "prespecified cell. Descriptive-only execution suppresses eligibility and "
            "claim outcomes before serialization."
        ),
        "matrix_complete": matrix_complete,
        "claim_gate": {"passed": claim_ready, "blockers": blockers},
        "diagnostics": diagnostics,
        "planned_runs": planned,
        "recorded_runs": len(records),
        "cases": len(cases),
        "solvers": solver_summary,
        "comparisons": rows,
        "direct_planora_pairwise_comparisons": direct_pairwise_comparisons,
        "official_results_source": {
            "url": official_payload.get("url"),
            "captured_at": official_payload.get("captured_at"),
            "expected_payload_sha256": expected_official_payload_sha256,
            "actual_payload_sha256": actual_official_payload_sha256,
            "trust_anchor_mode": (
                official_trust_anchor.get("mode")
                if isinstance(official_trust_anchor, dict)
                else None
            ),
            "trust_anchor_source": official_trust_anchor_source,
            "expected_trust_anchor_sha256": expected_official_trust_anchor_sha256,
            "actual_trust_anchor_sha256": actual_official_trust_anchor_sha256,
            "actual_matrix_evidence_sha256": actual_matrix_evidence_sha256,
            "external_authenticity_unproven": external_authenticity_unproven,
            "integrity_scope": (
                "Claim eligibility requires a separately pinned canonical anchor bound "
                "to the exact official payload and the immutable controller/raw-run "
                "evidence set. The anchor does not by itself prove benchmark quality or "
                "performance superiority."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--official-results", type=Path, required=True)
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument(
        "--official-trust-anchor",
        type=Path,
        help=(
            "canonical v2 anchor binding the official payload to immutable "
            "controller and raw-run evidence"
        ),
    )
    parser.add_argument(
        "--expected-official-trust-anchor-sha256",
        help=(
            "independently pinned SHA-256 of the exact canonical trust-anchor bytes; "
            "required for claim eligibility"
        ),
    )
    parser.add_argument(
        "--expected-official-payload-sha256",
        help="local-integrity check only; never an external authenticity proof",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--descriptive-only",
        action="store_true",
        help=(
            "write diagnostics and return zero even when the claim gate fails; "
            "the output is explicitly marked descriptive-only"
        ),
    )
    args = parser.parse_args()
    official_payload_bytes = args.official_results.read_bytes()
    trust_anchor_bytes = (
        args.official_trust_anchor.read_bytes()
        if args.official_trust_anchor is not None
        else None
    )
    trust_anchor: Any = None
    if trust_anchor_bytes is not None:
        try:
            trust_anchor = json.loads(trust_anchor_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            trust_anchor = None
    summary = summarize(
        json.loads(args.report.read_text(encoding="utf-8")),
        json.loads(official_payload_bytes),
        claim_eligibility_requested=not args.descriptive_only,
        matrix_root=args.matrix_root,
        expected_official_payload_sha256=args.expected_official_payload_sha256,
        official_payload_bytes=official_payload_bytes,
        official_trust_anchor=trust_anchor,
        official_trust_anchor_bytes=trust_anchor_bytes,
        expected_official_trust_anchor_sha256=(
            args.expected_official_trust_anchor_sha256
        ),
        official_trust_anchor_source=(
            _OFFICIAL_TRUST_ANCHOR_SOURCE
            if args.expected_official_trust_anchor_sha256 is not None
            else None
        ),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.descriptive_only:
        return 0
    return 0 if summary["claim_gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
