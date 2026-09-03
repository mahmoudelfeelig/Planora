from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Any, Tuple


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    mode: str
    room_mode: str
    use_objective: bool
    time_limit_seconds: float
    max_wall_seconds: float
    workers: int = 1
    expected_statuses: Tuple[int, ...] = (0, 4)
    max_soft_penalty: int | None = None


BENCHMARK_CASES = (
    BenchmarkCase(
        case_id="small_demo_fast_feasible",
        mode="small_demo",
        room_mode="greedy",
        use_objective=False,
        time_limit_seconds=20.0,
        max_wall_seconds=20.0,
        expected_statuses=(0, 4),
        max_soft_penalty=450,
    ),
    BenchmarkCase(
        case_id="labs_only_strict_verification",
        mode="labs_only",
        room_mode="cp_rooms",
        use_objective=True,
        time_limit_seconds=30.0,
        max_wall_seconds=35.0,
        expected_statuses=(2, 4),
        max_soft_penalty=None,
    ),
    BenchmarkCase(
        case_id="mixed_large_university_fast",
        mode="mixed_large",
        room_mode="partitioned",
        use_objective=False,
        time_limit_seconds=45.0,
        max_wall_seconds=55.0,
        workers=4,
        expected_statuses=(2, 4),
        max_soft_penalty=None,
    ),
    BenchmarkCase(
        case_id="ss23_uni_like_fast_scale",
        mode="ss23_uni_like",
        room_mode="partitioned",
        use_objective=False,
        time_limit_seconds=60.0,
        max_wall_seconds=75.0,
        workers=4,
        expected_statuses=(2, 4),
        max_soft_penalty=None,
    ),
)


@dataclass(frozen=True)
class BenchmarkFamily:
    """Discoverable capabilities for one independently scored benchmark family.

    Entry points are kept as ``module:attribute`` strings so inspecting the
    registry never imports OR-Tools, XML libraries, solver services, or an
    external validator. ``score_status`` explicitly distinguishes a local
    implementation of published/competition semantics from an official score.
    """

    family_id: str
    title: str
    problem_kinds: tuple[str, ...]
    parser_entrypoint: str
    scorer_entrypoint: str
    validator_entrypoint: str | None
    solver_entrypoint: str | None
    score_status: str
    validator_status: str
    solver_status: str
    official_validator_entrypoint: str | None = None
    format_versions: tuple[str, ...] = ()
    notes: str = ""

    @property
    def solver_available(self) -> bool:
        return self.solver_entrypoint is not None

    @property
    def official_validator_available(self) -> bool:
        return self.official_validator_entrypoint is not None

    @property
    def independent_validator_available(self) -> bool:
        return self.validator_entrypoint is not None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["solver_available"] = self.solver_available
        payload["official_validator_available"] = self.official_validator_available
        payload["independent_validator_available"] = (
            self.independent_validator_available
        )
        return payload


