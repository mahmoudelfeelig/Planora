from __future__ import annotations
from typing import Dict, List, Tuple, Optional, Set, DefaultDict
from collections import defaultdict

from ortools.sat.python import cp_model
from domain import Instance


class TimetableSolver:
    """
    CP-SAT feasibility model with generalized co-location clusters and room-count guards.

    Time model
      - Weekly grid of D*S slots. Each activity picks one start in staff-available days.
      - Interval variables for groups and staff with NoOverlap to prevent conflicts.
      - Sunday, if present, is never scheduled.
      - Block staff: at most two distinct teaching days per week.
      - Optional weekly/daily load caps via staff settings.
      - Optional weekly load caps via staff.max_slots_per_week.
      - Clusters: LEC, TUT, LAB can be clustered; members share the same start in that week.

    Room model
      - Count guards only:
          * LEC uses LECTURE rooms.
          * TUT can use TUTORIAL or LECTURE rooms.
          * LAB uses COMPUTER_LAB or SPECIALIZED_LAB; specialization tags further restrict some LABs.
        Followers of a cluster do not count twice.
      - Modes:
          * "greedy" (fast): CP does not choose rooms. A greedy pass assigns rooms and co-locates clusters.
          * "cp_rooms" (slower): CP also chooses rooms with NoOverlap per real room and co-location inside clusters.

    Semester rules
      - First week must contain lectures only.
      - For each course: total LEC count equals total TUT count across the semester.

    Notes
      - Model targets fast feasibility on large instances. Put preferences into metaheuristics.
    """

    def __init__(self, inst: Instance, room_mode: str = "greedy"):
        assert room_mode in ("greedy", "cp_rooms")
        self.inst = inst
        self.room_mode = room_mode

        self.m = cp_model.CpModel()

        # calendar geometry
        self.days: List[str] = inst.days
        self.weeks: List[int] = sorted(inst.weeks)
        self.S: int = inst.slots_per_day
        self.D: int = len(self.days)
        self.T_week: int = self.D * self.S

        # per-activity
        self.activity_staff: Dict[int, int] = {}
        self.allowed_starts: Dict[int, List[int]] = {}
        self.start: Dict[int, cp_model.IntVar] = {}
        self.x: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.interval: Dict[int, cp_model.IntervalVar] = {}

        # resources
        self.group_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}
        self.staff_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}

        # clusters: week -> kind -> list of clusters (each cluster is list[int] of activity ids)
        self.clusters_by_week_kind: Dict[int, Dict[str, List[List[int]]]] = {}

        # free days support
        self.sunday_idx: Optional[int] = self._find_day_index("SUN")
        self.free_day_bool: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}

        # decision var collections for strategy
        self._dec_free_bools: List[cp_model.BoolVar] = []
        self._dec_start_ints: List[cp_model.IntVar] = []
        self._dec_room_bools: List[cp_model.BoolVar] = []

        # room pools and CP-rooming vars
        self.lecture_room_ids: List[int] = []
        self.tutorial_room_ids: List[int] = []
        self.lab_room_ids: List[int] = []
        self.spec_rooms_by_tag: Dict[str, List[int]] = {}
        self.allowed_rooms: Dict[int, List[int]] = {}
        self.room_sel: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.room_iv: Dict[Tuple[int, int], cp_model.IntervalVar] = {}

        # build model
        self._precompute()
        self._build_variables()
        self._add_constraints()
        self._add_decision_strategy()

    # ---------- public API ----------

    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
        workers: Optional[int] = 8,
        random_seed: Optional[int] = None,
    ):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        if workers is not None:
            solver.parameters.num_search_workers = int(workers)
        if random_seed is not None:
            solver.parameters.random_seed = int(random_seed)
        solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
        status = solver.Solve(self.m)
        return solver, status

    def extract_solution(self, solver: cp_model.CpSolver):
        inst = self.inst
        out: Dict[int, Dict[str, object]] = {}

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
        return bool(getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False) or getattr(staff, "is_block_prof", False))

    def _validate_semester_rules(self) -> None:
        """
        Generator/semester invariants used by the solver:
        - For any course that has lectures, the total LEC slot count across the semester
            must equal the total TUT slot count per group for that course.
            (Lectures are shared; tutorials are per group.)
        - Week-1 must be lectures-only; tutorials/labs in the first week are rejected.
        """
        inst = self.inst
        first_week = inst.weeks[0] if inst.weeks else None

        # Pre-index activities per course and per course+group
        lec_slots_by_course: dict[int, int] = {}
        tut_slots_by_course_group: dict[tuple[int, int], int] = {}

        for act in inst.activities.values():
            if act.kind == "LEC":
                lec_slots_by_course[act.course_id] = lec_slots_by_course.get(act.course_id, 0) + act.duration
            elif act.kind == "TUT":
                for g in act.group_ids:
                    key = (act.course_id, g)
                    tut_slots_by_course_group[key] = tut_slots_by_course_group.get(key, 0) + act.duration

        # Work out which groups belong to each course (prefer the explicit share list)
        course_groups: dict[int, list[int]] = {}
        for c_id, c in inst.courses.items():
            gids = list(c.share_lecture_group_ids) if c.share_lecture_group_ids else [
                g_id for g_id, g in inst.groups.items() if c_id in g.course_ids
            ]
            course_groups[c_id] = gids

        courses_with_tutorials = {a.course_id for a in inst.activities.values() if a.kind == "TUT"}

        mismatches: list[str] = []
        for c_id, lec_slots in lec_slots_by_course.items():
            # Skip lab-only courses (no lectures)
            if lec_slots == 0:
                continue
            # Only enforce lecture/tutorial parity when the instance actually contains tutorials
            # for the course (keeps LEC_ONLY test instances valid).
            if c_id not in courses_with_tutorials:
                continue
            for g_id in course_groups.get(c_id, []):
                tut_slots = tut_slots_by_course_group.get((c_id, g_id), 0)
                if tut_slots != lec_slots:
                    mismatches.append(f"course {c_id} (group {g_id}): LEC_slots={lec_slots}, TUT_slots={tut_slots}")

        if mismatches:
            raise ValueError(
                "Per-course per-group lecture/tutorial slot totals must match. "
                "Mismatches: " + ", ".join(mismatches)
            )

        # Enforce: week-1 contains lectures only
        if first_week is not None:
            bad_first = [
                (a.id, a.course_id, a.kind) for a in inst.activities.values()
                if a.week == first_week and a.kind in ("TUT", "LAB")
            ]
            if bad_first:
                kinds = sorted({k for _, _, k in bad_first})
                raise ValueError(
                    f"Week {first_week} must be lectures only; "
                    f"found {len(bad_first)} tutorial/lab activities (kinds={kinds})."
                )


    def _precompute(self) -> None:
        inst = self.inst

        self._validate_semester_rules()

        # staff per activity: professors teach LEC, TAs teach TUT/LAB by convention
        for a_id, act in inst.activities.items():
            self.activity_staff[a_id] = act.prof_id if act.kind == "LEC" else act.ta_id

        # room pools
        for r_id, r in inst.rooms.items():
            if r.room_type == "LECTURE":
                self.lecture_room_ids.append(r_id)
            elif r.room_type == "TUTORIAL":
                self.tutorial_room_ids.append(r_id)
            elif r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                self.lab_room_ids.append(r_id)
                if r.room_type == "SPECIALIZED_LAB":
                    for tag in getattr(r, "specialization_tags", []) or []:
                        self.spec_rooms_by_tag.setdefault(tag, []).append(r_id)

        # allowed starts: respect staff available days and remove Sundays entirely
        sunday_range = None
        if self.sunday_idx is not None:
            lo = self.sunday_idx * self.S
            hi = lo + self.S - 1
            sunday_range = (lo, hi)

        for a_id, act in inst.activities.items():
            sid = self.activity_staff[a_id]
            staff = inst.staff[sid]
            available_days = set(getattr(staff, "available_days", self.days))
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
                    if sunday_range and sunday_range[0] <= t <= sunday_range[1]:
                        continue
                    times.append(t)
            if not times:
                raise ValueError(f"No allowed starts for activity {a_id}")
            self.allowed_starts[a_id] = times

        # clusters for LEC, TUT, LAB
        self.clusters_by_week_kind = self._compute_clusters()

        # optional CP-room list
        if self.room_mode == "cp_rooms":
            self._compute_allowed_rooms()

    def _compute_clusters(self) -> Dict[int, Dict[str, List[List[int]]]]:
        """
        Build clusters by week and kind.

        Sources:
          1) course.share_lecture_group_ids for LEC across single-group activities
          2) activity.cluster_key (optional, attach at generation time) for cross-course, cross-major grouping
             Works for LEC/TUT/LAB. If absent, nothing to cluster from this source.
        """
        inst = self.inst
        out: Dict[int, Dict[str, List[List[int]]]] = {w: {"LEC": [], "TUT": [], "LAB": []} for w in self.weeks}

        # single-group activities bucketed by (course, kind, week, group_id)
        by_ckwg: DefaultDict[Tuple[int, str, int, int], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            if len(a.group_ids) == 1:
                by_ckwg[(a.course_id, a.kind, a.week, a.group_ids[0])].append(a_id)

        # course-level lecture sharing
        for c_id, course in inst.courses.items():
            shared = getattr(course, "share_lecture_group_ids", None)
            if shared:
                shared_set = set(shared)
                by_week: DefaultDict[int, List[int]] = defaultdict(list)
                for (cc, k, w, g), bucket in by_ckwg.items():
                    if cc != c_id or k != "LEC":
                        continue
                    if g in shared_set:
                        by_week[w].extend(bucket)
                for w, members in by_week.items():
                    if len(members) >= 2:
                        out[w]["LEC"].append(sorted(members))

        # activity-level cluster keys for any kind
        by_key_week_kind: DefaultDict[Tuple[str, int, str], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            key = getattr(a, "cluster_key", None)
            if key:
                by_key_week_kind[(str(key), a.week, a.kind)].append(a_id)
        for (key, w, kind), members in by_key_week_kind.items():
            if len(members) >= 2:
                out[w][kind].append(sorted(members))

        # dedup per (w, kind)
        for w in out:
            for kind in ("LEC", "TUT", "LAB"):
                seen: Set[Tuple[int, ...]] = set()
                uniq: List[List[int]] = []
                for cluster in out[w][kind]:
                    t = tuple(cluster)
                    if t not in seen:
                        seen.add(t)
                        uniq.append(cluster)
                out[w][kind] = uniq

        return out

    def _compute_allowed_rooms(self) -> None:
        inst = self.inst
        for a_id, act in inst.activities.items():
            rooms: List[int] = []
            if act.kind == "LAB":
                req = getattr(act, "requires_specialization", None)
                lab_candidates = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
                if req:
                    for r_id in lab_candidates:
                        tags = getattr(inst.rooms[r_id], "specialization_tags", []) or []
                        if req in tags:
                            rooms.append(r_id)
                    if not rooms:
                        raise ValueError(f"Activity {a_id} requires specialized lab '{req}' but no matching room exists")
                else:
                    rooms = lab_candidates
            elif act.kind == "TUT":
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("TUTORIAL", "LECTURE")]
            else:  # LEC
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]

            if not rooms:
                raise ValueError(f"No eligible rooms for activity {a_id} ({act.kind})")
            self.allowed_rooms[a_id] = rooms

    def _build_variables(self) -> None:
        m = self.m
        inst = self.inst

        for a_id, act in inst.activities.items():
            allowed = self.allowed_starts[a_id]

            s_var = m.NewIntVar(0, self.T_week - 1, f"start[{a_id}]")
            self.start[a_id] = s_var
            self._dec_start_ints.append(s_var)

            picks: List[cp_model.BoolVar] = []
            for t in allowed:
                b = m.NewBoolVar(f"x[{a_id},{t}]")
                self.x[(a_id, t)] = b
                picks.append(b)
            m.Add(sum(picks) == 1)
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

        # Block staff: at most two distinct days per week
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

        # Optional weekly load cap
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

        # Optional daily load cap
        for s_id, staff in inst.staff.items():
            cap = getattr(staff, "max_slots_per_day", None)
            if cap is None:
                continue
            for w in self.weeks:
                for d_idx in range(self.D):
                    terms: List[cp_model.LinearExpr] = []
                    for a_id, act in inst.activities.items():
                        if act.week != w or self.activity_staff[a_id] != s_id:
                            continue
                        for t in self.allowed_starts[a_id]:
                            if (t // self.S) == d_idx:
                                terms.append(act.duration * self.x[(a_id, t)])
                    if terms:
                        m.Add(sum(terms) <= int(cap))

        # Cluster equal-start constraints
        for w in self.weeks:
            for kind in ("LEC", "TUT", "LAB"):
                for cluster in self.clusters_by_week_kind[w][kind]:
                    leader = cluster[0]
                    for a in cluster[1:]:
                        m.Add(self.start[a] == self.start[leader])

        # Room-count guards per slot with tutorial support
        num_lec = len(self.lecture_room_ids)
        num_tut = len(self.tutorial_room_ids)
        num_lab = len(self.lab_room_ids)

        # followers of clusters should not count twice
        follower_ids_by_week_kind: Dict[int, Dict[str, Set[int]]] = {w: {"LEC": set(), "TUT": set(), "LAB": set()}
                                                                     for w in self.weeks}
        for w in self.weeks:
            for kind in ("LEC", "TUT", "LAB"):
                for cluster in self.clusters_by_week_kind[w][kind]:
                    follower_ids_by_week_kind[w][kind].update(cluster[1:])

        for w in self.weeks:
            for tau in range(self.T_week):
                lec_terms: List[cp_model.BoolVar] = []
                tut_terms: List[cp_model.BoolVar] = []
                lab_terms: List[cp_model.BoolVar] = []
                tag_terms: Dict[str, List[cp_model.BoolVar]] = {}

                for a_id, act in inst.activities.items():
                    if act.week != w:
                        continue
                    dur = act.duration
                    allowed = self.allowed_starts[a_id]

                    if act.kind == "LEC":
                        if a_id in follower_ids_by_week_kind[w]["LEC"]:
                            continue
                        for t in allowed:
                            if t <= tau < t + dur:
                                lec_terms.append(self.x[(a_id, t)])

                    elif act.kind == "TUT":
                        if a_id in follower_ids_by_week_kind[w]["TUT"]:
                            continue
                        for t in allowed:
                            if t <= tau < t + dur:
                                tut_terms.append(self.x[(a_id, t)])

                    else:  # LAB
                        if a_id in follower_ids_by_week_kind[w]["LAB"]:
                            continue
                        for t in allowed:
                            if t <= tau < t + dur:
                                lab_terms.append(self.x[(a_id, t)])
                                req = getattr(act, "requires_specialization", None)
                                if req:
                                    tag_terms.setdefault(req, []).append(self.x[(a_id, t)])

                if num_lec > 0 and lec_terms:
                    m.Add(sum(lec_terms) <= num_lec)
                if (num_lec + num_tut) > 0 and (lec_terms or tut_terms):
                    m.Add(sum(lec_terms) + sum(tut_terms) <= (num_lec + num_tut))
                if num_lab > 0 and lab_terms:
                    m.Add(sum(lab_terms) <= num_lab)
                for tag, terms in tag_terms.items():
                    cap = len(self.spec_rooms_by_tag.get(tag, []))
                    if cap > 0:
                        m.Add(sum(terms) <= cap)

        # Optional CP rooming with cluster co-location
        if self.room_mode == "cp_rooms":
            room_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}

            for w in self.weeks:
                clustered: Set[int] = set()

                for kind in ("LEC", "TUT", "LAB"):
                    for cluster in self.clusters_by_week_kind[w][kind]:
                        leader = cluster[0]
                        common = set(self.allowed_rooms[leader])
                        for a in cluster[1:]:
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

                        for a in cluster[1:]:
                            self.m.Add(sum(self.room_sel[(a, r)] for r in self.allowed_rooms[a]) == 1)
                            for r in self.allowed_rooms[a]:
                                if r in common:
                                    self.m.Add(self.room_sel[(a, r)] == self.room_sel[(leader, r)])
                                else:
                                    self.m.Add(self.room_sel[(a, r)] == 0)
                        clustered.update(cluster)

                for a_id, act in self.inst.activities.items():
                    if act.week != w or a_id in clustered:
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


