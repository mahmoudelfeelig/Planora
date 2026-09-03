from __future__ import annotations

from typing import Any

from core.partitioned_solver import PartitionedTimetableSolver
from core.solver_cp_sat import TimetableSolver


def build_timetable_solver(
    inst: Any,
    *,
    room_mode: str,
    use_objective: bool,
) -> TimetableSolver | PartitionedTimetableSolver:
    mode = str(room_mode)
    if mode == "partitioned":
        return PartitionedTimetableSolver(inst, use_objective=bool(use_objective))
    return TimetableSolver(inst, room_mode=mode, use_objective=bool(use_objective))
