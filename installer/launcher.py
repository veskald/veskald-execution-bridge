"""Entry point for the PyInstaller-frozen Veskald Execution Bridge desktop app.

Launches the Qt GUI. On first run, the GUI opens its Settings dialog so the
user can enter Hub URL, machine token and exchange API keys; the values get
written to a .env file alongside the executable.

For headless / Docker deployments, run `python run.py` directly — this
launcher is only used for the desktop binary.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_module_path() -> None:
    """Make `installer.ui` importable when running both frozen and from source."""
    here = Path(__file__).resolve().parent
    project_root = here.parent
    for p in (str(project_root), str(here.parent)):
        if p not in sys.path:
            sys.path.insert(0, p)


def main() -> None:
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(
            "Veskald Execution Bridge — desktop app\n"
            "\n"
            "Usage:\n"
            "  veskald-execution-bridge              launch the GUI\n"
            "  veskald-execution-bridge --help       show this help\n"
            "\n"
            "Configuration is stored in a .env file next to the executable.\n"
        )
        return

    _ensure_module_path()
    from installer.ui.app import run_app
    sys.exit(run_app())


if __name__ == "__main__":
    main()
