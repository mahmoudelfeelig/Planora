from __future__ import annotations

from scripts.benchmark_local_app import run_local_app_benchmark


def test_local_application_path_solves_validates_and_reports_model_size() -> None:
    report = run_local_app_benchmark(
        mode="small_demo",
        room_mode="decomposed",
        use_objective=False,
        time_limit_seconds=15.0,
        workers=1,
        random_seed=1,
        include_desktop_startup=False,
    )
    assert report["feasible"] is True
    assert report["validation_error_count"] == 0
    assert report["schedule_rows"] == report["instance"]["activities"]
    assert report["model"]["variables"] > 0
    assert report["model"]["constraints"] > 0
    assert report["research_metrics"]["hard_conflict_count"] == 0
