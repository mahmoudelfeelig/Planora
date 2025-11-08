from __future__ import annotations
import sys
import json
import pickle
from dataclasses import is_dataclass, fields
from pathlib import Path
from typing import Dict, Any, Type, TypeVar, get_origin, get_args

from ortools.sat.python import cp_model
from domain import Instance, Program, Group, Course, StaffMember, Room, Activity
from solver_cp_sat import TimetableSolver

# Optional exporter imports. If not present, CLI still runs solver.
try:
    from exporter import (
        export_group_schedules_to_docx,
        export_staff_schedules_to_docx,
        export_room_schedules_to_docx,
        export_schedule_to_csv,
        export_groups_to_ics,
        export_staff_to_ics,
        export_rooms_to_ics,
    )
except Exception:
    export_group_schedules_to_docx = None  # type: ignore
    export_staff_schedules_to_docx = None  # type: ignore
    export_room_schedules_to_docx = None  # type: ignore
    export_schedule_to_csv = None  # type: ignore
    export_groups_to_ics = None  # type: ignore
    export_staff_to_ics = None  # type: ignore
    export_rooms_to_ics = None  # type: ignore


T = TypeVar("T")

def _coerce_value(t, v):
    origin = get_origin(t)
    if origin is None:
        # simple types
        if t in (int, float, str, bool) or v is None:
            return t(v) if t in (int, float, str, bool) and v is not None else v
        return v
    if origin is list:
        (inner,) = get_args(t)
        return [ _coerce_value(inner, x) for x in (v or []) ]
    if origin is set:
        (inner,) = get_args(t)
        return set(_coerce_value(inner, x) for x in (v or []))
    if origin is dict:
        kt, vt = get_args(t)
        return { _coerce_value(kt, k): _coerce_value(vt, vv) for k, vv in (v or {}).items() }
    return v


def _from_dict(cls: Type[T], payload: Dict[str, Any]) -> T:
    if not is_dataclass(cls):  # type: ignore
        return cls(**payload)  # type: ignore
    kwargs = {}
    for f in fields(cls):  # type: ignore
        if f.name not in payload:
            continue
        kwargs[f.name] = _coerce_value(f.type, payload[f.name])
    return cls(**kwargs)  # type: ignore


def instance_from_json(data: Dict[str, Any]) -> Instance:
    # IDs are serialized as string keys; coerce back to int dicts
    def parse_map(obj_type, mp):
        return { int(k): _from_dict(obj_type, v) for k, v in mp.items() }

    return Instance(
        days = data["days"],
        slots_per_day = int(data["slots_per_day"]),
        weeks = [int(x) for x in data["weeks"]],
        programs = parse_map(Program, data["programs"]),
        groups = parse_map(Group, data["groups"]),
        courses = parse_map(Course, data["courses"]),
        staff = parse_map(StaffMember, data["staff"]),
        rooms = parse_map(Room, data["rooms"]),
        activities = parse_map(Activity, data["activities"]),
    )


def instance_to_json(inst: Instance) -> Dict[str, Any]:
    # Use dataclasses.asdict-like conversion but keep dicts keyed by IDs.
    def conv(obj):
        if is_dataclass(obj):
            return { k: conv(getattr(obj, k)) for k in obj.__annotations__.keys() }  # type: ignore
        if isinstance(obj, dict):
            return { str(k): conv(v) for k, v in obj.items() }
        if isinstance(obj, (list, tuple)):
            return [ conv(x) for x in obj ]
        if isinstance(obj, set):
            return sorted(conv(x) for x in obj)
        return obj

    return {
        "days": inst.days,
        "slots_per_day": inst.slots_per_day,
        "weeks": inst.weeks,
        "programs": conv(inst.programs),
        "groups": conv(inst.groups),
        "courses": conv(inst.courses),
        "staff": conv(inst.staff),
        "rooms": conv(inst.rooms),
        "activities": conv(inst.activities),
    }


def _read_instance(path: Path) -> Instance:
    if path.suffix.lower() == ".pkl":
        with path.open("rb") as f:
            return pickle.load(f)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return instance_from_json(data)
    raise SystemExit(f"Unsupported input format: {path.suffix}")


def _write_result(path: Path, result: Dict[str, Any]) -> None:
    if path.suffix.lower() == ".pkl":
        with path.open("wb") as f:
            pickle.dump(result, f)
        return
    if path.suffix.lower() == ".json":
        with path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return
    raise SystemExit(f"Unsupported output format: {path.suffix}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Solve a timetable instance and output schedule.")
    p.add_argument("instance", help="Path to instance file (.pkl or .json)")
    p.add_argument("out", help="Path to result file (.pkl or .json)")
    p.add_argument("--export-csv", dest="export_csv", help="Write schedule CSV to this path")
    p.add_argument("--export-docx-dir", dest="export_docx_dir", help="Write DOCX files (groups/staff/rooms) to this directory")
    p.add_argument("--export-ics-dir", dest="export_ics_dir", help="Write ICS files (groups/staff/rooms) to this directory")
    p.add_argument("--calendar-start", dest="calendar_start", help="Anchor Monday date for ICS, e.g., 2025-10-06 (defaults to next Monday)")

    args = p.parse_args(argv)

    in_path = Path(args.instance)
    out_path = Path(args.out)

    inst = _read_instance(in_path)

    # Build and solve CP-SAT model
    solver_model = TimetableSolver(inst)
    cp_solver = cp_model.CpSolver()
    status = cp_solver.Solve(solver_model.model)

    result: Dict[str, Any] = {
        "status": int(status),
        "objective": 0.0,
        "schedule": {},
    }

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = solver_model.extract_solution(cp_solver)
        result["objective"] = float(0.0)
        result["schedule"] = schedule

        # Optional exports
        if args.export_csv and export_schedule_to_csv:
            export_schedule_to_csv(inst, schedule, args.export_csv)

        if args.export_docx_dir and export_group_schedules_to_docx:
            Path(args.export_docx_dir).mkdir(parents=True, exist_ok=True)
            export_group_schedules_to_docx(inst, schedule, str(Path(args.export_docx_dir) / "groups.docx"))
            export_staff_schedules_to_docx(inst, schedule, str(Path(args.export_docx_dir) / "staff.docx"))
            export_room_schedules_to_docx(inst, schedule, str(Path(args.export_docx_dir) / "rooms.docx"))

        if args.export_ics_dir and export_groups_to_ics:
            Path(args.export_ics_dir).mkdir(parents=True, exist_ok=True)
            anchor = None
            if args.calendar_start:
                try:
                    y,m,d = map(int, args.calendar_start.split("-"))
                    from datetime import date as _date
                    anchor = _date(y,m,d)
                except Exception:
                    anchor = None
            export_groups_to_ics(inst, schedule, str(Path(args.export_ics_dir) / "groups.ics"), week0_monday=anchor)
            export_staff_to_ics(inst, schedule, str(Path(args.export_ics_dir) / "staff.ics"), week0_monday=anchor)
            export_rooms_to_ics(inst, schedule, str(Path(args.export_ics_dir) / "rooms.ics"), week0_monday=anchor)

    _write_result(out_path, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
