import signal
import threading
import time
from queue import Empty, Queue
from typing import Dict, Optional
import sys

from lib.ssl_bootstrap import apply as _apply_ssl_bootstrap
_apply_ssl_bootstrap()

import socketio

import lib.base_trader
from config import HUB_URL, MACHINE_TOKEN, has_credentials
from lib.logger import get_logger
from lib.trader_factory import build_trader, SUPPORTED_BROKERS

logger = get_logger("Main")
# main() runs its own reconnect loop with backoff. The library's auto
# reconnect would race it and double every connection attempt — that hammering
# is what gets the machine token temporarily blocked by the hub.
sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

_command_queue: "Queue[dict]" = Queue()
_stop_event = threading.Event()
_worker_thread: Optional[threading.Thread] = None

ORPHAN_SWEEP_INTERVAL_SEC = 300.0


def request_stop() -> None:
    """Ask the bot loop to exit and disconnect the socket.

    Safe to call from any thread (used by the desktop GUI's Stop button).
    """
    _stop_event.set()
    try:
        if sio.connected:
            sio.disconnect()
    except Exception:
        pass


def reset_stop() -> None:
    """Clear the stop flag so main() can be re-entered after a previous stop."""
    _stop_event.clear()


def install_signal_handlers() -> None:
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):  # Windows console close
        sigs.append(signal.SIGBREAK)

    def _handle(signum, frame) -> None:
        for s in sigs:
            try:
                signal.signal(s, signal.SIG_DFL)
            except (ValueError, OSError):
                pass
        try:
            logger.info(f"Got {signal.Signals(signum).name} — shutting down")
        except Exception:
            pass
        request_stop()

    for s in sigs:
        try:
            signal.signal(s, _handle)
        except (ValueError, OSError):
            pass


def _execute_command(data: dict) -> None:
    try:
        trader = build_trader(data)
        result = trader.execute_action()
        if result:
            logger.info(
                "Sending report to server",
                extra={"order_id": result, "broker": data.get("broker")},
            )
            try:
                sio.emit(
                    "command.result",
                    {
                        "ex_order_id": result,
                        "strategy": data.get("strategy"),
                        "broker": data.get("broker"),
                    },
                    namespace="/machines",
                )
                logger.info("Report sent")
            except Exception as e:
                logger.error(
                    "Failed to send report",
                    extra={"error": str(e), "order_id": result},
                )
    except Exception as e:
        logger.error(
            "Worker error while executing command",
            extra={"error": str(e), "data": data},
            exc_info=True,
        )


def _sweep_orphan_orders() -> None:
    if not lib.base_trader.ORPHAN_CLEANUP_ENABLED:
        return
    for broker in SUPPORTED_BROKERS:
        if not has_credentials(broker):
            continue
        try:
            build_trader({"broker": broker}).cancel_orphan_orders()
        except Exception as e:
            logger.error(
                "Orphan order sweep failed",
                extra={"broker": broker, "error": str(e)},
                exc_info=True,
            )


def _worker_step(next_sweep: float, now: float) -> float:
    """Runs a due orphan sweep or one queued command; returns the next sweep time.

    Sweeps share the command thread, so they never interleave with the
    bridge's own order placement.
    """
    if now >= next_sweep:
        if not _stop_event.is_set():
            _sweep_orphan_orders()
        return now + ORPHAN_SWEEP_INTERVAL_SEC
    try:
        data = _command_queue.get(timeout=next_sweep - now)
    except Empty:
        return next_sweep
    try:
        _execute_command(data)
    finally:
        _command_queue.task_done()
    return next_sweep


def _worker_loop() -> None:
    next_sweep = time.monotonic()
    while True:
        next_sweep = _worker_step(next_sweep, time.monotonic())


def _start_worker() -> None:
    # The desktop app re-enters main() after Stop; a second worker would run
    # commands and sweeps in parallel with the first.
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(
            target=_worker_loop, daemon=True, name="cmd-worker",
        )
        _worker_thread.start()


@sio.event(namespace="/machines")
def connect() -> None:
    logger.info("CONNECTED to STREAM")
    logger.info("Waiting for commands...")


@sio.event(namespace="/machines")
def disconnect() -> None:
    logger.info("Disconnected from STREAM")


@sio.on("service.msg", namespace="/machines")
def on_service_msg(data) -> None:
    logger.info("Received service message", extra={"raw_data": data})


