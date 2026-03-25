"""Complexity calculations for files.

Includes Radon-based cyclomatic complexity, comment density, and refactor priority.
Extracted from files.py for focused responsibility.
"""

from __future__ import annotations

from ....logging_config import get_logger
from .file_constants import (
    REFACTOR_HIGH_COMPLEXITY,
    REFACTOR_HIGH_LINES,
    REFACTOR_MEDIUM_COMPLEXITY,
    REFACTOR_MEDIUM_LINES,
)

logger = get_logger(__name__)


def calculate_complexity_score(lines: int, function_count: int, class_count: int) -> float:
    """Calculate heuristic complexity score: lines/100 + funcs/10 + classes/5.

    This is a fallback for non-Python files or when Radon fails.

    Args:
        lines: Number of lines in file
        function_count: Number of functions/methods
        class_count: Number of classes

    Returns:
        Complexity score as a float
    """
    return round(lines / 100 + function_count / 10 + class_count / 5, 2)


def calculate_radon_cc(content: str) -> tuple[float, float] | None:
    """Calculate cyclomatic complexity using Radon.

    Args:
        content: Python source code

    Returns:
        Tuple of (avg_cc, max_cc) or None if analysis fails
    """
    try:
        from radon.complexity import cc_visit

        results = cc_visit(content)
        if not results:
            return (0.0, 0.0)

        complexities = [r.complexity for r in results]
        avg_cc = round(sum(complexities) / len(complexities), 2)
        max_cc = float(max(complexities))
        return (avg_cc, max_cc)
    except (ImportError, SyntaxError, ValueError, TypeError):
        # Radon can fail on syntax errors, encoding issues, etc.
        logger.debug("Radon cyclomatic complexity analysis failed", exc_info=True)
        return None


def calculate_comment_density(content: str) -> float | None:
    """Calculate comment density (comment lines / total lines) using radon.raw.

    Args:
        content: Python source code

    Returns:
        Comment density as percentage (0-100), or None if analysis fails.
        >15% is flagged for review (excessive commenting).
    """
    try:
        from radon.raw import analyze

        result = analyze(content)
        if result.loc == 0:
            return 0.0
        # comments / loc gives ratio, *100 for percentage
        density: float = float(result.comments) / float(result.loc) * 100
        return round(density, 1)
    except (ImportError, SyntaxError, ValueError, TypeError):
        logger.debug("Radon comment density analysis failed", exc_info=True)
        return None


def calculate_refactor_priority(
    complexity_score: float,
    lines: int,
    health_flags: dict[str, bool] | None = None,
    bloat_level: str | None = None,
) -> str:
    """Determine refactor priority based on complexity, lines, health flags, and bloat.

    Args:
        complexity_score: Calculated complexity score
        lines: Number of lines in file
        health_flags: Dict of structural issue flags (e.g. deep_nesting, has_long_functions)
        bloat_level: File bloat level ("ok", "warning", "critical")

    Returns:
        Priority level: "high", "medium", or "none"
    """
    flag_count = len(health_flags) if health_flags else 0

    # High: complexity/LOC thresholds, critical bloat, or 3+ health flags
    if (
        complexity_score > REFACTOR_HIGH_COMPLEXITY
        or lines > REFACTOR_HIGH_LINES
        or bloat_level == "critical"
        or flag_count >= 3
    ):
        return "high"

    # Medium: moderate complexity/LOC, warning bloat, or multiple health flags.
    # A single flag is usually diagnostic context, not enough by itself to
    # create recurring refactor work.
    if (
        complexity_score > REFACTOR_MEDIUM_COMPLEXITY
        or lines > REFACTOR_MEDIUM_LINES
        or bloat_level == "warning"
        or flag_count >= 2
    ):
        return "medium"

    return "none"


def build_refactor_issues(
    complexity_score: float,
    lines: int,
    health_flags: dict[str, bool] | None = None,
    bloat_level: str | None = None,
    magic_strings: dict[str, int] | None = None,
    compat_cruft: dict[str, int] | None = None,
) -> list[str]:
    """Build a list of specific refactoring issues found for a file.

    Returns:
        List of issue identifier strings (e.g. ["high_complexity", "deep_nesting"]).
    """
    issues: list[str] = []

    if complexity_score > REFACTOR_HIGH_COMPLEXITY:
        issues.append("high_complexity")
    elif complexity_score > REFACTOR_MEDIUM_COMPLEXITY:
        issues.append("medium_complexity")

    if lines > REFACTOR_HIGH_LINES:
        issues.append("oversized")
    elif lines > REFACTOR_MEDIUM_LINES:
        issues.append("large_file")

    if bloat_level == "critical":
        issues.append("bloat_critical")
    elif bloat_level == "warning":
        issues.append("bloat_warning")

    if health_flags:
        for flag in sorted(health_flags):
            issues.append(flag)

    if magic_strings:
        issues.append("magic_strings")

    if compat_cruft:
        if compat_cruft.get("stale_todos", 0) > 0:
            issues.append("stale_todos")
        if compat_cruft.get("deprecated_markers", 0) > 0:
            issues.append("deprecated_code")
        if compat_cruft.get("legacy_vars", 0) > 0:
            issues.append("legacy_code")

    return issues


def analyze_python_complexity(
    content: str, lines: int, function_count: int, class_count: int
) -> tuple[float, str, float | None, float | None, float | None]:
    """Analyze complexity for Python files.

    Uses Radon for cyclomatic complexity and comment density when available,
    falls back to heuristic scoring.

    Args:
        content: Python source code
        lines: Number of lines
        function_count: Number of functions
        class_count: Number of classes

    Returns:
        Tuple of (complexity_score, complexity_method, cc_avg, cc_max, comment_density)
    """
    cc_avg: float | None = None
    cc_max: float | None = None
    comment_density: float | None = None
    complexity_method = "heuristic"

    if content:
        # Try Radon CC
        radon_result = calculate_radon_cc(content)
        if radon_result is not None:
            cc_avg, cc_max = radon_result
            complexity_score = cc_avg
            complexity_method = "radon"
        else:
            complexity_score = calculate_complexity_score(lines, function_count, class_count)

        # Calculate comment density
        comment_density = calculate_comment_density(content)
    else:
        complexity_score = calculate_complexity_score(lines, function_count, class_count)

    return complexity_score, complexity_method, cc_avg, cc_max, comment_density
