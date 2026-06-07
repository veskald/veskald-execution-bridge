import datetime
import logging
import os
import sys
from typing import Any, Dict, Optional

from config import MACHINE_TOKEN, UNIQUE_ID
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


class ContextFilter(logging.Filter):
    """Инжектит контекст в каждый LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = DEFAULT_CTX
        record.machine_token = MACHINE_TOKEN
        record.user_id = UNIQUE_ID
        record.timestamp = int(
            datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        )
        record.extra = {
            k: v for k, v in record.__dict__.items()
            if k not in _STANDARD_RECORD_KEYS
        }
        return True


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


    def format(self, record: logging.LogRecord) -> str:
        extra = getattr(record, "extra", None)
        if extra and isinstance(extra, dict) and extra:
            record.msg = f"{record.msg}\n{_format_extra(extra)}"
        return super().format(record)



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


    ctx_filter = ContextFilter()


    log_file = os.path.join(LOGS_DIR, "veskald_bridge.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(ctx_filter)
    file_handler.setFormatter(ReadableFormatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s "
        "[%(ctx)s] [%(machine_token)s] [%(user_id)s]"
    ))
    root.addHandler(file_handler)


    # Skip the console handler when there's no point printing to a terminal:
    #   - frozen desktop binary (no terminal attached)
    #   - explicit GUI mode (set by installer/ui/app.py before import)
    # In either case the in-app log viewer is the user-facing sink.
    in_gui = bool(os.environ.get("VESKALD_GUI_MODE"))
    if not getattr(sys, "frozen", False) and not in_gui:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        ))
        root.addHandler(console_handler)

    _root_configured = True


def get_logger(name: str) -> logging.Logger:

    _configure_root_once()
    full_name = name if name.startswith("veskald_bridge") else f"veskald_bridge.{name}"
    logger = logging.getLogger(full_name)
    logger.setLevel(logging.DEBUG)

    return logger


class Logger:

    def __new__(cls, name: str) -> logging.Logger:  # type: ignore[misc]
        return get_logger(name)