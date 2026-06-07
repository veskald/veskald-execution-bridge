"""User-writable config / state directory.

PyInstaller's sys.executable can point inside read-only or transient
filesystems:
  - AppImage:  /tmp/.mount_*/usr/bin/...  (squashfs, read-only, new path
               every launch)
  - macOS .app: writing inside the bundle violates Gatekeeper assumptions
  - Windows .exe: may live under Program Files (no user write)

So when frozen we route persistent state to the OS-standard user config
dir; from source we keep the project root for developer convenience.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIRNAME_NIX = "veskald-execution-bridge"
APP_DIRNAME_OS  = "Veskald Execution Bridge"


def app_config_dir() -> Path:
    """Resolve and ensure-existence of the writable config directory."""
    path = _platform_config_dir() if getattr(sys, "frozen", False) else _source_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def app_logs_dir() -> Path:
    """Where rolling logs go. Honours VESKALD_LOGS_DIR override."""
    override = os.environ.get("VESKALD_LOGS_DIR")
    if override:
        path = Path(override)
    elif getattr(sys, "frozen", False):
        path = _platform_config_dir() / "logs"
    else:
        path = _source_dir() / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _source_dir() -> Path:
    # lib/userdir.py → lib/ → project root.
    return Path(__file__).resolve().parents[1]


def _platform_config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIRNAME_OS
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRNAME_OS
    # Linux + other unixes — follow XDG.
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIRNAME_NIX