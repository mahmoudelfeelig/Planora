from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    category: str
    title: str
    description: str
    target: str
    default_value: Any
    compile_hook: Optional[Callable[[Any, Any], None]] = None


def _set_hard_flag(inst: Any, value: Any, *, key: str) -> None:
    flags = dict(getattr(inst, "hard_constraints", {}) or {})
    flags[str(key)] = bool(value)
    inst.hard_constraints = flags


def _set_soft_weight(inst: Any, value: Any, *, key: str) -> None:
    weights = dict(getattr(inst, "soft_weights", {}) or {})
    weights[str(key)] = int(value)
    inst.soft_weights = weights


HARD_RULES: Dict[str, RuleDefinition] = {
    "week1_lectures_only": RuleDefinition(
        rule_id="week1_lectures_only",
        category="hard",
        title="Week 1 lectures only",
        description="Blocks tutorial/lab teaching during the first teaching week.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="week1_lectures_only"
        ),
    ),
    "force_repeat_weekly_pattern": RuleDefinition(
        rule_id="force_repeat_weekly_pattern",
        category="hard",
        title="Repeat weekly pattern",
        description=(
            "After the first teaching week, recurring activities with the same "
            "course, kind, staff, group set, and duration must keep the same "
            "day, slot, and room."
        ),
        target="hard_constraints",
        default_value=False,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="force_repeat_weekly_pattern"
        ),
    ),
    "enforce_course_totals": RuleDefinition(
        rule_id="enforce_course_totals",
        category="hard",
        title="Course total metadata",
        description="Requires generated course metadata to match the number of lecture, tutorial, and lab sessions.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_course_totals"
        ),
    ),
    "enforce_block_professor_rules": RuleDefinition(
        rule_id="enforce_block_professor_rules",
        category="hard",
        title="Block-professor rules",
        description="Requires block-only professors to teach a single contiguous lecture block.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_block_professor_rules"
        ),
    ),
    "enforce_staff_daily_caps": RuleDefinition(
        rule_id="enforce_staff_daily_caps",
        category="hard",
        title="Staff daily caps",
        description="Enforces maximum slots per day for staff.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_staff_daily_caps"
        ),
    ),
    "enforce_staff_weekly_caps": RuleDefinition(
        rule_id="enforce_staff_weekly_caps",
        category="hard",
        title="Staff weekly caps",
        description="Enforces maximum slots per week for staff.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_staff_weekly_caps"
        ),
    ),
    "enforce_room_availability": RuleDefinition(
        rule_id="enforce_room_availability",
        category="hard",
        title="Room availability",
        description="Prevents assigning rooms outside their declared availability.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_room_availability"
        ),
    ),
    "enforce_travel_time_buffers": RuleDefinition(
        rule_id="enforce_travel_time_buffers",
        category="hard",
        title="Travel-time buffers",
        description="Requires time buffers when shared staff/groups move between buildings or campuses.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_travel_time_buffers"
        ),
    ),
    "enforce_building_closures": RuleDefinition(
        rule_id="enforce_building_closures",
        category="hard",
        title="Building closures",
        description="Blocks rooms during declared building or campus closure windows.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_building_closures"
        ),
    ),
    "enforce_calendar_rules": RuleDefinition(
        rule_id="enforce_calendar_rules",
        category="hard",
        title="Calendar blackout rules",
        description="Blocks blackout weeks, holiday tokens, and special-week day closures.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_calendar_rules"
        ),
    ),
    "enforce_precedence_rules": RuleDefinition(
        rule_id="enforce_precedence_rules",
        category="hard",
        title="Activity precedence",
        description="Requires configured activities to occur before later dependent activities.",
        target="hard_constraints",
        default_value=True,
        compile_hook=lambda inst, value: _set_hard_flag(
            inst, value, key="enforce_precedence_rules"
        ),
    ),
}


SOFT_RULES: Dict[str, RuleDefinition] = {
    "stud_free_days": RuleDefinition(
        rule_id="stud_free_days",
        category="soft",
        title="Free days",
        description="Prefers more free days across the full teaching week.",
        target="soft_weights",
        default_value=10,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="stud_free_days"),
    ),
    "stud_free_mf": RuleDefinition(
        rule_id="stud_free_mf",
        category="soft",
        title="Mon-Fri free days",
        description="Prefers free weekdays from Monday to Friday.",
        target="soft_weights",
        default_value=5,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="stud_free_mf"),
    ),
    "stud_gaps": RuleDefinition(
        rule_id="stud_gaps",
        category="soft",
        title="Gap minimization",
        description="Penalizes separated teaching blocks within the same day.",
        target="soft_weights",
        default_value=5,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="stud_gaps"),
    ),
    "active_days": RuleDefinition(
        rule_id="active_days",
        category="soft",
        title="Active-day minimization",
        description="Penalizes schedules that spread teaching across too many days.",
        target="soft_weights",
        default_value=5,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="active_days"),
    ),
    "late_start": RuleDefinition(
        rule_id="late_start",
        category="soft",
        title="Late starts",
        description="Penalizes days whose first teaching slot starts late.",
        target="soft_weights",
        default_value=3,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="late_start"),
    ),
    "thin_day": RuleDefinition(
        rule_id="thin_day",
        category="soft",
        title="Thin days",
        description="Penalizes days with very small teaching loads.",
        target="soft_weights",
        default_value=3,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="thin_day"),
    ),
    "stability": RuleDefinition(
        rule_id="stability",
        category="soft",
        title="Week stability",
        description="Penalizes week-to-week pattern changes.",
        target="soft_weights",
        default_value=1,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="stability"),
    ),
    "single_slot": RuleDefinition(
        rule_id="single_slot",
        category="soft",
        title="Single-slot day",
        description="Penalizes days that contain only one scheduled slot.",
        target="soft_weights",
        default_value=6,
        compile_hook=lambda inst, value: _set_soft_weight(inst, value, key="single_slot"),
    ),
    "same_kind_week": RuleDefinition(
        rule_id="same_kind_week",
        category="soft",
        title="Same-kind weekly distribution",
        description="Penalizes repeated LEC/TUT occurrences of the same course in a week.",
        target="soft_weights",
        default_value=3,
        compile_hook=lambda inst, value: _set_soft_weight(
            inst, value, key="same_kind_week"
        ),
    ),
}


RULE_REGISTRY: Dict[str, RuleDefinition] = {**HARD_RULES, **SOFT_RULES}


def apply_rule_overrides(
    inst: Any,
    *,
    hard_constraints: Dict[str, bool] | None = None,
    soft_weights: Dict[str, int] | None = None,
) -> None:
    for rule_id, rule in HARD_RULES.items():
        value = (
            hard_constraints.get(rule_id, rule.default_value)
            if isinstance(hard_constraints, dict)
            else rule.default_value
        )
        if rule.compile_hook is not None:
            rule.compile_hook(inst, value)
    for rule_id, rule in SOFT_RULES.items():
        value = (
            soft_weights.get(rule_id, rule.default_value)
            if isinstance(soft_weights, dict)
            else rule.default_value
        )
        if rule.compile_hook is not None:
            rule.compile_hook(inst, value)
