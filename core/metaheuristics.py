from __future__ import annotations
from typing import Dict, Any, Tuple, List, Set
import random
import math
import time

from utils.domain import Instance


class LocalSearchImprover:
    """
    Local search on a feasible CP-SAT schedule.

    Keeps feasibility by checking resource occupancy when proposing moves.
    Optimizes a soft penalty capturing free days, gaps, thin/single days, late starts,
    active-day minimization, week-to-week stability, and room consistency.
    Daily load caps are ignored here by specification; weekly caps are enforced in CP.
    """

    def __init__(self, inst: Instance):
        self.inst = inst
        self._locked: Dict[int, Dict[str, Any]] = {}
        self._allowed_rooms: Dict[int, List[int]] = {}
        self._cluster_by_act: Dict[int, List[int]] = {}

    # ---------- state ----------

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
                else:
                    rooms = [r_id for r_id in lab_candidates if inst.rooms[r_id].capacity >= need]
            elif act.kind == "TUT":
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("TUTORIAL", "LECTURE") and r.capacity >= need]
            else:  # LEC
                rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE" and r.capacity >= need]

            if rooms:
                self._allowed_rooms[a_id] = rooms

    def _compute_clusters(self) -> None:
        """
        Build activity clusters (same logic as solver) to keep equal starts together.
        """
        inst = self.inst
        by_ckwg: Dict[Tuple[int, str, int, int], List[int]] = {}
        for a_id, a in inst.activities.items():
            if len(a.group_ids) == 1:
                by_ckwg.setdefault((a.course_id, a.kind, a.week, a.group_ids[0]), []).append(a_id)

        clusters: List[List[int]] = []
        for c_id, course in inst.courses.items():
            shared = getattr(course, "share_lecture_group_ids", None)
            if not shared:
                continue
            shared_set = set(shared)
            by_week: Dict[int, List[int]] = {}
            for (cc, kind, week, g), ids in by_ckwg.items():
                if cc != c_id or kind != "LEC" or g not in shared_set:
                    continue
                by_week.setdefault(week, []).extend(ids)
            for ids in by_week.values():
                if len(ids) >= 2:
                    clusters.append(sorted(ids))

        key_map: Dict[Tuple[str, int, str], List[int]] = {}
        for a_id, a in inst.activities.items():
            key = getattr(a, "cluster_key", None)
            if key:
                key_map.setdefault((str(key), a.week, a.kind), []).append(a_id)
        for ids in key_map.values():
            if len(ids) >= 2:
                clusters.append(sorted(ids))

        for cluster in clusters:
            for a_id in cluster:
                self._cluster_by_act[a_id] = cluster

    def _build_state(self, schedule: Dict[int, Dict[str, Any]]):
        inst = self.inst
        days = inst.days
        weeks = inst.weeks
        slots = inst.slots_per_day

        self.room_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}
        self.staff_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}
        self.group_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}
        self._locked = getattr(inst, "locked_activities", {}) or {}
        self._allowed_rooms = {}
        self._cluster_by_act = {}
        self._compute_allowed_rooms()
        self._compute_clusters()

        for w in weeks:
            for d in days:
                for s in range(slots):
                    key = (w, d, s)
                    self.room_use[key] = {}
                    self.staff_use[key] = {}
                    self.group_use[key] = {}

        self.staff_day_load: Dict[int, Dict[int, Dict[str, int]]] = {}
        self.staff_week_load: Dict[int, Dict[int, int]] = {}

        for s_id in inst.staff.keys():
            self.staff_day_load[s_id] = {w: {d: 0 for d in days} for w in weeks}
            self.staff_week_load[s_id] = {w: 0 for w in weeks}

        for a_id, info in schedule.items():
            act = inst.activities[a_id]
            w = info["week"]; d = info["day"]
            s0 = info["slot"]; dur = info["duration"]
            r = info["room_id"]; st_id = info["staff_id"]
            for ds in range(dur):
                s = s0 + ds
                key = (w, d, s)
                if r is not None:
                    self.room_use[key][r] = a_id
                self.staff_use[key][st_id] = a_id
                for g_id in info["group_ids"]:
                    self.group_use[key][g_id] = a_id
            self.staff_week_load[st_id][act.week] += dur
            self.staff_day_load[st_id][act.week][d] += dur

    # ---------- feasibility checks ----------

    def _is_block_staff(self, staff) -> bool:
        return bool(getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False) or getattr(staff, "is_block_prof", False))

    def _room_available(self, room_id: int, day: str, start_slot: int, dur: int) -> bool:
        room = self.inst.rooms[room_id]
        avail = getattr(room, "availability", None)
        if avail is None:
            return True
        pairs = getattr(room, "availability", None)
        if isinstance(pairs, set):
            for off in range(dur):
                if (day, start_slot + off) not in pairs:
                    return False
        return True

    def _can_place_time(self, schedule, a_id, new_day, new_slot) -> bool:
        inst = self.inst
        info = schedule[a_id]
        act = inst.activities[a_id]
        w = info["week"]
        dur = info["duration"]
        r = info["room_id"]
        st_id = info["staff_id"]

        if new_slot < 0 or new_slot + dur > inst.slots_per_day:
            return False

        locked = self._locked.get(a_id, {})
        if isinstance(locked, dict) and "day" in locked and "slot" in locked:
            if locked["day"] != new_day or int(locked["slot"]) != int(new_slot):
                return False

        # respect staff day availability
        staff = inst.staff[st_id]
        if getattr(staff, "blocks_only", False):
            return False  # avoid breaking block-only contiguity rule
        if new_day not in staff.available_days:
            return False

        # soft block staff: cap distinct teaching days to 2
        if self._is_block_staff(staff):
            used_days = {d for d, load in self.staff_day_load[st_id][w].items() if load > 0}
            if new_day not in used_days and len(used_days) >= 2:
                return False

        # check instantaneous occupancy
        for ds in range(dur):
            s = new_slot + ds
            key = (w, new_day, s)

            if r is not None and r in self.room_use[key] and self.room_use[key][r] != a_id:
                return False
            if st_id in self.staff_use[key] and self.staff_use[key][st_id] != a_id:
                return False
            for g_id in info["group_ids"]:
                if g_id in self.group_use[key] and self.group_use[key][g_id] != a_id:
                    return False

        # daily and weekly load caps
        max_per_day = getattr(staff, "max_slots_per_day", None)
        if max_per_day is not None:
            load_day = self.staff_day_load[st_id][w][new_day] + dur
            if load_day > int(max_per_day):
                return False
        max_per_week = getattr(staff, "max_slots_per_week", None)
        if max_per_week is not None:
            load_week = self.staff_week_load[st_id][w] + dur
            if load_week > int(max_per_week):
                return False

        return True

    def _cluster_can_place_time(self, schedule, cluster: List[int], new_day: str, new_slot: int) -> bool:
        """
        Validate a cluster move in one shot to keep load caps correct.
        """
        inst = self.inst
        added_week: Dict[Tuple[int, int], int] = {}
        added_day: Dict[Tuple[int, int, str], int] = {}

        for cid in cluster:
            info = schedule[cid]
            w = info["week"]
            dur = info["duration"]
            st_id = info["staff_id"]
            added_week[(st_id, w)] = added_week.get((st_id, w), 0) + dur
            added_day[(st_id, w, new_day)] = added_day.get((st_id, w, new_day), 0) + dur

            if not self._can_place_time(schedule, cid, new_day, new_slot):
                return False

        # Load caps with combined deltas
        for (st_id, w), add in added_week.items():
            staff = inst.staff[st_id]
            max_week = getattr(staff, "max_slots_per_week", None)
            if max_week is not None and self.staff_week_load[st_id][w] + add > int(max_week):
                return False

        for (st_id, w, d), add in added_day.items():
            staff = inst.staff[st_id]
            max_day = getattr(staff, "max_slots_per_day", None)
            if max_day is not None and self.staff_day_load[st_id][w][d] + add > int(max_day):
                return False

        return True

    def _room_ok(self, schedule, a_id, new_room_id) -> bool:
        inst = self.inst
        act = inst.activities[a_id]
        info = schedule[a_id]
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]

        locked = self._locked.get(a_id, {})
        if isinstance(locked, dict) and "room_id" in locked and int(locked["room_id"]) != int(new_room_id):
            return False

        if a_id in self._allowed_rooms and new_room_id not in self._allowed_rooms[a_id]:
            return False
        if a_id not in self._allowed_rooms:
            need = sum(inst.groups[g].size for g in act.group_ids if g in inst.groups)
            if inst.rooms[new_room_id].capacity < need:
                return False

        room = inst.rooms[new_room_id]
        if act.kind == "LAB":
            if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                return False
            tag = getattr(act, "requires_specialization", None)
            if tag:
                tags = getattr(room, "specialization_tags", []) or []
                if room.room_type != "SPECIALIZED_LAB" or tag not in tags:
                    return False
        elif act.kind == "LEC":
            if room.room_type != "LECTURE":
                return False
        else:  # TUT
            if room.room_type not in ("TUTORIAL", "LECTURE"):
                return False

        if not self._room_available(new_room_id, d, s0, dur):
            return False

        for ds in range(dur):
            s = s0 + ds
            key = (w, d, s)
            if new_room_id in self.room_use[key] and self.room_use[key][new_room_id] != a_id:
                return False

        return True

    # ---------- apply ----------

    def _apply_time_move(self, schedule, a_id, new_day, new_slot):
        info = schedule[a_id]
        w = info["week"]
        old_day = info["day"]; old_slot = info["slot"]
        dur = info["duration"]; r = info["room_id"]
        st_id = info["staff_id"]; groups = info["group_ids"]

        for ds in range(dur):
            s = old_slot + ds
            key = (w, old_day, s)
            if r is not None:
                self.room_use[key].pop(r, None)
            self.staff_use[key].pop(st_id, None)
            for g in groups:
                self.group_use[key].pop(g, None)
        self.staff_day_load[st_id][w][old_day] -= dur

        for ds in range(dur):
            s = new_slot + ds
            key = (w, new_day, s)
            if r is not None:
                self.room_use[key][r] = a_id
            self.staff_use[key][st_id] = a_id
            for g in groups:
                self.group_use[key][g] = a_id
        self.staff_day_load[st_id][w][new_day] += dur

        info["day"] = new_day
        info["slot"] = new_slot

    def _apply_room_move(self, schedule, a_id, new_room_id):
        info = schedule[a_id]
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]
        old_room = info["room_id"]

        if old_room is not None:
            for ds in range(dur):
                s = s0 + ds
                key = (w, d, s)
                self.room_use[key].pop(old_room, None)

        for ds in range(dur):
            s = s0 + ds
            key = (w, d, s)
            self.room_use[key][new_room_id] = a_id

        info["room_id"] = new_room_id

    # ---------- penalty ----------

    def compute_soft_penalty(self, schedule: Dict[int, Dict[str, Any]]) -> int:
        inst = self.inst
        days = inst.days
        weeks = inst.weeks
        slots = inst.slots_per_day

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
        }
        overrides = getattr(inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    weights[str(k)] = int(v)
                except Exception:
                    continue

        W_STUD_FREE_DAYS = weights["stud_free_days"]
        W_STUD_FREE_MF = weights["stud_free_mf"]
        W_STUD_GAPS = weights["stud_gaps"]
        W_STAFF_FREE_DAYS = weights["staff_free_day"]
        W_ACTIVE_DAYS = weights["active_days"]
        W_LATE_START = weights["late_start"]
        W_THIN_DAY = weights["thin_day"]
        W_STABILITY = weights["stability"]
        W_ROOM_CONSISTENCY = weights["room_consistency"]
        W_SINGLE_SLOT = weights["single_slot"]

        penalty = 0

        group_occ = {(g, w, d, s): 0 for g in inst.groups for w in weeks for d in days for s in range(slots)}
        staff_occ = {(s_id, w, d, s): 0 for s_id in inst.staff for w in weeks for d in days for s in range(slots)}

        for a_id, info in schedule.items():
            w = info["week"]; d = info["day"]
            s0 = info["slot"]; dur = info["duration"]
            st_id = info["staff_id"]
            for ds in range(dur):
                s = s0 + ds
                if 0 <= s < slots:
                    staff_occ[(st_id, w, d, s)] = 1
                    for g_id in info["group_ids"]:
                        group_occ[(g_id, w, d, s)] = 1

        group_day_active = {(g, w, d): int(any(group_occ[(g, w, d, s)] for s in range(slots)))
                            for g in inst.groups for w in weeks for d in days}
        staff_day_active = {(s_id, w, d): int(any(staff_occ[(s_id, w, d, s)] for s in range(slots)))
                            for s_id in inst.staff for w in weeks for d in days}

        # student free days and Mon–Fri free days
        for g_id, g in inst.groups.items():
            for w in weeks:
                free_days = sum(1 - group_day_active[(g_id, w, d)] for d in days)
                want = getattr(g, "preferred_free_days", 0)
                if free_days < want:
                    penalty += W_STUD_FREE_DAYS * (want - free_days)

        workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]
        for g_id, g in inst.groups.items():
            for w in weeks:
                free_mf = sum(1 - group_day_active[(g_id, w, d)] for d in workdays)
                want = getattr(g, "preferred_free_days", 0)
                if free_mf < want:
                    penalty += W_STUD_FREE_MF * (want - free_mf)

        # gaps, day shape, late start discourager
        for g_id in inst.groups.keys():
            for w in weeks:
                for d in days:
                    occ = [group_occ[(g_id, w, d, s)] for s in range(slots)]
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
                        penalty += W_STUD_GAPS * (blocks - 1)
                    if load == 1:
                        penalty += W_SINGLE_SLOT
                    if load == 2:
                        penalty += W_THIN_DAY
                    if load > 0:
                        first_slot = next((i for i, v in enumerate(occ) if v == 1), None)
                        if first_slot is not None and first_slot >= 2:
                            penalty += W_LATE_START

        # staff free day
        for s_id in inst.staff.keys():
            for w in weeks:
                free_days = sum(1 - staff_day_active[(s_id, w, d)] for d in days)
                if free_days < 1:
                    penalty += W_STAFF_FREE_DAYS * (1 - free_days)

        # minimize active days for groups
        for g_id in inst.groups.keys():
            for w in weeks:
                active_days = sum(group_day_active[(g_id, w, d)] for d in days)
                if active_days > 3:
                    penalty += W_ACTIVE_DAYS * (active_days - 3)

        # week-to-week stability of day-activity pattern
        for g_id in inst.groups.keys():
            for wi in range(1, len(weeks)):
                w_prev = weeks[wi - 1]
                w_curr = weeks[wi]
                for d in days:
                    if group_day_active[(g_id, w_prev, d)] != group_day_active[(g_id, w_curr, d)]:
                        penalty += W_STABILITY

        # room consistency per (course, group, kind)
        key_to_rooms = {}
        for a_id, info in schedule.items():
            c = info["course_id"]; kind = info["kind"]; r = info["room_id"]
            for g_id in info["group_ids"]:
                key = (c, g_id, kind)
                key_to_rooms.setdefault(key, set()).add(r)
        for key, rooms in key_to_rooms.items():
            if None in rooms:
                continue
            if len(rooms) > 1:
                penalty += W_ROOM_CONSISTENCY * (len(rooms) - 1)

        return penalty

    # ---------- search ----------

    def improve(
        self,
        schedule: Dict[int, Dict[str, Any]],
        iterations: int = 300,
        start_temp: float = 5.0,
        end_temp: float = 0.1,
        max_seconds: float | None = None,
        progress_every: int = 1000,
        progress_hook = None,
    ):
        current = {a_id: info.copy() for a_id, info in schedule.items()}
        best = {a_id: info.copy() for a_id, info in schedule.items()}

        self._build_state(current)
        current_pen = self.compute_soft_penalty(current)
        best_pen = current_pen

        activity_ids = list(current.keys())
        rooms = list(self.inst.rooms.keys())
        start_ts = time.perf_counter()

        for it in range(iterations):
            # exponential cooling
            if start_temp <= end_temp:
                temp = end_temp
            else:
                frac = it / max(1, iterations - 1)
                temp = start_temp * ((end_temp / start_temp) ** frac)

            if max_seconds is not None and (time.perf_counter() - start_ts) >= max_seconds:
                break

            a_id = random.choice(activity_ids)
            cluster = self._cluster_by_act.get(a_id, [a_id])
            move_type = random.choice(["time", "room"])

            info = current[a_id]
            old_day = info["day"]; old_slot = info["slot"]; old_room = info["room_id"]

            moved = False
            if move_type == "time":
                attempts = 0
                while attempts < 15 and not moved:
                    attempts += 1
                    new_day = random.choice(self.inst.days)
                    dur = info["duration"]
                    new_slot = random.randint(0, self.inst.slots_per_day - dur)
                    if new_day == old_day and new_slot == old_slot:
                        continue
                    if self._cluster_can_place_time(current, cluster, new_day, new_slot):
                        for cid in cluster:
                            self._apply_time_move(current, cid, new_day, new_slot)
                        moved = True
            else:
                attempts = 0
                while attempts < 10 and not moved:
                    attempts += 1
                    new_room = random.choice(rooms)
                    if new_room == old_room:
                        continue
                    if all(self._room_ok(current, cid, new_room) for cid in cluster):
                        for cid in cluster:
                            self._apply_room_move(current, cid, new_room)
                        moved = True

            if not moved:
                continue

            new_pen = self.compute_soft_penalty(current)
            delta = new_pen - current_pen
            accept = delta <= 0 or (temp > 0 and random.random() < math.exp(-delta / temp))

            if accept:
                current_pen = new_pen
                if new_pen < best_pen:
                    best_pen = new_pen
                    best = {a_id: info.copy() for a_id, info in current.items()}
            else:
                if move_type == "time":
                    for cid in cluster:
                        self._apply_time_move(current, cid, old_day, old_slot)
                else:
                    for cid in cluster:
                        self._apply_room_move(current, cid, old_room)

            if progress_hook and progress_every > 0 and (it + 1) % progress_every == 0:
                try:
                    progress_hook(it + 1, best_pen, current_pen)
                except Exception:
                    # keep search running even if the hook fails
                    pass

        return best
