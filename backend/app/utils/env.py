"""Environment-variable parsing helpers.

Small typed wrappers around ``os.environ.get`` used by configuration
modules throughout the backend.
"""

from __future__ import annotations

import os


def float_env(name: str, default: float) -> float:
    """Read an env var as a float, clamped to a minimum of 0.1.

    Returns *default* when the variable is unset or not a valid number.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.1)
    except ValueError:
        return default


def bool_env(name: str, default: bool = False) -> bool:
    """Read an env var as a boolean.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Returns *default* when the variable is unset.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
