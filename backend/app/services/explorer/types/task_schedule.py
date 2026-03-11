"""Scheduled workflow parsing and retrieval."""

from __future__ import annotations

import ast
import contextlib
import re
from pathlib import Path
from typing import Any, cast

import httpx

from ....logging_config import get_logger

logger = get_logger(__name__)


def _fetch_beat_schedule_from_endpoint(endpoint: str) -> dict[str, Any] | None:
    """Fetch beat schedule from HTTP endpoint. Returns None on failure."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(endpoint)
            if response.status_code != 200:
                return None
            data = cast(dict[str, Any], response.json())
            schedule = data.get("schedule", data)
            return cast(dict[str, Any], schedule)
    except Exception as e:
        logger.warning(f"Beat schedule fetch failed: {e}")
        return None


def get_beat_schedule(
    project_id: str,
    beat_schedule_endpoint: str | None,
    root_path: Path | None,
    backend_dir: str,
) -> dict[str, Any]:
    """Get beat schedule from endpoint or by scanning files."""
    if beat_schedule_endpoint:
        result = _fetch_beat_schedule_from_endpoint(beat_schedule_endpoint)
        if result is not None:
            return result

    if not root_path:
        return {}

    hatchet_schedule = scan_hatchet_schedule_files(root_path, backend_dir)
    if hatchet_schedule:
        return hatchet_schedule

    return scan_beat_schedule_files(root_path, backend_dir)


def scan_hatchet_schedule_files(root_path: Path, backend_dir: str) -> dict[str, Any]:
    """Scan Hatchet scheduled workflow files for cron-decorated tasks."""
    scheduled_file = root_path / backend_dir / "app" / "workflows" / "scheduled.py"
    if not scheduled_file.exists():
        return {}

    try:
        return parse_hatchet_scheduled_workflows(scheduled_file.read_text(), scheduled_file, root_path)
    except Exception as e:
        logger.warning(f"Failed to parse Hatchet scheduled workflows: {e}")
        return {}


def _literal_value(node: ast.AST | None) -> Any:
    if node is None:
        return None
    with contextlib.suppress(Exception):
        return ast.literal_eval(node)
    return None


def parse_hatchet_scheduled_workflows(
    content: str,
    source_file: Path | None = None,
    root_path: Path | None = None,
) -> dict[str, Any]:
    """Parse Hatchet @task decorators with on_crons from scheduled workflow modules."""
    tree = ast.parse(content)
    schedule: dict[str, Any] = {}

    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "task":
                continue

            keyword_map = {
                kw.arg: kw.value
                for kw in decorator.keywords
                if kw.arg is not None
            }
            on_crons = _literal_value(keyword_map.get("on_crons"))
            if not on_crons:
                continue

            workflow_name = _literal_value(keyword_map.get("name")) or node.name
            cron_expr = on_crons[0]
            rel_source = (
                str(source_file.relative_to(root_path))
                if source_file and root_path
                else str(source_file) if source_file else None
            )
            schedule[str(workflow_name)] = {
                "task": node.name,
                "workflow_name": workflow_name,
                "scheduler": "hatchet",
                "schedule_crontab": cron_expr,
                "execution_timeout": _literal_value(keyword_map.get("execution_timeout")),
                "retries": _literal_value(keyword_map.get("retries")),
                "source_file": rel_source,
            }

    return schedule


def _parse_celery_file(celery_file: Path, schedule: dict[str, Any]) -> None:
    """Parse a single celery file and update the schedule dict in place."""
    if not celery_file.exists():
        return
    try:
        content = celery_file.read_text()
        parsed = parse_beat_schedule(content)
        schedule.update(parsed)
    except Exception as e:
        logger.warning(f"Failed to parse {celery_file}: {e}")


def scan_beat_schedule_files(root_path: Path, backend_dir: str) -> dict[str, Any]:
    """Scan legacy Celery files for beat_schedule definitions."""
    celery_files = [
        root_path / backend_dir / "app" / "celery_schedules.py",
        root_path / backend_dir / "app" / "celery_app.py",
        root_path / backend_dir / "celery_app.py",
        root_path / backend_dir / "app" / "celery.py",
    ]

    schedule: dict[str, Any] = {}
    for celery_file in celery_files:
        _parse_celery_file(celery_file, schedule)

    return schedule


def _extract_task_names(content: str) -> dict[str, Any]:
    """Extract task names and paths from content using quote patterns."""
    schedule: dict[str, Any] = {}
    patterns = [
        r'"([^"]+)":\s*\{\s*"task":\s*"([^"]+)"',
        r"'([^']+)':\s*\{\s*'task':\s*'([^']+)'",
    ]
    for pattern in patterns:
        for task_name, task_path in re.findall(pattern, content):
            if task_name not in schedule:
                schedule[task_name] = {"task": task_path}
    return schedule


def _extract_schedule_seconds(block: str) -> float | None:
    """Extract numeric schedule value from a task block. Returns None if not found."""
    schedule_match = re.search(r'"schedule":\s*([\d\s\*\+\-\/\.]+)', block)
    if not schedule_match:
        return None
    expr = schedule_match.group(1).strip().rstrip(",")
    if not re.match(r"^[\d\s\*\+\-\/\.]+$", expr):
        return None
    result: float | None = None
    with contextlib.suppress(Exception):
        result = float(eval(expr))
    return result


def _extract_crontab(block: str) -> str | None:
    """Extract crontab schedule from a task block. Returns None if not found."""
    crontab_match = re.search(r'"schedule":\s*crontab\(([^)]+)\)', block)
    if not crontab_match:
        return None
    return crontab_match.group(1)


def _enrich_task_schedule(task_name: str, schedule: dict[str, Any], content: str) -> None:
    """Enrich task entry with schedule details extracted from content."""
    task_block_pattern = rf'"{re.escape(task_name)}":\s*\{{([^}}]+)\}}'
    task_block_match = re.search(task_block_pattern, content, re.DOTALL)
    if not task_block_match:
        return

    block = task_block_match.group(1)

    seconds = _extract_schedule_seconds(block)
    if seconds is not None:
        schedule[task_name]["schedule_seconds"] = seconds

    crontab = _extract_crontab(block)
    if crontab is not None:
        schedule[task_name]["schedule_crontab"] = crontab


def parse_beat_schedule(content: str) -> dict[str, Any]:
    """Parse beat_schedule from file content."""
    schedule = _extract_task_names(content)

    for task_name in list(schedule.keys()):
        _enrich_task_schedule(task_name, schedule, content)

    return schedule


def format_interval(seconds: float) -> str:
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
