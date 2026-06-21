from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.metaheuristics import LocalSearchImprover
from services.timetable_import_service import import_timetable_csv
from utils.specs import validate_schedule_against_instance


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lightweight SS23 import/score/improve regression guard."
    )
    parser.add_argument(
        "--csv",
        default=str(ROOT_DIR / "data" / "SS23-All-Majors-Schedule-events.csv"),
    )
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--max-seconds", type=float, default=1.5)
    args = parser.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(json.dumps({"skipped": True, "reason": f"missing {path}"}))
        return 0

    inst, schedule, meta = import_timetable_csv(path)
    improver = LocalSearchImprover(inst)
    before = int(improver.compute_soft_penalty(schedule))
    conflicts_before = validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=False,
    )
    improved = improver.improve(
        schedule,
        iterations=max(1, int(args.iterations)),
        max_seconds=max(0.0, float(args.max_seconds)),
    )
    after = int(improver.compute_soft_penalty(improved))
    conflicts_after = validate_schedule_against_instance(
        inst,
        improved,
        strict_rooms=True,
        require_all_activities=False,
    )
    payload = {
        "skipped": False,
        "activities": len(schedule),
        "groups": len(inst.groups),
        "courses": len(inst.courses),
        "rooms": len(inst.rooms),
        "import_soft_penalty": int(meta.get("soft_penalty", before)),
        "before_soft_penalty": before,
        "after_soft_penalty": after,
        "before_hard_conflicts": len(conflicts_before),
        "after_hard_conflicts": len(conflicts_after),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if after > before:
        print("SS23 regression guard failed: local improvement worsened soft penalty.", file=sys.stderr)
        return 1
    if len(conflicts_after) > len(conflicts_before):
        print("SS23 regression guard failed: local improvement added hard conflicts.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
