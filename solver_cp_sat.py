from typing import Dict, Tuple, Optional, List, Set
from ortools.sat.python import cp_model
from domain import Instance, WeekIndex, Day, SlotIndex


class TimetableSolver:
    """
    CP-SAT model with:
      - hard constraints: no overlaps, capacity/type, availability, labs/week1 rule, etc.
      - soft constraints: student free days, student gaps, staff free days, active days, early-start penalties
      - pattern_id stability: activities with same pattern_id share time and room (hard stability)

    You can extend this with more soft constraints or tweak weights.
    """

    def __init__(self, inst: Instance):
        self.inst = inst
        self.model = cp_model.CpModel()
        self._build_indexing()
        self._build_variables()
        self._add_hard_constraints()
        self._add_soft_constraints_and_objective()

    # ---------- indexing ----------

    def _build_indexing(self):
        inst = self.inst
        self.room_ids = list(inst.rooms.keys())
        self.staff_ids = list(inst.staff.keys())
        self.activity_ids = list(inst.activities.keys())
        self.weeks = inst.weeks
        self.days = inst.days
        self.num_slots = inst.slots_per_day

        # Flatten (week, day, slot) into a time index
        self.time_triples: List[Tuple[WeekIndex, Day, SlotIndex]] = []
        self.time_index: Dict[Tuple[WeekIndex, Day, SlotIndex], int] = {}

        t = 0
        for w in self.weeks:
            for d in self.days:
                for s in range(self.num_slots):
                    self.time_triples.append((w, d, s))
                    self.time_index[(w, d, s)] = t
                    t += 1
        self.num_times = t

    # ---------- variables ----------

    def _build_variables(self):
        m = self.model
        A = self.activity_ids
        T = range(self.num_times)
        R = self.room_ids
        S = self.staff_ids

        # Activity start time
        self.x_time = {}
        for a in A:
            for t in T:
                self.x_time[a, t] = m.NewBoolVar(f"x_time_a{a}_t{t}")

        # Activity room
        self.x_room = {}
        for a in A:
            for r in R:
                self.x_room[a, r] = m.NewBoolVar(f"x_room_a{a}_r{r}")

        # Activity staff
        self.x_staff = {}
        for a in A:
            for s in S:
                self.x_staff[a, s] = m.NewBoolVar(f"x_staff_a{a}_s{s}")

        # Activity coverage: which time indices it actually occupies
        self.covers = {}
        for a in A:
            for t in T:
                self.covers[a, t] = m.NewBoolVar(f"covers_a{a}_t{t}")

        # Staff-time occupancy: y[a,s,t] = 1 if staff s teaches a at time t
        self.y_staff_time = {}
        for a in A:
            for s in S:
                for t in T:
                    self.y_staff_time[a, s, t] = m.NewBoolVar(f"y_a{a}_s{s}_t{t}")

        # Room-time occupancy: z[a,r,t] = 1 if room r is used by a at time t
        self.z_room_time = {}
        for a in A:
            for r in R:
                for t in T:
                    self.z_room_time[a, r, t] = m.NewBoolVar(f"z_a{a}_r{r}_t{t}")

        # group_occ[g,w,d,s] = 1 if group g has something at (w,d,s)
        self.group_occ = {}
        for g_id in self.inst.groups.keys():
            for t_idx, (w, d, s) in enumerate(self.time_triples):
                self.group_occ[g_id, w, d, s] = m.NewBoolVar(f"group_occ_g{g_id}_w{w}_{d}_s{s}")

        # staff_day_active[s,w,d] = 1 if staff s teaches anything on that day/week
        self.staff_day_active = {}
        for s in self.staff_ids:
            for w in self.weeks:
                for d in self.days:
                    self.staff_day_active[s, w, d] = m.NewBoolVar(f"staff_active_s{s}_w{w}_{d}")

        # group_day_active[g,w,d] = 1 if group g has anything on that day/week
        self.group_day_active = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    self.group_day_active[g_id, w, d] = m.NewBoolVar(f"group_active_g{g_id}_w{w}_{d}")

        # group_day_blocks[g,w,d] = number of contiguous occupied blocks in that day
        self.group_day_blocks = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    # upper bound: number of slots
                    self.group_day_blocks[g_id, w, d] = m.NewIntVar(0, self.num_slots, f"blocks_g{g_id}_w{w}_{d}")

        # helper: start-of-block flags
        self.group_start_block = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    for s in range(self.num_slots):
                        self.group_start_block[g_id, w, d, s] = m.NewBoolVar(f"start_block_g{g_id}_w{w}_{d}_s{s}")

    # ---------- hard constraints ----------

    def _add_hard_constraints(self):
        m = self.model
        inst = self.inst
        A = self.activity_ids
        T = range(self.num_times)
        R = self.room_ids
        S = self.staff_ids

        # Each activity: exactly one start time, one room, one staff
        for a in A:
            m.Add(sum(self.x_time[a, t] for t in T) == 1)
            m.Add(sum(self.x_room[a, r] for r in R) == 1)
            m.Add(sum(self.x_staff[a, s] for s in S) == 1)

        # Staff eligibility per activity
        for a in A:
            act = inst.activities[a]
            allowed_staff = set(act.staff_candidates)
            for s in S:
                if s not in allowed_staff:
                    m.Add(self.x_staff[a, s] == 0)

        # Room capacity / type / specialization per activity
        for a in A:
            act = inst.activities[a]
            groups = [inst.groups[g_id] for g_id in act.group_ids]
            total_students = sum(g.size for g in groups)

            for r_id in R:
                room = inst.rooms[r_id]
                # capacity
                if room.capacity < total_students:
                    m.Add(self.x_room[a, r_id] == 0)

                if act.kind == "LAB":
                    # labs must be in lab-type rooms
                    if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                        m.Add(self.x_room[a, r_id] == 0)
                    if act.requires_specialization:
                        if act.requires_specialization not in room.specialization_tags:
                            m.Add(self.x_room[a, r_id] == 0)
                else:
                    # lectures/tutorials in generic classroom types
                    if room.room_type not in ("LECTURE", "TUTORIAL"):
                        m.Add(self.x_room[a, r_id] == 0)

        # Week 1: only lectures
        for a in A:
            act = inst.activities[a]
            if act.kind in ("TUT", "LAB"):
                for t_idx, (w, d, s) in enumerate(self.time_triples):
                    if w == 1:
                        m.Add(self.x_time[a, t_idx] == 0)

        # Duration: multi-slot activities cannot start so they overflow beyond end-of-day
        for a in A:
            act = inst.activities[a]
            if act.duration_slots > 1:
                for t_idx, (w, d, s) in enumerate(self.time_triples):
                    if s > self.num_slots - act.duration_slots:
                        m.Add(self.x_time[a, t_idx] == 0)

        # Coverage linking: covers[a,t] is implied by x_time and duration_slots
        for a in A:
            act = inst.activities[a]
            duration = act.duration_slots
            # total number of covered times is duration
            m.Add(sum(self.covers[a, t] for t in T) == duration)

            for t_idx, (w, d, s) in enumerate(self.time_triples):
                # compute which start indices can cover this (w,d,s)
                possible_starts = []
                for s_idx, (ww2, d2, s2) in enumerate(self.time_triples):
                    if ww2 != w or d2 != d:
                        continue
                    # if activity starts at s2, it covers slots [s2, s2+duration-1]
                    if s2 <= s < s2 + duration:
                        possible_starts.append(s_idx)
                if possible_starts:
                    m.Add(self.covers[a, t_idx] <= sum(self.x_time[a, s_idx] for s_idx in possible_starts))
                else:
                    m.Add(self.covers[a, t_idx] == 0)

        # Staff-time occupancy linkage and availability, no overlap
        for a in A:
            for s in S:
                for t_idx in T:
                    y = self.y_staff_time[a, s, t_idx]
                    m.Add(y <= self.covers[a, t_idx])
                    m.Add(y <= self.x_staff[a, s])

        for s in S:
            staff = inst.staff[s]
            for t_idx, (w, day, slot) in enumerate(self.time_triples):
                if day not in staff.available_days:
                    for a in A:
                        m.Add(self.y_staff_time[a, s, t_idx] == 0)
                # at most one activity per staff/slot
                m.Add(sum(self.y_staff_time[a, s, t_idx] for a in A) <= 1)

            # daily and weekly load
            if staff.max_slots_per_day is not None:
                for day in inst.days:
                    time_indices = [idx for idx, (w, d, sl) in enumerate(self.time_triples) if d == day]
                    m.Add(
                        sum(self.y_staff_time[a, s, t] for a in A for t in time_indices)
                        <= staff.max_slots_per_day
                    )
            if staff.max_slots_per_week is not None:
                for w in inst.weeks:
                    time_indices = [idx for idx, (ww, d, sl) in enumerate(self.time_triples) if ww == w]
                    m.Add(
                        sum(self.y_staff_time[a, s, t] for a in A for t in time_indices)
                        <= staff.max_slots_per_week
                    )

        # Room-time occupancy linkage and no overlap
        for a in A:
            for r in R:
                for t_idx in T:
                    z = self.z_room_time[a, r, t_idx]
                    m.Add(z <= self.covers[a, t_idx])
                    m.Add(z <= self.x_room[a, r])

        for r in R:
            room = inst.rooms[r]
            for t_idx, (w, day, slot) in enumerate(self.time_triples):
                # room availability
                if room.available_day_slots and (day, slot) not in room.available_day_slots:
                    for a in A:
                        m.Add(self.z_room_time[a, r, t_idx] == 0)
                # at most one activity per room/time
                m.Add(sum(self.z_room_time[a, r, t_idx] for a in A) <= 1)

        # No group overlap: each group may attend at most one activity per time index
        for g_id in inst.groups.keys():
            for t_idx in T:
                m.Add(
                    sum(
                        self.covers[a, t_idx]
                        for a in A
                        if g_id in inst.activities[a].group_ids
                    )
                    <= 1
                )

        # Stability across weeks: activities sharing a pattern_id must use same start time and room
        pattern_to_activities: Dict[int, List[int]] = {}
        for a in A:
            pid = inst.activities[a].pattern_id
            if pid is not None:
                pattern_to_activities.setdefault(pid, []).append(a)

        for pid, acts in pattern_to_activities.items():
            if len(acts) <= 1:
                continue
            ref = acts[0]
            for other in acts[1:]:
                for t_idx in T:
                    m.Add(self.x_time[other, t_idx] == self.x_time[ref, t_idx])
                for r in R:
                    m.Add(self.x_room[other, r] == self.x_room[ref, r])

        # Group-occ variables for soft constraints
        for g_id in inst.groups.keys():
            for t_idx, (w, d, s) in enumerate(self.time_triples):
                occ = self.group_occ[g_id, w, d, s]
                # occ = OR of covers[a, t_idx] over all activities involving g
                related_acts = [a for a in A if g_id in inst.activities[a].group_ids]
                if not related_acts:
                    m.Add(occ == 0)
                else:
                    for a in related_acts:
                        m.Add(occ >= self.covers[a, t_idx])
                    m.Add(occ <= sum(self.covers[a, t_idx] for a in related_acts))

    # ---------- soft constraints and objective ----------

    def _add_soft_constraints_and_objective(self):
        m = self.model
        inst = self.inst

        # weights (you can tune these)
        W_STUD_FREE_DAYS = 10
        W_STUD_GAPS = 5
        W_STAFF_FREE_DAYS = 6
        W_ACTIVE_DAYS = 2
        W_EARLY_START = 2

        penalties = []

        # group_day_active from group_occ
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    day_active = self.group_day_active[g_id, w, d]
                    # day_active >= any occ in that week/day
                    time_indices = [idx for idx, (ww, dd, s) in enumerate(self.time_triples) if ww == w and dd == d]
                    for t_idx in time_indices:
                        occ = self.group_occ[g_id, w, d, self.time_triples[t_idx][2]]
                        m.Add(day_active >= occ)
                    # day_active <= sum occ
                    if time_indices:
                        m.Add(day_active <= sum(self.group_occ[g_id, w, d, self.time_triples[t_idx][2]] for t_idx in time_indices))

        # staff_day_active from y_staff_time
        for s_id in inst.staff.keys():
            for w in inst.weeks:
                for d in inst.days:
                    var = self.staff_day_active[s_id, w, d]
                    time_indices = [idx for idx, (ww, dd, s) in enumerate(self.time_triples) if ww == w and dd == d]
                    if not time_indices:
                        m.Add(var == 0)
                        continue
                    # var = OR over all y_staff_time[a,s,t]
                    m.Add(var <= sum(self.y_staff_time[a, s_id, t_idx] for a in self.activity_ids for t_idx in time_indices))
                    for t_idx in time_indices:
                        m.Add(var >= sum(self.y_staff_time[a, s_id, t_idx] for a in self.activity_ids))

        # group_day_blocks and gaps
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    # start-of-block per slot
                    for s in range(self.num_slots):
                        start_flag = self.group_start_block[g_id, w, d, s]
                        occ_cur = self.group_occ[g_id, w, d, s]
                        if s == 0:
                            # block start if occupied at s and no earlier slot
                            m.Add(start_flag <= occ_cur)
                        else:
                            occ_prev = self.group_occ[g_id, w, d, s - 1]
                            # start_flag <= occ_cur
                            m.Add(start_flag <= occ_cur)
                            # start_flag <= 1 - occ_prev
                            m.Add(start_flag <= 1 - occ_prev)
                            # start_flag >= occ_cur - occ_prev
                            m.Add(start_flag >= occ_cur - occ_prev)

                    # number of blocks is sum of start flags
                    blocks_var = self.group_day_blocks[g_id, w, d]
                    m.Add(blocks_var == sum(self.group_start_block[g_id, w, d, s] for s in range(self.num_slots)))

        # 1) student free days: target at least 2 free days per week, prefer Mon–Fri
        for g_id, g in inst.groups.items():
            for w in inst.weeks:
                free_days = m.NewIntVar(0, len(inst.days), f"free_days_g{g_id}_w{w}")
                # free day = 1 - day_active
                m.Add(
                    free_days
                    == sum(1 - self.group_day_active[g_id, w, d] for d in inst.days)
                )
                shortfall = m.NewIntVar(0, len(inst.days), f"free_shortfall_g{g_id}_w{w}")
                m.Add(shortfall >= g.preferred_free_days - free_days)
                m.Add(shortfall >= 0)
                penalties.append(W_STUD_FREE_DAYS * shortfall)

        # 2) student gaps: penalize number of blocks - 1 per day
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    blocks = self.group_day_blocks[g_id, w, d]
                    gap_penalty = m.NewIntVar(0, self.num_slots, f"gap_pen_g{g_id}_w{w}_{d}")
                    m.Add(gap_penalty >= blocks - 1)
                    m.Add(gap_penalty >= 0)
                    penalties.append(W_STUD_GAPS * gap_penalty)

        # 3) staff free days: at least 1 free day per week
        for s_id in inst.staff.keys():
            for w in inst.weeks:
                free_days = m.NewIntVar(0, len(inst.days), f"staff_free_days_s{s_id}_w{w}")
                m.Add(
                    free_days
                    == sum(1 - self.staff_day_active[s_id, w, d] for d in inst.days)
                )
                shortfall = m.NewIntVar(0, len(inst.days), f"staff_free_shortfall_s{s_id}_w{w}")
                m.Add(shortfall >= 1 - free_days)
                m.Add(shortfall >= 0)
                penalties.append(W_STAFF_FREE_DAYS * shortfall)

        # 4) minimize active days per group (weakly, separate from free-day shortfall)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                active_days = m.NewIntVar(0, len(inst.days), f"active_days_g{g_id}_w{w}")
                m.Add(
                    active_days
                    == sum(self.group_day_active[g_id, w, d] for d in inst.days)
                )
                # penalize every active day beyond 3
                excess = m.NewIntVar(0, len(inst.days), f"active_excess_g{g_id}_w{w}")
                m.Add(excess >= active_days - 3)
                m.Add(excess >= 0)
                penalties.append(W_ACTIVE_DAYS * excess)

        # 5) early start penalties: if a group has first occupied slot at index 0
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    # first slot occupied?
                    occ0 = self.group_occ[g_id, w, d, 0]
                    # any later slot occupied?
                    later_occ = m.NewBoolVar(f"later_occ_g{g_id}_w{w}_{d}")
                    m.Add(
                        later_occ
                        <= sum(self.group_occ[g_id, w, d, s] for s in range(1, self.num_slots))
                    )
                    for s in range(1, self.num_slots):
                        m.Add(later_occ >= self.group_occ[g_id, w, d, s])

                    early_pen = m.NewIntVar(0, 1, f"early_pen_g{g_id}_w{w}_{d}")
                    # early_pen = 1 if occ0 == 1 and some later slot also used
                    m.Add(early_pen >= occ0 + later_occ - 1)
                    m.Add(early_pen <= occ0)
                    m.Add(early_pen <= later_occ)
                    penalties.append(W_EARLY_START * early_pen)

        # Minimize sum of penalties
        m.Minimize(sum(penalties))

    # ---------- solving ----------

    def solve(self, time_limit_seconds: Optional[float] = None):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        # Reasonable defaults
        solver.parameters.num_search_workers = 8

        status = solver.Solve(self.model)
        return solver, status

    # ---------- extraction ----------

    def extract_solution(self, solver: cp_model.CpSolver):
        """
        Returns a dict:
          schedule[a_id] = {
            "room_id": int,
            "staff_id": int,
            "week": int,
            "day": str,
            "slot": int,
            "duration": int,
          }
        """
        inst = self.inst
        schedule = {}
        for a_id, act in inst.activities.items():
            # find chosen time
            time_idx = None
            for t_idx in range(self.num_times):
                if solver.BooleanValue(self.x_time[a_id, t_idx]):
                    time_idx = t_idx
                    break
            if time_idx is None:
                continue
            w, d, s = self.time_triples[time_idx]

            # chosen room
            room_id = None
            for r_id in self.room_ids:
                if solver.BooleanValue(self.x_room[a_id, r_id]):
                    room_id = r_id
                    break

            # chosen staff
            staff_id = None
            for s_id in self.staff_ids:
                if solver.BooleanValue(self.x_staff[a_id, s_id]):
                    staff_id = s_id
                    break

            schedule[a_id] = {
                "room_id": room_id,
                "staff_id": staff_id,
                "week": w,
                "day": d,
                "slot": s,
                "duration": act.duration_slots,
                "group_ids": act.group_ids,
                "course_id": act.course_id,
                "kind": act.kind,
            }
        return schedule
