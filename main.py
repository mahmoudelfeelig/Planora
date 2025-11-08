from __future__ import annotations

from typing import Dict, Any, Iterable
from collections import Counter, defaultdict
from datetime import datetime, date, time, timedelta

from ortools.sat.python import cp_model

from generator import generate_instance
from solver_cp_sat import TimetableSolver
from metaheuristics import LocalSearchImprover
from domain import Instance
from exporter import (
    export_group_schedules_to_docx,
    export_groups_ics_per_id,
    export_staff_ics_per_id,
    export_rooms_ics_per_id,
)

# ---------- time labels ----------

def build_time_labels(slots_per_day: int, day_start: time, slot_minutes: int, break_minutes: int = 0) -> list[str]:
    labels: list[str] = []
    cur = datetime.combine(date.today(), day_start)
    for _ in range(slots_per_day):
        start = cur
        end = start + timedelta(minutes=slot_minutes)
        labels.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
        cur = end + timedelta(minutes=break_minutes)
    return labels

def stamp_instance_time(inst: Instance, day_start_str: str, slot_minutes: int, break_minutes: int = 0) -> None:
    inst.day_start_time = day_start_str
    inst.slot_minutes = int(slot_minutes)
    inst.slot_break_minutes = int(break_minutes)
    hh, mm = [int(x) for x in day_start_str.split(":")]
    inst.time_labels = build_time_labels(inst.slots_per_day, time(hh, mm), slot_minutes, break_minutes)

# ---------- feasibility helpers (new) ----------

def _has_sun(days: list[str]) -> bool:
    return any(d.upper().startswith("SUN") for d in days)

def normalize_instance_for_spec(inst: Instance) -> None:
    """
    Make the generated instance compatible with the new hard rules:
      - Ensure 'SUN' exists in inst.days for the 'Sunday off' rule.
      - Give every staffer availability on all listed days; the solver
        will enforce Sunday off + one extra free day (or ≤2 days for block profs).
      - Quick sanity for specialized lab tags: warn if a LAB requires a tag with no room.
    """
    # 1) Ensure 'SUN' in days list
    if not _has_sun(inst.days):
        inst.days = list(inst.days) + ["SUN"]

    # 2) Set all staff available on all days (solver applies the actual off-days)
    all_days = list(inst.days)
    for s in inst.staff.values():
        s.available_days = list(all_days)

    # 3) Warn if any specialized lab tag has no room (keeps your strict matching)
    tags_present = defaultdict(int)
    for r in inst.rooms.values():
        if getattr(r, "room_type", None) == "SPECIALIZED_LAB":
            for t in getattr(r, "specialization_tags", []) or []:
                tags_present[t] += 1
    missing = set()
    for a in inst.activities.values():
        if a.kind == "LAB":
            tag = getattr(a, "requires_specialization", None)
            if tag and tags_present.get(tag, 0) == 0:
                missing.add(tag)
    if missing:
        print("[WARN] No specialized lab rooms for tags:", sorted(missing))

def print_instance_stats(inst: Instance) -> None:
    profs = sum(1 for s in inst.staff.values() if s.is_prof)
    tas = sum(1 for s in inst.staff.values() if not s.is_prof)

    print("=== Instance stats ===")
    print(f"Programs       : {len(inst.programs)}")
    print(f"Groups         : {len(inst.groups)}")
    print(f"Courses        : {len(inst.courses)}")
    print(f"Staff total    : {len(inst.staff)}")
    print(f"  Professors   : {profs}")
    print(f"  TAs          : {tas}")
    print(f"Rooms          : {len(inst.rooms)}")
    print(f"Activities     : {len(inst.activities)}")

    lec = sum(1 for a in inst.activities.values() if a.kind == "LEC")
    tut = sum(1 for a in inst.activities.values() if a.kind == "TUT")
    lab = sum(1 for a in inst.activities.values() if a.kind == "LAB")
    print(f"  LEC activities: {lec}")
    print(f"  TUT activities: {tut}")
    print(f"  LAB activities: {lab}")

    c_struct = Counter(c.structure_type for c in inst.courses.values())
    print("Course structures:")
    for stype, cnt in c_struct.items():
        print(f"  {stype}: {cnt}")

    print("Groups and their course counts:")
    for g_id, g in inst.groups.items():
        print(f"  {g.name} (id {g_id}), size={g.size}, courses={len(g.course_ids)}")
    print("===")

