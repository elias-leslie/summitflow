"""Beat schedule parsing and retrieval."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any, cast

import httpx

from ....logging_config import get_logger

logger = get_logger(__name__)


def get_beat_schedule(
    project_id: str,
    beat_schedule_endpoint: str | None,
    root_path: Path | None,
    backend_dir: str,
) -> dict[str, Any]:
    """Get beat schedule from endpoint or by scanning files."""
    # Try API endpoint first
    if beat_schedule_endpoint:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(beat_schedule_endpoint)
                if response.status_code == 200:
                    data = cast(dict[str, Any], response.json())
                    schedule = data.get("schedule", data)
                    return cast(dict[str, Any], schedule)
        except Exception as e:
            logger.warning(f"Beat schedule fetch failed: {e}")

    # Fallback: scan files
    if not root_path:
        return {}

    return scan_beat_schedule_files(root_path, backend_dir)


def scan_beat_schedule_files(root_path: Path, backend_dir: str) -> dict[str, Any]:
    """Scan Celery files for beat_schedule definition."""
    celery_files = [
        root_path / backend_dir / "app" / "celery_schedules.py",
        root_path / backend_dir / "app" / "celery_app.py",
        root_path / backend_dir / "celery_app.py",
        root_path / backend_dir / "app" / "celery.py",
    ]

    schedule = {}
    for celery_file in celery_files:
        if celery_file and celery_file.exists():
            try:
                content = celery_file.read_text()
                parsed = parse_beat_schedule(content)
                schedule.update(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse {celery_file}: {e}")

    return schedule


def parse_beat_schedule(content: str) -> dict[str, Any]:
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
