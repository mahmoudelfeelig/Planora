from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def build_calendar_sync_bundle(manifest: Dict[str, Any], *, base_url: str = "") -> Dict[str, Any]:
    feeds = dict(manifest.get("feeds", {}) or {})
    base = str(base_url or "").rstrip("/")

    def _url(path: str) -> str:
        rel = str(path).replace("\\", "/")
        if base:
            return f"{base}/{rel.lstrip('./')}"
        return rel

    bundle = {
        "providers": {
            "google": [],
            "outlook": [],
        }
    }
    for scope, entries in feeds.items():
        if not isinstance(entries, list):
            continue
        for path in entries:
            url = _url(str(path))
            bundle["providers"]["google"].append({"scope": str(scope), "url": url})
            bundle["providers"]["outlook"].append({"scope": str(scope), "url": url})
    return bundle


def write_calendar_sync_bundle(path: str | Path, bundle: Dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(bundle, indent=2), encoding="utf-8")