def _is_block_prof(staff) -> bool:
    return bool(getattr(staff, "blocks_only", False) or getattr(staff, "is_block_prof", False))

def check_staff_weekly_capacity(inst: Instance) -> None:
    """
    Prints warnings when any staff's required slot load per week exceeds
    what is schedulable under the hard rules.
    """
    days = inst.days
    S = inst.slots_per_day
    has_sun = _has_sun(days)
    cap_by_staff: Dict[int, int] = {}
    for sid, s in inst.staff.items():
        if _is_block_prof(s):
            cap_by_staff[sid] = 2 * S  # ≤2 days * 5 slots per your model
        else:
            work_days = len(days) - (1 if has_sun else 0) - 1  # Sunday + one extra free day
            cap_by_staff[sid] = work_days * S

    load_by_staff_week: Dict[tuple, int] = defaultdict(int)
    for a in inst.activities.values():
        sid = a.prof_id if a.kind == "LEC" else a.ta_id
        load_by_staff_week[(sid, a.week)] += int(a.duration)

    flagged = False
    for (sid, w), req in sorted(load_by_staff_week.items()):
        cap = cap_by_staff.get(sid, 0)
        if req > cap:
            flagged = True
            s = inst.staff[sid]
            kind = "BLOCK" if _is_block_prof(s) else ("PROF" if s.is_prof else "TA")
            print(f"[WARN] Staff '{s.name}' ({kind}) week {w}: need {req} slots > capacity {cap}")
    if not flagged:
        print("Staff weekly loads within theoretical capacity bounds.")

# ---------- group quality (unchanged) ----------

