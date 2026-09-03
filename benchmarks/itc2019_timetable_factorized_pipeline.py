"""Isolated synthetic-only timetable and student-sectioning pipeline.

This module intentionally has no parser, filesystem, dispatch, serialization, or
publication surface.  Its default operation only builds the reviewed factorized
timetable model.  End-to-end solving requires an explicit trusted-synthetic flag
and is bounded independently at construction, timetable search, and sectioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import time
from types import MappingProxyType
from typing import Mapping

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    ITC2019SectioningResult,
    score_itc2019_solution,
    solve_itc2019_student_sectioning,
    validate_itc2019_solution,
)
from benchmarks.itc2019_timetable_factorized import (
    ITC2019TimetableFactorizedLimits,
    ITC2019TimetableFactorizedResult,
    ITC2019TimetableFactorizedTelemetry,
    solve_itc2019_timetable_factorized,
)


_SECTIONING_RESULT_OWN_FIELDS = (
    "status",
    "student_classes",
    "student_conflicts",
    "weighted_objective",
    "best_bound",
    "wall_time_seconds",
    "validation_errors",
    "model_build_seconds",
    "solver_wall_time_seconds",
)


@dataclass(frozen=True)
class ITC2019TimetableFactorizedPipelineLimits:
    """Independent, finite limits for a trusted synthetic pipeline run."""

    timetable_build_time_limit_seconds: float = 5.0
    timetable_solve_time_limit_seconds: float = 5.0
    sectioning_time_limit_seconds: float = 5.0
    timetable_random_seed: int = 0
    sectioning_random_seed: int = 0
    timetable_construction: ITC2019TimetableFactorizedLimits = field(
        default_factory=ITC2019TimetableFactorizedLimits
    )
    sectioning_max_conflict_pairs: int = 100_000
    sectioning_max_conflict_terms: int = 100_000
    max_rooms: int = 1_000
    max_courses: int = 1_000
    max_configurations: int = 5_000
    max_subparts: int = 10_000
    max_classes: int = 1_000
    max_distributions: int = 10_000
    max_students: int = 10_000
    max_course_requests: int = 100_000

    def validate(self) -> None:
        for name, value in (
            (
                "timetable_build_time_limit_seconds",
                self.timetable_build_time_limit_seconds,
            ),
            (
                "timetable_solve_time_limit_seconds",
                self.timetable_solve_time_limit_seconds,
            ),
            ("sectioning_time_limit_seconds", self.sectioning_time_limit_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in (
            ("sectioning_max_conflict_pairs", self.sectioning_max_conflict_pairs),
            ("sectioning_max_conflict_terms", self.sectioning_max_conflict_terms),
            ("max_rooms", self.max_rooms),
            ("max_courses", self.max_courses),
            ("max_configurations", self.max_configurations),
            ("max_subparts", self.max_subparts),
            ("max_classes", self.max_classes),
            ("max_distributions", self.max_distributions),
            ("max_students", self.max_students),
            ("max_course_requests", self.max_course_requests),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name, value in (
            ("timetable_random_seed", self.timetable_random_seed),
            ("sectioning_random_seed", self.sectioning_random_seed),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        self.timetable_construction.validate()


@dataclass(frozen=True)
class ITC2019TimetableFactorizedPipelineBudgetTelemetry:
    """Requested limits and observed stage timings without conflating phases."""

    timetable_build_limit_seconds: float
    timetable_solve_limit_seconds: float
    sectioning_limit_seconds: float
    timetable_workers: int
    sectioning_workers: int
    timetable_random_seed: int
    sectioning_random_seed: int
    sectioning_max_conflict_pairs: int
    sectioning_max_conflict_terms: int
    timetable_build_wall_seconds: float = 0.0
    timetable_solver_wall_seconds: float = 0.0
    sectioning_wall_seconds: float = 0.0
    sectioning_model_build_seconds: float = 0.0
    sectioning_solver_wall_seconds: float = 0.0
    pipeline_wall_seconds: float = 0.0


@dataclass(frozen=True)
class ITC2019TimetableFactorizedPipelineResult:
    """Fail-closed pipeline result.

    Candidate fields are populated only when every stage and the final independent
    validator pass.  Timetable, sectioning, validation, and budget evidence remain
    separate so an internal solver status cannot be mistaken for end-to-end success.
    """

    status: str
    build_only: bool
    trusted_synthetic: bool
    timetable_status: str
    timetable_solver_status: str
    sectioning_status: str
    validation_status: str
    timetable_validation_status: str
    final_validation_status: str
    placements: tuple[ITC2019ClassPlacement, ...]
    student_classes: Mapping[str, tuple[str, ...]]
    timetable_telemetry: ITC2019TimetableFactorizedTelemetry | None
    budget_telemetry: ITC2019TimetableFactorizedPipelineBudgetTelemetry
    unsupported_reasons: tuple[str, ...] = ()
    timetable_validation_errors: tuple[str, ...] = ()
    sectioning_validation_errors: tuple[str, ...] = ()
    final_validation_errors: tuple[str, ...] = ()
    execution_errors: tuple[str, ...] = ()

    @property
    def validation_errors(self) -> tuple[str, ...]:
        return (
            self.timetable_validation_errors
            + self.sectioning_validation_errors
            + self.final_validation_errors
        )

    @property
    def has_complete_candidate(self) -> bool:
        return (
            self.status == "COMPLETE"
            and self.timetable_status == "FEASIBLE"
            and self.timetable_solver_status == "OPTIMAL"
            and self.sectioning_status == "OPTIMAL"
            and self.validation_status == "PASSED"
            and bool(self.placements)
            and bool(self.student_classes)
            and not self.unsupported_reasons
            and not self.validation_errors
            and not self.execution_errors
        )


def _exception_text(exc: Exception) -> str:
    try:
        detail = str(exc).strip()
    except Exception:
        detail = ""
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _finite_builtin_number(value: object) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _extract_validator_errors(
    raw_errors: object,
) -> tuple[tuple[str, ...] | None, str | None]:
    """Accept only the validator's exact built-in ``list[str]`` contract."""

    if type(raw_errors) is not list:
        return None, "validator must return an exact built-in list of error strings"
    if any(type(error) is not str or not error.strip() for error in raw_errors):
        return None, "validator errors must be non-empty built-in strings"
    return tuple(raw_errors), None


