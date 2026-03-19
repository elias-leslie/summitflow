"""SummitFlow CLI (st) helpers for task_issue_mapper."""

from __future__ import annotations

import subprocess

from app.services._tim_constants import ST_COMMAND_TIMEOUT

from ..logging_config import get_logger

logger = get_logger(__name__)


def run_st_command(args: list[str]) -> tuple[bool, str]:
    """Run an st CLI command and return (success, output)."""
    try:
        result = subprocess.run(
            ["st", *args],
            capture_output=True,
            text=True,
            timeout=ST_COMMAND_TIMEOUT,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        logger.warning("st command failed: %s", result.stderr)
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("st command timed out")
        return False, "Command timed out"
    except FileNotFoundError:
        logger.error("st CLI not found in PATH")
        return False, "st CLI not found"
