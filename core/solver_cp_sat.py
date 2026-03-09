from __future__ import annotations
from typing import Dict, List, Tuple, Optional, Set, DefaultDict
from collections import defaultdict

from ortools.sat.python import cp_model
from utils.domain import Instance
from utils.schedule_rules import (
    calendar_slot_blocked,
    generic_resources_available,
    room_is_available,
    room_transition_buffer,
)


class GreedyRoomingError(ValueError):
    def __init__(self, message: str, *, reason: str, activity_id: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.activity_id = activity_id


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

    def __init__(self, inst: Instance, room_mode: str = "cp_rooms", *, use_objective: bool = True):
        assert room_mode in ("greedy", "cp_rooms")
        self.inst = inst
        self.room_mode = room_mode
        self.use_objective = bool(use_objective)

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
        if self.use_objective:
            self._add_objective()
        self._add_decision_strategy()

    # ---------- public API ----------

    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
        workers: Optional[int] = 8,
        random_seed: Optional[int] = None,
        log_progress: bool = False,
    ):
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        if workers is not None:
            solver.parameters.num_search_workers = int(workers)
        if random_seed is not None:
            solver.parameters.random_seed = int(random_seed)
        solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
        if log_progress:
            solver.parameters.log_search_progress = True
            solver.parameters.log_to_stdout = True
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

    def _hard_flag(self, name: str, default: bool = True) -> bool:
        flags = getattr(self.inst, "hard_constraints", {}) or {}
        if not isinstance(flags, dict):
            return default
        raw = flags.get(name, default)
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() not in ("0", "false", "no")

    def _validate_staff_assignments(self) -> None:
        inst = self.inst
        errs: list[str] = []
        for a in inst.activities.values():
            if a.kind == "LEC":
                sid = a.prof_id
                s = inst.staff.get(sid)
                if s is None:
                    errs.append(f"activity {a.id}: missing professor staff id {sid}")
                    continue
                if not s.is_prof:
                    errs.append(f"activity {a.id}: LEC must be taught by a professor (staff {sid})")
                if a.course_id not in getattr(s, "can_teach_courses", set()):
                    errs.append(f"activity {a.id}: professor {sid} cannot teach course {a.course_id}")
            else:
                sid = a.ta_id
                s = inst.staff.get(sid)
                if s is None:
                    errs.append(f"activity {a.id}: missing TA staff id {sid}")
                    continue
                if s.is_prof:
                    errs.append(f"activity {a.id}: {a.kind} must be taught by a TA (staff {sid})")
                if a.course_id not in getattr(s, "can_teach_courses", set()):
                    errs.append(f"activity {a.id}: TA {sid} cannot teach course {a.course_id}")
        if errs:
            raise ValueError("Invalid staff assignment/competency: " + "; ".join(errs))

    def _validate_block_professor_rules(self) -> None:
        if not self._hard_flag("enforce_block_professor_rules", True):
            return
        inst = self.inst
        errs: list[str] = []

        # Group LEC activities by (prof, course, week)
        by_scw: DefaultDict[Tuple[int, int, int], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            if a.kind == "LEC":
                by_scw[(a.prof_id, a.course_id, a.week)].append(a_id)

        for (sid, c_id, w), act_ids in by_scw.items():
            s = inst.staff.get(sid)
            if s is None or not self._is_block_prof(s):
                continue
            total = sum(inst.activities[a].duration for a in act_ids)
            if not (2 <= total <= 3):
                errs.append(f"block-prof {sid} course {c_id} week {w}: total lecture slots {total} not in [2,3]")
        if errs:
            raise ValueError("Block-professor rule violation: " + "; ".join(errs))

    def _validate_semester_rules(self) -> None:
        """
        Generator/semester invariants used by the solver:
        - Activity totals must match the course metadata (lecture/tutorial slot totals,
          lab session counts and lab durations).
        - Week-1 must be lectures-only; tutorials/labs in the first week are rejected.
        """
        inst = self.inst
        first_week = inst.weeks[0] if inst.weeks else None

        # Work out which groups belong to each course (prefer the explicit share list)
        course_groups: dict[int, list[int]] = {}
        for c_id, c in inst.courses.items():
            gids = list(c.share_lecture_group_ids) if c.share_lecture_group_ids else [
                g_id for g_id, g in inst.groups.items() if c_id in g.course_ids
            ]
            course_groups[c_id] = gids

        # Validate per-course totals against metadata (treat lecture/tutorial counts as slot totals).
        errs: list[str] = []
        by_course_kind: dict[tuple[int, str], list] = {}
        for a in inst.activities.values():
            by_course_kind.setdefault((a.course_id, a.kind), []).append(a)

        for c_id, c in inst.courses.items():
            lecs = by_course_kind.get((c_id, "LEC"), [])
            tuts = by_course_kind.get((c_id, "TUT"), [])
            labs = by_course_kind.get((c_id, "LAB"), [])

            lec_slots = sum(a.duration for a in lecs)
            tut_slots_by_group: dict[int, int] = {}
            for a in tuts:
                for g in a.group_ids:
                    tut_slots_by_group[g] = tut_slots_by_group.get(g, 0) + a.duration
            lab_sessions = len(labs)

            if c.structure_type == "LAB_ONLY":
                if lecs or tuts:
                    errs.append(f"course {c_id}: LAB_ONLY must not include LEC/TUT activities")

            if int(getattr(c, "lecture_count", 0) or 0) != lec_slots:
                errs.append(f"course {c_id}: lecture slots {lec_slots} != lecture_count {c.lecture_count}")

            expected_tut = int(getattr(c, "tutorial_count", 0) or 0)
            for g_id in course_groups.get(c_id, []):
                got = tut_slots_by_group.get(g_id, 0)
                if expected_tut != got:
                    errs.append(f"course {c_id} group {g_id}: tutorial slots {got} != tutorial_count {expected_tut}")

            expected_lab_weeks = int(getattr(c, "lab_weeks", 0) or 0)
            if expected_lab_weeks != lab_sessions:
                errs.append(f"course {c_id}: lab sessions {lab_sessions} != lab_weeks {expected_lab_weeks}")
            if labs:
                expected_dur = int(getattr(c, "lab_duration", 0) or 0)
                for a in labs:
                    if a.duration != expected_dur:
                        errs.append(f"course {c_id}: LAB a{a.id} duration {a.duration} != lab_duration {expected_dur}")

        if errs:
            raise ValueError("Instance violates course totals: " + "; ".join(errs))

        # Enforce: week-1 contains lectures only (configurable).
        if self._hard_flag("week1_lectures_only", True) and first_week is not None:
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
        self._validate_staff_assignments()
        self._validate_block_professor_rules()

        # staff per activity: professors teach LEC, TAs teach TUT/LAB by convention
        for a_id, act in inst.activities.items():
            self.activity_staff[a_id] = act.prof_id if act.kind == "LEC" else act.ta_id
            for resource_id in getattr(act, "resource_ids", []) or []:
                if int(resource_id) not in getattr(inst, "generic_resources", {}) and getattr(inst, "generic_resources", {}):
                    raise ValueError(f"Activity {a_id} references unknown generic resource {int(resource_id)}")

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

        week_set = set(int(w) for w in self.weeks)
        for a_id, act in inst.activities.items():
            sid = self.activity_staff[a_id]
            staff = inst.staff[sid]
            available_days = set(getattr(staff, "available_days", self.days))
            available_weeks = getattr(staff, "available_weeks", None)
            if available_weeks is None:
                allowed_weeks = set(week_set)
            else:
                allowed_weeks = {int(w) for w in available_weeks if int(w) in week_set}
                if not allowed_weeks:
                    allowed_weeks = set(week_set)
            allowed_day_idx: Set[int] = {i for i, d in enumerate(self.days) if d in available_days}

            if int(act.week) not in allowed_weeks:
                raise ValueError(
                    f"Activity {a_id} week {int(act.week)} is outside staff "
                    f"{sid} available weeks {sorted(allowed_weeks)}"
                )

            max_start_slot = self.S - act.duration
            if max_start_slot < 0:
                raise ValueError(f"Activity {a_id} duration {act.duration} exceeds day slots {self.S}")

            times: List[int] = []
            for d_idx in range(self.D):
                if d_idx not in allowed_day_idx:
                    continue
                if calendar_slot_blocked(inst, week=int(act.week), day=str(self.days[d_idx])):
                    continue
                for s in range(max_start_slot + 1):
                    if not generic_resources_available(
                        inst,
                        getattr(act, "resource_ids", []) or [],
                        day=str(self.days[d_idx]),
                        start_slot=int(s),
                        dur=int(act.duration),
                    ):
                        continue
                    t = d_idx * self.S + s
                    if sunday_range and sunday_range[0] <= t <= sunday_range[1]:
                        continue
                    times.append(t)

            lock = getattr(inst, "locked_activities", {}) or {}
            fixed = lock.get(a_id) if isinstance(lock, dict) else None
            if fixed and isinstance(fixed, dict) and "day" in fixed and "slot" in fixed:
                fixed_day = str(fixed["day"])
                fixed_slot = int(fixed["slot"])
                if fixed_day not in self.days:
                    raise ValueError(f"Locked activity {a_id}: day '{fixed_day}' is not in inst.days")
                if not (0 <= fixed_slot <= max_start_slot):
                    raise ValueError(f"Locked activity {a_id}: slot {fixed_slot} invalid for duration {act.duration}")
                fixed_t = self.days.index(fixed_day) * self.S + fixed_slot
                if fixed_t not in times:
                    raise ValueError(f"Locked activity {a_id}: fixed time {fixed_day}@{fixed_slot} is not allowed")
                times = [fixed_t]
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

        def required_capacity(act_id: int) -> int:
            gids = inst.activities[act_id].group_ids
            return sum(inst.groups[g].size for g in gids if g in inst.groups)

        for a_id, act in inst.activities.items():
            rooms: List[int] = []
            need = required_capacity(a_id)
            if act.kind == "LAB":
                req = getattr(act, "requires_specialization", None)
                lab_candidates = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
                if req:
                    for r_id in lab_candidates:
                        tags = getattr(inst.rooms[r_id], "specialization_tags", []) or []
                        if req in tags and inst.rooms[r_id].capacity >= need:
                            rooms.append(r_id)
                    if not rooms:
                        raise ValueError(f"Activity {a_id} requires specialized lab '{req}' but no matching room exists")
                else:
                    rooms = [r_id for r_id in lab_candidates if inst.rooms[r_id].capacity >= need]
            elif act.kind == "TUT":
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("TUTORIAL", "LECTURE") and r.capacity >= need]
            else:  # LEC
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE" and r.capacity >= need]

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
        if getattr(inst, "generic_resources", None):
            for res_id, resource in inst.generic_resources.items():
                cap = max(1, int(getattr(resource, "capacity", 1) or 1))
                for w in self.weeks:
                    for tau in range(self.T_week):
                        terms: List[cp_model.BoolVar] = []
                        for a_id, act in inst.activities.items():
                            if int(act.week) != int(w):
                                continue
                            if int(res_id) not in set(int(r) for r in (getattr(act, "resource_ids", []) or [])):
                                continue
                            dur = int(act.duration)
                            for t in self.allowed_starts[a_id]:
                                if int(t) <= int(tau) < int(t) + int(dur):
                                    terms.append(self.x[(a_id, t)])
                        if terms:
                            m.Add(sum(terms) <= int(cap))

        if self._hard_flag("enforce_block_professor_rules", True):
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

            # Block-only professor lecture blocks (per course/week): single 2–3-slot contiguous block on one day.
            for s_id, staff in inst.staff.items():
                if not getattr(staff, "blocks_only", False):
                    continue
                for w in self.weeks:
                    # courses with lectures taught by this professor in this week
                    courses_here = {
                        act.course_id
                        for act in inst.activities.values()
                        if act.week == w and act.kind == "LEC" and act.prof_id == s_id
                    }
                    for c_id in courses_here:
                        lec_ids = [
                            a_id for a_id, act in inst.activities.items()
                            if act.week == w and act.kind == "LEC" and act.prof_id == s_id and act.course_id == c_id
                        ]
                        if not lec_ids:
                            continue

                        occ: Dict[Tuple[int, int], cp_model.BoolVar] = {
                            (d, s): m.NewBoolVar(f"blk_occ[{s_id},{c_id},{w},{d},{s}]")
                            for d in range(self.D) for s in range(self.S)
                        }
                        for (d, s), b in occ.items():
                            terms: List[cp_model.BoolVar] = []
                            for a_id in lec_ids:
                                act = inst.activities[a_id]
                                for t in self.allowed_starts[a_id]:
                                    d_idx = t // self.S
                                    s0 = t % self.S
                                    if d_idx != d:
                                        continue
                                    if s0 <= s < s0 + act.duration:
                                        terms.append(self.x[(a_id, t)])
                                        m.Add(b >= self.x[(a_id, t)])
                            if terms:
                                m.Add(sum(terms) >= b)
                            else:
                                m.Add(b == 0)

                        day_used = {d: m.NewBoolVar(f"blk_day[{s_id},{c_id},{w},{d}]") for d in range(self.D)}
                        for d in range(self.D):
                            day_terms = [occ[(d, s)] for s in range(self.S)]
                            for s in range(self.S):
                                m.Add(day_used[d] >= occ[(d, s)])
                            m.Add(sum(day_terms) >= day_used[d])
                        m.Add(sum(day_used.values()) == 1)

                        total_slots_terms: List[cp_model.LinearExpr] = []
                        for a_id in lec_ids:
                            act = inst.activities[a_id]
                            for t in self.allowed_starts[a_id]:
                                total_slots_terms.append(act.duration * self.x[(a_id, t)])
                        total_slots = sum(total_slots_terms)
                        m.Add(total_slots >= 2)
                        m.Add(total_slots <= 3)
                        m.Add(sum(occ.values()) == total_slots)

                        start_block: Dict[Tuple[int, int], cp_model.BoolVar] = {
                            (d, s): m.NewBoolVar(f"blk_start[{s_id},{c_id},{w},{d},{s}]")
                            for d in range(self.D) for s in range(self.S)
                        }
                        for d in range(self.D):
                            # slot 0
                            m.Add(start_block[(d, 0)] <= occ[(d, 0)])
                            m.Add(start_block[(d, 0)] >= occ[(d, 0)])
                            for s in range(1, self.S):
                                cur = occ[(d, s)]
                                prev = occ[(d, s - 1)]
                                sb = start_block[(d, s)]
                                m.Add(sb <= cur)
                                m.Add(sb + prev <= 1)
                                m.Add(sb + prev >= cur)
                        m.Add(sum(start_block.values()) == 1)

        # Optional weekly load cap
        if self._hard_flag("enforce_staff_weekly_caps", True):
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
        if self._hard_flag("enforce_staff_daily_caps", True):
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

        # Precedence rules across activities.
        if self._hard_flag("enforce_precedence_rules", True):
            for raw_rule in getattr(inst, "precedence_rules", []) or []:
                if not isinstance(raw_rule, dict):
                    continue
                try:
                    before_id = int(raw_rule.get("before_activity_id"))
                    after_id = int(raw_rule.get("after_activity_id"))
                except Exception:
                    continue
                if before_id not in self.start or after_id not in self.start:
                    continue
                before_act = inst.activities[before_id]
                after_act = inst.activities[after_id]
                min_gap = int(raw_rule.get("min_gap_slots", 0) or 0)
                if int(before_act.week) > int(after_act.week):
                    raise ValueError(
                        f"Precedence impossible: A{before_id} is in a later week than A{after_id}"
                    )
                if int(before_act.week) == int(after_act.week):
                    m.Add(
                        self.start[after_id]
                        >= self.start[before_id] + int(before_act.duration) + int(min_gap)
                    )

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
            enforce_room_availability = self._hard_flag("enforce_room_availability", True)

            # Locked rooms (partial re-solve support)
            locks = getattr(inst, "locked_activities", {}) or {}
            if isinstance(locks, dict):
                for a_id, fixed in locks.items():
                    if not isinstance(fixed, dict) or "room_id" not in fixed:
                        continue
                    if a_id not in self.allowed_rooms:
                        continue
                    fixed_room = int(fixed["room_id"])
                    if fixed_room not in self.allowed_rooms[a_id]:
                        raise ValueError(f"Locked activity {a_id}: room_id {fixed_room} is not eligible")
                    for r in self.allowed_rooms[a_id]:
                        self.m.Add(self.room_sel[(a_id, r)] == (1 if r == fixed_room else 0))

            # Room availability (if provided): forbid (activity start, room) combinations that
            # use any unavailable (day, slot) pair.
            full_pairs = {(d, s) for d in self.days for s in range(self.S)}

            def _room_allows(room_id: int, week: int, day: str, start_slot: int, dur: int) -> bool:
                return room_is_available(
                    inst,
                    int(room_id),
                    week=int(week),
                    day=str(day),
                    start_slot=int(start_slot),
                    dur=int(dur),
                )

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

                # Availability constraints for all activities in the week (clustered or not)
                for a_id, act in self.inst.activities.items():
                    if act.week != w:
                        continue
                    dur = act.duration
                    allowed_starts = self.allowed_starts[a_id]
                    for r in self.allowed_rooms.get(a_id, []):
                        room = inst.rooms[r]
                        avail = getattr(room, "availability", None)
                        if (not enforce_room_availability) or avail is None:
                            continue
                        if isinstance(avail, set) and avail.issuperset(full_pairs):
                            continue
                        for t in allowed_starts:
                            d_idx = t // self.S
                            s0 = t % self.S
                            if not _room_allows(r, int(w), self.days[d_idx], s0, dur):
                                self.m.Add(self.room_sel[(a_id, r)] + self.x[(a_id, t)] <= 1)
                # Travel buffers between rooms for shared group/staff resources.
                if self._hard_flag("enforce_travel_time_buffers", True) and any(
                    int(v) > 0 for v in (getattr(inst, "travel_time_rules", {}) or {}).values()
                ):
                    shared_pairs: Set[Tuple[int, int]] = set()
                    week_activity_ids = [
                        int(a_id)
                        for a_id, act in self.inst.activities.items()
                        if int(act.week) == int(w)
                    ]
                    for idx, a_id in enumerate(week_activity_ids):
                        act_a = self.inst.activities[a_id]
                        staff_a = int(self.activity_staff[a_id])
                        groups_a = set(int(g) for g in act_a.group_ids)
                        for b_id in week_activity_ids[idx + 1 :]:
                            act_b = self.inst.activities[b_id]
                            if staff_a == int(self.activity_staff[b_id]) or groups_a & set(
                                int(g) for g in act_b.group_ids
                            ):
                                shared_pairs.add((int(a_id), int(b_id)))

                    for a_id, b_id in sorted(shared_pairs):
                        act_a = self.inst.activities[a_id]
                        act_b = self.inst.activities[b_id]
                        for ra in self.allowed_rooms.get(a_id, []):
                            for rb in self.allowed_rooms.get(b_id, []):
                                buffer_slots = room_transition_buffer(
                                    inst,
                                    inst.rooms.get(int(ra)),
                                    inst.rooms.get(int(rb)),
                                )
                                if int(buffer_slots) <= 0:
                                    continue
                                for ta in self.allowed_starts[a_id]:
                                    day_a = int(ta // self.S)
                                    end_a = int(ta) + int(act_a.duration)
                                    for tb in self.allowed_starts[b_id]:
                                        if int(tb // self.S) != int(day_a):
                                            continue
                                        end_b = int(tb) + int(act_b.duration)
                                        violated = False
                                        if int(ta) <= int(tb):
                                            violated = int(end_a) + int(buffer_slots) > int(tb)
                                        else:
                                            violated = int(end_b) + int(buffer_slots) > int(ta)
                                        if violated:
                                            self.m.Add(
                                                self.x[(a_id, ta)]
                                                + self.x[(b_id, tb)]
                                                + self.room_sel[(a_id, ra)]
                                                + self.room_sel[(b_id, rb)]
                                                <= 3
                                            )

            for (r, w), ivs in room_intervals_by_week.items():
                if len(ivs) > 1:
                    self.m.AddNoOverlap(ivs)

    def _add_objective(self) -> None:
        """
        Add a linear soft-constraint objective similar to the local-search scorer.

        Notes:
          - This is a weighted penalty model; it does not change feasibility.
          - Room-consistency penalties are included only in CP-rooming mode.
        """
        m = self.m
        inst = self.inst

        weights = {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "staff_free_day": 6,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "stability": 1,
            "room_consistency": 1,
            "single_slot": 6,
            "same_kind_week": 3,
        }
        overrides = getattr(inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    weights[str(k)] = int(v)
                except Exception:
                    continue

        days = list(self.days)
        weeks = list(self.weeks)
        S = int(self.S)
        D = int(self.D)

        group_ids = list(inst.groups.keys())
        staff_ids = list(inst.staff.keys())

        mf_days = {d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}}
        mf_day_idx = [i for i, d in enumerate(days) if d in mf_days]

        # Precompute occupancy terms by (entity, week, day_idx, slot).
        g_terms: DefaultDict[Tuple[int, int, int, int], List[cp_model.BoolVar]] = defaultdict(list)
        s_terms: DefaultDict[Tuple[int, int, int, int], List[cp_model.BoolVar]] = defaultdict(list)

        for a_id, act in inst.activities.items():
            w = act.week
            if w not in set(weeks):
                continue
            dur = int(act.duration)
            sid = self.activity_staff[a_id]
            for t in self.allowed_starts[a_id]:
                d_idx = t // S
                s0 = t % S
                xvar = self.x[(a_id, t)]
                for off in range(dur):
                    slot = s0 + off
                    if 0 <= slot < S:
                        s_terms[(sid, w, d_idx, slot)].append(xvar)
                        for g in act.group_ids:
                            g_terms[(int(g), w, d_idx, slot)].append(xvar)

        # Build group occupancy and day-active booleans.
        g_occ: Dict[Tuple[int, int, int, int], cp_model.BoolVar] = {}
        g_day: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}
        g_active_days: Dict[Tuple[int, int], cp_model.LinearExpr] = {}

        for g in group_ids:
            for w in weeks:
                for d_idx in range(D):
                    for s in range(S):
                        key = (g, w, d_idx, s)
                        b = m.NewBoolVar(f"g_occ[{g},{w},{d_idx},{s}]")
                        terms = g_terms.get(key, [])
                        if terms:
                            for xvar in terms:
                                m.Add(b >= xvar)
                            m.Add(sum(terms) >= b)
                        else:
                            m.Add(b == 0)
                        g_occ[key] = b

        for g in group_ids:
            for w in weeks:
                day_bools: List[cp_model.BoolVar] = []
                for d_idx in range(D):
                    b = m.NewBoolVar(f"g_day[{g},{w},{d_idx}]")
                    occs = [g_occ[(g, w, d_idx, s)] for s in range(S)]
                    for o in occs:
                        m.Add(b >= o)
                    m.Add(sum(occs) >= b)
                    g_day[(g, w, d_idx)] = b
                    day_bools.append(b)
                g_active_days[(g, w)] = sum(day_bools)

        # Staff day activity for staff-free-day penalty.
        s_occ: Dict[Tuple[int, int, int, int], cp_model.BoolVar] = {}
        s_day: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}
        s_active_days: Dict[Tuple[int, int], cp_model.LinearExpr] = {}

        for sid in staff_ids:
            for w in weeks:
                for d_idx in range(D):
                    for s in range(S):
                        key = (sid, w, d_idx, s)
                        b = m.NewBoolVar(f"s_occ[{sid},{w},{d_idx},{s}]")
                        terms = s_terms.get(key, [])
                        if terms:
                            for xvar in terms:
                                m.Add(b >= xvar)
                            m.Add(sum(terms) >= b)
                        else:
                            m.Add(b == 0)
                        s_occ[key] = b

        for sid in staff_ids:
            for w in weeks:
                day_bools: List[cp_model.BoolVar] = []
                for d_idx in range(D):
                    b = m.NewBoolVar(f"s_day[{sid},{w},{d_idx}]")
                    occs = [s_occ[(sid, w, d_idx, s)] for s in range(S)]
                    for o in occs:
                        m.Add(b >= o)
                    m.Add(sum(occs) >= b)
                    s_day[(sid, w, d_idx)] = b
                    day_bools.append(b)
                s_active_days[(sid, w)] = sum(day_bools)

        penalties: List[cp_model.LinearExpr] = []

        # Student free days + Mon–Fri free days + active days.
        for g, group in inst.groups.items():
            want = int(getattr(group, "preferred_free_days", 0) or 0)
            for w in weeks:
                active = g_active_days[(g, w)]

                slack_free = m.NewIntVar(0, D, f"slack_free[{g},{w}]")
                m.Add(slack_free >= want - D + active)
                penalties.append(weights["stud_free_days"] * slack_free)

                if mf_day_idx:
                    active_mf = sum(g_day[(g, w, d)] for d in mf_day_idx)
                    slack_mf = m.NewIntVar(0, len(mf_day_idx), f"slack_mf[{g},{w}]")
                    m.Add(slack_mf >= want - len(mf_day_idx) + active_mf)
                    penalties.append(weights["stud_free_mf"] * slack_mf)

                slack_active = m.NewIntVar(0, D, f"slack_active[{g},{w}]")
                m.Add(slack_active >= active - 3)
                penalties.append(weights["active_days"] * slack_active)

        # Student gaps, day shape (per day).
        for g in group_ids:
            for w in weeks:
                for d_idx in range(D):
                    occs = [g_occ[(g, w, d_idx, s)] for s in range(S)]
                    load_var = m.NewIntVar(0, S, f"g_load[{g},{w},{d_idx}]")
                    m.Add(load_var == sum(occs))

                    # thin day (exactly two slots)
                    thin = m.NewBoolVar(f"thin_day[{g},{w},{d_idx}]")
                    m.Add(load_var == 2).OnlyEnforceIf(thin)
                    m.Add(load_var != 2).OnlyEnforceIf(thin.Not())
                    penalties.append(weights["thin_day"] * thin)

                    # penalize single-slot presence days to avoid lonely days on campus
                    diff = m.NewIntVar(-S, S, f"single_diff[{g},{w},{d_idx}]")
                    abs_diff = m.NewIntVar(0, S, f"single_abs[{g},{w},{d_idx}]")
                    m.Add(diff == load_var - 1)
                    m.AddAbsEquality(abs_diff, diff)
                    is_single = m.NewBoolVar(f"single_day[{g},{w},{d_idx}]")
                    m.Add(abs_diff == 0).OnlyEnforceIf(is_single)
                    m.Add(abs_diff >= 1).OnlyEnforceIf(is_single.Not())
                    penalties.append(weights["single_slot"] * is_single)

                    # blocks: count starts of occupied segments
                    starts = [m.NewBoolVar(f"g_block[{g},{w},{d_idx},0]")]
                    m.Add(starts[0] == occs[0])
                    for s in range(1, S):
                        sb = m.NewBoolVar(f"g_block[{g},{w},{d_idx},{s}]")
                        cur = occs[s]
                        prev = occs[s - 1]
                        m.Add(sb <= cur)
                        m.Add(sb + prev <= 1)
                        m.Add(sb + prev >= cur)
                        starts.append(sb)
                    blocks = sum(starts)
                    slack_gaps = m.NewIntVar(0, S, f"slack_gaps[{g},{w},{d_idx}]")
                    m.Add(slack_gaps >= blocks - 1)
                    penalties.append(weights["stud_gaps"] * slack_gaps)

                    # late start: day active but nothing in the first two slots
                    if S >= 2:
                        early_first2 = m.NewBoolVar(f"early_first2[{g},{w},{d_idx}]")
                        m.Add(early_first2 >= occs[0])
                        m.Add(early_first2 >= occs[1])
                        m.Add(early_first2 <= occs[0] + occs[1])

                        late = m.NewBoolVar(f"late_start[{g},{w},{d_idx}]")
                        day_active = g_day[(g, w, d_idx)]
                        m.Add(late >= day_active - early_first2)
                        m.Add(late <= day_active)
                        m.Add(late <= 1 - early_first2)
                        penalties.append(weights["late_start"] * late)

        # Staff: require at least one free day per week (soft penalty).
        for sid in staff_ids:
            for w in weeks:
                active = s_active_days[(sid, w)]
                slack = m.NewIntVar(0, D, f"slack_staff_free[{sid},{w}]")
                m.Add(slack >= 1 - D + active)
                penalties.append(weights["staff_free_day"] * slack)

        # Stability: day-active pattern changes between consecutive weeks.
        for g in group_ids:
            for wi in range(1, len(weeks)):
                w_prev = weeks[wi - 1]
                w_curr = weeks[wi]
                for d_idx in range(D):
                    a = g_day[(g, w_prev, d_idx)]
                    b = g_day[(g, w_curr, d_idx)]
                    diff = m.NewBoolVar(f"g_stab[{g},{w_curr},{d_idx}]")
                    m.Add(diff >= a - b)
                    m.Add(diff >= b - a)
                    m.Add(diff <= a + b)
                    m.Add(diff <= 2 - a - b)
                    penalties.append(weights["stability"] * diff)

        # Room consistency per (course, group, kind) across weeks (CP-rooming only).
        if self.room_mode == "cp_rooms":
            key_to_activities: DefaultDict[Tuple[int, int, str], List[int]] = defaultdict(list)
            for a_id, act in inst.activities.items():
                for g in act.group_ids:
                    key_to_activities[(act.course_id, int(g), act.kind)].append(a_id)

            for (c_id, g_id, kind), act_ids in key_to_activities.items():
                if len(act_ids) <= 1:
                    continue
                room_ids: Set[int] = set()
                for a_id in act_ids:
                    room_ids.update(self.allowed_rooms.get(a_id, []))
                if not room_ids:
                    continue

                used: Dict[int, cp_model.BoolVar] = {r: m.NewBoolVar(f"room_used[{c_id},{g_id},{kind},{r}]") for r in room_ids}
                for r in room_ids:
                    terms: List[cp_model.BoolVar] = []
                    for a_id in act_ids:
                        if r in self.allowed_rooms.get(a_id, []):
                            sel = self.room_sel[(a_id, r)]
                            terms.append(sel)
                            m.Add(used[r] >= sel)
                    if terms:
                        m.Add(sum(terms) >= used[r])
                    else:
                        m.Add(used[r] == 0)

                slack = m.NewIntVar(0, len(room_ids), f"slack_room_cons[{c_id},{g_id},{kind}]")
                m.Add(slack >= sum(used.values()) - 1)
                penalties.append(weights["room_consistency"] * slack)

        if penalties:
            m.Minimize(sum(penalties))

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
      - Specialized labs require matching SPECIALIZED_LAB rooms with the right tag.
      - LEC use LECTURE rooms only.
      - TUT use TUTORIAL rooms first, then LECTURE overflow.
      - Room selection is capacity-aware (based on sum of involved group sizes).
    """
    days = inst.days
    weeks = sorted(inst.weeks)
    S = inst.slots_per_day
    hard_flags = getattr(inst, "hard_constraints", {}) or {}
    enforce_room_availability = bool(hard_flags.get("enforce_room_availability", True))
    enforce_travel_time_buffers = bool(
        hard_flags.get("enforce_travel_time_buffers", True)
    )

    lecture_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]
    tutorial_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "TUTORIAL"]
    specialized_lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "SPECIALIZED_LAB"]
    computer_lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "COMPUTER_LAB"]
    lab_rooms = specialized_lab_rooms + computer_lab_rooms
    spec_rooms_by_tag: Dict[str, List[int]] = {}
    for r_id, room in inst.rooms.items():
        if room.room_type == "SPECIALIZED_LAB":
            for tag in getattr(room, "specialization_tags", []) or []:
                spec_rooms_by_tag.setdefault(tag, []).append(r_id)

    def _room_available(room_id: int, week: int, day: str, start_slot: int, dur: int) -> bool:
        if not enforce_room_availability and not getattr(inst, "room_closures", None):
            return True
        return room_is_available(
            inst,
            int(room_id),
            week=int(week),
            day=str(day),
            start_slot=int(start_slot),
            dur=int(dur),
        )

    # time occupancy
    slot_acts: Dict[Tuple[int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]
        for off in range(dur):
            s = s0 + off
            slot_acts.setdefault((w, d, s), []).append(a_id)

    # honor locked rooms before assigning anything else
    locks = getattr(inst, "locked_activities", {}) or {}
    for a_id, fixed in locks.items():
        if not isinstance(fixed, dict) or "room_id" not in fixed or a_id not in schedule:
            continue
        room_id = int(fixed["room_id"])
        info = schedule[a_id]
        if info.get("room_id") not in (None, room_id):
            raise ValueError(f"Locked room for activity {a_id} conflicts with pre-assigned room")
        if not _room_available(room_id, int(info["week"]), info["day"], info["slot"], info["duration"]):
            raise ValueError(f"Locked room for activity {a_id} is unavailable at the scheduled time")
        schedule[a_id]["room_id"] = room_id

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

    def _travel_buffer_ok(member_ids: List[int], candidate_room_id: int) -> bool:
        if (not enforce_travel_time_buffers) or not getattr(inst, "travel_time_rules", None):
            return True
        member_set = {int(a_id) for a_id in member_ids}
        for a_id in member_set:
            info = schedule[int(a_id)]
            week = int(info["week"])
            day = str(info["day"])
            slot = int(info["slot"])
            dur = int(info["duration"])
            staff_id = int(info["staff_id"])
            groups = {int(g) for g in (info.get("group_ids", []) or [])}
            for other_id, other_info in schedule.items():
                if int(other_id) in member_set:
                    continue
                if other_info.get("room_id") is None:
                    continue
                if int(other_info.get("week", -1)) != int(week):
                    continue
                if str(other_info.get("day", "")) != str(day):
                    continue
                other_staff = int(other_info.get("staff_id", -1))
                other_groups = {int(g) for g in (other_info.get("group_ids", []) or [])}
                if other_staff != int(staff_id) and not (groups & other_groups):
                    continue
                buffer_slots = room_transition_buffer(
                    inst,
                    inst.rooms.get(int(candidate_room_id)),
                    inst.rooms.get(int(other_info["room_id"])),
                )
                if int(buffer_slots) <= 0:
                    continue
                other_slot = int(other_info["slot"])
                other_dur = int(other_info["duration"])
                if int(slot) <= int(other_slot):
                    gap = int(other_slot) - (int(slot) + int(dur))
                else:
                    gap = int(slot) - (int(other_slot) + int(other_dur))
                if int(gap) < int(buffer_slots):
                    return False
        return True

    def _pick_room(
        room_ids: List[int],
        occupied: set[int],
        required_capacity: int,
        week: int,
        day: str,
        slot: int,
        dur: int,
        *,
        member_ids: List[int] | None = None,
    ) -> int | None:
        candidates = [
            r_id for r_id in room_ids
            if r_id not in occupied
            and inst.rooms[r_id].capacity >= required_capacity
            and _room_available(r_id, week, day, slot, dur)
            and _travel_buffer_ok(member_ids or [], int(r_id))
        ]
        candidates.sort(key=lambda r_id: inst.rooms[r_id].capacity)
        return candidates[0] if candidates else None

    def _diagnose_room_failure(
        room_ids: List[int],
        occupied: set[int],
        required_capacity: int,
        week: int,
        day: str,
        slot: int,
        dur: int,
        *,
        member_ids: List[int] | None = None,
    ) -> str:
        if not room_ids:
            return "room_type_missing"
        cap_ok = [r_id for r_id in room_ids if inst.rooms[r_id].capacity >= required_capacity]
        if not cap_ok:
            return "capacity"
        avail_ok = [r_id for r_id in cap_ok if _room_available(r_id, week, day, slot, dur)]
        if not avail_ok:
            return "availability"
        free_ok = [r_id for r_id in avail_ok if r_id not in occupied]
        if not free_ok:
            return "occupied"
        travel_ok = [r_id for r_id in free_ok if _travel_buffer_ok(member_ids or [], int(r_id))]
        if not travel_ok:
            return "travel_buffer"
        return "unknown"

    def _reserved_specialized_rooms(
        *,
        week: int,
        day: str,
        start_slot: int,
        dur: int,
    ) -> set[int]:
        """Rooms that should be reserved for tagged labs overlapping this time span."""
        reserved: set[int] = set()
        for off in range(dur):
            slot = start_slot + off
            for a_id in slot_acts.get((week, day, slot), []):
                if schedule[a_id].get("room_id") is not None:
                    continue
                act = inst.activities[a_id]
                if act.kind != "LAB":
                    continue
                tag = getattr(act, "requires_specialization", None)
                if tag:
                    reserved.update(spec_rooms_by_tag.get(tag, []))
        return reserved

    def _pick_generic_lab_room(
        *,
        week: int,
        day: str,
        start_slot: int,
        dur: int,
        occupied: set[int],
        required_capacity: int,
        member_ids: List[int] | None = None,
    ) -> int | None:
        # Prefer computer labs, then specialized labs not needed by overlapping tagged labs.
        room_id = _pick_room(
            computer_lab_rooms,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )
        if room_id is not None:
            return room_id
        reserved = _reserved_specialized_rooms(week=week, day=day, start_slot=start_slot, dur=dur)
        non_reserved_spec = [r for r in specialized_lab_rooms if r not in reserved]
        room_id = _pick_room(
            non_reserved_spec,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )
        if room_id is not None:
            return room_id
        return _pick_room(
            specialized_lab_rooms,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )

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
                    room_id = _pick_room(
                        lecture_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[members[0]]["duration"],
                        member_ids=members,
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                        raise GreedyRoomingError(
                            f"No lecture room fits LEC cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
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
                    room_id = _pick_room(
                        tutorial_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[members[0]]["duration"],
                        member_ids=members,
                    )
                    if room_id is None:
                        room_id = _pick_room(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            tutorial_rooms + lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                        raise GreedyRoomingError(
                            f"No room fits TUT cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
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
                    dur = schedule[members[0]]["duration"]
                    req_tags = {
                        getattr(inst.activities[a_id], "requires_specialization", None)
                        for a_id in members
                        if getattr(inst.activities[a_id], "requires_specialization", None)
                    }
                    if len(req_tags) > 1:
                        raise GreedyRoomingError(
                            f"Conflicting specialisation tags in LAB cluster at {w}-{d}-{s}: {sorted(req_tags)}",
                            reason="tag_mismatch",
                            activity_id=members[0],
                        )
                    if req_tags:
                        tag = next(iter(req_tags))
                        candidates = spec_rooms_by_tag.get(str(tag), [])
                        room_id = _pick_room(
                            candidates,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            dur,
                            member_ids=members,
                        )
                    else:
                        room_id = _pick_generic_lab_room(
                            week=w,
                            day=d,
                            start_slot=s,
                            dur=dur,
                            occupied=occupied,
                            required_capacity=req,
                            member_ids=members,
                        )
                    if room_id is None:
                        if req_tags:
                            tag = next(iter(req_tags))
                            candidates = spec_rooms_by_tag.get(str(tag), [])
                            reason = (
                                "tag_mismatch"
                                if not candidates
                                else _diagnose_room_failure(
                                    candidates,
                                    occupied,
                                    req,
                                    w,
                                    d,
                                    s,
                                    dur,
                                    member_ids=members,
                                )
                            )
                        else:
                            reason = _diagnose_room_failure(
                                lab_rooms,
                                occupied,
                                req,
                                w,
                                d,
                                s,
                                dur,
                                member_ids=members,
                            )
                        raise GreedyRoomingError(
                            f"No lab room fits LAB cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
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
                        tag_rooms = spec_rooms_by_tag.get(tag, [])
                        room_id = _pick_room(
                            tag_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        if room_id is None:
                            if not tag_rooms:
                                reason = "tag_mismatch"
                            else:
                                reason = _diagnose_room_failure(
                                    tag_rooms,
                                    occupied,
                                    req,
                                    w,
                                    d,
                                    s,
                                    schedule[a_id]["duration"],
                                    member_ids=[a_id],
                                )
                            raise GreedyRoomingError(
                                f"No lab room fits specialised lab a{a_id} (need cap {req}, tag={tag}, reason={reason})",
                                reason=reason,
                                activity_id=a_id,
                            )
                        schedule[a_id]["room_id"] = room_id
                        occupied.add(room_id)

                for a_id in labs_generic:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_generic_lab_room(
                        week=w,
                        day=d,
                        start_slot=s,
                        dur=schedule[a_id]["duration"],
                        occupied=occupied,
                        required_capacity=req,
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lab_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No lab room fits lab a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)

                # lectures
                for a_id in lecs:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(
                        lecture_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[a_id]["duration"],
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No lecture room fits a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)

                # tutorials (prefer TUTORIAL then LECTURE)
                for a_id in tuts:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(
                        tutorial_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[a_id]["duration"],
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        room_id = _pick_room(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            tutorial_rooms + lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No tutorial/lecture room fits a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    schedule[a_id]["room_id"] = room_id
                    occupied.add(room_id)
