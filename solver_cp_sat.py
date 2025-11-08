from __future__ import annotations
from typing import Dict, List, Tuple, Optional, Set

from ortools.sat.python import cp_model
from domain import Instance


class TimetableSolver:
    """
    Time feasibility + room-count guards:

    Time rules
      - x[a,t] ∈ {0,1} on weekly grid, start[a] = Σ t·x[a,t].
      - Always-present intervals for groups and staff with AddNoOverlap.
      - Sunday off (hard).
      - TAs and normal profs: exactly one extra free day PER WEEK (chosen per person, per week).
      - Block profs: ≤2 distinct teaching days per week.
      - Optional weekly cap: staff.max_slots_per_week.
      - Shared-lecture clusters: same start time.

    Room rules (no seat capacities)
      - Global per-slot room-count constraints:
          * LEC/TUT concurrent count ≤ #LECTURE rooms.
          * LAB concurrent count ≤ #LAB rooms.
          * Specialized labs per tag ≤ #rooms with that tag.
        For clusters, lecture usage counts as 1 per cluster.
      - Greedy room assignment after CP to pick actual rooms and co-locate clusters.

    Set room_mode to "cp_rooms" if you want CP to assign rooms; default keeps greedy.
    """

    def __init__(self, inst: Instance, room_mode: str = "greedy"):
        assert room_mode in ("greedy", "cp_rooms")
        self.inst = inst
        self.room_mode = room_mode

        self.m = cp_model.CpModel()

        # calendar geometry
        self.days: List[str] = inst.days
        self.weeks: List[int] = inst.weeks
        self.S: int = inst.slots_per_day
        self.D: int = len(self.days)
        self.T_week: int = self.D * self.S

        # per-activity
        self.activity_staff: Dict[int, int] = {}
        self.allowed_starts: Dict[int, List[int]] = {}
        self.start: Dict[int, cp_model.IntVar] = {}
        self.x: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.interval: Dict[int, cp_model.IntervalVar] = {}

        # rooms (for cp_rooms)
        self.allowed_rooms: Dict[int, List[int]] = {}
        self.room_sel: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.room_iv: Dict[Tuple[int, int], cp_model.IntervalVar] = {}

        # resources
        self.group_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}
        self.staff_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}

        # shared clusters
        self.shared_clusters_by_week: Dict[int, List[List[int]]] = {}

        # staff-day governance
        self.sunday_idx: Optional[int] = self._find_day_index("SUN")
        self.free_day_bool: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}  # (staff, week, d_idx) -> Bool

        # decision strategy buckets
        self._dec_free_bools: List[cp_model.BoolVar] = []
        self._dec_start_ints: List[cp_model.IntVar] = []
        self._dec_room_bools: List[cp_model.BoolVar] = []

        # room pools for capacity guards
        self.lecture_room_ids: List[int] = []
        self.lab_room_ids: List[int] = []
        self.spec_rooms_by_tag: Dict[str, List[int]] = {}

        self._precompute()
        self._build_variables()
        self._add_constraints()
        self._add_decision_strategy()

    # ---------- public API ----------

    def solve(self, time_limit_seconds: Optional[float] = None):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = 8
        solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
        status = solver.Solve(self.m)
        return solver, status

    def extract_solution(self, solver: cp_model.CpSolver):
        inst = self.inst
        out: Dict[int, Dict[str, object]] = {}

        # chosen room only exists for cp_rooms; greedy mode sets later
        chosen_room: Dict[int, Optional[int]] = {}
        if self.room_mode == "cp_rooms":
            for a_id in inst.activities.keys():
                rid = None
                for r in self.allowed_rooms.get(a_id, []):
                    b = self.room_sel.get((a_id, r))
                    if b is not None and solver.BooleanValue(b):
                        rid = r
                        break
                chosen_room[a_id] = rid
        else:
            for a_id in inst.activities.keys():
                chosen_room[a_id] = None

        for a_id, act in inst.activities.items():
            t = solver.Value(self.start[a_id])
            day_index = t // self.S
            slot = t % self.S
            out[a_id] = {
                "room_id": chosen_room[a_id],
                "staff_id": self.activity_staff[a_id],
                "week": act.week,
                "day": self.days[day_index],
                "slot": slot,
                "duration": act.duration,
                "group_ids": list(act.group_ids),
                "course_id": act.course_id,
                "kind": act.kind,
            }

        if self.room_mode == "greedy":
            assign_rooms_greedily(inst, out)

        return out

    # ---------- internals ----------

    def _find_day_index(self, prefix: str) -> Optional[int]:
        p = prefix.upper()
        for i, d in enumerate(self.inst.days):
            if d.upper().startswith(p):
                return i
        return None

    def _is_block_prof(self, staff) -> bool:
        return bool(getattr(staff, "blocks_only", False) or getattr(staff, "is_block_prof", False))

    def _precompute(self) -> None:
        inst = self.inst

        # staff per activity
        for a_id, act in inst.activities.items():
            if act.kind == "LEC":
                self.activity_staff[a_id] = act.prof_id
            else:
                self.activity_staff[a_id] = act.ta_id

        # room pools for capacity guards and greedy
        for r_id, r in inst.rooms.items():
            if r.room_type == "LECTURE":
                self.lecture_room_ids.append(r_id)
            elif r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                self.lab_room_ids.append(r_id)
                if r.room_type == "SPECIALIZED_LAB":
                    for tag in getattr(r, "specialization_tags", []):
                        self.spec_rooms_by_tag.setdefault(tag, []).append(r_id)

        # allowed starts; prune Sunday immediately
        sunday_lo = sunday_hi = None
        if self.sunday_idx is not None:
            sunday_lo = self.sunday_idx * self.S
            sunday_hi = sunday_lo + self.S - 1

        for a_id, act in inst.activities.items():
            sid = self.activity_staff[a_id]
            staff = inst.staff[sid]
            available_days = list(getattr(staff, "available_days", self.days))
            allowed_day_idx: Set[int] = {i for i, d in enumerate(self.days) if d in available_days}

            max_start_slot = self.S - act.duration
            if max_start_slot < 0:
                raise ValueError(f"Activity {a_id} duration {act.duration} exceeds day slots {self.S}")

            times: List[int] = []
            for d_idx in range(self.D):
                if d_idx not in allowed_day_idx:
                    continue
                for s in range(max_start_slot + 1):
                    t = d_idx * self.S + s
                    if self.sunday_idx is not None and sunday_lo <= t <= sunday_hi:
                        continue
                    times.append(t)

            if not times:
                raise ValueError(f"No allowed starts for activity {a_id}")
            self.allowed_starts[a_id] = times

        # shared lecture clusters per week
        self.shared_clusters_by_week = self._compute_shared_lecture_clusters()

        # allowed rooms for cp_rooms mode
        if self.room_mode == "cp_rooms":
            self._compute_allowed_rooms()

    def _compute_shared_lecture_clusters(self) -> Dict[int, List[List[int]]]:
        clusters_by_week: Dict[int, List[List[int]]] = {w: [] for w in self.weeks}
        for c_id, course in self.inst.courses.items():
            shared = getattr(course, "share_lecture_group_ids", None)
            if not shared:
                continue
            shared_set: Set[int] = set(shared)
            acts_by_week: Dict[int, List[int]] = {w: [] for w in self.weeks}
            for a_id, act in self.inst.activities.items():
                if act.course_id != c_id or act.kind != "LEC":
                    continue
                if len(act.group_ids) == 1 and act.group_ids[0] in shared_set:
                    acts_by_week[act.week].append(a_id)
            for w, bucket in acts_by_week.items():
                if len(bucket) >= 2:
                    clusters_by_week[w].append(bucket)
        return clusters_by_week

    def _compute_allowed_rooms(self) -> None:
        inst = self.inst
        for a_id, act in inst.activities.items():
            rooms: List[int] = []
            if act.kind == "LAB":
                req = getattr(act, "requires_specialization", None)
                if req:
                    for r_id, r in inst.rooms.items():
                        if r.room_type == "SPECIALIZED_LAB" and req in getattr(r, "specialization_tags", []):
                            rooms.append(r_id)
                else:
                    for r_id, r in inst.rooms.items():
                        if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                            rooms.append(r_id)
            else:
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]

            if not rooms:
                rooms = list(inst.rooms.keys())
            self.allowed_rooms[a_id] = rooms

    def _build_variables(self) -> None:
        m = self.m
        inst = self.inst

        # activity selection + main interval
        for a_id, act in inst.activities.items():
            allowed = self.allowed_starts[a_id]

            s_var = m.NewIntVar(0, self.T_week - 1, f"start[{a_id}]")
            self.start[a_id] = s_var
            self._dec_start_ints.append(s_var)

            pick: List[cp_model.BoolVar] = []
            for t in allowed:
                b = m.NewBoolVar(f"x[{a_id},{t}]")
                self.x[(a_id, t)] = b
                pick.append(b)
            m.Add(sum(pick) == 1)
            m.Add(s_var == sum(t * self.x[(a_id, t)] for t in allowed))

            e_var = m.NewIntVar(0, self.T_week, f"end[{a_id}]")
            m.Add(e_var == s_var + act.duration)
            iv = m.NewIntervalVar(s_var, act.duration, e_var, f"iv[{a_id}]")
            self.interval[a_id] = iv

            for g_id in act.group_ids:
                self.group_intervals_by_week.setdefault((g_id, act.week), []).append(iv)
            sid = self.activity_staff[a_id]
            self.staff_intervals_by_week.setdefault((sid, act.week), []).append(iv)

        if self.room_mode == "cp_rooms":
            for a_id in inst.activities.keys():
                for r in self.allowed_rooms[a_id]:
                    b = m.NewBoolVar(f"room[{a_id}]={r}")
                    self.room_sel[(a_id, r)] = b
                    self._dec_room_bools.append(b)

    def _add_constraints(self) -> None:
        m = self.m
        inst = self.inst

        # resource NoOverlap
        for (g_id, w), ivs in self.group_intervals_by_week.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)
        for (s_id, w), ivs in self.staff_intervals_by_week.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)

        # TA/normal prof: exactly one extra free day per week
        for s_id, staff in inst.staff.items():
            if self._is_block_prof(staff):
                continue
            avail_days = list(getattr(staff, "available_days", self.days))
            cand_idx = [i for i, d in enumerate(self.days) if d in avail_days and i != self.sunday_idx]
            if not cand_idx:
                continue
            for w in self.weeks:
                free_bools = []
                for d_idx in cand_idx:
                    b = m.NewBoolVar(f"F[{s_id},{w},{d_idx}]")
                    self.free_day_bool[(s_id, w, d_idx)] = b
                    free_bools.append(b)
                    self._dec_free_bools.append(b)
                m.Add(sum(free_bools) == 1)
                # forbid starts on chosen free day
                for a_id, act in inst.activities.items():
                    if act.week != w or self.activity_staff[a_id] != s_id:
                        continue
                    for t in self.allowed_starts[a_id]:
                        d_idx = t // self.S
                        if d_idx in cand_idx:
                            m.Add(self.x[(a_id, t)] <= 1 - self.free_day_bool[(s_id, w, d_idx)])

        # Block profs: ≤2 distinct days per week
        for s_id, staff in inst.staff.items():
            if not self._is_block_prof(staff):
                continue
            for w in self.weeks:
                y_day: Dict[int, cp_model.BoolVar] = {d: m.NewBoolVar(f"workday[{s_id},{w},{d}]")
                                                      for d in range(self.D)}
                for a_id, act in inst.activities.items():
                    if act.week != w or self.activity_staff[a_id] != s_id:
                        continue
                    for t in self.allowed_starts[a_id]:
                        d_idx = t // self.S
                        m.Add(y_day[d_idx] >= self.x[(a_id, t)])
                m.Add(sum(y_day.values()) <= 2)

        # Optional weekly cap
        for s_id, staff in inst.staff.items():
            cap = getattr(staff, "max_slots_per_week", None)
            if cap is None:
                continue
            for w in self.weeks:
                terms: List[cp_model.LinearExpr] = []
                for a_id, act in inst.activities.items():
                    if act.week != w or self.activity_staff[a_id] != s_id:
                        continue
                    for t in self.allowed_starts[a_id]:
                        terms.append(act.duration * self.x[(a_id, t)])
                if terms:
                    m.Add(sum(terms) <= int(cap))

        # Shared lectures: tie starts
        for w, clusters in self.shared_clusters_by_week.items():
            for bucket in clusters:
                base = bucket[0]
                for a in bucket[1:]:
                    m.Add(self.start[a] == self.start[base])

        # ---- Room-count capacity guards per slot (works for both greedy and cp_rooms) ----
        num_lec_rooms = len(self.lecture_room_ids)
        num_lab_rooms = len(self.lab_room_ids)

        for w in self.weeks:
            # precompute cluster leaders in this week
            cluster_leaders: Set[int] = set(b[0] for b in self.shared_clusters_by_week.get(w, []))
            cluster_members: Set[int] = set(a for b in self.shared_clusters_by_week.get(w, []) for a in b[1:])

            for tau in range(self.T_week):
                lec_terms: List[cp_model.BoolVar] = []
                lab_terms: List[cp_model.BoolVar] = []
                tag_terms: Dict[str, List[cp_model.BoolVar]] = {}

                for a_id, act in inst.activities.items():
                    if act.week != w:
                        continue
                    dur = act.duration
                    allowed = self.allowed_starts[a_id]
                    if act.kind in ("LEC", "TUT"):
                        # count cluster as 1 using leader only
                        if a_id in cluster_members:
                            continue
                        # leader or non-cluster LEC/TUT
                        for t in allowed:
                            if t <= tau < t + dur:
                                lec_terms.append(self.x[(a_id, t)])
                    elif act.kind == "LAB":
                        for t in allowed:
                            if t <= tau < t + dur:
                                lab_terms.append(self.x[(a_id, t)])
                                req = getattr(act, "requires_specialization", None)
                                if req:
                                    tag_terms.setdefault(req, []).append(self.x[(a_id, t)])

                if num_lec_rooms > 0 and lec_terms:
                    m.Add(sum(lec_terms) <= num_lec_rooms)
                if num_lab_rooms > 0 and lab_terms:
                    m.Add(sum(lab_terms) <= num_lab_rooms)
                for tag, terms in tag_terms.items():
                    cap = len(self.spec_rooms_by_tag.get(tag, []))
                    if cap > 0:
                        m.Add(sum(terms) <= cap)

        # Optional: CP-based room assignment with NoOverlap
        if self.room_mode == "cp_rooms":
            room_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}

            for w in self.weeks:
                clusters = self.shared_clusters_by_week.get(w, [])
                leader_members: Set[int] = set()

                for bucket in clusters:
                    leader = bucket[0]
                    # common allowed rooms
                    common = set(self.allowed_rooms[leader])
                    for a in bucket[1:]:
                        common &= set(self.allowed_rooms[a])
                    if not common:
                        common = set(self.allowed_rooms[leader])

                    self.m.Add(sum(self.room_sel[(leader, r)] for r in self.allowed_rooms[leader]) == 1)
                    for r in self.allowed_rooms[leader]:
                        if r in common:
                            iv = self.m.NewOptionalIntervalVar(
                                self.start[leader],
                                self.inst.activities[leader].duration,
                                self.start[leader] + self.inst.activities[leader].duration,
                                self.room_sel[(leader, r)],
                                f"Riv[{leader},{r}]"
                            )
                            room_intervals_by_week.setdefault((r, w), []).append(iv)
                            self.room_iv[(leader, r)] = iv
                        else:
                            self.m.Add(self.room_sel[(leader, r)] == 0)

                    for a in bucket[1:]:
                        self.m.Add(sum(self.room_sel[(a, r)] for r in self.allowed_rooms[a]) == 1)
                        for r in self.allowed_rooms[a]:
                            if r in common:
                                self.m.Add(self.room_sel[(a, r)] == self.room_sel[(leader, r)])
                            else:
                                self.m.Add(self.room_sel[(a, r)] == 0)
                    leader_members.update(bucket)

                for a_id, act in self.inst.activities.items():
                    if act.week != w or a_id in leader_members:
                        continue
                    self.m.Add(sum(self.room_sel[(a_id, r)] for r in self.allowed_rooms[a_id]) == 1)
                    for r in self.allowed_rooms[a_id]:
                        iv = self.m.NewOptionalIntervalVar(
                            self.start[a_id], act.duration, self.start[a_id] + act.duration,
                            self.room_sel[(a_id, r)], f"Riv[{a_id},{r}]"
                        )
                        room_intervals_by_week.setdefault((r, w), []).append(iv)
                        self.room_iv[(a_id, r)] = iv

            for (r, w), ivs in room_intervals_by_week.items():
                if len(ivs) > 1:
                    self.m.AddNoOverlap(ivs)

    def _add_decision_strategy(self) -> None:
        # Solve free days → starts → rooms
        if self._dec_free_bools:
            self.m.AddDecisionStrategy(self._dec_free_bools,
                                       cp_model.CHOOSE_FIRST,
                                       cp_model.SELECT_MAX_VALUE)
        if self._dec_start_ints:
            self.m.AddDecisionStrategy(self._dec_start_ints,
                                       cp_model.CHOOSE_LOWEST_MIN,
                                       cp_model.SELECT_MIN_VALUE)
        if self._dec_room_bools:
            self.m.AddDecisionStrategy(self._dec_room_bools,
                                       cp_model.CHOOSE_FIRST,
                                       cp_model.SELECT_MAX_VALUE)


