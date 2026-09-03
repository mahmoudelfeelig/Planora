from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import benchmarks.itc2019_timetable_factorized as timetable_factorized
import benchmarks.itc2019_timetable_factorized_pipeline as pipeline
from benchmarks.itc2019 import (
    ITC2019Class,
    ITC2019Configuration,
    ITC2019Course,
    ITC2019Distribution,
    ITC2019OptimizationWeights,
    ITC2019Problem,
    ITC2019Room,
    ITC2019RoomOption,
    ITC2019SectioningResult,
    ITC2019Student,
    ITC2019Subpart,
    ITC2019TimeOption,
    ITC2019Unavailable,
)
from benchmarks.itc2019_timetable_factorized import (
    ITC2019TimetableFactorizedLimits,
)
from benchmarks.itc2019_timetable_factorized_pipeline import (
    ITC2019TimetableFactorizedPipelineLimits,
    run_itc2019_timetable_factorized_pipeline,
)


_SECTIONING_RESULT_FIELDS = (
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


class _HostileStr(str):
    pass


class _HostileInt(int):
    pass


class _HostileFloat(float):
    pass


class _HostileDict(dict[str, tuple[str, ...]]):
    pass


class _HostileTuple(tuple[str, ...]):
    pass


class _HostileList(list[str]):
    pass


class _EmptyCustomIterable:
    def __init__(self) -> None:
        self.iterated = False

    def __iter__(self):
        self.iterated = True
        return iter(())


def _problem(
    *,
    students: tuple[ITC2019Student, ...] | None = None,
    distributions: tuple[ITC2019Distribution, ...] = (),
    unavailable: tuple[ITC2019Unavailable, ...] = (),
) -> ITC2019Problem:
    klass = ITC2019Class(
        id="C1",
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=(ITC2019TimeOption("1", 0, 1, "1"),),
        room_options=(ITC2019RoomOption("R1"),),
    )
    course = ITC2019Course(
        id="COURSE1",
        configurations=(
            ITC2019Configuration(
                id="CONFIG1",
                subparts=(ITC2019Subpart(id="SUBPART1", classes=(klass,)),),
            ),
        ),
    )
    return ITC2019Problem(
        name="pipeline-synthetic",
        nr_days=1,
        slots_per_day=4,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=(
            ITC2019Room(
                id="R1",
                capacity=10,
                travel=(),
                unavailable=unavailable,
            ),
        ),
        courses=(course,),
        distributions=distributions,
        students=(ITC2019Student("S1", ("COURSE1",)),)
        if students is None
        else students,
        source_path="synthetic://pipeline-test",
    )


def _conflicting_problem() -> ITC2019Problem:
    def course(course_id: str, class_id: str, room_id: str) -> ITC2019Course:
        klass = ITC2019Class(
            id=class_id,
            limit=10,
            parent_id=None,
            room_required=True,
            time_options=(ITC2019TimeOption("1", 0, 1, "1"),),
            room_options=(ITC2019RoomOption(room_id),),
        )
        return ITC2019Course(
            id=course_id,
            configurations=(
                ITC2019Configuration(
                    id=f"{course_id}-CONFIG",
                    subparts=(
                        ITC2019Subpart(id=f"{course_id}-SUBPART", classes=(klass,)),
                    ),
                ),
            ),
        )

    return ITC2019Problem(
        name="pipeline-conflicting-synthetic",
        nr_days=1,
        slots_per_day=4,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(student=5),
        rooms=(
            ITC2019Room(id="R1", capacity=10, travel=(), unavailable=()),
            ITC2019Room(id="R2", capacity=10, travel=(), unavailable=()),
        ),
        courses=(course("COURSE1", "C1", "R1"), course("COURSE2", "C2", "R2")),
        distributions=(),
        students=(ITC2019Student("S1", ("COURSE1", "COURSE2")),),
        source_path="synthetic://pipeline-conflicting-test",
    )


def _limits() -> ITC2019TimetableFactorizedPipelineLimits:
    return ITC2019TimetableFactorizedPipelineLimits(
        timetable_build_time_limit_seconds=1.25,
        timetable_solve_time_limit_seconds=2.5,
        sectioning_time_limit_seconds=3.75,
        timetable_random_seed=17,
        sectioning_random_seed=23,
        timetable_construction=ITC2019TimetableFactorizedLimits(
            max_domain_values=100,
            max_required_pair_relations=100,
            max_sparse_room_constraints=100,
            max_room_pair_evaluations=100,
        ),
        sectioning_max_conflict_pairs=101,
        sectioning_max_conflict_terms=102,
        max_classes=10,
        max_students=20,
        max_course_requests=30,
    )


def _valid_sectioning_result() -> ITC2019SectioningResult:
    return ITC2019SectioningResult(
        status="OPTIMAL",
        student_classes={"S1": ("C1",)},
        student_conflicts=0,
        weighted_objective=0,
        best_bound=0.0,
        wall_time_seconds=0.01,
        validation_errors=(),
        model_build_seconds=0.001,
        solver_wall_time_seconds=0.009,
    )


def _assert_sectioning_rejected_without_candidate(
    result: pipeline.ITC2019TimetableFactorizedPipelineResult,
) -> None:
    assert result.status == "SECTIONING_FAILED"
    assert result.sectioning_validation_errors
    assert result.final_validation_status == "NOT_RUN"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_default_build_only_invokes_neither_solver_nor_sectioner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("solver or sectioner was invoked")

    monkeypatch.setattr(timetable_factorized.cp_model, "CpSolver", forbidden)
    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", forbidden)

    result = run_itc2019_timetable_factorized_pipeline(_problem())

    assert result.status == "BUILT"
    assert result.build_only is True
    assert result.timetable_status == "BUILT"
    assert result.timetable_solver_status == "NOT_RUN"
    assert result.sectioning_status == "NOT_RUN"
    assert result.validation_status == "NOT_RUN"
    assert result.timetable_validation_status == "NOT_RUN"
    assert result.final_validation_status == "NOT_RUN"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_explicit_pipeline_keeps_all_resource_budgets_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, dict[str, Any]] = {}
    original_timetable = pipeline.solve_itc2019_timetable_factorized
    original_sectioning = pipeline.solve_itc2019_student_sectioning

    def capture_timetable(*args: object, **kwargs: Any):
        seen["timetable"] = dict(kwargs)
        return original_timetable(*args, **kwargs)

    def capture_sectioning(*args: object, **kwargs: Any):
        seen["sectioning"] = dict(kwargs)
        return original_sectioning(*args, **kwargs)

    monkeypatch.setattr(
        pipeline, "solve_itc2019_timetable_factorized", capture_timetable
    )
    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", capture_sectioning
    )

    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.has_complete_candidate
    assert seen["timetable"] == {
        "build_only": False,
        "build_time_limit_seconds": 1.25,
        "solve_time_limit_seconds": 2.5,
        "workers": 1,
        "random_seed": 17,
        "limits": _limits().timetable_construction,
        "include_proto_fingerprint": True,
    }
    assert seen["sectioning"] == {
        "time_limit_seconds": 3.75,
        "workers": 1,
        "random_seed": 23,
        "max_conflict_pairs": 101,
        "max_conflict_terms": 102,
        "feasibility_first_only": False,
    }
    assert result.budget_telemetry.timetable_build_limit_seconds == 1.25
    assert result.budget_telemetry.timetable_solve_limit_seconds == 2.5
    assert result.budget_telemetry.sectioning_limit_seconds == 3.75
    assert result.budget_telemetry.timetable_workers == 1
    assert result.budget_telemetry.sectioning_workers == 1


