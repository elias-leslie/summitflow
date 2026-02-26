"""Git operations for file scanning.

Batch git operations optimized for scanning many files efficiently.
Extracted from files.py for focused responsibility.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from .file_constants import STALE_THRESHOLD_DAYS

logger = get_logger(__name__)


def _run_git_log(root_path: Path, args: list[str], timeout: int) -> str | None:
    """Run git log and return stdout, or None on failure."""
    result = subprocess.run(
        ["git", "log", *args],
        cwd=str(root_path),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(f"git log failed: {result.stderr}")
        return None
    return result.stdout


def _parse_commit_header(line: str) -> tuple[int, str, str] | None:
    """Parse a null-prefixed commit header line into (timestamp, hash, message)."""
    parts = line[1:].split("|", 2)
    if len(parts) < 3 or not parts[0]:
        return None
    try:
        return (int(parts[0]), parts[1], parts[2])
    except ValueError:
        return None


def get_all_last_commits(root_path: Path) -> dict[str, tuple[int, str, str]]:
    """Get last commit info for ALL files in one git call.

    Returns dict mapping path -> (timestamp, hash, message).
    """
    try:
        stdout = _run_git_log(
            root_path,
            [
                "--all",
                "--name-only",
                "--format=%x00%at|%h|%s",
                "--diff-filter=ACMRT",
            ],
            timeout=60,
        )
        if stdout is None:
            return {}

        file_commits: dict[str, tuple[int, str, str]] = {}
        current_commit: tuple[int, str, str] | None = None

        for line in stdout.split("\n"):
            if line.startswith("\x00"):
                current_commit = _parse_commit_header(line)
            elif line.strip() and current_commit:
                file_path = line.strip()
                if file_path not in file_commits:
                    file_commits[file_path] = current_commit

        logger.info(f"Batch git: got last commit info for {len(file_commits)} files")
        return file_commits

    except subprocess.TimeoutExpired:
        logger.warning("git log for last commits timed out")
        return {}
    except OSError as e:
        logger.warning(f"git log for last commits failed: {e}")
        return {}


def get_all_commit_counts_90d(root_path: Path) -> dict[str, int]:
    """Get 90-day commit counts for ALL files in one git call.

    Returns dict mapping path -> commit_count.
    """
    try:
        stdout = _run_git_log(
            root_path,
            [
                "--since=90 days ago",
                "--name-only",
                "--format=",
                "--diff-filter=ACMRT",
            ],
            timeout=30,
        )
        if stdout is None:
            return {}

        file_counts: Counter[str] = Counter(
            path for line in stdout.split("\n") if (path := line.strip())
        )
        logger.info(f"Batch git: got 90-day commit counts for {len(file_counts)} files")
        return dict(file_counts)

    except subprocess.TimeoutExpired:
        logger.warning("git log for commit counts timed out")
        return {}
    except OSError as e:
        logger.warning(f"git log for commit counts failed: {e}")
        return {}


def apply_git_info_to_entry(
    entry_metadata: dict[str, Any],
    path: str,
    last_commit_map: dict[str, tuple[int, str, str]],
    commit_count_map: dict[str, int],
    now: datetime,
) -> None:
    """Apply git information to an entry's metadata dict in place."""
    if path not in last_commit_map:
        entry_metadata["stale_status"] = "unknown"
        entry_metadata["commit_count_90d"] = commit_count_map.get(path, 0)
        return

    timestamp, commit_hash, message = last_commit_map[path]
    commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
    days = (now - commit_time).days
    entry_metadata["last_commit_days"] = days
    entry_metadata["last_commit_hash"] = commit_hash
    entry_metadata["last_commit_message"] = message[:100] if message else ""
    entry_metadata["stale_status"] = "stale" if days >= STALE_THRESHOLD_DAYS else "fresh"
    entry_metadata["commit_count_90d"] = commit_count_map.get(path, 0)
