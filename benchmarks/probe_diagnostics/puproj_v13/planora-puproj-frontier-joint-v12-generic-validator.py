#!/usr/bin/env python3
"""Isolated generic validator for a fresh PU-PROJ solution."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from benchmarks.itc2019 import (
    parse_itc2019_solution,
    parse_itc2019_xml,
    score_itc2019_solution,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
)


EXPECTED_CLASSES = 8_813
EXPECTED_STUDENTS = 38_437


def _read_stable_fd(source_fd: int, expected: str) -> bytes:
    descriptor = os.dup(source_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("validator input is not regular")
        output: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise RuntimeError("validator input ended early")
            output.append(block)
            offset += len(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda row: (
        row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns
    )
    value = b"".join(output)
    if identity(before) != identity(after) or sha256(value).hexdigest() != expected:
        raise RuntimeError("validator input identity/hash drift")
    return value


def run(args: argparse.Namespace) -> dict[str, object]:
    instance = _read_stable_fd(args.instance_fd, args.expected_instance_sha256)
    solution = _read_stable_fd(args.solution_fd, args.expected_solution_sha256)
    problem = parse_itc2019_xml(f"/proc/self/fd/{args.instance_fd}")
    parsed = parse_itc2019_solution(f"/proc/self/fd/{args.solution_fd}")
    semantic = tuple(
        validate_itc2019_solution(problem, parsed.placements, parsed.student_classes)
    )
    document = tuple(validate_itc2019_solution_document(problem, parsed))
    cardinality = []
    if len(problem.classes) != EXPECTED_CLASSES or len(parsed.placements) != EXPECTED_CLASSES:
        cardinality.append("class cardinality mismatch")
    if len(problem.students) != EXPECTED_STUDENTS or len(parsed.student_classes) != EXPECTED_STUDENTS:
        cardinality.append("student cardinality mismatch")
    complete = not semantic and not document and not cardinality
    del instance, solution
    return {
        "schema": "planora.pu-proj.frontier-joint-v12.generic-validation.v1",
        "status": "COMPLETE_VALID" if complete else "REJECTED",
        "complete_timetable": complete,
        "instance_sha256": args.expected_instance_sha256,
        "solution_sha256": args.expected_solution_sha256,
        "classes": len(parsed.placements),
        "students": len(parsed.student_classes),
        "semantic_errors": list(semantic),
        "document_errors": list(document),
        "cardinality_errors": cardinality,
        "score": score_itc2019_solution(
            problem, parsed.placements, parsed.student_classes
        ).to_dict() if complete else None,
        "checkpoint_or_incumbent_accessed": False,
        "competitor_schedule_or_result_used": False,
        "competitor_placement_or_hint_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    parser.add_argument("--instance-fd", type=int, required=True)
    parser.add_argument("--solution-fd", type=int, required=True)
    parser.add_argument("--expected-instance-sha256", required=True)
    parser.add_argument("--expected-solution-sha256", required=True)
    parser.add_argument("--report-fd", type=int, required=True)
    args = parser.parse_args()
    payload = run(args)
    report_bytes = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    offset = 0
    while offset < len(report_bytes):
        written = os.write(args.report_fd, report_bytes[offset:])
        if written <= 0:
            raise RuntimeError("inherited report descriptor stopped accepting bytes")
        offset += written
    os.fsync(args.report_fd)
    return 0 if payload["status"] == "COMPLETE_VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
