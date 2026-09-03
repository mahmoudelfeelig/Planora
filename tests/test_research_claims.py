from __future__ import annotations

from benchmarks.research_claims import (
    ResearchEvidenceContext,
    classify_research_evidence,
)


def _context(**changes: object) -> ResearchEvidenceContext:
    values: dict[str, object] = {
        "starting_solution_origin": "planora_current_run",
        "timing_scope": "end_to_end",
        "independent_validation_completed": True,
        "hard_feasible": True,
        "source_snapshot_match": True,
        "input_snapshot_match": True,
        "comparator_artifact_accessed_by_search": False,
        "strict_deadline_compliant": True,
    }
    values.update(changes)
    return ResearchEvidenceContext(**values)  # type: ignore[arg-type]


def test_current_run_can_be_an_end_to_end_native_candidate() -> None:
    result = classify_research_evidence(_context())

    assert result.classification == "native_end_to_end_candidate"
    assert result.native_quality_candidate is True
    assert result.end_to_end_runtime_candidate is True
    assert result.reasons == ()


def test_retained_planora_incumbent_is_quality_only() -> None:
    result = classify_research_evidence(
        _context(
            starting_solution_origin="planora_retained",
            timing_scope="post_incumbent",
        )
    )

    assert result.classification == "native_post_incumbent_candidate"
    assert result.native_quality_candidate is True
    assert result.end_to_end_runtime_candidate is False
    assert "retained_planora_incumbent" in result.reasons


def test_comparator_seed_is_always_diagnostic() -> None:
    result = classify_research_evidence(_context(starting_solution_origin="comparator"))

    assert result.classification == "diagnostic_comparator_seeded"
    assert result.native_quality_candidate is False
    assert result.end_to_end_runtime_candidate is False


def test_accessing_comparator_artifact_during_search_taints_native_start() -> None:
    result = classify_research_evidence(
        _context(comparator_artifact_accessed_by_search=True)
    )

    assert result.classification == "diagnostic_comparator_seeded"
    assert result.native_quality_candidate is False


def test_missing_integrity_or_validation_fails_closed() -> None:
    for changes in (
        {"independent_validation_completed": False},
        {"hard_feasible": False},
        {"source_snapshot_match": False},
        {"input_snapshot_match": False},
        {"starting_solution_origin": "unknown"},
    ):
        result = classify_research_evidence(_context(**changes))
        assert result.classification == "diagnostic_unverified"
        assert result.native_quality_candidate is False
        assert result.end_to_end_runtime_candidate is False


def test_stage_only_timing_cannot_become_equal_budget_claim() -> None:
    result = classify_research_evidence(_context(timing_scope="stage_only"))

    assert result.classification == "native_post_incumbent_candidate"
    assert result.native_quality_candidate is True
    assert result.end_to_end_runtime_candidate is False


def test_deadline_noncompliance_blocks_runtime_but_not_valid_quality() -> None:
    result = classify_research_evidence(_context(strict_deadline_compliant=False))

    assert result.classification == "native_post_incumbent_candidate"
    assert result.native_quality_candidate is True
    assert result.end_to_end_runtime_candidate is False
    assert "strict_deadline_not_established" in result.reasons
