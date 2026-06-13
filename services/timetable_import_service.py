from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from services.quality_service import compute_penalty_breakdown
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.specs import validate_schedule_against_instance


DAY_ALIASES = {
    "mon": "MON",
    "monday": "MON",
    "tue": "TUE",
    "tues": "TUE",
    "tuesday": "TUE",
    "wed": "WED",
    "wednesday": "WED",
    "thu": "THU",
    "thur": "THU",
    "thurs": "THU",
    "thursday": "THU",
    "fri": "FRI",
    "friday": "FRI",
    "sat": "SAT",
    "saturday": "SAT",
    "sun": "SUN",
    "sunday": "SUN",
}
DEFAULT_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "week": ("week", "wk", "week_number", "week no", "week no.", "academic_week"),
    "day": ("day", "weekday", "week_day"),
    "slot": ("slot", "slot_index", "period", "period_index", "timeslot", "time_slot"),
    "time": ("time", "time_label", "time range", "time_range"),
    "course": ("course", "course_name", "subject", "class", "module", "title"),
    "group": ("major", "group", "cohort", "program", "section", "class_group"),
    "group_row": ("major_row_index", "group_row_index", "row", "row_index", "section_index"),
    "room": ("room", "room_name", "classroom", "venue", "location"),
    "status": ("status", "state"),
    "source_page": ("source_page", "page", "pdf_page"),
    "duration": ("duration", "slots", "slot_count"),
    "kind": ("kind", "activity_kind", "type", "activity_type"),
}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _column_lookup(headers: Iterable[str]) -> Dict[str, str]:
    normalized = {_norm_header(h): str(h) for h in headers}
    out: Dict[str, str] = {}
    for logical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            found = normalized.get(_norm_header(alias))
            if found:
                out[logical] = found
                break
    return out


def _value(row: Dict[str, Any], columns: Dict[str, str], logical: str, default: Any = "") -> Any:
    column = columns.get(str(logical), "")
    if not column:
        return default
    return row.get(column, default)


def _parse_int(value: Any, *, default: int = 0) -> int:
    text = _clean_text(value)
    if not text:
        return int(default)
    match = re.search(r"-?\d+", text)
    if not match:
        return int(default)
    return int(match.group(0))


def _parse_day(value: Any) -> str:
    text = _clean_text(value)
    key = text.lower()
    return DAY_ALIASES.get(key, text.upper()[:3] if text else "MON")


def _course_code(name: str, fallback_id: int) -> str:
    match = re.match(r"^([A-Z]{2,}[A-Z0-9]*\d{2,}[A-Z0-9]*)\b", str(name))
    if match:
        return match.group(1)
    match = re.match(r"^([A-Z]{3,})\b", str(name))
    if match:
        return match.group(1)
    return f"CSV{int(fallback_id):04d}"


def _activity_kind(raw: Any) -> str:
    text = _clean_text(raw).upper()
    if "LAB" in text:
        return "LAB"
    if "TUT" in text or "REC" in text:
        return "TUT"
    return "LEC"


def _room_type_for_kind(kind: str) -> str:
    if str(kind).upper() == "LAB":
        return "SPECIALIZED_LAB"
    if str(kind).upper() == "TUT":
        return "TUTORIAL"
    return "LECTURE"


