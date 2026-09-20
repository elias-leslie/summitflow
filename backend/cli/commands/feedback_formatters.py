"""Lazy compatibility API; implementation is owned by agent-hub-st 0.1.x."""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(import_module("agent_hub_st.feedback_formatters"), name)
