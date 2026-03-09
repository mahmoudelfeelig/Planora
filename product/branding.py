from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

APP_SHORT_NAME = "Planora"
APP_DISPLAY_NAME = "Planora Academic Scheduler"
APP_SUBTITLE = "Academic scheduling workspace"
APP_OWNER_NAME = "feel"
APP_PUBLISHER = "feel"
APP_VERSION = "1.0"
APP_COPYRIGHT_LINE = f"{APP_SHORT_NAME} by {APP_OWNER_NAME}"
APP_SUPPORT_EMAIL = "support@planora.local"
APP_DOCUMENTATION_URL = "https://docs.planora.local"
APP_WEBSITE_URL = "https://planora.local"

DEFAULT_BRAND_KIT: Dict[str, Any] = {
    "short_name": APP_SHORT_NAME,
    "display_name": APP_DISPLAY_NAME,
    "subtitle": APP_SUBTITLE,
    "owner": APP_OWNER_NAME,
    "publisher": APP_PUBLISHER,
    "version": APP_VERSION,
    "copyright_line": APP_COPYRIGHT_LINE,
    "support_email": APP_SUPPORT_EMAIL,
    "documentation_url": APP_DOCUMENTATION_URL,
    "website_url": APP_WEBSITE_URL,
    "palette": {
        "background": "#10131A",
        "surface": "#181F2A",
        "surface_alt": "#21301F",
        "text": "#F2F4F8",
        "muted_text": "#A7B0BE",
        "accent": "#6F8F6A",
        "accent_strong": "#7D63D9",
        "danger": "#C84444",
        "warning": "#D7A632",
        "info": "#4E97D1",
    },
    "typography": {
        "ui_family": "Segoe UI",
        "heading_family": "Segoe UI Semibold",
        "mono_family": "Consolas",
    },
    "logo_variants": [
        {"id": "primary", "label": "Planora Primary"},
        {"id": "mono", "label": "Planora Mono"},
        {"id": "icon_only", "label": "Planora Icon"},
    ],
    "screenshots": [
        "docs/portal/assets/planora_dashboard.svg",
        "docs/portal/assets/planora_reports.svg",
    ],
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def resolve_brand_kit(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _deep_merge(DEFAULT_BRAND_KIT, dict(overrides or {}))


def brand_display_name(branding: Dict[str, Any] | None = None) -> str:
    profile = resolve_brand_kit(branding)
    return str(profile.get("display_name", APP_DISPLAY_NAME) or APP_DISPLAY_NAME)


def brand_short_name(branding: Dict[str, Any] | None = None) -> str:
    profile = resolve_brand_kit(branding)
    return str(profile.get("short_name", APP_SHORT_NAME) or APP_SHORT_NAME)


def branding_header_lines(branding: Dict[str, Any] | None = None) -> list[str]:
    profile = resolve_brand_kit(branding)
    return [
        str(profile.get("display_name", APP_DISPLAY_NAME)),
        str(profile.get("subtitle", APP_SUBTITLE)),
        f"Owner: {str(profile.get('owner', APP_OWNER_NAME))}",
    ]
