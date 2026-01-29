"""File content analysis and basic metrics calculation.

Extracted from files.py for focused responsibility.
"""

from __future__ import annotations

import re
from pathlib import Path

from .file_constants import BLOAT_THRESHOLDS, CLASS_PATTERNS, FUNCTION_PATTERNS, IMPORT_PATTERNS


def read_file_content(file_path: Path) -> tuple[str, int]:
    """Read file content and count lines.

    Args:
        file_path: Path to file to read

    Returns:
        Tuple of (content, line_count)
    """
    content = ""
    lines = 0
    try:
        with file_path.open(encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    except Exception:
        lines = 0
    return content, lines


def calculate_bloat(ext: str, lines: int) -> str | None:
    """Calculate bloat level based on file type and LOC.

    Args:
        ext: File extension (e.g., ".py")
        lines: Number of lines in file

    Returns:
        Bloat level: "critical", "warning", or None
    """
    thresholds = BLOAT_THRESHOLDS.get(ext)
    if not thresholds:
        return None

    warning, critical = thresholds
    if lines >= critical:
        return "critical"
    if lines >= warning:
        return "warning"
    return None


def count_matches(ext: str, patterns: dict[str, re.Pattern[str]], content: str) -> int:
    """Count regex matches for the given extension.

    Args:
        ext: File extension (e.g., ".py")
        patterns: Dict mapping extensions to compiled regex patterns
        content: File content to search

    Returns:
        Number of matches found
    """
    pattern = patterns.get(ext)
    if not pattern or not content:
        return 0
    return len(pattern.findall(content))


def calculate_basic_metrics(ext: str, content: str) -> tuple[int, int, int]:
    """Calculate basic code metrics (functions, classes, imports).

    Args:
        ext: File extension (e.g., ".py")
        content: File content to analyze

    Returns:
        Tuple of (function_count, class_count, import_count)
    """
    function_count = count_matches(ext, FUNCTION_PATTERNS, content)
    class_count = count_matches(ext, CLASS_PATTERNS, content)
    import_count = count_matches(ext, IMPORT_PATTERNS, content)
    return function_count, class_count, import_count
