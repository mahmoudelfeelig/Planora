#!/usr/bin/env python3
"""Focused no-solver checks for PU-PROJ v22 live-RSS finalization."""

from __future__ import annotations

import ast
import ctypes
from dataclasses import dataclass, fields, is_dataclass
import gc
from pathlib import Path
import resource
from types import SimpleNamespace
import time
from typing import Any


ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
RUNNER = ROOT / "benchmarks/probe_diagnostics/puproj_v22/planora-puproj-frontier-joint-v22-runner.py"


def load_guard_namespace() -> dict[str, object]:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    names = {
        "RUNNER_RSS_CEILING_KIB",
        "_lightweight_result_telemetry",
        "_parse_self_status_rss_kib",
        "_current_self_rss_kib",
        "_release_unused_heap",
        "_resource_guard",
    }
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in names for target in targets):
                selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {
        "ctypes": ctypes,
        "fields": fields,
        "gc": gc,
        "is_dataclass": is_dataclass,
        "Path": Path,
        "resource": resource,
        "time": time,
        "Any": Any,
        "LIBC": ctypes.CDLL(None, use_errno=True),
    }
    exec(compile(module, str(RUNNER), "exec"), namespace)
    return namespace


def expect(exception_type, callback) -> None:
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"expected {exception_type.__name__}")


def main() -> int:
    namespace = load_guard_namespace()
    @dataclass
    class Objective:
        total: int

    @dataclass
    class Result:
        status: str
        placements: object
        student_classes: object
        objective: Objective

    telemetry = namespace["_lightweight_result_telemetry"](
        Result("FEASIBLE", object(), object(), Objective(7))
    )
    assert telemetry == {"status": "FEASIBLE", "objective": {"total": 7}}
    parse = namespace["_parse_self_status_rss_kib"]
    assert parse("Name:\tpython\nVmRSS:\t1399999 kB\n") == 1_399_999
    expect(RuntimeError, lambda: parse("Name:\tpython\n"))
    expect(RuntimeError, lambda: parse("VmRSS:\t1 MB\n"))
    expect(RuntimeError, lambda: parse("VmRSS:\t1 kB\nVmRSS:\t2 kB\n"))

    class FakeResource:
        RUSAGE_SELF = 0

        @staticmethod
        def getrusage(_who):
            return SimpleNamespace(ru_maxrss=1_523_728)

    namespace["resource"] = FakeResource
    namespace["_current_self_rss_kib"] = lambda: 1_350_000
    guard = namespace["_resource_guard"]
    evidence = guard(time.monotonic() + 30.0, "test below live ceiling")
    assert evidence == {
        "metric": "proc_self_status_VmRSS",
        "current_rss_kib": 1_350_000,
        "historical_peak_rss_kib": 1_523_728,
        "limit_kib": 1_400_000,
    }
    namespace["_current_self_rss_kib"] = lambda: 1_400_000
    expect(MemoryError, lambda: guard(time.monotonic() + 30.0, "test at ceiling"))
    expect(TimeoutError, lambda: guard(0.0, "expired"))

    release = namespace["_release_unused_heap"]()
    assert release["before_rss_kib"] >= 0
    assert release["after_rss_kib"] >= 0
    assert release["released_rss_kib"] == max(
        0, release["before_rss_kib"] - release["after_rss_kib"]
    )
    assert isinstance(release["gc_collected"], int)
    assert release["malloc_trim_result"] in {0, 1}

    source = RUNNER.read_text(encoding="utf-8")
    assert 'memory_release_after_solve = _release_unused_heap()' in source
    assert 'solve_return_resource = _resource_guard(deadline, "fresh solve return")' in source
    assert '"metric": "proc_self_status_VmRSS"' in source
    assert "peak >= RUNNER_RSS_CEILING_KIB" not in source
    assert "key: value for key, value in asdict(result).items()" not in source
    print("PU-PROJ v22 focused live-RSS tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
