"""Wraps the bot's main loop in a worker thread with Qt signal lifecycle."""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal


class BotController(QObject):
    """Owns the worker thread, surfaces lifecycle and broker-check signals.

    Signals are emitted from the worker thread; consumers in the GUI thread
    just connect them to slots and Qt marshals across the thread boundary.
    """

    state_changed = Signal(str)           # "idle" | "starting" | "running" | "stopped" | "error"
    broker_updated = Signal(dict)         # incremental: one broker's status
    bot_error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[threading.Thread] = None
        self._state = "idle"

    @property
    def state(self) -> str:
        return self._state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._set_state("starting")
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="bot-main"
        )
        self._thread.start()

    def stop(self, join_timeout: float = 5.0) -> None:
        if not self.running:
            return
        try:
            from run import request_stop
            request_stop()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(join_timeout)
        self._set_state("stopped")

    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state)

    def _run(self) -> None:
        try:
            from run import main as run_main, reset_stop, _check_one_broker
            from lib.trader_factory import SUPPORTED_BROKERS

            reset_stop()
            # Stream broker checks so the user sees progress instead of a
            # frozen UI while we wait for 5 sequential round-trips.
            for broker in SUPPORTED_BROKERS:
                self.broker_updated.emit(
                    {"broker": broker, "status": "checking", "detail": "…"}
                )
                result = _check_one_broker(broker)
                self.broker_updated.emit(result)

            self._set_state("running")
            run_main(exit_on_missing_config=False)
            self._set_state("stopped")
        except SystemExit:
            self._set_state("stopped")
        except Exception as exc:  # noqa: BLE001
            self.bot_error.emit(str(exc))
            self._set_state("error")
