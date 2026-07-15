"""
Structured logging setup for Market-Intel.

Outputs JSON-formatted logs to stdout with:
- timestamp
- level
- component (module name)
- message
- extra fields
"""
from __future__ import annotations

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        # Add any extra fields passed via logger.info(msg, extra={...})
        for key, value in record.__dict__.items():
            if key not in ("name", "msg", "args", "levelname", "levelno", "pathname",
                           "filename", "module", "exc_info", "exc_text", "stack_info",
                           "lineno", "funcName", "created", "msecs", "relativeCreated",
                           "thread", "threadName", "processName", "process", "message",
                           "taskName"):
                log_entry[key] = value
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the root logger."""
    root = logging.getLogger("market_intel")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the market_intel namespace."""
    return logging.getLogger(f"market_intel.{name}")
