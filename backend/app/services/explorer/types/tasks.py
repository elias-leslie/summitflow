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

import contextlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy import create_engine, text

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .database import get_db_url_for_project

logger = get_logger(__name__)


def categorize_task(task_name: str) -> str:
    """Categorize a task by its name pattern."""
    name = task_name.lower()

    if "fetch" in name or "sync" in name or "pull" in name:
        return "data-fetch"
    if "cleanup" in name or "prune" in name or "archive" in name:
        return "maintenance"
    if "report" in name or "summary" in name or "digest" in name:
        return "reporting"
    if "alert" in name or "notify" in name:
        return "alerts"
    if "backup" in name or "snapshot" in name:
        return "backup"
    if "analytics" in name or "metric" in name or "stat" in name:
        return "analytics"
    if "market" in name or "price" in name or "quote" in name:
        return "market-data"
    if "news" in name or "headline" in name:
        return "news"
    if "indicator" in name or "signal" in name:
        return "indicators"

    return "scheduled"


class TaskScanner(BaseScanner):
    """Scans Celery tasks for explorer entries."""

    entry_type = "task"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.backend_dir: str = "backend"
        self.beat_schedule_endpoint: str | None = None
        self._task_stats: dict[str, dict[str, Any]] = {}

    def _fetch_task_stats(self) -> dict[str, dict[str, Any]]:
        """Fetch task execution stats from celery_taskmeta for the last 7 days.

        Returns dict mapping task_name -> {last_run_at, success_count, failure_count, success_rate_pct}
        """
        db_url = get_db_url_for_project(self.project_id)
        if not db_url:
            logger.debug(f"No DB URL for {self.project_id}, skipping task stats")
            return {}

        stats: dict[str, dict[str, Any]] = {}
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)

        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT
                            name,
                            MAX(date_done) as last_run,
                            COUNT(*) FILTER (WHERE status = 'SUCCESS') as success_count,
                            COUNT(*) FILTER (WHERE status = 'FAILURE') as failure_count,
                            COUNT(*) as total_count
                        FROM celery_taskmeta
                        WHERE date_done >= :since AND name IS NOT NULL
                        GROUP BY name
                    """),
                    {"since": seven_days_ago},
                )

                for row in result:
                    task_name = row[0]
                    last_run = row[1]
                    success_count = row[2]
                    failure_count = row[3]
                    total_count = row[4]

                    success_rate = (
                        round(success_count / total_count * 100, 1) if total_count > 0 else None
                    )

                    stats[task_name] = {
                        "last_run_at": last_run.isoformat() if last_run else None,
                        "success_count_7d": success_count,
                        "failure_count_7d": failure_count,
                        "success_rate_pct": success_rate,
                    }

            logger.info(f"Fetched stats for {len(stats)} tasks from celery_taskmeta")

        except Exception as e:
            logger.warning(f"Failed to fetch task stats: {e}")

        return stats

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
        beat_schedule = self._get_beat_schedule()
        if not beat_schedule:
            logger.warning(f"No beat schedule found for {self.project_id}")
            return []

        # Fetch execution stats from celery_taskmeta
        self._task_stats = self._fetch_task_stats()

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

    def _get_beat_schedule(self) -> dict[str, Any]:
        """Get beat schedule from endpoint or by scanning files."""
        # Try API endpoint first
        if self.beat_schedule_endpoint:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(self.beat_schedule_endpoint)
                    if response.status_code == 200:
                        data = cast(dict[str, Any], response.json())
                        schedule = data.get("schedule", data)
                        return cast(dict[str, Any], schedule)
            except Exception as e:
                logger.warning(f"Beat schedule fetch failed: {e}")

        # Fallback: scan files
        if not self.root_path:
            return {}

        return self._scan_beat_schedule_files()

    def _scan_beat_schedule_files(self) -> dict[str, Any]:
        """Scan Celery files for beat_schedule definition."""
        if not self.root_path:
            return {}

        celery_files = [
            self.root_path / self.backend_dir / "app" / "celery_schedules.py",
            self.root_path / self.backend_dir / "app" / "celery_app.py",
            self.root_path / self.backend_dir / "celery_app.py",
            self.root_path / self.backend_dir / "app" / "celery.py",
        ]

        schedule = {}
        for celery_file in celery_files:
            if celery_file and celery_file.exists():
                try:
                    content = celery_file.read_text()
                    parsed = self._parse_beat_schedule(content)
                    schedule.update(parsed)
                except Exception as e:
                    logger.warning(f"Failed to parse {celery_file}: {e}")

        return schedule

    def _parse_beat_schedule(self, content: str) -> dict[str, Any]:
        """Parse beat_schedule from file content."""
        schedule = {}

        # Pattern: "task-name": {"task": "module.path", ...}
        patterns = [
            r'"([^"]+)":\s*\{\s*"task":\s*"([^"]+)"',
            r"'([^']+)':\s*\{\s*'task':\s*'([^']+)'",
        ]

        for pattern in patterns:
            for task_name, task_path in re.findall(pattern, content):
                if task_name not in schedule:
                    schedule[task_name] = {"task": task_path}

        # Extract schedule values
        for task_name in list(schedule.keys()):
            task_block_pattern = rf'"{re.escape(task_name)}":\s*\{{([^}}]+)\}}'
            task_block_match = re.search(task_block_pattern, content, re.DOTALL)
            if task_block_match:
                block = task_block_match.group(1)
                # Numeric schedule - capture expressions like "60 * 60 * 6"
                schedule_match = re.search(r'"schedule":\s*([\d\s\*\+\-\/\.]+)', block)
                if schedule_match:
                    expr = schedule_match.group(1).strip().rstrip(",")
                    # Safely evaluate simple math expressions (only digits and operators)
                    if re.match(r"^[\d\s\*\+\-\/\.]+$", expr):
                        with contextlib.suppress(Exception):
                            schedule[task_name]["schedule_seconds"] = float(eval(expr))
                # Crontab schedule
                crontab_match = re.search(r'"schedule":\s*crontab\(([^)]+)\)', block)
                if crontab_match:
                    schedule[task_name]["schedule_crontab"] = crontab_match.group(1)

        return schedule

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
            schedule_human = self._format_interval(seconds)
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

    def _format_interval(self, seconds: float) -> str:
        """Format interval in seconds to human readable."""
        if seconds < 60:
            return f"every {int(seconds)} seconds"
        if seconds < 3600:
            mins = int(seconds / 60)
            return f"every {mins} minute{'s' if mins > 1 else ''}"
        if seconds < 86400:
            hours = int(seconds / 3600)
            return f"every {hours} hour{'s' if hours > 1 else ''}"
        days = int(seconds / 86400)
        return f"every {days} day{'s' if days > 1 else ''}"

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a task entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
