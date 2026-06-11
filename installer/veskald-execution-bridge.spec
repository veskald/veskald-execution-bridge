# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Veskald Execution Bridge desktop binary."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
ENTRY = ROOT / "installer" / "launcher.py"

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

# macOS arch selector. Set VESKALD_TARGET_ARCH=universal2 (or arm64 / x86_64)
# before invoking pyinstaller to override the host arch.
TARGET_ARCH = os.environ.get("VESKALD_TARGET_ARCH") or None

# Project-local imports — make sure run, config, lib.* and the GUI package
# all get pulled into the bundle.
project_modules = [
    "run",
    "config",
    "lib",
    "lib.base_trader",
    "lib.binance",
    "lib.bybit",
    "lib.coinbase",
    "lib.kraken",
    "lib.okx",
    "lib.logger",
    "lib.ssl_bootstrap",
    "lib.symbols",
    "lib.trader_factory",
    "lib.userdir",
    "installer",
    "installer.ui",
    "installer.ui.app",
    "installer.ui.bot_controller",
    "installer.ui.env_store",
    "installer.ui.log_bridge",
    "installer.ui.main_window",
    "installer.ui.settings_dialog",
    "installer.ui.style",
]

hidden_imports = list(project_modules) + [
    # socket.io / engineio transports
    "engineio.async_drivers.threading",
    "engineio.async_drivers.aiohttp",
    "socketio",
    "socketio.client",
    # websocket transports
    "websocket",
    "websockets",
    "simple_websocket",
    # exchange SDKs
    "pybit",
    "pybit.unified_trading",
    "binance_common",
    "binance_common.configuration",
    "binance_common.constants",
    "binance_sdk_derivatives_trading_usds_futures",
    "binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures",
    "okx",
    "okx.Account",
    "okx.PublicData",
    "okx.Trade",
    "kraken",
    "kraken.futures",
    "coinbase",
    "coinbase.rest",
    # crypto / signing
    "cryptography",
    "cryptography.hazmat.backends.openssl",
    "pycryptodome",
    "Crypto",
    "jwt",
    # http
    "aiohttp",
    "httpx",
    "requests",
    # Qt
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

hidden_imports += collect_submodules("pybit")
hidden_imports += collect_submodules("okx")
hidden_imports += collect_submodules("kraken")
hidden_imports += collect_submodules("coinbase")
hidden_imports += collect_submodules("binance_common")
hidden_imports += collect_submodules("binance_sdk_derivatives_trading_usds_futures")
hidden_imports += collect_submodules("engineio")
hidden_imports += collect_submodules("socketio")

datas = []
datas += collect_data_files("pybit")
datas += collect_data_files("okx")
datas += collect_data_files("kraken")
datas += collect_data_files("coinbase")
datas += collect_data_files("binance_common")
datas += collect_data_files("binance_sdk_derivatives_trading_usds_futures")
datas += collect_data_files("certifi")

# importlib.metadata.version(...) calls inside several SDKs need .dist-info
# folders bundled. PyInstaller skips them by default — fix with copy_metadata.
# Each entry uses the distribution name (the one pip uses), NOT the import
# name. recursive=True walks transitive deps that may do the same lookup.
def _safe_copy_metadata(name: str):
    try:
        return copy_metadata(name, recursive=True)
    except Exception:
        try:
            return copy_metadata(name)
        except Exception:
            return []

for dist in (
    "binance-sdk-derivatives-trading-usds-futures",
    "binance-common",
    "pybit",
    "python-okx",
    "python-kraken-sdk",
    "coinbase-advanced-py",
    "python-socketio",
    "python-engineio",
    "aiohttp",
    "websockets",
    "websocket-client",
    "requests",
    "cryptography",
    "pyjwt",
    "pydantic",
):
    datas += _safe_copy_metadata(dist)

block_cipher = None

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hidden_imports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Icon picker — prefers OS-native formats if you bothered to convert them,
# otherwise falls back to logo.png (PyInstaller accepts PNG for all OSes).
def _icon():
    candidates = []
    base = ROOT / "installer" / "assets"
    if IS_WIN:
        candidates = [base / "icon.ico", base / "logo.png"]
    elif IS_MAC:
        candidates = [base / "icon.icns", base / "logo.png"]
    else:
        candidates = [base / "logo.png"]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="veskald-execution-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Windowed GUI: no console window on Windows, no terminal flash on macOS.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon(),
)

if IS_MAC:
    app = BUNDLE(
        exe,
        name="Veskald Execution Bridge.app",
        icon=_icon(),
        bundle_identifier="com.veskald.executionbridge",
        info_plist={
            "CFBundleName": "Veskald Execution Bridge",
            "CFBundleDisplayName": "Veskald Execution Bridge",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