BENCHMARK_FAMILIES = (
    BenchmarkFamily(
        family_id="itc2007-cbctt",
        title="ITC-2007 Curriculum-Based Course Timetabling",
        problem_kinds=("course_timetabling",),
        format_versions=("ITC-2007 Track 3",),
        parser_entrypoint="benchmarks.itc2007:parse_itc2007_ctt",
        scorer_entrypoint="benchmarks.itc2007:score_itc2007_schedule",
        validator_entrypoint=None,
        official_validator_entrypoint="benchmarks.itc2007:run_itc2007_validator",
        solver_entrypoint="benchmarks.itc2007_harness:run_planora_case",
        score_status="independent_official_semantics",
        validator_status="official_external_validator_for_hard_feasibility",
        solver_status="production_solver_adapter_available",
        notes=(
            "The in-process scorer covers the official soft objective; hard "
            "feasibility agreement is provided by the official external validator."
        ),
    ),
    BenchmarkFamily(
        family_id="itc2007-pe",
        title="ITC-2007 Post-Enrolment Course Timetabling",
        problem_kinds=("post_enrolment_course_timetabling",),
        format_versions=("ITC-2007 Track 2",),
        parser_entrypoint="benchmarks.itc2007_pe:parse_itc2007_pe",
        scorer_entrypoint="benchmarks.itc2007_pe:validate_itc2007_pe_solution",
        validator_entrypoint="benchmarks.itc2007_pe:validate_itc2007_pe_solution",
        official_validator_entrypoint=(
            "benchmarks.itc2007_pe:run_itc2007_pe_validator"
        ),
        solver_entrypoint="benchmarks.itc2007_pe:solve_itc2007_pe",
        score_status="independent_official_semantics",
        validator_status="independent_plus_official_external_validator",
        solver_status="native_scale_guarded_solver_available",
    ),
    BenchmarkFamily(
        family_id="itc2007-exam",
        title="ITC-2007 Examination Timetabling",
        problem_kinds=("examination_timetabling",),
        format_versions=("ITC-2007 Track 1",),
        parser_entrypoint="benchmarks.itc2007_exam:parse_itc2007_exam",
        scorer_entrypoint=(
            "benchmarks.itc2007_exam:validate_itc2007_exam_solution"
        ),
        validator_entrypoint=(
            "benchmarks.itc2007_exam:validate_itc2007_exam_solution"
        ),
        official_validator_entrypoint=None,
        solver_entrypoint="benchmarks.itc2007_exam:solve_itc2007_exam",
        score_status="independent_official_semantics",
        validator_status="independent_complete_no_external_validator_available",
        solver_status="native_scale_guarded_solver_available",
        notes=(
            "The independent scorer implements the published competition "
            "components. No official Track-1 validator executable is currently "
            "available, so external agreement is not claimed."
        ),
    ),
    BenchmarkFamily(
        family_id="cbctt-extended",
        title="Extended Curriculum-Based Course Timetabling",
        problem_kinds=("course_timetabling",),
        format_versions=("ECTT UD1", "ECTT UD2", "ECTT UD3", "ECTT UD4", "ECTT UD5"),
        parser_entrypoint="benchmarks.cbctt:parse_cbctt_ectt",
        scorer_entrypoint="benchmarks.cbctt_native:score_cbctt_assignments",
        validator_entrypoint="benchmarks.cbctt_native:validate_cbctt_assignments",
        solver_entrypoint="benchmarks.cbctt_native:solve_cbctt_native",
        score_status="independent_published_formulation_semantics",
        validator_status="independent_published_formulation_validator",
        solver_status="native_scale_guarded_solver_available",
        notes="Implements the published Bonutti UD1-UD5 formulations.",
    ),
    BenchmarkFamily(
        family_id="itc2019",
        title="ITC-2019 University Course Timetabling",
        problem_kinds=("course_timetabling", "student_sectioning"),
        format_versions=("ITC-2019",),
        parser_entrypoint="benchmarks.itc2019:parse_itc2019_xml",
        scorer_entrypoint="benchmarks.itc2019:score_itc2019_solution",
        validator_entrypoint="benchmarks.itc2019:validate_itc2019_solution",
        solver_entrypoint="benchmarks.itc2019:solve_itc2019_native",
        score_status="independent_official_semantics",
        validator_status="independent_complete_no_external_official_validator",
        solver_status="native_joint_timetabling_sectioning_solver_available",
        notes=(
            "All published distribution families and the four-component objective "
            "are evaluated independently; no official external validator is bundled."
        ),
    ),
    BenchmarkFamily(
        family_id="unitime-native",
        title="UniTime Native XML",
        problem_kinds=(
            "course_timetabling",
            "examination_timetabling",
            "student_sectioning",
        ),
        format_versions=("course 2.1-2.4", "exam 1.0", "sectioning 1.0"),
        parser_entrypoint="benchmarks.unitime_native:parse_unitime_xml",
        scorer_entrypoint="benchmarks.unitime_native:score_unitime_solution",
        validator_entrypoint="benchmarks.unitime_native:validate_unitime_solution",
        solver_entrypoint="benchmarks.unitime_native:solve_unitime_native",
        score_status="native_non_official",
        validator_status="independent_supported_subset_fail_closed",
        solver_status="native_supported_subset_solver_available",
        notes=(
            "The planora-unitime-native-v1 score is deliberately not represented "
            "as an official or CPSolver-comparable UniTime score."
        ),
    ),
    BenchmarkFamily(
        family_id="xhstt",
        title="XHSTT High School Timetabling",
        problem_kinds=("high_school_timetabling",),
        format_versions=("XHSTT-2014",),
        parser_entrypoint="benchmarks.xhstt:parse_xhstt",
        scorer_entrypoint="benchmarks.xhstt:validate_xhstt_solution",
        validator_entrypoint="benchmarks.xhstt:validate_xhstt_solution",
        solver_entrypoint="benchmarks.xhstt:solve_xhstt",
        score_status="independent_official_semantics",
        validator_status="independent_supported_semantics_fail_closed",
        solver_status="native_supported_semantics_solver_available",
        notes=(
            "The independent validator computes the standard lexicographic cost; "
            "unknown features are retained and fail closed."
        ),
    ),
)


BENCHMARK_FAMILY_REGISTRY = MappingProxyType(
    {family.family_id: family for family in BENCHMARK_FAMILIES}
)


def get_benchmark_family(family_id: str) -> BenchmarkFamily:
    """Return a family descriptor with a useful error for unknown identifiers."""

    try:
        return BENCHMARK_FAMILY_REGISTRY[str(family_id)]
    except KeyError as exc:
        available = ", ".join(BENCHMARK_FAMILY_REGISTRY)
        raise KeyError(
            f"Unknown benchmark family {family_id!r}; available families: {available}"
        ) from exc


def resolve_benchmark_entrypoint(reference: str) -> Any:
    """Resolve one registry entry point on demand without eager solver imports."""

    module_name, separator, attribute_name = str(reference).partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError(
            "Benchmark entry points must use the 'module:attribute' format"
        )
    module = import_module(module_name)
    try:
        return getattr(module, attribute_name)
    except AttributeError as exc:
        raise ImportError(
            f"Benchmark entry point {reference!r} does not exist"
        ) from exc


__all__ = [
    "BENCHMARK_CASES",
    "BENCHMARK_FAMILIES",
    "BENCHMARK_FAMILY_REGISTRY",
    "BenchmarkCase",
    "BenchmarkFamily",
    "get_benchmark_family",
    "resolve_benchmark_entrypoint",
]
