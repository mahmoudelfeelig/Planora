from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict

from product.flags import DEFAULT_FEATURE_FLAGS
from product.model import (
    PRODUCT_SCHEMA_VERSION,
    ProductCalendar,
    ProductConstraintConfig,
    ProductGenerationConfig,
    ProductMetadata,
    ProductResourceConfig,
    ProductScenario,
)


def migrate_product_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(payload or {})
    raw.setdefault("schema_version", PRODUCT_SCHEMA_VERSION)
    raw.setdefault("metadata", {})
    raw.setdefault("calendar", {})
    raw.setdefault("generation", {})
    raw.setdefault("constraints", {})
    raw.setdefault("resources", {})
    flags = dict(DEFAULT_FEATURE_FLAGS)
    flags.update(raw.get("feature_flags") or {})
    raw["feature_flags"] = flags
    return raw


def _coerce_dataclass(data: Dict[str, Any], cls: Any) -> Any:
    names = {f.name for f in fields(cls)}
    usable = {key: value for key, value in dict(data or {}).items() if key in names}
    return cls(**usable)


def product_scenario_from_dict(payload: Dict[str, Any]) -> ProductScenario:
    raw = migrate_product_payload(payload)
    return ProductScenario(
        schema_version=int(raw.get("schema_version", PRODUCT_SCHEMA_VERSION)),
        metadata=_coerce_dataclass(raw.get("metadata", {}), ProductMetadata),
        calendar=_coerce_dataclass(raw.get("calendar", {}), ProductCalendar),
        generation=_coerce_dataclass(raw.get("generation", {}), ProductGenerationConfig),
        constraints=_coerce_dataclass(raw.get("constraints", {}), ProductConstraintConfig),
        resources=_coerce_dataclass(raw.get("resources", {}), ProductResourceConfig),
        feature_flags=dict(raw.get("feature_flags") or {}),
        legacy_instance=raw.get("legacy_instance"),
    )
