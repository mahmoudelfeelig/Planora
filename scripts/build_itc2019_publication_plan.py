from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.itc2019 import parse_itc2019_xml
from benchmarks.multifamily_harness import (
    BenchmarkCaseSpec,
    make_corpus_manifest,
    make_smoke_plan,
)
from scripts.benchmark_itc2019_competitors import COMPETITION_CASES


DEFAULT_INPUT_ROOT = Path(
    "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019"
)


def build_plan(input_root: Path, *, time_limit_seconds: float, cpu: int | None):
    valid: list[Path] = []
    rejected: list[dict[str, str]] = []
    for path in sorted(input_root.glob("*.xml")):
        try:
            parse_itc2019_xml(path)
        except Exception as exc:  # parser rejection is part of corpus accounting
            rejected.append({"name": path.name, "reason": str(exc)})
        else:
            valid.append(path.resolve())

    valid_by_stem = {path.stem: path for path in valid}
    missing = [name for name in COMPETITION_CASES if name not in valid_by_stem]
    if missing:
        raise RuntimeError(f"official competition instances unavailable: {missing}")
    selected = [valid_by_stem[name] for name in COMPETITION_CASES]

    time_tag = f"{time_limit_seconds:g}".replace(".", "p")
    cases = tuple(
        BenchmarkCaseSpec(
            case_id=f"itc2019-{path.stem}-seed17-{time_tag}s",
            family_id="itc2019",
            instance_path=str(path),
            time_limit_seconds=time_limit_seconds,
            seeds=(17,),
            repetitions=1,
            workers=1,
            cpu_affinity=cpu,
            options={
                "solver": {
                    "formulation": "auto",
                    "max_pair_matrix_cells": 2_000_000,
                    "max_group_table_rows": 200_000,
                    "max_joint_student_conjunctions": 200_000,
                    "max_sparse_room_constraints": 2_000_000,
                }
            },
        )
        for path in selected
    )
    plan = make_smoke_plan(
        cases,
        supervision_grace_seconds=40.0,
        corpus_manifest=make_corpus_manifest(
            cases, corpus_id="itc2019-official-competition-30-v2"
        ),
    )
    return plan, rejected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the fixed 30-condition ITC-2019 publication-scale plan."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit-seconds", type=float, default=5.0)
    parser.add_argument("--cpu", type=int)
    args = parser.parse_args()

    plan, rejected = build_plan(
        args.input_root.resolve(),
        time_limit_seconds=args.time_limit_seconds,
        cpu=args.cpu,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(plan.cases),
                "plan_sha256": plan.plan_sha256,
                "rejected_inputs": rejected,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
