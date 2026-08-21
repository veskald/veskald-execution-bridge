"""Bridge stdlib logging records into Qt signals for live log viewers."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from lib.logger import ReadableFormatter


class LogEmitter(QObject):
    message = Signal(str, str)  # level, formatted line


class QtLogHandler(logging.Handler):
    """Forwards log records to a Qt signal, formatted for human reading."""

    # Sentinel honoured by lib.logger._configure_root_once so subsequent
    # logger reconfigure doesn't wipe us out.
    _veskald_preserve = True

    def __init__(self) -> None:
        super().__init__()
        self.setLevel(logging.DEBUG)
        self.emitter = LogEmitter()
        self.setFormatter(
            ReadableFormatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            line = self.format(record)
            self.emitter.message.emit(record.levelname, line)
        except Exception:  # pragma: no cover
            self.handleError(record)


def attach(handler: QtLogHandler) -> None:
    """Attach the handler to the veskald_bridge logger tree.

    Also makes sure the logger is at DEBUG level so the GUI sees everything.
    """
    root = logging.getLogger("veskald_bridge")
    root.setLevel(logging.DEBUG)
    if handler not in root.handlers:
        root.addHandler(handler)
