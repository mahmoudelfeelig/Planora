#!/usr/bin/env python3
"""Windows-safe, no-solver verification for the PU-PROJ v23 chain."""

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
MANIFEST = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-freeze.json"
RUNNER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-runner.py"
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-supervisor.py"
LAUNCHER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v23-launcher.py"
DECOMPOSED = ROOT / "benchmarks/itc2019_decomposed.py"


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
    assert manifest["verdict"] == "GO_FOR_WINDOWS_STATIC_REVIEW_ONLY_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
    assert manifest["verification"]["sealed_import_probe"] == "NOT_RUN"
    assert manifest["verification"]["official_solution_published"] is False
    assert manifest["verification"]["official_launch_authorized"] is False

    controls = manifest["control_plane"]
    assert digest(RUNNER) == controls["runner"]["sha256"]
    assert digest(SUPERVISOR) == controls["supervisor"]["sha256"]
    assert digest(LAUNCHER) == controls["launcher"]["sha256"]
    assert literal_assignment(SUPERVISOR, "EXPECTED_RUNNER_SHA256") == digest(RUNNER)
    assert literal_assignment(LAUNCHER, "EXPECTED_SUPERVISOR_SHA256") == digest(SUPERVISOR)
    assert digest(DECOMPOSED) == manifest["source_closure"]["itc2019_decomposed_sha256"]
    assert literal_dict_value(RUNNER, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)
    assert literal_dict_value(SUPERVISOR, "EXPECTED_HASHES", "itc2019_decomposed") == digest(DECOMPOSED)

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

    print("PU-PROJ v23 Windows-safe static tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())