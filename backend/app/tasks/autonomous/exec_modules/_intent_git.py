"""Git utilities for intent_check: modified files and diff summaries."""

from __future__ import annotations

import subprocess

from ....logging_config import get_logger

logger = get_logger(__name__)


def get_modified_files(project_path: str) -> list[str]:
    """Get files modified between merge-base and HEAD."""
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if mb.returncode != 0:
            return []
        diff_range = f"{mb.stdout.strip()}...HEAD"
        result = subprocess.run(
            ["git", "diff", "--name-only", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception as e:
        logger.warning("Failed to get modified files", error=str(e))
        return []


def get_diff_summary(project_path: str) -> str:
    """Get diff stats and commit log for context."""
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        diff_range = f"{mb.stdout.strip()}..HEAD" if mb.returncode == 0 else "HEAD~1..HEAD"
        stat_out = subprocess.run(
            ["git", "diff", "--stat", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        log_out = subprocess.run(
            ["git", "log", "--oneline", diff_range],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        stat = stat_out.stdout.strip() if stat_out.returncode == 0 else ""
        log = log_out.stdout.strip() if log_out.returncode == 0 else ""
        return f"Recent commits:\n{log}\n\nDiff stats:\n{stat}"
    except Exception as e:
        logger.warning("Failed to get diff summary", error=str(e))
        return "(diff unavailable)"


def read_one_file(project_path: str, filepath: str, max_lines: int) -> str | None:
    """Read a single file with line numbers; return None on failure or empty output."""
    try:
        result = subprocess.run(
            ["head", "-n", str(max_lines), filepath],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        numbered = "\n".join(
            f"{i+1}: {line}"
            for i, line in enumerate(result.stdout.split("\n")[:max_lines])
        )
        return f"### {filepath}\n```\n{numbered}\n```"
    except Exception:
        return None


def read_modified_files(
    project_path: str,
    modified_files: list[str],
    max_files: int = 20,
    max_lines_per_file: int = 200,
) -> str:
    """Read modified files for the reviewer to verify citations."""
    if not modified_files:
        return "(no modified files)"
    sections = [
        section
        for filepath in modified_files[:max_files]
        if (section := read_one_file(project_path, filepath, max_lines_per_file)) is not None
    ]
    if not sections:
        return "(files could not be read)"
    return "\n\n".join(sections)
