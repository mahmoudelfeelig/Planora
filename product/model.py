from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from product.branding import APP_OWNER_NAME
from product.flags import DEFAULT_FEATURE_FLAGS

PRODUCT_SCHEMA_VERSION = 1
DEFAULT_PRODUCT_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
DEFAULT_PRODUCT_WEEKS = list(range(1, 13))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProductMetadata:
    name: str = "Untitled scenario"
    owner: str = APP_OWNER_NAME
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    tags: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ProductCalendar:
    label: str = "Default term"
    days: List[str] = field(default_factory=lambda: list(DEFAULT_PRODUCT_DAYS))
    weeks: List[int] = field(default_factory=lambda: list(DEFAULT_PRODUCT_WEEKS))
    term_blocks: List[Dict[str, Any]] = field(default_factory=list)
    day_start_time: str = "08:30"
    slot_minutes: int = 90
    break_minutes: int = 0
    holiday_dates: List[str] = field(default_factory=list)
    blackout_weeks: List[int] = field(default_factory=list)
    special_weeks: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ProductGenerationConfig:
    mode: str = "small_demo"
    custom_config: Dict[str, Any] = field(default_factory=dict)
    template_id: str = ""


@dataclass
class ProductConstraintConfig:
    hard_constraints: Dict[str, bool] = field(default_factory=dict)
    soft_weights: Dict[str, int] = field(default_factory=dict)
    objective_profile: str = "balanced"
    precedence_rules: List[Dict[str, Any]] = field(default_factory=list)
    sla_targets: Dict[str, Any] = field(default_factory=dict)
    rule_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductResourceConfig:
    campuses: List[str] = field(default_factory=list)
    buildings: Dict[str, List[str]] = field(default_factory=dict)
    closures: List[Dict[str, Any]] = field(default_factory=list)
    travel_buffers: Dict[str, int] = field(default_factory=dict)
    resource_tags: Dict[str, List[str]] = field(default_factory=dict)
    generic_resources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ProductScenario:
    schema_version: int = PRODUCT_SCHEMA_VERSION
    metadata: ProductMetadata = field(default_factory=ProductMetadata)
    calendar: ProductCalendar = field(default_factory=ProductCalendar)
    generation: ProductGenerationConfig = field(default_factory=ProductGenerationConfig)
    constraints: ProductConstraintConfig = field(default_factory=ProductConstraintConfig)
    resources: ProductResourceConfig = field(default_factory=ProductResourceConfig)
    feature_flags: Dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_FEATURE_FLAGS)
    )
    legacy_instance: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
