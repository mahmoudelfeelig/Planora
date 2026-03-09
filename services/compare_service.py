from __future__ import annotations

from typing import Any, Dict

from utils.compare import compare_schedules


def compare_schedule_sets(
    base: Dict[int, Dict[str, Any]],
    other: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    return compare_schedules(base, other)
