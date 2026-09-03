from __future__ import annotations

from services.contracts import SolveOptions
from services.solver_service import _apply_objective_profile, available_objective_profiles
from utils.generator import generate_instance


def test_fairness_profile_selects_exact_decomposition_and_no_fallback() -> None:
    inst, options, meta = _apply_objective_profile(
        generate_instance("small_demo", seed=9),
        SolveOptions(objective_profile="fairness_first", time_limit_seconds=5, workers=1),
    )

    assert meta["id"] == "fairness_first"
    assert inst.objective_profile == "fairness_first"
    assert options.room_mode == "decomposed"
    assert options.use_objective is True
    assert options.retry_without_objective is False
    assert ("fairness_first", "Fairness-first research") in available_objective_profiles()
