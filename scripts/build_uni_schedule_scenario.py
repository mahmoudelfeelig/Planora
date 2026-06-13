from __future__ import annotations

import argparse
import csv
import json
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.quality_service import compute_penalty_breakdown
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.exporter import export_schedule_to_csv
from utils.generator import instance_to_json
from utils.io import write_scenario
from utils.specs import validate_schedule_against_instance


DAY_MAP = {
    "Monday": "MON",
    "Tuesday": "TUE",
    "Wednesday": "WED",
    "Thursday": "THU",
    "Friday": "FRI",
    "Saturday": "SAT",
}
DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _room_key(value: str, *, activity_id: int) -> str:
    text = _clean_text(value)
    if text:
        return text
    return f"UNSPECIFIED-{activity_id}"


def _course_code(name: str, fallback_id: int) -> str:
    match = re.match(r"^([A-Z]{2,}[A-Z0-9]*\d{2,}[A-Z0-9]*)\b", name)
    if match:
        return match.group(1)
    match = re.match(r"^(ELECT|HUMA|OPER|CTRL|BSAD|MNGT|MGMT|MRKT|INSY)\b", name)
    if match:
        return match.group(1)
    return f"UNI{int(fallback_id):04d}"


def _load_events(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    events = []
    for row in rows:
        if str(row.get("status", "")).strip().lower() != "scheduled":
            continue
        course = _clean_text(row.get("course"))
        if not course:
            continue
        events.append(
            {
                "week": int(row["week"]),
                "day": DAY_MAP.get(str(row["day"]), str(row["day"]).upper()),
                "major": _clean_text(row["major"]),
                "major_row_index": int(row.get("major_row_index") or 0),
                "slot": int(row["slot_index"]) - 1,
                "time": _clean_text(row.get("time")),
                "course": course,
                "room": _clean_text(row.get("room")),
                "source_page": int(row.get("source_page") or 0),
            }
        )
    return events


def build_instance_and_schedule(events: list[dict[str, Any]]) -> tuple[Instance, dict[int, dict[str, Any]], dict[str, Any]]:
    major_keys = sorted({(str(event["major"]), int(event["major_row_index"])) for event in events})
    course_names = sorted({str(event["course"]) for event in events})
    duplicate_major_names = {
        major
        for major, rows in {
            major: {row for candidate_major, row in major_keys if candidate_major == major}
            for major, _row in major_keys
        }.items()
        if len(rows) > 1
    }

    groups: dict[int, Group] = {}
    programs: dict[int, Program] = {}
    major_to_group: dict[tuple[str, int], int] = {}
    for idx, (major, row_index) in enumerate(major_keys, start=1):
        group_name = f"{major} row {row_index}" if major in duplicate_major_names else major
        major_to_group[(major, row_index)] = idx
        groups[idx] = Group(
            id=idx,
            name=group_name,
            program_id=idx,
            size=1,
            course_ids=[],
            preferred_free_days=2,
        )
        programs[idx] = Program(id=idx, name=group_name, course_ids=[], group_ids=[idx])

    courses: dict[int, Course] = {}
    course_to_id: dict[str, int] = {}
    for idx, course_name in enumerate(course_names, start=1):
        course_to_id[course_name] = idx
        courses[idx] = Course(
            id=idx,
            code=_course_code(course_name, idx),
            name=course_name,
            structure_type="LEC_ONLY",
            lecture_count=0,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[],
            prof_id=None,
            ta_id=None,
        )

    room_names = sorted({_room_key(str(event["room"]), activity_id=idx) for idx, event in enumerate(events, start=1)})
    rooms: dict[int, Room] = {}
    room_to_id: dict[str, int] = {}
    for idx, room_name in enumerate(room_names, start=1):
        room_to_id[room_name] = idx
        rooms[idx] = Room(
            id=idx,
            name=room_name,
            capacity=999,
            room_type="LECTURE",
        )

    grouped_events: dict[tuple[int, str, int, str, str], set[int]] = defaultdict(set)
    pages_by_key: dict[tuple[int, str, int, str, str], set[int]] = defaultdict(set)
    for idx, event in enumerate(events, start=1):
        room_name = _room_key(str(event["room"]), activity_id=idx)
        key = (
            int(event["week"]),
            str(event["day"]),
            int(event["slot"]),
            str(event["course"]),
            room_name,
        )
        grouped_events[key].add(
            int(major_to_group[(str(event["major"]), int(event["major_row_index"]))])
        )
        pages_by_key[key].add(int(event["source_page"]))

    activities: dict[int, Activity] = {}
    staff: dict[int, StaffMember] = {}
    schedule: dict[int, dict[str, Any]] = {}
    course_counts: dict[int, int] = defaultdict(int)
    course_group_ids: dict[int, set[int]] = defaultdict(set)

    for activity_id, (key, group_ids_set) in enumerate(sorted(grouped_events.items()), start=1):
        week, day, slot, course_name, room_name = key
        course_id = int(course_to_id[course_name])
        room_id = int(room_to_id[room_name])
        staff_id = int(activity_id)
        group_ids = sorted(int(g) for g in group_ids_set)
        course_counts[course_id] += 1
        course_group_ids[course_id].update(group_ids)

        staff[staff_id] = StaffMember(
            id=staff_id,
            name=f"Imported lecturer A{activity_id}",
            is_prof=True,
            available_days=set(DAY_ORDER),
            available_weeks=set(range(1, 13)),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={course_id},
        )
        activities[activity_id] = Activity(
            id=activity_id,
            course_id=course_id,
            week=int(week),
            kind="LEC",
            duration=1,
            group_ids=group_ids,
            prof_id=staff_id,
            ta_id=staff_id,
        )
        schedule[activity_id] = {
            "week": int(week),
            "day": str(day),
            "slot": int(slot),
            "duration": 1,
            "room_id": int(room_id),
            "staff_id": int(staff_id),
            "course_id": int(course_id),
            "group_ids": group_ids,
            "kind": "LEC",
        }

    for course_id, count in course_counts.items():
        courses[int(course_id)].lecture_count = int(count)
        courses[int(course_id)].prof_id = min(
            int(activity.prof_id)
            for activity in activities.values()
            if int(activity.course_id) == int(course_id)
        )
        # Extracted timetable rows are observed section meetings, not necessarily
        # synchronized shared lectures. Inferring share_lecture_group_ids here
        # forces same-start constraints in CP-SAT and can make imports infeasible.
        courses[int(course_id)].share_lecture_group_ids = []

    for group in groups.values():
        enrolled = sorted(
            int(course_id)
            for course_id, group_ids in course_group_ids.items()
            if int(group.id) in {int(g) for g in group_ids}
        )
        group.course_ids = enrolled
        programs[int(group.program_id)].course_ids = sorted(
            set(programs[int(group.program_id)].course_ids) | set(enrolled)
        )

    inst = Instance(
        days=list(DAY_ORDER),
        slots_per_day=5,
        weeks=list(range(1, 13)),
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        locked_activities={
            int(a_id): {
                "day": str(info["day"]),
                "slot": int(info["slot"]),
                "room_id": int(info["room_id"]),
            }
            for a_id, info in schedule.items()
        },
        hard_constraints={
            "week1_lectures_only": True,
            "enforce_block_professor_rules": False,
            "enforce_staff_daily_caps": False,
            "enforce_staff_weekly_caps": False,
            "enforce_room_availability": True,
        },
        objective_profile="fast_feasible",
    )
    inst.day_start_time = "08:30"
    inst.slot_minutes = 90
    inst.slot_break_minutes = 0
    inst.time_labels = [
        "08:30 - 10:00",
        "10:30 - 12:00",
        "12:15 - 13:45",
        "14:15 - 15:45",
        "16:00 - 17:30",
    ]

    meta = {
        "source_events": int(len(events)),
        "activities_after_shared_event_merge": int(len(activities)),
        "groups": int(len(groups)),
        "courses": int(len(courses)),
        "rooms": int(len(rooms)),
        "staff": int(len(staff)),
        "assumptions": [
            "PDF has no staff data; one synthetic lecturer is assigned per imported activity to avoid false staff conflicts.",
            "PDF has no room capacities/types; rooms are modeled as large lecture rooms.",
            "Rows with identical week/day/slot/course/room across majors are merged into one shared activity.",
            "Every imported activity is locked to the observed PDF time and room.",
        ],
    }
    return inst, schedule, meta


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
