"""Modal Qt dialog for entering Hub URL, machine token, and exchange API keys."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .env_store import read_env, write_env, env_path

DEFAULT_HUB_URL = "https://stream.veskald.com"


@dataclass
class FieldSpec:
    key: str
    label: str
    secret: bool = False
    multiline: bool = False
    placeholder: str = ""


@dataclass
class BoolSpec:
    key: str
    label: str
    default: bool = False


@dataclass
class ExchangeSpec:
    label: str
    fields: List[FieldSpec]
    bools: List[BoolSpec]
    docs: str = ""
    broker: str = ""
    mode_switch: bool = False


EXCHANGES: List[ExchangeSpec] = [
    ExchangeSpec(
        label="Binance",
        broker="binance",
        mode_switch=True,
        fields=[
            FieldSpec("BINANCE_API_KEY", "API Key"),
            FieldSpec("BINANCE_API_SECRET", "API Secret", secret=True),
        ],
        bools=[],
        docs="USDⓈ-M Futures permissions required.",
    ),
    ExchangeSpec(
        label="Bybit",
        broker="bybit",
        mode_switch=True,
        fields=[
            FieldSpec("BYBIT_API_KEY", "API Key"),
            FieldSpec("BYBIT_API_SECRET", "API Secret", secret=True),
        ],
        bools=[BoolSpec("BYBIT_TESTNET", "Use Bybit testnet")],
        docs="Unified Trading Account (V5) with Derivatives enabled.",
    ),
    ExchangeSpec(
        label="Kraken",
        broker="kraken",
        fields=[
            FieldSpec("KRAKEN_API_KEY", "API Key"),
            FieldSpec("KRAKEN_API_SECRET", "API Secret", secret=True),
        ],
        bools=[BoolSpec("KRAKEN_SANDBOX", "Use Kraken sandbox")],
        docs="Kraken Futures keys (futures.kraken.com), not Spot.",
    ),
    ExchangeSpec(
        label="OKX",
        broker="okx",
        mode_switch=True,
        fields=[
            FieldSpec("OKX_API_KEY", "API Key"),
            FieldSpec("OKX_API_SECRET", "API Secret", secret=True),
            FieldSpec("OKX_API_PASSPHRASE", "Passphrase", secret=True),
        ],
        bools=[
            BoolSpec("OKX_DEMO", "Use OKX demo trading"),
            BoolSpec("OKX_DEFAULT_ISOLATED", "Default to isolated margin"),
        ],
        docs="V5 API key with SWAP / trade permissions.",
    ),
    ExchangeSpec(
        label="Coinbase",
        broker="coinbase",
        fields=[
            FieldSpec("COINBASE_API_KEY", "API Key", placeholder="organizations/.../apiKeys/..."),
            FieldSpec(
                "COINBASE_API_SECRET",
                "Private Key (multi-line PEM)",
                secret=True,
                multiline=True,
                placeholder="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----",
            ),
            FieldSpec(
                "COINBASE_INTX_PORTFOLIO_UUID",
                "INTX Portfolio UUID (optional)",
            ),
        ],
        bools=[],
        docs="Advanced Trade / INTX. Paste the full PEM private key.",
    ),
    ExchangeSpec(
        label="KuCoin",
        broker="kucoin",
        mode_switch=True,
        fields=[
            FieldSpec("KUCOIN_API_KEY", "API Key"),
            FieldSpec("KUCOIN_API_SECRET", "API Secret", secret=True),
            FieldSpec("KUCOIN_API_PASSPHRASE", "Passphrase", secret=True),
        ],
        bools=[],
        docs="KuCoin Futures API key with Futures trade permission.",
    ),
    ExchangeSpec(
        label="Hyperliquid",
        broker="hyperliquid",
        fields=[
            FieldSpec("HYPERLIQUID_ACCOUNT_ADDRESS", "Account address", placeholder="0x…"),
            FieldSpec("HYPERLIQUID_PRIVATE_KEY", "API wallet private key", secret=True),
        ],
        bools=[BoolSpec("HYPERLIQUID_TESTNET", "Testnet")],
        docs="Perpetuals. Create an API wallet at app.hyperliquid.xyz/API and paste "
             "its private key; the account address is your main wallet.",
    ),
]


def _make_secret_field(placeholder: str = "") -> tuple[QWidget, QLineEdit, QPushButton]:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    line = QLineEdit()
    line.setEchoMode(QLineEdit.Password)
    line.setPlaceholderText(placeholder)
    reveal = QPushButton("Show")
    reveal.setObjectName("ghostButton")
    reveal.setCheckable(True)
    reveal.setFixedWidth(72)

    def _toggle(checked: bool) -> None:
        line.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        reveal.setText("Hide" if checked else "Show")

    reveal.toggled.connect(_toggle)
    row.addWidget(line, 1)
    row.addWidget(reveal, 0)
    return container, line, reveal


class _ModeSwitchSignals(QObject):
    # Emitted from a worker thread; queued back onto the GUI thread by Qt.
    done = Signal(str, str, bool, str)  # exchange label, mode, ok, detail


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 580)
        self._fields: Dict[str, QLineEdit | QPlainTextEdit] = {}
        self._bools: Dict[str, QCheckBox] = {}
        self._mode_buttons: Dict[str, List[QPushButton]] = {}
        self._mode_signals = _ModeSwitchSignals()
        self._mode_signals.done.connect(self._on_mode_switched)

        existing = read_env()
        self._build_ui(existing)

    # ---- UI assembly -----------------------------------------------------

    def _build_ui(self, existing: Dict[str, str]) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            f"Configuration is stored in <code>{env_path()}</code>. Restart the "
            f"bot from the main window after saving."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        tabs = QTabWidget()
        tabs.addTab(self._build_veskald_tab(existing), "Veskald")
        for ex in EXCHANGES:
            tabs.addTab(self._build_exchange_tab(ex, existing), ex.label)
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_veskald_tab(self, existing: Dict[str, str]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        hub = QLineEdit(existing.get("HUB_URL") or DEFAULT_HUB_URL)
        form.addRow("Hub URL:", hub)
        self._fields["HUB_URL"] = hub

        token_widget, token_line, _reveal = _make_secret_field("paste machine token")
        token_line.setText(existing.get("MACHINE", ""))
        form.addRow("Machine token:", token_widget)
        self._fields["MACHINE"] = token_line

        unique_id = QLineEdit(existing.get("UNIQUE_ID", ""))
        unique_id.setPlaceholderText("auto-generated if blank")
        form.addRow("Unique ID (optional):", unique_id)
        self._fields["UNIQUE_ID"] = unique_id

        hint = QLabel(
            "Get a machine token from your dashboard at "
            "<a href='https://app.veskald.com/notifications'>app.veskald.com/notifications</a>."
        )
        hint.setOpenExternalLinks(True)
        hint.setWordWrap(True)
        form.addRow(hint)
        return page

    def _build_exchange_tab(self, ex: ExchangeSpec, existing: Dict[str, str]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        if ex.docs:
            note = QLabel(ex.docs)
            note.setWordWrap(True)
            layout.addWidget(note)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)

        for spec in ex.fields:
            if spec.multiline:
                edit = QPlainTextEdit()
                edit.setPlaceholderText(spec.placeholder)
                edit.setPlainText(existing.get(spec.key, ""))
                edit.setFixedHeight(140)
                form.addRow(f"{spec.label}:", edit)
                self._fields[spec.key] = edit
            elif spec.secret:
                container, line, _reveal = _make_secret_field(spec.placeholder)
                line.setText(existing.get(spec.key, ""))
                form.addRow(f"{spec.label}:", container)
                self._fields[spec.key] = line
            else:
                line = QLineEdit(existing.get(spec.key, ""))
                line.setPlaceholderText(spec.placeholder)
                form.addRow(f"{spec.label}:", line)
                self._fields[spec.key] = line

        for spec in ex.bools:
            cb = QCheckBox(spec.label)
            cb.setChecked(existing.get(spec.key, "").lower() == "true")
            layout.addWidget(cb)
            self._bools[spec.key] = cb

        if ex.mode_switch:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(QLabel("Position mode:"))
            btn_one = QPushButton("One-way")
            btn_hedge = QPushButton("Hedge")
            btn_one.clicked.connect(
                lambda _=False, e=ex: self._switch_mode(e, "ONE_WAY"))
            btn_hedge.clicked.connect(
                lambda _=False, e=ex: self._switch_mode(e, "HEDGE"))
            row.addWidget(btn_one)
            row.addWidget(btn_hedge)
            row.addStretch(1)
            layout.addLayout(row)
            self._mode_buttons[ex.label] = [btn_one, btn_hedge]

            mode_note = QLabel(
                "Hedge mode is required to run long and short strategies on "
                "the same asset. Applies on the exchange immediately using "
                "the saved keys; exchanges reject the switch while positions "
                "or orders are open."
            )
            mode_note.setWordWrap(True)
            layout.addWidget(mode_note)

        layout.addStretch(1)
        return page

    # ---- Position mode switching ----------------------------------------

    def _switch_mode(self, ex: ExchangeSpec, mode: str) -> None:
        for b in self._mode_buttons.get(ex.label, []):
            b.setEnabled(False)
        threading.Thread(
            target=self._switch_mode_worker, args=(ex, mode), daemon=True,
        ).start()

    def _switch_mode_worker(self, ex: ExchangeSpec, mode: str) -> None:
        try:
            from config import has_credentials
            if not has_credentials(ex.broker):
                self._mode_signals.done.emit(
                    ex.label, mode, False,
                    "No saved API keys — save settings and restart the app "
                    "first.",
                )
                return
            from lib.trader_factory import build_trader
            trader = build_trader({"broker": ex.broker})
            ok = trader.set_position_mode(mode)
            detail = "" if ok else (
                "Exchange refused the switch — check the Logs tab. Open "
                "positions or orders usually block it."
            )
            self._mode_signals.done.emit(ex.label, mode, ok, detail)
        except Exception as exc:  # noqa: BLE001
            self._mode_signals.done.emit(ex.label, mode, False, str(exc))

    def _on_mode_switched(
        self, label: str, mode: str, ok: bool, detail: str
    ) -> None:
        for b in self._mode_buttons.get(label, []):
            b.setEnabled(True)
        pretty = "hedge" if mode == "HEDGE" else "one-way"
        if ok:
            QMessageBox.information(
                self, "Position mode", f"{label}: switched to {pretty} mode.")
        else:
            QMessageBox.warning(
                self, "Position mode",
                f"{label}: switch to {pretty} mode failed. {detail}")

    # ---- Save ------------------------------------------------------------

    def _gather(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QPlainTextEdit):
                values[key] = widget.toPlainText().strip()
            else:
                values[key] = widget.text().strip()
        for key, cb in self._bools.items():
            values[key] = "true" if cb.isChecked() else "false"
        return values

    def _on_save(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        values = self._gather()
        if not values.get("HUB_URL") or not values.get("MACHINE"):
            QMessageBox.warning(
                self,
                "Missing required fields",
                "Hub URL and Machine token are required to run the bot.",
            )
            return
        try:
            saved_path = write_env(values)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Couldn't save settings",
                f"Failed to write {env_path()}:\n\n{exc}\n\n"
                "The config directory may be read-only.",
            )
            return
        self.accept()
