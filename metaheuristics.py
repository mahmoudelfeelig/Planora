from __future__ import annotations
from typing import Dict, Any, Tuple
import random
import math

from domain import Instance


class LocalSearchImprover:
    """
    Local search on a feasible CP-SAT schedule.

    Keeps feasibility by checking resource occupancy when proposing moves.
    Optimizes a soft penalty capturing free days, gaps, heavy days, early starts,
    week-to-week stability, and room consistency.
    Daily load caps are ignored here by specification; weekly caps are enforced in CP.
    """

    def __init__(self, inst: Instance):
        self.inst = inst

    # ---------- state ----------

    def _build_state(self, schedule: Dict[int, Dict[str, Any]]):
        inst = self.inst
        days = inst.days
        weeks = inst.weeks
        slots = inst.slots_per_day

        self.room_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}
        self.staff_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}
        self.group_use: Dict[Tuple[int, str, int], Dict[int, int]] = {}

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

        # respect staff day availability
        staff = inst.staff[st_id]
        if new_day not in staff.available_days:
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

        return True

    def _room_ok(self, schedule, a_id, new_room_id) -> bool:
        inst = self.inst
        act = inst.activities[a_id]
        info = schedule[a_id]
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]

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

        W_STUD_FREE_DAYS = 10
        W_STUD_FREE_MF = 5
        W_STUD_GAPS = 5
        W_STAFF_FREE_DAYS = 6
        W_ACTIVE_DAYS = 3
        W_EARLY_START = 2
        W_BALANCE = 2
        W_STABILITY = 1
        W_ROOM_CONSISTENCY = 1

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

        # gaps, heavy days, early-start discourager
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
                    if load > 3:
                        penalty += W_BALANCE * (load - 3)
                    if occ and occ[0] == 1 and any(occ[s] == 1 for s in range(1, slots)):
                        penalty += W_EARLY_START

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
    ):
        current = {a_id: info.copy() for a_id, info in schedule.items()}
        best = {a_id: info.copy() for a_id, info in schedule.items()}

        self._build_state(current)
        current_pen = self.compute_soft_penalty(current)
        best_pen = current_pen

        activity_ids = list(current.keys())
        rooms = list(self.inst.rooms.keys())

        for it in range(iterations):
            # exponential cooling
            if start_temp <= end_temp:
                temp = end_temp
            else:
                frac = it / max(1, iterations - 1)
                temp = start_temp * ((end_temp / start_temp) ** frac)

            a_id = random.choice(activity_ids)
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
                    if self._can_place_time(current, a_id, new_day, new_slot):
                        self._apply_time_move(current, a_id, new_day, new_slot)
                        moved = True
            else:
                attempts = 0
                while attempts < 10 and not moved:
                    attempts += 1
                    new_room = random.choice(rooms)
                    if new_room == old_room:
                        continue
                    if self._room_ok(current, a_id, new_room):
                        self._apply_room_move(current, a_id, new_room)
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
                    self._apply_time_move(current, a_id, old_day, old_slot)
                else:
                    self._apply_room_move(current, a_id, old_room)

        return best
