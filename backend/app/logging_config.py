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

# Environment variable names
_ENV_LOG_LEVEL = "LOG_LEVEL"
_ENV_SYSTEMD_INVOCATION = "INVOCATION_ID"

# Default log file settings
_DEFAULT_LOG_DIR = "logs"
_DEFAULT_LOG_FILE = "summitflow.log"

# File rotation settings
_FILE_ROTATION_WHEN = "midnight"
_FILE_ROTATION_INTERVAL = 1
_FILE_ROTATION_BACKUP_COUNT = 30
_FILE_ENCODING = "utf-8"

# Log format strings
_JSON_FORMAT = "%(timestamp)s %(level)s %(name)s %(message)s %(pathname)s %(lineno)d"
_CONSOLE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# JSON field rename mapping for file handler
_JSON_RENAME_FIELDS: dict[str, str] = {
    "levelname": "level",
    "name": "logger",
    "pathname": "file",
    "lineno": "line",
}

# Default syslog priority for unknown levels (INFO = 6)
_SYSLOG_DEFAULT_PRIORITY = 6

# Structlog timestamp format
_TIMESTAMP_FMT = "iso"


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
        priority = self.PRIORITY_MAP.get(record.levelno, _SYSLOG_DEFAULT_PRIORITY)

        # Format the actual message
        message = super().format(record)

        # Add syslog prefix for systemd to parse
        return f"<{priority}>{message}"


def _build_file_handler(
    log_dir: str, log_file: str, log_level: int
) -> logging.Handler:
    """Create a rotating file handler with JSON formatting.

    Creates the log directory if it does not exist, then configures a
    TimedRotatingFileHandler with daily rotation and a JSON formatter.

    Args:
        log_dir: Directory for log files
        log_file: Log file name
        log_level: Logging level constant

    Returns:
        Configured file handler
    """
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    json_formatter = jsonlogger.JsonFormatter(
        _JSON_FORMAT,
        rename_fields=_JSON_RENAME_FIELDS,
    )

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_path / log_file),
        when=_FILE_ROTATION_WHEN,
        interval=_FILE_ROTATION_INTERVAL,
        backupCount=_FILE_ROTATION_BACKUP_COUNT,
        encoding=_FILE_ENCODING,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(json_formatter)
    return file_handler


def _build_console_handler(log_level: int) -> logging.Handler:
    """Create a console handler with syslog prefix formatting.

    The syslog prefix allows systemd journald to parse the PRIORITY field
    correctly instead of defaulting all stdout to INFO.

    Args:
        log_level: Logging level constant

    Returns:
        Configured console handler
    """
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(SyslogPrefixFormatter(_CONSOLE_FORMAT))
    return console_handler


def _configure_root_logger(
    handlers: list[logging.Handler], log_level: int
) -> None:
    """Apply handlers to the root logger, replacing any existing handlers.

    Args:
        handlers: List of handlers to attach
        log_level: Logging level constant
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = []  # Clear existing handlers
    for handler in handlers:
        root_logger.addHandler(handler)


def _configure_structlog() -> None:
    """Configure structlog with standard processors for structured JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt=_TIMESTAMP_FMT),
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


def configure_logging(
    log_dir: str = _DEFAULT_LOG_DIR, log_file: str = _DEFAULT_LOG_FILE
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
    log_level = _parse_log_level(os.getenv(_ENV_LOG_LEVEL))

    # Check if running under systemd (systemd sets INVOCATION_ID)
    running_under_systemd = bool(os.getenv(_ENV_SYSTEMD_INVOCATION))

    handlers: list[logging.Handler] = []

    # Only add file handler if NOT running under systemd
    # (systemd captures stdout/stderr to journal automatically)
    if not running_under_systemd:
        handlers.append(_build_file_handler(log_dir, log_file, log_level))

    handlers.append(_build_console_handler(log_level))

    _configure_root_logger(handlers, log_level)
    _configure_structlog()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)
