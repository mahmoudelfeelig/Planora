from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

from utils.domain import Instance


@dataclass(frozen=True)
class DemandRequirement:
    nominal: int
    required: int
    mode: str
    binding_scenario: str | None = None
    service_level: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _group_ids(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values}))


def _scenario_totals(inst: Instance, group_ids: tuple[int, ...]) -> dict[str, int]:
    scenario_names = sorted(
        {
            str(name)
            for group_id in group_ids
            if group_id in inst.groups
            for name in (getattr(inst.groups[group_id], "demand_scenarios", {}) or {})
        }
    )
    totals: dict[str, int] = {}
    for scenario in scenario_names:
        total = 0
        for group_id in group_ids:
            group = inst.groups.get(group_id)
            if group is None:
                continue
            scenarios = getattr(group, "demand_scenarios", {}) or {}
            total += int(scenarios.get(scenario, group.size))
        totals[scenario] = int(total)
    return totals


def demand_requirement(inst: Instance, group_ids: Iterable[int]) -> DemandRequirement:
    """Compute the capacity required by an institution's uncertainty policy.

    ``quantile`` uses the empirical nearest-rank quantile over named scenarios.
    ``budgeted`` implements an integer/fractional Bertsimas-Sim-style budget over
    group deviations: nominal plus the largest ``gamma`` deviations.
    """

    groups = _group_ids(group_ids)
    nominal = sum(
        int(inst.groups[group_id].size)
        for group_id in groups
        if group_id in inst.groups
    )
    policy = getattr(inst, "demand_policy", {}) or {}
    mode = str(policy.get("mode", "nominal") or "nominal").strip().lower()
    if mode in {"", "nominal", "none"}:
        return DemandRequirement(nominal=nominal, required=nominal, mode="nominal")

    scenarios = _scenario_totals(inst, groups)
    if mode == "worst_case":
        if not scenarios:
            return DemandRequirement(nominal=nominal, required=nominal, mode=mode)
        binding, required = max(scenarios.items(), key=lambda item: (int(item[1]), str(item[0])))
        return DemandRequirement(
            nominal=nominal,
            required=max(nominal, int(required)),
            mode=mode,
            binding_scenario=str(binding),
            service_level=1.0,
        )

    if mode == "quantile":
        level = min(1.0, max(0.0, float(policy.get("service_level", 0.95) or 0.95)))
        values = sorted([(int(total), str(name)) for name, total in scenarios.items()])
        if not values:
            return DemandRequirement(
                nominal=nominal,
                required=nominal,
                mode=mode,
                service_level=level,
            )
        rank = max(0, min(len(values) - 1, int(math.ceil(level * len(values))) - 1))
        required, binding = values[rank]
        return DemandRequirement(
            nominal=nominal,
            required=max(nominal, int(required)),
            mode=mode,
            binding_scenario=str(binding),
            service_level=level,
        )

    if mode == "budgeted":
        gamma = max(0.0, float(policy.get("gamma", 0.0) or 0.0))
        deviations = sorted(
            (
                max(0, int(getattr(inst.groups[group_id], "demand_deviation", 0) or 0))
                for group_id in groups
                if group_id in inst.groups
            ),
            reverse=True,
        )
        whole = min(len(deviations), int(math.floor(gamma)))
        uplift = sum(deviations[:whole])
        fractional = gamma - whole
        if whole < len(deviations) and fractional > 0:
            uplift += int(math.ceil(float(deviations[whole]) * fractional))
        return DemandRequirement(
            nominal=nominal,
            required=int(nominal + uplift),
            mode=mode,
            service_level=None,
        )

    raise ValueError(f"Unsupported demand policy mode: {mode}")


def required_capacity(inst: Instance, group_ids: Iterable[int]) -> int:
    return int(demand_requirement(inst, group_ids).required)
