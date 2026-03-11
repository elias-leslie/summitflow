"""Scheduled Hatchet workflow parsing and retrieval."""

from __future__ import annotations

import ast
import contextlib
from pathlib import Path
from typing import Any, cast

import httpx

from ....logging_config import get_logger

logger = get_logger(__name__)


def _fetch_task_schedule_from_endpoint(endpoint: str) -> dict[str, Any] | None:
    """Fetch task schedule from HTTP endpoint. Returns None on failure."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(endpoint)
            if response.status_code != 200:
                return None
            data = cast(dict[str, Any], response.json())
            schedule = data.get("schedule", data)
            return cast(dict[str, Any], schedule)
    except Exception as e:
        logger.warning("Task schedule fetch failed: %s", e)
        return None


def get_task_schedule(
    project_id: str,
    task_schedule_endpoint: str | None,
    root_path: Path | None,
    backend_dir: str,
) -> dict[str, Any]:
    """Get scheduled workflows from endpoint or by scanning workflow files."""
    if task_schedule_endpoint:
        result = _fetch_task_schedule_from_endpoint(task_schedule_endpoint)
        if result is not None:
            return result

    if not root_path:
        return {}

    return scan_hatchet_schedule_files(root_path, backend_dir)


def scan_hatchet_schedule_files(root_path: Path, backend_dir: str) -> dict[str, Any]:
    """Scan Hatchet workflow modules for cron-decorated tasks."""
    workflows_dir = root_path / backend_dir / "app" / "workflows"
    if not workflows_dir.exists():
        return {}

    workflow_files = sorted(
        path
        for path in workflows_dir.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )

    schedule: dict[str, Any] = {}
    try:
        for workflow_file in workflow_files:
            parsed = parse_hatchet_scheduled_workflows(
                workflow_file.read_text(),
                workflow_file,
                root_path,
            )
            schedule.update(parsed)
        return schedule
    except Exception as e:
        logger.warning("Failed to parse Hatchet scheduled workflows: %s", e)
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