def _student_classes_snapshot(
    student_classes: object,
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...] | None, str | None]:
    """Create an immutable exact-shape snapshot without trusting custom mappings."""

    if type(student_classes) is not dict:
        return None, "student_classes must be an exact built-in dict"
    try:
        items = tuple(dict.items(student_classes))
    except Exception as exc:
        return None, "student_classes snapshot failed: " + _exception_text(exc)
    if any(
        type(student_id) is not str
        or type(class_ids) is not tuple
        or any(type(class_id) is not str for class_id in class_ids)
        for student_id, class_ids in items
    ):
        return None, (
            "student_classes must map built-in strings to tuples of built-in strings"
        )
    return tuple(
        sorted((student_id, tuple(class_ids)) for student_id, class_ids in items)
    ), None


def _extract_sectioning_own_fields(
    sectioning: object,
) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    """Extract only the exact dataclass instance shape, without attribute fallback."""

    if type(sectioning) is not ITC2019SectioningResult:
        return None, ("sectioner did not return an exact ITC2019SectioningResult",)
    try:
        own_fields = object.__getattribute__(sectioning, "__dict__")
    except Exception as exc:
        return None, (
            "sectioning result own-field extraction failed: " + _exception_text(exc),
        )
    if type(own_fields) is not dict:
        return None, ("sectioning result must have an exact built-in own-field dict",)

    try:
        observed_names = tuple(dict.keys(own_fields))
    except Exception as exc:
        return None, (
            "sectioning result own-field enumeration failed: " + _exception_text(exc),
        )
    if any(type(name) is not str for name in observed_names):
        return None, ("sectioning result contains a non-built-in field name",)

    expected = frozenset(_SECTIONING_RESULT_OWN_FIELDS)
    observed = frozenset(observed_names)
    missing = tuple(
        name for name in _SECTIONING_RESULT_OWN_FIELDS if name not in observed
    )
    extra = tuple(sorted(observed - expected))
    shape_errors: list[str] = []
    if missing:
        shape_errors.append(
            "sectioning result is missing own fields: " + ", ".join(missing)
        )
    if extra:
        shape_errors.append(
            "sectioning result has extra own fields: " + ", ".join(extra)
        )
    if shape_errors:
        return None, tuple(shape_errors)

    try:
        extracted = {
            name: dict.__getitem__(own_fields, name)
            for name in _SECTIONING_RESULT_OWN_FIELDS
        }
    except Exception as exc:
        return None, (
            "sectioning result own-field read failed: " + _exception_text(exc),
        )
    return extracted, ()


