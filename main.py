#!/usr/bin/env python3
"""Snapshotter application entry point."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"


def _missing_dependency_message(error: ImportError) -> str:
    return (
        f"Snapshotter could not start because a dependency is missing ({error.name}).\n\n"
        "Re-run install.sh to repair the installation, or install the requirements with:\n"
        "  pip install -r requirements.txt"
    )


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("SNAPSHOTTER_DEBUG") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        from PySide6.QtGui import QGuiApplication, QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as exc:
        print(_missing_dependency_message(exc), file=sys.stderr)
        return 1

    # argv[0] becomes the X11 WM_CLASS instance name; keep it stable.
    app = QApplication(["snapshotter", *sys.argv[1:]])
    app.setApplicationName("Snapshotter")
    app.setApplicationDisplayName("Snapshotter")
    # Matches snapshotter.desktop so Wayland compositors show the right icon.
    QGuiApplication.setDesktopFileName("snapshotter")

    icon = QIcon(str(ASSETS / "icon.svg"))
    icon.addFile(str(ASSETS / "icon.png"))
    app.setWindowIcon(icon)

    try:
        import yt_dlp  # noqa: F401 - verify before building the UI

        from app import styles
        from app.window import MainWindow
    except ImportError as exc:
        QMessageBox.critical(None, "Snapshotter", _missing_dependency_message(exc))
        return 1

    styles.apply_theme(app)
    window = MainWindow(icon)
    window.show()
    code = app.exec()

    if not window.wait_for_worker(5000):
        # A blocking network call is ignoring cancellation; don't let Qt abort
        # on a still-running QThread during interpreter shutdown.
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
