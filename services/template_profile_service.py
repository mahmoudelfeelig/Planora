from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

TEMPLATE_REGISTRY_VERSION = 1


def save_import_export_template(path: str | Path, template: Dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(dict(template or {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_import_export_template(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Template payload must be a JSON object.")
    return payload


def load_import_export_template_registry(path: str | Path) -> Dict[str, Dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Template registry payload must be a JSON object.")

    raw_templates = payload.get("templates")
    if isinstance(raw_templates, dict):
        return {
            str(name): dict(template)
            for name, template in raw_templates.items()
            if isinstance(template, dict)
        }

    if payload:
        # Backward compatibility for the original single-template file format.
        label = str(payload.get("institution_name", "Default") or "Default")
        return {label: dict(payload)}
    return {}


def save_import_export_template_profile(
    path: str | Path,
    *,
    institution_name: str,
    template: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    clean_name = str(institution_name or "").strip()
    if not clean_name:
        raise ValueError("Institution name is required.")
    registry = load_import_export_template_registry(path)
    registry[clean_name] = dict(template or {})
    payload = {
        "version": TEMPLATE_REGISTRY_VERSION,
        "templates": registry,
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return registry


def list_import_export_template_profiles(path: str | Path) -> list[str]:
    return sorted(load_import_export_template_registry(path).keys())


def load_import_export_template_profile(
    path: str | Path,
    *,
    institution_name: str,
) -> Dict[str, Any]:
    registry = load_import_export_template_registry(path)
    clean_name = str(institution_name or "").strip()
    if clean_name not in registry:
        raise KeyError(f"Template profile '{clean_name}' was not found.")
    return dict(registry[clean_name])
