#!/usr/bin/env python3
"""Fresh-process semantic/document validation for one ITC-2019 solution."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import sys
import time


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.itc2019 import (  # noqa: E402
    parse_itc2019_solution,
    parse_itc2019_xml,
    score_itc2019_solution,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
)


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    instance = args.instance.resolve()
    solution_path = args.solution.resolve()
    validator_path = ROOT / "benchmarks/itc2019.py"
    payload = {
        "schema": "planora.itc2019.independent-validation.v10",
        "status": "FAILED",
        "instance_path": str(instance),
        "instance_sha256": digest(instance),
        "solution_path": str(solution_path),
        "solution_sha256": digest(solution_path),
        "validator_path": str(validator_path),
        "validator_sha256": digest(validator_path),
    }
    try:
        if (
            args.expected_instance_sha256
            and payload["instance_sha256"] != args.expected_instance_sha256
        ):
            raise RuntimeError("instance hash drift")
        if (
            args.expected_solution_sha256
            and payload["solution_sha256"] != args.expected_solution_sha256
        ):
            raise RuntimeError("solution hash drift")
        problem = parse_itc2019_xml(instance)
        solution = parse_itc2019_solution(solution_path)
        semantic_errors = validate_itc2019_solution(
            problem, solution.placements, solution.student_classes
        )
        document_errors = validate_itc2019_solution_document(problem, solution)
        score = score_itc2019_solution(
            problem, solution.placements, solution.student_classes
        )
        expected_classes = len(problem.classes)
        expected_students = len(problem.students)
        cardinality_errors = []
        if len(solution.placements) != expected_classes:
            cardinality_errors.append(
                f"placements {len(solution.placements)} != {expected_classes}"
            )
        if len(solution.student_classes) != expected_students:
            cardinality_errors.append(
                "student assignments "
                f"{len(solution.student_classes)} != {expected_students}"
            )
        payload.update(
            instance_name=problem.name,
            expected_placements=expected_classes,
            placements=len(solution.placements),
            expected_students=expected_students,
            students=len(solution.student_classes),
            semantic_errors=list(semantic_errors),
            document_errors=list(document_errors),
            cardinality_errors=cardinality_errors,
            score={
                "time": score.time,
                "room": score.room,
                "distribution": score.distribution,
                "student": score.student,
                "total": score.total,
            },
        )
        if semantic_errors or document_errors or cardinality_errors:
            raise RuntimeError("validation errors")
        payload["status"] = "COMPLETE_VALID"
    except Exception as exc:
        payload.update(error_type=type(exc).__name__, error=str(exc))
    payload["elapsed_seconds"] = time.monotonic() - started
    payload["peak_rss_kb"] = int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    )
    report_bytes = (
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    offset = 0
    while offset < len(report_bytes):
        written = os.write(args.report_fd, report_bytes[offset:])
        if written <= 0:
            raise RuntimeError("inherited report descriptor stopped accepting bytes")
        offset += written
    os.fsync(args.report_fd)
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    parser.add_argument("--report-fd", type=int, required=True)
    parser.add_argument("--expected-instance-sha256")
    parser.add_argument("--expected-solution-sha256")
    args = parser.parse_args()
    return 0 if run(args)["status"] == "COMPLETE_VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
