from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_mean_ci(
    values: Iterable[float], *, confidence: float = 0.95, resamples: int = 10_000, seed: int = 0
) -> tuple[float | None, float | None]:
    sample = [float(value) for value in values]
    if not sample:
        return None, None
    if len(sample) == 1:
        return sample[0], sample[0]
    rng = random.Random(seed)
    means = [
        statistics.fmean(rng.choice(sample) for _ in sample)
        for _ in range(int(resamples))
    ]
    alpha = (1.0 - float(confidence)) / 2.0
    return _quantile(means, alpha), _quantile(means, 1.0 - alpha)


def exact_sign_test_pvalue(differences: Iterable[float]) -> float | None:
    nonzero = [float(value) for value in differences if float(value) != 0.0]
    if not nonzero:
        return None
    positives = sum(value > 0 for value in nonzero)
    n = len(nonzero)
    tail = min(positives, n - positives)
    probability = sum(math.comb(n, k) for k in range(tail + 1)) / (2**n)
    return min(1.0, 2.0 * probability)


def wilson_interval(
    successes: int,
    total: int,
    *,
    z: float = 1.959963984540054,
) -> tuple[float | None, float | None]:
    """Return a two-sided Wilson score interval for a binomial proportion."""
    if int(total) <= 0:
        return None, None
    if int(successes) < 0 or int(successes) > int(total):
        raise ValueError("successes must be between zero and total")
    n = float(total)
    proportion = float(successes) / n
    z_squared = float(z) ** 2
    denominator = 1.0 + z_squared / n
    center = (proportion + z_squared / (2.0 * n)) / denominator
    radius = (
        float(z)
        * math.sqrt(
            (proportion * (1.0 - proportion) + z_squared / (4.0 * n)) / n
        )
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def _numeric(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [float(row[field]) for row in rows if row.get(field) is not None]


def _is_effective(row: dict[str, Any]) -> bool:
    """Return whether a row is admissible as an independent primary observation.

    Older result files did not carry ``effective_instance``. They remain
    analyzable, but publication evidence requires a feasible primary attempt,
    no fallback, a stable instance fingerprint, and independent validation.
    """
    if "effective_instance" in row:
        return bool(row.get("effective_instance"))
    primary = dict(row.get("primary_attempt") or {})
    validation_errors = row.get("validation_errors_base")
    validator_passed = validation_errors == [] if validation_errors is not None else False
    return (
        int(primary.get("status", -1)) in (2, 4)
        and not bool(row.get("fallback_used"))
        and bool(row.get("instance_sha256"))
        and validator_passed
    )


def load_result_files(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load one or more immutable JSONL shards and record their provenance."""
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for path in paths:
        payload = path.read_bytes()
        shard_rows = [
            json.loads(line)
            for line in payload.decode("utf-8").splitlines()
            if line.strip()
        ]
        rows.extend(shard_rows)
        sources.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "rows": len(shard_rows),
            }
        )
    return rows, sources


def summarize_rows(
    rows: list[dict[str, Any]], *, minimum_effective_instances: int = 30
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["mode"]), str(row["requested_room_mode"]))].append(row)

    conditions: list[dict[str, Any]] = []
    for (mode, room_mode), group in sorted(grouped.items()):
        primary = [dict(row.get("primary_attempt") or {}) for row in group]
        primary_times = _numeric(primary, "cp_seconds")
        feasible_rows = [row for row in group if bool((row.get("primary_attempt") or {}).get("status") in (2, 4))]
        effective_rows = [row for row in group if _is_effective(row)]
        effective_times = _numeric(
            [dict(row.get("primary_attempt") or {}) for row in effective_rows],
            "cp_seconds",
        )
        unique_effective_instances = {
            str(row["instance_sha256"])
            for row in effective_rows
            if row.get("instance_sha256")
        }
        penalties = _numeric(feasible_rows, "penalty_base")
        time_ci = bootstrap_mean_ci(primary_times)
        effective_time_ci = bootstrap_mean_ci(effective_times)
        penalty_ci = bootstrap_mean_ci(penalties)
        feasibility_ci = wilson_interval(len(feasible_rows), len(group))
        conditions.append(
            {
                "mode": mode,
                "room_mode": room_mode,
                "runs": len(group),
                "primary_feasible_runs": len(feasible_rows),
                "primary_feasible_rate": len(feasible_rows) / len(group) if group else None,
                "primary_feasible_rate_wilson_ci95": list(feasibility_ci),
                "effective_runs": len(effective_rows),
                "unique_effective_instances": len(unique_effective_instances),
                "minimum_effective_instances": int(minimum_effective_instances),
                "effective_instance_gate": (
                    "PASS"
                    if len(unique_effective_instances) >= int(minimum_effective_instances)
                    else "NO-GO"
                ),
                "fallback_runs": sum(bool(row.get("fallback_used")) for row in group),
                "cp_seconds_median": statistics.median(primary_times) if primary_times else None,
                "cp_seconds_iqr": [_quantile(primary_times, 0.25), _quantile(primary_times, 0.75)],
                "cp_seconds_mean_ci95": list(time_ci),
                "effective_cp_seconds_median": (
                    statistics.median(effective_times) if effective_times else None
                ),
                "effective_cp_seconds_iqr": [
                    _quantile(effective_times, 0.25),
                    _quantile(effective_times, 0.75),
                ],
                "effective_cp_seconds_mean_ci95": list(effective_time_ci),
                "penalty_median": statistics.median(penalties) if penalties else None,
                "penalty_mean_ci95": list(penalty_ci),
            }
        )

    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (str(row["mode"]), str(row.get("instance_sha256") or row.get("seed")))
        by_pair[key][str(row["requested_room_mode"])] = row

    comparisons: list[dict[str, Any]] = []
    room_modes = sorted({str(row["requested_room_mode"]) for row in rows})
    for left_index, left in enumerate(room_modes):
        for right in room_modes[left_index + 1 :]:
            for mode in sorted({key[0] for key in by_pair}):
                pairs = [
                    (conditions_by_mode[left], conditions_by_mode[right])
                    for (pair_mode, _), conditions_by_mode in by_pair.items()
                    if pair_mode == mode and left in conditions_by_mode and right in conditions_by_mode
                ]
                time_differences = [
                    float((left_row.get("primary_attempt") or {})["cp_seconds"])
                    - float((right_row.get("primary_attempt") or {})["cp_seconds"])
                    for left_row, right_row in pairs
                ]
                effective_pairs = [
                    (left_row, right_row)
                    for left_row, right_row in pairs
                    if _is_effective(left_row) and _is_effective(right_row)
                ]
                effective_time_differences = [
                    float((left_row.get("primary_attempt") or {})["cp_seconds"])
                    - float((right_row.get("primary_attempt") or {})["cp_seconds"])
                    for left_row, right_row in effective_pairs
                ]
                penalty_differences = [
                    float(left_row["penalty_base"]) - float(right_row["penalty_base"])
                    for left_row, right_row in pairs
                    if left_row.get("penalty_base") is not None and right_row.get("penalty_base") is not None
                ]
                if not pairs:
                    continue
                comparisons.append(
                    {
                        "mode": mode,
                        "left": left,
                        "right": right,
                        "paired_runs": len(pairs),
                        "cp_seconds_left_minus_right_median": statistics.median(time_differences),
                        "cp_seconds_difference_mean_ci95": list(bootstrap_mean_ci(time_differences)),
                        "cp_seconds_sign_test_p": exact_sign_test_pvalue(time_differences),
                        "paired_effective_runs": len(effective_pairs),
                        "effective_cp_seconds_left_minus_right_median": (
                            statistics.median(effective_time_differences)
                            if effective_time_differences
                            else None
                        ),
                        "effective_cp_seconds_difference_mean_ci95": list(
                            bootstrap_mean_ci(effective_time_differences)
                        ),
                        "effective_cp_seconds_sign_test_p": exact_sign_test_pvalue(
                            effective_time_differences
                        ),
                        "penalty_paired_runs": len(penalty_differences),
                        "penalty_left_minus_right_median": (
                            statistics.median(penalty_differences) if penalty_differences else None
                        ),
                        "penalty_difference_mean_ci95": list(bootstrap_mean_ci(penalty_differences)),
                        "penalty_sign_test_p": exact_sign_test_pvalue(penalty_differences),
                    }
                )

    all_conditions_ready = bool(conditions) and all(
        condition["effective_instance_gate"] == "PASS" for condition in conditions
    )
    return {
        "schema_version": 2,
        "analysis_scope": (
            "primary attempts only; fallback outcomes are counted but excluded. "
            "All-run CP completion summaries include infeasibility proofs/timeouts; "
            "effective-CP summaries include only independently validated feasible rows."
        ),
        "publication_gate": {
            "minimum_unique_effective_instances_per_condition": int(minimum_effective_instances),
            "status": "PASS" if all_conditions_ready else "NO-GO",
            "definition": (
                "A unique generated or external instance fingerprint with a feasible primary "
                "result, no fallback, and zero independent-validator errors. Repeated solver "
                "seeds on one instance do not increase the effective-instance count."
            ),
        },
        "conditions": conditions,
        "paired_comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Planora JSONL experiment runs.")
    parser.add_argument(
        "results",
        type=Path,
        nargs="+",
        help="One or more JSONL result shards; inputs are combined without rewriting them.",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--minimum-effective-instances", type=int, default=30)
    parser.add_argument(
        "--require-publication-ready",
        action="store_true",
        help="Return a non-zero status unless every condition passes the effective-instance gate.",
    )
    args = parser.parse_args()

    rows, evidence_sources = load_result_files(args.results)
    analysis = summarize_rows(
        rows,
        minimum_effective_instances=max(1, int(args.minimum_effective_instances)),
    )
    analysis["evidence_sources"] = evidence_sources
    payload = json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(payload, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    if args.require_publication_ready and analysis["publication_gate"]["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
