from __future__ import annotations

import os
import random

import pytest

_QT_WIDGETS_AVAILABLE: bool | None = None


def _qt_widgets_available() -> bool:
    global _QT_WIDGETS_AVAILABLE
    if _QT_WIDGETS_AVAILABLE is not None:
        return bool(_QT_WIDGETS_AVAILABLE)
    try:
        import PyQt6.QtWidgets  # noqa: F401

        _QT_WIDGETS_AVAILABLE = True
    except Exception:
        _QT_WIDGETS_AVAILABLE = False
    return bool(_QT_WIDGETS_AVAILABLE)


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


def pytest_ignore_collect(collection_path, config: pytest.Config) -> bool:
    """
    Gracefully skip UI tests in environments where Qt runtime libs are unavailable
    (e.g., missing libEGL/libGL in minimal Linux CI images).
    """
    path_str = str(collection_path)
    if "tests/test_ui_" in path_str and not _qt_widgets_available():
        return True
    return False
