"""Lazy compatibility API; implementation is owned by agent-hub-st 0.1.x."""

from importlib import import_module
from typing import Any


def call_complete(*args: Any, **kwargs: Any) -> Any:
    """Call the versioned public Agent Hub helper only during execution."""
    return import_module("agent_hub_st.completion").call_complete(*args, **kwargs)


def resolve_message(*args: Any, **kwargs: Any) -> Any:
    return import_module("agent_hub_st.completion").resolve_message(*args, **kwargs)


def completion_failed(*args: Any, **kwargs: Any) -> Any:
    return import_module("agent_hub_st.completion").completion_failed(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(import_module("agent_hub_st.completion"), name)
