from __future__ import annotations

from typing import Dict, List, Tuple, Optional

from ortools.sat.python import cp_model

from domain import Instance


class TimetableSolver:
    """
    CP-SAT feasibility model:

    - Variables: start time (day+slot within week) for each activity.
    - Hard constraints:
        * staff availability by day
        * no group overlaps
        * no staff overlaps
        * staff weekly load limit when max_slots_per_week is set (block profs)
        * aggregate lecture / big-lecture / lab capacity per slot
        * per-specialisation capacity for specialised labs
    - Rooms are assigned afterwards by a greedy heuristic.
    """

    def __init__(self, inst: Instance):
        self.inst = inst
        self.model = cp_model.CpModel()

        self._precompute()
        self._build_variables()
        self._add_constraints()

    # ---------- precomputation ----------

    def _precompute(self) -> None:
        inst = self.inst

        self.days: List[str] = inst.days
        self.weeks: List[int] = inst.weeks
        self.slots_per_day: int = inst.slots_per_day
        self.num_days: int = len(self.days)
        self.times_per_week: int = self.num_days * self.slots_per_day

        # activities per week
        self.activities_by_week: Dict[int, List[int]] = {w: [] for w in self.weeks}
        for a_id, act in inst.activities.items():
            self.activities_by_week[act.week].append(a_id)

        # which staff member runs each activity
        self.activity_staff: Dict[int, int] = {}
        for a_id, act in inst.activities.items():
            if act.kind == "LEC":
                self.activity_staff[a_id] = act.prof_id
            else:
                # tutorials and labs treated as TA-led
                self.activity_staff[a_id] = act.ta_id

        # room categorisation
        self.lecture_room_ids: List[int] = []
        self.big_lecture_room_ids: List[int] = []
        self.lab_room_ids: List[int] = []
        self.special_lab_rooms_by_tag: Dict[str, List[int]] = {}

        for r_id, room in inst.rooms.items():
            if room.room_type == "LECTURE":
                self.lecture_room_ids.append(r_id)
                if room.capacity >= 200:
                    self.big_lecture_room_ids.append(r_id)
            elif room.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                self.lab_room_ids.append(r_id)
                if room.room_type == "SPECIALIZED_LAB":
                    for tag in room.specialization_tags:
                        self.special_lab_rooms_by_tag.setdefault(tag, []).append(r_id)

        self.num_lec_rooms = len(self.lecture_room_ids)
        self.num_big_lec_rooms = len(self.big_lecture_room_ids)
        self.num_lab_rooms = len(self.lab_room_ids)

        # room class for capacity constraints
        self.room_class: Dict[int, str] = {}
        for a_id, act in inst.activities.items():
            if act.kind == "LAB":
                self.room_class[a_id] = "LAB"
            else:
                total_students = sum(inst.groups[g].size for g in act.group_ids)
                if total_students > 80:
                    self.room_class[a_id] = "BIG_LEC"
                else:
                    self.room_class[a_id] = "LEC"

        # activities per group/week and per staff/week
        self.acts_by_group_week: Dict[Tuple[int, int], List[int]] = {}
        for a_id, act in inst.activities.items():
            for g_id in act.group_ids:
                key = (g_id, act.week)
                self.acts_by_group_week.setdefault(key, []).append(a_id)

        self.acts_by_staff_week: Dict[Tuple[int, int], List[int]] = {}
        for a_id, act in inst.activities.items():
            s_id = self.activity_staff[a_id]
            key = (s_id, act.week)
            self.acts_by_staff_week.setdefault(key, []).append(a_id)

        # allowed start times per activity (respect staff availability and duration)
        self.allowed_starts: Dict[int, List[int]] = {}
        for a_id, act in inst.activities.items():
            staff_id = self.activity_staff[a_id]
            staff = inst.staff[staff_id]
            allowed: List[int] = []

            max_start_slot = self.slots_per_day - act.duration
            if max_start_slot < 0:
                raise ValueError(
                    f"Activity {a_id} duration {act.duration} "
                    f"exceeds day slots {self.slots_per_day}"
                )

            for day_index, day in enumerate(self.days):
                if day not in staff.available_days:
                    continue
                for slot in range(max_start_slot + 1):
                    t = day_index * self.slots_per_day + slot
                    allowed.append(t)

            if not allowed:
                raise ValueError(f"No allowed start times for activity {a_id}")

            self.allowed_starts[a_id] = allowed

    # ---------- variables ----------

    def _build_variables(self) -> None:
        m = self.model

        self.start: Dict[int, cp_model.IntVar] = {}
        self.x: Dict[Tuple[int, int], cp_model.BoolVar] = {}

        T_week = self.times_per_week

        for a_id, act in self.inst.activities.items():
            allowed = self.allowed_starts[a_id]

            start_var = m.NewIntVar(0, T_week - 1, f"start_a{a_id}")
            self.start[a_id] = start_var

            bools: List[cp_model.BoolVar] = []
            for t in allowed:
                b = m.NewBoolVar(f"x_a{a_id}_t{t}")
                self.x[a_id, t] = b
                bools.append(b)

            # each activity chooses exactly one start time
            m.Add(sum(bools) == 1)
            # link integer start to chosen t
            m.Add(start_var == sum(t * self.x[a_id, t] for t in allowed))

    # ---------- constraints ----------

    def _add_constraints(self) -> None:
        m = self.model
        inst = self.inst
        T_week = self.times_per_week

        # 1) no group overlaps
        for g_id in inst.groups.keys():
            for w in self.weeks:
                acts = self.acts_by_group_week.get((g_id, w))
                if not acts:
                    continue
                for tau in range(T_week):
                    terms: List[cp_model.BoolVar] = []
                    for a_id in acts:
                        act = inst.activities[a_id]
                        dur = act.duration
                        for t in self.allowed_starts[a_id]:
                            if t <= tau < t + dur:
                                terms.append(self.x[a_id, t])
                    if terms:
                        m.Add(sum(terms) <= 1)

        # 2) no staff overlaps
        for s_id in inst.staff.keys():
            for w in self.weeks:
                acts = self.acts_by_staff_week.get((s_id, w))
                if not acts:
                    continue
                for tau in range(T_week):
                    terms: List[cp_model.BoolVar] = []
                    for a_id in acts:
                        act = inst.activities[a_id]
                        dur = act.duration
                        for t in self.allowed_starts[a_id]:
                            if t <= tau < t + dur:
                                terms.append(self.x[a_id, t])
                    if terms:
                        m.Add(sum(terms) <= 1)

        # 3) staff weekly load limits (used for block profs)
        for s_id, staff in inst.staff.items():
            if staff.max_slots_per_week is None:
                continue
            for w in self.weeks:
                acts = self.acts_by_staff_week.get((s_id, w))
                if not acts:
                    continue
                load_terms: List[cp_model.IntVar] = []
                for a_id in acts:
                    act = inst.activities[a_id]
                    for t in self.allowed_starts[a_id]:
                        load_terms.append(act.duration * self.x[a_id, t])
                if load_terms:
                    m.Add(sum(load_terms) <= staff.max_slots_per_week)

        # 4) room capacities per slot, including per-tag specialisation for labs
        for w in self.weeks:
            acts_w = self.activities_by_week[w]
            if not acts_w:
                continue

            for tau in range(T_week):
                lab_terms_all: List[cp_model.BoolVar] = []
                lec_terms_all: List[cp_model.BoolVar] = []
                big_lec_terms: List[cp_model.BoolVar] = []
                tag_terms: Dict[str, List[cp_model.BoolVar]] = {}

                for a_id in acts_w:
                    act = inst.activities[a_id]
                    dur = act.duration
                    allowed = self.allowed_starts[a_id]
                    for t in allowed:
                        if not (t <= tau < t + dur):
                            continue

                        if act.kind == "LAB":
                            lab_terms_all.append(self.x[a_id, t])
                            if act.requires_specialization:
                                tag_terms.setdefault(act.requires_specialization, []).append(
                                    self.x[a_id, t]
                                )
                        else:
                            cls = self.room_class[a_id]
                            if cls == "BIG_LEC":
                                big_lec_terms.append(self.x[a_id, t])
                                lec_terms_all.append(self.x[a_id, t])
                            else:
                                lec_terms_all.append(self.x[a_id, t])

                # total lab capacity (all lab rooms)
                if lab_terms_all and self.num_lab_rooms > 0:
                    m.Add(sum(lab_terms_all) <= self.num_lab_rooms)

                # per-tag specialised lab capacity
                for tag, terms in tag_terms.items():
                    cap = len(self.special_lab_rooms_by_tag.get(tag, []))
                    if cap > 0:
                        m.Add(sum(terms) <= cap)

                # big lecture rooms
                if big_lec_terms and self.num_big_lec_rooms > 0:
                    m.Add(sum(big_lec_terms) <= self.num_big_lec_rooms)

                # total lecture rooms (for lec+tut)
                if lec_terms_all and self.num_lec_rooms > 0:
                    m.Add(sum(lec_terms_all) <= self.num_lec_rooms)

        # pure feasibility; soft stuff is handled by local search
        # so no CP objective here

    # ---------- solving and extraction ----------

    def solve(self, time_limit_seconds: Optional[float] = None):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = 8
        status = solver.Solve(self.model)
        return solver, status

    def extract_solution(self, solver: cp_model.CpSolver):
        inst = self.inst
        schedule: Dict[int, Dict[str, object]] = {}

        for a_id, act in inst.activities.items():
            t = solver.Value(self.start[a_id])
            day_index = t // self.slots_per_day
            slot = t % self.slots_per_day
            day = self.days[day_index]
            staff_id = self.activity_staff[a_id]

            schedule[a_id] = {
                "room_id": None,  # filled later
                "staff_id": staff_id,
                "week": act.week,
                "day": day,
                "slot": slot,
                "duration": act.duration,
                "group_ids": list(act.group_ids),
                "course_id": act.course_id,
                "kind": act.kind,
            }

        assign_rooms_greedily(inst, schedule)
        return schedule


