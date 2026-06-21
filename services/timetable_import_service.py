from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from services.quality_service import compute_penalty_breakdown
from services.teaching_load_import_service import (
    load_teaching_load_assignments,
    match_teaching_assignment,
)
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
    "lecturer": ("lecturer", "professor", "instructor", "teacher", "staff"),
    "ta": ("ta", "assistant", "teaching_assistant", "tutor"),
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


def suggest_timetable_mapping(headers: Iterable[str]) -> Dict[str, str]:
    """Return best-effort logical-field -> CSV-header suggestions."""
    return _column_lookup(headers)


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


def _parse_day(value: Any, *, day_aliases: Dict[str, str] | None = None) -> str:
    text = _clean_text(value)
    key = text.lower()
    custom = {
        _norm_header(str(k)): str(v).upper()[:3]
        for k, v in dict(day_aliases or {}).items()
        if str(k).strip() and str(v).strip()
    }
    if _norm_header(key) in custom:
        return custom[_norm_header(key)]
    return DAY_ALIASES.get(key, text.upper()[:3] if text else "MON")


def _course_code(name: str, fallback_id: int) -> str:
    match = re.match(r"^([A-Z]{2,}[A-Z0-9]*\d{2,}[A-Z0-9]*)\b", str(name))
    if match:
        return match.group(1)
    match = re.match(r"^([A-Z]{3,})\b", str(name))
    if match:
        return match.group(1)
    return f"CSV{int(fallback_id):04d}"


def _activity_kind(
    raw: Any,
    *,
    course_text: Any = "",
    kind_aliases: Dict[str, str] | None = None,
) -> str:
    text = _clean_text(raw).upper()
    fallback = _clean_text(course_text).upper()
    custom = {
        _norm_header(str(k)): str(v).upper()[:3]
        for k, v in dict(kind_aliases or {}).items()
        if str(k).strip() and str(v).strip()
    }
    mapped = custom.get(_norm_header(text))
    if mapped in {"LEC", "TUT", "LAB"}:
        return mapped
    probe = text or fallback
    if "LAB" in probe:
        return "LAB"
    if "TUT" in probe or "REC" in probe or re.search(r"\bT\d+\b", probe):
        return "TUT"
    return "LEC"


def _staff_course_key(course_name: str, kind: str) -> str:
    text = _clean_text(course_name).upper()
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\bLAB\s*T?\d*\b", "", text)
    text = re.sub(r"\bT\d+\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -/")
    code = _course_code(text, 0)
    return f"{code}:{text or code}"


def _parse_slot(value: Any, *, transform_config: Dict[str, Any] | None = None) -> int:
    cfg = dict(transform_config or {})
    text = _clean_text(value)
    aliases = {
        _norm_header(str(k)): int(v)
        for k, v in dict(cfg.get("slot_aliases") or cfg.get("time_slot_map") or {}).items()
        if str(k).strip()
    }
    key = _norm_header(text)
    if key in aliases:
        return max(0, int(aliases[key]))
    slot_base = int(cfg.get("slot_base", 1) or 1)
    parsed = _parse_int(text, default=slot_base)
    return max(0, int(parsed) - int(slot_base))


def _infer_room_type(room_name: str, *, transform_config: Dict[str, Any] | None = None) -> str | None:
    rules = list(dict(transform_config or {}).get("room_type_rules") or [])
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("pattern", "") or "")
        room_type = str(rule.get("room_type", "") or "").upper()
        if not pattern or room_type not in {"LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"}:
            continue
        try:
            if re.search(pattern, room_name, flags=re.IGNORECASE):
                return room_type
        except re.error:
            if pattern.lower() in room_name.lower():
                return room_type
    return None


def _room_type_for_kind(kind: str) -> str:
    if str(kind).upper() == "LAB":
        return "SPECIALIZED_LAB"
    if str(kind).upper() == "TUT":
        return "TUTORIAL"
    return "LECTURE"


