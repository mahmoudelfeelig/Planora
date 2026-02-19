from __future__ import annotations

import os
import sys

# Ensure repo root on path when launching directly
ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from ui.window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "app_icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.resize(1300, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