# ---------- greedy room assignment ----------


def assign_rooms_greedily(inst: Instance, schedule: Dict[int, Dict[str, object]]) -> None:
    """
    Assign a concrete room to each activity, slot by slot.

    Rules:
      - labs go to lab rooms (specialised first, then generic)
      - big lectures go to big lecture rooms
      - all other lectures/tutorials go to lecture rooms
      - obey capacity
      - if a specialised lab has no specialised room left,
        fall back to any free lab room with enough capacity
        before failing.
    """

    days = inst.days
    weeks = inst.weeks
    slots_per_day = inst.slots_per_day

    # room lists
    lecture_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]
    big_lecture_rooms = [
        r_id for r_id, r in inst.rooms.items()
        if r.room_type == "LECTURE" and r.capacity >= 200
    ]
    lab_rooms = [
        r_id for r_id, r in inst.rooms.items()
        if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")
    ]
    spec_rooms_by_tag: Dict[str, List[int]] = {}
    for r_id, room in inst.rooms.items():
        if room.room_type == "SPECIALIZED_LAB":
            for tag in room.specialization_tags:
                spec_rooms_by_tag.setdefault(tag, []).append(r_id)

    # map (week, day, slot) -> activities covering that slot
    slot_acts: Dict[Tuple[int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        week = info["week"]
        day = info["day"]
        start_slot = info["slot"]
        duration = info["duration"]
        for off in range(duration):
            s = start_slot + off
            key = (week, day, s)
            slot_acts.setdefault(key, []).append(a_id)

    # total students per activity
    total_students: Dict[int, int] = {}
    for a_id, info in schedule.items():
        total_students[a_id] = sum(inst.groups[g].size for g in info["group_ids"])

    # assign per slot
    for w in weeks:
        for d in days:
            for s in range(slots_per_day):
                key = (w, d, s)
                acts = slot_acts.get(key)
                if not acts:
                    continue

                # rooms already fixed for these activities
                occupied_rooms = {
                    schedule[a_id]["room_id"]
                    for a_id in acts
                    if schedule[a_id]["room_id"] is not None
                }
                occupied_rooms.discard(None)

                unassigned = [a_id for a_id in acts if schedule[a_id]["room_id"] is None]
                if not unassigned:
                    continue

                # classify
                labs_spec_by_tag: Dict[str, List[int]] = {}
                labs_generic: List[int] = []
                big_lecs: List[int] = []
                small_lecs: List[int] = []

                for a_id in unassigned:
                    act = inst.activities[a_id]
                    size = total_students[a_id]

                    if act.kind == "LAB":
                        tag = act.requires_specialization
                        if tag:
                            labs_spec_by_tag.setdefault(tag, []).append(a_id)
                        else:
                            labs_generic.append(a_id)
                    else:
                        if size > 80:
                            big_lecs.append(a_id)
                        else:
                            small_lecs.append(a_id)

                # specialised labs first
                for tag, acts_tag in labs_spec_by_tag.items():
                    spec_rooms = spec_rooms_by_tag.get(tag, [])
                    available_spec = [r for r in spec_rooms if r not in occupied_rooms]
                    available_labs = [r for r in lab_rooms if r not in occupied_rooms]

                    for a_id in acts_tag:
                        size = total_students[a_id]
                        room_id = None

                        # try specialised rooms of that tag
                        for r in list(available_spec):
                            if inst.rooms[r].capacity >= size:
                                room_id = r
                                available_spec.remove(r)
                                break

                        # fallback: any lab room
                        if room_id is None:
                            for r in list(available_labs):
                                if inst.rooms[r].capacity >= size:
                                    room_id = r
                                    available_labs.remove(r)
                                    break

                        if room_id is None:
                            raise ValueError(
                                f"Failed to assign specialised lab for activity {a_id}"
                            )

                        schedule[a_id]["room_id"] = room_id
                        occupied_rooms.add(room_id)

                # remaining generic labs
                available_labs = [r for r in lab_rooms if r not in occupied_rooms]
                for a_id in labs_generic:
                    size = total_students[a_id]
                    room_id = None
                    for r in list(available_labs):
                        if inst.rooms[r].capacity >= size:
                            room_id = r
                            available_labs.remove(r)
                            break
                    if room_id is None:
                        raise ValueError(f"Failed to assign lab room for activity {a_id}")
                    schedule[a_id]["room_id"] = room_id
                    occupied_rooms.add(room_id)

                # big lectures
                available_big = [r for r in big_lecture_rooms if r not in occupied_rooms]
                for a_id in big_lecs:
                    size = total_students[a_id]
                    room_id = None
                    for r in list(available_big):
                        if inst.rooms[r].capacity >= size:
                            room_id = r
                            available_big.remove(r)
                            break
                    if room_id is None:
                        raise ValueError(
                            f"Failed to assign big lecture room for activity {a_id}"
                        )
                    schedule[a_id]["room_id"] = room_id
                    occupied_rooms.add(room_id)

                # remaining small lectures/tutorials
                available_lec = [r for r in lecture_rooms if r not in occupied_rooms]
                for a_id in small_lecs:
                    size = total_students[a_id]
                    room_id = None
                    for r in list(available_lec):
                        if inst.rooms[r].capacity >= size:
                            room_id = r
                            available_lec.remove(r)
                            break
                    if room_id is None:
                        raise ValueError(
                            f"Failed to assign lecture room for activity {a_id}"
                        )
                    schedule[a_id]["room_id"] = room_id
                    occupied_rooms.add(room_id)
