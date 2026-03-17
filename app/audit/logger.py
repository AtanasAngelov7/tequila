"""Structured JSON application logging for Tequila v2 (§12.4).

Sets up the Python logging hierarchy to emit structured JSON entries (one per
line) to both stdout and a rotating file in ``data/logs/tequila.log``.

### Design decisions
- ``setup_logging()`` is idempotent — safe to call multiple times (e.g., in
  tests that import several modules before the app is initialized).
- JSON format is used in production; human-readable text format is available
  for ``TEQUILA_DEBUG=true`` console output.
- The ``extra`` dict on each ``logger.XXX()`` call populates the top-level
  JSON object so structured fields are queryable without parsing the message.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from typing import Any

# ── JSON formatter ────────────────────────────────────────────────────────────


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    # Fields that should not be repeated in the structured output.
    _SKIP_EXTRA: frozenset[str] = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        record.message = record.getMessage()
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.message,
        }
        # Merge any ``extra={}`` fields the caller passed.
        for key, val in record.__dict__.items():
            if key not in self._SKIP_EXTRA:
                entry[key] = val
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


# ── Setup ─────────────────────────────────────────────────────────────────────

_configured: bool = False


def setup_logging(
    level: str = "INFO",
    fmt: str = "json",
    output: str = "both",
    log_file: str = "data/logs/tequila.log",
    max_file_size_mb: int = 50,
    max_files: int = 5,
    per_module_levels: dict[str, str] | None = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Root log level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
        fmt: Format style — ``"json"`` (machine-parseable) or ``"text"`` (human).
        output: Where to write — ``"stdout"``, ``"file"``, or ``"both"``.
        log_file: Path to the rotating log file.
        max_file_size_mb: Rotate after this many megabytes.
        max_files: Number of rotated files to keep.
        per_module_levels: Dict mapping module names to level overrides.

    This function is idempotent — calling it multiple times only reconfigures
    the root logger if ``_configured`` is ``False``.
    """
    global _configured  # noqa: PLW0603
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any pre-existing handlers to avoid duplicate output.
    root.handlers.clear()

    json_formatter = _JSONFormatter()
    text_formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    formatter = json_formatter if fmt == "json" else text_formatter

    # ── stdout handler ────────────────────────────────────────────────────────
    if output in ("stdout", "both"):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    # ── rotating file handler ─────────────────────────────────────────────────
    if output in ("file", "both"):
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=max_files,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)  # file is always JSON
        root.addHandler(file_handler)

    # ── Per-module level overrides ────────────────────────────────────────────
    if per_module_levels:
        for module_name, module_level in per_module_levels.items():
            logging.getLogger(module_name).setLevel(module_level)

    # Silence overly-verbose third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"level": level, "format": fmt, "output": output},
    )


def reset_logging() -> None:
    """Reset logging configuration so ``setup_logging`` can be called again.

    Primarily for use in tests that need to reconfigure logging.
    """
    global _configured  # noqa: PLW0603
    _configured = False
