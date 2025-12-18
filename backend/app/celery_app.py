"""Celery application configuration for SummitFlow background tasks.

This module configures Celery for dev tooling tasks:
- Scheduled file scanning across all registered projects
- Evidence capture scheduled tasks
- Verification scheduled tasks
- Sitemap health checks

NOTE: This is for generic dev tooling tasks only.
Financial-specific tasks (news, market, portfolio) stay in portfolio-ai.
"""

from __future__ import annotations

import logging
import os

from celery import Celery  # celery doesn't ship type stubs
from celery.signals import after_setup_logger, after_setup_task_logger

from app.logging_config import _parse_log_level

# Get Redis URL from environment or use default (different DB than portfolio-ai)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Get DATABASE_URL for result backend
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://portfolio_ai_user:portfolio_ai_dev_2025@localhost:5432/summitflow",
)

# Create Celery application with Redis broker + PostgreSQL backend
# Uses Redis DB 1 to avoid conflicts with portfolio-ai (which uses DB 0)
celery_app = Celery(
    "summitflow",
    broker=f"{REDIS_URL}/1",  # Redis broker (message queue) - different DB
    backend=f"db+{DATABASE_URL}",  # PostgreSQL result backend
    broker_connection_retry_on_startup=True,
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_extended=True,  # Store extended task metadata (name, args, kwargs, worker)
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=270,  # 4.5 minute soft limit
    result_expires=60 * 60 * 24 * 7,  # Results expire after 7 days
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks
)

# Celery Beat schedule - minimal for now, will expand
# Tasks will be added when task modules are created
celery_app.conf.beat_schedule = {
    # Placeholder - actual tasks will be added in future beads:
    # - Scheduled file scanning (bead 0ft: scanners)
    # - Scheduled evidence capture (bead 9kx)
    # - Sitemap health checks
}


# Configure Celery logging
@after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Configure Celery logger with proper formatting.

    This signal handler is called after Celery sets up its logger.
    """
    log_level = _parse_log_level(os.getenv("LOG_LEVEL"))

    # Update all handlers
    for handler in logger.handlers:
        handler.setLevel(log_level)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s: %(levelname)s/%(processName)s] %(message)s")
        )


@after_setup_task_logger.connect
def setup_celery_task_logger(logger: logging.Logger, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Configure Celery task logger with proper formatting."""
    log_level = _parse_log_level(os.getenv("LOG_LEVEL"))

    for handler in logger.handlers:
        handler.setLevel(log_level)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s: %(levelname)s/%(processName)s] %(message)s")
        )


# Task imports will be added here when task modules are created
# Example (future):
# from app.tasks import (
#     file_scan_tasks,
#     evidence_tasks,
#     sitemap_tasks,
# )
