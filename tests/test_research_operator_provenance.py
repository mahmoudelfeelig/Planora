from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.check_research_provenance import (
    REQUIRED_IMPLEMENTATION_RULES,
    SCHEMA_VERSION,
    validate_research_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "config" / "research_operator_provenance.json"


def _payload() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_operator_provenance_ledger_is_complete_and_clean_room_safe() -> None:
    payload = _payload()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert validate_research_provenance(payload, repository_root=ROOT) == []


def test_clean_room_rules_are_not_optional() -> None:
    payload = _payload()
    broken = copy.deepcopy(payload)
    policy = broken["clean_room_policy"]
    assert isinstance(policy, dict)
    policy["implementation_rules"] = sorted(REQUIRED_IMPLEMENTATION_RULES)[1:]

    errors = validate_research_provenance(broken, repository_root=ROOT)

    assert any("missing required rules" in error for error in errors)


def test_every_operator_cites_prior_art_and_states_falsifiable_ablations() -> None:
    payload = _payload()
    operators = payload["operators"]
    assert isinstance(operators, list)

    for operator in operators:
        assert isinstance(operator, dict)
        assert operator["source_ids"]
        assert operator["established_primitives"]
        assert operator["prohibited_claims"]
        assert operator["required_ablations"]
        contribution = str(operator["planora_specific_contribution"])
        assert "novel" not in contribution.lower()


def test_unknown_prior_art_reference_fails_closed() -> None:
    payload = _payload()
    broken = copy.deepcopy(payload)
    operators = broken["operators"]
    assert isinstance(operators, list)
    first = operators[0]
    assert isinstance(first, dict)
    first["source_ids"] = ["missing_primary_source"]

    errors = validate_research_provenance(broken, repository_root=ROOT)

    assert any("unknown sources" in error for error in errors)


def test_missing_operator_module_registration_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    fake_root = tmp_path / "repo"
    (fake_root / "core").mkdir(parents=True)
    for source in (ROOT / "core").glob("itc2007_*.py"):
        destination = fake_root / "core" / source.name
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (fake_root / "benchmarks").mkdir()
    exam_source = ROOT / "benchmarks" / "itc2007_exam.py"
    (fake_root / "benchmarks" / exam_source.name).write_text(
        exam_source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    unregistered = fake_root / "core" / "itc2007_new_operator.py"
    unregistered.write_text(
        "def optimize_itc2007_new_operator():\n    return None\n",
        encoding="utf-8",
    )

    errors = validate_research_provenance(payload, repository_root=fake_root)

    assert any("itc2007_new_operator.py" in error for error in errors)


def test_benchmark_fingerprint_in_operator_source_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    fake_root = tmp_path / "repo"
    (fake_root / "core").mkdir(parents=True)
    for source in (ROOT / "core").glob("itc2007_*.py"):
        destination = fake_root / "core" / source.name
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (fake_root / "benchmarks").mkdir()
    exam_source = ROOT / "benchmarks" / "itc2007_exam.py"
    (fake_root / "benchmarks" / exam_source.name).write_text(
        exam_source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    target = fake_root / "core" / "itc2007_compound_search.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nSPECIAL_CASE = 'comp14'\n",
        encoding="utf-8",
    )

    errors = validate_research_provenance(payload, repository_root=fake_root)

    assert any("benchmark instance id" in error for error in errors)
