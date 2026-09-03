from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


UI_CONTRACT_VERSION = "planora.ui.v1"


_SCENARIOS = (
    {
        "id": "demo",
        "label": "Demo timetable",
        "description": "A small ready-to-run timetable for learning Planora.",
        "source": "generated",
        "generator_mode": "small_demo",
    },
    {
        "id": "spring_2023",
        "label": "Spring 2023 university",
        "description": (
            "An SS23-calibrated university example for realistic planning and review."
        ),
        "source": "generated",
        "generator_mode": "ss23_uni_like",
    },
    {
        "id": "import",
        "label": "Import your data",
        "description": "Start from your university's JSON or timetable CSV export.",
        "source": "import",
        "generator_mode": None,
    },
)


_RUN_MODES = (
    {
        "id": "fast",
        "label": "Fast",
        "description": "Build a usable draft quickly.",
        "recommended": False,
        "solve": {
            "objective_profile": "university_fast",
            "room_mode": "partitioned",
            "time_limit_seconds": 8.0,
            "workers": 4,
            "use_objective": False,
            "retry_without_objective": True,
        },
        "improve": {"iterations": 250, "max_seconds": 0.75},
    },
    {
        "id": "balanced",
        "label": "Balanced",
        "description": "A dependable balance of speed and timetable quality.",
        "recommended": True,
        "solve": {
            "objective_profile": "university_fast",
            "room_mode": "partitioned",
            "time_limit_seconds": 20.0,
            "workers": 4,
            "use_objective": False,
            "retry_without_objective": True,
        },
        "improve": {"iterations": 750, "max_seconds": 2.5},
    },
    {
        "id": "quality",
        "label": "Maximum quality",
        "description": "Spend more time reducing clashes and quality penalties.",
        "recommended": False,
        "solve": {
            "objective_profile": "university_quality",
            "room_mode": "partitioned",
            "time_limit_seconds": 60.0,
            "workers": 4,
            "use_objective": True,
            "retry_without_objective": True,
        },
        "improve": {"iterations": 3000, "max_seconds": 8.0},
    },
)


_TUTORIAL = (
    {
        "id": "bring-in",
        "title": "Bring in your timetable",
        "body": "Open the Spring 2023 example or import your university data.",
    },
    {
        "id": "check-essentials",
        "title": "Check the essentials",
        "body": "Confirm the term, rooms, people, courses, and student groups.",
    },
    {
        "id": "build-draft",
        "title": "Build a draft",
        "body": "Choose Fast, Balanced, or Maximum quality and let Planora place events.",
    },
    {
        "id": "review-repair",
        "title": "Review and repair",
        "body": "Open a flagged event, understand the issue, and apply a suggested move.",
    },
    {
        "id": "validate-publish",
        "title": "Validate and publish",
        "body": "Confirm there are no hard conflicts, then publish or export the timetable.",
    },
)


def ui_contract() -> Dict[str, Any]:
    """Return the stable, engine-neutral contract shared by all Planora clients."""
    return {
        "contract_version": UI_CONTRACT_VERSION,
        "scenarios": deepcopy(list(_SCENARIOS)),
        "run_modes": [
            {
                key: deepcopy(value)
                for key, value in item.items()
                if key not in {"solve", "improve"}
            }
            for item in _RUN_MODES
        ],
        "tutorial": deepcopy(list(_TUTORIAL)),
        "actions": {
            "solve": "/sessions/{session_id}/solve",
            "improve": "/sessions/{session_id}/improve",
            "score": "/sessions/{session_id}/score",
            "move_deltas": "/sessions/{session_id}/move-deltas",
            "move": "/sessions/{session_id}/move",
        },
        "advanced_options_supported": True,
    }


def public_preset_ids() -> list[str]:
    return [
        str(item["id"])
        for item in _SCENARIOS
        if item.get("source") == "generated"
    ]


def generator_mode_for_scenario(scenario_id: str) -> str:
    requested = str(scenario_id or "").strip().lower()
    for item in _SCENARIOS:
        if item["id"] == requested and item.get("generator_mode"):
            return str(item["generator_mode"])
    # Existing URLs and saved projects remain readable without advertising them.
    compatibility = {
        "small_demo": "small_demo",
        "ss23_uni_like": "ss23_uni_like",
        "uni_like": "ss23_uni_like",
        "mixed_large": "mixed_large",
        "block_profs": "block_profs",
        "labs_only": "labs_only",
        "random": "random",
        "target_case": "target_case",
        "giu": "giu_target",
        "giu_target": "giu_target",
    }
    if requested in compatibility:
        return compatibility[requested]
    raise ValueError(f"Unknown scenario: {scenario_id}")


def run_mode_options(run_mode: str, *, action: str) -> Dict[str, Any]:
    requested = str(run_mode or "balanced").strip().lower()
    if requested == "best_quality":
        requested = "quality"
    for item in _RUN_MODES:
        if item["id"] == requested:
            return deepcopy(dict(item[action]))
    raise ValueError(f"Unknown run mode: {run_mode}")
