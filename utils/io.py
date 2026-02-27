from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.generator import instance_to_json


def _to_int_list(values: List[Any]) -> List[int]:
    return [int(v) for v in values]


def _to_str_set(values: List[Any]) -> set[str]:
    return {str(v) for v in values}


def _to_int_set(values: List[Any]) -> set[int]:
    return {int(v) for v in values}


def _availability_from_json(values: Any) -> set[Tuple[str, int]] | None:
    if values is None:
        return None
    pairs: set[Tuple[str, int]] = set()
    for item in values:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            day, slot = item
            pairs.add((str(day), int(slot)))
    return pairs


def instance_from_json(data: Dict[str, Any]) -> Instance:
    programs = {
        int(pid): Program(
            id=int(p["id"]),
            name=str(p["name"]),
            course_ids=_to_int_list(p.get("course_ids", [])),
            group_ids=_to_int_list(p.get("group_ids", [])),
        )
        for pid, p in (data.get("programs") or {}).items()
    }
    groups = {
        int(gid): Group(
            id=int(g["id"]),
            name=str(g["name"]),
            program_id=int(g["program_id"]),
            size=int(g["size"]),
            course_ids=_to_int_list(g.get("course_ids", [])),
            preferred_free_days=int(g.get("preferred_free_days", 2)),
        )
        for gid, g in (data.get("groups") or {}).items()
    }
    courses = {
        int(cid): Course(
            id=int(c["id"]),
            code=str(c["code"]),
            name=str(c["name"]),
            structure_type=str(c["structure_type"]),
            lecture_count=int(c.get("lecture_count", 0)),
            tutorial_count=int(c.get("tutorial_count", 0)),
            lab_weeks=int(c.get("lab_weeks", 0)),
            lab_duration=int(c.get("lab_duration", 0)),
            share_lecture_group_ids=_to_int_list(c.get("share_lecture_group_ids", [])),
            prof_id=int(c["prof_id"]) if c.get("prof_id") is not None else None,
            ta_id=int(c["ta_id"]) if c.get("ta_id") is not None else None,
        )
        for cid, c in (data.get("courses") or {}).items()
    }
    staff = {
        int(sid): StaffMember(
            id=int(s["id"]),
            name=str(s["name"]),
            is_prof=bool(s["is_prof"]),
            available_days=_to_str_set(s.get("available_days", [])),
            max_slots_per_day=int(s["max_slots_per_day"]) if s.get("max_slots_per_day") is not None else None,
            max_slots_per_week=int(s["max_slots_per_week"]) if s.get("max_slots_per_week") is not None else None,
            can_teach_courses=_to_int_set(s.get("can_teach_courses", [])),
            prefers_block=bool(s.get("prefers_block", False)),
            blocks_only=bool(s.get("blocks_only", False)),
            available_weeks=(
                _to_int_set(s.get("available_weeks", []))
                if s.get("available_weeks") is not None
                else None
            ),
        )
        for sid, s in (data.get("staff") or {}).items()
    }
    rooms = {
        int(rid): Room(
            id=int(r["id"]),
            name=str(r["name"]),
            capacity=int(r["capacity"]),
            room_type=str(r["room_type"]),
            specialization_tags=_to_str_set(r.get("specialization_tags", [])),
            availability=_availability_from_json(r.get("availability", None)),
        )
        for rid, r in (data.get("rooms") or {}).items()
    }
    activities = {
        int(aid): Activity(
            id=int(a["id"]),
            course_id=int(a["course_id"]),
            week=int(a["week"]),
            kind=str(a["kind"]),
            duration=int(a["duration"]),
            group_ids=_to_int_list(a.get("group_ids", [])),
            prof_id=int(a["prof_id"]),
            ta_id=int(a["ta_id"]),
            requires_specialization=a.get("requires_specialization", None),
        )
        for aid, a in (data.get("activities") or {}).items()
    }

    inst = Instance(
        days=[str(d) for d in data.get("days", [])],
        slots_per_day=int(data.get("slots_per_day", 0)),
        weeks=[int(w) for w in data.get("weeks", [])],
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        locked_activities=data.get("locked_activities", {}) or {},
        soft_weights=data.get("soft_weights", {}) or {},
        hard_constraints=data.get("hard_constraints", {}) or {},
    )

    # Restore optional time labeling fields when present.
    for key in ("day_start_time", "slot_minutes", "slot_break_minutes", "time_labels"):
        if key in data:
            setattr(inst, key, data[key])

    return inst


def read_instance(path: str | Path) -> Instance:
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return instance_from_json(data)
    if path.suffix.lower() == ".pkl":
        return pickle.loads(path.read_bytes())
    raise ValueError(f"Unsupported instance format: {path.suffix}")