@pytest.mark.parametrize("sectioning_status", ["INFEASIBLE", "DEADLINE_EXCEEDED"])
def test_sectioner_failure_suppresses_every_candidate_field(
    monkeypatch: pytest.MonkeyPatch,
    sectioning_status: str,
) -> None:
    def failed_sectioning(*_args: object, **_kwargs: object) -> ITC2019SectioningResult:
        return ITC2019SectioningResult(
            status=sectioning_status,
            student_classes={},
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=0.01,
        )

    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", failed_sectioning)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "SECTIONING_FAILED"
    assert result.sectioning_status == sectioning_status
    assert result.validation_status == "TIMETABLE_PASSED"
    assert result.timetable_validation_status == "PASSED"
    assert result.final_validation_status == "NOT_RUN"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


@pytest.mark.parametrize(
    ("student_conflicts", "weighted_objective", "best_bound"),
    [
        (0, 999, 0.0),
        (0, 0, 999.0),
        (0, float("nan"), 0.0),
        (0, float("inf"), 0.0),
        (0, 0, float("nan")),
        (0, 0, float("inf")),
        (0, 0, float("-inf")),
        (1, 5, 1.0),
    ],
    ids=(
        "contradictory-weighted-objective",
        "contradictory-best-bound",
        "nan-weighted-objective",
        "infinite-weighted-objective",
        "nan-best-bound",
        "positive-infinite-best-bound",
        "negative-infinite-best-bound",
        "contradictory-conflict-count",
    ),
)
def test_optimal_sectioning_evidence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    student_conflicts: object,
    weighted_objective: object,
    best_bound: object,
) -> None:
    def forged_sectioning(*_args: object, **_kwargs: object) -> ITC2019SectioningResult:
        return ITC2019SectioningResult(
            status="OPTIMAL",
            student_classes={"S1": ("C1",)},
            student_conflicts=student_conflicts,
            weighted_objective=weighted_objective,
            best_bound=best_bound,
            wall_time_seconds=0.01,
        )

    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", forged_sectioning)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "SECTIONING_FAILED"
    assert result.sectioning_status == "OPTIMAL"
    assert result.sectioning_validation_errors
    assert result.final_validation_status == "NOT_RUN"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


