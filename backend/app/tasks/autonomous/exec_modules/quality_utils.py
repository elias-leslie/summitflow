"""Quality checking utilities."""

from __future__ import annotations

import re
import shutil


def find_dev_tools() -> str | None:
    """Find dt command or dev-tools.sh script.

    Returns path to dt (if in PATH) or None if not found.
    """
    dt_path = shutil.which("dt")
    if dt_path:
        return dt_path
    return None


def parse_error_count(output: str) -> int:
    """Parse error count from dt --check output.

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