def schedule_to_rows(schedule: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for a_id, info in schedule.items():
        row = dict(info)
        row["activity_id"] = int(a_id)
        rows.append(row)
    return rows


def schedule_from_rows(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    schedule: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        a_id = int(row["activity_id"])
        info = dict(row)
        info.pop("activity_id", None)
        schedule[a_id] = info
    return schedule


def read_schedule_csv(path: str | Path) -> Dict[int, Dict[str, Any]]:
    import csv

    path = Path(path)
    schedule: Dict[int, Dict[str, Any]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a_id = int(row["activity_id"])
            groups = row.get("group_ids", "")
            group_ids = [int(x) for x in groups.split(";") if x.strip()] if groups else []
            schedule[a_id] = {
                "week": int(row["week"]),
                "day": row["day"],
                "slot": int(row["slot"]),
                "duration": int(row["duration"]),
                "room_id": int(row["room_id"]) if row.get("room_id") not in (None, "", "None") else None,
                "staff_id": int(row["staff_id"]) if row.get("staff_id") not in (None, "", "None") else None,
                "course_id": int(row["course_id"]),
                "group_ids": group_ids,
                "kind": row["kind"],
            }
    return schedule


def _parse_groups_field(raw: Any, *, separator: str = ";") -> List[int]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    out: List[int] = []
    for part in text.split(separator):
        token = str(part).strip()
        if not token:
            continue
        out.append(int(token))
    return out


def read_schedule_csv_mapped(
    path: str | Path,
    *,
    field_map: Dict[str, str],
    group_separator: str = ";",
) -> Dict[int, Dict[str, Any]]:
    """
    Read schedule CSV using custom header mapping.
    Required mapped logical fields:
      activity_id, week, day, slot, duration, course_id, kind
    Optional:
      room_id, staff_id, group_ids
    """
    import csv

    required = ("activity_id", "week", "day", "slot", "duration", "course_id", "kind")
    for key in required:
        src = str(field_map.get(key, "")).strip()
        if not src:
            raise ValueError(f"Missing mapping for required field: {key}")

    path = Path(path)
    schedule: Dict[int, Dict[str, Any]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        for key in required:
            src = str(field_map.get(key, "")).strip()
            if src not in headers:
                raise ValueError(f"Mapped column not found for {key}: {src}")

        for row in reader:
            a_id = int(row[str(field_map["activity_id"])])
            week = int(row[str(field_map["week"])])
            day = str(row[str(field_map["day"])])
            slot = int(row[str(field_map["slot"])])
            duration = int(row[str(field_map["duration"])])
            course_id = int(row[str(field_map["course_id"])])
            kind = str(row[str(field_map["kind"])])
            staff_col = str(field_map.get("staff_id", "")).strip()
            room_col = str(field_map.get("room_id", "")).strip()
            groups_col = str(field_map.get("group_ids", "")).strip()
            staff_raw = row.get(staff_col) if staff_col else None
            room_raw = row.get(room_col) if room_col else None
            groups_raw = row.get(groups_col) if groups_col else None
            staff_id = (
                int(staff_raw)
                if staff_raw not in (None, "", "None", "none", "NULL", "null")
                else None
            )
            room_id = (
                int(room_raw)
                if room_raw not in (None, "", "None", "none", "NULL", "null")
                else None
            )
            group_ids = _parse_groups_field(groups_raw, separator=str(group_separator))
            schedule[a_id] = {
                "week": int(week),
                "day": str(day),
                "slot": int(slot),
                "duration": int(duration),
                "room_id": room_id,
                "staff_id": staff_id,
                "course_id": int(course_id),
                "group_ids": [int(g) for g in group_ids],
                "kind": str(kind),
            }
    return schedule


def write_scenario(path: str | Path, inst: Instance, schedule: Dict[int, Dict[str, Any]], meta: Dict[str, Any] | None = None) -> None:
    path = Path(path)
    meta = meta or {}
    if path.suffix.lower() == ".pkl":
        payload = {"instance": inst, "schedule": schedule, "meta": meta}
        path.write_bytes(pickle.dumps(payload))
        return
    if path.suffix.lower() == ".json":
        data = instance_to_json(inst)
        data["locked_activities"] = getattr(inst, "locked_activities", {}) or {}
        data["soft_weights"] = getattr(inst, "soft_weights", {}) or {}
        data["hard_constraints"] = getattr(inst, "hard_constraints", {}) or {}
        for key in ("day_start_time", "slot_minutes", "slot_break_minutes", "time_labels"):
            if hasattr(inst, key):
                data[key] = getattr(inst, key)
        payload = {
            "instance": data,
            "schedule": schedule_to_rows(schedule),
            "meta": meta,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    raise ValueError(f"Unsupported scenario format: {path.suffix}")


def read_scenario(path: str | Path) -> Tuple[Instance, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() == ".pkl":
        payload = pickle.loads(path.read_bytes())
        return payload["instance"], payload["schedule"], payload.get("meta", {})
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        inst = instance_from_json(payload["instance"])
        schedule = schedule_from_rows(payload.get("schedule", []))
        meta = payload.get("meta", {})
        return inst, schedule, meta
    raise ValueError(f"Unsupported scenario format: {path.suffix}")


def schedule_to_dict(schedule: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    return schedule_from_rows(schedule_to_rows(schedule))


def schedule_to_json(schedule: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return schedule_to_rows(schedule)
