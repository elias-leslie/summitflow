"""Background sampler for persisted runtime resource metrics."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

from ..logging_config import get_logger

logger = get_logger(__name__)

_task: asyncio.Task[None] | None = None
_last_cleanup_monotonic = 0.0


def _interval_seconds() -> int:
    raw = os.environ.get("SUMMITFLOW_RUNTIME_METRICS_INTERVAL_SECONDS", "30")
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def _retention_days() -> int:
    raw = os.environ.get("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", "30")
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


async def sample_runtime_metrics_once() -> int:
    """Collect current runtime service metrics and persist one bounded sample."""
    global _last_cleanup_monotonic
    from ..api.docker.helpers import _runtime_metrics, _runtime_service_statuses
    from ..storage import runtime_metrics as runtime_metric_store

    statuses, metrics = await asyncio.gather(
        _runtime_service_statuses(),
        _runtime_metrics(),
    )
    stored = await asyncio.to_thread(
        runtime_metric_store.record_runtime_metric_samples,
        statuses,
        metrics,
    )
    now = time.monotonic()
    if now - _last_cleanup_monotonic > 3600:
        await asyncio.to_thread(
            runtime_metric_store.cleanup_old_runtime_metric_samples,
            max_age_days=_retention_days(),
        )
        _last_cleanup_monotonic = now
    return stored


async def _run_sampler(interval_seconds: int) -> None:
    while True:
        try:
            await sample_runtime_metrics_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Runtime metric sampler failed: %s", exc)
        await asyncio.sleep(interval_seconds)


def start_runtime_metrics_sampler() -> asyncio.Task[None] | None:
    """Start the background runtime metric sampler."""
    global _task
    interval = _interval_seconds()
    if interval <= 0:
        logger.info("Runtime metric sampler disabled")
        return None
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(_run_sampler(interval), name="runtime-metrics-sampler")
    return _task


async def stop_runtime_metrics_sampler() -> None:
    """Stop the background runtime metric sampler."""
    global _task
    if _task is None:
        return
    task = _task
    _task = None
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
