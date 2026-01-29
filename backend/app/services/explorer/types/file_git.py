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


def get_all_last_commits(root_path: Path) -> dict[str, tuple[int, str, str]]:
    """Get last commit info for ALL files in one git call.

    Uses git log with --name-only to get commit info with filenames.
    Optimized to avoid O(n) git calls.

    Args:
        root_path: Root directory of git repository

    Returns:
        Dict mapping path -> (timestamp, hash, message)
    """
    try:
        # Use null separators for reliable parsing
        # Format: timestamp|hash|subject, then files on separate lines
        result = subprocess.run(
            [
                "git",
                "log",
                "--all",
                "--name-only",
                "--format=%x00%at|%h|%s",  # null byte before each commit
                "--diff-filter=ACMRT",  # Added, Copied, Modified, Renamed, Type-changed
            ],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=60,  # Allow more time for full history
            check=False,
        )

        if result.returncode != 0:
            logger.warning(f"git log for last commits failed: {result.stderr}")
            return {}

        # Parse output to build file -> latest commit map
        # We only keep the FIRST (most recent) commit for each file
        file_commits: dict[str, tuple[int, str, str]] = {}
        current_commit: tuple[int, str, str] | None = None

        for line in result.stdout.split("\n"):
            if line.startswith("\x00"):
                # New commit header
                parts = line[1:].split("|", 2)
                if len(parts) >= 3 and parts[0]:
                    try:
                        current_commit = (int(parts[0]), parts[1], parts[2])
                    except ValueError:
                        current_commit = None
            elif line.strip() and current_commit:
                # File name - only record if we haven't seen this file yet
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

    Optimized to avoid O(n) git calls.

    Args:
        root_path: Root directory of git repository

    Returns:
        Dict mapping path -> commit_count
    """
    try:
        # Get all files changed in commits from last 90 days
        result = subprocess.run(
            [
                "git",
                "log",
                "--since=90 days ago",
                "--name-only",
                "--format=",  # No commit info, just filenames
                "--diff-filter=ACMRT",
            ],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            logger.warning(f"git log for commit counts failed: {result.stderr}")
            return {}

        # Count occurrences of each file
        file_counts: Counter[str] = Counter()
        for line in result.stdout.split("\n"):
            path = line.strip()
            if path:
                file_counts[path] += 1

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
    """Apply git information to an entry's metadata.

    Modifies metadata dict in place.

    Args:
        entry_metadata: Entry metadata dict to update
        path: File path
        last_commit_map: Map of path -> (timestamp, hash, message)
        commit_count_map: Map of path -> commit count
        now: Current datetime
    """
    # Apply last commit info
    if path in last_commit_map:
        timestamp, commit_hash, message = last_commit_map[path]
        commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
        days = (now - commit_time).days
        entry_metadata["last_commit_days"] = days
        entry_metadata["last_commit_hash"] = commit_hash
        entry_metadata["last_commit_message"] = message[:100] if message else ""
        entry_metadata["stale_status"] = "stale" if days >= STALE_THRESHOLD_DAYS else "fresh"
    else:
        entry_metadata["stale_status"] = "unknown"

    # Apply commit count
    entry_metadata["commit_count_90d"] = commit_count_map.get(path, 0)
