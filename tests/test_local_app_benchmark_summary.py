from __future__ import annotations

import pytest

from scripts.benchmark_local_app import summarize_benchmark_runs


def _report(total: float, solve: float, *, valid: bool = True) -> dict:
    return {
        "mode": "small_demo",
        "room_mode": "decomposed",
        "use_objective": False,
        "time_limit_seconds": 10.0,
        "workers": 1,
        "random_seed": 1,
        "include_desktop_startup": False,
        "feasible": valid,
        "validation_error_count": 0 if valid else 1,
        "measured_total_seconds": total,
        "peak_rss_kib": 100,
        "stage_seconds": {
            "model": 0.1,
            "solve": solve,
            "validate": 0.01,
            "desktop_startup": None,
        },
    }


def test_repeated_benchmark_summary_reports_tail_and_failed_runs() -> None:
    summary = summarize_benchmark_runs(
        [_report(1.0, 0.7), _report(2.0, 1.4), _report(3.0, 2.1, valid=False)]
    )

    assert summary["repetitions"] == 3
    assert summary["valid_runs"] == 2
    assert summary["all_runs_valid"] is False
    assert summary["timings"]["measured_total_seconds"]["median"] == 2.0
    assert summary["timings"]["measured_total_seconds"]["p95"] == pytest.approx(2.9)
    assert summary["timings"]["desktop_startup_seconds"]["median"] is None
    assert summary["configuration"]["time_limit_seconds"] == 10.0
    assert summary["configuration"]["include_desktop_startup"] is False


def test_repeated_benchmark_summary_requires_at_least_one_run() -> None:
    with pytest.raises(ValueError, match="At least one"):
        summarize_benchmark_runs([])
