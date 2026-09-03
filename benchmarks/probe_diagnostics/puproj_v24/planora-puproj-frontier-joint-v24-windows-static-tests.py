#!/usr/bin/env python3
"""Windows-safe, no-solver verification for the PU-PROJ v24 chain."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import sys
import tracemalloc

from ortools.sat.python import cp_model


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).resolve().parent
BUILD_SCRIPT = ROOT / "scripts/build_puproj_v24_chain.ps1"
MANIFEST = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-freeze.json"
RUNNER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-runner.py"
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-supervisor.py"
LAUNCHER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-launcher.py"
GENERIC_VALIDATOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-generic-validator.py"
STDLIB_MANIFEST = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v24-stdlib.sha256"
DECOMPOSED = ROOT / "benchmarks/itc2019_decomposed.py"
DECOMPOSED_TESTS = ROOT / "tests/test_itc2019_decomposed_extended_budget.py"
SHARED_CORE_RECEIPT = (
    ROOT
    / "output/diagnostic-receipts/"
    "shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.receipt.json"
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"missing literal assignment {name} in {path.name}")


def literal_dict_value(path: Path, assignment: str, key: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == assignment for target in node.targets):
            continue
        assert isinstance(node.value, ast.Dict)
        for key_node, value_node in zip(node.value.keys, node.value.values, strict=True):
            if ast.literal_eval(key_node) == key:
                return ast.literal_eval(value_node)
    raise AssertionError(f"missing literal dictionary value {assignment}[{key!r}] in {path.name}")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "planora.pu-proj.frontier-joint-v24-freeze.v1"
    assert manifest["verdict"] == "GO_FOR_WINDOWS_STATIC_REVIEW_ONLY_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
    assert manifest["scope"] == (
        "PU-PROJ v24 corrected semantics-preserving bounded decomposed model "
        "construction under exact unchanged v22 caps"
    )
    assert manifest["verification"]["sealed_import_probe"] == "NOT_RUN"
    assert manifest["verification"]["official_solution_published"] is False
    assert manifest["verification"]["official_launch_authorized"] is False
    assert manifest["verification"]["no_solver_probe_authorized"] is False

    derivation = manifest["derivation"]
    assert derivation["schema"] == "planora.pu-proj.frontier-joint-v24-derivation.v1"
    assert derivation["generated_artifact_version"] == "v24"
    assert digest(BUILD_SCRIPT) == derivation["builder_sha256"]
    assert derivation["template_builder_sha256"] == (
        "c7026ca34017d0f2cd2a2f7684a62767ca22f5e979796d9e35624c2da86681bd"
    )

    rejected = manifest["rejected_predecessor"]
    assert rejected["schema"] == "planora.pu-proj.frontier-joint-v24-rejected-predecessor.v1"
    assert rejected["version"] == "v23"
    assert rejected["static_review_verdict"] == "NO_GO"
    assert rejected["retained_no_solver_probe_ran"] is False
    assert rejected["official_launch_ran"] is False
    assert rejected["official_launch_authorized"] is False
    assert "empty forbidden tables changed protobuf structure" in rejected["reason"]

    controls = manifest["control_plane"]
    assert digest(RUNNER) == controls["runner"]["sha256"]
    assert digest(SUPERVISOR) == controls["supervisor"]["sha256"]
    assert digest(LAUNCHER) == controls["launcher"]["sha256"]
    assert literal_assignment(SUPERVISOR, "EXPECTED_RUNNER_SHA256") == digest(RUNNER)
    assert literal_assignment(LAUNCHER, "EXPECTED_SUPERVISOR_SHA256") == digest(SUPERVISOR)
    assert digest(DECOMPOSED) == manifest["source_closure"]["itc2019_decomposed_sha256"]
    assert digest(DECOMPOSED_TESTS) == manifest["source_closure"]["decomposed_focused_test_sha256"]
    assert digest(SHARED_CORE_RECEIPT) == manifest["source_closure"]["shared_core_test_receipt_sha256"]
    receipt = json.loads(SHARED_CORE_RECEIPT.read_text(encoding="utf-8"))
    assert receipt["decision"] == "PASS"
    assert receipt["shared_core"]["sha256"] == digest(DECOMPOSED)
    assert receipt["focused_test_source"]["sha256"] == digest(DECOMPOSED_TESTS)
    assert receipt["reviewer_boundary_fix"]["focused_tests"] == "17_PASS"
    assert receipt["scope"]["passed"] == 457
    assert receipt["scope"]["skipped"] == 2
    assert receipt["scope"]["failures"] == 0
    assert receipt["scope"]["errors"] == 0
    assert literal_dict_value(RUNNER, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)
    assert literal_dict_value(SUPERVISOR, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)
    assert digest(GENERIC_VALIDATOR) == manifest["reused_runtime"]["generic_validator"]["sha256"]
    assert digest(STDLIB_MANIFEST) == manifest["reused_runtime"]["stdlib_manifest"]["sha256"]

    generated = tuple(path for path in ARTIFACT_ROOT.iterdir() if path.is_file())
    assert len(generated) == 7
    assert all("v23" not in path.name for path in generated)
    assert all("v24" in path.name for path in generated)
    for source in (RUNNER, SUPERVISOR, LAUNCHER):
        source_text = source.read_text(encoding="utf-8")
        assert "puproj_v23" not in source_text
        assert "frontier-joint-v23" not in source_text

    for source in (RUNNER, SUPERVISOR, LAUNCHER, DECOMPOSED, Path(__file__)):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")

    expected_caps = {
        "PROCESS_GROUP_RSS_LIMIT_KIB": 1_550_000,
        "PROCESS_GROUP_VMSWAP_LIMIT_KIB": 131_072,
        "WHOLE_LAUNCH_MEMORY_LIMIT_KIB": 1_600_000,
        "RUNTIME_MIN_MEM_AVAILABLE_KIB": 450_000,
        "ADDRESS_SPACE_CAP_BYTES": 2_800_000_000,
        "CHILD_ACCEPTANCE_COOPERATIVE_DEADLINE_SECONDS": 300.0,
        "SUPERVISOR_HARD_WALL_SECONDS": 330.0,
    }
    for name, expected in expected_caps.items():
        assert literal_assignment(SUPERVISOR, name) == expected
    assert manifest["resource_contract"] == {
        "process_group_rss_limit_kib": 1_550_000,
        "process_group_vmswap_limit_kib": 131_072,
        "whole_launch_vmrss_plus_vmswap_limit_kib": 1_600_000,
        "runtime_memavailable_floor_kib": 450_000,
        "address_space_cap_bytes": 2_800_000_000,
        "child_deadline_seconds": 300.0,
        "supervisor_wall_seconds": 330.0,
    }

    sys.path.insert(0, str(ROOT))
    from benchmarks.itc2019_decomposed import (
        _BoundedPredicateCache,
        _add_streamed_forbidden_assignments,
        _build_compact_allowed_option_masks,
        _iter_forbidden_option_pairs,
    )

    first_size = 17
    second_size = 19
    predicate = lambda first, second: (first * 7 + second * 5) % 11 not in {0, 3}
    legacy_rows = tuple(
        sum(1 << second for second in range(second_size) if predicate(first, second))
        for first in range(first_size)
    )
    compact_rows = _build_compact_allowed_option_masks(
        first_size,
        second_size,
        predicate,
        deadline=1.0,
        clock=lambda: 0.0,
    )
    assert compact_rows == legacy_rows

    legacy_forbidden = [
        (first, second)
        for first, allowed in enumerate(legacy_rows)
        for second in range(second_size)
        if not allowed & (1 << second)
    ]
    streamed_forbidden = _iter_forbidden_option_pairs(
        compact_rows,
        second_size,
        deadline=1.0,
        clock=lambda: 0.0,
    )

    def model_text(forbidden, streamed: bool) -> str:
        model = cp_model.CpModel()
        first = model.new_int_var(0, first_size - 1, "first")
        second = model.new_int_var(0, second_size - 1, "second")
        if streamed:
            _add_streamed_forbidden_assignments(model, (first, second), forbidden)
        else:
            model.add_forbidden_assignments((first, second), forbidden)
        return str(model.proto)

    assert model_text(streamed_forbidden, True) == model_text(legacy_forbidden, False)

    empty_model = cp_model.CpModel()
    empty_first = empty_model.new_int_var(0, 2, "empty_first")
    empty_second = empty_model.new_int_var(0, 3, "empty_second")
    assert _add_streamed_forbidden_assignments(
        empty_model, (empty_first, empty_second), iter(())
    ) is True
    legacy_empty_model = cp_model.CpModel()
    legacy_empty_first = legacy_empty_model.new_int_var(0, 2, "empty_first")
    legacy_empty_second = legacy_empty_model.new_int_var(0, 3, "empty_second")
    legacy_empty_model.add_forbidden_assignments(
        (legacy_empty_first, legacy_empty_second), []
    )
    assert str(empty_model.proto) == str(legacy_empty_model.proto)

    cache = _BoundedPredicateCache(max_entries=5)
    for value in range(50):
        assert cache.resolve(value, lambda value=value: value % 2 == 0) is (value % 2 == 0)
        assert len(cache) <= 5

    tracemalloc.start()
    try:
        large_rows = _build_compact_allowed_option_masks(
            512,
            512,
            lambda first, second: (first + second) % 3 == 0,
            deadline=1.0,
            clock=lambda: 0.0,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(large_rows) == 512
    assert peak < 1_000_000

    try:
        _build_compact_allowed_option_masks(
            1,
            1,
            lambda _first, _second: True,
            deadline=0.0,
            clock=lambda: 0.0,
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("expired compact construction did not fail closed")

    print("PU-PROJ v24 Windows-safe static tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())