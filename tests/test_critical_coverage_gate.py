from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from scripts.check_critical_coverage import check_coverage, measured_floor


ROOT = Path(__file__).resolve().parent.parent


def _coverage(*, lines: int = 8, statements: int = 10, branches: int = 3) -> dict:
    return {
        "meta": {"branch_coverage": True},
        "files": {
            "core/example.py": {
                "summary": {
                    "covered_lines": lines,
                    "num_statements": statements,
                    "covered_branches": branches,
                    "num_branches": 4,
                }
            }
        },
    }


def _baseline(*, line_floor: float = 80.0, branch_floor: float = 75.0) -> dict:
    return {
        "schema_version": 1,
        "categories": {
            "solver": {
                "files": ["core/example.py"],
                "minimum_line_percent": line_floor,
                "minimum_branch_percent": branch_floor,
            }
        },
        "files": {
            "core/example.py": {
                "minimum_line_percent": line_floor,
                "minimum_branch_percent": branch_floor,
            }
        },
    }


def test_coverage_gate_accepts_rates_at_the_measured_floor() -> None:
    reports, failures = check_coverage(_coverage(), _baseline())

    assert failures == []
    assert reports == [
        "solver: lines 80.00% (8/10), branches 75.00% (3/4)",
        "core/example.py: lines 80.00% (8/10), branches 75.00% (3/4)",
    ]


def test_coverage_gate_reports_line_and_branch_regressions() -> None:
    _reports, failures = check_coverage(
        _coverage(lines=7, branches=2),
        _baseline(),
    )

    assert failures == [
        "solver line coverage 70.00% is below the 80.00% ratchet",
        "solver branch coverage 50.00% is below the 75.00% ratchet",
        "core/example.py line coverage 70.00% is below the 80.00% ratchet",
        "core/example.py branch coverage 50.00% is below the 75.00% ratchet",
    ]


def test_coverage_gate_rejects_missing_files_and_non_branch_reports() -> None:
    missing_file_baseline = _baseline()
    missing_file_baseline["categories"] = {
        "solver": {
            "files": ["core/missing.py"],
            "minimum_line_percent": 0,
            "minimum_branch_percent": 0,
        }
    }
    with pytest.raises(ValueError, match="missing configured files"):
        check_coverage(_coverage(), missing_file_baseline)

    without_branches = _coverage()
    without_branches["meta"]["branch_coverage"] = False
    with pytest.raises(ValueError, match="not collected with branch coverage"):
        check_coverage(without_branches, _baseline())


def test_measured_floor_never_rounds_above_observation() -> None:
    assert measured_floor(66.666666) == 66.66
    assert measured_floor(100.0) == 100.0


def _observed_percent(entry: dict, measurement: str, kind: str) -> float:
    observed = entry[measurement]
    covered = int(observed[f"covered_{kind}"])
    total = int(observed["statements" if kind == "lines" else "branches"])
    return 100.0 if total == 0 else 100.0 * covered / total


def test_checked_in_ratchet_scope_and_floors_match_measurement_evidence() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    baseline = json.loads(
        (ROOT / "config" / "critical_coverage_baseline.json").read_text(encoding="utf-8")
    )

    configured = set(pyproject["tool"]["coverage"]["report"]["include"])
    per_file = set(baseline["files"])
    categorized = {
        path
        for category in baseline["categories"].values()
        for path in category["files"]
    }
    assert configured == per_file == categorized

    for entries in (baseline["categories"], baseline["files"]):
        for entry in entries.values():
            for kind, floor_name in (("lines", "line"), ("branches", "branch")):
                observed_minimum = min(
                    _observed_percent(entry, measurement, kind)
                    for measurement in ("full_local", "ci_portable")
                )
                floor = float(entry[f"minimum_{floor_name}_percent"])
                assert floor == measured_floor(observed_minimum)
