"""SummitFlow database storage."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULE_EXPORTS = {
    "agent_configs",
    "events",
}
_ATTRIBUTE_EXPORTS = {
    "create_event": ("events", "create_event"),
    "get_connection": ("connection", "get_connection"),
    "get_events_by_trace": ("events", "get_events_by_trace"),
    "get_events_with_filters": ("events", "get_events_with_filters"),
    "log_task_event": ("events", "log_task_event"),
}

__all__ = [
    "agent_configs",
    "create_event",
    "events",
    "get_connection",
    "get_events_by_trace",
    "get_events_with_filters",
    "log_task_event",
]


def __getattr__(name: str) -> Any:
    """Resolve legacy package re-exports only when callers use them."""
    if name in _MODULE_EXPORTS:
        value = import_module(f"{__name__}.{name}")
    elif target := _ATTRIBUTE_EXPORTS.get(name):
        module_name, attribute_name = target
        value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