# ---------- greedy room assignment with cluster co-location ----------

def _find_shared_lecture_clusters_for_assignment(inst: Instance) -> List[List[int]]:
    clusters: List[List[int]] = []
    for c_id, course in inst.courses.items():
        shared = getattr(course, "share_lecture_group_ids", None)
        if not shared:
            continue
        shared_set = set(shared)
        bucket: List[int] = []
        for a_id, act in inst.activities.items():
            if act.course_id != c_id or act.kind != "LEC":
                continue
            if len(act.group_ids) == 1 and act.group_ids[0] in shared_set:
                bucket.append(a_id)
        if len(bucket) >= 2:
            clusters.append(bucket)
    return clusters


def assign_rooms_greedily(inst: Instance, schedule: Dict[int, Dict[str, object]]) -> None:
    """
    Assign rooms per slot:

      - Specialised labs → tag-matched lab rooms, else any lab room.
      - Generic labs → any lab room.
      - LEC/TUT → any lecture room.
      - Shared-lecture clusters co-located in one lecture room.
      - No seat capacities modeled.
    """
    days = inst.days
    weeks = inst.weeks
    slots_per_day = inst.slots_per_day

    lecture_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]
    lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
    spec_rooms_by_tag: Dict[str, List[int]] = {}
    for r_id, room in inst.rooms.items():
        if room.room_type == "SPECIALIZED_LAB":
            for tag in getattr(room, "specialization_tags", []):
                spec_rooms_by_tag.setdefault(tag, []).append(r_id)

    # build time occupancy map
    slot_acts: Dict[Tuple[int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        week = info["week"]; day = info["day"]
        start_slot = info["slot"]; duration = info["duration"]
        for off in range(duration):
            s = start_slot + off
            slot_acts.setdefault((week, day, s), []).append(a_id)

    clusters = _find_shared_lecture_clusters_for_assignment(inst)
    a_to_cluster: Dict[int, int] = {}
    for cid, bucket in enumerate(clusters):
        for a in bucket:
            a_to_cluster[a] = cid

    for w in weeks:
        for d in days:
            for s in range(slots_per_day):
                key = (w, d, s)
                acts = slot_acts.get(key)
                if not acts:
                    continue

                occupied: Set[int] = {
                    schedule[a_id]["room_id"]
                    for a_id in acts
                    if schedule[a_id]["room_id"] is not None
                }
                occupied.discard(None)

                unassigned = [a_id for a_id in acts if schedule[a_id]["room_id"] is None]
                if not unassigned:
                    continue

                # co-locate clusters first
                processed: Set[int] = set()
                avail_lec = [r for r in lecture_rooms if r not in occupied]
                for a_id in list(unassigned):
                    if a_id in processed or a_id not in a_to_cluster:
                        continue
                    cluster_id = a_to_cluster[a_id]
                    members = [x for x in unassigned if a_to_cluster.get(x) == cluster_id]
                    if len(members) < 2:
                        continue
                    if not avail_lec:
                        raise ValueError(f"No lecture room left for cluster at {w}-{d}-{s}")
                    room_id = avail_lec.pop(0)
                    for x in members:
                        schedule[x]["room_id"] = room_id
                        processed.add(x)
                    occupied.add(room_id)

                # rebuild lists
                avail_lec = [r for r in lecture_rooms if r not in occupied]
                avail_labs = [r for r in lab_rooms if r not in occupied]

                # assign labs first
                labs_spec_by_tag: Dict[str, List[int]] = {}
                labs_generic: List[int] = []
                lecs_tuts: List[int] = []

                for a_id in unassigned:
                    if schedule[a_id]["room_id"] is not None:
                        continue
                    act = inst.activities[a_id]
                    if act.kind == "LAB":
                        tag = getattr(act, "requires_specialization", None)
                        if tag:
                            labs_spec_by_tag.setdefault(tag, []).append(a_id)
                        else:
                            labs_generic.append(a_id)
                    else:
                        lecs_tuts.append(a_id)

                for tag, acts_tag in labs_spec_by_tag.items():
                    spec_rooms = [r for r in spec_rooms_by_tag.get(tag, []) if r not in occupied]
                    any_labs = [r for r in lab_rooms if r not in occupied]
                    for a_id in acts_tag:
                        room_id = None
                        if spec_rooms:
                            room_id = spec_rooms.pop(0)
                        elif any_labs:
                            room_id = any_labs.pop(0)
                        else:
                            raise ValueError(f"No lab room for specialised lab a{a_id}")
                        schedule[a_id]["room_id"] = room_id
                        occupied.add(room_id)

                avail_labs = [r for r in lab_rooms if r not in occupied]
                for a_id in labs_generic:
                    if not avail_labs:
                        raise ValueError(f"No lab room for lab a{a_id}")
                    schedule[a_id]["room_id"] = avail_labs.pop(0)
                    occupied.add(schedule[a_id]["room_id"])

                # lectures/tutorials
                avail_lec = [r for r in lecture_rooms if r not in occupied]
                for a_id in lecs_tuts:
                    if schedule[a_id]["room_id"] is not None:
                        continue
                    if not avail_lec:
                        raise ValueError(f"No lecture room for a{a_id}")
                    schedule[a_id]["room_id"] = avail_lec.pop(0)
                    occupied.add(schedule[a_id]["room_id"])
