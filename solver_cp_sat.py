from typing import Dict, Tuple, Optional, List
from ortools.sat.python import cp_model
from domain import Instance, WeekIndex, Day, SlotIndex


class TimetableSolver:
    """
    CP-SAT model with:

    Hard:
      - no staff/group/room overlaps
      - room capacity/type/specialization
      - staff availability and load limits
      - week-1 rule (lectures only)
      - correct durations (1/2/3 slots) on a single day
      - labs and tuts only from week 2
      - group cannot be in two places at once

    Soft:
      - student free days (>=2), prefer Mon–Fri free days
      - student gaps (blocks per day)
      - daily load balance (avoid heavy days)
      - staff free days (>=1)
      - minimize active days for students
      - avoid early starts when possible
      - week-to-week stability of active days
      - room consistency across weeks for the same course/group/kind
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

        # flatten (week, day, slot) into a single time index
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

        # one start time per activity
        self.x_time: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for a in A:
            for t in T:
                self.x_time[a, t] = m.NewBoolVar(f"x_time_a{a}_t{t}")

        # one room per activity
        self.x_room: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for a in A:
            for r in R:
                self.x_room[a, r] = m.NewBoolVar(f"x_room_a{a}_r{r}")

        # one staff per activity
        self.x_staff: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for a in A:
            for s in S:
                self.x_staff[a, s] = m.NewBoolVar(f"x_staff_a{a}_s{s}")

        # coverage of activity across time indices
        self.covers: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for a in A:
            for t in T:
                self.covers[a, t] = m.NewBoolVar(f"covers_a{a}_t{t}")

        # staff-time usage: y[a,s,t]
        self.y_staff_time: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
        for a in A:
            for s in S:
                for t in T:
                    self.y_staff_time[a, s, t] = m.NewBoolVar(f"y_a{a}_s{s}_t{t}")

        # room-time usage: z[a,r,t]
        self.z_room_time: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
        for a in A:
            for r in R:
                for t in T:
                    self.z_room_time[a, r, t] = m.NewBoolVar(f"z_a{a}_r{r}_t{t}")

        # group occupancy by week, day, slot
        self.group_occ: Dict[Tuple[int, WeekIndex, Day, SlotIndex], cp_model.IntVar] = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    for s in range(self.num_slots):
                        self.group_occ[g_id, w, d, s] = m.NewBoolVar(f"group_occ_g{g_id}_w{w}_{d}_s{s}")

        # day-active flags
        self.group_day_active: Dict[Tuple[int, WeekIndex, Day], cp_model.IntVar] = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    self.group_day_active[g_id, w, d] = m.NewBoolVar(f"group_active_g{g_id}_w{w}_{d}")

        self.staff_day_active: Dict[Tuple[int, WeekIndex, Day], cp_model.IntVar] = {}
        for s_id in self.staff_ids:
            for w in self.weeks:
                for d in self.days:
                    self.staff_day_active[s_id, w, d] = m.NewBoolVar(f"staff_active_s{s_id}_w{w}_{d}")

        # number of contiguous blocks per group/day/week and block-start flags
        self.group_day_blocks: Dict[Tuple[int, WeekIndex, Day], cp_model.IntVar] = {}
        self.group_start_block: Dict[Tuple[int, WeekIndex, Day, SlotIndex], cp_model.IntVar] = {}
        for g_id in self.inst.groups.keys():
            for w in self.weeks:
                for d in self.days:
                    self.group_day_blocks[g_id, w, d] = m.NewIntVar(0, self.num_slots, f"blocks_g{g_id}_w{w}_{d}")
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

        # exactly one start time, one room, one staff per activity
        for a in A:
            m.Add(sum(self.x_time[a, t] for t in T) == 1)
            m.Add(sum(self.x_room[a, r] for r in R) == 1)
            m.Add(sum(self.x_staff[a, s] for s in S) == 1)

        # staff eligibility per activity
        for a in A:
            act = inst.activities[a]
            allowed = set(act.staff_candidates)
            for s in S:
                if s not in allowed:
                    m.Add(self.x_staff[a, s] == 0)

        # room capacity/type/specialization
        for a in A:
            act = inst.activities[a]
            groups = [inst.groups[g_id] for g_id in act.group_ids]
            total_students = sum(g.size for g in groups)

            for r_id in R:
                room = inst.rooms[r_id]
                if room.capacity < total_students:
                    m.Add(self.x_room[a, r_id] == 0)

                if act.kind == "LAB":
                    if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                        m.Add(self.x_room[a, r_id] == 0)
                    if act.requires_specialization:
                        if act.requires_specialization not in room.specialization_tags:
                            m.Add(self.x_room[a, r_id] == 0)
                else:
                    if room.room_type not in ("LECTURE", "TUTORIAL"):
                        m.Add(self.x_room[a, r_id] == 0)

        # week-1 rule: only lectures
        for a in A:
            act = inst.activities[a]
            if act.kind in ("TUT", "LAB"):
                for t_idx, (w, d, s) in enumerate(self.time_triples):
                    if w == 1:
                        m.Add(self.x_time[a, t_idx] == 0)

        # duration: activity must not overflow the day
        for a in A:
            act = inst.activities[a]
            if act.duration_slots > 1:
                for t_idx, (w, d, s) in enumerate(self.time_triples):
                    if s > self.num_slots - act.duration_slots:
                        m.Add(self.x_time[a, t_idx] == 0)

        # coverage: covers[a,t] based on chosen start time and duration
        for a in A:
            act = inst.activities[a]
            duration = act.duration_slots
            m.Add(sum(self.covers[a, t] for t in T) == duration)

            for t_idx, (w, d, s) in enumerate(self.time_triples):
                possible_starts = []
                for s_idx, (ww2, d2, s2) in enumerate(self.time_triples):
                    if ww2 != w or d2 != d:
                        continue
                    if s2 <= s < s2 + duration:
                        possible_starts.append(s_idx)
                if possible_starts:
                    m.Add(self.covers[a, t_idx] <= sum(self.x_time[a, s_idx] for s_idx in possible_starts))
                else:
                    m.Add(self.covers[a, t_idx] == 0)

        # link staff-time occupancy
        for a in A:
            for s in S:
                for t_idx in T:
                    y = self.y_staff_time[a, s, t_idx]
                    m.Add(y <= self.covers[a, t_idx])
                    m.Add(y <= self.x_staff[a, s])

        # staff availability and no staff overlap
        for s in S:
            staff = inst.staff[s]
            for t_idx, (w, day, slot) in enumerate(self.time_triples):
                if day not in staff.available_days:
                    for a in A:
                        m.Add(self.y_staff_time[a, s, t_idx] == 0)
                m.Add(sum(self.y_staff_time[a, s, t_idx] for a in A) <= 1)

            # daily load
            if staff.max_slots_per_day is not None:
                for day in inst.days:
                    indices = [idx for idx, (w, d, sl) in enumerate(self.time_triples) if d == day]
                    m.Add(
                        sum(self.y_staff_time[a, s, t] for a in A for t in indices)
                        <= staff.max_slots_per_day
                    )
            # weekly load
            if staff.max_slots_per_week is not None:
                for w in inst.weeks:
                    indices = [idx for idx, (ww, d, sl) in enumerate(self.time_triples) if ww == w]
                    m.Add(
                        sum(self.y_staff_time[a, s, t] for a in A for t in indices)
                        <= staff.max_slots_per_week
                    )

        # link room-time occupancy and room overlap
        for a in A:
            for r in R:
                for t_idx in T:
                    z = self.z_room_time[a, r, t_idx]
                    m.Add(z <= self.covers[a, t_idx])
                    m.Add(z <= self.x_room[a, r])

        for r in R:
            room = inst.rooms[r]
            for t_idx, (w, day, slot) in enumerate(self.time_triples):
                if room.available_day_slots and (day, slot) not in room.available_day_slots:
                    for a in A:
                        m.Add(self.z_room_time[a, r, t_idx] == 0)
                m.Add(sum(self.z_room_time[a, r, t_idx] for a in A) <= 1)

        # no group overlap
        for g_id in inst.groups.keys():
            for t_idx in T:
                m.Add(
                    sum(
                        self.covers[a, t_idx]
                        for a in A
                        if g_id in inst.activities[a].group_ids
                    ) <= 1
                )

        # group_occ = OR of covers for that group at (w,d,s)
        for g_id in inst.groups.keys():
            for t_idx, (w, d, s) in enumerate(self.time_triples):
                occ = self.group_occ[g_id, w, d, s]
                related = [a for a in A if g_id in inst.activities[a].group_ids]
                if not related:
                    m.Add(occ == 0)
                else:
                    for a in related:
                        m.Add(occ >= self.covers[a, t_idx])
                    m.Add(occ <= sum(self.covers[a, t_idx] for a in related))

    # ---------- soft constraints and objective ----------

    def _add_soft_constraints_and_objective(self):
        m = self.model
        inst = self.inst

        # weights; tune as needed
        W_STUD_FREE_DAYS = 10
        W_STUD_FREE_MF = 5
        W_STUD_GAPS = 5
        W_STAFF_FREE_DAYS = 6
        W_ACTIVE_DAYS = 3
        W_EARLY_START = 2
        W_BALANCE = 2
        W_STABILITY = 1
        W_ROOM_CONSISTENCY = 1

        penalties = []

        # group_day_active based on group_occ
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    var = self.group_day_active[g_id, w, d]
                    occs = [self.group_occ[g_id, w, d, s] for s in range(self.num_slots)]
                    for occ in occs:
                        m.Add(var >= occ)
                    if occs:
                        m.Add(var <= sum(occs))

        # staff_day_active based on y_staff_time
        for s_id in inst.staff.keys():
            for w in inst.weeks:
                for d in inst.days:
                    var = self.staff_day_active[s_id, w, d]
                    indices = [idx for idx, (ww, dd, sl) in enumerate(self.time_triples) if ww == w and dd == d]
                    if not indices:
                        m.Add(var == 0)
                        continue
                    for t_idx in indices:
                        for a in self.activity_ids:
                            m.Add(var >= self.y_staff_time[a, s_id, t_idx])
                    m.Add(
                        var
                        <= sum(self.y_staff_time[a, s_id, t_idx] for a in self.activity_ids for t_idx in indices)
                    )

        # group_day_blocks and gaps (blocks >1 implies gaps)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    # start-of-block flags
                    for s in range(self.num_slots):
                        start_flag = self.group_start_block[g_id, w, d, s]
                        occ_cur = self.group_occ[g_id, w, d, s]
                        if s == 0:
                            m.Add(start_flag <= occ_cur)
                            m.Add(start_flag >= occ_cur)
                        else:
                            occ_prev = self.group_occ[g_id, w, d, s - 1]
                            m.Add(start_flag <= occ_cur)
                            m.Add(start_flag <= 1 - occ_prev)
                            m.Add(start_flag >= occ_cur - occ_prev)

                    blocks_var = self.group_day_blocks[g_id, w, d]
                    m.Add(blocks_var == sum(self.group_start_block[g_id, w, d, s] for s in range(self.num_slots)))

        # 1) student free days (any days)
        for g_id, g in inst.groups.items():
            for w in inst.weeks:
                free_days = m.NewIntVar(0, len(inst.days), f"free_days_g{g_id}_w{w}")
                m.Add(
                    free_days
                    == sum(1 - self.group_day_active[g_id, w, d] for d in inst.days)
                )
                shortfall = m.NewIntVar(0, len(inst.days), f"free_shortfall_g{g_id}_w{w}")
                m.Add(shortfall >= g.preferred_free_days - free_days)
                m.Add(shortfall >= 0)
                penalties.append(W_STUD_FREE_DAYS * shortfall)

        # 2) student free days on Mon–Fri preferred
        workdays = [d for d in inst.days if d in {"MON", "TUE", "WED", "THU", "FRI"}]
        for g_id, g in inst.groups.items():
            for w in inst.weeks:
                free_mf = m.NewIntVar(0, len(workdays), f"free_mf_g{g_id}_w{w}")
                m.Add(
                    free_mf
                    == sum(1 - self.group_day_active[g_id, w, d] for d in workdays)
                )
                shortfall_mf = m.NewIntVar(0, len(workdays), f"free_mf_shortfall_g{g_id}_w{w}")
                m.Add(shortfall_mf >= g.preferred_free_days - free_mf)
                m.Add(shortfall_mf >= 0)
                penalties.append(W_STUD_FREE_MF * shortfall_mf)

        # 3) student gaps (blocks-1 per day)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    blocks = self.group_day_blocks[g_id, w, d]
                    gap_pen = m.NewIntVar(0, self.num_slots, f"gap_pen_g{g_id}_w{w}_{d}")
                    m.Add(gap_pen >= blocks - 1)
                    m.Add(gap_pen >= 0)
                    penalties.append(W_STUD_GAPS * gap_pen)

        # 4) staff free days (>=1)
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

        # 5) minimize active days per group (compress days)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                active_days = m.NewIntVar(0, len(inst.days), f"active_days_g{g_id}_w{w}")
                m.Add(
                    active_days
                    == sum(self.group_day_active[g_id, w, d] for d in inst.days)
                )
                excess = m.NewIntVar(0, len(inst.days), f"active_excess_g{g_id}_w{w}")
                m.Add(excess >= active_days - 3)
                m.Add(excess >= 0)
                penalties.append(W_ACTIVE_DAYS * excess)

        # 6) early starts (group uses slot 0 when later slots also used)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    occ0 = self.group_occ[g_id, w, d, 0]
                    later = m.NewBoolVar(f"later_occ_g{g_id}_w{w}_{d}")
                    m.Add(
                        later
                        <= sum(self.group_occ[g_id, w, d, s] for s in range(1, self.num_slots))
                    )
                    for s in range(1, self.num_slots):
                        m.Add(later >= self.group_occ[g_id, w, d, s])

                    early_pen = m.NewIntVar(0, 1, f"early_pen_g{g_id}_w{w}_{d}")
                    m.Add(early_pen >= occ0 + later - 1)
                    m.Add(early_pen <= occ0)
                    m.Add(early_pen <= later)
                    penalties.append(W_EARLY_START * early_pen)

        # 7) daily load balance (avoid very heavy days)
        for g_id in inst.groups.keys():
            for w in inst.weeks:
                for d in inst.days:
                    load = m.NewIntVar(0, self.num_slots, f"load_g{g_id}_w{w}_{d}")
                    m.Add(
                        load
                        == sum(self.group_occ[g_id, w, d, s] for s in range(self.num_slots))
                    )
                    overload = m.NewIntVar(0, self.num_slots, f"overload_g{g_id}_w{w}_{d}")
                    m.Add(overload >= load - 3)   # up to 3 slots per day is fine
                    m.Add(overload >= 0)
                    penalties.append(W_BALANCE * overload)

        # 8) week-to-week stability of active days
        for g_id in inst.groups.keys():
            for w_index in range(1, len(self.weeks)):
                w_prev = self.weeks[w_index - 1]
                w_curr = self.weeks[w_index]
                for d in inst.days:
                    a = self.group_day_active[g_id, w_curr, d]
                    b = self.group_day_active[g_id, w_prev, d]
                    delta = m.NewIntVar(0, 1, f"stability_delta_g{g_id}_w{w_prev}_{w_curr}_{d}")
                    m.Add(delta >= a - b)
                    m.Add(delta >= b - a)
                    penalties.append(W_STABILITY * delta)

        # 9) room consistency: same course/group/kind should use few rooms
        key_to_acts: Dict[Tuple[int, int, str], List[int]] = {}
        for a_id in self.activity_ids:
            act = inst.activities[a_id]
            for g_id in act.group_ids:
                key = (act.course_id, g_id, act.kind)
                key_to_acts.setdefault(key, []).append(a_id)

        for key, acts in key_to_acts.items():
            if len(acts) <= 1:
                continue
            use_room: Dict[int, cp_model.IntVar] = {}
            for r_id in self.room_ids:
                var = m.NewBoolVar(f"use_room_c{key[0]}_g{key[1]}_{key[2]}_r{r_id}")
                use_room[r_id] = var
                for a_id in acts:
                    m.Add(var >= self.x_room[a_id, r_id])
                m.Add(var <= sum(self.x_room[a_id, r_id] for a_id in acts))
            rooms_used = m.NewIntVar(0, len(self.room_ids), f"rooms_used_c{key[0]}_g{key[1]}_{key[2]}")
            m.Add(rooms_used == sum(use_room[r] for r in self.room_ids))
            excess_rooms = m.NewIntVar(0, len(self.room_ids), f"excess_rooms_c{key[0]}_g{key[1]}_{key[2]}")
            m.Add(excess_rooms >= rooms_used - 1)
            m.Add(excess_rooms >= 0)
            penalties.append(W_ROOM_CONSISTENCY * excess_rooms)

        # final objective
        m.Minimize(sum(penalties))

    # ---------- solve and extract ----------

    def solve(self, time_limit_seconds: Optional[float] = None):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = 8
        status = solver.Solve(self.model)
        return solver, status

    def extract_solution(self, solver: cp_model.CpSolver):
        """
        Returns:
          schedule[a_id] = {
            "room_id", "staff_id", "week", "day", "slot", "duration",
            "group_ids", "course_id", "kind"
          }
        """
        inst = self.inst
        schedule = {}
        for a_id, act in inst.activities.items():
            time_idx = None
            for t_idx in range(self.num_times):
                if solver.BooleanValue(self.x_time[a_id, t_idx]):
                    time_idx = t_idx
                    break
            if time_idx is None:
                continue
            w, d, s = self.time_triples[time_idx]

            room_id = None
            for r_id in self.room_ids:
                if solver.BooleanValue(self.x_room[a_id, r_id]):
                    room_id = r_id
                    break

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
