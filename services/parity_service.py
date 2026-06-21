from __future__ import annotations

from typing import Any, Dict, List


PARITY_ITEMS: List[Dict[str, Any]] = [
    {"capability": "preset_load", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "json_import", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "csv_import", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "solve", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "portfolio_solve", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "local_search_improve", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "async_progress", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "cp_sat_polish", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "score_breakdown", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "conflict_diagnostics", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "move_target_deltas", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "activity_locks", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "project_save_load", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "tenant_auth", "desktop": False, "backend": True, "web": True, "status": "web_extension"},
    {"capability": "audit_log", "desktop": False, "backend": True, "web": True, "status": "web_extension"},
    {"capability": "csv_export", "desktop": True, "backend": True, "web": True, "status": "covered"},
    {"capability": "docx_export", "desktop": True, "backend": False, "web": False, "status": "partial"},
    {"capability": "installer_update_flow", "desktop": True, "backend": False, "web": False, "status": "desktop_only"},
]


def parity_manifest() -> Dict[str, Any]:
    covered = sum(1 for item in PARITY_ITEMS if item["status"] in {"covered", "web_extension"})
    return {
        "items": list(PARITY_ITEMS),
        "covered": covered,
        "total": len(PARITY_ITEMS),
        "coverage_percent": round(100.0 * covered / max(1, len(PARITY_ITEMS)), 2),
    }
