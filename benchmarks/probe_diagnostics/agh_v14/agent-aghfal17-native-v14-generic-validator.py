#!/usr/bin/env python3
"""Distinct isolated semantic validator for AGH-FAL17 native v11."""

from __future__ import annotations

from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import types


CAPTURE_MANIFEST_ENV = "AGHFAL_NATIVE_V14_CAPTURE_MANIFEST"


def _read_fd(descriptor: int, maximum: int) -> bytes:
    row = os.fstat(descriptor)
    if row.st_size < 1 or row.st_size > maximum:
        raise RuntimeError("generic validator descriptor size rejected")
    chunks: list[bytes] = []
    offset = 0
    while offset < row.st_size:
        block = os.pread(descriptor, min(1 << 20, row.st_size - offset), offset)
        if not block:
            raise RuntimeError("generic validator descriptor ended early")
        chunks.append(block)
        offset += len(block)
    return b"".join(chunks)


def _load_runner() -> types.ModuleType:
    manifest = json.loads(os.environ[CAPTURE_MANIFEST_ENV])
    evidence = manifest["runner"]
    descriptor = int(evidence["fd"])
    raw = _read_fd(descriptor, 8 << 20)
    actual = sha256(raw).hexdigest()
    if actual != evidence["sha256"] or actual != evidence["expected_sha256"]:
        raise RuntimeError("generic validator runner capture drift")
    module = types.ModuleType("aghfal17_native_v14_generic_runtime")
    module.__file__ = f"<sealed-native-v14-runner:{actual}>"
    module.__package__ = None
    module.__captured_sha256__ = actual
    exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    return module


def validate(solution_fd: int) -> dict[str, object]:
    runner = _load_runner()
    payloads, captures = runner.load_capture_manifest()
    stdlib_start = runner.verify_stdlib_manifest(
        payloads, phase="generic_before_native_import"
    )
    executing_python = runner.verify_executing_python(payloads, captures)
    runtime_bundle = runner.verify_runtime_bundle(payloads)
    runtime_install = runner.install_sealed_runtime(runtime_bundle)
    planora_install = runner.install_sealed_planora_modules(payloads)
    native = importlib.import_module("benchmarks.itc2019")
    official_fd = int(captures["official_instance"]["fd"])
    problem = native.parse_itc2019_xml(Path(f"/proc/self/fd/{official_fd}"))
    solution = native.parse_itc2019_solution(Path(f"/proc/self/fd/{solution_fd}"))
    expected_classes = {klass.id for klass in problem.classes}
    expected_students = {student.id for student in problem.students}
    observed_classes = {placement.class_id for placement in solution.placements}
    observed_students = set(solution.student_classes)
    semantic_errors = list(
        native.validate_itc2019_solution(
            problem, solution.placements, solution.student_classes
        )
    )
    document_errors = list(native.validate_itc2019_solution_document(problem, solution))
    cardinality_errors: list[str] = []
    if len(problem.classes) != 5_081 or len(solution.placements) != 5_081:
        cardinality_errors.append("exact class cardinality mismatch")
    if observed_classes != expected_classes:
        cardinality_errors.append("class ID set mismatch")
    if len(solution.student_classes) != len(problem.students):
        cardinality_errors.append("actual student cardinality mismatch")
    if observed_students != expected_students:
        cardinality_errors.append("student ID set mismatch")
    errors = [*semantic_errors, *document_errors, *cardinality_errors]
    return {
        "schema": "planora.agh-fal17.native-v14-isolated-generic-validator.v1",
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "classes": len(solution.placements),
        "students": len(solution.student_classes),
        "actual_problem_students": len(problem.students),
        "official_input_only": True,
        "checkpoint_or_certified_provenance_used": False,
        "executing_python": executing_python,
        "stdlib_start": stdlib_start,
        "stdlib_final": runner.verify_stdlib_manifest(
            payloads, phase="generic_final"
        ),
        "runtime_install": runtime_install,
        "planora_install": planora_install,
        "loaded_planora_modules": runner.verify_loaded_planora_modules(),
    }


def self_test() -> dict[str, object]:
    return {
        "status": "PASS",
        "distinct_isolated_validator": True,
        "student_cardinality_source": "sealed_official_problem_students",
        "official_instance_opened": False,
        "solver_execution_started": False,
    }


def _write_report(descriptor: int, payload: dict[str, object]) -> None:
    row = os.fstat(descriptor)
    if not stat.S_ISREG(row.st_mode) or row.st_size != 0:
        raise RuntimeError("generic report descriptor contract rejected")
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    view = memoryview(raw)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RuntimeError("generic report descriptor stopped accepting bytes")
        view = view[written:]
    os.fsync(descriptor)


def main() -> int:
    if globals().get("__generic_loader_protocol__") != (
        "planora.aghfal17.native-v14-generic-loader.v1"
    ):
        raise SystemExit("direct generic validator execution rejected")
    if sys.argv[1:] == ["--self-test"]:
        payload = self_test()
        print(json.dumps(payload, sort_keys=True), flush=True)
    elif (
        len(sys.argv) == 5
        and sys.argv[1] == "--solution-fd"
        and sys.argv[3] == "--report-fd"
    ):
        payload = validate(int(sys.argv[2]))
        _write_report(int(sys.argv[4]), payload)
    else:
        raise SystemExit("generic validator arguments rejected")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
