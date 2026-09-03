from __future__ import annotations

"""Fail-closed classification for solver research evidence.

This module does not decide whether a method is novel.  It prevents a useful
diagnostic, warm continuation, or comparator-seeded postprocessing result from
silently becoming a Planora-native or equal-budget claim.
"""

from dataclasses import asdict, dataclass
from typing import Literal


StartingSolutionOrigin = Literal[
    "planora_current_run",
    "planora_retained",
    "comparator",
    "unknown",
]
TimingScope = Literal["end_to_end", "post_incumbent", "stage_only", "unknown"]
EvidenceClassification = Literal[
    "native_end_to_end_candidate",
    "native_post_incumbent_candidate",
    "diagnostic_comparator_seeded",
    "diagnostic_unverified",
]


@dataclass(frozen=True)
class ResearchEvidenceContext:
    starting_solution_origin: StartingSolutionOrigin
    timing_scope: TimingScope
    independent_validation_completed: bool
    hard_feasible: bool
    source_snapshot_match: bool
    input_snapshot_match: bool
    comparator_artifact_accessed_by_search: bool = False
    strict_deadline_compliant: bool = False


@dataclass(frozen=True)
class ResearchEvidenceClassification:
    classification: EvidenceClassification
    native_quality_candidate: bool
    end_to_end_runtime_candidate: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


def classify_research_evidence(
    context: ResearchEvidenceContext,
) -> ResearchEvidenceClassification:
    """Classify one result without inferring missing provenance or authority."""

    if (
        context.starting_solution_origin == "comparator"
        or context.comparator_artifact_accessed_by_search
    ):
        reasons = ["comparator_seeded_or_accessed_by_search"]
        if not context.independent_validation_completed:
            reasons.append("independent_validation_incomplete")
        return ResearchEvidenceClassification(
            classification="diagnostic_comparator_seeded",
            native_quality_candidate=False,
            end_to_end_runtime_candidate=False,
            reasons=tuple(reasons),
        )

    integrity_reasons: list[str] = []
    if context.starting_solution_origin not in {
        "planora_current_run",
        "planora_retained",
    }:
        integrity_reasons.append("starting_solution_origin_unverified")
    if not context.independent_validation_completed:
        integrity_reasons.append("independent_validation_incomplete")
    if not context.hard_feasible:
        integrity_reasons.append("hard_feasibility_not_established")
    if not context.source_snapshot_match:
        integrity_reasons.append("source_snapshot_mismatch_or_missing")
    if not context.input_snapshot_match:
        integrity_reasons.append("input_snapshot_mismatch_or_missing")
    if integrity_reasons:
        return ResearchEvidenceClassification(
            classification="diagnostic_unverified",
            native_quality_candidate=False,
            end_to_end_runtime_candidate=False,
            reasons=tuple(integrity_reasons),
        )

    if (
        context.starting_solution_origin == "planora_current_run"
        and context.timing_scope == "end_to_end"
        and context.strict_deadline_compliant
    ):
        return ResearchEvidenceClassification(
            classification="native_end_to_end_candidate",
            native_quality_candidate=True,
            end_to_end_runtime_candidate=True,
            reasons=(),
        )

    reasons = []
    if context.starting_solution_origin == "planora_retained":
        reasons.append("retained_planora_incumbent")
    if context.timing_scope != "end_to_end":
        reasons.append(f"timing_scope:{context.timing_scope}")
    if not context.strict_deadline_compliant:
        reasons.append("strict_deadline_not_established")
    return ResearchEvidenceClassification(
        classification="native_post_incumbent_candidate",
        native_quality_candidate=True,
        end_to_end_runtime_candidate=False,
        reasons=tuple(reasons),
    )
