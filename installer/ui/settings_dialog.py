"""Modal Qt dialog for entering Hub URL, machine token, and exchange API keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
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


EXCHANGES: List[ExchangeSpec] = [
    ExchangeSpec(
        label="Binance",
        fields=[
            FieldSpec("BINANCE_API_KEY", "API Key"),
            FieldSpec("BINANCE_API_SECRET", "API Secret", secret=True),
        ],
        bools=[],
        docs="USDⓈ-M Futures permissions required.",
    ),
    ExchangeSpec(
        label="Bybit",
        fields=[
            FieldSpec("BYBIT_API_KEY", "API Key"),
            FieldSpec("BYBIT_API_SECRET", "API Secret", secret=True),
        ],
        bools=[BoolSpec("BYBIT_TESTNET", "Use Bybit testnet")],
        docs="Unified Trading Account (V5) with Derivatives enabled.",
    ),
    ExchangeSpec(
        label="Kraken",
        fields=[
            FieldSpec("KRAKEN_API_KEY", "API Key"),
            FieldSpec("KRAKEN_API_SECRET", "API Secret", secret=True),
        ],
        bools=[BoolSpec("KRAKEN_SANDBOX", "Use Kraken sandbox")],
        docs="Kraken Futures keys (futures.kraken.com), not Spot.",
    ),
    ExchangeSpec(
        label="OKX",
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


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 580)
        self._fields: Dict[str, QLineEdit | QPlainTextEdit] = {}
        self._bools: Dict[str, QCheckBox] = {}

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

        layout.addStretch(1)
        return page

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
