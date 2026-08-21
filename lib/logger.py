import datetime
import logging
import os
import sys
from typing import Any, Dict, Optional

from config import GRAYLOG_HOST, GRAYLOG_PORT, MACHINE_TOKEN, UNIQUE_ID
from lib.userdir import app_logs_dir


LOGS_DIR = str(app_logs_dir())

DEFAULT_CTX = "veskald_bridge"


_STANDARD_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "ctx", "machine_token", "user_id", "timestamp",
    "message", "asctime", "extra", "taskName",
}


# Commands carry credentials (e.g. the KuCoin broker key), and log files and
# Graylog are shared far more widely than the host itself — mask any field
# that looks like a secret before it reaches a sink.
_SECRET_NAME_HINTS = ("secret", "passphrase", "password", "token", "key")
_MASK = "***"
_MAX_MASK_DEPTH = 6


def _is_secret_name(name: Any) -> bool:
    lowered = str(name).lower()
    return any(hint in lowered for hint in _SECRET_NAME_HINTS)


def _mask_secrets(value: Any, depth: int = 0) -> Any:
    """Copies `value` with secret-looking fields masked.

    Returns new containers so the caller's command dict — which the traders
    still need intact to sign requests — is never touched.
    """
    if depth >= _MAX_MASK_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            k: _MASK if _is_secret_name(k) else _mask_secrets(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_secrets(v, depth + 1) for v in value]
    return value


class ContextFilter(logging.Filter):
    """Injects context into every LogRecord and masks secrets in its extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = DEFAULT_CTX
        record.machine_token = MACHINE_TOKEN
        record.user_id = UNIQUE_ID
        record.timestamp = int(
            datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        )
        extra = {}
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_RECORD_KEYS:
                continue
            safe = _MASK if _is_secret_name(key) else _mask_secrets(value)
            # Write back: graypy's extra_fields reads record attributes
            # directly rather than going through record.extra.
            setattr(record, key, safe)
            extra[key] = safe
        record.extra = extra
        return True


# Shared instance: attached both per-logger (runs before any handler, whatever
# order handlers were added in) and per-handler. Filtering is idempotent.
_CTX_FILTER = ContextFilter()


def _format_extra(extra: Dict[str, Any], indent: int = 0) -> str:

    if not extra:
        return ""
    parts = []
    prefix = "  " * indent
    for key, value in extra.items():
        if isinstance(value, dict):
            parts.append(f"{prefix}{key}:")
            parts.append(_format_extra(value, indent + 1))
        elif isinstance(value, list):
            parts.append(f"{prefix}{key}: [")
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    parts.append(f"{prefix}  [{i}]:")
                    parts.append(_format_extra(item, indent + 2))
                else:
                    parts.append(f"{prefix}  [{i}]: {item}")
            parts.append(f"{prefix}]")
        else:
            parts.append(f"{prefix}{key}: {value}")
    return "\n".join(parts) if indent > 0 else "\n" + "\n".join(parts)


class ReadableFormatter(logging.Formatter):
    """Appends the extras block to its own output only.

    Must not mutate the record: other handlers (console, GUI, Graylog)
    format the same record and would inherit the appended block.
    """

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict) and extra:
            formatted += _format_extra(extra)
        return formatted



_root_configured = False


def _configure_root_once() -> None:
    global _root_configured
    if _root_configured:
        return

    root = logging.getLogger("veskald_bridge")
    root.setLevel(logging.DEBUG)

    root.propagate = False


    # Drop any prior handlers EXCEPT ones the GUI attached (marked sentinel).
    for h in list(root.handlers):
        if getattr(h, "_veskald_preserve", False):
            continue
        root.removeHandler(h)


    ctx_filter = _CTX_FILTER


    log_file = os.path.join(LOGS_DIR, "veskald_bridge.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(ctx_filter)
    file_handler.setFormatter(ReadableFormatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s "
        "[%(ctx)s] [%(machine_token)s] [%(user_id)s]"
    ))
    root.addHandler(file_handler)

    if GRAYLOG_HOST:
        try:
            import graypy
            gelf_handler = graypy.GELFUDPHandler(
                GRAYLOG_HOST,
                GRAYLOG_PORT,
                extra_fields=True,
                debugging_fields=False,
            )
            gelf_handler.setLevel(logging.DEBUG)
            gelf_handler.addFilter(ctx_filter)
            root.addHandler(gelf_handler)
        except Exception as e:
            sys.stderr.write(f"[logger] Graylog handler init failed: {e}\n")


    # Skip the console handler when there's no point printing to a terminal:
    #   - frozen desktop binary (no terminal attached)
    #   - explicit GUI mode (set by installer/ui/app.py before import)
    # In either case the in-app log viewer is the user-facing sink.
    in_gui = bool(os.environ.get("VESKALD_GUI_MODE"))
    if not getattr(sys, "frozen", False) and not in_gui:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(ReadableFormatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        ))
        root.addHandler(console_handler)

    _root_configured = True


def get_logger(name: str) -> logging.Logger:

    _configure_root_once()
    full_name = name if name.startswith("veskald_bridge") else f"veskald_bridge.{name}"
    logger = logging.getLogger(full_name)
    logger.setLevel(logging.DEBUG)
    # Masking must run before every handler, including ones attached elsewhere
    # (the desktop app's Qt viewer). A logger-level filter runs first; addFilter
    # is a no-op when the instance is already there.
    logger.addFilter(_CTX_FILTER)

    return logger


class Logger:

    def __new__(cls, name: str) -> logging.Logger:  # type: ignore[misc]
        return get_logger(name)