"""Internal utilities for the debug module.

This module contains helper functions used by the debug system.
Not intended for direct import by application code.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

_DEBUG = os.environ.get("DEBUG", "").lower() == "true"
_DEBUG_LEVEL = int(os.environ.get("DEBUG_LEVEL", "1"))


def is_debug_enabled(level: int = 1) -> bool:
    """Check if debug logging is enabled for the given level."""
    return _DEBUG and level <= _DEBUG_LEVEL


def get_caller_info() -> tuple[str, str, int]:
    """Get the calling function name, filename, and line number."""
    import inspect

    frame = inspect.currentframe()
    if frame is None:
        return "unknown", "unknown", 0
    try:
        caller = frame.f_back
        if caller is None or caller.f_back is None:
            return "unknown", "unknown", 0
        caller = caller.f_back
        return (
            caller.f_code.co_name,
            caller.f_code.co_filename.split("/")[-1],
            caller.f_lineno,
        )
    finally:
        del frame


def format_attributes(
    elapsed_ms: float | None = None,
    function_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Format attributes for event emission."""
    attrs: dict[str, Any] = {}
    if elapsed_ms is not None:
        attrs["elapsed_ms"] = round(elapsed_ms, 2)
    if function_name is not None:
        attrs["function_name"] = function_name
    for key, value in kwargs.items():
        if value is not None:
            try:
                json.dumps(value)
                attrs[key] = value
            except (TypeError, ValueError):
                attrs[key] = str(value)
    return attrs


def emit_debug_event(
    message: str,
    level: str = "debug",
    source: str = "debug",
    task_id: str | None = None,
    project_id: str | None = None,
    **attributes: Any,
) -> None:
    """Emit a debug event via the event system."""
    from ..services.pubsub import publish_ws_event

    if task_id is None:
        task_id = "debug"

    publish_ws_event(
        task_id,
        {
            "type": "debug",
            "task_id": task_id,
            "data": {"level": level, "message": message, "source": source, **attributes},
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source=source,
        level="debug",
        visibility="debug",
    )


def emit_stderr(
    message: str,
    level: str = "debug",
    function_name: str | None = None,
    elapsed_ms: float | None = None,
    **attributes: Any,
) -> None:
    """Emit to stderr for immediate visibility in worker logs."""
    timestamp = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"[DEBUG {timestamp}]"]
    if function_name:
        parts.append(f"[{function_name}]")
    parts.append(message)
    if elapsed_ms is not None:
        parts.append(f"({elapsed_ms:.1f}ms)")
    if attributes:
        extras = " ".join(f"{k}={v}" for k, v in attributes.items() if v is not None)
        if extras:
            parts.append(f"| {extras}")
    print(" ".join(parts), file=sys.stderr)
