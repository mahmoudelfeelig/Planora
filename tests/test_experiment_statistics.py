from __future__ import annotations

from scripts.analyze_experiments import (
    bootstrap_mean_ci,
    exact_sign_test_pvalue,
    load_result_files,
    summarize_rows,
    wilson_interval,
)


def _row(seed: int, room_mode: str, seconds: float, penalty: int, *, fallback: bool = False):
    return {
        "mode": "small_demo",
        "seed": seed,
        "instance_sha256": f"instance-{seed}",
        "requested_room_mode": room_mode,
        "primary_attempt": {"status": 4, "cp_seconds": seconds},
        "penalty_base": penalty,
        "fallback_used": fallback,
        "validation_errors_base": [],
    }


def test_bootstrap_interval_and_sign_test_are_deterministic() -> None:
    assert bootstrap_mean_ci([1, 2, 3], resamples=1000, seed=7) == bootstrap_mean_ci(
        [1, 2, 3], resamples=1000, seed=7
    )
    assert exact_sign_test_pvalue([1, 2, 3, 4]) == 0.125
    assert exact_sign_test_pvalue([0, 0]) is None
    lower, upper = wilson_interval(38, 50)
    assert lower is not None and 0.62 < lower < 0.63
    assert upper is not None and 0.85 < upper < 0.86
    assert wilson_interval(0, 0) == (None, None)


def test_summary_uses_primary_attempts_and_pairs_identical_instances() -> None:
    rows = [
        _row(1, "cp_rooms", 4.0, 10, fallback=True),
        _row(1, "greedy", 1.0, 13),
        _row(2, "cp_rooms", 6.0, 12),
        _row(2, "greedy", 2.0, 14),
    ]
    result = summarize_rows(rows)

    strict = next(item for item in result["conditions"] if item["room_mode"] == "cp_rooms")
    assert strict["fallback_runs"] == 1
    assert strict["cp_seconds_median"] == 5.0
    assert strict["primary_feasible_rate_wilson_ci95"][0] is not None

    comparison = result["paired_comparisons"][0]
    assert comparison["paired_runs"] == 2
    assert comparison["cp_seconds_left_minus_right_median"] == 3.5
    assert comparison["paired_effective_runs"] == 1
    assert comparison["effective_cp_seconds_left_minus_right_median"] == 4.0
    assert result["publication_gate"]["status"] == "NO-GO"


def test_publication_gate_requires_30_unique_validated_instances_per_condition() -> None:
    rows = [_row(seed, "cp_rooms", 1.0, seed) for seed in range(1, 31)]
    result = summarize_rows(rows)

    assert result["publication_gate"]["status"] == "PASS"
    assert result["conditions"][0]["unique_effective_instances"] == 30

    duplicate = [_row(1, "cp_rooms", 1.0, seed) for seed in range(1, 31)]
    duplicate_result = summarize_rows(duplicate)
    assert duplicate_result["publication_gate"]["status"] == "NO-GO"
    assert duplicate_result["conditions"][0]["unique_effective_instances"] == 1


def test_publication_gate_rejects_fallback_or_validator_failure() -> None:
    rows = [_row(seed, "cp_rooms", 1.0, seed) for seed in range(1, 31)]
    rows[0]["fallback_used"] = True
    rows[1]["validation_errors_base"] = ["hard conflict"]

    result = summarize_rows(rows)
    assert result["conditions"][0]["unique_effective_instances"] == 28
    assert result["publication_gate"]["status"] == "NO-GO"


def test_result_shards_are_combined_with_content_hash_provenance(tmp_path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"seed": 1}\n', encoding="utf-8")
    second.write_text('{"seed": 2}\n{"seed": 3}\n', encoding="utf-8")

    rows, sources = load_result_files([first, second])

    assert [row["seed"] for row in rows] == [1, 2, 3]
    assert [source["rows"] for source in sources] == [1, 2]
    assert all(len(source["sha256"]) == 64 for source in sources)
