from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from utils.domain import Instance


DEFAULT_TEMPLATES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "Balanced": {
        "hard": {
            "week1_lectures_only": True,
            "enforce_block_professor_rules": True,
            "enforce_staff_daily_caps": True,
            "enforce_staff_weekly_caps": True,
            "enforce_room_availability": True,
        },
        "soft": {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "staff_free_day": 6,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "single_slot": 6,
            "stability": 1,
            "room_consistency": 1,
            "same_kind_week": 3,
        },
    },
    "Compact Student Weeks": {
        "hard": {
            "week1_lectures_only": True,
            "enforce_block_professor_rules": True,
            "enforce_staff_daily_caps": True,
            "enforce_staff_weekly_caps": True,
            "enforce_room_availability": True,
        },
        "soft": {
            "stud_free_days": 14,
            "stud_free_mf": 7,
            "stud_gaps": 9,
            "staff_free_day": 5,
            "active_days": 8,
            "late_start": 2,
            "thin_day": 5,
            "single_slot": 9,
            "stability": 1,
            "room_consistency": 1,
            "same_kind_week": 4,
        },
    },
    "Staff Friendly": {
        "hard": {
            "week1_lectures_only": True,
            "enforce_block_professor_rules": True,
            "enforce_staff_daily_caps": True,
            "enforce_staff_weekly_caps": True,
            "enforce_room_availability": True,
        },
        "soft": {
            "stud_free_days": 8,
            "stud_free_mf": 4,
            "stud_gaps": 4,
            "staff_free_day": 12,
            "active_days": 4,
            "late_start": 2,
            "thin_day": 2,
            "single_slot": 5,
            "stability": 2,
            "room_consistency": 1,
            "same_kind_week": 2,
        },
    },
}


def load_templates(path: str | Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_TEMPLATES)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_TEMPLATES)
    if not isinstance(payload, dict):
        return dict(DEFAULT_TEMPLATES)
    out: Dict[str, Dict[str, Dict[str, Any]]] = dict(DEFAULT_TEMPLATES)
    for name, cfg in payload.items():
        if not isinstance(cfg, dict):
            continue
        hard = cfg.get("hard", {})
        soft = cfg.get("soft", {})
        if not isinstance(hard, dict) or not isinstance(soft, dict):
            continue
        out[str(name)] = {
            "hard": {str(k): bool(v) for k, v in hard.items()},
            "soft": {str(k): int(v) for k, v in soft.items()},
        }
    return out


def save_templates(path: str | Path, templates: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, cfg in templates.items():
        if not isinstance(cfg, dict):
            continue
        hard = cfg.get("hard", {})
        soft = cfg.get("soft", {})
        if not isinstance(hard, dict) or not isinstance(soft, dict):
            continue
        payload[str(name)] = {
            "hard": {str(k): bool(v) for k, v in hard.items()},
            "soft": {str(k): int(v) for k, v in soft.items()},
        }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def apply_template_to_instance(
    inst: Instance,
    template: Dict[str, Dict[str, Any]],
) -> None:
    hard = template.get("hard", {}) if isinstance(template, dict) else {}
    soft = template.get("soft", {}) if isinstance(template, dict) else {}
    if isinstance(hard, dict):
        inst.hard_constraints = {str(k): bool(v) for k, v in hard.items()}
    if isinstance(soft, dict):
        inst.soft_weights = {str(k): int(v) for k, v in soft.items()}
