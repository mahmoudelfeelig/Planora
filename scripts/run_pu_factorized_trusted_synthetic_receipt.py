from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "planora.itc2019.pu-factorized-trusted-synthetic-e2e.v1"
CLAIM_SCHEMA = "planora.itc2019.pu-factorized-trusted-synthetic-claim.v1"
RUN_ID = "pu-factorized-trusted-synthetic-e2e-6cd00de292d8"
SCRIPT_PATH = Path(__file__).resolve()
RECEIPT_PATH = ROOT / "output" / "diagnostic-receipts" / f"{RUN_ID}.receipt.json"
CLAIM_PATH = RECEIPT_PATH.with_suffix(".claim.json")
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
    "benchmarks/itc2019_timetable_factorized_pipeline.py": (
        "3ead77d8542f31c283b3aecea47582f14d38af8248ec73ac3557fab12a9f18e7"
    ),
    "tests/test_itc2019_timetable_factorized_pipeline.py": (
        "a90af0b84176959e9391b3b94a5008cece48238fbc14420608481d6946a16bab"
    ),
    "tests/test_itc2019_timetable_factorized.py": (
        "389f2c6d44b5e8715d6b302c08c9d692f645cf81febfd90e84d5b4897ffaf78b"
    ),
    "tests/test_run_pu_factorized_trusted_synthetic_receipt.py": (
        "9e1fa9aef58d788c5c13b2703d9da7237afed09be04240de9556c932681e529e"
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _publish_bytes_create_only(path: Path, encoded: bytes) -> None:
    """Durably stage bytes, then atomically publish without replacing a peer."""
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


def _observe_sources() -> dict[str, str]:
    return {relative: _sha256(ROOT / relative) for relative in EXPECTED_SOURCE_SHA256}


def _require_reviewed_sources() -> dict[str, str]:
    observed = _observe_sources()
    if observed != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("reviewed source hash drift; experiment was not run")
    return observed


def _error_type(error: BaseException) -> str:
    error_class = type(error)
    return f"{error_class.__module__}.{error_class.__qualname__}"


def _publish_post_claim_error(
    *,
    claim_sha256: str,
    script_sha256: str,
    started_at: datetime,
    error: BaseException,
) -> None:
    if RECEIPT_PATH.exists():
        return
    try:
        postflight_sources = _observe_sources()
        postflight_script_sha256 = _sha256(SCRIPT_PATH)
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "run_id": RUN_ID,
            "outcome": "ERROR",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "started_at_utc": started_at.isoformat(),
            "script_path": str(SCRIPT_PATH),
            "script_sha256": script_sha256,
            "postflight_script_sha256": postflight_script_sha256,
            "postflight_script_match": postflight_script_sha256 == script_sha256,
            "claim_path": str(CLAIM_PATH),
            "claim_sha256": claim_sha256,
            "reviewed_source_sha256": postflight_sources,
            "postflight_source_match": postflight_sources == EXPECTED_SOURCE_SHA256,
            "error": {"type": _error_type(error)},
            "scope": {
                "official_input_used": False,
                "official_solve_used": False,
                "performance_claim_authorized": False,
                "quality_claim_authorized": False,
                "official_dispatch_authorized": False,
            },
        }
        _publish_json_create_only(RECEIPT_PATH, payload)
    except BaseException:
        if RECEIPT_PATH.exists():
            return
        fallback = (
            "{\n"
            f'  "schema": "{SCHEMA}",\n'
            f'  "run_id": "{RUN_ID}",\n'
            '  "outcome": "ERROR",\n'
            '  "error": {"type": "receipt-finalization-failure"}\n'
            "}\n"
        ).encode("ascii")
        _publish_bytes_create_only(RECEIPT_PATH, fallback)