def load_timetable_events(path: str | Path) -> List[Dict[str, Any]]:
    """
    Load a timetable-shaped CSV and normalize it to scheduler import events.

    Required columns, by detected name: week, day, slot, course.
    Optional columns: major/group, room, status, time, duration, kind, row/page.
    The SS23 extracted events CSV is supported directly.
    """
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        columns = _column_lookup(headers)
        missing = [key for key in ("week", "day", "slot", "course") if key not in columns]
        if missing:
            raise ValueError(
                "CSV is missing required timetable columns: "
                + ", ".join(missing)
                + ". Expected names like week, day, slot, course, group/major, room."
            )
        events: List[Dict[str, Any]] = []
        for row_index, row in enumerate(reader, start=1):
            status = _clean_text(_value(row, columns, "status", "scheduled")).lower()
            if status and status not in {"scheduled", "schedule", "active", "ok", "yes", "1"}:
                continue
            course = _clean_text(_value(row, columns, "course"))
            if not course:
                continue
            group = _clean_text(_value(row, columns, "group", "Imported group"))
            if not group:
                group = "Imported group"
            events.append(
                {
                    "week": max(1, _parse_int(_value(row, columns, "week"), default=1)),
                    "day": _parse_day(_value(row, columns, "day")),
                    "slot": max(0, _parse_int(_value(row, columns, "slot"), default=1) - 1),
                    "duration": max(1, _parse_int(_value(row, columns, "duration"), default=1)),
                    "course": course,
                    "major": group,
                    "major_row_index": max(1, _parse_int(_value(row, columns, "group_row"), default=1)),
                    "room": _clean_text(_value(row, columns, "room", "")) or f"UNSPECIFIED-{row_index}",
                    "time": _clean_text(_value(row, columns, "time", "")),
                    "source_page": _parse_int(_value(row, columns, "source_page"), default=0),
                    "kind": _activity_kind(_value(row, columns, "kind", "")),
                }
            )
    if not events:
        raise ValueError("No scheduled timetable rows were found in the CSV.")
    return events


