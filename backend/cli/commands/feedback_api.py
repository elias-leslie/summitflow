"""Lazy compatibility API; implementation is owned by agent-hub-st 0.1.x."""

from importlib import import_module
from typing import Any


def feedback_request(*args: Any, **kwargs: Any) -> Any:
    """Call the versioned public Agent Hub helper only during execution."""
    return import_module("agent_hub_st.feedback_api").feedback_request(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(import_module("agent_hub_st.feedback_api"), name)
