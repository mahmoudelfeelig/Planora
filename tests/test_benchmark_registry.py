from __future__ import annotations

import json
import subprocess
import sys

import pytest

import benchmarks
from benchmarks.corpus import (
    BENCHMARK_FAMILIES,
    BENCHMARK_FAMILY_REGISTRY,
    get_benchmark_family,
    resolve_benchmark_entrypoint,
)


EXPECTED_FAMILIES = {
    "cbctt-extended",
    "itc2007-cbctt",
    "itc2007-exam",
    "itc2007-pe",
    "itc2019",
    "unitime-native",
    "xhstt",
}


def test_registry_describes_each_native_benchmark_lane_unambiguously() -> None:
    assert set(BENCHMARK_FAMILY_REGISTRY) == EXPECTED_FAMILIES
    assert len(BENCHMARK_FAMILIES) == len(EXPECTED_FAMILIES)

    official_external = {
        family.family_id
        for family in BENCHMARK_FAMILIES
        if family.official_validator_available
    }
    assert official_external == {"itc2007-cbctt", "itc2007-pe"}
    assert all(family.solver_available for family in BENCHMARK_FAMILIES)

    unitime = get_benchmark_family("unitime-native")
    assert unitime.score_status == "native_non_official"
    assert unitime.official_validator_available is False
    assert "not represented as an official" in unitime.notes

    itc2019 = get_benchmark_family("itc2019")
    assert itc2019.problem_kinds == ("course_timetabling", "student_sectioning")
    assert itc2019.score_status == "independent_official_semantics"
    assert itc2019.official_validator_available is False

    xhstt = get_benchmark_family("xhstt")
    assert xhstt.problem_kinds == ("high_school_timetabling",)
    assert "fail_closed" in xhstt.validator_status

    # Descriptors are directly serializable for CLIs, UIs, and experiment manifests.
    json.dumps([family.to_dict() for family in BENCHMARK_FAMILIES])


def test_every_declared_entrypoint_exists_and_is_callable() -> None:
    for family in BENCHMARK_FAMILIES:
        references = (
            family.parser_entrypoint,
            family.scorer_entrypoint,
            family.validator_entrypoint,
            family.solver_entrypoint,
            family.official_validator_entrypoint,
        )
        for reference in references:
            if reference is not None:
                assert callable(resolve_benchmark_entrypoint(reference)), (
                    family.family_id,
                    reference,
                )


def test_package_exports_are_lazy_and_backwards_compatible() -> None:
    probe = """
import json
import sys
import benchmarks

unexpected = sorted(
    name for name in (
        'benchmarks.cbctt_native',
        'benchmarks.itc2007_exam',
        'benchmarks.itc2007_pe',
        'benchmarks.itc2019',
        'benchmarks.unitime_native',
        'benchmarks.xhstt',
        'ortools',
        'lxml',
    )
    if name in sys.modules
)
print(json.dumps(unexpected))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []

    assert benchmarks.parse_itc2007_exam is resolve_benchmark_entrypoint(
        "benchmarks.itc2007_exam:parse_itc2007_exam"
    )
    assert benchmarks.solve_cbctt_native is resolve_benchmark_entrypoint(
        "benchmarks.cbctt_native:solve_cbctt_native"
    )
    assert benchmarks.solve_itc2019_native is resolve_benchmark_entrypoint(
        "benchmarks.itc2019:solve_itc2019_native"
    )
    assert benchmarks.solve_unitime_native is resolve_benchmark_entrypoint(
        "benchmarks.unitime_native:solve_unitime_native"
    )
    assert benchmarks.solve_xhstt is resolve_benchmark_entrypoint(
        "benchmarks.xhstt:solve_xhstt"
    )


def test_registry_is_immutable_and_rejects_bad_references() -> None:
    with pytest.raises(TypeError):
        BENCHMARK_FAMILY_REGISTRY["new"] = BENCHMARK_FAMILIES[0]  # type: ignore[index]
    with pytest.raises(KeyError, match="available families"):
        get_benchmark_family("does-not-exist")
    with pytest.raises(ValueError, match="module:attribute"):
        resolve_benchmark_entrypoint("not-an-entrypoint")
    with pytest.raises(ImportError, match="does not exist"):
        resolve_benchmark_entrypoint("benchmarks.corpus:missing")