def compute_group_penalties(inst: Instance, schedule: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
    days = inst.days
    weeks = inst.weeks
    S = inst.slots_per_day

    W_STUD_FREE_DAYS = 10
    W_STUD_FREE_MF = 5
    W_STUD_GAPS = 5
    W_ACTIVE_DAYS = 3
    W_EARLY_START = 2
    W_BALANCE = 2
    W_STABILITY = 1

    group_occ: Dict[tuple, int] = {}
    for g_id in inst.groups.keys():
        for w in weeks:
            for d in days:
                for s in range(S):
                    group_occ[g_id, w, d, s] = 0

    for a_id, info in schedule.items():
        w = info["week"]; d = info["day"]; s0 = info["slot"]; dur = info["duration"]
        for ds in range(dur):
            s = s0 + ds
            if 0 <= s < S:
                for g_id in info["group_ids"]:
                    group_occ[g_id, w, d, s] = 1

    day_active: Dict[tuple, int] = {}
    for g_id in inst.groups.keys():
        for w in weeks:
            for d in days:
                occs = [group_occ[g_id, w, d, s] for s in range(S)]
                day_active[g_id, w, d] = 1 if any(occs) else 0

    penalties: Dict[int, int] = {g_id: 0 for g_id in inst.groups.keys()}
    workdays = [d for d in days if d in {"MON","TUE","WED","THU","FRI"}]

    for g_id, g in inst.groups.items():
        pen = 0
        for w in weeks:
            free_days = sum(1 - day_active[g_id, w, d] for d in days)
            if free_days < g.preferred_free_days:
                pen += W_STUD_FREE_DAYS * (g.preferred_free_days - free_days)
            free_mf = sum(1 - day_active[g_id, w, d] for d in workdays)
            if free_mf < g.preferred_free_days:
                pen += W_STUD_FREE_MF * (g.preferred_free_days - free_mf)
            for d in days:
                occ = [group_occ[g_id, w, d, s] for s in range(S)]
                blocks = 0; prev = 0; load = 0
                for v in occ:
                    if v == 1 and prev == 0: blocks += 1
                    if v == 1: load += 1
                    prev = v
                if blocks > 1: pen += W_STUD_GAPS * (blocks - 1)
                if load > 3: pen += W_BALANCE * (load - 3)
            active_days = sum(day_active[g_id, w, d] for d in days)
            if active_days > 3: pen += W_ACTIVE_DAYS * (active_days - 3)
            for d in days:
                occ = [group_occ[g_id, w, d, s] for s in range(S)]
                if occ[0] == 1 and any(occ[s] == 1 for s in range(1, S)):
                    pen += W_EARLY_START
        for wi in range(1, len(weeks)):
            w_prev = weeks[wi-1]; w_curr = weeks[wi]
            for d in days:
                if day_active[g_id, w_prev, d] != day_active[g_id, w_curr, d]:
                    pen += W_STABILITY
        penalties[g_id] = pen
    return penalties

def classify_group_quality(pen: int) -> str:
    if pen <= 150: return "optimal"
    if pen <= 400: return "near-optimal"
    if pen <= 800: return "decent"
    return "bad"

def print_group_quality(inst: Instance, schedule: Dict[int, Dict[str, Any]]) -> None:
    group_pens = compute_group_penalties(inst, schedule)
    print("=== Per-group quality ===")
    for g_id in sorted(inst.groups.keys()):
        g = inst.groups[g_id]
        pen = group_pens.get(g_id, 0)
        label = classify_group_quality(pen)
        print(f"  {g.name} (id {g_id}): {pen} ({label})")
    print("===")

# ---------- main ----------

def main():
    MODE = "target_case"

    CP_TIME_LIMIT = 120.0
    LS_ITERATIONS = 10000
    LS_START_TEMP = 5.0
    LS_END_TEMP = 0.1

    DAY_START = "08:30"
    SLOT_MINUTES = 90
    BREAK_MINUTES = 0

    EXPORT_DOCX = f"timetable_{MODE}.docx"
    EXPORT_ICS_DIR = f"ics_{MODE}"

    inst = generate_instance(mode=MODE)

    # normalize to satisfy new hard rules
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, DAY_START, SLOT_MINUTES, BREAK_MINUTES)
    print_instance_stats(inst)
    check_staff_weekly_capacity(inst)  # prints warnings only

    solver_model = TimetableSolver(inst)
    cp_solver, status = solver_model.solve(time_limit_seconds=CP_TIME_LIMIT)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible solution, status:", status)
        return

    schedule = solver_model.extract_solution(cp_solver)
    print(f"CP-SAT status: {status} (0=FEASIBLE, 4=OPTIMAL); time limit = {CP_TIME_LIMIT}s")

    # optional local search: off by default to avoid breaking hard rules
    improved = schedule
    if LS_ITERATIONS and LS_ITERATIONS > 0:
        ls = LocalSearchImprover(inst)
        base_pen = ls.compute_soft_penalty(schedule)
        print("Soft penalty before local search:", base_pen)
        improved = ls.improve(
            schedule, iterations=LS_ITERATIONS,
            start_temp=LS_START_TEMP, end_temp=LS_END_TEMP,
        )
        print("Soft penalty after local search:", ls.compute_soft_penalty(improved))

    print_group_quality(inst, improved)

    print("=== Sample activities ===")
    for a_id, info in sorted(improved.items())[:200]:
        print(
            f"A{a_id}: week {info['week']} {info['day']} "
            f"slot {info['slot']} dur {info['duration']} "
            f"room {info['room_id']} staff {info['staff_id']} "
            f"course {info['course_id']} kind {info['kind']} "
            f"groups {info['group_ids']}"
        )

    try:
        print(f"Exporting group DOCX to {EXPORT_DOCX} ...")
        export_group_schedules_to_docx(inst, improved, EXPORT_DOCX)
        print("Export finished:", EXPORT_DOCX)
    except Exception as e:
        print("Export error:", e)

    # new: per-entity ICS files (groups, staff, rooms)
    try:
        export_groups_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        export_staff_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        export_rooms_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        print("ICS exported to:", EXPORT_ICS_DIR)
    except Exception as e:
        print("ICS export error:", e)


if __name__ == "__main__":
    main()