def build_instance_and_schedule_from_events(
    events: List[Dict[str, Any]],
    *,
    lock_imported: bool = False,
) -> Tuple[Instance, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    major_keys = sorted({(str(event["major"]), int(event["major_row_index"])) for event in events})
    course_names = sorted({str(event["course"]) for event in events})
    weeks = sorted({int(event["week"]) for event in events}) or [1]
    days = [day for day in DEFAULT_DAYS if day in {str(event["day"]) for event in events}]
    extra_days = sorted({str(event["day"]) for event in events} - set(days))
    days = days + extra_days if days else list(DEFAULT_DAYS)
    slots_per_day = max(1, max(int(event["slot"]) + int(event["duration"]) for event in events))

    duplicate_major_names = {
        major
        for major, rows in {
            major: {row for candidate_major, row in major_keys if candidate_major == major}
            for major, _row in major_keys
        }.items()
        if len(rows) > 1
    }

    groups: Dict[int, Group] = {}
    programs: Dict[int, Program] = {}
    major_to_group: Dict[Tuple[str, int], int] = {}
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

    courses: Dict[int, Course] = {}
    course_to_id: Dict[str, int] = {}
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

    room_names = sorted({_clean_text(event.get("room")) or f"UNSPECIFIED-{idx}" for idx, event in enumerate(events, start=1)})
    room_to_id: Dict[str, int] = {}
    rooms: Dict[int, Room] = {}
    room_kind: Dict[str, str] = {}
    for event in events:
        room_name = _clean_text(event.get("room")) or "UNSPECIFIED"
        room_kind.setdefault(room_name, _room_type_for_kind(str(event.get("kind", "LEC"))))
    for idx, room_name in enumerate(room_names, start=1):
        room_to_id[room_name] = idx
        rooms[idx] = Room(
            id=idx,
            name=room_name,
            capacity=999,
            room_type=room_kind.get(room_name, "LECTURE"),
        )

    grouped_events: Dict[Tuple[int, str, int, int, str, str, str], set[int]] = defaultdict(set)
    pages_by_key: Dict[Tuple[int, str, int, int, str, str, str], set[int]] = defaultdict(set)
    for idx, event in enumerate(events, start=1):
        room_name = _clean_text(event.get("room")) or f"UNSPECIFIED-{idx}"
        key = (
            int(event["week"]),
            str(event["day"]),
            int(event["slot"]),
            int(event.get("duration", 1)),
            str(event["course"]),
            room_name,
            str(event.get("kind", "LEC")),
        )
        grouped_events[key].add(
            int(major_to_group[(str(event["major"]), int(event["major_row_index"]))])
        )
        pages_by_key[key].add(int(event.get("source_page", 0) or 0))

    activities: Dict[int, Activity] = {}
    staff: Dict[int, StaffMember] = {}
    schedule: Dict[int, Dict[str, Any]] = {}
    course_counts: Dict[int, int] = defaultdict(int)
    course_group_ids: Dict[int, set[int]] = defaultdict(set)

    for activity_id, (key, group_ids_set) in enumerate(sorted(grouped_events.items()), start=1):
        week, day, slot, duration, course_name, room_name, kind = key
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
            available_days=set(days),
            available_weeks=set(weeks),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={course_id},
        )
        activities[activity_id] = Activity(
            id=activity_id,
            course_id=course_id,
            week=int(week),
            kind=str(kind),
            duration=int(duration),
            group_ids=group_ids,
            prof_id=staff_id,
            ta_id=staff_id,
        )
        schedule[activity_id] = {
            "week": int(week),
            "day": str(day),
            "slot": int(slot),
            "duration": int(duration),
            "room_id": int(room_id),
            "staff_id": int(staff_id),
            "course_id": int(course_id),
            "group_ids": group_ids,
            "kind": str(kind),
        }

    for course_id, count in course_counts.items():
        courses[int(course_id)].lecture_count = int(count)
        courses[int(course_id)].prof_id = min(
            int(activity.prof_id)
            for activity in activities.values()
            if int(activity.course_id) == int(course_id)
        )
        courses[int(course_id)].ta_id = courses[int(course_id)].prof_id
        # Raw timetable CSVs may contain repeated course sessions for different sections
        # and weeks. Do not infer solver-level shared-lecture synchronization here;
        # only explicit generator data should use share_lecture_group_ids.
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

    locks = (
        {
            int(a_id): {
                "day": str(info["day"]),
                "slot": int(info["slot"]),
                "room_id": int(info["room_id"]),
            }
            for a_id, info in schedule.items()
        }
        if bool(lock_imported)
        else {}
    )

    inst = Instance(
        days=list(days),
        slots_per_day=int(slots_per_day),
        weeks=list(weeks),
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        locked_activities=locks,
        hard_constraints={
            "week1_lectures_only": False,
            "enforce_block_professor_rules": False,
            "enforce_staff_daily_caps": False,
            "enforce_staff_weekly_caps": False,
            "enforce_room_availability": True,
        },
        objective_profile="university_fast" if len(activities) >= 500 else "balanced",
    )
    inst.day_start_time = "08:30"
    inst.slot_minutes = 90
    inst.slot_break_minutes = 0
    inst.time_labels = [f"S{idx + 1}" for idx in range(int(slots_per_day))]

    meta = {
        "source_events": int(len(events)),
        "activities_after_shared_event_merge": int(len(activities)),
        "groups": int(len(groups)),
        "courses": int(len(courses)),
        "rooms": int(len(rooms)),
        "staff": int(len(staff)),
        "locked_imported_assignments": bool(lock_imported),
        "assumptions": [
            "CSV import creates synthetic staff when lecturer data is unavailable.",
            "CSV import infers groups/programs from major/group/cohort columns.",
            "Rows with identical week/day/slot/duration/course/room/kind are merged into one shared activity.",
            "Imported assignments are left unlocked by default so solve/improve can repair conflicts.",
        ],
    }
    return inst, schedule, meta


def import_timetable_csv(
    path: str | Path,
    *,
    lock_imported: bool = False,
) -> Tuple[Instance, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    events = load_timetable_events(path)
    inst, schedule, meta = build_instance_and_schedule_from_events(
        events,
        lock_imported=bool(lock_imported),
    )
    validation_errors = validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    quality = compute_penalty_breakdown(inst, schedule)
    meta = {
        **meta,
        "source_path": str(path),
        "validation_error_count": int(len(validation_errors)),
        "validation_errors": list(validation_errors[:200]),
        "quality": dict(quality),
        "soft_penalty": int(quality.get("total", 0)),
    }
    return inst, schedule, meta
