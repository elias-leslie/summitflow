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
from pathlib import Path

from celery import Celery  # celery doesn't ship type stubs
from celery.signals import after_setup_logger, after_setup_task_logger
from dotenv import load_dotenv

from app.logging_config import _parse_log_level

# Load environment from ~/.env.local (same pattern as ~/.smbcredentials)
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

# Get Redis URL from environment (default to localhost if not set)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Get DATABASE_URL for result backend - REQUIRED
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Create ~/.env.local with DATABASE_URL=postgresql://..."
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

# Celery Beat schedule
celery_app.conf.beat_schedule = {
    # Explorer scan - scan all projects every 6 hours
    "scan-all-projects": {
        "task": "summitflow.scan_all_projects",
        "schedule": 60 * 60 * 6,  # Every 6 hours
        "kwargs": {"dry_run": False},
    },
    # Debug cleanup - daily at 3 AM UTC
    "cleanup-debug-captures": {
        "task": "summitflow.cleanup_debug_captures",
        "schedule": 60 * 60 * 24,  # Every 24 hours
        "kwargs": {"max_age_days": 7, "max_files": 20},
    },
    # Memory lifecycle cleanup tasks
    "cleanup-failed-queue-items": {
        "task": "summitflow.cleanup_failed_queue_items",
        "schedule": 60 * 60 * 24,  # Daily (every 24 hours)
        "kwargs": {"max_age_days": 14},
    },
    "cleanup-old-checkpoints": {
        "task": "summitflow.cleanup_old_checkpoints",
        "schedule": 60 * 60 * 24 * 7,  # Weekly (every 7 days)
        "kwargs": {"max_age_days": 30},
    },
    "reset-stuck-queue-items": {
        "task": "summitflow.reset_stuck_queue_items",
        "schedule": 60 * 60,  # Hourly
        "kwargs": {"threshold_minutes": 60},
    },
    # Reflection processing - catch unreflected diary entries
    "process-pending-reflections": {
        "task": "summitflow.process_pending_reflections",
        "schedule": 60 * 60 * 2,  # Every 2 hours
    },
    # Embedding processing - generate embeddings for observations and prompts
    "process-pending-embeddings": {
        "task": "summitflow.process_pending_embeddings",
        "schedule": 60 * 5,  # Every 5 minutes
    },
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


# Import tasks to register them with Celery
from app.tasks import (  # noqa: F401, E402
    agent_runner,
    embedding_processor,
    evidence_tasks,
    explorer_tasks,
    lifecycle_cleanup,
    observation_processor,
    reflection_processor,
)
