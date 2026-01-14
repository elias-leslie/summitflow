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
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
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
    # Memory health check - auto-apply patterns and detect issues
    # Note: Task iterates all projects if project_id not specified
    "run-memory-health-check": {
        "task": "summitflow.run_memory_health_check",
        "schedule": 60 * 60 * 6,  # Every 6 hours
    },
    # Weekly deep review - comprehensive instruction surface analysis
    "run-weekly-deep-review": {
        "task": "summitflow.run_weekly_deep_review",
        "schedule": 60 * 60 * 24 * 7,  # Weekly (every 7 days)
        # Runs Sundays at 2am via crontab below would be ideal,
        # but simple interval works for now
    },
    # Autonomous execution - reset expired task claims
    "reset-expired-task-claims": {
        "task": "summitflow.reset_expired_task_claims",
        "schedule": 60 * 60,  # Hourly
    },
    # Autonomous work pickup - pick up and execute eligible tasks
    "autonomous-work-pickup-summitflow": {
        "task": "summitflow.autonomous_work_pickup",
        "schedule": 60 * 30,  # Every 30 minutes
        "kwargs": {"project_id": "summitflow"},
    },
    # Autonomous review - Opus review gate for ai_reviewing tasks
    "review-pending-tasks-summitflow": {
        "task": "summitflow.review_pending_tasks",
        "schedule": 60 * 30,  # Every 30 minutes
        "kwargs": {"project_id": "summitflow"},
    },
    # Worktree cleanup - remove orphaned worktrees from failed/abandoned executions
    "cleanup-orphaned-worktrees": {
        "task": "summitflow.cleanup_orphaned_worktrees",
        "schedule": 60 * 60 * 6,  # Every 6 hours
        "kwargs": {"max_age_hours": 24},
    },
    # Code health - daily scan at 2am UTC
    "daily-code-health-scan": {
        "task": "summitflow.daily_code_health_scan",
        "schedule": 60 * 60 * 24,  # Every 24 hours
        "kwargs": {"project_id": "summitflow"},
    },
    # Code health - weekly deep scan on Sundays at 3am UTC
    "weekly-deep-scan": {
        "task": "summitflow.weekly_deep_scan",
        "schedule": 60 * 60 * 24 * 7,  # Weekly
        "kwargs": {"project_id": "summitflow"},
    },
    # Daily evidence capture - capture screenshots and API responses at 2am UTC
    "daily-evidence-capture": {
        "task": "summitflow.capture_all_projects",
        "schedule": 60 * 60 * 24,  # Every 24 hours
        "kwargs": {"environment": "local", "dry_run": False},
    },
    # Scheduled backups - check and run due backups every hour
    "run-scheduled-backups": {
        "task": "summitflow.run_scheduled_backups",
        "schedule": 60 * 60,  # Hourly
    },
    # Crowdsourced ideas - process approved ideas for Monkey Fight at 3am UTC
    "process-crowdsourced-ideas-monkey-fight": {
        "task": "summitflow.process_crowdsourced_ideas",
        "schedule": 60 * 60 * 24,  # Every 24 hours
        "kwargs": {"project_id": "monkey-fight"},
    },
    # Refactor task generation - weekly scan for refactor targets
    "generate-refactor-tasks-summitflow": {
        "task": "summitflow.generate_tasks_from_scan",
        "schedule": 60 * 60 * 24 * 7,  # Weekly
        "kwargs": {"project_id": "summitflow"},
    },
    # Resolved regressions check - auto-close tasks when regressions fixed
    "check-resolved-regressions-summitflow": {
        "task": "summitflow.check_resolved_regressions",
        "schedule": 60 * 60 * 6,  # Every 6 hours
        "kwargs": {"project_id": "summitflow", "auto_close_tasks": True},
    },
    # Stale task cleanup - archive tasks pending >30 days with no activity
    "cleanup-stale-tasks": {
        "task": "summitflow.cleanup_stale_tasks",
        "schedule": 60 * 60 * 24,  # Daily
        "kwargs": {"max_age_days": 30},
    },
}


# Configure Celery logging
@after_setup_logger.connect  # type: ignore[untyped-decorator]
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


@after_setup_task_logger.connect  # type: ignore[untyped-decorator]
def setup_celery_task_logger(logger: logging.Logger, *args: Any, **kwargs: Any) -> None:
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
    autonomous,
    backup,
    embedding_processor,
    enrichment,
    evidence_capture,
    evidence_tasks,
    explorer_tasks,
    lifecycle_cleanup,
    memory_health_task,
    observation_processor,
    orchestrator_runner,
    reflection_processor,
)
from app.tasks.autonomous import ideas  # noqa: F401, E402