def _verify_optimal_sectioning_evidence(
    problem: ITC2019Problem,
    placements: tuple[ITC2019ClassPlacement, ...],
    sectioning: object,
) -> tuple[
    dict[str, tuple[str, ...]] | None,
    ITC2019SectioningResult | None,
    tuple[str, ...],
    str,
]:
    """Recompute and verify the sectioner's complete OPTIMAL certificate.

    The sectioning CP-SAT objective is the raw student-conflict count.  The public
    ``weighted_objective`` field applies the instance's student weight afterward,
    while ``best_bound`` remains in raw conflict units.  Keep those units explicit
    so a contradictory or non-finite result cannot be promoted by feasibility-only
    final validation.
    """

    own_fields, shape_errors = _extract_sectioning_own_fields(sectioning)
    if own_fields is None:
        return None, None, shape_errors, "MALFORMED_RESULT"

    errors: list[str] = []
    status = own_fields["status"]
    safe_status = status if type(status) is str else "MALFORMED_RESULT"
    if type(status) is not str or status != "OPTIMAL":
        errors.append("sectioning status is not the exact built-in string 'OPTIMAL'")

    validation_errors = own_fields["validation_errors"]
    if type(validation_errors) is not tuple or any(
        type(error) is not str for error in validation_errors
    ):
        errors.append(
            "sectioning validation_errors must be a tuple of built-in strings"
        )
    elif validation_errors:
        errors.extend(f"sectioning validation: {error}" for error in validation_errors)

    raw_student_classes = own_fields["student_classes"]
    student_classes: dict[str, tuple[str, ...]] | None = None
    if type(raw_student_classes) is not dict:
        errors.append("sectioning student_classes must be an exact built-in dict")
    else:
        malformed_student_classes = any(
            type(student_id) is not str
            or type(class_ids) is not tuple
            or any(type(class_id) is not str for class_id in class_ids)
            for student_id, class_ids in raw_student_classes.items()
        )
        if malformed_student_classes:
            errors.append(
                "sectioning student_classes must map built-in strings to tuples "
                "of built-in strings"
            )
        else:
            student_classes = {
                student_id: tuple(class_ids)
                for student_id, class_ids in raw_student_classes.items()
            }

    reported_conflicts = own_fields["student_conflicts"]
    if type(reported_conflicts) is not int or reported_conflicts < 0:
        errors.append(
            "sectioning student_conflicts must be a non-negative built-in int"
        )

    reported_weighted = own_fields["weighted_objective"]
    if type(reported_weighted) is not int:
        errors.append("sectioning weighted_objective must be a finite built-in int")

    reported_bound = own_fields["best_bound"]
    if not _finite_builtin_number(reported_bound):
        errors.append("sectioning best_bound must be a finite built-in number")

    for field_name, value in (
        ("wall_time_seconds", own_fields["wall_time_seconds"]),
        ("model_build_seconds", own_fields["model_build_seconds"]),
        ("solver_wall_time_seconds", own_fields["solver_wall_time_seconds"]),
    ):
        if not _finite_builtin_number(value) or value < 0:
            errors.append(f"sectioning {field_name} must be finite and non-negative")

    if student_classes is None:
        return None, None, tuple(errors), safe_status

    try:
        authoritative = score_itc2019_solution(problem, placements, student_classes)
    except Exception as exc:
        errors.append(
            "authoritative sectioning objective recomputation failed: "
            + _exception_text(exc)
        )
        return None, None, tuple(errors), safe_status

    if type(reported_conflicts) is int and reported_conflicts != authoritative.student:
        errors.append(
            "sectioning student_conflicts contradicts the authoritative recomputation"
        )
    if (
        type(reported_weighted) is int
        and reported_weighted != authoritative.weighted_student
    ):
        errors.append(
            "sectioning weighted_objective contradicts the authoritative recomputation"
        )
    if (
        _finite_builtin_number(reported_bound)
        and reported_bound != authoritative.student
    ):
        errors.append(
            "sectioning OPTIMAL best_bound does not equal the authoritative raw "
            "conflict objective"
        )

    if errors:
        return None, None, tuple(errors), safe_status

    assert type(status) is str
    assert type(reported_conflicts) is int
    assert type(reported_weighted) is int
    assert _finite_builtin_number(reported_bound)
    verified_sectioning = ITC2019SectioningResult(
        status=status,
        student_classes=dict(student_classes),
        student_conflicts=reported_conflicts,
        weighted_objective=reported_weighted,
        best_bound=float(reported_bound),
        wall_time_seconds=float(own_fields["wall_time_seconds"]),
        validation_errors=tuple(validation_errors),
        model_build_seconds=float(own_fields["model_build_seconds"]),
        solver_wall_time_seconds=float(own_fields["solver_wall_time_seconds"]),
    )
    return student_classes, verified_sectioning, (), safe_status


