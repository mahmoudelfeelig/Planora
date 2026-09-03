from __future__ import annotations

from utils.demand import demand_requirement, required_capacity
from utils.generator import generate_instance, instance_to_json
from utils.io import instance_from_json


def test_worst_case_and_quantile_demand_are_deterministic() -> None:
    inst = generate_instance("small_demo", seed=1)
    group_ids = sorted(inst.groups)[:2]
    nominal = sum(inst.groups[group_id].size for group_id in group_ids)
    for index, group_id in enumerate(group_ids):
        group = inst.groups[group_id]
        group.demand_scenarios = {
            "low": int(group.size),
            "high": int(group.size + 10 + index),
            "medium": int(group.size + 4),
        }

    inst.demand_policy = {"mode": "worst_case"}
    worst = demand_requirement(inst, group_ids)
    assert worst.nominal == nominal
    assert worst.required == nominal + 21
    assert worst.binding_scenario == "high"

    inst.demand_policy = {"mode": "quantile", "service_level": 2 / 3}
    quantile = demand_requirement(inst, group_ids)
    assert quantile.required == nominal + 8
    assert quantile.binding_scenario == "medium"


def test_budgeted_demand_supports_fractional_gamma() -> None:
    inst = generate_instance("small_demo", seed=2)
    group_ids = sorted(inst.groups)[:2]
    inst.groups[group_ids[0]].demand_deviation = 10
    inst.groups[group_ids[1]].demand_deviation = 4
    nominal = sum(inst.groups[group_id].size for group_id in group_ids)
    inst.demand_policy = {"mode": "budgeted", "gamma": 1.5}
    assert required_capacity(inst, group_ids) == nominal + 12


def test_demand_configuration_survives_json_roundtrip() -> None:
    inst = generate_instance("small_demo", seed=3)
    group_id = min(inst.groups)
    inst.groups[group_id].demand_scenarios = {"forecast-p90": 73}
    inst.groups[group_id].demand_deviation = 9
    inst.demand_policy = {"mode": "quantile", "service_level": 0.9}

    restored = instance_from_json(instance_to_json(inst))
    assert restored.groups[group_id].demand_scenarios == {"forecast-p90": 73}
    assert restored.groups[group_id].demand_deviation == 9
    assert restored.demand_policy == {"mode": "quantile", "service_level": 0.9}
