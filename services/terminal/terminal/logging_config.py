"""Simple logging configuration for Terminal Service.

Provides a basic structured logger using Python's logging module.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any


def _parse_log_level(level_str: str | None) -> int:
    """Parse log level string to logging constant."""
    if not level_str:
        return logging.INFO

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    return level_map.get(level_str.upper(), logging.INFO)


# Configure root logger
_log_level = _parse_log_level(os.getenv("LOG_LEVEL"))
_handler = logging.StreamHandler(sys.stdout)
_handler.setLevel(_log_level)
_handler.setFormatter(logging.Formatter("%(asctime)s - terminal.%(name)s - %(levelname)s - %(message)s"))

logging.root.setLevel(_log_level)
logging.root.handlers = [_handler]


class StructuredLogger:
    """Simple structured logger that mimics structlog interface."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        """Log with structured data."""
        if kwargs:
            extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
            msg = f"{event} {extra}"
        else:
            msg = event
        self._logger.log(level, msg)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return StructuredLogger(name)
