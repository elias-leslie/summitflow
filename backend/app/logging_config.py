"""Structured logging configuration using structlog.

This module configures structured JSON logging with proper processors,
formatters, and file rotation for production observability.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import ClassVar

import structlog
from pythonjsonlogger import jsonlogger


def _parse_log_level(level_str: str | None) -> int:
    """Parse log level string to logging constant.

    Args:
        level_str: Log level string (DEBUG, INFO, WARN, WARNING, ERROR, CRITICAL)

    Returns:
        logging level constant (defaults to INFO if invalid)
    """
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


class SyslogPrefixFormatter(logging.Formatter):
    """Formatter that adds syslog priority prefixes for systemd journald.

    Systemd's journal can parse syslog-style priority prefixes like "<3>message"
    to set the correct PRIORITY field in journald, rather than defaulting all
    stdout to INFO (priority 6).

    Priority mapping (RFC 5424):
        0 = Emergency (not used)
        1 = Alert (not used)
        2 = Critical
        3 = Error
        4 = Warning
        5 = Notice (not used, maps to INFO)
        6 = Informational
        7 = Debug
    """

    # Map Python logging levels to syslog priorities
    PRIORITY_MAP: ClassVar[dict[int, int]] = {
        logging.CRITICAL: 2,  # Critical
        logging.ERROR: 3,  # Error
        logging.WARNING: 4,  # Warning
        logging.INFO: 6,  # Informational
        logging.DEBUG: 7,  # Debug
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with syslog priority prefix.

        Args:
            record: LogRecord to format

        Returns:
            Formatted string with syslog prefix: "<priority>message"
        """
        # Get syslog priority for this log level
        priority = self.PRIORITY_MAP.get(record.levelno, 6)  # Default to INFO

        # Format the actual message
        message = super().format(record)

        # Add syslog prefix for systemd to parse
        return f"<{priority}>{message}"


def configure_logging(
    log_dir: str = "logs", log_file: str = "summitflow.log"
) -> None:
    """Configure structured logging with JSON output.

    Log level can be controlled via LOG_LEVEL environment variable.
    Valid values: DEBUG, INFO, WARN, WARNING, ERROR, CRITICAL
    Default: INFO

    When running under systemd (INVOCATION_ID env var present), file logging
    is disabled since systemd handles log capture via StandardOutput/StandardError.

    Args:
        log_dir: Directory for log files
        log_file: Log file name
    """
    # Get log level from environment (default: INFO)
    log_level = _parse_log_level(os.getenv("LOG_LEVEL"))

    # Check if running under systemd (systemd sets INVOCATION_ID)
    running_under_systemd = bool(os.getenv("INVOCATION_ID"))

    handlers: list[logging.Handler] = []

    # Only add file handler if NOT running under systemd
    # (systemd captures stdout/stderr to journal automatically)
    if not running_under_systemd:
        # Create logs directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)

        # Configure standard library logging
        log_file_path = log_path / log_file

        # JSON formatter for file output
        json_formatter = jsonlogger.JsonFormatter(  # type: ignore[attr-defined]
            "%(timestamp)s %(level)s %(name)s %(message)s %(pathname)s %(lineno)d",
            rename_fields={
                "levelname": "level",
                "name": "logger",
                "pathname": "file",
                "lineno": "line",
            },
        )

        # File handler with daily rotation (keep 30 days)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file_path),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(json_formatter)
        handlers.append(file_handler)

    # Console handler with syslog prefixes for systemd journald
    # Systemd will parse the "<priority>" prefix and set PRIORITY field correctly
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(
        SyslogPrefixFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    handlers.append(console_handler)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = []  # Clear existing handlers
    for handler in handlers:
        root_logger.addHandler(handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