def _build_wall_seconds(
    telemetry: ITC2019TimetableFactorizedTelemetry | None,
) -> float:
    if telemetry is None:
        return 0.0
    return sum(max(0.0, seconds) for _phase, seconds in telemetry.phase_wall_seconds)


def _budget_telemetry(
    limits: ITC2019TimetableFactorizedPipelineLimits,
    *,
    started: float,
    timetable: ITC2019TimetableFactorizedResult | None = None,
    sectioning: ITC2019SectioningResult | None = None,
) -> ITC2019TimetableFactorizedPipelineBudgetTelemetry:
    return ITC2019TimetableFactorizedPipelineBudgetTelemetry(
        timetable_build_limit_seconds=limits.timetable_build_time_limit_seconds,
        timetable_solve_limit_seconds=limits.timetable_solve_time_limit_seconds,
        sectioning_limit_seconds=limits.sectioning_time_limit_seconds,
        timetable_workers=1,
        sectioning_workers=1,
        timetable_random_seed=limits.timetable_random_seed,
        sectioning_random_seed=limits.sectioning_random_seed,
        sectioning_max_conflict_pairs=limits.sectioning_max_conflict_pairs,
        sectioning_max_conflict_terms=limits.sectioning_max_conflict_terms,
        timetable_build_wall_seconds=_build_wall_seconds(
            timetable.telemetry if timetable is not None else None
        ),
        timetable_solver_wall_seconds=(
            timetable.solver_wall_time_seconds if timetable is not None else 0.0
        ),
        sectioning_wall_seconds=(
            sectioning.wall_time_seconds if sectioning is not None else 0.0
        ),
        sectioning_model_build_seconds=(
            sectioning.model_build_seconds if sectioning is not None else 0.0
        ),
        sectioning_solver_wall_seconds=(
            sectioning.solver_wall_time_seconds if sectioning is not None else 0.0
        ),
        pipeline_wall_seconds=max(0.0, time.monotonic() - started),
    )


def _result(
    limits: ITC2019TimetableFactorizedPipelineLimits,
    *,
    started: float,
    status: str,
    build_only: bool,
    trusted_synthetic: bool,
    timetable: ITC2019TimetableFactorizedResult | None = None,
    sectioning: ITC2019SectioningResult | None = None,
    timetable_status: str = "NOT_RUN",
    timetable_solver_status: str = "NOT_RUN",
    sectioning_status: str = "NOT_RUN",
    validation_status: str = "NOT_RUN",
    timetable_validation_status: str = "NOT_RUN",
    final_validation_status: str = "NOT_RUN",
    placements: tuple[ITC2019ClassPlacement, ...] = (),
    student_classes: Mapping[str, tuple[str, ...]] | None = None,
    unsupported_reasons: tuple[str, ...] = (),
    timetable_validation_errors: tuple[str, ...] = (),
    sectioning_validation_errors: tuple[str, ...] = (),
    final_validation_errors: tuple[str, ...] = (),
    execution_errors: tuple[str, ...] = (),
) -> ITC2019TimetableFactorizedPipelineResult:
    return ITC2019TimetableFactorizedPipelineResult(
        status=status,
        build_only=build_only,
        trusted_synthetic=trusted_synthetic,
        timetable_status=timetable_status,
        timetable_solver_status=timetable_solver_status,
        sectioning_status=sectioning_status,
        validation_status=validation_status,
        timetable_validation_status=timetable_validation_status,
        final_validation_status=final_validation_status,
        placements=placements,
        student_classes=MappingProxyType(
            {} if student_classes is None else dict(student_classes)
        ),
        timetable_telemetry=timetable.telemetry if timetable is not None else None,
        budget_telemetry=_budget_telemetry(
            limits,
            started=started,
            timetable=timetable,
            sectioning=sectioning,
        ),
        unsupported_reasons=unsupported_reasons,
        timetable_validation_errors=timetable_validation_errors,
        sectioning_validation_errors=sectioning_validation_errors,
        final_validation_errors=final_validation_errors,
        execution_errors=execution_errors,
    )


