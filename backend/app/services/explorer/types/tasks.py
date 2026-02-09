"""Task scanner for Explorer.

Scans Celery beat schedule and produces entries for explorer_entries table.

Metadata schema (per architecture doc):
{
  "task_path": "app.tasks.process_payment",
  "function_name": "process_payment",
  "schedule_type": "crontab",
  "schedule_value": "*/5 * * * *",
  "schedule_human": "every 5 minutes",
  "last_run_at": "2025-12-18T10:00:00Z",
  "success_count_7d": 1440,
  "failure_count_7d": 2,
  "success_rate_pct": 99.8
}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .task_categorization import categorize_task
from .task_schedule import format_interval, get_beat_schedule
from .task_stats import fetch_task_stats

logger = get_logger(__name__)


class TaskScanner(BaseScanner):
    """Scans Celery tasks for explorer entries."""

    entry_type = "task"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.backend_dir: str = "backend"
        self.beat_schedule_endpoint: str | None = None
        self._task_stats: dict[str, dict[str, Any]] = {}


    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan Celery beat schedule and return task entries."""
        # Get project config
        project_config = get_project_config(self.project_id)
        if not project_config:
            logger.error(f"Project not found: {self.project_id}")
            return []

        if project_config.get("root_path"):
            self.root_path = Path(project_config["root_path"])
        if project_config.get("backend_dir"):
            self.backend_dir = project_config["backend_dir"]

        # Check config overrides
        if self.config:
            if self.config.get("root_path"):
                self.root_path = Path(self.config["root_path"])
            if self.config.get("backend_dir"):
                self.backend_dir = self.config["backend_dir"]
            if self.config.get("beat_schedule_endpoint"):
                self.beat_schedule_endpoint = self.config["beat_schedule_endpoint"]

        logger.info(f"Task scan started for {self.project_id}")

        # Get beat schedule
        beat_schedule = get_beat_schedule(
            self.project_id,
            self.beat_schedule_endpoint,
            self.root_path,
            self.backend_dir,
        )
        if not beat_schedule:
            logger.warning(f"No beat schedule found for {self.project_id}")
            return []

        # Fetch execution stats from celery_taskmeta
        self._task_stats = fetch_task_stats(self.project_id)

        entries: list[ExplorerEntryCreate] = []

        for task_name, task_config in beat_schedule.items() if beat_schedule else []:
            try:
                entry = self._scan_task(task_name, task_config)
                if entry:
                    entries.append(entry)
            except Exception as e:
                logger.warning(f"Failed to scan task {task_name}: {e}")

        logger.info(f"Task scan found {len(entries)} tasks")
        return entries


    def _scan_task(
        self,
        task_name: str,
        task_config: dict[str, Any],
    ) -> ExplorerEntryCreate | None:
        """Scan a single task and return entry."""
        task_path = task_config.get("task", task_name)
        function_name = task_path.split(".")[-1] if "." in task_path else task_path

        # Parse schedule
        schedule_type = "unknown"
        schedule_value = None
        schedule_human = "unknown"

        if "schedule_seconds" in task_config:
            seconds = task_config["schedule_seconds"]
            schedule_type = "interval"
            schedule_value = str(seconds)
            schedule_human = format_interval(seconds)
        elif "schedule_crontab" in task_config:
            schedule_type = "crontab"
            schedule_value = task_config["schedule_crontab"]
            schedule_human = f"crontab({schedule_value})"

        category = categorize_task(task_name)

        # Get stats from celery_taskmeta (match by task path)
        task_stats = self._task_stats.get(task_path, {})

        return ExplorerEntryCreate(
            path=task_name,
            name=function_name,
            health_status="unknown",  # Will be set by get_health_status
            metadata={
                "task_path": task_path,
                "function_name": function_name,
                "schedule_type": schedule_type,
                "schedule_value": schedule_value,
                "schedule_human": schedule_human,
                "category": category,
                "last_run_at": task_stats.get("last_run_at"),
                "success_count_7d": task_stats.get("success_count_7d", 0),
                "failure_count_7d": task_stats.get("failure_count_7d", 0),
                "success_rate_pct": task_stats.get("success_rate_pct"),
            },
        )


    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a task entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
