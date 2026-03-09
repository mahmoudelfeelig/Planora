from __future__ import annotations

from typing import Any, Dict, List

from product.model import ProductScenario
from product.rules import apply_rule_overrides
from utils.domain import GenericResource
from utils.generator import generate_custom_instance, generate_instance
from utils.io import instance_from_json
from main import normalize_instance_for_spec, stamp_instance_time


def _expand_term_blocks(term_blocks: List[Dict[str, Any]]) -> List[int]:
    weeks: List[int] = []
    next_week = 1
    for block in term_blocks:
        if not isinstance(block, dict):
            continue
        try:
            length = max(1, int(block.get("length_weeks", 0)))
        except Exception:
            continue
        block_weeks = list(range(int(next_week), int(next_week + length)))
        block["weeks"] = list(block_weeks)
        weeks.extend(block_weeks)
        next_week += length
    return weeks


def compile_product_scenario(scenario: ProductScenario):
    if scenario.legacy_instance:
        inst = instance_from_json(dict(scenario.legacy_instance))
    else:
        mode = str(scenario.generation.mode or "small_demo")
        if mode == "custom":
            custom_config = dict(scenario.generation.custom_config or {})
            custom_config.setdefault("calendar_days", list(scenario.calendar.days or []))
            expanded_weeks = list(scenario.calendar.weeks or [])
            if scenario.calendar.term_blocks:
                expanded_weeks = _expand_term_blocks(
                    [dict(block) for block in scenario.calendar.term_blocks]
                )
            if not list(custom_config.get("calendar_weeks") or []):
                custom_config["calendar_weeks"] = list(expanded_weeks)
            if scenario.calendar.term_blocks:
                custom_config["term_blocks"] = [
                    dict(block) for block in scenario.calendar.term_blocks
                ]
            if custom_config.get("slots_per_day") in (None, ""):
                custom_config["slots_per_day"] = 5
            inst = generate_custom_instance(**custom_config)
        else:
            inst = generate_instance(mode=mode)

    apply_rule_overrides(
        inst,
        hard_constraints=dict(scenario.constraints.hard_constraints or {}),
        soft_weights=dict(scenario.constraints.soft_weights or {}),
    )
    inst.objective_profile = str(
        scenario.constraints.objective_profile or "balanced"
    )
    inst.travel_time_rules = dict(scenario.resources.travel_buffers or {})
    inst.room_closures = list(scenario.resources.closures or [])
    term_block_blackouts = [
        int(w)
        for block in (scenario.calendar.term_blocks or [])
        if isinstance(block, dict) and not bool(block.get("teaching", True))
        for w in (block.get("weeks") or [])
    ]
    inst.calendar_rules = {
        "blackout_weeks": list(
            dict.fromkeys(
                [int(w) for w in (scenario.calendar.blackout_weeks or [])]
                + term_block_blackouts
            )
        ),
        "holiday_dates": list(scenario.calendar.holiday_dates or []),
        "special_weeks": dict(scenario.calendar.special_weeks or {}),
    }
    inst.term_blocks = [dict(block) for block in (scenario.calendar.term_blocks or [])]
    inst.precedence_rules = list(scenario.constraints.precedence_rules or [])
    inst.sla_targets = dict(scenario.constraints.sla_targets or {})
    inst.generic_resources = {}
    for idx, raw in enumerate(scenario.resources.generic_resources or [], start=1):
        if not isinstance(raw, dict):
            continue
        rid = int(raw.get("id", idx) or idx)
        inst.generic_resources[int(rid)] = GenericResource(
            id=int(rid),
            name=str(raw.get("name", f"Resource-{rid}") or f"Resource-{rid}"),
            resource_type=str(raw.get("resource_type", "GENERIC") or "GENERIC"),
            capacity=max(1, int(raw.get("capacity", 1) or 1)),
            tags={str(v).strip().upper() for v in (raw.get("tags") or []) if str(v).strip()},
        )
    normalize_instance_for_spec(inst)
    stamp_instance_time(
        inst,
        str(scenario.calendar.day_start_time),
        int(scenario.calendar.slot_minutes),
        int(scenario.calendar.break_minutes),
    )
    # Attach product-layer metadata without mutating the solver schema.
    setattr(
        inst,
        "product_metadata",
        {
            "schema_version": int(scenario.schema_version),
            "name": str(scenario.metadata.name),
            "owner": str(scenario.metadata.owner),
            "calendar_label": str(scenario.calendar.label),
        },
    )
    setattr(inst, "product_feature_flags", dict(scenario.feature_flags or {}))
    setattr(
        inst,
        "product_resources",
        {
            "campuses": list(scenario.resources.campuses or []),
            "buildings": dict(scenario.resources.buildings or {}),
            "resource_tags": dict(scenario.resources.resource_tags or {}),
        },
    )
    return inst
