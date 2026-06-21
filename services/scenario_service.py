from __future__ import annotations

import json
from pathlib import Path

from product.compiler import compile_product_scenario
from product.migrations import product_scenario_from_dict
from product.model import ProductMetadata, ProductScenario
from utils.generator import instance_to_json


def build_builtin_product_scenario(
    mode: str,
    *,
    name: str | None = None,
    owner: str | None = None,
) -> ProductScenario:
    scenario = ProductScenario()
    scenario.generation.mode = str(mode)
    scenario.metadata = ProductMetadata(
        name=str(name or f"{str(mode).replace('_', ' ').title()} Scenario"),
        owner=str(owner or scenario.metadata.owner),
    )
    return scenario


def build_product_scenario_from_instance(
    inst,
    *,
    name: str = "Imported scenario",
    owner: str | None = None,
) -> ProductScenario:
    scenario = ProductScenario()
    scenario.metadata = ProductMetadata(
        name=str(name),
        owner=str(owner or scenario.metadata.owner),
    )
    scenario.legacy_instance = instance_to_json(inst)
    scenario.constraints.hard_constraints = dict(getattr(inst, "hard_constraints", {}) or {})
    scenario.constraints.soft_weights = dict(getattr(inst, "soft_weights", {}) or {})
    scenario.constraints.objective_profile = str(
        getattr(inst, "objective_profile", "balanced") or "balanced"
    )
    scenario.constraints.precedence_rules = list(
        getattr(inst, "precedence_rules", []) or []
    )
    scenario.constraints.sla_targets = dict(getattr(inst, "sla_targets", {}) or {})
    scenario.calendar.days = [str(day) for day in getattr(inst, "days", [])]
    scenario.calendar.weeks = [int(week) for week in getattr(inst, "weeks", [])]
    scenario.calendar.term_blocks = list(getattr(inst, "term_blocks", []) or [])
    calendar_rules = dict(getattr(inst, "calendar_rules", {}) or {})
    scenario.calendar.holiday_dates = list(calendar_rules.get("holiday_dates") or [])
    scenario.calendar.blackout_weeks = [
        int(w) for w in (calendar_rules.get("blackout_weeks") or [])
    ]
    scenario.calendar.special_weeks = dict(calendar_rules.get("special_weeks") or {})
    scenario.resources.travel_buffers = dict(
        getattr(inst, "travel_time_rules", {}) or {}
    )
    scenario.resources.closures = list(getattr(inst, "room_closures", []) or [])
    scenario.resources.generic_resources = [
        {
            "id": int(resource.id),
            "name": str(resource.name),
            "resource_type": str(resource.resource_type),
            "capacity": int(resource.capacity),
            "tags": sorted(str(tag) for tag in (resource.tags or [])),
        }
        for resource in (getattr(inst, "generic_resources", {}) or {}).values()
    ]
    room_campuses: dict[str, list[str]] = {}
    campuses: set[str] = set()
    for room in getattr(inst, "rooms", {}).values():
        campus = str(getattr(room, "campus", "") or "MAIN").strip().upper()
        building = str(getattr(room, "building", "") or "").strip()
        if campus:
            campuses.add(campus)
        if campus and building:
            room_campuses.setdefault(campus, [])
            if building not in room_campuses[campus]:
                room_campuses[campus].append(building)
    scenario.resources.campuses = sorted(campuses)
    scenario.resources.buildings = {
        campus: sorted(buildings) for campus, buildings in room_campuses.items()
    }
    if hasattr(inst, "day_start_time"):
        scenario.calendar.day_start_time = str(getattr(inst, "day_start_time"))
    if hasattr(inst, "slot_minutes"):
        scenario.calendar.slot_minutes = int(getattr(inst, "slot_minutes"))
    if hasattr(inst, "slot_break_minutes"):
        scenario.calendar.break_minutes = int(getattr(inst, "slot_break_minutes"))
    return scenario


def compile_scenario_instance(scenario: ProductScenario):
    return compile_product_scenario(scenario)


def save_product_scenario(path: str | Path, scenario: ProductScenario) -> None:
    payload = scenario.to_dict()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_product_scenario(path: str | Path) -> ProductScenario:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return product_scenario_from_dict(payload)
