from __future__ import annotations

import os
import sys
import traceback

# Ensure repo root on path when launching directly
ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

def _resource_path(*parts: str) -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = ROOT_DIR
    return os.path.normpath(os.path.join(base, *parts))


def _run_engine_cli_if_requested() -> int | None:
    if len(sys.argv) < 2 or sys.argv[1] != "--engine-cli":
        return None
    from core.engine_cli import main as engine_main

    # Re-shape argv to the format expected by core/engine_cli.py:
    # <program> <instance_pickle_path> <result_pickle_path>
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    return int(engine_main())


def __getattr__(name: str):
    if name == "MainWindow":
        from ui.window import MainWindow as _MainWindow

        return _MainWindow
    raise AttributeError(name)


def main() -> None:
    cli_code = _run_engine_cli_if_requested()
    if cli_code is not None:
        raise SystemExit(cli_code)

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    from services.runtime_ops_service import (
        default_runtime_paths,
        load_runtime_settings,
        write_crash_report,
    )
    from ui.constants import APP_DISPLAY_NAME, APP_PUBLISHER, APP_SHORT_NAME
    from ui.window import MainWindow

    runtime_paths = default_runtime_paths(APP_SHORT_NAME)
    runtime_settings = load_runtime_settings(runtime_paths["settings"])

    def _excepthook(exc_type, exc, tb) -> None:
        traceback_text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            write_crash_report(
                runtime_paths["crash_dir"],
                error_type=str(getattr(exc_type, "__name__", "Exception")),
                message=str(exc),
                traceback_text=traceback_text,
                context={"source": "ui_app"},
                opt_in=bool(runtime_settings.get("crash_reports_opt_in", False)),
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setApplicationName(APP_SHORT_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_PUBLISHER)
    icon_path = _resource_path("app_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
