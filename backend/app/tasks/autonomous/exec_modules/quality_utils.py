"""Quality checking utilities."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


def find_check_tool() -> str | None:
    """Find the st command, including the common user-local bin fallback.

    Returns:
        Path to st, or None if it is unavailable.
    """
    st_path = shutil.which("st")
    if st_path:
        return st_path
    fallback = Path.home() / "bin" / "st"
    if fallback.exists():
        return str(fallback)
    return None


def find_dev_tools() -> str | None:
    """Compatibility alias for older imports."""
    return find_check_tool()


def parse_error_count(output: str) -> int:
    """Parse error count from st check output.

    Looks for patterns like:
    - "Found N errors" / "N errors"
    - "N failed" / "N failures"
    - Fall back to counting "error:" lines
    """
    output_lower = output.lower()

    patterns = [
        r"found\s+(\d+)\s+error",
        r"(\d+)\s+error",
        r"(\d+)\s+fail",
        r"(\d+)\s+problem",
    ]

    for pattern in patterns:
        match = re.search(pattern, output_lower)
        if match:
            return int(match.group(1))

    error_lines = sum(1 for line in output.split("\n") if "error" in line.lower())
    return max(error_lines, 1 if "error" in output_lower else 0)