def load_timetable_events(
    path: str | Path,
    *,
    field_map: Dict[str, str] | None = None,
    transform_config: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
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
        columns = {
            str(k): str(v)
            for k, v in dict(field_map or {}).items()
            if str(v or "").strip()
        } or _column_lookup(headers)
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
            cfg = dict(transform_config or {})
            group = _clean_text(_value(row, columns, "group", "Imported group"))
            if not group:
                group = "Imported group"
            group_separator = str(cfg.get("group_separator", "") or "").strip()
            groups = [group]
            if group_separator:
                groups = [g.strip() for g in group.split(group_separator) if g.strip()]
                if not groups:
                    groups = ["Imported group"]
            room_name = _clean_text(_value(row, columns, "room", "")) or f"UNSPECIFIED-{row_index}"
            kind = _activity_kind(
                _value(row, columns, "kind", ""),
                course_text=course,
                kind_aliases=dict(cfg.get("kind_aliases") or {}),
            )
            room_type = _infer_room_type(room_name, transform_config=cfg)
            for group_name in groups:
                events.append(
                    {
                        "week": max(1, _parse_int(_value(row, columns, "week"), default=1)),
                        "day": _parse_day(
                            _value(row, columns, "day"),
                            day_aliases=dict(cfg.get("day_aliases") or {}),
                        ),
                        "slot": _parse_slot(_value(row, columns, "slot"), transform_config=cfg),
                        "duration": max(1, _parse_int(_value(row, columns, "duration"), default=1)),
                        "course": course,
                        "major": group_name,
                        "major_row_index": max(1, _parse_int(_value(row, columns, "group_row"), default=1)),
                        "room": room_name,
                        "room_type": room_type,
                        "lecturer": _clean_text(_value(row, columns, "lecturer", "")),
                        "ta": _clean_text(_value(row, columns, "ta", "")),
                        "time": _clean_text(_value(row, columns, "time", "")),
                        "source_page": _parse_int(_value(row, columns, "source_page"), default=0),
                        "kind": kind,
                    }
                )
    if not events:
        raise ValueError("No scheduled timetable rows were found in the CSV.")
    return events


def build_instance_and_schedule_from_events(
    events: List[Dict[str, Any]],
    *,
    lock_imported: bool = False,
    teaching_load_catalog: Dict[str, Any] | None = None,
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
        room_kind.setdefault(
            room_name,
            str(event.get("room_type") or "") or _room_type_for_kind(str(event.get("kind", "LEC"))),
        )
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
    staff_names_by_key: Dict[Tuple[int, str, int, int, str, str, str], Dict[str, set[str]]] = {}
    duplicate_event_rows = 0
    seen_event_rows: set[Tuple[Any, ...]] = set()
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
        group_id = int(major_to_group[(str(event["major"]), int(event["major_row_index"]))])
        row_key = (
            *key,
            group_id,
            _clean_text(event.get("lecturer", "")),
            _clean_text(event.get("ta", "")),
        )
        if row_key in seen_event_rows:
            duplicate_event_rows += 1
            continue
        seen_event_rows.add(row_key)
        grouped_events[key].add(group_id)
        pages_by_key[key].add(int(event.get("source_page", 0) or 0))
        staff_names = staff_names_by_key.setdefault(
            key,
            {"lecturer": set(), "ta": set()},
        )
        lecturer_name = _clean_text(event.get("lecturer", ""))
        ta_name = _clean_text(event.get("ta", ""))
        if lecturer_name:
            staff_names["lecturer"].add(lecturer_name)
        if ta_name:
            staff_names["ta"].add(ta_name)

    activities: Dict[int, Activity] = {}
    staff: Dict[int, StaffMember] = {}
    schedule: Dict[int, Dict[str, Any]] = {}
    course_counts_by_kind: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    course_group_ids: Dict[int, set[int]] = defaultdict(set)
    staff_key_to_id: Dict[Tuple[str, str], int] = {}
    fallback_staff_count = max(1, (len(course_names) + 3) // 4)
    fallback_pool_by_course_name = {
        str(name): min(fallback_staff_count - 1, index * fallback_staff_count // len(course_names))
        for index, name in enumerate(course_names)
    }
    teaching_matches: Dict[str, Dict[str, Any]] = {}
    for course_name in course_names:
        matched = match_teaching_assignment(teaching_load_catalog or {}, course_name)
        if matched:
            teaching_matches[str(course_name)] = matched

    def _get_staff_id(
        *,
        role: str,
        is_prof: bool,
        course_id: int,
        course_name: str,
        explicit_names: set[str] | None = None,
        kind: str,
    ) -> int:
        names = sorted(_clean_text(name) for name in (explicit_names or set()) if _clean_text(name))
        stable_name = names[0] if names else ""
        if stable_name:
            key = (str(role), _norm_header(stable_name))
            display_name = stable_name
        else:
            pool_index = int(fallback_pool_by_course_name.get(str(course_name), 0)) + 1
            key = (str(role), f"fallback-pool-{pool_index}")
            label = "lecturer" if bool(is_prof) else "TA"
            display_name = f"Imported {label} {pool_index}"
        existing = staff_key_to_id.get(key)
        if existing is not None:
            staff[int(existing)].can_teach_courses.add(int(course_id))
            return int(existing)
        staff_id = len(staff) + 1
        staff_key_to_id[key] = int(staff_id)
        staff[int(staff_id)] = StaffMember(
            id=int(staff_id),
            name=display_name,
            is_prof=bool(is_prof),
            available_days=set(days),
            available_weeks=set(weeks),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={int(course_id)},
        )
        return int(staff_id)

    for activity_id, (key, group_ids_set) in enumerate(sorted(grouped_events.items()), start=1):
        week, day, slot, duration, course_name, room_name, kind = key
        course_id = int(course_to_id[course_name])
        room_id = int(room_to_id[room_name])
        group_ids = sorted(int(g) for g in group_ids_set)
        course_counts_by_kind[course_id][str(kind)] += 1
        course_group_ids[course_id].update(group_ids)
        staff_names = staff_names_by_key.get(key, {"lecturer": set(), "ta": set()})
        teaching_match = teaching_matches.get(str(course_name), {})
        lecturer_names = set(staff_names.get("lecturer", set()))
        ta_names = set(staff_names.get("ta", set()))
        if not lecturer_names:
            lecturer_names.update(
                str(name)
                for name in teaching_match.get("lecturers", [])
                if str(name).strip()
            )
        if not ta_names:
            ta_names.update(
                str(name)
                for name in teaching_match.get("tas", [])
                if str(name).strip()
            )
        prof_id = _get_staff_id(
            role="prof",
            is_prof=True,
            course_id=course_id,
            course_name=str(course_name),
            explicit_names=lecturer_names,
            kind="LEC",
        )
        ta_id = _get_staff_id(
            role="ta",
            is_prof=False,
            course_id=course_id,
            course_name=str(course_name),
            explicit_names=ta_names,
            kind=str(kind),
        )
        staff_id = int(prof_id if str(kind) == "LEC" else ta_id)

        activities[activity_id] = Activity(
            id=activity_id,
            course_id=course_id,
            week=int(week),
            kind=str(kind),
            duration=int(duration),
            group_ids=group_ids,
            prof_id=int(prof_id),
            ta_id=int(ta_id),
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

    for course_id, counts in course_counts_by_kind.items():
        courses[int(course_id)].lecture_count = int(counts.get("LEC", 0))
        courses[int(course_id)].tutorial_count = int(counts.get("TUT", 0))
        courses[int(course_id)].lab_weeks = int(counts.get("LAB", 0))
        courses[int(course_id)].prof_id = min(
            int(activity.prof_id)
            for activity in activities.values()
            if int(activity.course_id) == int(course_id)
        )
        courses[int(course_id)].ta_id = min(
            int(activity.ta_id)
            for activity in activities.values()
            if int(activity.course_id) == int(course_id)
        )
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
            "force_repeat_weekly_pattern": False,
            "enforce_course_totals": False,
            "enforce_block_professor_rules": False,
            "enforce_staff_daily_caps": False,
            "enforce_staff_weekly_caps": False,
            "enforce_room_availability": True,
            "enforce_travel_time_buffers": False,
            "enforce_building_closures": False,
            "enforce_calendar_rules": False,
            "enforce_precedence_rules": False,
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
        "duplicate_event_rows_skipped": int(duplicate_event_rows),
        "teaching_load_matches": int(len(teaching_matches)),
        "synthetic_staff_pool_size_per_role": int(fallback_staff_count),
        "locked_imported_assignments": bool(lock_imported),
        "assumptions": [
            "CSV import uses explicit or teaching-load staff names when available.",
            "Unmatched courses share balanced synthetic professor/TA pools with at most four base courses per person.",
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
    field_map: Dict[str, str] | None = None,
    transform_config: Dict[str, Any] | None = None,
    teaching_load_path: str | Path | None = None,
) -> Tuple[Instance, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    events = load_timetable_events(
        path,
        field_map=field_map,
        transform_config=transform_config,
    )
    inst, schedule, meta = build_instance_and_schedule_from_events(
        events,
        lock_imported=bool(lock_imported),
        teaching_load_catalog=(
            load_teaching_load_assignments(teaching_load_path)
            if teaching_load_path is not None
            else None
        ),
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
