"""Qt application bootstrap for Veskald Execution Bridge."""
from __future__ import annotations

import os
import sys

# Suppress the stdlib console log handler — lib/logger checks this before
# adding StreamHandler so the GUI doesn't echo every line back to the terminal.
os.environ.setdefault("VESKALD_GUI_MODE", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .env_store import app_dir, env_path, read_env
from .main_window import MainWindow
from .settings_dialog import SettingsDialog
from .style import STYLE_QSS


APP_NAME = "Veskald Execution Bridge"
ORG_NAME = "Veskald"


def _set_cwd_to_app_dir() -> None:
    try:
        os.chdir(app_dir())
    except OSError:
        pass


def _configure_qt() -> None:
    """Settings that must be applied BEFORE QApplication is constructed."""
    # Qt6 high-DPI: do NOT touch AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps,
    # they are deprecated Qt5 no-ops in Qt6 and can cause ghosting.
    policy = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy is not None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(policy.PassThrough)


def _ensure_initial_settings(app: QApplication) -> bool:
    env = read_env()
    if env.get("HUB_URL") and env.get("MACHINE"):
        return True
    dialog = SettingsDialog()
    if dialog.exec() != SettingsDialog.Accepted:
        return False
    env = read_env()
    return bool(env.get("HUB_URL") and env.get("MACHINE"))


def run_app() -> int:
    _set_cwd_to_app_dir()
    _configure_qt()

    app = QApplication(sys.argv)
    # Fusion renders QSS consistently across platforms and ignores the host
    # GTK / native theme that can introduce paint trails on Wayland.
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)
    app.setStyleSheet(STYLE_QSS)

    if not _ensure_initial_settings(app):
        return 0

    window = MainWindow()
    window.show()
    return app.exec()
