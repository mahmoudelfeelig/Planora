from __future__ import annotations

import os
import random

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Keep UI tests deterministic and headless in local runs and CI.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("PYTHONHASHSEED", "0")
    os.environ.setdefault("TT_CP_WORKERS", "4")
    random.seed(0)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        nodeid = item.nodeid
        if "tests/test_ui_" in nodeid:
            item.add_marker(pytest.mark.ui)
            item.add_marker(pytest.mark.slow)
        if "tests/test_engine_cli_integration.py" in nodeid:
            item.add_marker(pytest.mark.slow)
        if "tests/test_performance_controls.py" in nodeid:
            item.add_marker(pytest.mark.slow)
