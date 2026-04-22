# Canonical source: synchronized across summitflow, agent-hub, portfolio-ai
"""Hatchet client singleton for workflow orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import timedelta
from functools import lru_cache, wraps
from typing import TYPE_CHECKING, Any, cast  # Any: __getattr__ return is inherently dynamic

if TYPE_CHECKING:
    from hatchet_sdk import Hatchet


logger = logging.getLogger(__name__)

# Hatchet injects hidden 60s execution / 5m schedule defaults when callers omit
# them. Keep one centralized, non-restrictive fallback here so long-running
# agentic workflows are not silently cancelled.
DEFAULT_TASK_SCHEDULE_TIMEOUT = timedelta(days=7)
DEFAULT_TASK_EXECUTION_TIMEOUT = timedelta(days=7)
_HATCHET_SHUTDOWN_404_GUARD_ATTR = "_hatchet_shutdown_404_guard"

PauseTaskAssignmentFn = Callable[[Any], Coroutine[Any, Any, None]]


def _wrap_hatchet_shutdown_404_guard(
    pause_task_assignment: PauseTaskAssignmentFn,
    *,
    not_found_exception: type[Exception],
) -> PauseTaskAssignmentFn:
    if getattr(pause_task_assignment, _HATCHET_SHUTDOWN_404_GUARD_ATTR, False):
        return pause_task_assignment

    @wraps(pause_task_assignment)
    async def guarded_pause_task_assignment(process: Any) -> None:
        try:
            await pause_task_assignment(process)
        except not_found_exception:
            worker_id = getattr(getattr(process, "listener", None), "worker_id", None)
            logger.debug(
                "Hatchet listener worker %s already removed during shutdown pause; suppressing 404",
                worker_id,
            )

    setattr(guarded_pause_task_assignment, _HATCHET_SHUTDOWN_404_GUARD_ATTR, True)
    return cast(PauseTaskAssignmentFn, guarded_pause_task_assignment)


def _install_hatchet_shutdown_404_guard() -> None:
    """Treat shutdown-time Hatchet worker 404s as an already-complete pause.

    During SIGTERM/SIGQUIT shutdown races, Hatchet can evict the listener's
    worker record before ``pause_task_assignment()`` reaches the REST update.
    That 404 is effectively "already paused / already gone" and should not
    bubble out as an unhandled task exception.
    """

    from hatchet_sdk.clients.rest.exceptions import NotFoundException
    from hatchet_sdk.worker.action_listener_process import WorkerActionListenerProcess

    guarded_pause_task_assignment = _wrap_hatchet_shutdown_404_guard(
        WorkerActionListenerProcess.pause_task_assignment,
        not_found_exception=NotFoundException,
    )
    type.__setattr__(
        WorkerActionListenerProcess,
        "pause_task_assignment",
        guarded_pause_task_assignment,
    )


@lru_cache
def get_hatchet() -> Hatchet:
    """Get cached Hatchet client instance.

    Lazy initialization - only created on first call.
    Requires HATCHET_CLIENT_TOKEN env var.
    """
    _install_hatchet_shutdown_404_guard()
    from hatchet_sdk import Hatchet as HatchetClass

    return HatchetClass()


class _LazyHatchet:
    """Lazy proxy that defers Hatchet client creation until first attribute access.

    Allows workflow modules to import ``hatchet`` at module level for decorators
    without triggering client construction at import time.  The real
    ``Hatchet`` instance is only created when an attribute (e.g. ``.task()``,
    ``.worker()``) is first accessed.
    """

    def task(self, *args: Any, **kwargs: Any) -> Any:
        """Apply centralized task timeout defaults before delegating to Hatchet."""
        effective_kwargs = dict(kwargs)
        effective_kwargs.setdefault("schedule_timeout", DEFAULT_TASK_SCHEDULE_TIMEOUT)
        effective_kwargs.setdefault("execution_timeout", DEFAULT_TASK_EXECUTION_TIMEOUT)
        return get_hatchet().task(*args, **effective_kwargs)

    def workflow(self, *args: Any, **kwargs: Any) -> Any:
        """Apply centralized workflow task defaults before delegating to Hatchet."""
        from hatchet_sdk.runnables.types import TaskDefaults

        effective_kwargs = dict(kwargs)
        task_defaults = effective_kwargs.get("task_defaults")
        merged = task_defaults.model_copy(deep=True) if isinstance(task_defaults, TaskDefaults) else TaskDefaults()
        if merged.schedule_timeout is None:
            merged.schedule_timeout = DEFAULT_TASK_SCHEDULE_TIMEOUT
        if merged.execution_timeout is None:
            merged.execution_timeout = DEFAULT_TASK_EXECUTION_TIMEOUT
        effective_kwargs["task_defaults"] = merged
        return get_hatchet().workflow(*args, **effective_kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(get_hatchet(), name)


hatchet: Hatchet = _LazyHatchet()  # type: ignore[assignment]  # _LazyHatchet proxies Hatchet