@pytest.mark.parametrize(
    "student_classes",
    [
        {},
        {"S1": ()},
        {"S1": ("UNKNOWN",)},
        {"S1": ["C1"]},
    ],
    ids=("missing-student", "incomplete", "unknown-class", "malformed-class-sequence"),
)
def test_malformed_optimal_sectioning_suppresses_candidate(
    monkeypatch: pytest.MonkeyPatch,
    student_classes: object,
) -> None:
    def malformed_sectioning(
        *_args: object, **_kwargs: object
    ) -> ITC2019SectioningResult:
        return ITC2019SectioningResult(
            status="OPTIMAL",
            student_classes=student_classes,
            student_conflicts=0,
            weighted_objective=0,
            best_bound=0.0,
            wall_time_seconds=0.01,
        )

    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", malformed_sectioning
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "SECTIONING_FAILED"
    assert result.sectioning_validation_errors
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


@pytest.mark.parametrize("missing_field", _SECTIONING_RESULT_FIELDS)
def test_every_missing_sectioning_field_is_contained_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    missing_field: str,
) -> None:
    def missing_field_result(*_args: object, **_kwargs: object) -> object:
        result = _valid_sectioning_result()
        object.__delattr__(result, missing_field)
        return result

    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", missing_field_result
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    _assert_sectioning_rejected_without_candidate(result)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("status", _HostileStr("OPTIMAL")),
        ("student_classes", _HostileDict({"S1": ("C1",)})),
        ("student_classes", {_HostileStr("S1"): ("C1",)}),
        ("student_classes", {"S1": _HostileTuple(("C1",))}),
        ("student_classes", {"S1": (_HostileStr("C1"),)}),
        ("student_conflicts", True),
        ("student_conflicts", _HostileInt(0)),
        ("weighted_objective", True),
        ("weighted_objective", _HostileInt(0)),
        ("best_bound", True),
        ("best_bound", _HostileFloat(0.0)),
        ("validation_errors", []),
        ("validation_errors", (_HostileStr("forged"),)),
        ("validation_errors", _HostileTuple(())),
    ],
    ids=(
        "status-subclass",
        "dict-subclass",
        "student-id-subclass",
        "class-tuple-subclass",
        "class-id-subclass",
        "bool-conflicts",
        "int-subclass-conflicts",
        "bool-weighted-objective",
        "int-subclass-weighted-objective",
        "bool-bound",
        "float-subclass-bound",
        "list-validation-errors",
        "str-subclass-validation-error",
        "tuple-subclass-validation-errors",
    ),
)
def test_sectioning_field_types_are_exact_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    invalid_value: object,
) -> None:
    def malformed_result(*_args: object, **_kwargs: object) -> object:
        result = _valid_sectioning_result()
        object.__setattr__(result, field_name, invalid_value)
        return result

    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", malformed_result)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    _assert_sectioning_rejected_without_candidate(result)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        (field_name, invalid_value)
        for field_name in (
            "wall_time_seconds",
            "model_build_seconds",
            "solver_wall_time_seconds",
        )
        for invalid_value in (
            True,
            _HostileFloat(0.0),
            float("nan"),
            float("inf"),
            float("-inf"),
            -1.0,
        )
    ],
)
def test_sectioning_timing_evidence_is_exact_finite_and_non_negative(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    invalid_value: object,
) -> None:
    def malformed_timing(*_args: object, **_kwargs: object) -> object:
        result = _valid_sectioning_result()
        object.__setattr__(result, field_name, invalid_value)
        return result

    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", malformed_timing)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    _assert_sectioning_rejected_without_candidate(result)


