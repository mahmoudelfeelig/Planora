from __future__ import annotations

from typing import Dict


DEFAULT_FEATURE_FLAGS: Dict[str, bool] = {
    "versioned_projects": True,
    "rule_registry": True,
    "service_backend": True,
    "benchmark_guards": True,
    "calendar_overrides": False,
    "multi_campus": False,
    "publish_workflow": False,
    "portfolio_solves": False,
    "api_mode": False,
    "legacy_instance_embed": True,
}

