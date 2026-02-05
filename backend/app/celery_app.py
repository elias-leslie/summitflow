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
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    worker_ready,
    worker_shutdown,
)

from app.config import DATABASE_URL, REDIS_URL
from app.logging_config import _parse_log_level

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
    task_time_limit=900,  # 15 minutes max per task (Tier 3 needs ~10 min)
    task_soft_time_limit=840,  # 14 minute soft limit (2x safety margin on profiled 400s)
    result_expires=60 * 60 * 24 * 7,  # Results expire after 7 days
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks
    # Dead Letter Queue configuration (Task #11)
    # When a worker is lost (crash/kill), reject the task so it goes to DLQ
    task_reject_on_worker_lost=True,
    # Default task acknowledgment after execution (can be overridden per-task)
    task_acks_late=True,
    # Default retry settings for all tasks
    task_default_retry_delay=60,  # 1 minute default retry delay
)

# Dead Letter Queue routing configuration
# Tasks that fail permanently (after max retries) are routed to dead_letter queue
celery_app.conf.task_routes = {
    # Route failed tasks to dead letter queue
    "summitflow.*": {"queue": "celery"},
}

# Define the dead letter exchange and queue
celery_app.conf.task_queues = {
    "celery": {
        "exchange": "celery",
        "routing_key": "celery",
    },
    "dead_letter": {
        "exchange": "dead_letter",
        "routing_key": "dead_letter",
    },
}

# Celery Beat schedule using crontab for predictable scheduling (Task #13)
celery_app.conf.beat_schedule = {
    # Explorer scan - scan all projects every 6 hours (0:00, 6:00, 12:00, 18:00 UTC)
    "scan-all-projects": {
        "task": "summitflow.scan_all_projects",
        "schedule": crontab(minute=0, hour="*/6"),
        "kwargs": {"dry_run": False},
    },
    # Debug cleanup - daily at 3 AM UTC
    "cleanup-debug-captures": {
        "task": "summitflow.cleanup_debug_captures",
        "schedule": crontab(minute=0, hour=3),
        "kwargs": {"max_age_days": 7, "max_files": 20},
    },
    # Autonomous execution - reset expired task claims (hourly at minute 0)
    "reset-expired-task-claims": {
        "task": "summitflow.reset_expired_task_claims",
        "schedule": crontab(minute=0),
    },
    # Autonomous work pickup - FALLBACK for missed events (every 2 hours at minute 15)
    "autonomous-work-pickup-summitflow": {
        "task": "summitflow.autonomous_work_pickup",
        "schedule": crontab(minute=15, hour="*/2"),
        "kwargs": {"project_id": "summitflow"},
    },
    # Autonomous review - Opus review gate (every 30 minutes)
    "review-pending-tasks-summitflow": {
        "task": "summitflow.review_pending_tasks",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"project_id": "summitflow"},
    },
    # Scheduled task processor - check for due scheduled tasks (every minute)
    "process-scheduled-tasks": {
        "task": "summitflow.process_scheduled_tasks",
        "schedule": crontab(minute="*"),
    },
    # Code health - daily scan at 2am UTC
    "daily-code-health-scan": {
        "task": "summitflow.daily_code_health_scan",
        "schedule": crontab(minute=0, hour=2),
        "kwargs": {"project_id": "summitflow"},
    },
    # Code health - weekly deep scan on Sundays at 3am UTC
    "weekly-deep-scan": {
        "task": "summitflow.weekly_deep_scan",
        "schedule": crontab(minute=0, hour=3, day_of_week=0),  # Sunday = 0
        "kwargs": {"project_id": "summitflow"},
    },
    # Scheduled backups - check and run due backups (hourly at minute 30)
    "run-scheduled-backups": {
        "task": "summitflow.run_scheduled_backups",
        "schedule": crontab(minute=30),
    },
    # Crowdsourced ideas - process approved ideas for Monkey Fight at 3am UTC
    "process-crowdsourced-ideas-monkey-fight": {
        "task": "summitflow.process_crowdsourced_ideas",
        "schedule": crontab(minute=0, hour=3),
        "kwargs": {"project_id": "monkey-fight"},
    },
    # Refactor task generation - weekly scan on Mondays at 4am UTC
    "generate-refactor-tasks-summitflow": {
        "task": "summitflow.generate_tasks_from_scan",
        "schedule": crontab(minute=0, hour=4, day_of_week=1),  # Monday = 1
        "kwargs": {"project_id": "summitflow"},
    },
    # Stale task cleanup - archive tasks pending >30 days (daily at 4am UTC)
    "cleanup-stale-tasks": {
        "task": "summitflow.cleanup_stale_tasks",
        "schedule": crontab(minute=0, hour=4),
        "kwargs": {"max_age_days": 30},
    },
    # Self-healing - monitor systemd for runtime errors (every 5 minutes)
    "monitor-systemd-errors": {
        "task": "summitflow.monitor_systemd_errors",
        "schedule": crontab(minute="*/5"),
        "kwargs": {"project_id": "summitflow"},
    },
    # Self-healing - monitor browser console errors (every 6 hours at minute 30)
    "monitor-browser-errors": {
        "task": "summitflow.monitor_browser_errors",
        "schedule": crontab(minute=30, hour="*/6"),
        "kwargs": {"project_id": "summitflow"},
    },
    # Self-healing - orchestrate automated fix triggering (every 15 minutes)
    "orchestrate-self-healing": {
        "task": "summitflow.orchestrate_self_healing",
        "schedule": crontab(minute="*/15"),
        "kwargs": {"max_errors": 20},
    },
}


# Configure Celery logging
@after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, *args: Any, **kwargs: Any) -> None:
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
def setup_celery_task_logger(logger: logging.Logger, *args: Any, **kwargs: Any) -> None:
    """Configure Celery task logger with proper formatting."""
    log_level = _parse_log_level(os.getenv("LOG_LEVEL"))

    for handler in logger.handlers:
        handler.setLevel(log_level)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s: %(levelname)s/%(processName)s] %(message)s")
        )


# Redis pub/sub dispatcher for immediate task dispatch
_dispatcher = None


@worker_ready.connect
def start_dispatch_subscriber(sender: Any, **kwargs: Any) -> None:
    """Start Redis pub/sub subscriber when Celery worker is ready.

    This enables immediate task dispatch via st autocode without waiting
    for the Beat polling fallback.
    """
    global _dispatcher
    from app.logging_config import get_logger
    from app.scheduling import get_dispatcher
    from app.tasks.autonomous.pickup import handle_dispatch_event

    logger = get_logger(__name__)

    try:
        _dispatcher = get_dispatcher()
        _dispatcher.subscribe(handle_dispatch_event)
        logger.info("Started Redis dispatch subscriber for immediate task pickup")
    except Exception as e:
        logger.warning(f"Failed to start dispatch subscriber: {e}")


@worker_shutdown.connect
def stop_dispatch_subscriber(sender: Any, **kwargs: Any) -> None:
    """Stop Redis pub/sub subscriber when Celery worker shuts down."""
    global _dispatcher
    if _dispatcher is not None:
        from app.logging_config import get_logger

        logger = get_logger(__name__)
        try:
            _dispatcher.unsubscribe()
            logger.info("Stopped Redis dispatch subscriber")
        except Exception as e:
            logger.warning(f"Error stopping dispatch subscriber: {e}")


# Import tasks to register them with Celery
from app.tasks import (  # noqa: F401, E402
    autonomous,
    backup,
    enrichment,
    explorer_tasks,
    self_healing,
)
from app.tasks.autonomous import ideas  # noqa: F401, E402