@sio.on("command.run", namespace="/machines")
def on_command_run(data) -> None:
    logger.info("Received command from socket", extra={"raw_data": data})
    if not isinstance(data, dict):
        logger.error("Invalid command payload — not a dict", extra={"raw_data": data})
        return
    if not data.get("broker"):
        data["broker"] = "binance"
        logger.warning("Command without broker — defaulting to binance",
                       extra={"raw_data": data})
    _command_queue.put(data)


# The hub rejects the connection on the /machines namespace, so the handler
# must be bound to it — a bare handler would sit on "/" and never fire.
@sio.on("connect_error", namespace="/machines")
def connect_error(*args) -> None:
    reason = args[0] if args else "no reason given by hub"
    logger.error(f"Hub rejected /machines connection: {reason!r}",
                 extra={"data": args})


def _check_one_broker(broker: str) -> Dict[str, str]:
    if not has_credentials(broker):
        return {"broker": broker, "status": "skip",
                "detail": "no credentials in env"}
    try:
        trader = build_trader({"broker": broker})
        mode = trader.get_position_mode()
        if mode is None:
            return {"broker": broker, "status": "error",
                    "detail": "could not resolve position mode (auth/perms?)"}
        return {"broker": broker, "status": "ok",
                "detail": f"position_mode={mode}"}
    except Exception as e:  # noqa: BLE001
        return {"broker": broker, "status": "error", "detail": str(e)}


def _startup_check() -> None:
    logger.info("Startup: checking API connectivity for all brokers")

    results = []
    for broker in SUPPORTED_BROKERS:
        result = _check_one_broker(broker)
        results.append(result)
        if result["status"] == "ok":
            logger.info(f"[{broker:8s}] OK — {result['detail']}")
        elif result["status"] == "error":
            logger.error(f"[{broker:8s}] FAIL — {result['detail']}")

    skipped = [r["broker"] for r in results if r["status"] == "skip"]
    if skipped:
        logger.info(f"Skipped (no credentials in env): {', '.join(skipped)}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = sum(1 for r in results if r["status"] == "error")
    skip_count = sum(1 for r in results if r["status"] == "skip")
    logger.info(
        f"Brokers: {ok_count} active, {fail_count} failing, {skip_count} skipped"
    )

    if ok_count == 0:
        logger.warning(
            "No brokers passed health check — bot will accept commands but "
            "all of them will fail. Check API keys in .env."
        )


def main(exit_on_missing_config: bool = True) -> None:

    if not HUB_URL or not MACHINE_TOKEN:
        logger.error(
            "HUB_URL or MACHINE_TOKEN not set in environment — refusing to start. "
            "Check that .env is loaded (docker compose / --env-file)."
        )
        if exit_on_missing_config:
            sys.exit(1)
        return

    _startup_check()

    _start_worker()

    backoff = 5
    while not _stop_event.is_set():
        try:
            if not sio.connected:
                logger.info(f"Connecting to {HUB_URL}...")
                sio.connect(
                    HUB_URL,
                    namespaces=["/machines"],
                    auth={"token": MACHINE_TOKEN},
                    transports=["websocket"],
                    wait_timeout=5,
                )
                backoff = 5
            sio.wait()
            if _stop_event.is_set():
                break
        except Exception as e:
            if _stop_event.is_set():
                break
            try:
                if sio.connected:
                    sio.disconnect()
            except Exception:
                pass
            logger.error(
                f"Connect error: {e!r} (backoff {backoff}s)",
                extra={"error": repr(e), "backoff": backoff},
                exc_info=True,
            )
            # Sleep in small slices so a stop request is honoured quickly.
            for _ in range(backoff * 10):
                if _stop_event.is_set():
                    break
                time.sleep(0.1)
            backoff = min(backoff * 2, 60)

    logger.info("Bot loop exited")


if __name__ == "__main__":
    from config import UNIQUE_ID, ENV_UNIQUE_ID, LOCAL_UNIQUE_ID

    print("==========================================")
    print(f"           UNIQUE_ID: {UNIQUE_ID}")
    print(f"       SET_UNIQUE_ID: {ENV_UNIQUE_ID}")
    print(f" GENERATED_UNIQUE_ID: {LOCAL_UNIQUE_ID}")
    print("==========================================")
    install_signal_handlers()
    try:
        main()
    except KeyboardInterrupt:
        request_stop()