# ---------- Greedy room assignment with co-location and tutorial support ----------

def _clusters_for_assignment(inst: Instance) -> Dict[int, Dict[str, List[List[int]]]]:
    # build the same cluster view the solver uses, but only membership is needed here
    by_week_kind: Dict[int, Dict[str, List[List[int]]]] = {w: {"LEC": [], "TUT": [], "LAB": []} for w in inst.weeks}

    by_ckwg: DefaultDict[Tuple[int, str, int, int], List[int]] = defaultdict(list)
    for a_id, a in inst.activities.items():
        if len(a.group_ids) == 1:
            by_ckwg[(a.course_id, a.kind, a.week, a.group_ids[0])].append(a_id)

    for c_id, course in inst.courses.items():
        shared = getattr(course, "share_lecture_group_ids", None)
        if shared:
            shared_set = set(shared)
            by_week: DefaultDict[int, List[int]] = defaultdict(list)
            for (cc, k, w, g), bucket in by_ckwg.items():
                if cc != c_id or k != "LEC":
                    continue
                if g in shared_set:
                    by_week[w].extend(bucket)
            for w, members in by_week.items():
                if len(members) >= 2:
                    by_week_kind[w]["LEC"].append(sorted(members))

    key_map: DefaultDict[Tuple[str, int, str], List[int]] = defaultdict(list)
    for a_id, a in inst.activities.items():
        key = getattr(a, "cluster_key", None)
        if key:
            key_map[(str(key), a.week, a.kind)].append(a_id)
    for (key, w, kind), members in key_map.items():
        if len(members) >= 2:
            by_week_kind[w][kind].append(sorted(members))

    for w in by_week_kind:
        for kind in ("LEC", "TUT", "LAB"):
            seen: Set[Tuple[int, ...]] = set()
            uniq: List[List[int]] = []
            for c in by_week_kind[w][kind]:
                t = tuple(c)
                if t not in seen:
                    seen.add(t)
                    uniq.append(c)
            by_week_kind[w][kind] = uniq

    return by_week_kind


