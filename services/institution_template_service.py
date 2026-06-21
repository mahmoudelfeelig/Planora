from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from services.branding_service import ensure_branding_profile


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in dict(override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def save_institution_template(path: str | Path, template: Dict[str, Any]) -> None:
    payload = dict(template or {})
    if isinstance(payload.get("branding"), dict):
        payload["branding"] = ensure_branding_profile(payload.get("branding"))
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_institution_template(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Institution template must be a JSON object.")
    return payload


def apply_institution_template(
    template: Dict[str, Any],
    *,
    current_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    merged = _deep_merge(dict(current_config or {}), dict(template or {}))
    if isinstance(merged.get("branding"), dict):
        merged["branding"] = ensure_branding_profile(merged.get("branding"))
    return merged
