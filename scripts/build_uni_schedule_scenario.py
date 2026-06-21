from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.quality_service import compute_penalty_breakdown
from services.timetable_import_service import (
    build_instance_and_schedule_from_events,
    load_timetable_events,
)
from utils.domain import Instance
from utils.exporter import export_schedule_to_csv
from utils.generator import instance_to_json
from utils.io import write_scenario
from utils.specs import validate_schedule_against_instance


def _load_events(path: Path) -> list[dict[str, Any]]:
    return load_timetable_events(path)


def build_instance_and_schedule(
    events: list[dict[str, Any]],
) -> tuple[Instance, dict[int, dict[str, Any]], dict[str, Any]]:
    return build_instance_and_schedule_from_events(events, lock_imported=True)


def write_outputs(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    meta: dict[str, Any],
    *,
    output_prefix: Path,
    validation_errors: list[str],
    quality: dict[str, int],
) -> dict[str, str]:
    scenario_json = output_prefix.with_name(output_prefix.name + "-scenario.json")
    scenario_pkl = output_prefix.with_name(output_prefix.name + "-scenario.pkl")
    instance_json = output_prefix.with_name(output_prefix.name + "-instance.json")
    schedule_csv = output_prefix.with_name(output_prefix.name + "-schedule.csv")
    report_json = output_prefix.with_name(output_prefix.name + "-validation-report.json")

    write_scenario(
        scenario_json,
        inst,
        schedule,
        meta={**meta, "validation_errors": validation_errors, "quality": quality},
    )
    scenario_pkl.write_bytes(
        pickle.dumps({"instance": inst, "schedule": schedule, "meta": meta})
    )
    instance_json.write_text(
        json.dumps(instance_to_json(inst), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    export_schedule_to_csv(inst, schedule, str(schedule_csv))
    report_json.write_text(
        json.dumps(
            {
                **meta,
                "validation_error_count": int(len(validation_errors)),
                "validation_errors": validation_errors[:200],
                "validation_details": describe_validation_errors(
                    inst,
                    schedule,
                    validation_errors[:200],
                ),
                "quality": quality,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "scenario_json": str(scenario_json),
        "scenario_pkl": str(scenario_pkl),
        "instance_json": str(instance_json),
        "schedule_csv": str(schedule_csv),
        "report_json": str(report_json),
    }


def describe_validation_errors(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    validation_errors: list[str],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    activity_re = re.compile(r"\((A\d+), (A\d+)\)")

    def _activity_summary(token: str) -> dict[str, Any]:
        a_id = int(token.lstrip("A"))
        info = schedule.get(a_id, {})
        course = inst.courses.get(int(info.get("course_id", -1)))
        room = inst.rooms.get(int(info.get("room_id", -1)))
        groups = [
            inst.groups[int(g)].name
            for g in info.get("group_ids", [])
            if int(g) in inst.groups
        ]
        return {
            "activity_id": a_id,
            "week": info.get("week"),
            "day": info.get("day"),
            "slot": int(info.get("slot", 0)) + 1 if "slot" in info else None,
            "course": course.name if course else None,
            "room": room.name if room else None,
            "groups": groups,
        }

    for error in validation_errors:
        row: dict[str, Any] = {"error": str(error)}
        match = activity_re.search(str(error))
        if match:
            row["activities"] = [
                _activity_summary(match.group(1)),
                _activity_summary(match.group(2)),
            ]
        details.append(row)
    return details


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a scheduler scenario from the extracted SS23 university timetable CSV."
    )
    parser.add_argument(
        "--events-csv",
        type=Path,
        default=Path("data/SS23-All-Majors-Schedule-events.csv"),
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("data/ss23-uni"),
    )
    parser.add_argument("--fail-on-validation-errors", action="store_true")
    args = parser.parse_args()

    events = _load_events(args.events_csv)
    inst, schedule, meta = build_instance_and_schedule(events)
    validation_errors = validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    quality = compute_penalty_breakdown(inst, schedule)
    outputs = write_outputs(
        inst,
        schedule,
        meta,
        output_prefix=args.output_prefix,
        validation_errors=validation_errors,
        quality=quality,
    )
    summary = {
        **meta,
        "validation_error_count": int(len(validation_errors)),
        "soft_penalty": int(quality.get("total", 0)),
        "outputs": outputs,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if validation_errors and args.fail_on_validation_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