def assign_rooms_greedily(inst: Instance, schedule: Dict[int, Dict[str, object]]) -> None:
    """
    After CP assigns times, pick rooms per slot.

    Policy:
      - Co-locate clustered activities onto one room for that kind.
      - Specialized labs prefer matching SPECIALIZED_LAB; may fall back to any lab room.
      - LEC use LECTURE rooms only.
      - TUT use TUTORIAL rooms first, then LECTURE overflow.
      - Room selection is capacity-aware (based on sum of involved group sizes).
    """
    days = inst.days
    weeks = sorted(inst.weeks)
    S = inst.slots_per_day

    lecture_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]
    tutorial_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "TUTORIAL"]
    lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
    spec_rooms_by_tag: Dict[str, List[int]] = {}
    for r_id, room in inst.rooms.items():
        if room.room_type == "SPECIALIZED_LAB":
            for tag in getattr(room, "specialization_tags", []) or []:
                spec_rooms_by_tag.setdefault(tag, []).append(r_id)

    # time occupancy
    slot_acts: Dict[Tuple[int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]
        for off in range(dur):
            s = s0 + off
            slot_acts.setdefault((w, d, s), []).append(a_id)

    clusters = _clusters_for_assignment(inst)

    def _required_capacity_for_activity(a_id: int) -> int:
        gids = schedule[a_id].get("group_ids", []) or []
        gids_int = [int(g) for g in gids]
        return sum(inst.groups[g].size for g in gids_int if g in inst.groups)

    def _required_capacity_for_members(members: List[int]) -> int:
        gids: set[int] = set()
        for a_id in members:
            for g in schedule[a_id].get("group_ids", []) or []:
                gids.add(int(g))
        return sum(inst.groups[g].size for g in gids if g in inst.groups)

    def _pick_room(room_ids: List[int], occupied: set[int], required_capacity: int) -> int | None:
        candidates = [
            r_id for r_id in room_ids
            if r_id not in occupied and inst.rooms[r_id].capacity >= required_capacity
        ]
        candidates.sort(key=lambda r_id: inst.rooms[r_id].capacity)
        return candidates[0] if candidates else None

    for w in weeks:
        for d in days:
            for s in range(S):
                key = (w, d, s)
                acts = slot_acts.get(key)
                if not acts:
                    continue

                occupied = {
                    schedule[a_id]["room_id"]
                    for a_id in acts
                    if schedule[a_id]["room_id"] is not None
                }
                occupied.discard(None)

                unassigned = [a_id for a_id in acts if schedule[a_id]["room_id"] is None]
                if not unassigned:
                    continue

                # co-locate clusters per kind
                # LEC clusters → LECTURE room
                clusters_here_lec: List[List[int]] = []
                for cl in clusters[w]["LEC"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_lec.append(members)
                for members in clusters_here_lec:
                    req = _required_capacity_for_members(members)
                    room_id = _pick_room(lecture_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No LECTURE room fits LEC cluster at {w}-{d}-{s} (need cap {req})")
                    for a_id in members:
                        schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # TUT clusters → TUTORIAL first, else LECTURE
                clusters_here_tut: List[List[int]] = []
                for cl in clusters[w]["TUT"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_tut.append(members)
                for members in clusters_here_tut:
                    req = _required_capacity_for_members(members)
                    room_id = _pick_room(tutorial_rooms, occupied, req)
                    if room_id is None:
                        room_id = _pick_room(lecture_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No room fits TUT cluster at {w}-{d}-{s} (need cap {req})")
                    for a_id in members:
                        schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # LAB clusters → lab room
                clusters_here_lab: List[List[int]] = []
                for cl in clusters[w]["LAB"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_lab.append(members)
                for members in clusters_here_lab:
                    req = _required_capacity_for_members(members)
                    room_id = _pick_room(lab_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No LAB room fits LAB cluster at {w}-{d}-{s} (need cap {req})")
                    for a_id in members:
                        schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # specialized labs first
                labs_spec_by_tag: Dict[str, List[int]] = {}
                labs_generic: List[int] = []
                lecs: List[int] = []
                tuts: List[int] = []

                for a_id in unassigned:
                    act = inst.activities[a_id]
                    if act.kind == "LAB":
                        tag = getattr(act, "requires_specialization", None)
                        if tag:
                            labs_spec_by_tag.setdefault(tag, []).append(a_id)
                        else:
                            labs_generic.append(a_id)
                    elif act.kind == "LEC":
                        lecs.append(a_id)
                    else:
                        tuts.append(a_id)

                for tag, acts_tag in labs_spec_by_tag.items():
                    for a_id in acts_tag:
                        req = _required_capacity_for_activity(a_id)
                        preferred = [r for r in spec_rooms_by_tag.get(tag, []) if r not in occupied]
                        room_id = _pick_room(preferred, occupied, req)
                        if room_id is None:
                            room_id = _pick_room(lab_rooms, occupied, req)
                        if room_id is None:
                            raise ValueError(f"No lab room fits specialised lab a{a_id} (need cap {req})")
                        schedule[a_id]["room_id"] = room_id
                        occupied.add(room_id)

                for a_id in labs_generic:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(lab_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No lab room fits lab a{a_id} (need cap {req})")
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)

                # lectures
                for a_id in lecs:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(lecture_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No lecture room fits a{a_id} (need cap {req})")
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)

                # tutorials (prefer TUTORIAL then LECTURE)
                for a_id in tuts:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(tutorial_rooms, occupied, req)
                    if room_id is None:
                        room_id = _pick_room(lecture_rooms, occupied, req)
                    if room_id is None:
                        raise ValueError(f"No tutorial/lecture room fits a{a_id} (need cap {req})")
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)
