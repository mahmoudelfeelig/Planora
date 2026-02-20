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
        self._weights: Dict[str, int] = {}
        self._week_index: Dict[int, int] = {}
        self._activity_room_keys: Dict[int, List[Tuple[int, int, str]]] = {}
        self._room_key_counts: Dict[Tuple[int, int, str], Dict[Any, int]] = {}
        self._group_badness: Dict[int, int] = {}
        self._staff_badness: Dict[int, int] = {}
        self._acts_by_group: Dict[int, List[int]] = {}
        self._acts_by_staff: Dict[int, List[int]] = {}
        self._priority_activity_ids: Set[int] = set()

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

    def _load_soft_weights(self) -> Dict[str, int]:
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
        overrides = getattr(self.inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    weights[str(k)] = int(v)
                except Exception:
                    continue
        return weights

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
        self._weights = self._load_soft_weights()
        self._week_index = {int(w): idx for idx, w in enumerate(weeks)}

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

        # Cache room-consistency keys/counts for fast local room-move deltas.
        self._activity_room_keys = {}
        self._room_key_counts = {}
        self._acts_by_group = {}
        self._acts_by_staff = {}
        for a_id, info in schedule.items():
            c_id = int(info["course_id"])
            kind = str(info["kind"])
            room = info.get("room_id")
            keys: List[Tuple[int, int, str]] = []
            st_id = int(info["staff_id"])
            self._acts_by_staff.setdefault(st_id, []).append(int(a_id))
            for g_id in info["group_ids"]:
                key = (c_id, int(g_id), kind)
                keys.append(key)
                counts = self._room_key_counts.setdefault(key, {})
                counts[room] = int(counts.get(room, 0)) + 1
                self._acts_by_group.setdefault(int(g_id), []).append(int(a_id))
            self._activity_room_keys[a_id] = keys

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
            old_day = info["day"]
            # This activity already contributes to self.staff_day_load.
            # Moving within the same day keeps load unchanged.
            load_day = self.staff_day_load[st_id][w][new_day] + (0 if new_day == old_day else dur)
            if load_day > int(max_per_day):
                return False
        max_per_week = getattr(staff, "max_slots_per_week", None)
        if max_per_week is not None:
            # Week and duration are unchanged by a time move.
            load_week = self.staff_week_load[st_id][w]
            if load_week > int(max_per_week):
                return False

        return True

    def _cluster_can_place_time(self, schedule, cluster: List[int], new_day: str, new_slot: int) -> bool:
        """
        Validate a cluster move in one shot to keep load caps correct.
        """
        inst = self.inst
        day_delta: Dict[Tuple[int, int, str], int] = {}

        for cid in cluster:
            info = schedule[cid]
            w = info["week"]
            dur = info["duration"]
            st_id = info["staff_id"]
            old_day = str(info["day"])
            if new_day != old_day:
                day_delta[(st_id, w, new_day)] = day_delta.get((st_id, w, new_day), 0) + int(dur)
                day_delta[(st_id, w, old_day)] = day_delta.get((st_id, w, old_day), 0) - int(dur)

            if not self._can_place_time(schedule, cid, new_day, new_slot):
                return False

        # Load caps with combined day deltas.
        for (st_id, w, d), delta in day_delta.items():
            staff = inst.staff[st_id]
            max_day = getattr(staff, "max_slots_per_day", None)
            if max_day is not None and self.staff_day_load[st_id][w][d] + int(delta) > int(max_day):
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

        # Update room-consistency counts for this activity.
        keys = self._activity_room_keys.get(a_id, [])
        if old_room != new_room_id:
            for key in keys:
                counts = self._room_key_counts.setdefault(key, {})
                if old_room in counts:
                    counts[old_room] = int(counts[old_room]) - 1
                    if counts[old_room] <= 0:
                        counts.pop(old_room, None)
                counts[new_room_id] = int(counts.get(new_room_id, 0)) + 1

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

    def _group_day_profile(self, g_id: int, week: int, day: str) -> Tuple[int, int, int | None]:
        occ = [1 if g_id in self.group_use[(week, day, s)] else 0 for s in range(self.inst.slots_per_day)]
        load = sum(occ)
        if load <= 0:
            return 0, 0, None
        blocks = 0
        prev = 0
        first_slot = None
        for i, v in enumerate(occ):
            if v == 1 and prev == 0:
                blocks += 1
                if first_slot is None:
                    first_slot = i
            prev = v
        return int(load), int(blocks), first_slot

    def _group_week_penalty(self, g_id: int, week: int) -> int:
        w = self._weights
        days = self.inst.days
        group = self.inst.groups[g_id]
        preferred = int(getattr(group, "preferred_free_days", 0))
        workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]

        day_active: Dict[str, int] = {}
        penalty = 0
        for d in days:
            load, blocks, first_slot = self._group_day_profile(g_id, week, d)
            active = 1 if load > 0 else 0
            day_active[d] = active
            if blocks > 1:
                penalty += int(w["stud_gaps"]) * int(blocks - 1)
            if load == 1:
                penalty += int(w["single_slot"])
            if load == 2:
                penalty += int(w["thin_day"])
            if load > 0 and first_slot is not None and int(first_slot) >= 2:
                penalty += int(w["late_start"])

        free_days = sum(1 - day_active[d] for d in days)
        if free_days < preferred:
            penalty += int(w["stud_free_days"]) * int(preferred - free_days)

        free_mf = sum(1 - day_active[d] for d in workdays)
        if free_mf < preferred:
            penalty += int(w["stud_free_mf"]) * int(preferred - free_mf)

        active_days = sum(day_active[d] for d in days)
        if active_days > 3:
            penalty += int(w["active_days"]) * int(active_days - 3)

        return int(penalty)

    def _group_stability_pair_penalty(self, g_id: int, w_prev: int, w_curr: int) -> int:
        w = self._weights
        penalty = 0
        for d in self.inst.days:
            prev_active = 1 if any(g_id in self.group_use[(w_prev, d, s)] for s in range(self.inst.slots_per_day)) else 0
            curr_active = 1 if any(g_id in self.group_use[(w_curr, d, s)] for s in range(self.inst.slots_per_day)) else 0
            if prev_active != curr_active:
                penalty += int(w["stability"])
        return int(penalty)

    def _staff_week_penalty(self, staff_id: int, week: int) -> int:
        free_days = 0
        for d in self.inst.days:
            active = 1 if any(staff_id in self.staff_use[(week, d, s)] for s in range(self.inst.slots_per_day)) else 0
            free_days += (1 - active)
        if free_days < 1:
            return int(self._weights["staff_free_day"]) * int(1 - free_days)
        return 0

    def _room_key_penalty(self, key: Tuple[int, int, str]) -> int:
        counts = self._room_key_counts.get(key, {})
        if not counts:
            return 0
        if int(counts.get(None, 0)) > 0:
            return 0
        distinct = sum(1 for room_id, c in counts.items() if room_id is not None and int(c) > 0)
        if distinct <= 1:
            return 0
        return int(self._weights["room_consistency"]) * int(distinct - 1)

    def _refresh_entity_badness(self) -> None:
        """
        Recompute which groups/staff are currently most problematic so move
        selection focuses on worst offenders first.
        """
        weeks = list(self.inst.weeks)
        groups = list(self.inst.groups.keys())
        staff_ids = list(self.inst.staff.keys())

        group_badness: Dict[int, int] = {int(g): 0 for g in groups}
        for g_id in groups:
            total = 0
            for w in weeks:
                total += int(self._group_week_penalty(int(g_id), int(w)))
            for idx in range(1, len(weeks)):
                total += int(
                    self._group_stability_pair_penalty(
                        int(g_id), int(weeks[idx - 1]), int(weeks[idx])
                    )
                )
            group_badness[int(g_id)] = int(total)

        staff_badness: Dict[int, int] = {int(s): 0 for s in staff_ids}
        for s_id in staff_ids:
            total = 0
            for w in weeks:
                total += int(self._staff_week_penalty(int(s_id), int(w)))
            staff_badness[int(s_id)] = int(total)

        self._group_badness = group_badness
        self._staff_badness = staff_badness

        sorted_groups = sorted(
            (g for g in group_badness.keys() if int(group_badness[g]) > 0),
            key=lambda g: int(group_badness[g]),
            reverse=True,
        )
        sorted_staff = sorted(
            (s for s in staff_badness.keys() if int(staff_badness[s]) > 0),
            key=lambda s: int(staff_badness[s]),
            reverse=True,
        )

        keep_groups = max(1, len(sorted_groups) // 3) if sorted_groups else 0
        keep_staff = max(1, len(sorted_staff) // 3) if sorted_staff else 0
        bad_groups = set(sorted_groups[:keep_groups])
        bad_staff = set(sorted_staff[:keep_staff])

        priority: Set[int] = set()
        for g_id in bad_groups:
            priority.update(int(a_id) for a_id in self._acts_by_group.get(int(g_id), []))
        for s_id in bad_staff:
            priority.update(int(a_id) for a_id in self._acts_by_staff.get(int(s_id), []))
        self._priority_activity_ids = priority

    def _snapshot_time_local_penalty(self, schedule: Dict[int, Dict[str, Any]], cluster: List[int]) -> int:
        affected_group_weeks: Set[Tuple[int, int]] = set()
        affected_staff_weeks: Set[Tuple[int, int]] = set()
        stability_pairs: Set[Tuple[int, int]] = set()

        weeks = self.inst.weeks
        for cid in cluster:
            info = schedule[cid]
            w = int(info["week"])
            s_id = int(info["staff_id"])
            affected_staff_weeks.add((s_id, w))
            for g_id in info["group_ids"]:
                g_int = int(g_id)
                affected_group_weeks.add((g_int, w))
                idx = self._week_index.get(w, -1)
                if idx > 0:
                    stability_pairs.add((int(weeks[idx - 1]), w))
                if idx >= 0 and idx + 1 < len(weeks):
                    stability_pairs.add((w, int(weeks[idx + 1])))

        total = 0
        for g_id, w in affected_group_weeks:
            total += self._group_week_penalty(g_id, w)
        for s_id, w in affected_staff_weeks:
            total += self._staff_week_penalty(s_id, w)
        for w_prev, w_curr in stability_pairs:
            for g_id, w in affected_group_weeks:
                if w == w_prev or w == w_curr:
                    total += self._group_stability_pair_penalty(g_id, w_prev, w_curr)
        return int(total)

    def _snapshot_room_local_penalty(self, cluster: List[int]) -> int:
        keys: Set[Tuple[int, int, str]] = set()
        for cid in cluster:
            for key in self._activity_room_keys.get(cid, []):
                keys.add(key)
        return int(sum(self._room_key_penalty(key) for key in keys))

    def _time_move_delta(
        self,
        schedule: Dict[int, Dict[str, Any]],
        cluster: List[int],
        new_day: str,
        new_slot: int,
    ) -> int:
        before = self._snapshot_time_local_penalty(schedule, cluster)
        old_pos = {cid: (str(schedule[cid]["day"]), int(schedule[cid]["slot"])) for cid in cluster}
        for cid in cluster:
            self._apply_time_move(schedule, cid, str(new_day), int(new_slot))
        after = self._snapshot_time_local_penalty(schedule, cluster)
        for cid in cluster:
            old_day, old_slot = old_pos[cid]
            self._apply_time_move(schedule, cid, old_day, old_slot)
        return int(after - before)

    def _room_move_delta(
        self,
        schedule: Dict[int, Dict[str, Any]],
        cluster: List[int],
        new_room_id: int,
    ) -> int:
        before = self._snapshot_room_local_penalty(cluster)
        old_rooms = {cid: schedule[cid]["room_id"] for cid in cluster}
        for cid in cluster:
            self._apply_room_move(schedule, cid, int(new_room_id))
        after = self._snapshot_room_local_penalty(cluster)
        for cid in cluster:
            self._apply_room_move(schedule, cid, old_rooms[cid])
        return int(after - before)

    def _estimate_activity_pressure(
        self,
        schedule: Dict[int, Dict[str, Any]],
        a_id: int,
    ) -> int:
        info = schedule[a_id]
        week = int(info["week"])
        day = str(info["day"])
        staff_id = int(info["staff_id"])
        pressure = 0

        for g_id in info["group_ids"]:
            pressure += int(self._group_badness.get(int(g_id), 0))
            load, blocks, first_slot = self._group_day_profile(int(g_id), week, day)
            if blocks > 1:
                pressure += (blocks - 1) * 3
            if load == 1:
                pressure += 4
            if load == 2:
                pressure += 2
            if load > 0 and first_slot is not None and int(first_slot) >= 2:
                pressure += 2
            # Prefer pulling groups toward <=3 active days.
            active_days = 0
            for d in self.inst.days:
                ld, _, _ = self._group_day_profile(int(g_id), week, d)
                if ld > 0:
                    active_days += 1
            if active_days > 3:
                pressure += (active_days - 3) * 2

        pressure += int(self._staff_badness.get(int(staff_id), 0)) * 2
        staff_active_days = 0
        for d in self.inst.days:
            if any(staff_id in self.staff_use[(week, d, s)] for s in range(self.inst.slots_per_day)):
                staff_active_days += 1
        if staff_active_days >= len(self.inst.days):
            pressure += 3
        return int(pressure)

    def _pick_candidate_activity(self, schedule: Dict[int, Dict[str, Any]], activity_ids: List[int]) -> int:
        if len(activity_ids) <= 1:
            return activity_ids[0]
        targeted_pool = [
            int(a_id)
            for a_id in activity_ids
            if int(a_id) in self._priority_activity_ids
        ]
        if targeted_pool and random.random() < 0.9:
            pool = targeted_pool
        else:
            pool = activity_ids
        k = min(24, len(activity_ids))
        sample = random.sample(pool, min(k, len(pool)))
        best = sample[0]
        best_score = -10**9
        for a_id in sample:
            score = self._estimate_activity_pressure(schedule, a_id)
            locked = self._locked.get(a_id, {})
            if isinstance(locked, dict) and "day" in locked and "slot" in locked and "room_id" in locked:
                score -= 1000
            if score > best_score:
                best_score = score
                best = a_id
        return best

    def _try_random_feasible_time_move(
        self,
        schedule: Dict[int, Dict[str, Any]],
        cluster: List[int],
        old_day: str,
        old_slot: int,
        max_tries: int = 12,
    ) -> bool:
        max_dur = max(int(schedule[cid]["duration"]) for cid in cluster)
        for _ in range(int(max_tries)):
            new_day = str(random.choice(self.inst.days))
            new_slot = int(random.randint(0, self.inst.slots_per_day - max_dur))
            if new_day == old_day and int(new_slot) == int(old_slot):
                continue
            if not self._cluster_can_place_time(schedule, cluster, new_day, int(new_slot)):
                continue
            for cid in cluster:
                self._apply_time_move(schedule, cid, new_day, int(new_slot))
            return True
        return False

    def _try_random_feasible_room_move(
        self,
        schedule: Dict[int, Dict[str, Any]],
        cluster: List[int],
        old_room: int | None,
        max_tries: int = 10,
    ) -> bool:
        allowed_sets: List[Set[int]] = []
        for cid in cluster:
            allowed = self._allowed_rooms.get(cid, list(self.inst.rooms.keys()))
            allowed_sets.append(set(int(r) for r in allowed))
        if allowed_sets:
            common_rooms = set.intersection(*allowed_sets)
        else:
            common_rooms = set()
        if old_room in common_rooms:
            common_rooms.remove(old_room)
        if not common_rooms:
            return False
        room_candidates = list(common_rooms)
        random.shuffle(room_candidates)
        tries = 0
        for new_room in room_candidates:
            tries += 1
            if tries > int(max_tries):
                break
            if not all(self._room_ok(schedule, cid, int(new_room)) for cid in cluster):
                continue
            for cid in cluster:
                self._apply_room_move(schedule, cid, int(new_room))
            return True
        return False

    def _diversification_kick(
        self,
        schedule: Dict[int, Dict[str, Any]],
        activity_ids: List[int],
        steps: int,
    ) -> int:
        moved = 0
        if not activity_ids:
            return moved
        for _ in range(max(1, int(steps))):
            a_id = self._pick_candidate_activity(schedule, activity_ids)
            cluster = self._cluster_by_act.get(a_id, [a_id])
            info = schedule[a_id]
            old_day = str(info["day"])
            old_slot = int(info["slot"])
            old_room = info["room_id"]
            # Mostly time diversification; occasional room shake-up.
            if random.random() < 0.75:
                ok = self._try_random_feasible_time_move(
                    schedule, cluster, old_day, old_slot, max_tries=10
                )
            else:
                ok = self._try_random_feasible_room_move(
                    schedule, cluster, old_room, max_tries=8
                )
            if ok:
                moved += 1
        return int(moved)

    def _best_group_week_time_move(
        self,
        schedule: Dict[int, Dict[str, Any]],
        group_id: int,
        week: int,
    ) -> Dict[str, Any] | None:
        """
        Deterministically search feasible time moves for activities involving
        (group_id, week), and return the best local-delta move.
        """
        activity_ids = [
            int(a_id)
            for a_id in self._acts_by_group.get(int(group_id), [])
            if int(schedule.get(int(a_id), {}).get("week", -1)) == int(week)
        ]
        if not activity_ids:
            return None

        seen_clusters: Set[Tuple[int, ...]] = set()
        best_move: Dict[str, Any] | None = None
        for a_id in activity_ids:
            cluster = tuple(sorted(int(cid) for cid in self._cluster_by_act.get(int(a_id), [int(a_id)])))
            if not cluster or cluster in seen_clusters:
                continue
            seen_clusters.add(cluster)
            cluster_ids = list(cluster)
            ref = schedule[int(cluster_ids[0])]
            old_day = str(ref["day"])
            old_slot = int(ref["slot"])
            max_dur = max(int(schedule[int(cid)]["duration"]) for cid in cluster_ids)

            for new_day in self.inst.days:
                for new_slot in range(0, self.inst.slots_per_day - max_dur + 1):
                    if str(new_day) == old_day and int(new_slot) == old_slot:
                        continue
                    if not self._cluster_can_place_time(
                        schedule, cluster_ids, str(new_day), int(new_slot)
                    ):
                        continue
                    delta = int(
                        self._time_move_delta(
                            schedule,
                            cluster_ids,
                            str(new_day),
                            int(new_slot),
                        )
                    )
                    if best_move is None or int(delta) < int(best_move["delta"]):
                        best_move = {
                            "cluster": list(cluster_ids),
                            "choice": (str(new_day), int(new_slot)),
                            "delta": int(delta),
                            "group_id": int(group_id),
                            "week": int(week),
                        }

        return best_move

    def _cluster_time_move_candidates(
        self,
        schedule: Dict[int, Dict[str, Any]],
        cluster_ids: List[int],
        *,
        max_candidates: int = 12,
        max_positive_delta: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Enumerate feasible time relocations for a cluster and return the best
        candidates sorted by local delta (ascending).
        """
        if not cluster_ids:
            return []
        ref = schedule[int(cluster_ids[0])]
        old_day = str(ref["day"])
        old_slot = int(ref["slot"])
        max_dur = max(int(schedule[int(cid)]["duration"]) for cid in cluster_ids)

        cand: List[Dict[str, Any]] = []
        for new_day in self.inst.days:
            for new_slot in range(0, self.inst.slots_per_day - max_dur + 1):
                if str(new_day) == old_day and int(new_slot) == old_slot:
                    continue
                if not self._cluster_can_place_time(
                    schedule, cluster_ids, str(new_day), int(new_slot)
                ):
                    continue
                delta = int(
                    self._time_move_delta(
                        schedule,
                        cluster_ids,
                        str(new_day),
                        int(new_slot),
                    )
                )
                if int(delta) > int(max_positive_delta):
                    continue
                cand.append(
                    {
                        "cluster": [int(cid) for cid in cluster_ids],
                        "choice": (str(new_day), int(new_slot)),
                        "delta": int(delta),
                    }
                )

        cand.sort(key=lambda x: int(x.get("delta", 0)))
        if int(max_candidates) > 0:
            cand = cand[: int(max_candidates)]
        return cand

    def _best_group_week_compound_time_move(
        self,
        schedule: Dict[int, Dict[str, Any]],
        group_id: int,
        week: int,
        max_steps: int = 2,
    ) -> Dict[str, Any] | None:
        """
        Multi-step lookahead move (up to max_steps):
        allows temporary local losses if the cumulative delta across steps is good.
        """
        activity_ids = [
            int(a_id)
            for a_id in self._acts_by_group.get(int(group_id), [])
            if int(schedule.get(int(a_id), {}).get("week", -1)) == int(week)
        ]
        if len(activity_ids) < 2:
            return None
        max_steps = max(2, min(5, int(max_steps)))

        # Focus on thin days first (1-2 slots for this group in this week).
        thin_days: Set[str] = set()
        for d in self.inst.days:
            load, _, _ = self._group_day_profile(int(group_id), int(week), str(d))
            if int(load) in (1, 2):
                thin_days.add(str(d))

        cluster_info: List[Tuple[Tuple[int, ...], int]] = []
        seen: Set[Tuple[int, ...]] = set()
        for a_id in activity_ids:
            cluster = tuple(
                sorted(int(cid) for cid in self._cluster_by_act.get(int(a_id), [int(a_id)]))
            )
            if not cluster or cluster in seen:
                continue
            seen.add(cluster)
            day = str(schedule[int(cluster[0])]["day"])
            if thin_days:
                if day in thin_days:
                    priority = 0
                else:
                    priority = 2
            else:
                priority = 1
            cluster_info.append((cluster, int(priority)))

        if len(cluster_info) < 2:
            return None

        cluster_info.sort(key=lambda t: int(t[1]))
        clusters = [tuple(int(cid) for cid in info[0]) for info in cluster_info]
        best_plan: Dict[str, Any] | None = None

        def _search(
            depth: int,
            running_delta: int,
            steps: List[Dict[str, Any]],
            used_clusters: Set[Tuple[int, ...]],
        ) -> None:
            nonlocal best_plan

            if depth >= 2:
                if best_plan is None or int(running_delta) < int(best_plan["delta"]):
                    best_plan = {
                        "steps": [
                            {
                                "cluster": [int(cid) for cid in step["cluster"]],
                                "choice": (
                                    str(step["choice"][0]),
                                    int(step["choice"][1]),
                                ),
                                "delta": int(step["delta"]),
                            }
                            for step in steps
                        ],
                        "delta": int(running_delta),
                        "group_id": int(group_id),
                        "week": int(week),
                    }
            if depth >= int(max_steps):
                return

            # Strongly bounded branching to keep runtime reasonable.
            remaining = [c for c in clusters if c not in used_clusters]
            if not remaining:
                return
            cluster_limit = 3 if depth == 0 else 2
            remaining = remaining[:cluster_limit]

            for cluster in remaining:
                cand_limit = 4 if depth == 0 else 2
                pos_limit = 14 if depth == 0 else 10
                candidates = self._cluster_time_move_candidates(
                    schedule,
                    list(cluster),
                    max_candidates=int(cand_limit),
                    max_positive_delta=int(pos_limit),
                )
                if not candidates:
                    continue
                for cand in candidates:
                    delta = int(cand.get("delta", 0))

                    # Light pruning once a baseline exists.
                    if (
                        best_plan is not None
                        and depth >= 1
                        and int(running_delta + delta) >= int(best_plan["delta"]) + 14
                    ):
                        continue

                    cluster_ids = [int(cid) for cid in cand["cluster"]]
                    new_day, new_slot = cand["choice"]
                    old_pos = {
                        int(cid): (
                            str(schedule[int(cid)]["day"]),
                            int(schedule[int(cid)]["slot"]),
                        )
                        for cid in cluster_ids
                    }
                    for cid in cluster_ids:
                        self._apply_time_move(
                            schedule,
                            int(cid),
                            str(new_day),
                            int(new_slot),
                        )
                    steps.append(
                        {
                            "cluster": list(cluster_ids),
                            "choice": (str(new_day), int(new_slot)),
                            "delta": int(delta),
                        }
                    )
                    try:
                        _search(
                            depth + 1,
                            int(running_delta + delta),
                            steps,
                            used_clusters | {tuple(cluster_ids)},
                        )
                    finally:
                        steps.pop()
                        for cid in cluster_ids:
                            old_day, old_slot = old_pos[int(cid)]
                            self._apply_time_move(
                                schedule,
                                int(cid),
                                str(old_day),
                                int(old_slot),
                            )

        _search(0, 0, [], set())
        return best_plan

    def _systematic_group_week_sweep(
        self,
        schedule: Dict[int, Dict[str, Any]],
        current_pen: int,
        *,
        max_moves: int,
        max_passes: int,
        start_ts: float,
        max_seconds: float | None = None,
        stop_hook = None,
    ) -> Tuple[int, int]:
        """
        Deterministic pre-pass:
        iterate weeks and high-penalty groups, applying best improving single
        or compound (up-to-five-step) time moves.
        """
        moves_applied = 0
        weeks = [int(w) for w in self.inst.weeks]
        if not weeks or int(max_moves) <= 0:
            return int(current_pen), 0

        for _ in range(max(1, int(max_passes))):
            if moves_applied >= int(max_moves):
                break
            if stop_hook is not None:
                try:
                    if bool(stop_hook()):
                        break
                except Exception:
                    pass
            if max_seconds is not None and (time.perf_counter() - start_ts) >= float(max_seconds):
                break

            self._refresh_entity_badness()
            groups = sorted(
                [int(g) for g in self.inst.groups.keys()],
                key=lambda g: int(self._group_badness.get(int(g), 0)),
                reverse=True,
            )
            improved_in_pass = False

            for week in weeks:
                if moves_applied >= int(max_moves):
                    break
                for group_id in groups:
                    if moves_applied >= int(max_moves):
                        break
                    if stop_hook is not None:
                        try:
                            if bool(stop_hook()):
                                break
                        except Exception:
                            pass
                    if max_seconds is not None and (time.perf_counter() - start_ts) >= float(max_seconds):
                        break

                    single_move = self._best_group_week_time_move(
                        schedule,
                        int(group_id),
                        int(week),
                    )
                    compound_move = self._best_group_week_compound_time_move(
                        schedule,
                        int(group_id),
                        int(week),
                        max_steps=2,
                    )
                    move: Dict[str, Any] | None = None
                    if single_move is not None and compound_move is not None:
                        move = (
                            compound_move
                            if int(compound_move.get("delta", 0)) < int(single_move.get("delta", 0))
                            else single_move
                        )
                    else:
                        move = single_move if single_move is not None else compound_move

                    if not move:
                        continue
                    delta = int(move.get("delta", 0))
                    if delta >= 0:
                        continue

                    if "steps" in move:
                        for step in list(move.get("steps", [])):
                            cluster = [int(cid) for cid in step["cluster"]]
                            new_day, new_slot = step["choice"]
                            for cid in cluster:
                                self._apply_time_move(
                                    schedule, int(cid), str(new_day), int(new_slot)
                                )
                    else:
                        cluster = [int(cid) for cid in move["cluster"]]
                        new_day, new_slot = move["choice"]
                        for cid in cluster:
                            self._apply_time_move(
                                schedule, int(cid), str(new_day), int(new_slot)
                            )
                    current_pen += int(delta)
                    moves_applied += 1
                    improved_in_pass = True

                    # Periodic refresh keeps the "worst group first" ordering aligned.
                    if moves_applied % 6 == 0:
                        self._refresh_entity_badness()

                if max_seconds is not None and (time.perf_counter() - start_ts) >= float(max_seconds):
                    break

            if not improved_in_pass:
                break

        return int(current_pen), int(moves_applied)

    def improve(
        self,
        schedule: Dict[int, Dict[str, Any]],
        iterations: int = 300,
        start_temp: float = 5.0,
        end_temp: float = 0.1,
        max_seconds: float | None = None,
        progress_every: int = 1000,
        progress_hook = None,
        stop_hook = None,
        restart_after: int | None = None,
        max_restarts: int | None = None,
        kick_steps: int | None = None,
        probe_activities: int | None = None,
    ):
        current = {a_id: info.copy() for a_id, info in schedule.items()}
        best = {a_id: info.copy() for a_id, info in schedule.items()}

        self._build_state(current)
        current_pen = self.compute_soft_penalty(current)
        best_pen = current_pen

        activity_ids = list(current.keys())
        start_ts = time.perf_counter()
        recompute_every = 250
        badness_refresh_every = 40
        if restart_after is None:
            restart_after = max(120, int(iterations) // 8)
        if max_restarts is None:
            max_restarts = 4
        if kick_steps is None:
            kick_steps = max(2, min(14, max(1, len(activity_ids) // 20)))
        if probe_activities is None:
            probe_activities = max(4, min(14, len(activity_ids) // 150 + 4))
        no_improve_iters = 0
        restarts_used = 0
        self._refresh_entity_badness()

        # Group-first deterministic pass:
        # week-by-week scan and best-delta relocations for high-penalty groups.
        systematic_budget = max(4, min(220, int(iterations) // 2))
        systematic_seconds = None
        if max_seconds is not None:
            # Reserve most of the budget for stochastic improvement.
            systematic_seconds = max(0.35, min(3.0, float(max_seconds) * 0.35))
        current_pen, systematic_moves = self._systematic_group_week_sweep(
            current,
            int(current_pen),
            max_moves=int(systematic_budget),
            max_passes=3,
            start_ts=float(start_ts),
            max_seconds=systematic_seconds,
            stop_hook=stop_hook,
        )
        if int(current_pen) < int(best_pen):
            best_pen = int(current_pen)
            best = {a_id: info.copy() for a_id, info in current.items()}
            no_improve_iters = 0
        if int(systematic_moves) > 0:
            self._refresh_entity_badness()

        for it in range(iterations):
            if stop_hook is not None:
                try:
                    if bool(stop_hook()):
                        break
                except Exception:
                    pass
            # exponential cooling
            if start_temp <= end_temp:
                temp = end_temp
            else:
                frac = it / max(1, iterations - 1)
                temp = start_temp * ((end_temp / start_temp) ** frac)

            if max_seconds is not None and (time.perf_counter() - start_ts) >= max_seconds:
                break

            # Multi-start restart: when plateauing, restart from elite best and diversify.
            if (
                int(no_improve_iters) >= int(restart_after)
                and int(restarts_used) < int(max_restarts)
            ):
                if max_seconds is not None and (time.perf_counter() - start_ts) >= max_seconds:
                    break
                current = {a_id: info.copy() for a_id, info in best.items()}
                self._build_state(current)
                kicked = self._diversification_kick(
                    current,
                    activity_ids,
                    int(kick_steps) + int(restarts_used),
                )
                if kicked > 0:
                    current_pen = int(self.compute_soft_penalty(current))
                else:
                    current_pen = int(best_pen)
                no_improve_iters = 0
                restarts_used += 1
                self._refresh_entity_badness()

            # Probe multiple high-pressure activities and execute the best available move.
            probe_ids: List[int] = []
            seen_ids: Set[int] = set()
            probe_target = max(1, int(probe_activities))
            for _ in range(max(probe_target * 2, 1)):
                cand = int(self._pick_candidate_activity(current, activity_ids))
                if cand in seen_ids:
                    continue
                seen_ids.add(cand)
                probe_ids.append(cand)
                if len(probe_ids) >= probe_target:
                    break
            if not probe_ids:
                probe_ids = [int(self._pick_candidate_activity(current, activity_ids))]

            best_move: Dict[str, Any] | None = None
            for a_id in probe_ids:
                cluster = self._cluster_by_act.get(a_id, [a_id])
                info = current[a_id]
                old_day = str(info["day"])
                old_slot = int(info["slot"])
                old_room = info["room_id"]

                max_dur = max(int(current[cid]["duration"]) for cid in cluster)
                candidates: List[Tuple[str, int]] = []
                for d in self.inst.days:
                    for s in range(0, self.inst.slots_per_day - max_dur + 1):
                        if d == old_day and int(s) == int(old_slot):
                            continue
                        candidates.append((str(d), int(s)))
                random.shuffle(candidates)

                best_time_choice: Tuple[str, int] | None = None
                best_time_delta: int | None = None
                for new_day, new_slot in candidates:
                    if not self._cluster_can_place_time(current, cluster, new_day, new_slot):
                        continue
                    delta = int(self._time_move_delta(current, cluster, new_day, new_slot))
                    if best_time_delta is None or int(delta) < int(best_time_delta):
                        best_time_delta = int(delta)
                        best_time_choice = (str(new_day), int(new_slot))

                if best_time_choice is not None and best_time_delta is not None:
                    move = {
                        "type": "time",
                        "cluster": list(cluster),
                        "choice": best_time_choice,
                        "delta": int(best_time_delta),
                    }
                    if best_move is None or int(move["delta"]) < int(best_move["delta"]):
                        best_move = move

                allowed_sets: List[Set[int]] = []
                for cid in cluster:
                    allowed = self._allowed_rooms.get(cid, list(self.inst.rooms.keys()))
                    allowed_sets.append(set(int(r) for r in allowed))
                common_rooms = set.intersection(*allowed_sets) if allowed_sets else set()
                if old_room in common_rooms:
                    common_rooms.remove(old_room)
                room_candidates = list(common_rooms)
                random.shuffle(room_candidates)

                best_room: int | None = None
                best_room_delta: int | None = None
                for new_room in room_candidates:
                    if not all(self._room_ok(current, cid, int(new_room)) for cid in cluster):
                        continue
                    delta = int(self._room_move_delta(current, cluster, int(new_room)))
                    if best_room_delta is None or int(delta) < int(best_room_delta):
                        best_room_delta = int(delta)
                        best_room = int(new_room)

                if best_room is not None and best_room_delta is not None:
                    move = {
                        "type": "room",
                        "cluster": list(cluster),
                        "choice": int(best_room),
                        "delta": int(best_room_delta),
                    }
                    if best_move is None or int(move["delta"]) < int(best_move["delta"]):
                        best_move = move

            moved = False
            accept = False
            if best_move is not None:
                best_delta = int(best_move["delta"])
                accept = best_delta <= 0 or (
                    temp > 0 and random.random() < math.exp(-float(best_delta) / float(temp))
                )
                if accept:
                    cluster = list(best_move["cluster"])
                    if str(best_move["type"]) == "time":
                        new_day, new_slot = best_move["choice"]
                        for cid in cluster:
                            self._apply_time_move(current, cid, str(new_day), int(new_slot))
                    else:
                        new_room = int(best_move["choice"])
                        for cid in cluster:
                            self._apply_room_move(current, cid, int(new_room))
                    current_pen += int(best_delta)
                    moved = True

            if not moved:
                no_improve_iters += 1
                if progress_hook and progress_every > 0 and (it + 1) % progress_every == 0:
                    try:
                        progress_hook(
                            it + 1,
                            best_pen,
                            current_pen,
                            current_schedule=current,
                            best_schedule=best,
                            moved=False,
                            accepted=False,
                            elapsed_seconds=float(time.perf_counter() - start_ts),
                            total_iterations=int(iterations),
                        )
                    except TypeError:
                        try:
                            progress_hook(it + 1, best_pen, current_pen)
                        except Exception:
                            pass
                    except Exception:
                        pass
                continue

            if current_pen < best_pen:
                best_pen = int(current_pen)
                best = {a_id: info.copy() for a_id, info in current.items()}
                no_improve_iters = 0
            else:
                no_improve_iters += 1

            if (it + 1) % int(badness_refresh_every) == 0:
                self._refresh_entity_badness()

            # Periodic exact recomputation keeps the incremental tracker robust.
            if (it + 1) % int(recompute_every) == 0:
                current_pen = int(self.compute_soft_penalty(current))
                if current_pen < best_pen:
                    best_pen = int(current_pen)
                    best = {a_id: info.copy() for a_id, info in current.items()}
                    no_improve_iters = 0
                self._refresh_entity_badness()

            if progress_hook and progress_every > 0 and (it + 1) % progress_every == 0:
                try:
                    progress_hook(
                        it + 1,
                        best_pen,
                        current_pen,
                        current_schedule=current,
                        best_schedule=best,
                        moved=bool(moved),
                        accepted=bool(accept) if moved else False,
                        elapsed_seconds=float(time.perf_counter() - start_ts),
                        total_iterations=int(iterations),
                    )
                except TypeError:
                    # Backward compatibility for legacy hooks with signature (it, best, cur).
                    try:
                        progress_hook(it + 1, best_pen, current_pen)
                    except Exception:
                        pass
                except Exception:
                    # keep search running even if the hook fails
                    pass

        return best
