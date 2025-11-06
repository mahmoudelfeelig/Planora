from typing import Dict, Any
from domain import Instance
from solver_cp_sat import TimetableSolver


class LocalSearchImprover:
    """
    Optional metaheuristic layer.

    Currently only provides a rough penalty evaluator.
    You can extend with real neighbor moves and a search loop.
    """

    def __init__(self, inst: Instance, solver: TimetableSolver):
        self.inst = inst
        self.solver = solver

    def compute_soft_penalty(self, schedule: Dict[int, Dict[str, Any]]) -> int:
        days = self.inst.days
        weeks = self.inst.weeks
        slots_per_day = self.inst.slots_per_day

        # build group occupancy
        group_occ = {}
        for g_id in self.inst.groups.keys():
            for w in weeks:
                for d in days:
                    for s in range(slots_per_day):
                        group_occ[g_id, w, d, s] = 0

        for a_id, info in schedule.items():
            w = info["week"]
            d = info["day"]
            s = info["slot"]
            dur = info["duration"]
            for g_id in info["group_ids"]:
                for ds in range(dur):
                    if 0 <= s + ds < slots_per_day:
                        group_occ[g_id, w, d, s + ds] = 1

        penalty = 0

        # free days (any)
        for g_id, g in self.inst.groups.items():
            for w in weeks:
                active_days = 0
                for d in days:
                    if any(group_occ[g_id, w, d, s] for s in range(slots_per_day)):
                        active_days += 1
                free_days = len(days) - active_days
                if free_days < g.preferred_free_days:
                    penalty += 10 * (g.preferred_free_days - free_days)

        # gaps
        for g_id in self.inst.groups.keys():
            for w in weeks:
                for d in days:
                    occ = [group_occ[g_id, w, d, s] for s in range(slots_per_day)]
                    blocks = 0
                    prev = 0
                    for v in occ:
                        if v == 1 and prev == 0:
                            blocks += 1
                        prev = v
                    if blocks > 1:
                        penalty += 5 * (blocks - 1)

        # early starts
        for g_id in self.inst.groups.keys():
            for w in weeks:
                for d in days:
                    occ = [group_occ[g_id, w, d, s] for s in range(slots_per_day)]
                    if occ[0] == 1 and any(occ[s] == 1 for s in range(1, slots_per_day)):
                        penalty += 2

        return penalty

    def improve(self, schedule: Dict[int, Dict[str, Any]], iterations: int = 0):
        # placeholder; returns the input unchanged for now
        return schedule
