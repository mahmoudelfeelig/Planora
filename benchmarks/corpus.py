from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    mode: str
    room_mode: str
    use_objective: bool
    time_limit_seconds: float
    max_wall_seconds: float
    expected_statuses: Tuple[int, ...] = (0, 4)
    max_soft_penalty: int | None = None


BENCHMARK_CASES = (
    BenchmarkCase(
        case_id="small_demo_fast_feasible",
        mode="small_demo",
        room_mode="greedy",
        use_objective=False,
        time_limit_seconds=20.0,
        max_wall_seconds=20.0,
        expected_statuses=(0, 4),
        max_soft_penalty=450,
    ),
)
