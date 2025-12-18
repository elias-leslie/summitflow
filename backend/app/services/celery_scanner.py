"""Celery task scanner for SummitFlow.

Scans Celery beat schedule to discover scheduled tasks per project.
Detects task metadata: schedules, dependencies, table interactions.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.logging_config import get_logger
from app.storage.connection import get_connection

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


def calculate_celery_health(
    populates_tables: list[str],
    depends_on_tasks: list[str],
    called_by: list[str],
    last_run_at: Any | None,
    success_rate_pct: int | None,
    schedule_interval_seconds: int | None,
) -> str:
    """Calculate health status for a Celery task.

    Args:
        populates_tables: Tables this task populates
        depends_on_tasks: Tasks this task depends on
        called_by: Files/tasks that call this task
        last_run_at: Last execution timestamp
        success_rate_pct: Success rate over last 7 days
        schedule_interval_seconds: Schedule interval in seconds

    Returns:
        Health status: "active", "orphaned", "legacy", "suspect"
    """
    has_zero_success = success_rate_pct is not None and success_rate_pct == 0

    # If other code calls this task, it's active (suspect if failing)
    if called_by:
        return "suspect" if has_zero_success else "active"

    # Orphaned: Not scheduled and no dependencies and no callers
    is_isolated = (
        schedule_interval_seconds is None and not populates_tables and not depends_on_tasks
    )
    if is_isolated:
        return "orphaned"

    # Legacy: Never executed OR complete failure
    if last_run_at is None or has_zero_success:
        return "legacy"

    # Suspect: Low success rate
    has_low_success = success_rate_pct is not None and success_rate_pct < 50
    return "suspect" if has_low_success else "active"


class CeleryScanner:
    """Scans Celery tasks for a project."""

    def __init__(
        self,
        project_id: str,
        root_path: str,
        backend_dir: str | None = None,
        beat_schedule_endpoint: str | None = None,
    ) -> None:
        """Initialize scanner.

        Args:
            project_id: The project ID to associate results with
            root_path: Root path of the project
            backend_dir: Relative path to backend directory (default: "backend")
            beat_schedule_endpoint: API endpoint to fetch beat_schedule from (optional)
        """
        self.project_id = project_id
        self.root_path = Path(root_path)
        self.backend_dir = backend_dir or "backend"
        self.beat_schedule_endpoint = beat_schedule_endpoint

    def scan(self) -> list[dict[str, Any]]:
        """Scan Celery beat schedule and return task metadata.

        Returns:
            List of task capability dicts
        """
        logger.info("scanning_celery_tasks", project=self.project_id)

        # Get beat schedule
        beat_schedule = self._get_beat_schedule()
        if not beat_schedule:
            logger.warning("no_beat_schedule_found", project=self.project_id)
            return []

        capabilities = []

        for task_name, task_config in beat_schedule.items():
            try:
                capability = self._scan_single_task(task_name, task_config)
                capabilities.append(capability)
            except Exception as e:
                logger.error("task_scan_failed", task=task_name, error=str(e))

        logger.info("celery_scan_complete", project=self.project_id, tasks=len(capabilities))
        return capabilities

    def _get_beat_schedule(self) -> dict[str, Any]:
        """Get beat schedule from endpoint or by scanning files.

        Returns:
            Beat schedule dict
        """
        # Try fetching from API endpoint first
        if self.beat_schedule_endpoint:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(self.beat_schedule_endpoint)
                    if response.status_code == 200:
                        data = response.json()
                        # Handle both direct schedule and wrapped response
                        if "schedule" in data:
                            return data["schedule"]
                        return data
            except Exception as e:
                logger.warning(
                    "beat_schedule_fetch_failed",
                    endpoint=self.beat_schedule_endpoint,
                    error=str(e),
                )

        # Fallback: scan celery_app.py for beat_schedule definition
        return self._scan_beat_schedule_file()

    def _scan_beat_schedule_file(self) -> dict[str, Any]:
        """Scan Celery files for beat_schedule definition.

        Returns:
            Parsed beat schedule dict
        """
        # Files to check for beat_schedule definitions
        celery_files = [
            self.root_path / self.backend_dir / "app" / "celery_schedules.py",  # Portfolio-AI pattern
            self.root_path / self.backend_dir / "app" / "celery_app.py",
            self.root_path / self.backend_dir / "celery_app.py",
            self.root_path / self.backend_dir / "app" / "celery.py",
        ]

        schedule = {}
        for celery_file in celery_files:
            if celery_file.exists():
                try:
                    content = celery_file.read_text()
                    parsed = self._parse_beat_schedule(content)
                    # Merge schedules from multiple files
                    schedule.update(parsed)
                except Exception as e:
                    logger.warning("celery_file_parse_failed", file=str(celery_file), error=str(e))

        return schedule

    def _parse_beat_schedule(self, content: str) -> dict[str, Any]:
        """Parse beat_schedule from file content.

        This is a simplified parser that extracts task names and paths.
        Handles various patterns found in Celery beat schedules.
        """
        schedule = {}

        # Pattern 1: "task-name": { "task": "module.path", ...}
        pattern1 = r'"([^"]+)":\s*\{\s*"task":\s*"([^"]+)"'
        for task_name, task_path in re.findall(pattern1, content):
            schedule[task_name] = {"task": task_path, "schedule": None}

        # Pattern 2: 'task-name': { 'task': 'module.path', ...}
        pattern2 = r"'([^']+)':\s*\{\s*'task':\s*'([^']+)'"
        for task_name, task_path in re.findall(pattern2, content):
            if task_name not in schedule:
                schedule[task_name] = {"task": task_path, "schedule": None}

        # Pattern 3: "task-name": {\n            "task": "module.path" (with newlines)
        pattern3 = r'"([^"]+)":\s*\{[^}]*?"task":\s*"([^"]+)"'
        for task_name, task_path in re.findall(pattern3, content, re.DOTALL):
            if task_name not in schedule:
                schedule[task_name] = {"task": task_path, "schedule": None}

        # Extract schedule values where possible
        # Pattern: "schedule": 60.0 (numeric interval)
        for task_name in list(schedule.keys()):
            # Find the block for this task
            task_block_pattern = rf'"{re.escape(task_name)}":\s*\{{([^}}]+)\}}'
            task_block_match = re.search(task_block_pattern, content, re.DOTALL)
            if task_block_match:
                block = task_block_match.group(1)
                # Try to extract numeric schedule
                schedule_match = re.search(r'"schedule":\s*(\d+(?:\.\d+)?)', block)
                if schedule_match:
                    schedule[task_name]["schedule"] = float(schedule_match.group(1))
                # Try to extract crontab schedule
                crontab_match = re.search(r'"schedule":\s*crontab\(([^)]+)\)', block)
                if crontab_match:
                    schedule[task_name]["schedule"] = f"crontab({crontab_match.group(1)})"

        return schedule

    def _scan_single_task(
        self,
        task_name: str,
        task_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Scan a single Celery task for metadata."""
        task_path = task_config.get("task", task_name)
        function_name = task_path.split(".")[-1] if "." in task_path else task_path

        # Parse schedule
        schedule_obj = task_config.get("schedule")
        schedule_description, schedule_crontab, schedule_interval_seconds = self._parse_schedule(
            schedule_obj, task_config
        )

        # Detect populated tables
        populates_tables = self._detect_populates_tables(task_path)

        # Detect tables this task reads from
        reads_from_tables = self._detect_reads_from_tables(task_path)

        # Detect task callers
        called_by = self._detect_task_callers(task_name, task_path)

        # Detect dependencies
        depends_on_tasks = self._detect_task_dependencies(task_path)

        # Categorize task
        category = categorize_task(task_name)

        # Calculate health status
        health_status = calculate_celery_health(
            populates_tables=populates_tables,
            depends_on_tasks=depends_on_tasks,
            called_by=called_by,
            last_run_at=None,  # Would need celery_taskmeta access
            success_rate_pct=None,
            schedule_interval_seconds=schedule_interval_seconds,
        )

        return {
            "task_name": task_name,
            "category": category,
            "task_path": task_path,
            "function_name": function_name,
            "schedule_description": schedule_description,
            "schedule_crontab": schedule_crontab,
            "schedule_interval_seconds": schedule_interval_seconds,
            "last_run_at": None,
            "success_count_7d": 0,
            "failure_count_7d": 0,
            "success_rate_pct": None,
            "populates_tables": populates_tables,
            "reads_from_tables": reads_from_tables,
            "depends_on_tasks": depends_on_tasks,
            "called_by": called_by,
            "health_status": health_status,
        }

    def _parse_schedule(
        self,
        schedule_obj: Any,
        task_config: dict[str, Any],
    ) -> tuple[str, str | None, int | None]:
        """Parse Celery schedule into human-readable format."""
        if schedule_obj is None:
            # Try to extract from task_config options
            options = task_config.get("options", {})
            if "crontab" in str(task_config):
                return "Scheduled (crontab)", None, None
            return "Scheduled", None, None

        schedule_str = str(schedule_obj)

        # Try to parse interval (seconds)
        if isinstance(schedule_obj, (int, float)):
            interval_seconds = int(schedule_obj)
            if interval_seconds < 60:
                description = f"Every {interval_seconds} seconds"
            elif interval_seconds < 3600:
                description = f"Every {interval_seconds // 60} minutes"
            elif interval_seconds < 86400:
                description = f"Every {interval_seconds // 3600} hours"
            else:
                description = f"Every {interval_seconds // 86400} days"
            return description, None, interval_seconds

        # Generic fallback
        return f"Schedule: {schedule_str[:50]}", None, None

    def _detect_populates_tables(self, task_path: str) -> list[str]:
        """Detect which tables a task populates."""
        try:
            file_path = self._task_path_to_file(task_path)
            if not file_path or not file_path.exists():
                return []

            content = file_path.read_text()
            tables = set()

            patterns = [
                r"INSERT\s+INTO\s+([a-z_][a-z0-9_]*)",
                r"UPDATE\s+([a-z_][a-z0-9_]*)",
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                tables.update(matches)

            return sorted(tables)

        except Exception as e:
            logger.debug("failed_to_detect_populated_tables", task=task_path, error=str(e))
            return []

    def _detect_reads_from_tables(self, task_path: str) -> list[str]:
        """Detect tables this task reads from."""
        try:
            file_path = self._task_path_to_file(task_path)
            if not file_path or not file_path.exists():
                return []

            content = file_path.read_text()
            tables = set()

            # Extract SQL strings
            sql_string_pattern = r'(?:"""|\'\'\')(.*?)(?:"""|\'\'\')'
            sql_strings = []
            for match in re.finditer(sql_string_pattern, content, re.DOTALL):
                s = match.group(1)
                if re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b", s, re.IGNORECASE):
                    sql_strings.append(s)

            # Search for table names
            from_pattern = r"\bFROM\s+([a-z_][a-z0-9_]*)\b"
            join_pattern = r"\bJOIN\s+([a-z_][a-z0-9_]*)\b"

            sql_keywords = {
                "select", "where", "and", "or", "not", "null", "true", "false",
                "values", "excluded", "returning", "case", "when", "then", "else",
                "end", "exists", "between", "like", "in", "is", "as", "on", "set",
            }

            for sql in sql_strings:
                for match in re.finditer(from_pattern, sql, re.IGNORECASE):
                    table = match.group(1).lower()
                    if table not in sql_keywords:
                        tables.add(table)
                for match in re.finditer(join_pattern, sql, re.IGNORECASE):
                    table = match.group(1).lower()
                    if table not in sql_keywords:
                        tables.add(table)

            # Remove tables that this task writes to
            writes = {t.lower() for t in self._detect_populates_tables(task_path)}
            reads_only = tables - writes

            return sorted(reads_only)

        except Exception as e:
            logger.debug("failed_to_detect_reads_from_tables", task=task_path, error=str(e))
            return []

    def _detect_task_callers(self, task_name: str, task_path: str) -> list[str]:
        """Detect files/tasks that call this task."""
        try:
            callers = set()
            function_name = task_path.split(".")[-1] if "." in task_path else task_path

            patterns = [
                rf"{function_name}\.delay\s*\(",
                rf"{function_name}\.apply_async\s*\(",
                rf"send_task\s*\(\s*['\"].*{function_name}['\"]",
            ]

            app_dir = self.root_path / self.backend_dir / "app"
            if not app_dir.exists():
                return []

            for py_file in app_dir.glob("**/*.py"):
                if function_name in py_file.name:
                    continue

                try:
                    content = py_file.read_text()
                    for pattern in patterns:
                        if re.search(pattern, content):
                            rel_path = str(py_file.relative_to(app_dir))
                            callers.add(rel_path)
                            break
                except Exception:
                    continue

            return sorted(callers)

        except Exception as e:
            logger.debug("failed_to_detect_task_callers", task=task_name, error=str(e))
            return []

    def _detect_task_dependencies(self, task_path: str) -> list[str]:
        """Detect tasks that this task calls."""
        try:
            dependencies = set()

            file_path = self._task_path_to_file(task_path)
            if not file_path or not file_path.exists():
                return []

            content = file_path.read_text()

            delay_pattern = r"(\w+)\.delay\s*\("
            async_pattern = r"(\w+)\.apply_async\s*\("
            send_pattern = r"send_task\s*\(\s*['\"]([^'\"]+)['\"]"

            for match in re.finditer(delay_pattern, content):
                task_var = match.group(1)
                if task_var not in ["self", "cls", "result", "response", "data"]:
                    dependencies.add(task_var)

            for match in re.finditer(async_pattern, content):
                task_var = match.group(1)
                if task_var not in ["self", "cls", "result", "response", "data"]:
                    dependencies.add(task_var)

            for match in re.finditer(send_pattern, content):
                dependencies.add(match.group(1))

            return sorted(dependencies)

        except Exception as e:
            logger.debug("failed_to_detect_task_dependencies", task=task_path, error=str(e))
            return []

    def _task_path_to_file(self, task_path: str) -> Path | None:
        """Convert task import path to file path."""
        path_parts = task_path.split(".")
        if len(path_parts) < 2:
            return None

        # Remove function name
        module_parts = path_parts[:-1]

        # Build file path - try different base paths
        possible_paths = [
            self.root_path / self.backend_dir / "/".join(module_parts),
            self.root_path / self.backend_dir / "app" / "/".join(module_parts[1:]),
        ]

        for base_path in possible_paths:
            file_path = base_path.with_suffix(".py")
            if file_path.exists():
                return file_path

        return None

    def save(self, capabilities: list[dict[str, Any]]) -> int:
        """Save scan results to scanner_celery table.

        Args:
            capabilities: List of task capability dicts

        Returns:
            Number of rows upserted
        """
        if not capabilities:
            return 0

        scan_time = datetime.now(UTC)

        with get_connection() as conn, conn.cursor() as cur:
            for cap in capabilities:
                cur.execute(
                    """
                    INSERT INTO scanner_celery (
                        project_id, task_name, category, task_path, function_name,
                        schedule_description, schedule_crontab, schedule_interval_seconds,
                        last_run_at, success_count_7d, failure_count_7d, success_rate_pct,
                        populates_tables, reads_from_tables, depends_on_tasks, called_by,
                        health_status, last_scanned_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (project_id, task_name) DO UPDATE SET
                        category = EXCLUDED.category,
                        task_path = EXCLUDED.task_path,
                        function_name = EXCLUDED.function_name,
                        schedule_description = EXCLUDED.schedule_description,
                        schedule_crontab = EXCLUDED.schedule_crontab,
                        schedule_interval_seconds = EXCLUDED.schedule_interval_seconds,
                        last_run_at = EXCLUDED.last_run_at,
                        success_count_7d = EXCLUDED.success_count_7d,
                        failure_count_7d = EXCLUDED.failure_count_7d,
                        success_rate_pct = EXCLUDED.success_rate_pct,
                        populates_tables = EXCLUDED.populates_tables,
                        reads_from_tables = EXCLUDED.reads_from_tables,
                        depends_on_tasks = EXCLUDED.depends_on_tasks,
                        called_by = EXCLUDED.called_by,
                        health_status = EXCLUDED.health_status,
                        last_scanned_at = EXCLUDED.last_scanned_at,
                        updated_at = NOW()
                    """,
                    [
                        self.project_id,
                        cap["task_name"],
                        cap["category"],
                        cap["task_path"],
                        cap["function_name"],
                        cap["schedule_description"],
                        cap["schedule_crontab"],
                        cap["schedule_interval_seconds"],
                        cap["last_run_at"],
                        cap["success_count_7d"],
                        cap["failure_count_7d"],
                        cap["success_rate_pct"],
                        json.dumps(cap["populates_tables"]),
                        json.dumps(cap["reads_from_tables"]),
                        json.dumps(cap["depends_on_tasks"]),
                        json.dumps(cap["called_by"]),
                        cap["health_status"],
                        scan_time,
                    ],
                )

            # Cleanup stale entries
            cur.execute(
                """
                DELETE FROM scanner_celery
                WHERE project_id = %s AND last_scanned_at < %s
                """,
                [self.project_id, scan_time],
            )

            conn.commit()

        return len(capabilities)


def get_project_celery_config(project_id: str) -> tuple[str | None, str | None, str | None]:
    """Get Celery scanner config for a project.

    Args:
        project_id: The project ID

    Returns:
        Tuple of (root_path, backend_dir, beat_schedule_endpoint) or (None, None, None)
    """
    # Known project configs
    configs = {
        "portfolio-ai": (
            "/home/kasadis/portfolio-ai",
            "backend",
            "http://localhost:8000/api/celery/schedule",
        ),
        "summitflow": (
            "/home/kasadis/summitflow",
            "backend",
            None,  # SummitFlow doesn't have its own Celery
        ),
    }

    if project_id in configs:
        return configs[project_id]

    # Try to get from database
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path, backend_dir FROM projects WHERE id = %s",
            [project_id],
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1], None

    return None, None, None
