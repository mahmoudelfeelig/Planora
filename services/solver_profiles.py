from __future__ import annotations

from typing import Any, Dict


OBJECTIVE_PROFILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "university_fast": {
        "label": "University fast",
        "use_objective": False,
        "retry_without_objective": False,
        "phased_solve": False,
        "room_mode": "greedy",
        "improve_total_seconds": 0.0,
    },
    "university_quality": {
        "label": "University quality",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
        "room_mode": "greedy",
    },
    "verification": {
        "label": "Verification",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": False,
        "room_mode": "cp_rooms",
    },
    "fast_feasible": {
        "label": "Fast feasible",
        "use_objective": False,
        "retry_without_objective": False,
        "phased_solve": False,
        "improve_total_seconds": 0.0,
    },
    "balanced": {
        "label": "Balanced",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
    },
    "quality_first": {
        "label": "Quality-first",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
        "improve_slice_seconds": 6.0,
        "improve_iters_per_slice": 1500,
        "improve_max_rounds": 16,
    },
}
