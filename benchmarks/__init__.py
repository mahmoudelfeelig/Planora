"""Benchmark adapters and a dependency-light capability registry.

Public adapter symbols are resolved lazily. Importing :mod:`benchmarks` for
registry discovery therefore does not require OR-Tools, lxml, solver services,
or any external validator executable.
"""

from __future__ import annotations

from typing import Any

from benchmarks.corpus import (
    BENCHMARK_CASES,
    BENCHMARK_FAMILIES,
    BENCHMARK_FAMILY_REGISTRY,
    BenchmarkCase,
    BenchmarkFamily,
    get_benchmark_family,
    resolve_benchmark_entrypoint,
)


def _module_exports(module: str, names: tuple[str, ...]) -> dict[str, str]:
    return {name: f"{module}:{name}" for name in names}


_LAZY_EXPORTS = {
    **_module_exports(
        "benchmarks.cbctt",
        (
            "CBCTTITC2007Projection",
            "CBCTTExtendedProblem",
            "CBCTTExtensionLosses",
            "parse_cbctt_ectt",
            "project_cbctt_to_itc2007",
            "write_projected_itc2007_ctt",
        ),
    ),
    **_module_exports(
        "benchmarks.cbctt_corpus",
        (
            "CBCTT_ARCHIVE_PIN",
            "CBCTT_CORPUS_FILES",
            "CBCTT_EXCLUDED_ARCHIVE_VARIANTS",
            "fetch_cbctt_corpus",
            "validate_cbctt_projection_compatibility",
            "verify_cached_cbctt_corpus",
        ),
    ),
    **_module_exports(
        "benchmarks.cbctt_native",
        (
            "CBCTTAssignment",
            "CBCTTFormulation",
            "CBCTTScore",
            "CBCTTSolveResult",
            "CBCTTSolverEligibility",
            "CBCTTValidation",
            "CBCTT_FORMULATIONS",
            "CBCTT_NATIVE_REFERENCE_DOI",
            "CBCTT_NATIVE_SEMANTICS_ID",
            "assess_cbctt_native_eligibility",
            "get_cbctt_formulation",
            "parse_cbctt_solution",
            "render_cbctt_solution",
            "score_cbctt_assignments",
            "solve_cbctt_native",
            "validate_cbctt_assignments",
            "write_cbctt_solution",
        ),
    ),
    **_module_exports(
        "benchmarks.itc2007",
        (
            "ITC2007Assignment",
            "ITC2007Validation",
            "ITC2007ValidatorError",
            "canonicalize_itc2007_schedule",
            "load_itc2007_instance",
            "load_itc2007_solution",
            "parse_itc2007_ctt",
            "parse_itc2007_out",
            "parse_itc2007_validator_output",
            "run_itc2007_validator",
            "score_itc2007_instance_schedule",
            "score_itc2007_schedule",
            "write_itc2007_solution",
        ),
    ),
    **_module_exports(
        "benchmarks.itc2007_exam",
        (
            "ITC2007ExamAssignment",
            "ITC2007ExamOfficialValidation",
            "ITC2007ExamProblem",
            "ITC2007ExamSolveResult",
            "ITC2007ExamValidation",
            "ITC2007ExamValidatorError",
            "parse_itc2007_exam",
            "parse_itc2007_exam_solution",
            "parse_itc2007_exam_validator_output",
            "run_itc2007_exam_validator",
            "solve_itc2007_exam",
            "validate_itc2007_exam_solution",
            "write_itc2007_exam_solution",
        ),
    ),
    **_module_exports(
        "benchmarks.itc2007_pe",
        (
            "ITC2007PEAssignment",
            "ITC2007PEOfficialValidation",
            "ITC2007PEProblem",
            "ITC2007PEScore",
            "ITC2007PESolveResult",
            "ITC2007PEValidation",
            "ITC2007PEValidatorError",
            "parse_itc2007_pe",
            "parse_itc2007_pe_solution",
            "parse_itc2007_pe_validator_output",
            "run_itc2007_pe_validator",
            "solve_itc2007_pe",
            "validate_itc2007_pe_solution",
            "write_itc2007_pe_solution",
        ),
    ),
    **_module_exports(
        "benchmarks.itc2019",
        (
            "ITC2019ClassPlacement",
            "ITC2019ConversionSummary",
            "ITC2019NativeSolveResult",
            "ITC2019Objective",
            "ITC2019Problem",
            "ITC2019Solution",
            "evaluate_itc2019_distributions",
            "inspect_itc2019_xml",
            "parse_itc2019_solution",
            "parse_itc2019_xml",
            "score_itc2019_solution",
            "solve_itc2019_native",
            "solve_itc2019_student_sectioning",
            "summarize_itc2019_problem",
            "validate_itc2019_class_placements",
            "validate_itc2019_solution",
            "validate_itc2019_solution_document",
            "validate_itc2019_student_sectioning",
            "write_itc2019_solution",
        ),
    ),
    **_module_exports(
        "benchmarks.itc2019_corpus",
        (
            "ITC2019_PUBLIC_COMMIT",
            "ITC2019_PUBLIC_CORPUS_FILES",
            "ITC2019_PUBLIC_CORPUS_PIN",
            "fetch_itc2019_public_corpus",
            "verify_cached_itc2019_public_corpus",
        ),
    ),
    **_module_exports(
        "benchmarks.unitime_native",
        (
            "UniTimeAssignment",
            "UniTimeCourseProblem",
            "UniTimeExamProblem",
            "UniTimeNativeScore",
            "UniTimeNativeSolveResult",
            "UniTimeProblem",
            "UniTimeSectioningProblem",
            "UniTimeSolution",
            "UniTimeValidation",
            "parse_unitime_course_xml",
            "parse_unitime_exam_xml",
            "parse_unitime_native",
            "parse_unitime_sectioning_xml",
            "parse_unitime_xml",
            "score_unitime_native",
            "score_unitime_solution",
            "solve_unitime_native",
            "summarize_unitime_problem",
            "validate_unitime_native",
            "validate_unitime_solution",
            "write_unitime_solution_xml",
        ),
    ),
    **_module_exports(
        "benchmarks.xhstt",
        (
            "XHSTTArchive",
            "XHSTTConstraint",
            "XHSTTConstraintCost",
            "XHSTTMeet",
            "XHSTTProblem",
            "XHSTTScore",
            "XHSTTSolution",
            "XHSTTSolveResult",
            "XHSTTValidation",
            "parse_xhstt",
            "parse_xhstt_archive",
            "parse_xhstt_solutions",
            "solve_xhstt",
            "validate_xhstt_solution",
            "write_xhstt_solution",
        ),
    ),
}


def __getattr__(name: str) -> Any:
    try:
        reference = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = resolve_benchmark_entrypoint(reference)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})


__all__ = [
    "BENCHMARK_CASES",
    "BENCHMARK_FAMILIES",
    "BENCHMARK_FAMILY_REGISTRY",
    "BenchmarkCase",
    "BenchmarkFamily",
    "get_benchmark_family",
    "resolve_benchmark_entrypoint",
    *_LAZY_EXPORTS,
]
