"""Execution-scoped policy snapshots supplied by Agent Hub automation runs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_execution_policy: ContextVar[dict[str, Any] | None] = ContextVar(
    "summitflow_execution_policy",
    default=None,
)


@contextmanager
def use_execution_policy(policy: Mapping[str, Any] | None) -> Iterator[None]:
    """Bind one immutable-in-practice policy snapshot to this execution context."""
    token = _execution_policy.set(dict(policy) if policy is not None else None)
    try:
        yield
    finally:
        _execution_policy.reset(token)


def current_execution_policy() -> dict[str, Any] | None:
    policy = _execution_policy.get()
    return dict(policy) if policy is not None else None
