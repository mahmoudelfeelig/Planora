from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "planora.research-operator-provenance.v1"
NOVELTY_STATUSES = frozenset(
    {
        "established_primitives_planora_systems_composition",
        "unestablished_planora_selection_hypothesis",
        "unestablished_planora_root_selection_hypothesis",
        "unestablished_planora_frontier_construction_hypothesis",
        "unestablished_planora_root_ordering_hypothesis",
        "unestablished_planora_cross_component_ranking_hypothesis",
        "unestablished_planora_residual_selector_hypothesis",
        "unestablished_planora_orchestration_hypothesis",
        "unestablished_verification_aware_dispatch_hypothesis",
        "unestablished_verification_aware_orchestration_hypothesis",
        "unestablished_planora_rebuild_and_handoff_hypothesis",
        "unestablished_verification_aware_room_dispatch_hypothesis",
        "established_mathematics_planora_certificate_integration",
        "unestablished_verification_aware_portfolio_hypothesis",
        "unestablished_planora_pressure_ordering_hypothesis",
        "unestablished_planora_block_selection_hypothesis",
    }
)
REQUIRED_IMPLEMENTATION_RULES = frozenset(
    {
        "derive selectors from the current problem representation and independently scored incumbent",
        "accept candidates only after independent hard validation and canonical objective rescoring",
        "fail closed on deadline, mutation, malformed collaborator output, or score disagreement",
        "label established primitives as prior art and test Planora-specific composition separately",
        "retain comparator-seeded experiments as diagnostic_unverified_for_native_superiority",
    }
)
BENCHMARK_ID_PATTERN = re.compile(r"(?i)\bcomp(?:0[1-9]|1[0-9]|2[01])\b")
TARGET_IDENTIFIER_PATTERN = re.compile(
    r"(?i)(?:target|cpsolver|comparator).*(?:score|threshold)"
)


def _source_fingerprint_errors(source_text: str, *, relative_path: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        return [f"operator source cannot be parsed: {relative_path}: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if BENCHMARK_ID_PATTERN.search(node.value):
                errors.append(
                    f"benchmark instance id found in operator source: {relative_path}"
                )
                break
    for node in ast.walk(tree):
        identifier: str | None = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        if identifier is not None and TARGET_IDENTIFIER_PATTERN.fullmatch(identifier):
            errors.append(
                f"comparator or target score coupling found in operator source: {relative_path}"
            )
            break
    return errors


def _nonempty_strings(value: Any, *, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must be a non-empty list")
        return []
    strings = [item for item in value if isinstance(item, str) and item.strip()]
    if len(strings) != len(value):
        errors.append(f"{field} must contain only non-empty strings")
    return strings


def validate_research_provenance(
    payload: Any,
    *,
    repository_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["root must be an object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    policy = payload.get("clean_room_policy")
    if not isinstance(policy, dict):
        errors.append("clean_room_policy must be an object")
        policy = {}
    rules = set(
        _nonempty_strings(
            policy.get("implementation_rules"),
            field="clean_room_policy.implementation_rules",
            errors=errors,
        )
    )
    missing_rules = sorted(REQUIRED_IMPLEMENTATION_RULES - rules)
    if missing_rules:
        errors.append(f"clean_room_policy is missing required rules: {missing_rules}")
    _nonempty_strings(
        policy.get("allowed_inputs"),
        field="clean_room_policy.allowed_inputs",
        errors=errors,
    )
    _nonempty_strings(
        policy.get("forbidden_inputs"),
        field="clean_room_policy.forbidden_inputs",
        errors=errors,
    )

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif source_id in source_ids:
            errors.append(f"duplicate source id: {source_id}")
        else:
            source_ids.add(source_id)
        for field in ("kind", "title", "url"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        url = source.get("url")
        if isinstance(url, str) and not url.startswith("https://"):
            errors.append(f"{prefix}.url must use https")

    operators = payload.get("operators")
    if not isinstance(operators, list) or not operators:
        errors.append("operators must be a non-empty list")
        operators = []
    operator_ids: set[str] = set()
    covered_paths: set[str] = set()
    for index, operator in enumerate(operators):
        prefix = f"operators[{index}]"
        if not isinstance(operator, dict):
            errors.append(f"{prefix} must be an object")
            continue
        operator_id = operator.get("id")
        if not isinstance(operator_id, str) or not operator_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif operator_id in operator_ids:
            errors.append(f"duplicate operator id: {operator_id}")
        else:
            operator_ids.add(operator_id)
        if operator.get("novelty_status") not in NOVELTY_STATUSES:
            errors.append(f"{prefix}.novelty_status is not recognized")
        contribution = operator.get("planora_specific_contribution")
        if not isinstance(contribution, str) or len(contribution.strip()) < 40:
            errors.append(f"{prefix}.planora_specific_contribution is too short")
        paths = _nonempty_strings(
            operator.get("implementation_paths"),
            field=f"{prefix}.implementation_paths",
            errors=errors,
        )
        for raw_path in paths:
            relative = Path(raw_path)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"{prefix} has unsafe implementation path: {raw_path}")
                continue
            implementation = repository_root / relative
            if not implementation.is_file():
                errors.append(
                    f"{prefix} implementation path does not exist: {raw_path}"
                )
            covered_paths.add(relative.as_posix())
        referenced_sources = _nonempty_strings(
            operator.get("source_ids"),
            field=f"{prefix}.source_ids",
            errors=errors,
        )
        unknown_sources = sorted(set(referenced_sources) - source_ids)
        if unknown_sources:
            errors.append(f"{prefix} references unknown sources: {unknown_sources}")
        _nonempty_strings(
            operator.get("established_primitives"),
            field=f"{prefix}.established_primitives",
            errors=errors,
        )
        _nonempty_strings(
            operator.get("prohibited_claims"),
            field=f"{prefix}.prohibited_claims",
            errors=errors,
        )
        _nonempty_strings(
            operator.get("required_ablations"),
            field=f"{prefix}.required_ablations",
            errors=errors,
        )

    required_operator_paths = {
        path.relative_to(repository_root).as_posix()
        for path in (repository_root / "core").glob("itc2007_*.py")
        if any(
            marker in path.read_text(encoding="utf-8")
            for marker in ("def optimize_itc2007_", "def itc2007_room_load_eligibility")
        )
    }
    missing_paths = sorted(required_operator_paths - covered_paths)
    if missing_paths:
        errors.append(
            f"optimization modules missing from operator ledger: {missing_paths}"
        )

    for relative_path in sorted(required_operator_paths):
        source_text = (repository_root / relative_path).read_text(encoding="utf-8")
        errors.extend(
            _source_fingerprint_errors(source_text, relative_path=relative_path)
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Planora's research provenance ledger."
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("config/research_operator_provenance.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"research provenance: FAIL: {exc}")
        return 1
    errors = validate_research_provenance(payload, repository_root=root)
    if errors:
        print("research provenance: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "research provenance: PASS "
        f"({len(payload['operators'])} operators, {len(payload['sources'])} sources)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
