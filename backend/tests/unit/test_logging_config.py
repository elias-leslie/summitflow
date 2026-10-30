"""Tests for backend file logging setup."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from app.logging_config import _build_file_handler


def _format(handler: logging.Handler, record: logging.LogRecord) -> dict[str, object]:
    formatter = handler.formatter
    assert formatter is not None
    return json.loads(formatter.format(record))


def test_json_file_log_fills_timestamp_and_level_for_stdlib_records(tmp_path: Path) -> None:
    handler = _build_file_handler(str(tmp_path), "app.log", logging.INFO)
    try:
        record = logging.LogRecord("httpx", logging.WARNING, __file__, 10, "HTTP %s", ("GET",), None)
        payload = _format(handler, record)
    finally:
        handler.close()
    assert payload["timestamp"] and str(payload["timestamp"]).endswith("Z")
    assert payload["level"] == "warning"
    assert payload["logger"] == "httpx"
    assert payload["message"] == "HTTP GET"


def test_json_file_log_keeps_structlog_event_fields(tmp_path: Path) -> None:
    handler = _build_file_handler(str(tmp_path), "app.log", logging.INFO)
    try:
        event = {"event": "done", "timestamp": "2026-10-10T00:00:00Z", "level": "info"}
        record = logging.LogRecord("app.x", logging.INFO, __file__, 10, event, None, None)
        payload = _format(handler, record)
    finally:
        handler.close()
    assert payload["timestamp"] == "2026-10-10T00:00:00Z"
    assert payload["level"] == "info"


def test_importing_app_under_pytest_does_not_attach_file_log_handler() -> None:
    """Collection imports app.main before PYTEST_CURRENT_TEST exists; it must not log to the checkout."""
    import app.main  # noqa: F401

    assert not any(
        isinstance(handler, logging.handlers.TimedRotatingFileHandler)
        for handler in logging.getLogger().handlers
    )


def test_loggers_import_structlog_on_first_use() -> None:
    """Module-level loggers must not cost every st command structlog's import; first use still logs through it."""
    import os
    import subprocess
    import sys

    backend = Path(__file__).resolve().parents[2]
    probe = (
        "import sys; import app.storage.tasks.claims; loaded = 'structlog' in sys.modules;"
        "from structlog.testing import capture_logs; from app.logging_config import get_logger;"
        "logger = get_logger('probe');"
        "exec('with capture_logs() as logs: logger.bind(task=1).info(\"claimed\")');"
        "print(loaded, [(entry['event'], entry['task'], entry['log_level']) for entry in logs])"
    )
    result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True, check=True, timeout=30,
                            cwd=backend, env={**os.environ, "PYTHONPATH": str(backend)})
    assert result.stdout.strip() == "False [('claimed', 1, 'info')]"
