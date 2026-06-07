"""Main desktop window — modern dark dashboard."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .bot_controller import BotController
from .env_store import env_path, read_env
from .log_bridge import QtLogHandler, attach as attach_log_handler
from .settings_dialog import SettingsDialog
from . import style


BROKERS_DISPLAY = [
    ("binance",  "Binance"),
    ("bybit",    "Bybit"),
    ("kraken",   "Kraken"),
    ("okx",      "OKX"),
    ("coinbase", "Coinbase"),
]


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


class MainWindow(QMainWindow):
    MAX_LOG_LINES = 2000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Veskald Execution Bridge")
        self.resize(1240, 820)
        self.setMinimumSize(960, 620)

        self.controller = BotController(self)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.broker_updated.connect(self._on_broker_updated)
        self.controller.bot_error.connect(self._on_bot_error)

        self.log_handler = QtLogHandler()
        self.log_handler.emitter.message.connect(self._on_log_message)
        attach_log_handler(self.log_handler)

        self._broker_rows: Dict[str, int] = {
            key: row for row, (key, _) in enumerate(BROKERS_DISPLAY)
        }

        self._build_ui()
        self._wire_shortcuts()
        self._refresh_state_label("idle")

        # Live UTC clock in the status bar.
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

    # ---- UI assembly -----------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        central.setAutoFillBackground(True)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 14)
        root.setSpacing(18)

        root.addLayout(self._build_header())

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(12)
        splitter.addWidget(self._build_brokers_panel())
        splitter.addWidget(self._build_logs_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 520])
        root.addWidget(splitter, 1)

        bar = QStatusBar()
        self.setStatusBar(bar)
        self._status_left = QLabel(self._format_cfg_path())
        self._status_right = QLabel("")
        bar.addWidget(self._status_left, 1)
        bar.addPermanentWidget(self._status_right)

    def _format_cfg_path(self) -> str:
        p = str(env_path())
        home = os.path.expanduser("~")
        if p.startswith(home):
            p = "~" + p[len(home):]
        return f"Config: {p}"

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("Idle")
        self.status_text.setObjectName("statusText")
        row.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        row.addWidget(self.status_text, 0, Qt.AlignVCenter)

        self.token_badge = QLabel("No token")
        self.token_badge.setObjectName("metaBadge")
        row.addSpacing(8)
        row.addWidget(self.token_badge, 0, Qt.AlignVCenter)

        row.addStretch(1)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("ghostButton")
        self.settings_btn.clicked.connect(self._open_settings)
        row.addWidget(self.settings_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._on_start_clicked)
        row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        return row

    def _build_brokers_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(_section_label("Exchanges"))

        self.broker_table = QTableWidget(len(BROKERS_DISPLAY), 3)
        self.broker_table.setHorizontalHeaderLabels(["Exchange", "Status", "Detail"])
        self.broker_table.verticalHeader().setVisible(False)
        self.broker_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.broker_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.broker_table.setFocusPolicy(Qt.NoFocus)
        self.broker_table.setShowGrid(False)
        self.broker_table.setAlternatingRowColors(True)
        self.broker_table.verticalHeader().setDefaultSectionSize(52)
        self.broker_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.broker_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.broker_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for row, (_, label) in enumerate(BROKERS_DISPLAY):
            self.broker_table.setItem(row, 0, QTableWidgetItem(label))
            self.broker_table.setItem(row, 1, QTableWidgetItem("Not checked"))
            self.broker_table.setItem(row, 2, QTableWidgetItem(""))
            self.broker_table.item(row, 1).setForeground(QBrush(QColor(style.TEXT_MUTED)))
        layout.addWidget(self.broker_table, 1)
        return panel

    def _build_logs_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(_section_label("Activity"))
        header.addStretch(1)
        clear = QPushButton("Clear")
        clear.setObjectName("ghostButton")
        clear.clicked.connect(lambda: self.log_view.clear())
        header.addWidget(clear)
        layout.addLayout(header)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self.MAX_LOG_LINES)
        layout.addWidget(self.log_view, 1)
        return panel

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._open_settings)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._restart_app)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.log_view.clear)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._toggle_start_stop)

    def _toggle_start_stop(self) -> None:
        if self.controller.running:
            self._on_stop_clicked()
        else:
            self._on_start_clicked()

    # ---- Slots -----------------------------------------------------------

    @Slot(str)
    def _on_state_changed(self, state: str) -> None:
        self._refresh_state_label(state)
        running = state in ("starting", "running")
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _refresh_state_label(self, state: str) -> None:
        color, text = style.STATUS_COLORS.get(state, (style.TEXT_MUTED, state.title()))
        self.status_dot.setStyleSheet(f"font-size: 32pt; color: {color}; background-color: transparent;")
        self.status_text.setStyleSheet(
            f"font-size: 32pt; font-weight: 700; color: {color}; background-color: transparent;"
        )
        self.status_text.setText(text)
        env = read_env()
        token = env.get("MACHINE") or ""
        if token:
            self.token_badge.setText(f"Machine · {token[:8]}…")
        else:
            self.token_badge.setText("No token")

    @Slot(dict)
    def _on_broker_updated(self, result: dict) -> None:
        broker = result.get("broker")
        if broker not in self._broker_rows:
            return
        row = self._broker_rows[broker]
        status = result.get("status", "?")
        detail = result.get("detail", "")
        label = style.BROKER_STATUS_LABEL.get(status, status.title())
        color = style.BROKER_STATUS_COLORS.get(status, style.TEXT)
        item = self.broker_table.item(row, 1)
        item.setText(label)
        item.setForeground(QBrush(QColor(color)))
        self.broker_table.item(row, 2).setText(detail)
        self.broker_table.item(row, 2).setForeground(QBrush(QColor(style.TEXT_DIM)))

    @Slot(str, str)
    def _on_log_message(self, level: str, line: str) -> None:
        color = style.LOG_LEVEL_COLORS.get(level, style.TEXT)
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log_view.appendHtml(f'<span style="color:{color}">{safe}</span>')

    @Slot(str)
    def _on_bot_error(self, message: str) -> None:
        QMessageBox.critical(self, "Bot error", message)

    def _tick_clock(self) -> None:
        now = datetime.utcnow().strftime("%H:%M:%S")
        self._status_right.setText(f"UTC {now}")

    # ---- Actions ---------------------------------------------------------

    def _ensure_configured(self) -> bool:
        env = read_env()
        if env.get("HUB_URL") and env.get("MACHINE"):
            return True
        self._open_settings()
        env = read_env()
        return bool(env.get("HUB_URL") and env.get("MACHINE"))

    def _on_start_clicked(self) -> None:
        if not self.start_btn.isEnabled():
            return
        if not self._ensure_configured():
            return
        self.controller.start()

    def _on_stop_clicked(self) -> None:
        if not self.stop_btn.isEnabled():
            return
        self.controller.stop()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            ret = QMessageBox.question(
                self,
                "Restart to apply",
                "Settings saved. Restart the app to apply the new values?\n\n"
                "(Required even when the bot is stopped — config is cached "
                "at module load time.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ret == QMessageBox.Yes:
                self._restart_app()
        self._refresh_state_label(self.controller.state)

    def _restart_app(self) -> None:
        self.controller.stop()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ---- Window lifecycle ------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.controller.running:
            self.controller.stop()
        super().closeEvent(event)
