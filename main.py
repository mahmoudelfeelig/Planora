from __future__ import annotations

from typing import Dict, Any
from collections import Counter

from ortools.sat.python import cp_model

from generator import generate_instance
from solver_cp_sat import TimetableSolver
from metaheuristics import LocalSearchImprover
from domain import Instance
from exporter import export_group_schedules_to_docx


# ---------- analysis helpers ----------


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


def compute_group_penalties(
    inst: Instance,
    schedule: Dict[int, Dict[str, Any]],
) -> Dict[int, int]:
    days = inst.days
    weeks = inst.weeks
    S = inst.slots_per_day

    # same weights as LocalSearchImprover.compute_soft_penalty for group-related parts
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
        w = info["week"]
        d = info["day"]
        s0 = info["slot"]
        dur = info["duration"]
        for ds in range(dur):
            s = s0 + ds
            if s < 0 or s >= S:
                continue
            for g_id in info["group_ids"]:
                group_occ[g_id, w, d, s] = 1

    day_active: Dict[tuple, int] = {}
    for g_id in inst.groups.keys():
        for w in weeks:
            for d in days:
                occs = [group_occ[g_id, w, d, s] for s in range(S)]
                day_active[g_id, w, d] = 1 if any(occs) else 0

    penalties: Dict[int, int] = {g_id: 0 for g_id in inst.groups.keys()}
    workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]

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
                blocks = 0
                prev = 0
                load = 0
                for v in occ:
                    if v == 1 and prev == 0:
                        blocks += 1
                    if v == 1:
                        load += 1
                    prev = v
                if blocks > 1:
                    pen += W_STUD_GAPS * (blocks - 1)
                if load > 3:
                    pen += W_BALANCE * (load - 3)

            active_days = sum(day_active[g_id, w, d] for d in days)
            if active_days > 3:
                pen += W_ACTIVE_DAYS * (active_days - 3)

            for d in days:
                occ = [group_occ[g_id, w, d, s] for s in range(S)]
                if occ[0] == 1 and any(occ[s] == 1 for s in range(1, S)):
                    pen += W_EARLY_START

        for wi in range(1, len(weeks)):
            w_prev = weeks[wi - 1]
            w_curr = weeks[wi]
            for d in days:
                if day_active[g_id, w_prev, d] != day_active[g_id, w_curr, d]:
                    pen += W_STABILITY

        penalties[g_id] = pen

    return penalties


def classify_group_quality(pen: int) -> str:
    if pen <= 150:
        return "optimal"
    if pen <= 400:
        return "near-optimal"
    if pen <= 800:
        return "decent"
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


# ---------- main flow ----------


def main():
    # change MODE if you want: "small_demo", "block_profs", "labs_only",
    # "mixed_large", "random", "target_case"
    MODE = "target_case"

    CP_TIME_LIMIT = 120.0          # seconds for CP-SAT
    LS_ITERATIONS = 1_000_000_000_000          # metaheuristic search iterations
    LS_START_TEMP = 5.0
    LS_END_TEMP = 0.1

    # output path for DOCX export
    EXPORT_PATH = f"timetable_{MODE}.docx"

    inst = generate_instance(mode=MODE)
    print_instance_stats(inst)

    solver_model = TimetableSolver(inst)
    cp_solver, status = solver_model.solve(time_limit_seconds=CP_TIME_LIMIT)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible solution, status:", status)
        return

    schedule = solver_model.extract_solution(cp_solver)
    print(f"CP-SAT status: {status} (0=FEASIBLE, 4=OPTIMAL); time limit = {CP_TIME_LIMIT}s")

    ls = LocalSearchImprover(inst)
    base_pen = ls.compute_soft_penalty(schedule)
    print("Soft penalty before local search:", base_pen)

    improved = ls.improve(
        schedule,
        iterations=LS_ITERATIONS,
        start_temp=LS_START_TEMP,
        end_temp=LS_END_TEMP,
    )
    improved_pen = ls.compute_soft_penalty(improved)
    print("Soft penalty after local search:", improved_pen)

    print_group_quality(inst, improved)

    # dump some activities for inspection
    print("=== Sample activities ===")
    for a_id, info in sorted(improved.items())[:200]:
        print(
            f"A{a_id}: week {info['week']} {info['day']} "
            f"slot {info['slot']} dur {info['duration']} "
            f"room {info['room_id']} staff {info['staff_id']} "
            f"course {info['course_id']} kind {info['kind']} "
            f"groups {info['group_ids']}"
        )

    # export schedule to DOCX (per-group, 12 pages each) using same exporter as UI
    try:
        print(f"Exporting group schedules to {EXPORT_PATH} ...")
        export_group_schedules_to_docx(inst, improved, EXPORT_PATH)
        print(f"Export finished: {EXPORT_PATH}")
    except Exception as e:
        print("Export error:", e)


if __name__ == "__main__":
    main()
