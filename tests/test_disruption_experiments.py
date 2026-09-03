from __future__ import annotations

from scripts.run_disruption_experiments import run_disruption_trials


def test_disruption_experiment_is_seeded_and_records_recovery_metrics() -> None:
    result = run_disruption_trials(
        "small_demo",
        71,
        room_mode="greedy",
        time_limit_seconds=10,
        trials_per_type=1,
    )

    assert result["baseline_feasible"] is True
    assert result["baseline_schedule_sha256"]
    assert {trial["type"] for trial in result["trials"]} == {
        "staff_outage",
        "room_outage",
    }
    assert all(0.0 <= trial["recovery_rate"] <= 1.0 for trial in result["trials"])
    assert all(trial["repair_seconds"] >= 0.0 for trial in result["trials"])
