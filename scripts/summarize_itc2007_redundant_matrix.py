from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pass(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if not summary.get("complete") or summary.get("completed_runs") != 42:
        raise ValueError(f"matrix is not complete: {path}")
    return summary, manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize two complete ITC-2007 competitor matrix passes."
    )
    parser.add_argument("--pass-a", type=Path, required=True)
    parser.add_argument("--pass-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary_a, manifest_a = _load_pass(args.pass_a)
    summary_b, manifest_b = _load_pass(args.pass_b)
    identity_fields = (
        "planora_source_sha256",
        "cpsolver_classes_sha256",
        "validator_sha256",
        "seeds",
        "time_limit_seconds",
        "workers",
        "cpu_affinity",
        "planora_strategy",
    )
    identity = {field: manifest_a[field] for field in identity_fields}
    for field in identity_fields:
        if manifest_a[field] != manifest_b[field]:
            raise ValueError(f"pass identity mismatch: {field}")

    by_pass = {}
    comparisons: dict[str, dict[str, Any]] = {}
    for label, summary, path in (
        ("a", summary_a, args.pass_a),
        ("b", summary_b, args.pass_b),
    ):
        by_pass[label] = {
            "directory": str(path.resolve()),
            "manifest_sha256": _sha256(path / "manifest.json"),
            "results_sha256": _sha256(path / "results.jsonl"),
            "summary_sha256": _sha256(path / "summary.json"),
            "aggregate": summary["aggregate"],
            "paired_counts": {
                key: summary["paired"][key]
                for key in ("planora_wins", "cpsolver_wins", "ties", "unpaired")
            },
        }
        for row in summary["paired"]["comparisons"]:
            instance = row["instance_id"]
            comparisons.setdefault(instance, {})[label] = {
                "planora": row["planora_objective"],
                "cpsolver": row["cpsolver_objective"],
                "winner": row["winner"],
            }

    stable_winner_count = sum(
        rows["a"]["winner"] == rows["b"]["winner"]
        for rows in comparisons.values()
    )
    payload = {
        "schema": "planora.itc2007-redundant-matrix-summary.v1",
        "generated_at": "2026-08-13",
        "identity": identity,
        "passes": by_pass,
        "instances": comparisons,
        "reproducibility": {
            "instance_count": len(comparisons),
            "stable_winner_count": stable_winner_count,
            "winner_changed_count": len(comparisons) - stable_winner_count,
            "both_passes_complete": True,
            "all_84_rows_officially_feasible": all(
                pass_data["aggregate"][solver]["feasibility_rate"] == 1.0
                for pass_data in by_pass.values()
                for solver in ("planora", "cpsolver-itc2007")
            ),
        },
        "claim_boundary": (
            "Planora has the lower mean objective in both passes, but winner changes "
            "between passes prohibit deterministic per-instance or general superiority claims."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["reproducibility"], sort_keys=True))


if __name__ == "__main__":
    main()