@pytest.mark.parametrize("extra_field", ["extra", "is_feasible", _HostileStr("shadow")])
def test_extra_or_shadow_sectioning_fields_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    extra_field: str,
) -> None:
    def extra_field_result(*_args: object, **_kwargs: object) -> object:
        result = _valid_sectioning_result()
        vars(result)[extra_field] = True
        return result

    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", extra_field_result
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    _assert_sectioning_rejected_without_candidate(result)


def test_sectioning_subclass_and_proxy_fail_without_attribute_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SectioningSubclass(ITC2019SectioningResult):
        pass

    class HostileProxy:
        def __getattr__(self, _name: str) -> object:
            raise AssertionError("proxy attributes must not be accessed")

    hostile_results: tuple[object, ...] = (
        SectioningSubclass(**vars(_valid_sectioning_result())),
        HostileProxy(),
    )
    for hostile_result in hostile_results:
        monkeypatch.setattr(
            pipeline,
            "solve_itc2019_student_sectioning",
            lambda *_args, _result=hostile_result, **_kwargs: _result,
        )
        result = run_itc2019_timetable_factorized_pipeline(
            _problem(),
            build_only=False,
            trusted_synthetic=True,
            limits=_limits(),
        )
        _assert_sectioning_rejected_without_candidate(result)