def _input_spec() -> dict[str, object]:
    return {
        "name": "pu-factorized-reviewed-e2e",
        "source_path": "synthetic://pu-factorized-reviewed-e2e",
        "calendar": {"nr_days": 1, "slots_per_day": 4, "nr_weeks": 1},
        "rooms": [{"id": "R1", "capacity": 10}],
        "courses": [
            {
                "id": "COURSE1",
                "configurations": [
                    {
                        "id": "CONFIG1",
                        "subparts": [
                            {
                                "id": "SUBPART1",
                                "classes": [
                                    {
                                        "id": "C1",
                                        "limit": 10,
                                        "days": "1",
                                        "start": 0,
                                        "length": 1,
                                        "weeks": "1",
                                        "room": "R1",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "students": [{"id": "S1", "courses": ["COURSE1"]}],
        "distributions": [],
    }


def _problem() -> object:
    from benchmarks.itc2019 import (
        ITC2019Class,
        ITC2019Configuration,
        ITC2019Course,
        ITC2019OptimizationWeights,
        ITC2019Problem,
        ITC2019Room,
        ITC2019RoomOption,
        ITC2019Student,
        ITC2019Subpart,
        ITC2019TimeOption,
    )

    klass = ITC2019Class(
        id="C1",
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=(ITC2019TimeOption("1", 0, 1, "1"),),
        room_options=(ITC2019RoomOption("R1"),),
    )
    return ITC2019Problem(
        name="pu-factorized-reviewed-e2e",
        nr_days=1,
        slots_per_day=4,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=(ITC2019Room(id="R1", capacity=10, travel=(), unavailable=()),),
        courses=(
            ITC2019Course(
                id="COURSE1",
                configurations=(
                    ITC2019Configuration(
                        id="CONFIG1",
                        subparts=(ITC2019Subpart(id="SUBPART1", classes=(klass,)),),
                    ),
                ),
            ),
        ),
        distributions=(),
        students=(ITC2019Student("S1", ("COURSE1",)),),
        source_path="synthetic://pu-factorized-reviewed-e2e",
    )


def _limits() -> object:
    from benchmarks.itc2019_timetable_factorized import (
        ITC2019TimetableFactorizedLimits,
    )
    from benchmarks.itc2019_timetable_factorized_pipeline import (
        ITC2019TimetableFactorizedPipelineLimits,
    )

    return ITC2019TimetableFactorizedPipelineLimits(
        timetable_build_time_limit_seconds=1.25,
        timetable_solve_time_limit_seconds=2.5,
        sectioning_time_limit_seconds=3.75,
        timetable_random_seed=17,
        sectioning_random_seed=23,
        timetable_construction=ITC2019TimetableFactorizedLimits(
            max_domain_values=100,
            max_required_pair_relations=100,
            max_sparse_room_constraints=100,
            max_room_pair_evaluations=100,
        ),
        sectioning_max_conflict_pairs=101,
        sectioning_max_conflict_terms=102,
        max_classes=10,
        max_students=20,
        max_course_requests=30,
    )


def main() -> int:
    observed_sources = _require_reviewed_sources()
    script_sha256 = _sha256(SCRIPT_PATH)
    started_at = datetime.now(timezone.utc)
    claim = {
        "schema": CLAIM_SCHEMA,
        "run_id": RUN_ID,
        "claimed_at_utc": started_at.isoformat(),
        "pid": os.getpid(),
        "script_path": str(SCRIPT_PATH),
        "script_sha256": script_sha256,
        "reviewed_source_sha256": observed_sources,
    }
    claim_encoded = _encode_json(claim)
    claim_sha256 = hashlib.sha256(claim_encoded).hexdigest()
    _publish_bytes_create_only(CLAIM_PATH, claim_encoded)

    try:
        if _sha256(CLAIM_PATH) != claim_sha256:
            raise RuntimeError("published claim hash mismatch")
        from benchmarks.itc2019_timetable_factorized_pipeline import (
            run_itc2019_timetable_factorized_pipeline,
        )

        spec = _input_spec()
        limits = _limits()
        result = run_itc2019_timetable_factorized_pipeline(
            _problem(),
            build_only=False,
            trusted_synthetic=True,
            limits=limits,
        )
        completed_at = datetime.now(timezone.utc)
        if not result.has_complete_candidate:
            raise RuntimeError(
                "trusted-synthetic pipeline did not produce an independently "
                "validated candidate"
            )
        if (
            result.status != "COMPLETE"
            or result.timetable_status != "FEASIBLE"
            or result.timetable_solver_status != "OPTIMAL"
            or result.sectioning_status != "OPTIMAL"
            or result.validation_status != "PASSED"
            or result.timetable_validation_status != "PASSED"
            or result.final_validation_status != "PASSED"
            or len(result.placements) != 1
            or dict(result.student_classes) != {"S1": ("C1",)}
            or result.validation_errors
            or result.execution_errors
        ):
            raise RuntimeError(
                "trusted-synthetic result violated the reviewed success contract"
            )

        candidate = {
            "placements": [asdict(item) for item in result.placements],
            "student_classes": {
                student: list(classes)
                for student, classes in sorted(result.student_classes.items())
            },
        }
        postflight_sources = _require_reviewed_sources()
        if _sha256(SCRIPT_PATH) != script_sha256:
            raise RuntimeError("runner source changed during the experiment")
        receipt = {
            "schema": SCHEMA,
            "run_id": RUN_ID,
            "outcome": "SUCCESS",
            "created_at_utc": completed_at.isoformat(),
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "script_path": str(SCRIPT_PATH),
            "script_sha256": script_sha256,
            "claim_path": str(CLAIM_PATH),
            "claim_sha256": claim_sha256,
            "reviewed_source_sha256": postflight_sources,
            "review_gate": {
                "verdict": "GO_FOR_ONE_TRUSTED_SYNTHETIC_EXPERIMENT",
                "pipeline_sha256": EXPECTED_SOURCE_SHA256[
                    "benchmarks/itc2019_timetable_factorized_pipeline.py"
                ],
                "pipeline_tests_sha256": EXPECTED_SOURCE_SHA256[
                    "tests/test_itc2019_timetable_factorized_pipeline.py"
                ],
                "timetable_tests_sha256": EXPECTED_SOURCE_SHA256[
                    "tests/test_itc2019_timetable_factorized.py"
                ],
                "timetable_tests_passed": 65,
                "pipeline_tests_passed": 90,
                "combined_tests_passed": 155,
                "independent_adversarial_probe_evidence": (
                    "NOT_BOUND_TO_A_WORKSPACE_ARTIFACT_NOT_USED_FOR_AUTHORIZATION"
                ),
            },
            "input": spec,
            "input_sha256": _json_sha256(spec),
            "limits": asdict(limits),
            "result": {
                "status": result.status,
                "build_only": result.build_only,
                "trusted_synthetic": result.trusted_synthetic,
                "timetable_status": result.timetable_status,
                "timetable_solver_status": result.timetable_solver_status,
                "sectioning_status": result.sectioning_status,
                "validation_status": result.validation_status,
                "timetable_validation_status": result.timetable_validation_status,
                "final_validation_status": result.final_validation_status,
                "has_complete_candidate": result.has_complete_candidate,
                "unsupported_reasons": list(result.unsupported_reasons),
                "timetable_validation_errors": list(result.timetable_validation_errors),
                "sectioning_validation_errors": list(
                    result.sectioning_validation_errors
                ),
                "final_validation_errors": list(result.final_validation_errors),
                "execution_errors": list(result.execution_errors),
                "candidate": candidate,
                "candidate_sha256": _json_sha256(candidate),
                "timetable_telemetry": (
                    asdict(result.timetable_telemetry)
                    if result.timetable_telemetry is not None
                    else None
                ),
                "budget_telemetry": asdict(result.budget_telemetry),
            },
            "scope": {
                "official_input_used": False,
                "official_solve_used": False,
                "performance_claim_authorized": False,
                "quality_claim_authorized": False,
                "official_dispatch_authorized": False,
            },
        }
        _publish_json_create_only(RECEIPT_PATH, receipt)
    except BaseException as error:
        _publish_post_claim_error(
            claim_sha256=claim_sha256,
            script_sha256=script_sha256,
            started_at=started_at,
            error=error,
        )
        raise

    print(
        json.dumps(
            {
                "receipt": str(RECEIPT_PATH),
                "receipt_sha256": _sha256(RECEIPT_PATH),
                "status": result.status,
                "validation_status": result.validation_status,
                "candidate_sha256": receipt["result"]["candidate_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
