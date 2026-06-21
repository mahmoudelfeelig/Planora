from __future__ import annotations

from typing import Any, Dict

from product.branding import (
    APP_COPYRIGHT_LINE,
    APP_DISPLAY_NAME,
    APP_DOCUMENTATION_URL,
    APP_OWNER_NAME,
    APP_PUBLISHER,
    APP_SHORT_NAME,
    APP_SUBTITLE,
    APP_SUPPORT_EMAIL,
    APP_VERSION,
    DEFAULT_BRAND_KIT,
    resolve_brand_kit,
)


def default_branding_profile() -> Dict[str, Any]:
    return resolve_brand_kit()


def branding_from_institution_template(template: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(template or {})
    branding = dict(payload.get("branding", {}) or {})
    if "product" in branding and "display_name" not in branding:
        branding["display_name"] = str(branding.get("product", APP_DISPLAY_NAME))
    if "short_name" not in branding and "product" in branding:
        branding["short_name"] = str(branding.get("product", APP_SHORT_NAME))
    return resolve_brand_kit(branding)


def ensure_branding_profile(profile: Dict[str, Any] | None) -> Dict[str, Any]:
    return resolve_brand_kit(profile)


def white_label_profile_for_institution(
    *,
    institution_name: str,
    owner_name: str,
    accent: str | None = None,
    support_email: str | None = None,
    documentation_url: str | None = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "display_name": f"{institution_name} Scheduler",
        "short_name": str(institution_name).strip() or APP_SHORT_NAME,
        "subtitle": "White-label academic scheduling workspace",
        "owner": str(owner_name or APP_OWNER_NAME),
        "publisher": str(owner_name or APP_PUBLISHER),
        "support_email": str(support_email or APP_SUPPORT_EMAIL),
        "documentation_url": str(documentation_url or APP_DOCUMENTATION_URL),
    }
    if accent:
        overrides["palette"] = {"accent": str(accent)}
    return resolve_brand_kit(overrides)


def about_lines(branding: Dict[str, Any] | None = None) -> list[str]:
    profile = ensure_branding_profile(branding)
    return [
        str(profile.get("display_name", APP_DISPLAY_NAME)),
        str(profile.get("subtitle", APP_SUBTITLE)),
        f"Version {str(profile.get('version', APP_VERSION))}",
        str(profile.get("copyright_line", APP_COPYRIGHT_LINE)),
        f"Support: {str(profile.get('support_email', APP_SUPPORT_EMAIL))}",
        f"Docs: {str(profile.get('documentation_url', APP_DOCUMENTATION_URL))}",
    ]


__all__ = [
    "DEFAULT_BRAND_KIT",
    "about_lines",
    "branding_from_institution_template",
    "default_branding_profile",
    "ensure_branding_profile",
    "white_label_profile_for_institution",
]
