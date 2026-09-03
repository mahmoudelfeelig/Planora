from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SolveOptions:
    room_mode: str = "cp_rooms"
    use_objective: bool = True
    retry_without_objective: bool = True
    objective_profile: str = "balanced"
    time_limit_seconds: Optional[float] = None
    strict_limit_seconds: Optional[float] = None
    workers: Optional[int] = 8
    random_seed: Optional[int] = None
    phased_solve: bool = False
    feasibility_seconds: Optional[float] = None
    improve_total_seconds: float = 0.0
    improve_slice_seconds: float = 5.0
    improve_iters_per_slice: int = 1200
    improve_max_rounds: int = 12
    adaptive_lns_seconds: float = 0.0
    adaptive_lns_slice_seconds: float = 2.0
    adaptive_lns_max_rounds: int = 24
    adaptive_lns_neighborhood_sizes: Tuple[int, ...] = (12, 24, 48)
    adaptive_lns_exact_activity_limit: int = 750
    projected_time_search: bool = False
    projected_time_room_reserve_seconds: float = 0.8
    projected_time_feedback: bool = True
    projected_time_feedback_seconds: float = 5.0
    projected_time_feedback_rounds: int = 3
    projected_time_stability_collision_weight: int = 1
    projected_time_stability_proxy_mode: str = "collision_events"
    projected_time_small_room_cp_seconds: float = 0.35
    fixed_time_room_dive: bool = False
    fixed_time_room_strategy: str = "oracle_then_cp"
    log_progress: bool = False
    enforce_hard_conflict_free: bool = True
    base_schedule: Optional[Dict[int, Dict[str, Any]]] = None
    affected_activity_ids: Optional[List[int]] = None
    freeze_unaffected: bool = False


@dataclass(frozen=True)
class ImproveOptions:
    iterations: int = 300
    start_temp: float = 5.0
    end_temp: float = 0.1
    max_seconds: Optional[float] = None
    progress_every: int = 1000
    restart_after: Optional[int] = None
    max_restarts: Optional[int] = None
    kick_steps: Optional[int] = None
    probe_activities: Optional[int] = None


@dataclass(frozen=True)
class SolveAttempt:
    room_mode: str
    use_objective: bool
    time_limit_seconds: Optional[float]
    raw_status: int
    objective_value: Optional[float] = None
    best_objective_bound: Optional[float] = None
    relative_gap: Optional[float] = None
    status_name: Optional[str] = None
    proof_status: str = "no_solution"
    budget_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    model_build_seconds: float = 0.0
    setup_seconds: float = 0.0
    deadline_safety_margin_seconds: float = 0.0
    search_budget_seconds: Optional[float] = None
    search_seconds: float = 0.0
    deadline_overrun_seconds: float = 0.0
    budget_exhausted: bool = False


@dataclass
class SolveResult:
    status: int
    raw_status: int
    schedule: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    attempts: List[SolveAttempt] = field(default_factory=list)
    hard_conflicts: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_feasible(self) -> bool:
        return int(self.status) in (0, 4)


@dataclass
class PortfolioCandidate:
    name: str
    options: SolveOptions
    result: SolveResult
    soft_penalty: Optional[int] = None
    rank_explanation: str = ""


@dataclass
class PortfolioResult:
    candidates: List[PortfolioCandidate] = field(default_factory=list)
    best_index: int = -1

    @property
    def best(self) -> Optional[PortfolioCandidate]:
        if 0 <= int(self.best_index) < len(self.candidates):
            return self.candidates[int(self.best_index)]
        return None