def run_itc2019_timetable_factorized_pipeline(
    problem: ITC2019Problem,
    *,
    build_only: bool = True,
    trusted_synthetic: bool = False,
    limits: ITC2019TimetableFactorizedPipelineLimits | None = None,
) -> ITC2019TimetableFactorizedPipelineResult:
    """Build or solve an isolated, bounded, trusted-synthetic pipeline.

    ``trusted_synthetic`` is deliberately explicit and has no automatic source-path
    inference.  This module is not imported by official dispatch and exposes no
    parsing or output path.  One deterministic worker is fixed for both CP-SAT
    stages; their seeds and resource budgets remain independently visible.
    """

    started = time.monotonic()
    effective_limits = limits or ITC2019TimetableFactorizedPipelineLimits()
    effective_limits.validate()

    if not build_only and not trusted_synthetic:
        return _result(
            effective_limits,
            started=started,
            status="SYNTHETIC_ENABLEMENT_REQUIRED",
            build_only=False,
            trusted_synthetic=False,
        )
    source_path = problem.source_path
    if type(source_path) is not str or not str.startswith(source_path, "synthetic://"):
        return _result(
            effective_limits,
            started=started,
            status="SYNTHETIC_SOURCE_REQUIRED",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
        )
    for count, maximum, label in (
        (len(problem.rooms), effective_limits.max_rooms, "room"),
        (len(problem.courses), effective_limits.max_courses, "course"),
        (
            len(problem.distributions),
            effective_limits.max_distributions,
            "distribution",
        ),
    ):
        if count > maximum:
            return _result(
                effective_limits,
                started=started,
                status="SYNTHETIC_SCALE_REJECTED",
                build_only=build_only,
                trusted_synthetic=trusted_synthetic,
                unsupported_reasons=(f"{label} count {count} exceeds {maximum}",),
            )

    class_count = 0
    configuration_count = 0
    subpart_count = 0
    for course in problem.courses:
        for configuration in course.configurations:
            configuration_count += 1
            if configuration_count > effective_limits.max_configurations:
                return _result(
                    effective_limits,
                    started=started,
                    status="SYNTHETIC_SCALE_REJECTED",
                    build_only=build_only,
                    trusted_synthetic=trusted_synthetic,
                    unsupported_reasons=(
                        "configuration count exceeds "
                        f"{effective_limits.max_configurations}",
                    ),
                )
            for subpart in configuration.subparts:
                subpart_count += 1
                if subpart_count > effective_limits.max_subparts:
                    return _result(
                        effective_limits,
                        started=started,
                        status="SYNTHETIC_SCALE_REJECTED",
                        build_only=build_only,
                        trusted_synthetic=trusted_synthetic,
                        unsupported_reasons=(
                            f"subpart count exceeds {effective_limits.max_subparts}",
                        ),
                    )
                class_count += len(subpart.classes)
                if class_count > effective_limits.max_classes:
                    return _result(
                        effective_limits,
                        started=started,
                        status="SYNTHETIC_SCALE_REJECTED",
                        build_only=build_only,
                        trusted_synthetic=trusted_synthetic,
                        unsupported_reasons=(
                            f"class count exceeds {effective_limits.max_classes}",
                        ),
                    )
    if class_count == 0:
        return _result(
            effective_limits,
            started=started,
            status="MISSING_CLASSES",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
        )
    if not problem.students:
        return _result(
            effective_limits,
            started=started,
            status="MISSING_STUDENTS",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
        )

    student_count = len(problem.students)
    if student_count > effective_limits.max_students:
        return _result(
            effective_limits,
            started=started,
            status="SYNTHETIC_SCALE_REJECTED",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
            unsupported_reasons=(
                f"student count {student_count} exceeds "
                f"{effective_limits.max_students}",
            ),
        )
    course_request_count = sum(len(student.course_ids) for student in problem.students)
    if course_request_count > effective_limits.max_course_requests:
        return _result(
            effective_limits,
            started=started,
            status="SYNTHETIC_SCALE_REJECTED",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
            unsupported_reasons=(
                "course request count "
                f"{course_request_count} exceeds "
                f"{effective_limits.max_course_requests}",
            ),
        )

    try:
        timetable = solve_itc2019_timetable_factorized(
            problem,
            build_only=build_only,
            build_time_limit_seconds=(
                effective_limits.timetable_build_time_limit_seconds
            ),
            solve_time_limit_seconds=(
                effective_limits.timetable_solve_time_limit_seconds
            ),
            workers=1,
            random_seed=effective_limits.timetable_random_seed,
            limits=effective_limits.timetable_construction,
            include_proto_fingerprint=True,
        )
    except Exception as exc:
        return _result(
            effective_limits,
            started=started,
            status="TIMETABLE_ERROR",
            build_only=build_only,
            trusted_synthetic=trusted_synthetic,
            execution_errors=(_exception_text(exc),),
        )

    if build_only:
        return _result(
            effective_limits,
            started=started,
            status="BUILT" if timetable.status == "BUILT" else "TIMETABLE_FAILED",
            build_only=True,
            trusted_synthetic=trusted_synthetic,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            unsupported_reasons=tuple(timetable.unsupported_reasons),
            timetable_validation_errors=tuple(timetable.validation_errors),
        )

    timetable_accepted = (
        timetable.status == "FEASIBLE"
        and timetable.solver_status == "OPTIMAL"
        and timetable.has_validated_candidate
    )
    if not timetable_accepted:
        return _result(
            effective_limits,
            started=started,
            status="TIMETABLE_FAILED",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            unsupported_reasons=tuple(timetable.unsupported_reasons),
            timetable_validation_errors=tuple(timetable.validation_errors),
        )

    timetable_problem = replace(problem, students=())
    try:
        raw_timetable_errors = validate_itc2019_solution(
            timetable_problem,
            timetable.placements,
            {},
        )
    except Exception as exc:
        return _result(
            effective_limits,
            started=started,
            status="TIMETABLE_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            validation_status="ERROR",
            timetable_validation_status="ERROR",
            execution_errors=(_exception_text(exc),),
        )
    timetable_errors, timetable_schema_error = _extract_validator_errors(
        raw_timetable_errors
    )
    if timetable_errors is None:
        return _result(
            effective_limits,
            started=started,
            status="TIMETABLE_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            validation_status="ERROR",
            timetable_validation_status="ERROR",
            execution_errors=(
                "timetable validator schema error: " + str(timetable_schema_error),
            ),
        )
    if timetable_errors:
        return _result(
            effective_limits,
            started=started,
            status="TIMETABLE_VALIDATION_FAILED",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            validation_status="TIMETABLE_FAILED",
            timetable_validation_status="FAILED",
            timetable_validation_errors=timetable_errors,
        )

    try:
        sectioning = solve_itc2019_student_sectioning(
            problem,
            timetable.placements,
            time_limit_seconds=effective_limits.sectioning_time_limit_seconds,
            workers=1,
            random_seed=effective_limits.sectioning_random_seed,
            max_conflict_pairs=effective_limits.sectioning_max_conflict_pairs,
            max_conflict_terms=effective_limits.sectioning_max_conflict_terms,
            feasibility_first_only=False,
        )
    except Exception as exc:
        return _result(
            effective_limits,
            started=started,
            status="SECTIONING_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            validation_status="TIMETABLE_PASSED",
            timetable_validation_status="PASSED",
            execution_errors=(_exception_text(exc),),
        )

    try:
        (
            student_classes,
            verified_sectioning,
            sectioning_evidence_errors,
            sectioning_status,
        ) = _verify_optimal_sectioning_evidence(
            problem,
            tuple(timetable.placements),
            sectioning,
        )
    except Exception as exc:
        student_classes = None
        verified_sectioning = None
        sectioning_status = "MALFORMED_RESULT"
        sectioning_evidence_errors = (
            "sectioning evidence validation failed closed: " + _exception_text(exc),
        )
    if student_classes is None or verified_sectioning is None:
        return _result(
            effective_limits,
            started=started,
            status="SECTIONING_FAILED",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning_status,
            validation_status="TIMETABLE_PASSED",
            timetable_validation_status="PASSED",
            sectioning_validation_errors=sectioning_evidence_errors,
        )
    sectioning = verified_sectioning
    candidate_snapshot, candidate_snapshot_error = _student_classes_snapshot(
        student_classes
    )
    if candidate_snapshot is None:
        return _result(
            effective_limits,
            started=started,
            status="FINAL_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            sectioning=sectioning,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning.status,
            validation_status="ERROR",
            timetable_validation_status="PASSED",
            final_validation_status="ERROR",
            execution_errors=(
                "candidate snapshot error: " + str(candidate_snapshot_error),
            ),
        )
    publishable_student_classes = MappingProxyType(dict(candidate_snapshot))
    validator_student_classes = dict(candidate_snapshot)
    try:
        raw_final_errors = validate_itc2019_solution(
            problem,
            timetable.placements,
            validator_student_classes,
        )
    except Exception as exc:
        return _result(
            effective_limits,
            started=started,
            status="FINAL_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            sectioning=sectioning,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning.status,
            validation_status="ERROR",
            timetable_validation_status="PASSED",
            final_validation_status="ERROR",
            execution_errors=(_exception_text(exc),),
        )
    validated_snapshot, validator_mutation_error = _student_classes_snapshot(
        validator_student_classes
    )
    if validated_snapshot is None or validated_snapshot != candidate_snapshot:
        detail = (
            validator_mutation_error
            if validated_snapshot is None
            else "validator mutated candidate student_classes"
        )
        return _result(
            effective_limits,
            started=started,
            status="FINAL_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            sectioning=sectioning,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning.status,
            validation_status="ERROR",
            timetable_validation_status="PASSED",
            final_validation_status="ERROR",
            execution_errors=(
                "final validator candidate isolation error: " + str(detail),
            ),
        )
    final_errors, final_schema_error = _extract_validator_errors(raw_final_errors)
    if final_errors is None:
        return _result(
            effective_limits,
            started=started,
            status="FINAL_VALIDATOR_ERROR",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            sectioning=sectioning,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning.status,
            validation_status="ERROR",
            timetable_validation_status="PASSED",
            final_validation_status="ERROR",
            execution_errors=(
                "final validator schema error: " + str(final_schema_error),
            ),
        )
    if final_errors:
        return _result(
            effective_limits,
            started=started,
            status="FINAL_VALIDATION_FAILED",
            build_only=False,
            trusted_synthetic=True,
            timetable=timetable,
            sectioning=sectioning,
            timetable_status=timetable.status,
            timetable_solver_status=timetable.solver_status,
            sectioning_status=sectioning.status,
            validation_status="FINAL_FAILED",
            timetable_validation_status="PASSED",
            final_validation_status="FAILED",
            final_validation_errors=final_errors,
        )

    return _result(
        effective_limits,
        started=started,
        status="COMPLETE",
        build_only=False,
        trusted_synthetic=True,
        timetable=timetable,
        sectioning=sectioning,
        timetable_status=timetable.status,
        timetable_solver_status=timetable.solver_status,
        sectioning_status=sectioning.status,
        validation_status="PASSED",
        timetable_validation_status="PASSED",
        final_validation_status="PASSED",
        placements=tuple(timetable.placements),
        student_classes=publishable_student_classes,
    )


__all__ = [
    "ITC2019TimetableFactorizedPipelineBudgetTelemetry",
    "ITC2019TimetableFactorizedPipelineLimits",
    "ITC2019TimetableFactorizedPipelineResult",
    "run_itc2019_timetable_factorized_pipeline",
]
