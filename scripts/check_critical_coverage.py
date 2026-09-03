from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CoverageRates:
    line_percent: float
    branch_percent: float
    covered_lines: int
    statements: int
    covered_branches: int
    branches: int


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def summarize_files(
    coverage_files: Mapping[str, Any],
    paths: Sequence[str],
) -> CoverageRates:
    missing = [path for path in paths if path not in coverage_files]
    if missing:
        raise ValueError(f"coverage report is missing configured files: {', '.join(missing)}")

    statements = 0
    covered_lines = 0
    branches = 0
    covered_branches = 0
    for path in paths:
        summary = coverage_files[path].get("summary", {})
        statements += int(summary.get("num_statements", 0))
        covered_lines += int(summary.get("covered_lines", 0))
        branches += int(summary.get("num_branches", 0))
        covered_branches += int(summary.get("covered_branches", 0))

    return CoverageRates(
        line_percent=_percent(covered_lines, statements),
        branch_percent=_percent(covered_branches, branches),
        covered_lines=covered_lines,
        statements=statements,
        covered_branches=covered_branches,
        branches=branches,
    )


def check_coverage(
    coverage_payload: Mapping[str, Any],
    baseline_payload: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    if baseline_payload.get("schema_version") != 1:
        raise ValueError("unsupported critical coverage baseline schema")
    if not coverage_payload.get("meta", {}).get("branch_coverage"):
        raise ValueError("coverage report was not collected with branch coverage")

    coverage_files = coverage_payload.get("files")
    if not isinstance(coverage_files, Mapping):
        raise ValueError("coverage report does not contain a file map")

    reports: list[str] = []
    failures: list[str] = []

    def check_scope(label: str, raw_config: Mapping[str, Any], paths: list[str]) -> None:
        rates = summarize_files(coverage_files, paths)
        minimum_line = float(raw_config["minimum_line_percent"])
        minimum_branch = float(raw_config["minimum_branch_percent"])
        reports.append(
            f"{label}: lines {rates.line_percent:.2f}% "
            f"({rates.covered_lines}/{rates.statements}), branches "
            f"{rates.branch_percent:.2f}% ({rates.covered_branches}/{rates.branches})"
        )
        if rates.line_percent + 1e-9 < minimum_line:
            failures.append(
                f"{label} line coverage {rates.line_percent:.2f}% is below "
                f"the {minimum_line:.2f}% ratchet"
            )
        if rates.branch_percent + 1e-9 < minimum_branch:
            failures.append(
                f"{label} branch coverage {rates.branch_percent:.2f}% is below "
                f"the {minimum_branch:.2f}% ratchet"
            )

    categories = baseline_payload.get("categories")
    if not isinstance(categories, Mapping) or not categories:
        raise ValueError("critical coverage baseline has no categories")

    for category, raw_config in categories.items():
        if not isinstance(raw_config, Mapping):
            raise ValueError(f"invalid baseline category: {category}")
        paths = raw_config.get("files")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"baseline category {category} has no files")
        check_scope(str(category), raw_config, [str(path) for path in paths])

    file_ratchets = baseline_payload.get("files")
    if not isinstance(file_ratchets, Mapping) or not file_ratchets:
        raise ValueError("critical coverage baseline has no per-file ratchets")
    for path, raw_config in file_ratchets.items():
        if not isinstance(raw_config, Mapping):
            raise ValueError(f"invalid per-file baseline: {path}")
        check_scope(str(path), raw_config, [str(path)])

    return reports, failures


def measured_floor(value: float) -> float:
    """Return a two-decimal floor so a recorded floor never exceeds its measurement."""
    return math.floor(value * 100.0 + 1e-9) / 100.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check critical line and branch coverage against measured ratchets."
    )
    parser.add_argument("--coverage-json", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    args = parser.parse_args()

    coverage_payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    baseline_payload = json.loads(args.baseline.read_text(encoding="utf-8"))
    reports, failures = check_coverage(coverage_payload, baseline_payload)

    for report in reports:
        print(report)
    if failures:
        for failure in failures:
            print(f"COVERAGE GATE FAILED: {failure}")
        return 1
    print("Critical coverage ratchets passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