def test_unexpected_sectioning_evidence_exception_is_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "solve_itc2019_student_sectioning",
        lambda *_args, **_kwargs: _valid_sectioning_result(),
    )

    def broken_evidence_checker(*_args: object, **_kwargs: object) -> None:
        raise AttributeError("synthetic evidence extraction fault")

    monkeypatch.setattr(
        pipeline, "_verify_optimal_sectioning_evidence", broken_evidence_checker
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    _assert_sectioning_rejected_without_candidate(result)


def test_independent_timetable_validator_failure_prevents_sectioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sectioner_called = False

    def reject_timetable(*_args: object, **_kwargs: object) -> list[str]:
        return ["independent timetable rejection"]

    def forbidden_sectioner(*_args: object, **_kwargs: object) -> None:
        nonlocal sectioner_called
        sectioner_called = True

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", reject_timetable)
    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", forbidden_sectioner
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "TIMETABLE_VALIDATION_FAILED"
    assert result.validation_status == "TIMETABLE_FAILED"
    assert result.timetable_validation_status == "FAILED"
    assert result.final_validation_status == "NOT_RUN"
    assert result.validation_errors == ("independent timetable rejection",)
    assert sectioner_called is False
    assert result.placements == ()
    assert result.student_classes == {}


def test_final_validator_failure_suppresses_an_otherwise_complete_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def validate(*_args: object, **_kwargs: object) -> list[str]:
        nonlocal calls
        calls += 1
        return [] if calls == 1 else ["whole-solution rejection"]

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", validate)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert calls == 2
    assert result.status == "FINAL_VALIDATION_FAILED"
    assert result.validation_status == "FINAL_FAILED"
    assert result.timetable_validation_status == "PASSED"
    assert result.final_validation_status == "FAILED"
    assert result.validation_errors == ("whole-solution rejection",)
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def _assert_final_validator_error_without_candidate(
    result: pipeline.ITC2019TimetableFactorizedPipelineResult,
) -> None:
    assert result.status == "FINAL_VALIDATOR_ERROR"
    assert result.validation_status == "ERROR"
    assert result.timetable_validation_status == "PASSED"
    assert result.final_validation_status == "ERROR"
    assert result.execution_errors
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_final_validator_mutation_and_empty_error_list_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def mutate_candidate(
        _problem: object,
        _placements: object,
        student_classes: dict[str, tuple[str, ...]],
    ) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            student_classes["S1"] = ("UNKNOWN",)
        return []

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", mutate_candidate)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert calls == 2
    _assert_final_validator_error_without_candidate(result)


def test_validator_working_copy_is_never_the_published_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    retained: list[dict[str, tuple[str, ...]]] = []

    def retain_candidate(
        _problem: object,
        _placements: object,
        student_classes: dict[str, tuple[str, ...]],
    ) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            retained.append(student_classes)
        return []

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", retain_candidate)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "COMPLETE"
    assert result.has_complete_candidate
    assert retained and retained[0] is not result.student_classes
    retained[0]["S1"] = ("UNKNOWN",)
    assert result.student_classes == {"S1": ("C1",)}


_EMPTY_CUSTOM_ITERABLE = _EmptyCustomIterable()


@pytest.mark.parametrize(
    "hostile_return",
    [
        "",
        {},
        set(),
        (),
        _EMPTY_CUSTOM_ITERABLE,
        _HostileList(),
        [""],
        ["   "],
        [1],
        [_HostileStr("forged error")],
    ],
    ids=(
        "empty-string",
        "empty-dict",
        "empty-set",
        "empty-tuple",
        "custom-iterable",
        "list-subclass",
        "empty-error-string",
        "whitespace-error-string",
        "non-string-error",
        "string-subclass-error",
    ),
)
def test_final_validator_requires_exact_builtin_error_list_schema(
    monkeypatch: pytest.MonkeyPatch,
    hostile_return: object,
) -> None:
    calls = 0

    def hostile_schema(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return [] if calls == 1 else hostile_return

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", hostile_schema)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert calls == 2
    _assert_final_validator_error_without_candidate(result)
    if hostile_return is _EMPTY_CUSTOM_ITERABLE:
        assert not _EMPTY_CUSTOM_ITERABLE.iterated


def test_timetable_validator_schema_error_prevents_sectioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sectioner_called = False

    def invalid_schema(*_args: object, **_kwargs: object) -> tuple[()]:
        return ()

    def forbidden_sectioner(*_args: object, **_kwargs: object) -> None:
        nonlocal sectioner_called
        sectioner_called = True

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", invalid_schema)
    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", forbidden_sectioner
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "TIMETABLE_VALIDATOR_ERROR"
    assert result.validation_status == "ERROR"
    assert result.timetable_validation_status == "ERROR"
    assert result.execution_errors
    assert sectioner_called is False
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_timetable_validator_exception_is_contained_before_sectioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sectioner_called = False

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic timetable validator fault")

    def forbidden_sectioner(*_args: object, **_kwargs: object) -> None:
        nonlocal sectioner_called
        sectioner_called = True

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", explode)
    monkeypatch.setattr(
        pipeline, "solve_itc2019_student_sectioning", forbidden_sectioner
    )
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "TIMETABLE_VALIDATOR_ERROR"
    assert result.execution_errors == (
        "RuntimeError: synthetic timetable validator fault",
    )
    assert sectioner_called is False
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_synthetic_success_is_deterministic_and_complete() -> None:
    results = tuple(
        run_itc2019_timetable_factorized_pipeline(
            _problem(),
            build_only=False,
            trusted_synthetic=True,
            limits=_limits(),
        )
        for _ in range(4)
    )
    first = results[0]

    assert all(result.status == "COMPLETE" for result in results)
    assert all(result.timetable_status == "FEASIBLE" for result in results)
    assert all(result.timetable_solver_status == "OPTIMAL" for result in results)
    assert all(result.sectioning_status == "OPTIMAL" for result in results)
    assert all(result.validation_status == "PASSED" for result in results)
    assert all(result.timetable_validation_status == "PASSED" for result in results)
    assert all(result.final_validation_status == "PASSED" for result in results)
    assert all(result.placements == first.placements for result in results)
    assert all(result.student_classes == {"S1": ("C1",)} for result in results)
    assert all(result.has_complete_candidate for result in results)
    with pytest.raises(TypeError):
        first.student_classes["S1"] = ()


def test_nonzero_weighted_objective_uses_raw_conflict_optimal_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[ITC2019SectioningResult] = []
    original = pipeline.solve_itc2019_student_sectioning

    def capture(*args: object, **kwargs: Any) -> ITC2019SectioningResult:
        result = original(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(pipeline, "solve_itc2019_student_sectioning", capture)
    result = run_itc2019_timetable_factorized_pipeline(
        _conflicting_problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "COMPLETE"
    assert result.has_complete_candidate
    assert len(observed) == 1
    assert observed[0].student_conflicts == 1
    assert observed[0].weighted_objective == 5
    assert observed[0].best_bound == 1.0


def test_hostile_source_path_subclass_cannot_forge_synthetic_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HostileSourcePath(str):
        def startswith(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def __str__(self) -> str:
            return "synthetic://forged"

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("timetable builder was invoked")

    monkeypatch.setattr(pipeline, "solve_itc2019_timetable_factorized", forbidden)
    problem = replace(_problem(), source_path=HostileSourcePath("official.xml"))
    result = run_itc2019_timetable_factorized_pipeline(
        problem,
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "SYNTHETIC_SOURCE_REQUIRED"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


@pytest.mark.parametrize(
    ("problem", "trusted_synthetic", "expected_status"),
    [
        (_problem(), False, "SYNTHETIC_ENABLEMENT_REQUIRED"),
        (
            replace(_problem(), source_path="not-synthetic.xml"),
            True,
            "SYNTHETIC_SOURCE_REQUIRED",
        ),
        (_problem(students=()), True, "MISSING_STUDENTS"),
        (replace(_problem(), courses=()), True, "MISSING_CLASSES"),
        (
            _problem(unavailable=(ITC2019Unavailable("1", 0, 1, "1"),)),
            True,
            "TIMETABLE_FAILED",
        ),
    ],
    ids=(
        "explicit-enablement",
        "synthetic-source-marker",
        "missing-students",
        "missing-classes",
        "infeasible-timetable",
    ),
)
def test_no_candidate_states_fail_closed(
    problem: ITC2019Problem,
    trusted_synthetic: bool,
    expected_status: str,
) -> None:
    result = run_itc2019_timetable_factorized_pipeline(
        problem,
        build_only=False,
        trusted_synthetic=trusted_synthetic,
        limits=_limits(),
    )

    assert result.status == expected_status
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_timetable_construction_timeout_returns_no_candidate() -> None:
    limits = replace(_limits(), timetable_build_time_limit_seconds=1e-12)

    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=limits,
    )

    assert result.status == "TIMETABLE_FAILED"
    assert result.timetable_status == "DEADLINE_EXCEEDED"
    assert result.sectioning_status == "NOT_RUN"
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_validator_exception_is_contained_and_suppresses_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def validate(*_args: object, **_kwargs: object) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic validator fault")
        return []

    monkeypatch.setattr(pipeline, "validate_itc2019_solution", validate)
    result = run_itc2019_timetable_factorized_pipeline(
        _problem(),
        build_only=False,
        trusted_synthetic=True,
        limits=_limits(),
    )

    assert result.status == "FINAL_VALIDATOR_ERROR"
    assert result.timetable_validation_status == "PASSED"
    assert result.final_validation_status == "ERROR"
    assert result.execution_errors == ("RuntimeError: synthetic validator fault",)
    assert not result.has_complete_candidate
    assert result.placements == ()
    assert result.student_classes == {}


def test_synthetic_scale_rejection_happens_before_timetable_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem(
        students=(
            ITC2019Student("S1", ("COURSE1",)),
            ITC2019Student("S2", ("COURSE1",)),
        )
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("timetable builder was invoked")

    monkeypatch.setattr(pipeline, "solve_itc2019_timetable_factorized", forbidden)
    result = run_itc2019_timetable_factorized_pipeline(
        problem,
        build_only=False,
        trusted_synthetic=True,
        limits=replace(_limits(), max_students=1),
    )

    assert result.status == "SYNTHETIC_SCALE_REJECTED"
    assert result.timetable_status == "NOT_RUN"
    assert result.unsupported_reasons
    assert not result.has_complete_candidate


def test_pipeline_has_no_serialization_or_publication_surface() -> None:
    exported = set(pipeline.__all__)
    assert not any(
        token in name.lower()
        for name in exported
        for token in ("write", "serialize", "publish", "dispatch", "launch")
    )
